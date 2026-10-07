"""Import checked annex tables from the original public PISTE response."""
import hashlib
import html
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .legal_tables import tables
from .model import cents, norm


def articles(value):
    if isinstance(value, dict):
        if value.get('content') and value.get('id', '').startswith('JORFARTI'):
            yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from articles(child)
    elif isinstance(value, list):
        for child in value:
            yield from articles(child)


def iso_date(timestamp):
    return datetime.fromtimestamp(timestamp/1000, timezone.utc).date().isoformat()


def parse(document, source, mappings):
    if document['cid'] != 'JORFTEXT000049180270':
        raise ValueError('Cet adaptateur doit être vérifié avant extension à un autre acte')
    annexes = [(a, t) for a in articles(document) for t in tables(a['content'])]
    assert len(annexes) == 1, 'Une annexe attendue'
    article, table = annexes[0]
    assert len(table[0]) == 4 and 'annulees' in norm(table[0][2]) and 'annules' in norm(table[0][3])
    records = []; checks = []; mission = None; total = None; programmes = set()
    for line, row in enumerate(table[1:], 2):
        assert len(row) == 4, (line, row)
        label, code, ae, cp = row; amounts = [cents(ae), cents(cp)]
        if norm(label).startswith('donttitre2'):
            continue
        if norm(label) == 'totaux':
            total = amounts; continue
        if not code:
            mission = {'label':label, 'amounts':amounts, 'rows':[]}; checks.append(mission); continue
        assert re.fullmatch(r'\d{3}', code) and code not in programmes
        programmes.add(code)
        assert mission is not None and code in mappings, ('Programme non rattaché', code)
        mapping = mappings[code]
        assert norm(mapping['mission_label']) == norm(mission['label']), ('Mission différente', code, mapping, mission['label'])
        # The act supplies the programme label and the annual reference supplies its hierarchy.
        mission['rows'].append(amounts)
        for measure, amount in zip(('AE','CP'), amounts):
            assert amount is None or amount >= 0
            records.append(dict(event_id=document['cid']+'/'+code+'/'+measure, act_id=document['cid'], act_title=document['title'],
                event_type='ANNULATION', year=2024, measure=measure, budget=mapping['budget'], mission=mapping['mission'],
                mission_label=mission['label'], program=code, program_label=label, action='', subaction='', amount_cents=amount,
                sign=-1, act_date=iso_date(document['dateTexte']), publication_date=iso_date(document['dateParution']),
                effective_date=None, legal_status='published', origin_year=2024, destination_year=None, transfer_id=None,
                source=source, article=article['cid'], line=line, field=f'Annexe tableau 1 ligne {line} · {measure} annulés',
                url='https://www.legifrance.gouv.fr/jorf/article_jo/'+article['cid']))
    assert total is not None
    validations=[]
    for scope, expected, values in [(c['label'],c['amounts'],c['rows']) for c in checks]+[('Ensemble du décret',total,[[r['amount_cents'] for r in records if r['program']==code] for code in sorted(programmes)])]:
        for column, measure in enumerate(('AE','CP')):
            # Empty programme cells stay absent; the published aggregate is checked independently.
            reported=[row[column] for row in values if row[column] is not None]
            actual=sum(reported) if reported else None
            assert expected[column] == actual, (scope,measure,expected[column],actual)
            validations.append(dict(scope=scope,measure=measure,expected_cents=expected[column],actual_cents=actual))
    return records, validations


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,default=Path('/data'));parser.add_argument('--incoming',type=Path,required=True)
    args=parser.parse_args();data=args.data;incoming=args.incoming
    original=incoming/'JORFTEXT000049180270.json';document=json.loads(original.read_text(encoding='utf-8'))
    raw=original.read_bytes();digest=hashlib.sha256(raw).hexdigest();sid=hashlib.sha256(('events/'+document['cid']+'.html').encode()).hexdigest()[:20]
    with sqlite3.connect((data/'derived/budget.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        mappings={}
        for row in db.execute('select distinct budget,mission,mission_label,program from facts where year=2024'):
            r=dict(row);code=r.pop('program')
            if code in mappings:
                assert (r['budget'],r['mission']) == (mappings[code]['budget'],mappings[code]['mission']), ('Rattachement ambigu',code)
            mappings[code]=r
    rows,checks=parse(document,sid,mappings)
    target=data/'derived/events.sqlite'
    if target.exists():
        raise ValueError('Registre déjà présent ; mise à jour versionnée nécessaire, base conservée')
    folder=data/'public/legal/events';folder.mkdir(parents=True,exist_ok=True)
    paths=[]
    for suffix,content in [('json',raw),('html',('<!doctype html><html lang="fr"><meta charset="utf-8"><title>'+html.escape(document['title'])+'</title><body><h1>'+html.escape(document['title'])+'</h1>'+''.join('<section id="'+a['cid']+'"><h2>Article '+html.escape(a.get('num') or 'Annexe')+'</h2>'+a['content']+'</section>' for a in articles(document))+'</body></html>').encode('utf-8'))]:
        path=folder/(document['cid']+'.'+suffix)
        if path.exists():assert path.read_bytes()==content
        else:path.write_bytes(content);path.chmod(0o644)
        identifier=sid if suffix=='html' else hashlib.sha256(('events/'+path.name).encode()).hexdigest()[:20]
        paths.append(dict(id=identifier,path=path.relative_to(data).as_posix(),title=document['title']+(' · réponse API originale' if suffix=='json' else ' · annexe chiffrée'),format=suffix,years_title=['2024'],bytes=len(content),sha256=hashlib.sha256(content).hexdigest(),url='https://www.legifrance.gouv.fr/jorf/id/'+document['cid'],imported=suffix=='html',checked_at=datetime.now(timezone.utc).isoformat(),license='Licence non renseignée dans cet inventaire'))
    staged=data/'derived/events.staged.sqlite';assert not staged.exists()
    db=sqlite3.connect(staged)
    definitions=','.join(k+(' INTEGER' if k in ('year','amount_cents','sign','origin_year','destination_year','line') else ' TEXT')+(' PRIMARY KEY' if k=='event_id' else '') for k in rows[0])
    db.execute('CREATE TABLE events('+definitions+')')
    db.executemany('INSERT INTO events VALUES('+','.join('?' for k in rows[0])+')',[tuple(r.values()) for r in rows])
    db.execute('CREATE INDEX event_scope ON events(year,budget,measure,mission,program)')
    db.execute('CREATE TABLE sources(id TEXT PRIMARY KEY,data TEXT)')
    db.executemany('INSERT INTO sources VALUES(?,?)',[(s['id'],json.dumps(s,ensure_ascii=False)) for s in paths])
    meta=dict(version=digest,built_at=datetime.now(timezone.utc).isoformat(),coverage='Décret d’annulation 2024-124 du 21 février 2024 uniquement. Registre partiel ; autres actes, gels et dégels à intégrer.',checks=checks,event_count=len(rows),act_count=1)
    db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)');db.executemany('INSERT INTO meta VALUES(?,?)',[(k,json.dumps(v,ensure_ascii=False)) for k,v in meta.items()])
    db.commit();assert db.execute('pragma integrity_check').fetchone()[0]=='ok';db.close();staged.chmod(0o644);staged.replace(target)
    audit=data/'imports/developpement-evenements';audit.mkdir(exist_ok=True);(audit/'receipt.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2));shutil.copyfile(original,audit/original.name)
    print(json.dumps({k:v for k,v in meta.items() if k!='checks'},ensure_ascii=False));print('Rapprochements',len(checks))


if __name__=='__main__':main()

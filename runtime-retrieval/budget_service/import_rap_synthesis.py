"""Import same-exercise execution totals from RAP syntheses with hierarchical checks.

The 2021 HT2 columns are deliberately not imported: anomalies are documented.
Only published AE/CP TOTAL columns are used, never divided by an inferred factor.
"""
import collections,hashlib,json,os,sqlite3,shutil
from pathlib import Path
from datetime import datetime,timezone
import xlrd
from .model import cents,code,norm

DATA=Path(os.environ.get('BUDGET_DATA_DIR','/data'))
SOURCES={2021:'c3eda3a052cdbd475b5a',2022:'1f6bb8b3cc177a733a99'}


def parse(record,year):
    path=DATA/record['path']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256']
    sheet=xlrd.open_workbook(str(path)).sheet_by_name('Crédits')
    assert sheet.ncols==22
    assert str(year) in str(sheet.cell_value(2,18)) and str(year) in str(sheet.cell_value(2,21))
    nodes=[];current={};bykey={}
    for i in range(3,sheet.nrows):
        row=sheet.row_values(i);kind=norm(row[0]);budget=row[1];key=code(row[2]);label=str(row[3]).strip()
        if kind not in ('budget','mission','programme','action','sousaction'):continue
        if kind in ('programme','action','sousaction') and 'mission' not in current:
            assert cents(row[18]) is None and cents(row[21]) is None, ('Unmapped monetary row',year,i+1)
            continue
        if kind=='budget':current={};parent=None;ident=(budget,)
        elif kind=='mission':parent=current['budget'];ident=(budget,key)
        elif kind=='programme':parent=current['mission'];ident=parent['identity']+(key,)
        elif kind=='action':parent=current['programme'];ident=parent['identity']+(code(key.split('-')[-1],2),)
        else:parent=current['action'];ident=parent['identity']+(code(key.split('-')[-1],2),)
        node=dict(identity=ident,kind=kind,label=label,line=i+1,children=[],amounts={'AE':cents(row[18]),'CP':cents(row[21])})
        if parent:parent['children'].append(node)
        nodes.append(node);bykey[ident]=node;current[kind]=node
    records=[];checks=[];fallbacks=[];availability=[]
    def leaves(node,measure):
        amount=node['amounts'][measure];children=node['children']
        if not children:return [node] if amount is not None else []
        child_amounts=[ch['amounts'][measure] for ch in children]
        # Missing children are not assumed to be zeros. Preserve the published parent.
        if amount is None:return []
        if all(x is not None for x in child_amounts) and sum(child_amounts)==amount:
            return [leaf for ch in children for leaf in leaves(ch,measure)]
        fallbacks.append(dict(year=year,measure=measure,node='/'.join(node['identity']),line=node['line'],reason='Détail absent ou somme des enfants différente du total publié ; total parent conservé.',difference_cents=None if any(x is None for x in child_amounts) else sum(child_amounts)-amount))
        return [node]
    for node in nodes:
        if node['kind'] in ('programme','action','sousaction'):
            for measure in ('AE','CP'):
                availability.append((year,'EXEC',measure,node['identity'][0],'/'.join(node['identity'][1:]),'published' if node['amounts'][measure] is not None else 'not_reported',record['id'],node['line']))
        if node['kind']!='programme':continue
        budget,mission,program=node['identity'];mission_label=bykey[(budget,mission)]['label']
        for measure,col in [('AE','S'),('CP','V')]:
            chosen=leaves(node,measure);actual=sum(n['amounts'][measure] for n in chosen)
            expected=node['amounts'][measure]
            checks.append(dict(year=year,budget=budget,mission=mission,program=program,measure=measure,expected_cents=expected,actual_cents=actual if chosen else None,ok=actual==expected if expected is not None else not chosen))
            assert checks[-1]['ok'],checks[-1]
            for n in chosen:
                parts=n['identity'];a=parts[3] if len(parts)>3 else '';s=parts[4] if len(parts)>4 else ''
                al=bykey[parts[:4]]['label'] if a else '';sl=n['label'] if s else ''
                records.append((year,'EXEC',measure,budget,mission,mission_label,program,node['label'],a,al,s,sl,'','',n['amounts'][measure],record['id'],n['line'],f'Crédits!{col}{n["line"]} · Consommation {year} · {measure} total',0))
    # A budget/mission total check is independent of the selected leaf grain.
    for node in nodes:
        if node['kind'] not in ('budget','mission'):continue
        for measure in ('AE','CP'):
            values=[r[14] for r in records if r[2]==measure and (r[3],r[4])[:len(node['identity'])]==node['identity']]
            expected=node['amounts'][measure]
            actual=sum(values) if values else None
            checks.append(dict(year=year,node='/'.join(node['identity']),measure=measure,expected_cents=expected,actual_cents=actual,ok=actual==expected))
    return records,checks,fallbacks,availability


def main():
    source=DATA/'derived/budget.sqlite';db=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    rows=[];checks=[];fallbacks=[];availability=[];source_records=[]
    for year,sid in SOURCES.items():
        assert db.execute('select count(*) from facts where year=? and stage=?',(year,'EXEC')).fetchone()[0]==0,'Existing execution preserved'
        rec=json.loads(db.execute('select data from sources where id=?',(sid,)).fetchone()[0]);source_records.append(rec)
        r,c,f,a=parse(rec,year);rows+=r;checks+=c;fallbacks+=f;availability+=a
    out=DATA/'imports/developpement-rap-2021-2022';out.mkdir(exist_ok=True)
    report=dict(facts=len(rows),checks=len(checks),failures=[c for c in checks if not c['ok']],fallbacks=fallbacks,by_year=dict(collections.Counter(r[0] for r in rows)),sources=[r['id'] for r in source_records])
    (out/'validation.json').write_text(json.dumps(dict(report,checks_detail=checks),ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='fallbacks'},ensure_ascii=False))
    if os.environ.get('BUDGET_APPLY_RAP')!='1':return
    assert not report['failures'],'Source reconciliation requires review'
    backup=out/'budget-before.sqlite'
    assert not backup.exists(),'Existing import backup preserved'
    with sqlite3.connect(backup) as dest:db.backup(dest)
    staged=DATA/'derived/budget.rap-staged.sqlite';assert not staged.exists()
    new=sqlite3.connect(staged);db.backup(new)
    old_count=db.execute('select count(*) from facts').fetchone()[0]
    # No existing fact is modified; new rows occupy unused year/stage partitions.
    new.executemany('insert into facts values ('+','.join('?'*19)+')',rows)
    new.execute('create table if not exists published_nodes(year integer,stage text,measure text,budget text,path text,availability text,source text,line integer,primary key(year,stage,measure,budget,path,source))')
    new.executemany('insert into published_nodes values (?,?,?,?,?,?,?,?)',availability)
    new.execute('create table if not exists reconciled_totals(year integer,stage text,measure text,budget text,path text,cents integer,source text,primary key(year,stage,measure,budget,path))')
    for c in checks:
        if c.get('node') and c['ok'] and c['expected_cents'] is not None:
            bits=c['node'].split('/')
            new.execute('insert into reconciled_totals values (?,?,?,?,?,?,?)',(c['year'],'EXEC',c['measure'],bits[0],'/'.join(bits[1:]),c['expected_cents'],SOURCES[c['year']]))
    now=datetime.now(timezone.utc).isoformat()
    for rec in source_records:
        rec.update(imported=True,numeric_import=True,numeric_import_scope='Consommation du même exercice ; colonnes AE/CP total uniquement ; détail hiérarchique rapproché',source_precision='Montants publiés arrondis au centime après lecture XLS')
        new.execute('update sources set data=? where id=?',(json.dumps(rec,ensure_ascii=False),rec['id']))
    meta={k:json.loads(v) for k,v in new.execute('select key,value from meta')}
    updated=dict(built_at=now,fact_count=old_count+len(rows),data_version=hashlib.sha256(json.dumps([meta['built_at'],[(r['sha256'],r['id']) for r in source_records]],sort_keys=True).encode()).hexdigest(),imported_source_count=meta['imported_source_count']+2)
    for k,v in updated.items():new.execute('insert or replace into meta values (?,?)',(k,json.dumps(v)))
    def old_digest(conn):
        digest=hashlib.sha256()
        for row in conn.execute('select * from facts where rowid<=? order by rowid',(old_count,)):
            digest.update(json.dumps(tuple(row),ensure_ascii=False,separators=(',',':')).encode());digest.update(b'\n')
        return digest.hexdigest()
    assert old_digest(db)==old_digest(new),'Existing observations changed'
    new.commit();assert new.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert new.execute('select count(*) from facts').fetchone()[0]==old_count+len(rows)
    new.close();db.close();staged.chmod(0o644);staged.replace(source)
    (out/'receipt.json').write_text(json.dumps(dict(report,updated=updated,original_facts_preserved=old_count),ensure_ascii=False,indent=2))
    normal=DATA/'derived/normalization-report.json'
    previous=json.loads(normal.read_text());shutil.copyfile(normal,out/'normalization-report-before.json');previous.update(updated);normal.write_text(json.dumps(previous,ensure_ascii=False,indent=2))
    print('Applied',updated)

if __name__=='__main__':main()

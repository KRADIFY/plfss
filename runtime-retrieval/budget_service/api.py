"""Read-only queries over the derived budget database."""
import csv
import io
import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from .model import STAGES, constant_cents, norm, safe_csv
from . import topics, exports, events, action_details
from .comparisons import compare
from . import evolution

DATA = Path(os.environ.get('BUDGET_DATA_DIR', '/data'))
MISSION_LINEAGES = {
    (2026, 'M26985a5788'): ('MB', 'Monde combattant, mémoire et liens avec la Nation',
                            'La mission « Monde combattant, mémoire et liens avec la Nation » en LFI 2026 est rattachée à la série historique « Anciens combattants » : les programmes 158 et 169 sont inchangés.'),
}

def connect():
    db = sqlite3.connect((DATA/'derived/budget.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    db.execute('PRAGMA temp_store=MEMORY')
    db.row_factory=sqlite3.Row
    return db

def metadata(db):
    meta={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM meta')}
    if meta.get('rap_investigation',{}).get('sources_added'):
        meta['catalogue_updated_at']=max(meta.get('catalogue_updated_at',''),meta['rap_investigation']['checked_at'])
    try:
        audit=json.loads((DATA/'derived/data-audit.json').read_text(encoding='utf-8'))
        from .data_signature import signature
        if (audit.get('success') and audit.get('built_at')==meta['built_at']
                and audit.get('data_signature')==signature(DATA/'derived/budget.sqlite')):
            meta['reconciliation']={k:v for k,v in audit.items() if k!='checks'}
    except (FileNotFoundError,ValueError): pass
    return meta

def node_path(row):
    return '/'.join(str(row[k]) for k in ('mission','program','action','subaction') if row[k])

def within(path, parent): return not parent or path == parent or path.startswith(parent+'/')

def valid_path(path):
    if not re.fullmatch(r'[A-Za-z0-9]{1,16}(?:/\d{2,3}){0,3}',path): raise ValueError('Périmètre invalide')
    return path

def parameters(query):
    one=lambda k,d: query.get(k,[d])[0]
    start,end=int(one('start','2023')),int(one('end','2025'))
    if not 2017<=start<=end<=2026: raise ValueError('Choisir des années de 2017 à 2026')
    measure=one('measure','CP'); budget=one('budget','BG')
    if measure not in ('AE','CP') or budget not in ('BG','BA','CAS','CCF'): raise ValueError('Type de crédits invalide')
    scope=one('scope','')
    if scope: valid_path(scope)
    excluded=json.loads(one('exclude','[]'))
    if not isinstance(excluded,list) or len(excluded)>100: raise ValueError('Liste d’exclusions invalide')
    excluded=[valid_path(p) for p in excluded if isinstance(p,str)]
    base=int(one('base','2025'))
    if not 2017<=base<=2025: raise ValueError('Année de référence IPC indisponible')
    topic=one('topic',''); topic_mode=one('topic_mode','only')
    if topic not in ('','maprimerenov') or topic_mode not in ('only','without'): raise ValueError('Dossier invalide')
    denominator=one('denominator','LFI')
    if denominator not in ('LFI','OUVERT'): raise ValueError('Dénominateur invalide')
    return dict(denominator=denominator,start=start,end=end,measure=measure,budget=budget,scope=scope,exclude=excluded,constant=one('constant','0')=='1',base=base,topic=topic,topic_mode=topic_mode)

def selected_records(db, p):
    records = [dict(r) for r in db.execute('SELECT * FROM facts WHERE year BETWEEN ? AND ? AND measure=? AND budget=?',
            (p['start'],p['end'],p['measure'],p['budget']))]
    # Reviewed PDF observations store their physical page in the source line.
    for row in records:
        lineage=MISSION_LINEAGES.get((row['year'],row['mission']))
        if lineage:
            row['mission'],row['mission_label'],row['_mission_lineage_note']=lineage
        if row['year']==2026 and row['stage'] in ('PLF','FDC_PREVU') and 'PAP p.' in row['field']:
            row['page']=row['line']
    return action_details.attach(records, db)

def cell(records, scope, year, stage, p, indices, stage_records=None, expected_programs=None):
    relevant=stage_records if stage_records is not None else [r for r in records if r['year']==year and r['stage']==stage]
    values=[]; unresolved=False; removed=0; excluded_programs=set()
    review_notes=[r.get('_detail_note','') for r in action_details.review_rows(relevant,scope,p['exclude'])]
    for r in action_details.resolve(relevant, scope, p['exclude']):
        path=node_path(r)
        if r.get('_detail_review_required') and (within(scope,path) or within(path,scope)):
            review_notes.append(r.get('_detail_note',''))
        if not within(path,scope):
            if scope and within(scope,path) and not any(within(scope,e) for e in p['exclude']): unresolved=True
            continue
        if action_details.is_excluded(r, p['exclude']):
            removed+=1
            if r.get('_fully_excluded'): excluded_programs.add(r['program'])
            continue
        if action_details.unresolved_exclusion(r, p['exclude']): unresolved=True; continue
        values.append(r)
    if unresolved:
        reason='Ventilation insuffisante pour isoler ce périmètre ou appliquer les exclusions.'
        if review_notes:reason='Détail non utilisé : désaccord entre publications. '+' '.join(dict.fromkeys(review_notes))
        return {'value':None,'nominal':None,'status':'detail_unavailable','count':0,'reason':reason}
    if not values:
        return {'value':0 if removed else None,'nominal':0 if removed else None,'status':'excluded' if removed else 'missing','count':0,'reason':'Périmètre entièrement exclu.' if removed else 'Aucune valeur importée à ce niveau pour cette étape et cette année.'}
    amount=sum(r['cents'] for r in values)
    converted=constant_cents(amount,year,p['base'],indices) if p['constant'] else amount
    expected=expected_programs if expected_programs is not None else {r['program'] for r in records if r['year']==year and r['stage'] in ('PLF','LFI','EXEC') and within(node_path(r),scope) and not any(within(node_path(r),e) for e in p['exclude'])}
    actual={r['program'] for r in values}
    missing=sorted(expected-actual-excluded_programs)
    status='partial' if missing else 'ok'
    missing_programs=[]
    reason=''
    if missing:
        labels={r['program']:r['program_label'].lstrip(': ').strip() for r in records
                if r['program'] in missing and r.get('program_label')}
        missing_programs=[dict(code=code,label=labels.get(code,'')) for code in missing]
        if len(missing)==1:
            named=f'{missing[0]} (« {labels[missing[0]]} »)' if labels.get(missing[0]) else missing[0]
            reason=(f'Le programme budgétaire {named} n’a pas de montant renseigné pour cette étape et cette année. '
                    'Le chiffre affiché additionne seulement les autres programmes renseignés : il est partiel. '
                    'Un montant manquant ne signifie pas 0 €.')
        else:
            reason=(f'Ce chiffre est partiel : {len(missing)} programmes budgétaires n’ont pas de montant renseigné '
                    'pour cette étape et cette année. Seuls les autres programmes sont additionnés. '
                    'Un montant manquant ne signifie pas 0 €.')
    coverage_reason=reason
    sources, detail_note, extra = action_details.annotations(values)
    if detail_note: reason = (reason + ' ' + detail_note).strip()
    nominal_status=status
    if converted is None: status='inflation_missing';reason=(reason+' Indice annuel d’inflation indisponible.').strip()
    return {'approximate':any(r.get('approximate',0) for r in values),'value':converted/100 if converted is not None else None,'nominal':amount/100,'nominal_cents':amount,'status':status,'nominal_status':nominal_status,'reason':reason,'coverage_reason':coverage_reason,'missing_programs':missing_programs,'detail_note':detail_note,
            **extra, 'count':len(values),'sources':sources,
            'grain':'sous-action' if all(r['subaction'] for r in values) else 'action' if all(r['action'] for r in values) else 'programme'}

def explorer(db, p):
    records=selected_records(db,p); meta=metadata(db)
    indices={int(k):v for k,v in meta['indices'].items()}
    has_rollups=db.execute("select 1 from sqlite_master where type='table' and name='reconciled_totals'").fetchone()
    rollups={(r['year'],r['stage'],r['measure'],r['budget'],r['path']):r['cents'] for r in db.execute('select * from reconciled_totals')} if has_rollups else {}
    years=list(range(p['start'],p['end']+1))
    depth=len(p['scope'].split('/')) if p['scope'] else 0
    groups={}; names={}
    thematic=bool(p.get('topic'))
    group_records=topics.navigation(p) if thematic and p['topic_mode']=='only' else list(action_details.navigation(records))
    for r in sorted(group_records,key=lambda r:r['year']):
        path=node_path(r); bits=path.split('/')
        for i in range(len(bits)):
            names['/'.join(bits[:i+1])]=r[('mission_label','program_label','action_label','subaction_label')[i]]
        if not within(path,p['scope']) or len(bits)<=depth: continue
        key='/'.join(bits[:depth+1]); groups[key]=names[key]
    def series(scope):
        annual_records=defaultdict(list)
        for r in records:
            path=node_path(r)
            if within(path,scope) or within(scope,path): annual_records[r['year']].append(r)
        result=[]
        for year in years:
            annual={'year':year}
            by_stage=defaultdict(list)
            for r in annual_records[year]: by_stage[r['stage']].append(r)
            expected={r['program'] for r in annual_records[year] if r['stage'] in ('PLF','LFI','EXEC') and within(node_path(r),scope) and not any(within(node_path(r),e) for e in p['exclude'])}
            for stage in STAGES:
                c=cell(annual_records[year],scope,year,stage,p,indices,by_stage[stage],expected)
                # Mission and budget totals independently reconciled to the official summary.
                # This does not fill a missing programme/action value with zero.
                if (meta.get('reconciliation') and p['budget']=='BG' and year in (2024,2025)
                    and stage in ('EXEC','OUVERT') and not p['exclude'] and '/' not in scope
                    and c.get('nominal_status',c['status'])=='partial'):
                    c['nominal_status']='ok'
                    if c['status']!='inflation_missing': c['status']='ok';c['reason']='Total rapproché de l’état officiel par mission.'
                checked_total=rollups.get((year,stage,p['measure'],p['budget'],scope))
                if checked_total is not None and not p['exclude'] and c.get('nominal_cents')==checked_total and c.get('nominal_status',c['status']) in ('ok','partial'):
                    c['nominal_status']='ok'
                    if c['status']!='inflation_missing': c.update(status='ok',reason='Total rapproché du total officiel du même exercice.')
                if thematic: c=topics.calculate(annual_records[year],c,scope,year,stage,p,indices)
                annual[stage]=c
            annual['comparisons']=compare(annual,p.get('denominator','LFI'))
            result.append(annual)
        evolution.attach(result,indices)
        return result
    rows=[]
    for key,label in sorted(groups.items(),key=lambda kv:norm(kv[1])):
        rows.append({'id':key,'label':label,'code':key.split('/')[-1], 'depth':depth,
                     'excluded':any(within(key,e) for e in p['exclude']),
                     'has_children':any(within(node_path(r),key) and node_path(r)!=key for r in group_records),
                     'series':series(key)})
    result={'parameters':p,'years':years,'stages':STAGES,'rows':rows,'totals':series(p['scope']),
            'scope_label':names.get(p['scope'],'Ensemble des missions'),'breadcrumbs':[{'id':'/'.join(p['scope'].split('/')[:i+1]),'label':names.get('/'.join(p['scope'].split('/')[:i+1]),'?')} for i in range(depth)],
            'exclusions':[{'id':e,'label':names.get(e,e)} for e in p['exclude']],
            'notes':['Les séries suivent la nomenclature publiée chaque année. Les changements de périmètre ne sont pas retraités.',
                     'Les mouvements et FdC/AdP sont déjà inclus dans les crédits ouverts. Le solde non consommé ne mesure pas le gel.',
                     'Les ajustements nets de crédits reprennent l’agrégat officiel. La colonne source LFR peut réunir des lois de finances et des décrets d’annulation ; les autres mouvements, reports et FdC sont affichés séparément.'],
            'built_at':meta['built_at']}
    if thematic:
        result['topic']=topics.description(p)
        prefix='MaPrimeRénov’' if p['topic_mode']=='only' else 'Hors MaPrimeRénov’ identifié'
        result['scope_label']=prefix+' · '+result['scope_label']
        result['notes']+=result['topic']['limitations']
    result['calculation_version']=evolution.VERSION
    result['data_version']=meta.get('data_version') or meta['built_at']
    result['action_detail_version']=action_details.registry()[1]+':'+action_details.POLICY_VERSION
    if any(r.get('_action_details') and (within(node_path(r),p['scope']) or within(p['scope'],node_path(r))) for r in records):
        result['notes'].append(action_details.NOTE)
    result['notes'] += list(dict.fromkeys(r['_mission_lineage_note'] for r in records if r.get('_mission_lineage_note')))
    result['catalogue_updated_at']=meta.get('catalogue_updated_at',meta['built_at'])
    result['inflation']={'source':meta.get('inflation_source'),'indices':meta['indices'],'base':p['base'],'method':'Montant annuel × IPC de référence ÷ IPC annuel ; arrondi au centime.'}
    import hashlib
    result['topic_version']=hashlib.sha256((Path(__file__).parent/'data/maprimerenov.json').read_bytes()).hexdigest()
    result['selection_id']=exports.fingerprint(result)
    return result

def bootstrap(db):
    meta=metadata(db)
    coverage=[dict(r) for r in db.execute('SELECT year,stage,budget,COUNT(*) records,COUNT(DISTINCT program) programs,MIN(CASE WHEN action="" THEN 1 WHEN subaction="" THEN 2 ELSE 3 END) grain FROM facts GROUP BY year,stage,budget ORDER BY year,stage')]
    meta['application_version']='0.3'
    meta['source_count']+=len(topics.sources())+len(events.sources(DATA))
    meta['topic_source_count']=len(topics.sources())
    return {'meta':meta,'coverage':coverage,'stages':STAGES,
            'documents':db.execute("SELECT count(*) FROM sources WHERE json_extract(data,'$.format')='pdf'").fetchone()[0]+len(topics.sources())}

def source(db, identifier):
    if not re.fullmatch(r'[a-f0-9]{20}',identifier): raise ValueError('Source invalide')
    row=db.execute('SELECT data FROM sources WHERE id=?',(identifier,)).fetchone()
    if not row:
        match=next((s for s in topics.sources()+events.sources(DATA) if s['id']==identifier),None)
        if match: return match
        raise LookupError('Source introuvable')
    return json.loads(row['data'])

def provenance(db,p,year,stage,scope):
    if stage not in STAGES or not p['start']<=year<=p['end']: raise ValueError('Étape ou année invalide')
    if scope: valid_path(scope)
    if p.get('topic'): return topics.provenance(db,p,year,stage,scope)
    records=selected_records(db,p)
    relevant=[r for r in records if r['year']==year and r['stage']==stage]
    values=[r for r in action_details.resolve(relevant,scope,p['exclude']) if within(node_path(r),scope)
            and not action_details.is_excluded(r,p['exclude']) and not action_details.unresolved_exclusion(r,p['exclude'])]
    # Keep the conflicting publications inspectable even when no subtraction is allowed.
    review_parents=list(action_details.review_rows(relevant,scope,p['exclude']))
    if review_parents:
        # A blocked branch must keep its proof even when another programme has values.
        represented={action_details.path_of(r) for r in values}
        for r in review_parents:
            if action_details.path_of(r) not in represented:
                values.append(r)
                values += r.get('_detail_parent_rows',[])[1:]
    _,note,extra=action_details.annotations(values)
    citations=extra.get('citations',[])+[r['_detail_comparison'] for r in values if r.get('_detail_comparison')]
    values=action_details.proofs(values)
    sources={r['source']:source(db,r['source']) for r in values}
    for citation in citations:
        if citation['source'] not in sources:sources[citation['source']]=source(db,citation['source'])
    indices = {int(k):v for k,v in metadata(db)['indices'].items()} if p['constant'] else {}
    result = cell(records, scope, year, stage, p, indices)
    for identifier in result.get('sources', []):
        if identifier not in sources:sources[identifier]=source(db,identifier)
    from . import data_quality
    explanation = data_quality.general(result, p, year, stage, scope) if result['value'] is None or result['status']=='partial' else None
    differences = data_quality.source_discrepancies(values, metadata(db).get('issues', []))
    if differences:
        explanation = explanation or data_quality.general(result, p, year, stage, scope)
        if result['status'] != 'partial' and not result.get('source_disagreements'):
            explanation['title'] = 'Écart dans le document source'
            explanation['summary'] = ('Le montant affiché reprend le chiffre publié. Une ligne du document '
                                      'ne correspond pas exactement à l’addition des mouvements indiqués ; '
                                      'l’écart est détaillé ci-dessous.')
        explanation['details'].extend(differences)
    if result.get('source_disagreements'):
        explanation = explanation or data_quality.general(result, p, year, stage, scope)
        explanation['title'] = 'Alerte : écart entre les sources'
        explanation['details'].extend(w['summary'] for w in result['source_disagreements']
                                      if w['summary'] not in explanation['summary'])
        explanation['references'].extend(dict(source=c['source'], page=c['page'],
                                              label='Total du RAP' if i==0 else 'Total de référence')
                                         for w in result['source_disagreements'] for i,c in enumerate(w['citations']))
    return {'year':year,'stage':STAGES[stage],'count':len(values),'sources':list(sources.values()),
            'rows':values[:300],'truncated':len(values)>300,'note':note,'citations':citations,'explanation':explanation}

def documents(db,query):
    search=norm(query.get('q',[''])[0])[:200]
    year=query.get('year',[''])[0]; fmt=query.get('format',['pdf'])[0]
    items=[]
    entries=[json.loads(row[0]) for row in db.execute('SELECT data FROM sources')]+topics.sources()+events.sources(DATA)
    for r in entries:
        if fmt and r.get('format')!=fmt: continue
        hay=r.get('title','')+' '+r.get('dataset_title','')+' '+r.get('path','')
        if search and search not in norm(hay): continue
        if year and year not in hay and year not in r.get('years_title',[]): continue
        items.append(r)
    return {'count':len(items),'items':sorted(items,key=lambda r:r['title'])}

def export_csv(data, db=None):
    out=io.StringIO(newline=''); writer=csv.writer(out,delimiter=';')
    p=data['parameters']; urls={}
    if db:
        urls={r['id']:json.loads(r['data']).get('url','') for r in db.execute('SELECT id,data FROM sources')}
    urls.update({s['id']:s['url'] for s in topics.sources()})
    thematic=bool(p.get('topic'))
    writer.writerow(['Type de ligne','Budget','Périmètre','Code','Année','Crédits','Étape','Montant EUR','Statut','Précision source','Monnaie','Exclusions','Sources officielles','Identifiants sources','Motif de disponibilité','Version des données','Empreinte de sélection']+
                    (['Dossier','Traitement du dossier','Montant retiré EUR courants','Périmètre du dispositif','Note de disponibilité'] if thematic else [])+
                    ['Variation annuelle courante %','Statut variation courante','Variation annuelle réelle %','Statut variation réelle','Variation réelle depuis début %','Statut variation depuis début','Année de référence depuis début','Sources des variations','Motifs des variations','Repères sources'])
    entries=[dict(id=p['scope'],label=data['scope_label'],series=data['totals'],total=True)]+data['rows']
    for row in entries:
        for annual in row['series']:
            for stage in STAGES:
                c=annual[stage]
                writer.writerow(['Total du périmètre' if row.get('total') else 'Détail (ne pas additionner au total)',p['budget'],safe_csv(row['label']),row['id'],annual['year'],p['measure'],STAGES[stage],
                    str(c['value']).replace('.',',') if c['value'] is not None else '',c['status'],
                    c.get('precision') or ('Au moins une valeur arrondie en notation scientifique' if c.get('approximate') else 'Précision du fichier source'),
                    f'Euros {p["base"]}' if p['constant'] else 'Euros courants',safe_csv(' / '.join(e['label'] for e in data['exclusions'])),
                    exports.citation_urls(c,urls), ' '.join(c.get('sources',[])),safe_csv(c.get('reason','')),data.get('data_version',data.get('built_at','')),data.get('selection_id','')]+
                    (['MaPrimeRénov’','Isoler le dispositif' if p['topic_mode']=='only' else 'Retirer le dispositif identifié',
                      str(c.get('topic_subtracted_nominal','')).replace('.',','),safe_csv(data['topic']['perimeter']),safe_csv(c.get('reason',''))] if thematic else [])+list(exports.evolution_csv(annual,stage,p['start']))+[safe_csv(exports.source_locators(c))])
    return ('\ufeff'+out.getvalue()).encode('utf-8')

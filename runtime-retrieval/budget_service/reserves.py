"""RAP reserve tables, separately sourced and never added to consumption."""
import hashlib,json
from functools import lru_cache
from pathlib import Path
from .model import constant_cents
from . import topics, rap_quality

@lru_cache(maxsize=1)
def registry():
    root=Path(__file__).parent/'data'
    data=json.loads((root/'reserves-ecologie.json').read_text(encoding='utf-8'))
    extension=root/'reserves-national.json'
    if extension.exists():
        national=json.loads(extension.read_text(encoding='utf-8'))
        data['records']+=national['records']
        known={source['id'] for source in data['sources']}
        data['sources']+=[source for source in national['sources'] if source['id'] not in known]
        data['checks']+=national.get('checks',[])
        data['notes']+=national.get('notes',[])
        data['coverage']=data['coverage']+' '+national['coverage']
        data['version']=hashlib.sha256((data['version']+'|'+hashlib.sha256(extension.read_bytes()).hexdigest()).encode()).hexdigest()        historical = root/'reserves-historique-2017-2022.json'
        if historical.exists():
            extra=json.loads(historical.read_text(encoding='utf-8'))
            existing={(r['year'],r['mission'],r['program'],r['measure']) for r in data['records']}
            data['records'] += [r for r in extra.get('records',[]) if (r['year'],r['mission'],r['program'],r['measure']) not in existing]
            known={source['id'] for source in data['sources']}
            data['sources'] += [source for source in extra.get('sources',[]) if source['id'] not in known]
            data['notes'] += extra.get('notes',[])
            data['coverage']=data['coverage']+' '+extra.get('coverage','')
            data['version']=hashlib.sha256((data['version']+'|'+hashlib.sha256(historical.read_bytes()).hexdigest()).encode()).hexdigest()
    # Preserve the earlier manually reviewed rows when the same gap was audited again.
    known_rows={(r['year'],r['mission'],r['program'],r['measure']) for r in data['records']+data.get('missing_tables',[])}
    data.setdefault('missing_tables',[]).extend(r for r in rap_quality.reserve_placeholders()
        if (r['year'],r['mission'],r['program'],r['measure']) not in known_rows)
    coverage,coverage_version=rap_quality.registry()
    known_sources={s['id'] for s in data['sources']}
    data['sources'] += [s for s in coverage['sources'] if s['id'] not in known_sources]
    data['version']=hashlib.sha256((data['version']+'|'+coverage_version).encode()).hexdigest()
    return data


def within(path,parent):
    return not parent or path==parent or path.startswith(parent+'/')


def query(p,meta):
    reg=registry();items=[]
    indices={int(k):v for k,v in meta['indices'].items()}
    carriers={x['path'] for x in topics.registry()['carriers']}
    rows=sorted(reg['records']+reg.get('missing_tables',[]),key=lambda r:(r['year'],int(r['program']),r['measure']))
    for row in rows:
        if row['budget']!=p['budget'] or row['measure']!=p['measure'] or not p['start']<=row['year']<=p['end']:continue
        path=row['mission']+'/'+row['program']
        if not (within(path,p['scope']) or within(p['scope'],path)):continue
        if any(within(path,e) or within(p['scope'],e) for e in p['exclude']):continue
        reason='';unavailable_status='detail_unavailable'
        if not within(path,p['scope']) or any(within(e,path) for e in p['exclude']):
            reason='La réserve est publiée au niveau du programme ; la ventilation nécessaire à cette sélection n’est pas établie.'
        if p.get('topic'):
            only=p.get('topic_mode','only')=='only'
            if only and path not in carriers:continue
            if only and row['year']<2020:
                reason='MaPrimeRénov’ a été créé en 2020. Le tableau antérieur concerne le programme entier.'
                unavailable_status='not_applicable'
            elif path in carriers and row['year']>=2020:
                reason='La part MaPrimeRénov’ dans cette réserve n’est pas isolée. Impossible de l’attribuer au dispositif ou de la retirer du programme.'
        cells={}
        for field in reg['field_labels']:
            original=row['cells'].get(field)
            cents=original['total_cents'] if original else None
            adjusted=constant_cents(cents,row['year'],p['base'],indices) if p['constant'] and cents is not None else cents
            status=unavailable_status if reason else row.get('coverage_status','table_unavailable') if row.get('table_unavailable') else 'not_reported' if cents is None else 'inflation_missing' if adjusted is None else 'published'
            cells[field]=dict(value=adjusted/100 if status=='published' else None,
                nominal=cents/100 if cents is not None and not reason else None,
                nominal_cents=cents if not reason else None,
                status=status,reason=reason or (row['note'] if row.get('table_unavailable') else 'Ligne absente du tableau.' if cents is None else 'Indice annuel indisponible.' if adjusted is None else ''),
                source_cells=original)
            if status!='published' or 'difference' in row['numeric_validation']:
                cells[field]['explanation']=rap_quality.explanation(p,row,'reserves',status,
                    cells[field]['reason'] or row['note'],field)
        items.append(dict(year=row['year'],program=row['program'],program_label=row['program_label'],path=path,
            measure=row['measure'],page=row['page'],source=row['source'],source_sha256=row['source_sha256'],
            cells=cells,note=row['note'],remaining_label=row['remaining_label'],
            table_available=not row.get('table_unavailable',False),context_pages=row.get('context_pages',[row['page']]),
            numeric_validation=row['numeric_validation'],checks=row.get('checks',[])))
    ids={r['source'] for r in items}
    missing_years=[year for year in range(p['start'],p['end']+1) if year not in {r['year'] for r in items if r['table_available']}]
    return dict(parameters=p,items=items,count=len(items),coverage=reg['coverage'],notes=reg['notes'],version=reg['version'],
        year_explanations=rap_quality.year_explanations(p,missing_years,'reserves'),
        programmes_without_table_count=sum(not r['table_available'] for r in items),
        integrated_table_count=sum(r['table_available'] for r in items),
        coverage_by_year=[dict(year=year,
            integrated_programmes=sorted({r['program'] for r in items if r['year']==year and r['table_available']}),
            programmes_without_table=sorted({r['program'] for r in items if r['year']==year and not r['table_available']}))
            for year in range(p['start'],p['end']+1) if any(r['year']==year for r in items)],
        sources=[s for s in reg['sources'] if s['id'] in ids],
        years_without_integrated_table=missing_years,
        inflation={'indices':meta['indices'],'source':meta.get('inflation_source'),'base':p['base']},
        selection_id=hashlib.sha256(json.dumps({'parameters':p,'reserves':reg['version'],'inflation':meta['indices']},sort_keys=True).encode()).hexdigest())

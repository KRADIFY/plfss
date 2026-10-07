"""Documented policy subsets, kept separate from the additive budget fact table."""
import json
from functools import lru_cache
from pathlib import Path
from .model import constant_cents


@lru_cache(maxsize=1)
def registry():
    return json.loads((Path(__file__).parent/'data/maprimerenov.json').read_text(encoding='utf-8'))


def within(path, parent):
    return not parent or path == parent or path.startswith(parent+'/')


def path_of(row):
    return '/'.join(row[k] for k in ('mission', 'program', 'action', 'subaction') if row[k])


def sources():
    return registry()['sources']


def navigation(p):
    """Programmes are navigation anchors, never an estimate of the policy amount."""
    if p['budget'] != 'BG':
        return []
    anchors = [dict(year=p['end'], mission=x['path'].split('/')[0],
                 program=x['path'].split('/')[1], action='', subaction='',
                 mission_label=x['mission_label'], program_label=x['label'],
                 action_label='', subaction_label='') for x in registry()['carriers']]
    return anchors + [r for r in registry()['facts'] if r['action'] and p['start']<=r['year']<=p['end'] and r['measure']==p['measure']]


def rows_for(p, year, stage, scope):
    return [r.copy() for r in registry()['facts']
            if r['year'] == year and r['stage'] == stage and r['measure'] == p['measure']
            and within(path_of(r), scope)
            and not any(within(path_of(r), e) for e in p['exclude'])]


def unavailable(reason, status='topic_unavailable'):
    return dict(value=None, nominal=None, nominal_cents=None, status=status,
                count=0, reason=reason)


def target_paths(scope, excluded, year, stage, measure):
    published=[r for r in registry()['facts'] if (r['year'],r['stage'],r['measure'])==(year,stage,measure)]
    paths=set()
    for carrier in registry()['carriers']:
        rows=[r for r in published if within(path_of(r),carrier['path'])]
        paths.update(path_of(r) for r in rows) if rows else paths.add(carrier['path'])
    return sorted(path for path in paths if (within(path,scope) or within(scope,path))
                  and not any(within(path,e) or within(scope,e) for e in excluded))


def perimeter_evidence(scope, excluded, year, stage, measure):
    return [r for r in registry().get('perimeter_evidence', [])
            if r['year'] == year and stage in r['stages'] and measure in r['measures']
            and (within(r['path'], scope) or within(scope, r['path']))
            and not any(within(r['path'], e) or within(scope, e) for e in excluded)]


def row_citations(rows):
    citations = [c for r in rows for c in
                 [dict(source=r['source'], page=r['page'])] + r.get('references', [])]
    return list({(c['source'], c['page']): dict(source=c['source'], page=c['page'])
                 for c in citations}.values())


def evidence_citations(evidence):
    return list({(c['source'], c['page']): dict(source=c['source'], page=c['page'])
                 for r in evidence for c in r['references']}.values())


def subset(scope, year, stage, p, indices):
    if year < 2020:
        return unavailable('MaPrimeRénov’ a été créé en 2020. Le CITE antérieur est un autre dispositif.', 'not_applicable')
    if p['budget'] != 'BG':
        return unavailable('Ce dossier documente les crédits du budget général de l’État.', 'not_applicable')
    paths = target_paths(scope, p['exclude'], year, stage, p['measure'])
    if not paths:
        return dict(value=0, nominal=0, nominal_cents=0, status='excluded', count=0,
                    reason='Aucun crédit du périmètre documenté MaPrimeRénov’ dans cette sélection.', sources=[])
    evidence = perimeter_evidence(scope, p['exclude'], year, stage, p['measure'])
    # Documentary perimeter evidence is not a monetary observation of zero.
    active_paths = [path for path in paths if not any(within(path, e['path']) for e in evidence)]
    coverage = [r for r in registry().get('coverage', [])
                if (r['year'], r['stage'], r['measure']) == (year, stage, p['measure'])]
    covered = {path for r in coverage for path in r['paths']}
    if any((scope and within(scope, path) and scope != path)
           or any(within(e, path) and e != path for e in p['exclude']) for path in active_paths):
        return unavailable('La ventilation MaPrimeRénov’ n’est pas vérifiée à ce niveau pour cette année et cette étape.', 'detail_unavailable')
    if any(not any(within(path, carrier) for carrier in covered) for path in active_paths):
        result = unavailable('Montant propre à MaPrimeRénov’ non isolé pour tout le périmètre demandé, cette année et cette étape. Aucun montant de programme ou de l’Anah ne le remplace.')
        if not evidence:
            return result
        citations = evidence_citations(evidence)
        return dict(result, evidence=evidence, citations=citations,
                    sources=sorted({c['source'] for c in citations}))
    rows = rows_for(p, year, stage, scope)
    # A partial import must not silently fill another carrier with zero.
    amount = sum(r['cents'] for r in rows)
    converted = constant_cents(amount, year, p['base'], indices) if p['constant'] else amount
    citations = row_citations(rows) + evidence_citations(evidence)
    reason = ' '.join(e['explanation'] for e in evidence) if evidence and not rows else registry()['perimeter']
    return dict(value=converted/100 if converted is not None else None,
                nominal=amount/100, nominal_cents=amount,
                status='ok' if converted is not None else 'inflation_missing', nominal_status='ok',
                reason=reason if converted is not None else 'Indice annuel d’inflation indisponible.',
                count=len(rows), sources=sorted({c['source'] for c in citations}),
                citations=citations, evidence=evidence,
                approximate=any(r.get('approximate') for r in rows),
                precision=('Précision source : '+', '.join(sorted({r['precision'] for r in rows}))) if rows else 'Périmètre documenté ; aucun zéro monétaire importé',
                grain='dispositif au sein de l’action' if rows and all(r['action'] for r in rows) else 'dispositif au sein du programme')


def calculate(records, base, scope, year, stage, p, indices):
    from .action_details import effective_exclusions, resolve
    p=dict(p,exclude=effective_exclusions([r for r in records if r['year']==year and r['stage']==stage],scope,p['exclude']))
    if p.get('topic_mode', 'only') == 'only':
        return subset(scope, year, stage, p, indices)
    if year < 2020 or p['budget'] != 'BG' or not target_paths(scope, p['exclude'], year, stage, p['measure']):
        return base
    part = subset(scope, year, stage, dict(p, constant=False), indices)
    if part['value'] is None:
        return part
    if base['value'] is None and not (base['status']=='inflation_missing' and base.get('nominal_cents') is not None):
        return dict(base, reason=base['reason']+' Le total de départ est nécessaire pour retirer MaPrimeRénov’.')
    components = rows_for(p, year, stage, scope)
    for component in components:
        parent = path_of(component) if scope.count('/')>1 else '/'.join(path_of(component).split('/')[:2])
        backing = [r for r in resolve(records,parent,p['exclude']) if r['year'] == year and r['stage'] == stage
                   and within(path_of(r), parent) and within(path_of(r), scope)
                   and not any(within(path_of(r), e) for e in p['exclude'])]
        if component['cents'] > 0 and (not backing or sum(r['cents'] for r in backing) < component['cents']):
            return unavailable('Le total importé du programme ne permet pas de rapprocher ce montant MaPrimeRénov’. Retrait suspendu.', 'detail_unavailable')
    amount = base['nominal_cents'] - part['nominal_cents']
    if amount < 0:
        return unavailable('Le montant à retirer dépasse le total disponible. Retrait suspendu.', 'detail_unavailable')
    converted = constant_cents(amount, year, p['base'], indices) if p['constant'] else amount
    return dict(base, value=converted/100 if converted is not None else None,
                nominal=amount/100, nominal_cents=amount,
                status=base['status'] if converted is not None else 'inflation_missing',
                count=base['count']+part['count'],
                sources=sorted(set(base.get('sources', [])) | set(part.get('sources', []))),
                citations=list({(r['source'],r['page']):r for r in base.get('citations',[])+part.get('citations',[])}.values()),
                approximate=base.get('approximate', False) or part.get('approximate', False),
                precision=part.get('precision', ''),
                topic_subtracted_nominal=part['nominal'],
                evidence=part.get('evidence', []),
                reason=(base.get('reason', '')+' '+(' '.join(e['explanation'] for e in part.get('evidence', [])) if part.get('evidence') and not components else 'Retrait des seuls crédits MaPrimeRénov’ identifiés dans les programmes sélectionnés, avant correction de l’inflation.')).strip())


def description(p):
    r = registry()
    return dict(id=r['id'], title=r['title'], mode=p['topic_mode'], perimeter=r['perimeter'],
                availability_note=r['availability_note'],
                limitations=r['limitations'], updated_at=r['updated_at'],
                timeline=[x for x in r['timeline'] if p['start'] <= x['year'] <= p['end']],
                sources=r['sources'], references=r['references'])


def provenance(db, p, year, stage, scope):
    from . import api
    from . import data_quality
    from .action_details import effective_exclusions
    records = api.selected_records(db, p)
    p=dict(p,exclude=effective_exclusions([r for r in records if r['year']==year and r['stage']==stage],scope,p['exclude']))
    plain = dict(p, topic='')
    indices = {int(k): v for k, v in api.metadata(db)['indices'].items()}
    base = api.cell(records, scope, year, stage, plain, indices)
    result = calculate(records, base, scope, year, stage, p, indices)
    explanation = data_quality.mpr(result, p, year, stage, scope)
    calculation = dict(base_nominal=base.get('nominal') if p['topic_mode']=='without' else None,
                       subtracted_nominal=result.get('topic_subtracted_nominal', 0 if p['topic_mode']=='without' and result.get('value') is not None else None),
                       result_nominal=result.get('nominal'), displayed_value=result.get('value'),
                       constant=p['constant'], base_year=p['base'], status=result['status'],
                       scope=scope, measure=p['measure'])
    evidence = result.get('evidence', [])
    citations = result.get('citations', []) + explanation.get('references', [])
    if result['value'] is None:
        return dict(year=year, stage=api.STAGES[stage], count=0, rows=[],
                    sources=[api.source(db, s) for s in sorted(set(result.get('sources', [])) | {c['source'] for c in citations})],
                    truncated=False, note=result['reason'], topic_mode=p['topic_mode'],
                    calculation=calculation, evidence=evidence, citations=citations, explanation=explanation)
    component_rows = rows_for(p, year, stage, scope) if p['budget'] == 'BG' else []
    if p['topic_mode'] == 'without':
        data = api.provenance(db, plain, year, stage, scope)
        rows = [dict(r, operation=r.get('operation','base')) for r in data['rows']]
        rows += [dict(r, cents=-r['cents'], operation='subtract') for r in component_rows]
        count = data['count'] + len(component_rows)
        source_map = {r['id']: r for r in data['sources']}
    else:
        rows = [dict(r, operation='subset') for r in component_rows]
        count = len(rows)
        source_map = {}
    for row in component_rows:
        source_map[row['source']] = api.source(db, row['source'])
    for citation in citations:
        source_map[citation['source']] = api.source(db, citation['source'])
    return dict(year=year, stage=api.STAGES[stage], count=count, rows=rows,
                sources=list(source_map.values()), truncated=count>len(rows),
                note=result.get('reason', registry()['perimeter']), topic_mode=p['topic_mode'],
                calculation=calculation, evidence=evidence, citations=citations, explanation=explanation)

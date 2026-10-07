"""Dated RAP recapitulations, kept separate from the published-acts register."""
import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from .model import constant_cents
from . import topics, rap_quality

KINDS = {
    'RATTACHEMENT_FDC': 'Rattachement de fonds de concours',
    'RATTACHEMENT_ADP': 'Rattachement d’attributions de produits',
    'REPORT_FDC': 'Report de fonds de concours',
    'REPORT_AENE': 'Report d’autorisations d’engagement non engagées',
    'REPORT_TRANCHES_FONCTIONNELLES': 'Report de tranches fonctionnelles',
    'REPORT_GENERAL': 'Report de crédits généraux',
    'TRANSFERT': 'Transfert de crédits',
    'ANNULATION': 'Annulation de crédits',
    'ANNULATION_FDC_ADP': 'Annulation de fonds de concours ou d’attributions de produits',
    'VIREMENT': 'Virement de crédits',
    'REPARTITION': 'Répartition pour mesures générales',
    'DEPENSES_ACCIDENTELLES': 'Dépenses accidentelles',
    'DECRET_AVANCE': 'Décret d’avance',
    'LOI_FINANCES': 'Loi de finances',
    'OUVERTURE_ARTICLE_21': 'Ouverture de crédits par arrêté (article 21)',
    'TOTAL': 'Total annuel net ouvertures et annulations',
}
DATA = Path(__file__).parent / 'data'


@lru_cache(maxsize=1)
def registry():
    return json.loads((DATA / 'mouvements-rap-p174.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def national_registry():
    path = DATA / 'mouvements-rap-national.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'registries': [], 'coverage': '', 'limits': []}


@lru_cache(maxsize=1)
def historical_registry():
    path = DATA / 'mouvements-rap-historique.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'registries': [], 'coverage': '', 'limits': []}


@lru_cache(maxsize=1)
def historical_detail_registry():
    path = DATA / 'mouvements-rap-historique-detail.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'registries': [], 'coverage': '', 'limits': []}


@lru_cache(maxsize=1)
def other_budget_historical_registry():
    path = DATA / 'mouvements-rap-autres-budgets-historique.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'registries': [], 'coverage': '', 'limits': []}


def _registry_keys(registry):
    scope = registry['scope']
    return {(year, scope['budget'], scope['mission'], scope['program']) for year in scope['years']}


def within(path, parent):
    return not parent or path == parent or path.startswith(parent + '/')


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=8)
def _file_fingerprint(name):
    path=DATA/name
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _unique_registries(registries):
    # Precedence follows input order. Remove duplicate years without mutating
    # cached source registries or dropping distinct years in a mixed register.
    seen, result = set(), []
    for reg in registries:
        scope = reg['scope']
        years = [year for year in scope['years']
                 if (year,scope['budget'],scope['mission'],scope['program']) not in seen]
        if not years:
            continue
        if years != scope['years']:
            reg = dict(reg, scope=dict(scope, years=years))
            for field in ('sources','items','evidence_rows','table_totals','reconciliations','annual_adjustments'):
                if field in reg:
                    reg[field] = [row for row in reg[field] if row['year'] in years]
        result.append(reg)
        seen.update(_registry_keys(reg))
    return result


def _historical_details():
    return _unique_registries(historical_detail_registry().get('registries',[])
                             + other_budget_historical_registry().get('registries',[]))


def historical_coverage_counts():
    detailed=_historical_details()
    keys=set().union(*(_registry_keys(r) for r in detailed)) if detailed else set()
    return len(detailed),sum(not (_registry_keys(r)&keys) for r in historical_registry().get('registries',[]))


def historical_validation_counts():
    detailed=_historical_details()
    complete=sum(r.get('source_validation',{}).get('independent_annual_reference_check') is not False for r in detailed)
    return dict(detailed_reconciled=complete,detailed_without_annual_reference=len(detailed)-complete,annual_only=historical_coverage_counts()[1])


def page_result(result,offset=0,limit=500):
    if type(offset) is not int or type(limit) is not int or offset<0 or not 1<=limit<=500:
        raise ValueError('Invalid movement page')
    page={k:v for k,v in result.items() if k not in ('proofs','evidence_rows','table_totals')}
    page['items']=result['items'][offset:offset+limit]
    end=min(result['count'],offset+len(page['items']))
    page.update(offset=offset,limit=limit,displayed_count=end,has_more=end<result['count'],
                next_offset=end if end<result['count'] else None,view='summary')
    return page


def _source_checks(db, records):
    """Re-read the catalogue on every request; never trust an ID without its hash."""
    expected = {}
    for row in records:
        source = row.get('source', row.get('id'))
        expected.setdefault(source, set()).add(row.get('sha256'))
    checks, sources = [], []
    for source, hashes in sorted(expected.items()):
        result = db.execute('SELECT data FROM sources WHERE id=?', (source,)).fetchone()
        try:
            record = json.loads(result[0]) if result else {}
        except (ValueError, TypeError):
            record = {}
        wanted = next(iter(hashes)) if len(hashes) == 1 else None
        valid = bool(isinstance(wanted, str) and re.fullmatch(r'[0-9a-f]{64}', wanted)
                     and record.get('sha256') == wanted and re.fullmatch(r'[0-9a-f]{20}', source or ''))
        checks.append(dict(source=source, verified=valid, expected_sha256=wanted,
                           catalog_sha256=record.get('sha256'),
                           reason='' if valid else 'Empreinte du RAP non confirmée dans le catalogue local.'))
        if valid:
            sources.append(dict(id=source, sha256=wanted, title=record.get('title', ''),
                                url=record.get('url'), download_url='/api/download/' + source))
    return checks, sources


def _all_registries():
    detailed = _historical_details()
    detailed_keys = set().union(*(_registry_keys(reg) for reg in detailed)) if detailed else set()
    annual = [reg for reg in historical_registry().get('registries', [])
              if not (_registry_keys(reg) & detailed_keys)]
    return _unique_registries(
        [registry()]
        + national_registry().get('registries', [])
        + detailed
        + annual
    )


def query(db, p, meta, include_evidence=True):
    selected = []
    carriers = {c['path'] for c in topics.registry()['carriers']}
    for reg in _all_registries():
        scope = reg['scope']
        path = scope['mission'] + '/' + scope['program']
        overlaps = within(path, p['scope']) or within(p['scope'], path)
        excluded = any(within(path, item) or within(p['scope'], item) for item in p['exclude'])
        if p.get('topic') and p.get('topic_mode','only')=='only' and path not in carriers:
            continue
        if p['budget'] == scope['budget'] and overlaps and not excluded:
            selected.append((reg, path))
    raw_items, raw_proofs, raw_tables, raw_reconciliations, source_rows, raw_adjustments = [], [], [], [], [], []
    scope_by_key = {}
    for reg, path in selected:
        scope = reg['scope']
        for year in scope['years']:
            scope_by_key[(year, scope['mission'], scope['program'])] = scope
        in_years = lambda row: p['start'] <= row['year'] <= p['end']
        raw_items.extend(row for row in reg['items'] if in_years(row) and row['measure'] == p['measure'])
        raw_proofs.extend(row for row in reg['evidence_rows'] if in_years(row))
        raw_tables.extend(row for row in reg.get('table_totals', []) if in_years(row))
        raw_reconciliations.extend(dict(row,program=scope['program'],budget=scope['budget'],mission=scope['mission']) for row in reg.get('reconciliations', []) if in_years(row) and row['measure'] == p['measure'])
        raw_adjustments.extend(row for row in reg.get('annual_adjustments',[]) if in_years(row) and row['measure']==p['measure'])
        source_rows.extend(row for row in reg['sources'] if in_years(row))
    missing_programmes = rap_quality.gaps(p,'movements')
    checks, sources = _source_checks(db, source_rows + raw_items + raw_proofs + raw_tables + raw_reconciliations + raw_adjustments + missing_programmes)
    verified = {check['source'] for check in checks if check['verified']}
    indices = {int(year): value for year, value in meta['indices'].items()}
    partial_checks={(r['year'],r['source'],r['measure']):r for r in raw_reconciliations if r['status']=='annual_reference_unavailable'}
    items = []
    for original in sorted(raw_items, key=lambda row: (row['year'], row['date'], row['mission'], row['program'], row['id'])):
        row = copy.deepcopy(original)
        path = row['mission'] + '/' + row['program']
        reason = ''
        if not within(path, p['scope']) or any(within(excluded, path) for excluded in p['exclude']):
            reason = 'Le RAP publie ces mouvements au niveau du programme ; leur ventilation par action ou sous-action n’est pas établie.'
        if p.get('topic') and path in carriers and row['year'] >= 2020:
            reason = 'La part MaPrimeRénov’ dans ces mouvements n’est pas isolée. Impossible de l’attribuer au dispositif ou de la retirer du programme.'
        not_applicable = bool(p.get('topic') and p.get('topic_mode','only')=='only' and row['year']<2020)
        if not_applicable:
            reason = 'MaPrimeRénov’ a été créé en 2020. Le tableau antérieur concerne le programme entier.'
        is_verified = row['source'] in verified
        magnitude = row['amount_cents']
        if magnitude is not None and (type(magnitude) is not int or magnitude < 0 or row['sign'] not in (-1, 1)):
            raise ValueError('Montant ou signe RAP invalide')
        signed = row['sign'] * magnitude if magnitude is not None else None
        adjusted = constant_cents(signed, row['year'], p['base'], indices) if p['constant'] and signed is not None else signed
        status = ('source_unverified' if not is_verified else 'not_applicable' if not_applicable else 'detail_unavailable' if reason
                  else 'not_reported' if signed is None else 'inflation_missing' if adjusted is None else 'published')
        available_nominal = is_verified and not reason and signed is not None
        scope = scope_by_key[(row['year'], row['mission'], row['program'])]
        row.update(path=path, kind_label=KINDS.get(row['kind'], row['kind']),
                   mission_label=scope.get('mission_label', ''), program_label=scope.get('program_label', ''),
                   title_label='Titre 2' if row.get('title') == '2' else 'Autres titres',
                   source_verified=is_verified, value=adjusted / 100 if status == 'published' else None,
                   nominal=signed / 100 if available_nominal else None,
                   nominal_cents=signed if available_nominal else None,
                   value_cents=adjusted if status == 'published' else None, status=status,
                   reason=('Empreinte du RAP non confirmée dans le catalogue local.' if not is_verified else reason
                           or ('Montant non renseigné dans le RAP.' if signed is None else 'Indice annuel indisponible.' if adjusted is None else '')),
                   citation={'url': '/api/download/' + row['source'] + '#page=' + str(row['page']),
                             'label': 'RAP ' + str(row['year']) + ', p. ' + str(row['page'])} if is_verified else None,
                   linked_act_relation='same_operation' if row.get('linked_act_id') else None)
        partial=partial_checks.get((row['year'],row['source'],row['measure']))
        if partial and is_verified:
            row.update(annual_reconciliation_status='annual_reference_unavailable',annual_reconciliation_note=partial['note'])
        if not is_verified:
            row['amount_cents'] = None
        if status != 'published':
            row['explanation'] = rap_quality.explanation(p,row,'movements',status,row['reason'])
        items.append(row)
    verified_proofs=[row for row in raw_proofs if row['source'] in verified]
    verified_tables=[row for row in raw_tables if row['source'] in verified]
    proofs = copy.deepcopy(verified_proofs) if include_evidence else []
    tables = copy.deepcopy(verified_tables) if include_evidence else []
    adjustments=[]
    for original in raw_adjustments:
        if original['source'] not in verified:
            continue
        row=copy.deepcopy(original)
        path=row['mission']+'/'+row['program']
        applicable=within(path,p['scope']) and not any(within(excluded,path) for excluded in p['exclude'])
        if p.get('topic') and path in carriers:
            applicable=False
        nominal=row['amount_cents'] if applicable else None
        adjusted=constant_cents(nominal,row['year'],p['base'],indices) if p['constant'] and nominal is not None else nominal
        scope=scope_by_key[(row['year'],row['mission'],row['program'])]
        row.update(path=path,source_verified=True,applies_to_selection=applicable,
                   program_label=scope.get('program_label',''),mission_label=scope.get('mission_label',''),
                   reason='Montant annuel publié pour le programme entier ; ventilation par action indisponible.' if not applicable else 'Indice annuel indisponible.' if adjusted is None else '',
                   nominal_cents=nominal,value_cents=adjusted,
                   status='detail_unavailable' if not applicable else 'inflation_missing' if adjusted is None else 'published',
                   citation={'url':'/api/download/'+row['source']+'#page='+str(row['page']),
                             'label':'Annexe 2 du PLR '+str(row['year'])+', p. '+str(row['page'])})
        adjustments.append(row)
    def reconciliation_sources_verified(row):
        references=row.get('reference_proofs',[])
        dependencies=[a for a in raw_adjustments if a['id'] in row.get('annual_adjustment_ids',[])]
        return row['source'] in verified and all(p['source'] in verified for p in references+dependencies)
    reconciliations = copy.deepcopy([row for row in raw_reconciliations if reconciliation_sources_verified(row)])
    national = national_registry()
    historical_detail = historical_detail_registry()
    historical_annual = historical_registry()
    other_historical = other_budget_historical_registry()
    version = 'rap-national-' + _fingerprint({'files':{
        name:_file_fingerprint(name) for name in ('mouvements-rap-p174.json','mouvements-rap-national.json',
            'mouvements-rap-historique-detail.json','mouvements-rap-historique.json',
            'mouvements-rap-autres-budgets-historique.json')},
        'coverage': rap_quality.registry()[1]})[:16]
    detailed = _historical_details()
    detailed_count = len(detailed)
    detailed_keys = set().union(*(_registry_keys(reg) for reg in detailed)) if detailed_count else set()
    annual_only_count = sum(not (_registry_keys(reg) & detailed_keys) for reg in historical_annual.get('registries', []))
    validation_counts=historical_validation_counts()
    coverage = ('Mouvements RAP vérifiés : programme 174 Écologie 2023–2025 et '
                + str(len(national.get('registries', []))) + ' programme-années nationales supplémentaires, '
                + str(validation_counts['detailed_reconciled']) + ' programme-années historiques détaillés avec rapprochement annuel, '
                + str(validation_counts['detailed_without_annual_reference']) + ' avec tableaux détaillés vérifiés et rapprochement annuel indisponible, plus '
                + str(annual_only_count) + ' totaux historiques annuels sans détail, '
                'avec le statut de rapprochement indiqué pour chaque programme.')
    notes = list(dict.fromkeys(registry().get('limits', []) + national.get('limits', [])
                              + historical_detail.get('limits', []) + historical_annual.get('limits', [])
                              + other_historical.get('limits', [])))
    scopes = [reg['scope'] for reg, _ in selected]
    evidence_scope = dict(grain='programme', selected_measure=p['measure'], scopes=scopes,
                          original_columns_preserved=True,
                          applies_to_selection=bool(items) and all(row.get('status') in ('published','inflation_missing') for row in items))
    if len(scopes) == 1:
        evidence_scope.update(scopes[0])
    for row in missing_programmes:
        is_verified = row['source'] in verified
        row['path'] = row['mission'] + '/' + row['program']
        row['status'] = 'table_unavailable' if is_verified else 'source_unverified'
        row['explanation'] = rap_quality.explanation(p,row,'movements',row['status'],
            row.get('movement_note',f'Aucune récapitulation datée de mouvements intégrée pour ce programme dans le RAP, pages {row["context_pages"][0]} à {row["page_end"]}.')
            if is_verified else 'Empreinte du RAP non confirmée dans le catalogue local.')
    missing_years = [year for year in range(p['start'], p['end'] + 1)
                    if year not in {row['year'] for row in items if row['source_verified']}]
    return dict(parameters=p, version=version, items=items, count=len(items),
                programmes_without_recap=missing_programmes,
                year_explanations=rap_quality.year_explanations(p,missing_years,'movements'),
                proofs=proofs, evidence_rows=proofs, evidence_row_count=len(verified_proofs),table_total_count=len(verified_tables),
                table_totals=tables, reconciliations=reconciliations, annual_adjustments=adjustments,
                evidence_scope=evidence_scope, sources=sources, source_checks=checks,
                coverage=coverage, notes=notes,
                years_without_integrated_rows=missing_years,
                inflation={'indices': meta['indices'], 'source': meta.get('inflation_source'), 'base': p['base']},
                selection_id=_fingerprint({'parameters': p, 'version': version, 'inflation': meta['indices'], 'sources': checks}))

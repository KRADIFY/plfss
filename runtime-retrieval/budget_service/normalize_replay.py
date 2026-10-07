"""Replay reviewed facts in memory before any candidate database is written.

This is a bounded adapter. A complete predecessor and check_preserved remain
mandatory: replaying these plans does not certify a reconstruction from zero.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from . import normalize
from .import_pap_2026_national import FIELDS, KEY_FIELDS, validate_plan as validate_pap
from .import_pap_2026 import validate_plan as validate_ecology
from .correction_ledger import KEY

PLAN_DIR = Path(__file__).parent / 'data'
PLAN_NAME = 'validated-fact-replay.json'
ROUTINE_META = {'version', 'built_at', 'fact_count', 'source_count',
                'imported_source_count', 'issues', 'indices', 'inflation_source',
                'stats', 'data_version', 'catalogue_updated_at', 'validated_replay'}
RECEIPTS = {'pap2026_ecology', 'pap2026_national', 'rap_explicit_zeros', 'rap_investigation'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def row_tuple(row):
    if set(row) != set(FIELDS):
        raise ValueError('Le plan doit contenir exactement les 19 colonnes facts')
    for field in ('year', 'cents', 'line', 'approximate'):
        if type(row[field]) is not int:
            raise ValueError('Champ entier invalide : ' + field)
    if row['line'] <= 0 or row['approximate'] not in (0, 1):
        raise ValueError('Page/ligne ou précision invalide')
    if any(not isinstance(row[k], str) for k in FIELDS if k not in ('year', 'cents', 'line', 'approximate')):
        raise ValueError('Champ texte invalide')
    return tuple(row[k] for k in FIELDS)


class Replay:
    def __init__(self, importer, data):
        normalize.validate_source_ids(importer.manifest)
        self.records = {normalize.source_id(r): r for r in importer.manifest}
        self.data = Path(data).resolve()
        self.facts = [tuple(r) for r in importer.facts]
        self.issues = deepcopy(importer.issues)
        self.totals = [tuple(r) for r in getattr(importer, 'reconciled_totals', [])]
        self.verified = {}
        self.indices = {}
        self.meta = {}

    def source(self, sid, sha256=None, expected_path=None):
        record = self.records.get(sid)
        if not record or not isinstance(record.get('sha256'), str) or len(record['sha256']) != 64:
            raise ValueError('Source absente ou empreinte invalide : ' + sid)
        if sha256 is not None and record['sha256'] != sha256:
            raise ValueError('Empreinte du catalogue différente du plan : ' + sid)
        if expected_path is not None and record['path'] != expected_path:
            raise ValueError('Chemin source différent du plan : ' + sid)
        if sid not in self.verified:
            path = (self.data / record['path']).resolve()
            if not path.is_relative_to(self.data):
                raise ValueError('Source hors du répertoire de données')
            if digest(path) != record['sha256']:
                raise ValueError('Empreinte du fichier source différente du plan : ' + sid)
            self.verified[sid] = record['sha256']
        return record

    def proof(self, row, proof, original=False):
        sid = proof.get('source')
        sha = proof.get('sha256') or proof.get('source_sha256')
        if not sha or sid != row['source']:
            raise ValueError('Preuve absente ou source différente du fait')
        # Proof paths can name an archived copy; source ID and exact bytes bind
        # that copy to the catalogue. source_evidence checks the canonical path.
        source = self.source(sid, sha)
        line = proof.get('row') if original and 'row' in proof else proof.get('page')
        if type(line) is not int or line <= 0 or line != row['line']:
            raise ValueError('Page/ligne de preuve différente du fait')
        if 'page' in proof and source.get('pages') and line > source['pages']:
            raise ValueError('Page hors du document source')
        for field in ('cents', 'amount_cents', 'candidate_cents'):
            if field in proof and (type(proof[field]) is not int or proof[field] != row['cents']):
                raise ValueError('Montant de preuve différent du fait')
        for field in ('euros', 'published_total_euros'):
            if field in proof and Decimal(str(proof[field])) * 100 != row['cents']:
                raise ValueError('Montant en euros différent du fait')
        for field in ('year', 'stage', 'measure'):
            if field in proof and proof[field] != row[field]:
                raise ValueError('Périmètre de preuve différent du fait')

    def positions(self, fields, row):
        fields = tuple(fields)
        if not set(('year', 'stage', 'measure', 'budget', 'program')) <= set(fields) <= set(KEY) or len(fields) != len(set(fields)):
            raise ValueError('Clé de rapprochement/absence invalide')
        indices = tuple(FIELDS.index(k) for k in fields)
        if fields not in self.indices:
            lookup = defaultdict(list)
            for pos, fact in enumerate(self.facts):
                lookup[tuple(fact[i] for i in indices)].append(pos)
            self.indices[fields] = lookup
        return self.indices[fields].get(tuple(row[k] for k in fields), [])

    def add(self, fact):
        position = len(self.facts)
        self.facts.append(fact)
        for fields, lookup in self.indices.items():
            lookup[tuple(fact[FIELDS.index(k)] for k in fields)].append(position)

    def change(self, change):
        after = change['after']; expected = row_tuple(after)
        before = change.get('before')
        fields = tuple(change.get('absence_key_fields', KEY))
        if before is not None:
            old = row_tuple(before)
            if any(before[k] != after[k] for k in KEY):
                raise ValueError('Une correction ne peut pas déplacer la clé comptable')
            self.proof(before, change.get('csv_evidence') or change.get('before_proof') or {}, original=True)
        self.proof(after, change.get('rap_evidence') or change.get('proof') or {})
        found = self.positions(fields, after)
        if len(found) > 1:
            raise ValueError('Faits concurrents ou doublons : ' + change['id'])
        if found and self.facts[found[0]] == expected:
            return 'already_present'
        if before is not None:
            if not found or self.facts[found[0]] != old:
                raise ValueError('Valeur avant différente du plan : ' + change['id'])
            self.facts[found[0]] = expected
            return 'replaced'
        if found:
            raise ValueError('Absence non vérifiée : ' + change['id'])
        self.add(expected)
        return 'inserted'

    def insert(self, row, proof):
        row = {k: row[k] for k in FIELDS}
        return self.change(dict(id='/'.join(str(row[k]) for k in KEY_FIELDS), after=row,
                                proof=proof, absence_key_fields=KEY_FIELDS))

    def total(self, row):
        row = tuple(row)
        found = [old for old in self.totals if old[:5] == row[:5]]
        if found and found != [row]:
            raise ValueError('Total indépendant différent du plan')
        if not found:
            self.totals.append(row)

    def batch(self, batch):
        ledger = batch['ledger']
        if ledger['id'] != batch['id'] or ledger.get('independent_published_totals_modified') is not False:
            raise ValueError('Lot de corrections non validé ou totaux indépendants modifiés')
        changes = ledger.get('fact_replacements', []) + ledger.get('fact_insertions', [])
        ids = [c['id'] for c in changes]
        if not changes or len(ids) != len(set(ids)):
            raise ValueError('Lot vide ou identifiants de correction dupliqués')
        for change in changes:
            self.change(change)
        # The original independent totals remain intact; only exact justified
        # adjustments may explain the difference with corrected observations.
        impacts = defaultdict(int); correction_ids = defaultdict(list)
        scope = ('year', 'stage', 'measure', 'budget', 'mission')
        for change in changes:
            key = tuple(change['after'][k] for k in scope)
            impacts[key] += change['after']['cents'] - (change['before']['cents'] if change.get('before') else 0)
            correction_ids[key].append(change['id'])
        adjustments = ledger.get('affected_aggregate_adjustments')
        if adjustments is not None:
            actual = defaultdict(int)
            for fact in self.facts:
                actual[tuple(fact[FIELDS.index(k)] for k in scope)] += fact[FIELDS.index('cents')]
            seen = set()
            for item in adjustments:
                key = tuple(item[k] for k in scope)
                if (key in seen or item['correction_cents'] != impacts[key]
                        or set(item['correction_ids']) != set(correction_ids[key])
                        or item['previous_fact_sum_cents'] + item['correction_cents'] != item['corrected_fact_sum_cents']
                        or actual[key] != item['corrected_fact_sum_cents']):
                    raise ValueError('Ajustement agrégé différent du registre validé')
                seen.add(key)
            if seen != set(impacts):
                raise ValueError('Ajustements agrégés incomplets')
        resolved = batch.get('resolved_source_issues', [])
        for entry in resolved:
            if not entry['correction_ids'] or not set(entry['correction_ids']) <= set(ids):
                raise ValueError('Résolution de note sans corrections vérifiées')
            original = entry['original_issue']
            conflicting = [i for i in self.issues if all(i.get(k) == original.get(k) for k in ('source', 'row', 'kind')) and i != original]
            if conflicting:
                raise ValueError('Note source différente de la note résolue')
            self.issues = [i for i in self.issues if i != original]
        key = batch['ledger_meta_key']
        if key in ROUTINE_META | RECEIPTS | {'resolved_source_issues'} or key in self.meta:
            raise ValueError('Clé de reçu de corrections réservée ou dupliquée')
        self.meta[key] = deepcopy(ledger)
        self.meta.setdefault('resolved_source_issues', []).extend(deepcopy(resolved))


def replay_standard_plans(state, plans, receipts):
    pap, ecology, zeros, investigation = (plans[n] for n in (
        'pap-2026-national.json', 'pap-ecologie-2026.json', 'rap-explicit-zeros.json', 'rap-investigation.json'))
    validate_pap(pap); validate_ecology(ecology)
    if {row_tuple({k: r[k] for k in FIELDS}) for r in ecology['rows']} != {row_tuple({k: r[k] for k in FIELDS}) for r in pap['existing_rows_preserved']}:
        raise ValueError('Le plan Écologie ne correspond plus au sous-ensemble national')
    source_by_mission = {s['mission']: s for s in pap['sources']}
    for row in pap['rows']:
        source = source_by_mission[row['mission']]
        state.insert(row, dict(source=source['source_id'], sha256=source['source_sha256'], page=row['page']))
    for check in pap['mission_total_checks']:
        state.total((2026, check['stage'], check['measure'], 'BG', check['mission'], check['cents'], source_by_mission[check['mission']]['source_id']))
    source = ecology['source']
    ecology_receipt = dict(source=source['id'], sha256=source['sha256'], pages=ecology['reviewed_pages'], limits=ecology['limits'], observations=len(ecology['rows']))
    if receipts['pap2026_ecology'] != ecology_receipt:
        raise ValueError('Reçu Écologie différent du plan')
    national = receipts['pap2026_national']
    for key, expected in dict(sources={k:s['source_sha256'] for k,s in source_by_mission.items()}, missions=len(pap['sources']), programmes_checked=len(pap['checks']), mission_totals_checked=len(pap['mission_total_checks']), observations=len(pap['rows']), observations_added=len(pap['additions']), limits=pap['limits']).items():
        if national.get(key) != expected:
            raise ValueError('Reçu PAP national différent du plan : ' + key)
    if zeros.get('version') != 'rap-explicit-zeros-1' or len(zeros['rows']) != len(zeros['proofs']) or len(zeros['rows']) != 46:
        raise ValueError('Plan des zéros publiés invalide')
    seen = set()
    for row, proof in zip(zeros['rows'], zeros['proofs']):
        key = tuple(row[k] for k in KEY_FIELDS)
        if (key in seen or row['cents'] != 0 or proof['published_total_euros'] != 0
                or any(row[k] for k in ('action', 'subaction', 'category', 'title'))
                or row['year'] not in (2023, 2024, 2025) or row['stage'] not in ('LFI', 'EXEC', 'OUVERT')
                or row['measure'] not in ('AE', 'CP')):
            raise ValueError('Zéro non publié ou doublon')
        seen.add(key); state.insert(row, proof)
    receipt = receipts['rap_explicit_zeros']
    if receipt['facts_added'] != len(seen) or receipt['zeroes_from_blank_cells'] != 0 or receipt['sources_verified'] != len({r['source'] for r in zeros['rows']}):
        raise ValueError('Reçu des zéros différent du plan')
    for source in investigation['sources']:
        state.source(source['id'], source['sha256'], source['path'])
    receipt = receipts['rap_investigation']
    if receipt['records'] != len(investigation['records']) or receipt['checked_at'] != investigation['checked_at']:
        raise ValueError('Reçu documentaire différent du registre')


def extend(importer, data, previous_meta=None, plan_dir=PLAN_DIR):
    """Commit only the fully checked in-memory result; never open a writable DB."""
    plan_dir = Path(plan_dir)
    plan_path = plan_dir / PLAN_NAME
    plan = json.loads(plan_path.read_text(encoding='utf8'))
    if plan.get('version') != 'validated-fact-replay-1' or set(plan['receipts']) != RECEIPTS:
        raise ValueError('Plan persistant de rejeu invalide')
    names = {'pap-ecologie-2026.json', 'pap-2026-national.json', 'rap-explicit-zeros.json', 'rap-investigation.json'}
    if set(plan['plan_sha256s']) != names:
        raise ValueError('Plans de rejeu absents ou inattendus')
    plans = {}
    for name, expected in plan['plan_sha256s'].items():
        path = plan_dir / name
        if digest(path) != expected:
            raise ValueError('Plan modifié depuis sa validation : ' + name)
        plans[name] = json.loads(path.read_text(encoding='utf8'))
    for key, name in [('pap2026_national','pap-2026-national.json'), ('rap_explicit_zeros','rap-explicit-zeros.json')]:
        if plan['receipts'][key]['plan_sha256'] != plan['plan_sha256s'][name]:
            raise ValueError('Empreinte du reçu différente du plan')
    state = Replay(importer, data)
    for source in plan['source_evidence']:
        state.source(source['id'], source['sha256'], source['path'])
    replay_standard_plans(state, plans, plan['receipts'])
    batch_ids = set()
    for batch in plan['correction_batches']:
        if batch['id'] in batch_ids:
            raise ValueError('Lot de corrections dupliqué')
        batch_ids.add(batch['id']); state.batch(batch)
    state.meta.update(deepcopy(plan['receipts']))
    # Historical receipts stay historical: their original insertion counts and
    # timestamps are not presented as events caused by this replay.
    previous_meta = previous_meta or {}
    unknown = set(previous_meta) - ROUTINE_META - set(state.meta)
    if unknown:
        raise ValueError('Reçus existants sans adaptateur de rejeu : ' + ', '.join(sorted(unknown)))
    for key, value in state.meta.items():
        if key in previous_meta and previous_meta[key] != value:
            raise ValueError('Reçu existant différent du plan de rejeu : ' + key)
    state.meta['validated_replay'] = dict(plan_sha256=digest(plan_path), correction_batches=sorted(batch_ids),
                                        sources_verified=len(state.verified), source_sha256s=state.verified,
                                        scope='bounded_replay_against_complete_predecessor')
    importer.facts = state.facts
    importer.issues = state.issues
    importer.reconciled_totals = state.totals
    importer.used = {r[FIELDS.index('source')] for r in state.facts}
    importer.stats = Counter(f'{r[0]}/{r[1]}/{r[3]}' for r in state.facts)
    importer.replayed_meta = state.meta

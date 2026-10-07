"""Replay the checked incremental imports during a full offline reconstruction."""
import hashlib
import json
from collections import Counter
from . import normalize


def extend(importer):
    from . import import_rap_synthesis
    importer.published_nodes = []
    importer.reconciled_totals = []
    importer.nomenclature_provenance = []
    records = {normalize.source_id(r): r for r in importer.manifest}
    for year, sid in import_rap_synthesis.SOURCES.items():
        if sid not in records:
            continue
        source = dict(records[sid], id=sid)
        rows, checks, fallbacks, nodes = import_rap_synthesis.parse(source, year)
        if any(not c['ok'] for c in checks):
            raise ValueError(f'Rapprochement RAP {year} non conforme')
        if any(r[0] == year and r[1] == 'EXEC' for r in importer.facts):
            raise ValueError(f'Exécution {year} déjà importée par un autre adaptateur')
        importer.facts.extend(rows)
        importer.used.add(sid)
        importer.published_nodes.extend(nodes)
        importer.issues.extend(dict(f, kind='preserved_published_parent') for f in fallbacks)
        for c in checks:
            if c.get('node') and c['expected_cents'] is not None:
                bits = c['node'].split('/')
                importer.reconciled_totals.append((year, 'EXEC', c['measure'], bits[0], '/'.join(bits[1:]), c['expected_cents'], sid))
    plan_path = normalize.INPUTS / 'developpement-20260909/lfi2026/plan.json'
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        if any(c['expected'] != c['actual'] for c in plan['checks']):
            raise ValueError('Rapprochement LFI 2026 non conforme')
        for source in plan['sources']:
            actual = records.get(source['id'])
            if not actual or actual['sha256'] != source['sha256']:
                raise ValueError('Source LFI absente ou différente du plan validé')
            if hashlib.sha256((normalize.DATA / actual['path']).read_bytes()).hexdigest() != source['sha256']:
                raise ValueError('Empreinte source LFI non conforme')
        if any(r[0] == 2026 and r[1] == 'LFI' for r in importer.facts):
            raise ValueError('LFI 2026 déjà intégrée par un autre adaptateur')
        importer.facts.extend(plan['facts'])
        sid = plan['facts'][0][15]
        importer.used.add(sid)
        importer.published_nodes.extend(plan['published_nodes'])
        importer.reconciled_totals.extend((2026, 'LFI', c['measure'], c['budget'], c['path'], c['expected'], sid) for c in plan['checks'])
        importer.nomenclature_provenance.extend((2026, m['budget'], m['mission'], m['label'], m['code_basis']) for m in plan['mission_mapping'])
    from .import_fdc_forecast import extend as import_forecasts
    import_forecasts(importer)
    importer.stats = Counter(f'{r[0]}/{r[1]}/{r[3]}' for r in importer.facts)


def check_preserved(previous, facts):
    """A routine rebuild must never silently erase or change validated observations."""
    expected = Counter(tuple(r) for r in previous.execute('select * from facts'))
    missing = expected - Counter(tuple(r) for r in facts)
    if missing:
        raise ValueError(f'Reconstruction interrompue : {sum(missing.values())} observations existantes ne sont pas reproduites. Base servie conservée.')


def save_extra(db, importer):
    db.executescript('''
    CREATE TABLE published_nodes(year INTEGER, stage TEXT, measure TEXT, budget TEXT, path TEXT, availability TEXT, source TEXT, line INTEGER, PRIMARY KEY(year,stage,measure,budget,path,source));
    CREATE TABLE reconciled_totals(year INTEGER, stage TEXT, measure TEXT, budget TEXT, path TEXT, cents INTEGER, source TEXT, PRIMARY KEY(year,stage,measure,budget,path));
    CREATE TABLE nomenclature_provenance(year INTEGER,budget TEXT,mission TEXT,label TEXT,code_basis TEXT,PRIMARY KEY(year,budget,mission));
    ''')
    db.executemany('INSERT INTO published_nodes VALUES(?,?,?,?,?,?,?,?)', getattr(importer, 'published_nodes', []))
    db.executemany('INSERT INTO reconciled_totals VALUES(?,?,?,?,?,?,?)', getattr(importer, 'reconciled_totals', []))
    db.executemany('INSERT INTO nomenclature_provenance VALUES(?,?,?,?,?)', getattr(importer, 'nomenclature_provenance', []))

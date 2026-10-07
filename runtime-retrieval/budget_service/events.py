"""Published legal events are separate from annual net budget observations."""
import hashlib
import json
import sqlite3
from pathlib import Path
from .model import constant_cents
from . import topics


def connect(data):
    path = data / 'derived/events.sqlite'
    if not path.exists():
        return None
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def sources(data):
    db = connect(data)
    if db is None:
        return []
    try:
        return [json.loads(r[0]) for r in db.execute('select data from sources')]
    finally:
        db.close()


def within(path, parent):
    return not parent or path == parent or path.startswith(parent+'/')


def select(rows, p, indices):
    items = []
    carriers = {c['path'] for c in topics.registry()['carriers']}
    for row in rows:
        r = dict(row)
        if not p['start'] <= r['year'] <= p['end'] or r['budget'] != p['budget'] or r['measure'] != p['measure']:
            continue
        path = '/'.join(x for x in (r['mission'], r['program'], r.get('action'), r.get('subaction')) if x)
        carrier = '/'.join((r['mission'], r['program'])) in carriers
        if p.get('topic') and p.get('topic_mode', 'only') == 'only' and not carrier:
            continue
        if not (within(path, p['scope']) or within(p['scope'], path)):
            continue
        if any(within(path, e) or within(p['scope'], e) for e in p['exclude']):
            continue
        status = 'published' if r['amount_cents'] is not None else 'not_reported'
        reason = '' if status == 'published' else 'Cellule non renseignée dans cet acte ; aucun zéro imputé.'
        if not within(path, p['scope']) or any(within(e, path) for e in p['exclude']):
            status = 'detail_unavailable'; reason = 'Acte publié au niveau du programme ; ventilation insuffisante pour cette sélection.'
        if p.get('topic') and carrier and r['year'] >= 2020:
            status = 'detail_unavailable'; reason = 'La part MaPrimeRénov’ dans cet acte n’est pas isolée ; aucun montant imputé au dispositif ou à son reste.'
        if p.get('topic') and p.get('topic_mode', 'only') == 'only' and r['year'] < 2020:
            status = 'not_applicable'; reason = 'MaPrimeRénov’ a été créé en 2020 ; cet acte antérieur porte sur le programme entier.'
        nominal = r['sign'] * r['amount_cents'] if r['amount_cents'] is not None else None
        value = nominal if not p['constant'] or nominal is None else constant_cents(nominal, r['year'], p['base'], indices)
        if nominal is not None and value is None and status == 'published':
            status = 'inflation_missing'; reason = 'Indice annuel d’inflation indisponible.'
        r.update(path=path, status=status, reason=reason, nominal=nominal/100 if nominal is not None and status in ('published', 'inflation_missing') else None,
                 value=value/100 if value is not None and status == 'published' else None)
        items.append(r)
    return sorted(items, key=lambda r: (r['publication_date'], r['act_id'], r['mission'], r['program'], r['measure']))


def query(data, p, meta):
    db = connect(data)
    empty = {'items': [], 'count': 0, 'coverage': 'Aucun acte chiffré intégré.', 'version': None, 'sources': []}
    if db is None:
        return empty
    try:
        event_meta = {r['key']: json.loads(r['value']) for r in db.execute('select * from meta')}
        items = select(db.execute('select * from events'), p, {int(k):v for k,v in meta['indices'].items()})
        source_ids = {r['source'] for r in items}
        return dict(parameters=p,inflation={'indices':meta['indices'],'source':meta.get('inflation_source'),'base':p['base']},items=items, count=len(items), coverage=event_meta['coverage'], version=event_meta['version'],
                    updated_at=event_meta['built_at'], sources=[json.loads(r['data']) for r in db.execute('select * from sources') if r['id'] in source_ids],
                    notes=['Ces événements expliquent une partie des mouvements annuels et ne s’ajoutent pas aux crédits ouverts.',
                           'Le registre est partiel. L’absence d’événement dans la sélection ne signifie pas absence de mouvement.',
                           'Les annulations ne mesurent pas les gels ou les dégels. La date d’effet non établie reste vide.'],
                    selection_id=hashlib.sha256(json.dumps({'parameters':p,'events':event_meta['version'],'inflation':meta['indices']},sort_keys=True).encode()).hexdigest())
    finally:
        db.close()

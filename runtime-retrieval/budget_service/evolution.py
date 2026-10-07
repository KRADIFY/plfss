"""Comparable annual rates over published, explicitly selected budget scopes."""
from decimal import Decimal,ROUND_HALF_UP
from .model import STAGES

VERSION='annual-evolution-1'
LABELS={
 'nominal_yoy':'Variation annuelle en euros courants',
 'real_yoy':'Variation annuelle corrigée de l’inflation',
 'real_from_start':'Variation réelle depuis la première année sélectionnée',
}

def operand(annual,stage,indices):
    if annual is None:return None
    c=annual[stage]
    cents=c.get('nominal_cents')
    if cents is None and c.get('nominal') is not None:cents=int(Decimal(str(c['nominal']))*100)
    return dict(year=annual['year'],nominal_cents=cents,status=c.get('nominal_status',c['status']),
        sources=c.get('sources',[]),approximate=bool(c.get('approximate')),
        ipc=indices.get(annual['year']),grain=c.get('grain'),reason=c.get('reason',''))

def rate(current,reference,real,reference_year):
    operands=[v for v in (reference,current) if v is not None]
    result=dict(value=None,status='unavailable',unit='%',reference_year=reference_year,
        sources=sorted({s for op in operands for s in op['sources']}),
        approximate=any(op['approximate'] for op in operands),operands=operands,
        formula='((montant / IPC de l’année) / (montant de référence / IPC de référence) − 1) × 100' if real else '(montant / montant de référence − 1) × 100')
    valid=lambda x:x is not None and x['nominal_cents'] is not None and x['status'] in ('ok','excluded')
    if reference is None:
        result['reason']='L’année précédente est hors de la sélection ; aucun taux annuel n’est calculé pour la première année affichée.'
    elif not valid(current) or not valid(reference):
        result['reason']='Variation indisponible : une année est absente, partielle ou insuffisamment ventilée.'
    elif reference['nominal_cents']<=0:
        result.update(status='nonpositive_reference',reason='Le montant de référence est nul ou négatif ; la variation en pourcentage n’est pas calculée.')
    elif real and any(op['ipc'] is None or Decimal(str(op['ipc']))<=0 for op in operands):
        result.update(status='inflation_missing',reason='Indice annuel d’inflation indisponible pour au moins une des deux années.')
    else:
        ratio=Decimal(current['nominal_cents'])/Decimal(reference['nominal_cents'])
        if real:ratio*=Decimal(str(reference['ipc']))/Decimal(str(current['ipc']))
        value=((ratio-1)*100).quantize(Decimal('0.0001'),rounding=ROUND_HALF_UP)
        result.update(value=float(value),status='ok',reason=('Variation corrigée de l’inflation, calculée avant arrondi des euros constants.' if real else 'Variation des montants en euros courants.')+' Périmètre publié après les exclusions choisies ; les changements de nomenclature ne sont pas neutralisés.')
    return result

def attach(series,indices):
    if not series:return
    by_year={a['year']:a for a in series};first=min(by_year)
    for annual in series:
        annual['evolution']={}
        for stage in STAGES:
            current=operand(annual,stage,indices)
            previous=operand(by_year.get(annual['year']-1),stage,indices)
            initial=operand(by_year[first],stage,indices)
            annual['evolution'][stage]=dict(
                nominal_yoy=rate(current,previous,False,annual['year']-1),
                real_yoy=rate(current,previous,True,annual['year']-1),
                real_from_start=rate(current,initial,True,first))

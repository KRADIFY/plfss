"""Derived comparisons never turn an absent or partial operand into a zero."""
from decimal import Decimal, ROUND_HALF_UP

COMPARISONS = {
    'LFI_PLF': 'Écart LFI − PLF',
    'EXEC_LFI': 'Écart consommé − LFI',
    'CONSUMPTION': 'Taux de consommation',
}


def compare(annual, denominator='LFI'):
    result = {}
    for key, left, right, percent in [('LFI_PLF','LFI','PLF',False),
                                      ('EXEC_LFI','EXEC','LFI',False),
                                      ('CONSUMPTION','EXEC',denominator,True)]:
        a,b=annual[left],annual[right]
        item={'value':None,'status':'unavailable','operands':[left,right],
              'unit':'%' if percent else 'EUR',
              'sources':sorted(set(a.get('sources',[])+b.get('sources',[]))),
              'approximate':bool(a.get('approximate') or b.get('approximate'))}
        if any(c.get('value') is None or c['status'] not in ('ok','excluded') for c in (a,b)):
            item['reason']='Calcul indisponible : une des deux étapes est absente, partielle ou insuffisamment ventilée.'
        elif percent and b['nominal']==0:
            item.update(status='zero_denominator',reason='Le dénominateur est nul ; le taux ne peut pas être calculé.')
        else:
            if percent:
                value=Decimal(str(a['nominal']))/Decimal(str(b['nominal']))*100
                value=value.quantize(Decimal('0.0001'),rounding=ROUND_HALF_UP)
            else:value=Decimal(str(a['value']))-Decimal(str(b['value']))
            item.update(value=float(value),status='ok',reason=(f'Consommé ÷ {right} × 100. Calcul sur les euros courants du même exercice.' if percent else f'{left} − {right}, sur le même périmètre.'))
        result[key]=item
    return result

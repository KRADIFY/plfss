"""Budget amounts are stored as integer cents; no inference of missing amounts."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata

STAGES = {
    'PLF': 'Proposé en PLF', 'LFI': 'Voté en LFI', 'EXEC': 'Consommé',
    'OUVERT': 'Crédits ouverts', 'REPORT_ENTRANT': 'Reports de N−1',
    'LEGIS': 'Ajustements nets de crédits', 'REGLEMENT': 'Mouvements réglementaires nets',
    'FDC': 'FdC et AdP rattachés', 'FDC_PREVU': 'FdC et AdP prévus',
    'FONGIBILITE': 'Fongibilité des crédits',
    'PLRG_OUVERTURE': 'Ouvertures proposées en PLRG',
    'PLRG_ANNULATION': 'Annulations proposées en PLRG',
    'REPORT_SORTANT': 'Reports vers N+1',
}

def norm(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower())

def code(value, width=0):
    value = str(value or '').strip()
    if re.fullmatch(r'\d+\.0+', value): value = value.split('.')[0]
    if value.isdigit(): value = str(int(value)).zfill(width)
    return value

def cents(value):
    if value is None or str(value).strip() in ('', '-', '—', 'n.d.', 'NA'): return None
    text = re.sub(r'\s', '', str(value)).replace('\u00a0', '').replace(',', '.')
    if text.startswith('(') and text.endswith(')'): text = '-' + text[1:-1]
    try:
        number = Decimal(text)
        if not number.is_finite(): raise ValueError('Non-finite amount')
        return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except InvalidOperation as error: raise ValueError('Invalid budget amount') from error

def constant_cents(amount, year, base, indices):
    if amount is None: return None
    if year not in indices or base not in indices: return None
    return int((Decimal(amount) * Decimal(str(indices[base])) / Decimal(str(indices[year]))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def budget_code(value):
    return {'budgetgeneral':'BG', 'budgetsannexes':'BA', 'budgetannexe':'BA',
            'comptesdaffectationspeciale':'CAS', 'comptesdeconcoursfinanciers':'CCF',
            'cs':'CAS', 'cf':'CCF'}.get(norm(value), str(value).strip().upper())

def parts(program, action, subaction):
    program = code(program).removeprefix('P')
    a, s = code(action), code(subaction)
    if '-' in s:
        bits = s.split('-'); a, s = bits[-2], bits[-1]
    if '-' in a: a = a.split('-')[-1]
    return program, code(a, 2), code(s, 2)

def safe_csv(value):
    text = str(value if value is not None else '')
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text

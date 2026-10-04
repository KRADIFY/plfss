"""Comptes sociaux : centimes entiers, phases distinctes, aucun blanc converti en zéro."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata

STAGES={'PLFSS':'Proposé en PLFSS','LFSS':'Voté en LFSS','CONSTATE':'Comptes constatés',
        'PLFSS_RECTIF':'Rectification proposée','LFSS_RECTIF':'Rectification votée','PROJECTION':'Projection pluriannuelle'}
METRICS={'RECETTES':'Recettes','DEPENSES':'Dépenses','SOLDE':'Solde'}
BRANCHES={'MALADIE':'Maladie','ATMP':'Accidents du travail et maladies professionnelles','VIEILLESSE':'Vieillesse','FAMILLE':'Famille','AUTONOMIE':'Autonomie','FSV':'Fonds de solidarité vieillesse'}
ONDAM={'ONDAM':'Total ONDAM','SOINS_VILLE':'Soins de ville','ETABLISSEMENTS_SANTE':'Établissements de santé','PERSONNES_AGEES':'Établissements et services pour personnes âgées','PERSONNES_HANDICAPEES':'Établissements et services pour personnes handicapées','FIR':'Fonds d’intervention régional et soutien à l’investissement','AUTRES':'Autres prises en charge'}


def norm(text):
    return re.sub('[^a-z0-9]','',unicodedata.normalize('NFKD',str(text or '')).encode('ascii','ignore').decode().lower())


def amount(text,unit):
    text=str(text).strip().replace('\u2212','-').replace('\u2011','-').replace('\u2013','-').replace('\u2010','-')
    if text in ('','-','—','n.d.','ND','n/a'):return None
    text=re.sub(r'\s','',text).replace(',','.')
    if text.startswith('(') and text.endswith(')'):text='-'+text[1:-1]
    value=Decimal(text)
    if not value.is_finite():raise ValueError('Montant non fini')
    return int((value*Decimal(unit)*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def stage_for(kind,edition,year):
    if year>edition:return 'PROJECTION'
    if year==edition:return 'LFSS' if kind=='LFSS' else 'PLFSS'
    if year==edition-1:return 'LFSS_RECTIF' if kind=='LFSS' else 'PLFSS_RECTIF'
    return 'CONSTATE'


def branch(text):
    n=norm(text)
    if n in ('rgconsolide','robssconsolide'):return 'TOTAL'
    if n in ('rgfsv','robssfsv'):return 'TOTAL_FSV'
    if n.startswith('maladie'):return 'MALADIE'
    if n.startswith(('accidentsdutravail','atmp')):return 'ATMP'
    if n.startswith(('vieillesse','retraites')):return 'VIEILLESSE'
    if n.startswith('famille'):return 'FAMILLE'
    if n.startswith('autonomie'):return 'AUTONOMIE'
    if n.startswith(('toutesbranches','ensemble','total','regimesobligatoiresdebase','regimesdebase')):
        return 'TOTAL_FSV' if 'fondssolidaritevieillesse' in n or 'fondsdesolidaritevieillesse' in n or 'fsv' in n else 'TOTAL'
    if 'fondssolidaritevieillesse' in n or 'fondsdesolidaritevieillesse' in n or n=='fsv':return 'FSV'
    return None


def ondam(text):
    n=norm(text)
    if n in ('total','totalondam','ondam','ondamtotal'):return 'ONDAM'
    if 'soinsdeville' in n:return 'SOINS_VILLE'
    if 'personnesagees' in n:return 'PERSONNES_AGEES'
    if 'personneshandicapees' in n:return 'PERSONNES_HANDICAPEES'
    if 'etablissementsdesante' in n or 'etablissementssanitaires' in n:return 'ETABLISSEMENTS_SANTE'
    if 'interventionregional' in n or n=='fir' or n.startswith('firet'):return 'FIR'
    if 'autres' in n:return 'AUTRES'
    return None

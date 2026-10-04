"""Document expected comparison coverage without converting missing amounts to zero."""
import sys,json,csv
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from plfss_service.store import Store
store=Store(ROOT/'data')
rows=[]
for domain,metric in [('EQUILIBRE','RECETTES'),('EQUILIBRE','DEPENSES'),('EQUILIBRE','SOLDE'),('ONDAM','DEPENSES')]:
 m=store.matrix(domain,'ROBSS',2017,2027,metric,('PLFSS','LFSS','CONSTATE'))
 for r in [m['total'],*m['rows']]:
  for col,c in zip(m['columns'],r['cells']):
   status=c['status'];reason=c.get('reason','')
   if c['amount_cents'] is None and ((col['year']==2027 and col['stage']=='LFSS') or (col['year']>=2026 and col['stage']=='CONSTATE')):status='publication_future'
   if r['entity']=='AUTONOMIE' and col['year']<2021 and c['amount_cents'] is None:
    status='ligne_historique_distincte_non_reperee';reason='Les tableaux historiques consultés ne présentent pas de ligne Autonomie distincte. Aucun zéro imputé ; les postes du tableau restent séparés.'
   rows.append(dict(year=col['year'],stage=col['stage'],domain=domain,metric=metric,entity=r['label'],status=status,reason=reason,amount_cents=c['amount_cents'],references=c['references'],administration='Direction de la sécurité sociale / commission des comptes de la sécurité sociale'))
summary=dict(Counter(r['status'] for r in rows))
result=dict(explanation='Matrice ciblée des tableaux d’équilibre par branche et des sous-objectifs ONDAM, 2017–2027, tous régimes de base. Ce décompte ne représente pas tous les chiffres des annexes, ni tous les régimes particuliers.',summary=summary,rows=rows,
 notes=['Les textes initiaux PLFSS et les LFSS promulguées sont distincts. Les autres lectures parlementaires sont conservées comme documents et ne remplacent pas automatiquement le texte proposé.',
 'Les comptes historiques publiés dans une annexe ne sont pas assimilés à des objectifs futurs : leur exercice et leur édition source sont conservés.',
 'Annexes PLFSS 2027 1 à 8 annoncées à venir sur la page DSS consultée. Pas de LFSS 2027 votée ni d’exécution annuelle 2026–2027 complète dans ce lot.',
 'Les détails par nature de recettes, prestations, organismes, dette et réserves présents dans les annexes restent à qualifier. Le téléchargement n’est pas une intégration chiffrée.',
 'La collecte ne comporte pas encore de vecteurs. La taille annoncée correspond aux fichiers récupérés, pas à un index dense/sparse.'],data_version=store.meta()['data_version'])
delivery=ROOT/'reports/delivery-check.json'
if delivery.is_file():
 checks=json.loads(delivery.read_text(encoding='utf-8'))
 if checks['data_version']==result['data_version']:
  result['source_notices']=checks.get('source_arithmetic_notices',[])
  documented=sum(n.get('status')=='source_difference_documented_values_retained' for n in result['source_notices'])
  result['notes'].append(f"{len(result['source_notices'])} lignes sources présentent un écart entre recettes moins dépenses et solde publié au-delà des arrondis. {documented} rapprochements documentaires sont expliqués dans leurs preuves. Les valeurs originales restent marquées et conservées ; ces notices ne constituent pas des corrections officielles des publications.")
  result['failed_downloads']=checks['failed_downloads']
  result['notes'].append(f"{len(checks['failed_downloads'])} liens de téléchargement restent en échec ; la liste est conservée dans le bilan de livraison.")
annexes=ROOT/'reports/annex-qualification.json'
if annexes.is_file():
 inventory=json.loads(annexes.read_text(encoding='utf-8'))
 if inventory['data_version']==result['data_version']:
  result['annex_qualification']={k:inventory[k] for k in ('workbooks','worksheets','numeric_cells','status_counts','all_tables_financially_qualified')}
  result['notes'].append(f"{inventory['worksheets']} feuilles de {inventory['workbooks']} classeurs ont un état d’exploitation explicite : montants sélectionnés intégrés, taux, unités mixtes ou rattachement à qualifier. Les cellules numériques inventoriées ne sont pas automatiquement des montants en euros.")
(ROOT/'reports/coverage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
with (ROOT/'reports/donnees-a-traiter.csv').open('w',encoding='utf-8-sig',newline='') as out:
 writer=csv.DictWriter(out,fieldnames=list(rows[0]),delimiter=';');writer.writeheader();writer.writerows([r for r in rows if r['status'] not in ('published',)])
print(json.dumps(summary))

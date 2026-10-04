"""Rapprochements documentaires : conserver les valeurs publiées, ne jamais les corriger par calcul."""
import hashlib,json,sys
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.collect import row,document_worker,atomic,now
from tools.audit_source import check

SUPPORT=[
 ('LFSS 2018 : annexe B examinée au Sénat',2018,'https://www.senat.fr/rap/l17-122/l17-1225.html'),
 ('LFSS 2020 : texte examiné au Sénat, article 1 et annexe B',2020,'https://www.senat.fr/enseance/textes/2019-2020/98.html'),
 ('PLFSS 2022 : texte initial PDF, annexes B et C',2022,'https://www.assemblee-nationale.fr/15/pdf/projets/pl4523.pdf'),
 ('PLFSS 2022 : texte examiné au Sénat, annexe B',2022,'https://www.senat.fr/enseance/textes/2021-2022/118.html'),
 ('PLACSS 2022 : rapport du Sénat sur les corrections incomplètes des comptes 2021',2022,'https://www.senat.fr/rap/l22-789/l22-789_mono.html'),
]

def main():
 data=ROOT/'data'
 sources={s['id']:s for s in json.loads((data/'catalogue/normalized-sources.json').read_text('utf-8'))}
 facts=json.loads((data/'derived/facts.json').read_text('utf-8'))
 notices=json.loads((data/'derived/source-notices.json').read_text('utf-8'))
 support_path=data/'catalogue/reconciliation-sources.json'
 previous={s['url']:s for s in json.loads(support_path.read_text('utf-8'))} if support_path.exists() else {}
 supports=[]
 for title,year,url in SUPPORT:
  s=previous.get(url)
  if not s or s['status']!='downloaded' or not (data/s['path']).is_file():
   s=document_worker(row(title,url,year,'Rapprochement des neuf lignes sources','reconciliation_support'))
  supports.append(s)
  atomic(support_path,supports)
  print(json.dumps(dict(support=title,status=s['status'])),flush=True)
 # Equivalent triplets in other normative/annex tables are comparisons, not substitutions.
 groups=defaultdict(dict)
 for f in facts:
  if f['domain']!='EQUILIBRE':continue
  key=tuple(f.get(k) for k in ('source_id','table_index','exercise','stage','perimeter','entity'))+(f.get('balance_row_index',f['row_index']),)
  groups[key][f['metric']]=f
 out=[]
 for n in notices:
  target=[f for f in facts if f['source_id']==n['source_id'] and f.get('table_index')==n['table_index'] and f['exercise']==n['exercise'] and f['perimeter']==n['perimeter'] and f['entity']==n['entity'] and f.get('balance_row_index',f['row_index'])==n['balance_row_index']]
  assert len(target)==3 and all(check(f,sources[f['source_id']],data) is None for f in target)
  comparisons=[]
  for key,g in groups.items():
   if len(g)!=3 or key[:2]==(n['source_id'],n['table_index']) or key[2]!=n['exercise'] or key[4]!=n['perimeter'] or key[5]!=n['entity']:continue
   r,d,s=(g[m] for m in ('RECETTES','DEPENSES','SOLDE'))
   # Same documentary edition for proposed projections; original audited
   # results may be republished in a later edition, which stays explicit.
   if r['edition']!=target[0]['edition'] and n['stage']!='CONSTATE':continue
   if key[3] not in (n['stage'],'CONSTATE') and not (n['exercise']==2017 and key[3] in ('PLFSS_RECTIF','LFSS_RECTIF')):continue
   if not all(check(f,sources[f['source_id']],data) is None for f in g.values()):continue
   comparisons.append(dict(source_id=key[0],source_sha=r['source_sha'],url=sources[key[0]]['url'],table_index=key[1],balance_row_index=key[6],stage=key[3],edition=r['edition'],values_cents={m:f['amount_cents'] for m,f in g.items()},gap_cents=r['amount_cents']-d['amount_cents']-s['amount_cents']))
  if n['exercise']==2017:
   category='divergence_article_annexe';reason='L’article rectificatif imprime 232,2 / 231,1 / +1,5 Md€. L’annexe B de la même édition imprime 232,6 / 231,1 / +1,5 Md€ pour la vieillesse des régimes de base. Le rapport sénatorial reprend cette seconde série. La différence porte sur les recettes ; le solde de +1,5 n’est pas modifié. Les deux emplacements sont conservés ; l’article n’est pas réécrit à partir de l’annexe.';urls=[SUPPORT[0][2]]
  elif n['source_id']=='JORFARTI000036339114':
   category='divergence_signe_entre_publications';reason='Les recettes et dépenses de la projection sont identiques dans l’annexe JORF et la présentation sénatoriale de l’annexe B. Le JORF porte un solde négatif, alors que l’Assemblée et le Sénat présentent un solde positif pour 2019, 2020 et 2021. Le signe positif concorde avec recettes moins dépenses. Cela documente une divergence de publication ; aucun signe n’est retourné automatiquement dans la valeur JORF.';urls=[SUPPORT[0][2]]
  elif n['source_id']=='JORFARTI000039675325':
   category='divergence_signe_article_annexe';reason='Pour 2018, l’article 1 JORF imprime +1,2 Md€ pour RG+FSV avec 394,6 de recettes et 395,8 de dépenses. L’annexe B et le texte parlementaire examiné présentent −1,2 Md€ pour ce même périmètre. La divergence de signe est localisée et sourcée ; l’article JORF reste conservé avec son avertissement.';urls=[SUPPORT[1][2]]
  elif n['source_id']=='JORFARTI000046791760':
   category='coordination_legislative_incomplete_documentee';reason='Le rapport sénatorial sur le PLACSS 2022 reprend 205,3 / 235,0 / −28,7 Md€ pour la maladie du régime général en 2021 et décrit les coordinations législatives incomplètes après la correction des comptes. Ce commentaire éclaire le contexte mais ne justifie pas à lui seul quel chiffre de la ligne changer. Les trois valeurs légales et l’écart arithmétique restent affichés ; aucune dépense ou recette corrigée n’est inventée.';urls=[SUPPORT[4][2]]
  elif n['entity']=='FSV':
   category='divergence_valeur_annexe_historique';reason='Le PLFSS 2022, y compris son PDF et le texte examiné au Sénat, publie 17,2 / 19,9 / −1,8 Md€ pour le FSV en 2018. L’article 1 et l’annexe B de la LFSS 2020 publient 17,2 / 19,0 / −1,8 Md€ pour 2018. Le montant des dépenses diffère de 0,9 Md€ ; aucune correction formelle du PLFSS 2022 n’a été trouvée dans ce rapprochement. L’ancienne annexe est conservée comme une observation distincte, pas comme un nouveau résultat 2018.';urls=[SUPPORT[1][2],SUPPORT[2][2],SUPPORT[3][2]]
  else:
   category='incoherence_source_reproduite';reason='La projection vieillesse 2023 du PLFSS 2022 imprime 258,9 / 265,6 / −5,7 Md€ : la soustraction donne −6,7. Le PDF initial et le texte parlementaire examiné reproduisent cette série. Aucun rectificatif établissant la valeur à remplacer n’est démontré dans le lot. L’incohérence est donc documentée et reste signalée, sans transformer le résultat calculé en solde officiel.';urls=[SUPPORT[2][2],SUPPORT[3][2]]
  evidence=[dict(id=s['id'],title=s['title'],url=s['url'],path=s.get('path'),sha256=s.get('sha256'),status=s['status'],page_number=165 if s['url'].endswith('pl4523.pdf') else None) for s in supports if s['url'] in urls]
  out.append(dict(key=n['key'],source_sha=n['source_sha'],values_cents=n['values_cents'],category=category,analysis_status='documented_original_values_retained',resolved_value=False,warning_required=True,explanation=reason,comparisons=comparisons,evidence=evidence,checked_at=now()))
 result=dict(data_version=json.loads((ROOT/'reports/normalized.json').read_text('utf-8'))['data_version'],lines=len(out),all_lines_documented=len(out)==len(notices),source_values_changed=0,unresolved_authoritative_corrections=len(out),support_download_failures=[s['url'] for s in supports if s['status']!='downloaded'],items=out)
 atomic(data/'derived/source-reconciliations.json',result)
 atomic(ROOT/'reports/source-reconciliation.json',result)
 print(json.dumps({k:v for k,v in result.items() if k!='items'}),flush=True)

if __name__=='__main__':main()

"""Readable source reconciliation report with the scope of the retained warnings."""
import html,json,sys
from pathlib import Path
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from plfss_service.store import Store,PERIMETERS
from plfss_service.model import BRANCHES,STAGES

def main():
 store=Store(ROOT/'data');report=json.loads((ROOT/'reports/source-reconciliation.json').read_text('utf-8'));esc=html.escape
 def bn(c):return format(Decimal(c)/Decimal(10**11),'f').replace('.',',')
 rows=[];selected=[]
 for i,item in enumerate(report['items'],1):
  sid,table,year,scope,entity,row=item['key'];src=store.source(sid);triplet=item['values_cents'];affected=[]
  for metric in ('RECETTES','DEPENSES','SOLDE'):
   matrix=store.matrix('EQUILIBRE',scope,year,year,metric,(next(n['stage'] for n in json.loads((ROOT/'reports/delivery-check.json').read_text('utf-8'))['source_arithmetic_notices'] if n['key']==item['key']),))
   target=next((r for r in [matrix['total'],*matrix['rows']] if r['entity']==entity),None)
   if target and any(n['key']==item['key'] for n in target['cells'][0].get('source_notices',[])):affected.append(metric)
  item['selected_metrics_current_matrix']=affected
  if affected:selected.append(i)
  numbers=' / '.join(bn(triplet[m]) for m in ('RECETTES','DEPENSES','SOLDE'))
  links=''.join('<li><a href="'+esc(s['url'].split('#')[0]+('#page='+str(s['page_number']) if s.get('page_number') else ''),quote=True)+'">'+esc(s.get('title') or 'Publication officielle')+('</a> · page '+str(s['page_number']) if s.get('page_number') else '</a>')+'</li>' for s in item['evidence'])
  impact='Avertissement associé aux valeurs retenues pour cette étape.' if affected else 'Observation conservée dans les anciennes preuves ; une autre observation est retenue pour cette étape.'
  rows.append(f'<tr><td>{i}</td><td>{year}<br>{esc(PERIMETERS[scope])}<br>{esc(BRANCHES.get(entity,entity))}</td><td>{esc(numbers)} Md€<br><small>Recettes / dépenses / solde</small><br><a href="{esc(src["url"],quote=True)}">Source examinée</a><br>Tableau {table+1}, ligne {row+1}</td><td>{esc(item["explanation"])}<p><strong>{impact}</strong></p><ul>{links}</ul></td></tr>')
 report['currently_selected_source_rows']=len(selected)
 (ROOT/'reports/source-reconciliation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 text='''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PLFSS · neuf lignes sources rapprochées</title><style>body{font:16px/1.6 system-ui,sans-serif;color:#173a55;max-width:1250px;margin:35px auto;padding:0 20px}h1{color:#08183f}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d4e2f1;padding:12px;vertical-align:top;text-align:left}td:last-child{width:55%}.notice{padding:18px;background:#fff8eb;border:1px solid #edcb97;border-radius:10px}a{color:#173a55}</style><h1>PLFSS · neuf lignes sources rapprochées</h1><p class="notice"><strong>Les données copiées sont fidèles aux sources. Les différences entre publications sont maintenant documentées.</strong> Aucun montant n’a été remplacé par une valeur calculée. Un avertissement est conservé lorsque la série source ne respecte pas recettes moins dépenses = solde. Une explication documentaire ne vaut pas rectificatif officiel.</p><p>Les neuf lignes comprennent deux occurrences du même écart vieillesse 2017, dans le projet et dans la loi. Elles concernent des séries historiques ou des anciennes projections ; elles ne remettent pas par elles-mêmes en cause les montants proposés pour 2027.</p><table><thead><tr><th>N°</th><th>Position</th><th>Série publiée</th><th>Rapprochement et portée</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table><p>Les cellules et leurs emplacements ont été relus indépendamment. Les références complémentaires sont téléchargées, leurs empreintes conservées. Les deux lignes du PLFSS 2022 ont également été relues visuellement à la page 165 du PDF officiel.</p><p><a href="BILAN_PREPARATION.html">Bilan général</a> · <a href="source-reconciliation.json">Registre technique</a></p></html>'''
 (ROOT/'reports/RAPPROCHEMENT_9_LIGNES.html').write_text(text,encoding='utf-8')
 print(json.dumps(dict(lines=len(rows),currently_selected_source_rows=len(selected),source_amounts_changed=0)))

if __name__=='__main__':main()

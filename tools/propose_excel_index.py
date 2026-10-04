"""Preview an indexing change; never alter the running preparation contract.

Keep original rows and files as evidence. In the proposed reading only, replace
the repeated trailing None fields by one labelled range. Explicit zero, empty
strings, formulas, errors and interior None fields are always retained.
"""
from pathlib import Path
import ast, gzip, hashlib, html, json, re, sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'vectorization'

def row_preview(row,headers,row_number):
 end=max((i+1 for i,v in enumerate(row) if v is not None),default=0)
 cells=[]
 for i,value in enumerate(row[:end],1):
  if value is None:text='[ABSENT NULL]'
  elif value=='':text='[VIDE chaîne vide]'
  elif isinstance(value,(dict,list)):text=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
  else:text=str(value)
  label=str(headers[i-1]) if i<=len(headers) else ''
  cells.append(f'Colonne {i}'+(f' [en-tête candidat {label}]' if label else '')+' : '+text)
 tail=None
 if end<len(row):
  tail=dict(first_column=end+1,last_column=len(row),count=len(row)-end,state='NULL',source_row=row_number)
  cells.append(f'Colonnes {end+1} à {len(row)} : {len(row)-end} cellules [ABSENT NULL], conservées dans la preuve originale.')
 return dict(text=f'Ligne {row_number}. '+' | '.join(cells),tail=tail,
             retained_values=row[:end],original_column_count=len(row),row_number=row_number)

def main():
 from tokenizers import Tokenizer
 tokenizer=Tokenizer.from_file(str(OUT/'assets/tokenizer.json'));tokenizer.no_truncation();tokenizer.no_padding()
 code=OUT/'code/prepare_complement_final_contract.py'
 tree=ast.parse(code.read_text('utf-8'));definitions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='natural_chunks']
 env={'re':re};exec(compile(ast.Module(body=definitions,type_ignores=[]),str(code),'exec'),env)
 bysha={x['source']['sha256']:x for x in json.loads((OUT/'source-inventory.json').read_text('utf-8'))['items']}
 examples=[]
 for p in sorted((OUT/'documents').glob('*.jsonl.gz.partial')):
  latest=None
  try:
   with gzip.open(p,'rt',encoding='utf-8') as f:
    for line in f:latest=json.loads(line)
  except (EOFError,OSError):pass
  if not latest or latest['record']['kind']!='table':continue
  rec=latest['record'];source=bysha[p.name.split('.')[0]]['source'];rows=rec['rows'];headers=rec.get('header_candidates',[])
  proposed=[row_preview(row,headers,number) for number,row in enumerate(rows,rec.get('row_start',1))]
  context=f'PLFSS. Source officielle. Années documentaires : {source["publication_year"]}. {source["family"]}. {rec["sheet"]}'
  chunks=env['natural_chunks'](tokenizer,context,[x['text'] for x in proposed])
  for original,alternative in zip(rows,proposed):
   reconstructed=alternative['retained_values']+[None]*(alternative['tail']['count'] if alternative['tail'] else 0)
   assert reconstructed==original
  examples.append(dict(source_id=source['id'],source_sha256=source['sha256'],url=source['url'],
    sheet=rec['sheet'],row_start=rec['row_start'],original_columns=len(rows[0]),
    original_chunks=len(latest['chunks']),original_tokens=sum(x['tokens'] for x in latest['chunks']),
    proposed_chunks=len(chunks),proposed_tokens=sum(x['tokens'] for x in chunks),
    unchanged_source_values=True,all_nulls_reconstructable=True,proposed_reading=[x['text'] for x in proposed],
    proposed_ranges=[x['tail'] for x in proposed]))
 result=dict(status='proposal_only_not_applied',source_files_changed=False,preparation_contract_changed=False,
             numeric_database_changed=False,paid_compute_authorized=False,gpu_launched=False,
             proposal_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),examples=examples)
 (ROOT/'reports/excel-index-proposal.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 esc=html.escape
 details=''.join(f'<h2>{esc(x["sheet"])} · ligne {x["row_start"]}</h2><p><a href="{esc(x["url"],quote=True)}">Classeur officiel</a> · {x["original_columns"]:,} colonnes conservées dans la preuve.</p><p>Lecture actuelle : {x["original_chunks"]} passages / {x["original_tokens"]:,} tokens. Proposition : {x["proposed_chunks"]} passages / {x["proposed_tokens"]:,} tokens.</p><pre>{esc(chr(10).join(x["proposed_reading"]))}</pre>' for x in examples)
 text='''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PLFSS · proposition pour les grandes plages vides Excel</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:1050px;margin:35px auto;padding:0 22px;color:#173a55}pre{white-space:pre-wrap;background:#f4f7fb;padding:18px;overflow-wrap:anywhere}h1{color:#08183f}</style><h1>Plages vides Excel : proposition d’indexation</h1><p><strong>Proposition préparée, pas appliquée.</strong> Les fichiers, lignes originales, numéros de cellules et nombres restent intégralement conservés. Les blancs intérieurs restent explicités. Seule la répétition finale des champs NULL serait remplacée dans le texte à encoder par une plage numérotée reconstructible.</p><p>Aucun zéro n’est retiré ni créé. Une chaîne vide, une formule ou une erreur est conservée à sa position. Le modèle BGE-M3, dense et sparse, le découpage naturel, la limite de 800 tokens et l’absence de chevauchement restent identiques. Cette représentation Excel constituerait toutefois une adaptation documentée du protocole.</p>'''+details+'''<p>Les deux lectures proposées sont reconstruites et comparées aux lignes originales : aucune valeur ni case NULL perdue. Les passages déjà contrôlés restent disponibles ; aucune vectorisation n’est lancée.</p></html>'''
 (ROOT/'reports/PROPOSITION_PLAGES_VIDES_EXCEL.html').write_text(text,encoding='utf-8')
 print(json.dumps(dict(examples=len(examples),status=result['status'],savings=[dict(source_id=x['source_id'],before=x['original_tokens'],after=x['proposed_tokens']) for x in examples])))

if __name__=='__main__':main()

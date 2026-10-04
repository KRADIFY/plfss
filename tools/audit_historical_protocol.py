"""Read the actual Nos Deniers generation and distinguish its two preparations.

Read-only on historical data. Write only this PLFSS comparison report. Never
change a frozen extractor, financial amount, staged passage or encoder input.
"""
from pathlib import Path
import ast,hashlib,html,json,re,sqlite3,unicodedata
from decimal import Decimal,InvalidOperation

ROOT=Path(__file__).resolve().parents[1]
MAIN=Path('F:/LexMachine/NosDeniers/generation_tables_20260911')
OLD=Path('C:/Users/Jean-Christophe/Documents/ChatGPT/Mises à jour auto/nos_deniers_preparation_20260909')
FINAL=ROOT.parent/'budget/consolidation-vectorisation-20260924/preparation-conforme'

def sha(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def read(path):return json.loads(Path(path).read_text('utf-8'))

def definitions(path,names,env):
 tree=ast.parse(Path(path).read_text('utf-8'))
 nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
 if {n.name for n in nodes}!=set(names):raise ValueError('Historical definition missing')
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env)
 return env

def main():
 config=read(MAIN/'encoding_config.json');gpu=read(MAIN/'gpu_input/contract.json')
 final=read(FINAL/'preparation_contract.json');plfss=read(ROOT/'vectorization/preparation-contract.json')
 db=sqlite3.connect((MAIN/'catalogue.sqlite').as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 try:
  stored=json.loads(db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()[0])
  sample=db.execute("SELECT a.sha256,o.locator,o.kind,p.tokens,p.text FROM assets a JOIN occurrences o ON o.asset_sha256=a.sha256 JOIN passages p ON p.id=o.passage_id WHERE a.sha256=? LIMIT 3",('b8ffda3b198a83cefbf6bf72ec08512d3e65cf618de4883c11b6cdefe8a1457a',)).fetchall()
 finally:db.close()
 if not sample:raise ValueError('Actual historical Excel sample unavailable')
 assert config['overlap_max_tokens']==stored['overlap_max_tokens']==150
 assert all(r['kind']=='table_rows' and '[ABSENT NULL]' not in r['text'] for r in sample)
 same_encoder=(gpu['model']==final['model']==plfss['model'] and
  gpu['revision']==final['revision']==plfss['revision'] and
  gpu['max_tokens']==final['max_tokens']==plfss['max_tokens']==800 and
  gpu['dimension']==plfss['dense_dimensions']==1024 and
  gpu['dense_dtype']==plfss['dense_dtype']=='float16' and
  gpu['dense_normalized']==plfss['dense_normalized'] is True and
  gpu['sparse_dtype']==plfss['sparse_dtype']=='float32' and
  gpu['colbert']==plfss['colbert'] is False and
  config['tokenizer_sha256']==final['tokenizer_sha256']==plfss['tokenizer_sha256'])
 assert same_encoder
 hashes=[]
 for name,original in [('common.py',OLD/'common.py'),('extractors.py',OLD/'extractors.py'),('prepare_vectorisation_tables.py',MAIN/'runtime/prepare_vectorisation_tables.py')]:
  frozen=ROOT/'vectorization/code'/name
  hashes.append(dict(name=name,historical_path=str(original),historical_sha256=sha(original),plfss_path=str(frozen),plfss_sha256=sha(frozen),identical=sha(original)==sha(frozen)))
 assert all(r['identical'] for r in hashes)
 env={'re':re,'json':json,'unicodedata':unicodedata}
 definitions(OLD/'common.py',{'clean','dumps'},env)
 definitions(OLD/'prepare.py',{'table_lines'},env)
 table=dict(rows=[[None,'',0,'0','0,0','—','sans objet',None]],row_start=17)
 before=json.dumps(table,ensure_ascii=False,sort_keys=True)
 lines=list(env['table_lines'](table,['Vide NULL','Chaîne vide','Zéro numérique','Zéro texte','Zéro décimal','Tiret','Non applicable','Fin NULL']))
 assert json.dumps(table,ensure_ascii=False,sort_keys=True)==before
 assert len(lines)==1 and 'Ligne 17.' in lines[0]
 assert all(f'Colonne {i} ' in lines[0] for i in (3,4,5,6,7))
 assert all(f'Colonne {i} ' not in lines[0] for i in (1,2,8))
 zero_path=ROOT.parent/'budget/auditeur-independant/zeros.py'
 zero=definitions(zero_path,{'meaning'},{'re':re,'Decimal':Decimal,'InvalidOperation':InvalidOperation})['meaning']
 cases=[]
 for raw,expected in [(None,'source_blank'),('','source_blank'),('0','source_zero'),('0,0','source_zero'),('—','source_dash'),('sans objet','source_not_applicable'),('non applicable','source_not_applicable')]:
  status,value=zero(raw);assert status==expected
  cases.append(dict(raw=raw,status=status,numeric_value=str(value) if value is not None else None))
 receipt=read(MAIN/'table_integration_receipt.json');docs=receipt['documents']
 result=dict(encoder_identical=True,tokenizer_sha256=plfss['tokenizer_sha256'],model=gpu['model'],revision=gpu['revision'],dense_dimensions=1024,dense_dtype='float16',dense_normalized=True,sparse_dtype='float32',colbert=False,max_tokens=800,
  historical_main=dict(path=str(MAIN),contract_sha256=sha(MAIN/'gpu_input/contract.json'),stored_initial_overlap_max_tokens=150,pdf_pages=sum(d['pages'] for d in docs),pdf_pages_replaced_with_table_revision=sum(d.get('replaced_pages',0) for d in docs),excel_empty_fields_in_raw_proof=True,excel_empty_fields_repeated_in_encoded_text=False,excel_rows_grouped_at=32,table_lines_code_sha256=sha(OLD/'prepare.py'),actual_excel_sample=[dict(source_sha256=r['sha256'],locator=r['locator'],kind=r['kind'],tokens=r['tokens'],text_sha256=hashlib.sha256(r['text'].encode('utf-8')).hexdigest()) for r in sample]),
  historical_final=dict(path=str(FINAL),contract_sha256=sha(FINAL/'preparation_contract.json'),artificial_overlap=final['artificial_overlap'],excel_empty_fields_explicit_in_encoded_text=True),
  plfss_current=dict(preparation_identity=plfss['preparation_identity'],uses_final_complement_serialization=True,strictly_identical_to_whole_main_preparation=False),
  shared_code=hashes,original_excel_sample_input=table,original_excel_serialized_lines=lines,zero_semantics=cases,zero_semantics_code_sha256=sha(zero_path),
  user_instruction='Reprendre exactement la méthode utilisée pour Nos Deniers ; aucune autorisation de compacter les NULL.',
  invented_range_compaction_enabled=False,financial_database_modified=False,original_source_files_modified=False,gpu_launched=False,paid_compute_authorized=False,
  conclusion='Les paramètres BGE-M3 et le tokenizer correspondent. La grande base et le contrat final des compléments ne constituent pas une préparation de texte uniforme : overlap historique 150 pour les passages initiaux, remplacements de pages PDF sans duplication de caractères ; Excel sans blancs sérialisés dans la grande base, blancs explicités dans les compléments. L’utilisateur demande la méthode de la grande base : aligner la préparation sur ce profil, préserver les points existants et contrôler cet alignement avant toute entrée GPU ; aucune plage compacte artificielle.')
 path=ROOT/'reports/comparaison-protocole-nos-deniers.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
 text='''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PLFSS · vérification du protocole Nos Deniers</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:1050px;margin:35px auto;padding:0 22px;color:#173a55}table{border-collapse:collapse;width:100%;margin:22px 0}td,th{border:1px solid #d9e4ef;padding:12px;text-align:left;vertical-align:top}th{background:#f4f7fb}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7fb;padding:18px}h1{color:#08183f}</style><h1>Reprendre la méthode effectivement utilisée</h1><p><strong>L’encodeur et les règles des zéros correspondent ; la préparation historique du texte a évolué.</strong> Cette comparaison lit le catalogue réel de la grosse base, ses contrats, le code d’origine et le contrat final des compléments. Aucun montant, document, passage préparé ou index historique n’est modifié.</p><table><tr><th>Point</th><th>Grande base Nos Deniers</th><th>Contrat final des compléments / PLFSS en préparation</th></tr><tr><td>Encodage</td><td colspan="2">BAAI/bge-m3, même révision et tokenizer ; dense 1 024 dimensions float16 normalisé ; sparse float32 ; ColBERT désactivé ; 800 tokens maximum.</td></tr><tr><td>Chevauchement</td><td>La configuration et le catalogue initial portent un maximum de 150 tokens. Les pages PDF remplacées par la révision des tableaux conservent leurs caractères sans chevauchement.</td><td>Le découpage final emploie zéro chevauchement artificiel. Cela ne prouve pas que tous les anciens passages avaient déjà ce fonctionnement.</td></tr><tr><td>Cases Excel vides</td><td>Conservées dans les lignes sources ; omises du texte à encoder. Les autres cellules gardent leur numéro original. Jusqu’à 32 lignes regroupées.</td><td>Les blancs sont explicités cellule par cellule dans le texte à encoder. C’est ce qui produit des milliers de NULL dans certains classeurs PLFSS très larges.</td></tr><tr><td>Zéros</td><td colspan="2">Un zéro explicitement publié reste un zéro. Un blanc, un tiret ou une mention « non applicable » ne devient pas automatiquement zéro. Les preuves gardent leurs coordonnées et leurs valeurs sources.</td></tr></table><h2>Contrôle du sérialiseur Excel d’origine</h2><p>La ligne originale conserve ses huit cases. Le texte ci-dessous garde les colonnes 3 à 7 à leur position ; il ne crée ni zéro ni plage fictive pour les cases vides 1, 2 et 8.</p><pre>'''+html.escape(lines[0])+'''</pre><p><strong>La proposition de plage compacte n’est pas activée.</strong> La préparation actuelle doit être alignée avec le profil historique retenu et contrôlée avant toute entrée GPU. Aucun encodage payant lancé.</p></html>'''
 (ROOT/'reports/COMPARAISON_PROTOCOLE_NOS_DENIERS.html').write_text(text,'utf-8')
 print(json.dumps(dict(encoder_identical=True,shared_original_files_verified=len(hashes),zero_cases_verified=len(cases),main_vs_final_preparation_different=True,range_compaction_enabled=False,gpu_launched=False)))

if __name__=='__main__':main()

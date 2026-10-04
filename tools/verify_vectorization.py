"""Independent audit of staged characters, token counts and export references.

This verifier never calls an encoder. It can audit completed document
checkpoints while the preparation continues; a full input is only approved
after the closed export and every document have passed.
"""
from pathlib import Path
import argparse,collections,gzip,hashlib,json,re,sqlite3,sys,unicodedata
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'vectorization'

def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def save(path,obj):
 p=Path(path);tmp=p.with_name(p.name+'.partial');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)

def recover(chunks,field='block'):
 fields=collections.defaultdict(str)
 for c in chunks:
  for s in c.get('segments',[]):
   key=s.get(field)
   if key is None:continue
   if len(fields[key])!=s['char_start']:raise ValueError('Lost/repeated character boundary')
   if s['char_end']-s['char_start']!=len(s['text']):raise ValueError('Wrong source character length')
   if fields[key] and s['text'] and not (fields[key][-1].isspace() or s['text'][0].isspace()):raise ValueError('Source word split')
   fields[key]+=s['text']
 return fields

def literal_table_lines(rec):
 lines=[];headers=rec.get('header_candidates',[])
 for rowno,row in enumerate(rec['rows'],rec.get('row_start',1)):
  cells=[]
  for i,value in enumerate(row,1):
   if value is None:text='[ABSENT NULL]'
   elif value=='':text='[VIDE chaîne vide]'
   elif isinstance(value,(dict,list)):text=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
   else:text=str(value)
   label=str(headers[i-1]) if i<=len(headers) else ''
   cells.append(f'Colonne {i}'+(f' [en-tête candidat {label}]' if label else '')+' : '+text)
  lines.append(f'Ligne {rowno}. '+' | '.join(cells))
 return lines

def verify_record(obj,tokenizer):
 rec=obj['record'];chunks=obj['chunks'];critical=[]
 for ch in chunks:
  count=len(tokenizer.encode(ch['text'],add_special_tokens=True).ids)
  if count!=ch['tokens'] or not 0<count<=800:raise ValueError('Incorrect token count/budget')
  if ch['record_ref']!=obj['record_ref']:raise ValueError('Broken evidence reference')
  if ch['quality']['allow_automatic_numeric_fact'] is not False:raise ValueError('Unsupported certified numeric claim')
 if rec['kind']=='text':
  fields=recover(chunks)
  if fields.get(0,'')!=rec['text'] or len(fields)!=1:raise ValueError('Text paragraph changed')
 elif rec['kind']=='table':
  fields=recover(chunks);expected=literal_table_lines(rec)
  if [fields.get(i,'') for i in range(len(expected))]!=expected or len(fields)!=len(expected):raise ValueError('Table cell text changed')
 elif rec['kind']=='page':
  raw=[c for c in chunks if c.get('kind')=='page_source_text'];fields=recover(raw)
  blocks=[str(b.get('text','')) for b in rec.get('blocks',[])]
  for i,body in enumerate(blocks):
   if fields.get(i,'')!=body:raise ValueError('Positioned PDF text changed')
  words=collections.Counter(w[4] for w in rec.get('words',[]))
  text=' '.join(fields.values())
  # Punctuation joins can differ between PDF words and blocks; every source
  # word must still occur verbatim in the retained raw reading.
  normalized=unicodedata.normalize('NFC',text)
  if any(unicodedata.normalize('NFC',word) not in normalized for word in words):raise ValueError('Positioned PDF word omitted')
  for issue in rec.get('issues',[]):
   if issue.startswith('ocr_failed:') or issue=='image_page_without_recoverable_text':critical.append(dict(page=rec['page'],issue=issue,image_count=rec.get('image_count',0)))
  for ch in chunks:
   if ch.get('page')!=rec['page']:raise ValueError('Wrong physical PDF page')
 return critical

def main(available=False):
 from tokenizers import Tokenizer
 config=json.loads((OUT/'preparation-contract.json').read_text('utf-8'))
 reviews_path=OUT/'page-reviews.json'
 reviews=json.loads(reviews_path.read_text('utf-8')) if reviews_path.is_file() else []
 assert sha(OUT/'assets/tokenizer.json')==config['tokenizer_sha256']
 assert sha(OUT/'code/plfss_preparation_adapter.py')==config['adapter_sha256']
 for name,value in config['code'].items():assert sha(OUT/'code'/name)==value
 tk=Tokenizer.from_file(str(OUT/'assets/tokenizer.json'));tk.no_truncation();tk.no_padding()
 items=json.loads((OUT/'source-inventory.json').read_text('utf-8'))['items'];bysha={i['source']['sha256']:i for i in items}
 audit_dir=OUT/'audit';audit_dir.mkdir(exist_ok=True);results=[];errors=[];critical=[]
 for receipt_path in sorted((OUT/'documents').glob('*.receipt.json')):
  receipt=json.loads(receipt_path.read_text('utf-8'));source=bysha[receipt['source_sha256']]['source'];p=OUT/receipt['path'];cached=audit_dir/(receipt['source_sha256']+'.json')
  try:
   actual_source=sha(ROOT/'data'/source['path']);actual_stage=sha(p)
   guard=receipt.get('serialization_token_guard')
   actual_guard=sha(OUT/guard['path']) if guard else ''
  except Exception as e:
   errors.append(dict(source_sha256=receipt['source_sha256'],source_id=source['id'],error=str(e),type=type(e).__name__));continue
  identity=digest(config['preparation_identity']+sha(Path(__file__))+receipt['sha256']+actual_source+actual_stage+actual_guard+json.dumps(guard,sort_keys=True)+(sha(reviews_path) if reviews_path.is_file() else ''))
  if cached.exists() and json.loads(cached.read_text('utf-8'))['audit_identity']==identity:
   r=json.loads(cached.read_text('utf-8'));results.append(r);critical+=r['critical_pages'];continue
  try:
   assert actual_source==receipt['source_sha256']
   assert actual_stage==receipt['sha256'] and receipt['preparation_identity']==config['preparation_identity']
   if guard:=receipt.get('serialization_token_guard'):
    assert sha(OUT/guard['path'])==guard['code_sha256'] and guard['max_contract_tokens']==800
    assert guard['extractor_changed'] is False and guard['source_text_conserved'] is True
   counts=collections.Counter();pages=[]
   with gzip.open(p,'rt',encoding='utf-8') as stream:
    for line in stream:
     obj=json.loads(line);rec=obj['record'];assert rec['record_number']==counts['records']+1
     for issue in verify_record(obj,tk):
      matched=[r for r in reviews if r['source_sha256']==receipt['source_sha256'] and r['page']==issue['page'] and r['status']=='visually_verified_blank_graphic_page']
      if len(matched)==1 and (ROOT/matched[0]['rendered_path']).is_file() and sha(ROOT/matched[0]['rendered_path'])==matched[0]['rendered_sha256']:
       continue
      pages.append(dict(issue,source_sha256=receipt['source_sha256'],source_id=source['id'],source_path=source['path']))
     counts['records']+=1;counts['chunks']+=len(obj['chunks']);counts['tokens']+=sum(c['tokens'] for c in obj['chunks'])
   assert all(counts[k]==receipt[k] for k in ('records','chunks','tokens'))
   r=dict(source_sha256=receipt['source_sha256'],audit_identity=identity,passed=True,critical_pages=pages,**counts)
   save(cached,r);results.append(r);critical+=pages
  except Exception as e:errors.append(dict(source_sha256=receipt['source_sha256'],source_id=source['id'],error=str(e),type=type(e).__name__))
  if (len(results)+len(errors))%50==0:print(json.dumps(dict(documents_verified=len(results),errors=len(errors),expected=len(items))),flush=True)
 summary=dict(documents_verified=len(results),documents_expected=len(items),passages_checked=sum(r['chunks'] for r in results),tokens_checked=sum(r['tokens'] for r in results),errors=errors,critical_pages=critical,all_documents_checked=len(results)==len(items),input_checked=False,paid_compute_authorized=False,gpu_launched=False,manual_page_reviews=reviews)
 if not available:
  status=json.loads((OUT/'export-status.json').read_text('utf-8'))
  if not status.get('complete') or status.get('documents_prepared')!=len(items) or status.get('documents_expected')!=len(items):
   errors.append(dict(error='export_not_complete_for_current_inventory'))
  if status['input_sha256']!=sha(OUT/'gpu_input/public.bge-m3.jsonl'):errors.append(dict(error='input_hash_changed'))
  if status['catalogue_sha256']!=sha(OUT/'catalogue.sqlite'):errors.append(dict(error='catalogue_hash_changed'))
  with sqlite3.connect((OUT/'catalogue.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
   assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
   expected_sources={(r['id'],i['source']['sha256']) for i in items for r in i['references']}
   if set(db.execute('SELECT id,asset_sha FROM sources'))!=expected_sources:errors.append(dict(error='catalogue_source_inventory_differs'))
   if db.execute('SELECT COUNT(*) FROM records').fetchone()[0]!=sum(r['records'] for r in results):errors.append(dict(error='catalogue_record_count_differs'))
   if db.execute('SELECT COUNT(*) FROM occurrences').fetchone()[0]!=sum(r['chunks'] for r in results):errors.append(dict(error='catalogue_occurrence_count_differs'))
   rows=db.execute('SELECT id,text,tokens FROM passages ORDER BY id');n=t=0
   with (OUT/'gpu_input/public.bge-m3.jsonl').open(encoding='utf-8') as f:
    for line in f:
     row=next(rows,None);obj=json.loads(line)
     if row is None or tuple(obj[k] for k in ('id','text','tokens'))!=row:raise ValueError('GPU input differs from evidence catalogue')
     assert obj['id']==digest('public\n'+obj['text']);assert obj['tokens']==len(tk.encode(obj['text']).ids)<=800
     n+=1;t+=obj['tokens']
   assert next(rows,None) is None and n==status['passages'] and t==status['tokens']
   broken=db.execute('SELECT COUNT(*) FROM occurrences o LEFT JOIN passages p ON p.id=o.passage_id LEFT JOIN records r ON r.id=o.record_ref WHERE p.id IS NULL OR r.id IS NULL').fetchone()[0]
   assert not broken
  summary.update(input_checked=True,input_sha256=status['input_sha256'],export_complete=status['complete'])
 summary['passed']=not errors and not critical and summary['all_documents_checked'] and summary['input_checked']
 save(OUT/('preparation-audit.partial.json' if available else 'preparation-audit.json'),summary)
 print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--available',action='store_true');main(parser.parse_args().available)

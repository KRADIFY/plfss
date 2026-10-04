"""Local, resumable PLFSS preparation using the frozen Nos Deniers extractors.

No encoder, GPU, external API write or deployment. Staged source records remain
beside every passage; the numeric application database is never opened for write.
"""
from pathlib import Path
import argparse,ast,collections,concurrent.futures,gzip,hashlib,importlib,importlib.metadata,json,os,re,shutil,sqlite3,sys,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'vectorization'
HIST=ROOT.parent/'budget/consolidation-vectorisation-20260924/preparation-conforme'
OLD=Path('C:/Users/Jean-Christophe/Documents/ChatGPT/Mises à jour auto/nos_deniers_preparation_20260909')

def dump(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def save(path,obj):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.partial');temp.write_text(dump(obj)+'\n',encoding='utf-8');os.replace(temp,path)

def freeze():
 contract=json.loads((HIST/'preparation_contract.json').read_text('utf-8'))
 expected={Path(p).name:h for p,h in contract['code'].items()}
 origins={'common.py':OLD/'common.py','extractors.py':OLD/'extractors.py',
  'prepare_complement_final_contract.py':HIST/'code/original/prepare_complement_final_contract.py',
  'prepare_vectorisation_tables.py':HIST/'code/original/prepare_vectorisation_tables.py',
  'vectorisation_table_geometry.py':ROOT.parent/'budget/tools/vectorisation_table_geometry.py',
  'vectorisation_table_text.py':ROOT.parent/'budget/tools/vectorisation_table_text.py',
  'vectorisation_table_text_word_safe.py':HIST/'code/vectorisation_table_text_word_safe.py'}
 files={}
 for name,p in origins.items():
  h=sha(p)
  if name in expected and h!=expected[name]:raise ValueError('Historical extractor changed: '+name)
  target=OUT/'code'/name;target.parent.mkdir(parents=True,exist_ok=True)
  if target.exists() and sha(target)!=h:raise ValueError('Preserve incompatible frozen file: '+str(target))
  if not target.exists():shutil.copyfile(p,target)
  files[name]=h
 config=json.loads((OLD/'config.json').read_text('utf-8'))
 tokenizer=Path(config['tokenizer']);assert sha(tokenizer)==contract['tokenizer_sha256']
 target=OUT/'assets/tokenizer.json';target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():shutil.copyfile(tokenizer,target)
 assert sha(target)==contract['tokenizer_sha256']
 settings=dict(model=contract['model'],revision=contract['revision'],tokenizer_sha256=contract['tokenizer_sha256'],
  dense_dimensions=1024,dense_dtype='float16',dense_normalized=True,sparse_dtype='float32',colbert=False,
  max_tokens=800,artificial_overlap=0,truncate=False,context_included_in_token_limit=True,word_boundaries=True,
  part_size=8192,allow_automatic_numeric_fact=False,reference_contract_id=contract['contract_id'],code=files,
  adapter_sha256=sha(Path(__file__)),python=sys.version.split()[0],
  libraries={m:importlib.metadata.version(m) for m in ('PyMuPDF','tokenizers','beautifulsoup4','openpyxl','lxml')},
  tessdata=config['tessdata'],gpu_launched=False,paid_compute_authorized=False)
 settings['preparation_identity']=digest(dump(settings))
 path=OUT/'preparation-contract.json'
 if path.exists() and json.loads(path.read_text('utf-8'))['preparation_identity']!=settings['preparation_identity']:
  raise ValueError('Existing preparation belongs to another code/runtime; keep it separately')
 save(path,settings);return settings

_runtime=None
def runtime(settings):
 global _runtime
 if _runtime is not None:return _runtime
 sys.path.insert(0,str(OUT/'code'))
 import extractors,prepare_vectorisation_tables as tables,vectorisation_table_text_word_safe as safe
 from tokenizers import Tokenizer
 # Use the final historical word-safe table serializer, including its original
 # evidence fields. Do not execute the old project's controller or hardcoded paths.
 tables.serialize_table=safe.serialize_table
 source=OUT/'code/prepare_complement_final_contract.py'
 tree=ast.parse(source.read_text('utf-8'));names={'dump','natural_chunks','tab_text'}
 defs=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
 env={'json':json,'re':re};exec(compile(ast.Module(body=defs,type_ignores=[]),str(source),'exec'),env)
 tk=Tokenizer.from_file(str(OUT/'assets/tokenizer.json'));tk.no_truncation();tk.no_padding()
 _runtime=(extractors,tables,tk,env);return _runtime

def boundary_check(chunks):
 fields=collections.defaultdict(list)
 for c in chunks:
  for s in c.get('segments',[]):fields[(c.get('table_ref',''),s.get('field_ref',s.get('block')))].append(s)
 for segs in fields.values():
  for a,b in zip(segs,segs[1:]):
   if a['char_end']!=b['char_start']:raise ValueError('Gap or overlap in source characters')
   if a['text'] and b['text'] and not (a['text'][-1].isspace() or b['text'][0].isspace()):raise ValueError('In-word boundary; preserve source and hold document')

def stage_one(item,settings):
 source=item['source'];path=ROOT/'data'/source['path'];sid=source['sha256']
 output=OUT/'documents'/(sid+'.jsonl.gz');receipt=OUT/'documents'/(sid+'.receipt.json')
 if receipt.exists():
  old=json.loads(receipt.read_text('utf-8'))
  if old['preparation_identity']!=settings['preparation_identity'] or sha(output)!=old['sha256']:raise ValueError('Staged checkpoint changed')
  return old
 assert sha(path)==sid
 extractors,tables,tk,functions=runtime(settings)
 ctx=('PLFSS. Source officielle. Années documentaires : '+', '.join(map(str,item['years']))+'. '+source['family']+'. ')
 counts=collections.Counter();headers={};started=time.time();output.parent.mkdir(parents=True,exist_ok=True)
 temp=output.with_name(output.name+'.partial')
 def write(stream,record,chunks):
  no=counts['records']+1;loc=record.get('locator') or f'paragraph:{no}'
  record=dict(record,locator=loc,record_number=no,source_sha256=sid)
  # A physical article ID/number stays in the source-reference catalogue.
  quality=dict(source_kind='source_'+item['format'],table_layout='candidate_not_certified' if record['kind']=='table' else 'positioned_source' if item['format']=='pdf' else 'original_structure_retained',numeric_status='raw_not_validated_facts',allow_automatic_numeric_fact=False,header_status='source_candidates_not_certified',null_is_not_zero=True)
  ref=digest(sid+'\n'+loc+'\n'+dump(record))
  for n,c in enumerate(chunks,1):
   c['locator']=c.get('locator') or loc+f'/part:{n}'
   c['quality']=quality|c.get('quality',{});c['record_ref']=ref
   assert c['quality']['allow_automatic_numeric_fact'] is False
   assert 0<c['tokens']==len(tk.encode(c['text']).ids)<=800
  boundary_check(chunks)
  stream.write(dump(dict(record_ref=ref,record=record,chunks=chunks,quality=quality))+'\n')
  counts['records']+=1;counts['chunks']+=len(chunks);counts['tokens']+=sum(c['tokens'] for c in chunks)
  if counts['records']%100==0:save(OUT/'progress'/(sid+'.json'),dict(source_id=source['id'],**counts,elapsed=round(time.time()-started,1)))
 with gzip.open(temp,'wt',encoding='utf-8',compresslevel=3) as stream:
  if item['format']=='pdf':
   import fitz
   with fitz.open(path) as doc:
    for rec in extractors.pdf_records(path,settings):
     counts['pages']+=1
     payload=tables.page_payload(rec,doc[rec['page']-1],sid,tk,ctx)
     if payload['review_required']:
      chunks=payload['chunks'];rec=dict(rec,review=payload);counts['table_review_pages']+=1;counts['tables']+=len(payload['tables'])
     else:chunks=tables.raw_chunks(rec,sid,tk)
     rec=dict(rec,locator=f'page:{rec["page"]}')
     counts['ocr_pages']+=rec['method'].startswith('ocr');counts['pages_with_alerts']+=bool(rec.get('issues'))
     for c in chunks:c.update(page=rec['page'],page_label=rec.get('page_label'),paragraph_number_kind='extractor_block_order_not_official_number')
     write(stream,rec,chunks)
  else:
   for rec in extractors.records(path,item['format'],settings):
    kind=rec['kind'];section=rec.get('section') or rec.get('sheet') or ''
    if kind=='structure':write(stream,rec,[]);continue
    if kind=='table':
     candidates=headers.setdefault(rec.get('sheet',''),[]) if item['format']=='xlsx' else []
     if len(candidates)<5:candidates.extend(rec['rows'][:5-len(candidates)])
     names=rec.get('header',{}).get('names') or []
     if not names and candidates:names=[' / '.join(str(row[c]) for row in candidates if c<len(row) and row[c] is not None)[:120] for c in range(max(map(len,candidates)))]
     rec=dict(rec,header_candidates=names,header_assignment='candidate_not_certified',null_is_not_zero=True)
     chunks=functions['natural_chunks'](tk,ctx+section,functions['tab_text'](rec,names));counts['table_rows']+=len(rec['rows'])
    else:chunks=functions['natural_chunks'](tk,ctx+section,[rec['text']])
    write(stream,rec,chunks)
 os.replace(temp,output)
 result=dict(source_sha256=sid,source_id=source['id'],sha256=sha(output),path=output.relative_to(OUT).as_posix(),preparation_identity=settings['preparation_identity'],**counts,elapsed_seconds=round(time.time()-started,2))
 save(receipt,result);return result

def inventory():
 sources=json.loads((ROOT/'data/catalogue/normalized-sources.json').read_text('utf-8'))
 extra=ROOT/'data/catalogue/reconciliation-sources.json'
 if extra.exists():sources+=json.loads(extra.read_text('utf-8'))
 grouped={};omitted=[]
 for s in sources:
  if s['status']!='downloaded':omitted.append(dict(id=s['id'],reason='download_failed'));continue
  ext=Path(s['path']).suffix.lower();fmt={'pdf':'pdf','xlsx':'xlsx','html':'html','htm':'html','asp':'html','csv':'csv'}.get(ext.lstrip('.'))
  if fmt is None:omitted.append(dict(id=s['id'],reason='archive_container_children_catalogued' if ext=='.zip' else 'unsupported_format'));continue
  item=grouped.setdefault(s['sha256'],dict(source=s,format=fmt,references=[],years=[]))
  item['references'].append(s)
  if s['publication_year'] not in item['years']:item['years'].append(s['publication_year'])
 items=list(grouped.values())
 # Start small representative sources and every format; long annual reports
 # remain checkpointed independently and never block saving other receipts.
 items.sort(key=lambda x:(x['source']['bytes'],x['source']['id']))
 save(OUT/'source-inventory.json',dict(items=items,omitted=omitted,source_entries=len(sources)))
 return items

def export(settings,items,receipts,failures):
 target=OUT/'catalogue.sqlite';temp=OUT/'catalogue.new.sqlite';temp.unlink(missing_ok=True)
 db=sqlite3.connect(temp)
 db.executescript('CREATE TABLE sources(id TEXT PRIMARY KEY,asset_sha TEXT,metadata TEXT);CREATE TABLE passages(id TEXT PRIMARY KEY,text TEXT,tokens INTEGER);CREATE TABLE occurrences(id TEXT PRIMARY KEY,passage_id TEXT,asset_sha TEXT,record_ref TEXT,locator TEXT,chunk_json TEXT);CREATE TABLE records(id TEXT PRIMARY KEY,asset_sha TEXT,record_no INTEGER,locator TEXT,staged_path TEXT);CREATE INDEX passage_occurrence ON occurrences(passage_id);')
 done={r['source_sha256']:r for r in receipts};count=0
 for item in items:
  sid=item['source']['sha256']
  for ref in item['references']:db.execute('INSERT INTO sources VALUES(?,?,?)',(ref['id'],sid,dump(ref)))
  if sid not in done:continue
  receipt=done[sid];p=OUT/receipt['path'];assert sha(p)==receipt['sha256']
  with gzip.open(p,'rt',encoding='utf-8') as stream:
   for line in stream:
    obj=json.loads(line);rec=obj['record'];ref=obj['record_ref']
    db.execute('INSERT INTO records VALUES(?,?,?,?,?)',(ref,sid,rec['record_number'],rec['locator'],receipt['path']))
    for no,ch in enumerate(obj['chunks']):
     ident=digest('public\n'+ch['text']);occ=digest(ref+'\n'+str(no)+'\n'+ident)
     db.execute('INSERT OR IGNORE INTO passages VALUES(?,?,?)',(ident,ch['text'],ch['tokens']))
     db.execute('INSERT INTO occurrences VALUES(?,?,?,?,?,?)',(occ,ident,sid,ref,ch['locator'],dump(ch)));count+=1
  db.commit()
 gpu=OUT/'gpu_input';gpu.mkdir(exist_ok=True);part=gpu/'public.bge-m3.jsonl.partial';n=t=0
 with part.open('w',encoding='utf-8',newline='\n') as f:
  for ident,text,tokens in db.execute('SELECT id,text,tokens FROM passages ORDER BY id'):
   f.write(dump(dict(id=ident,text=text,tokens=tokens))+'\n');n+=1;t+=tokens
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';db.close();os.replace(temp,target)
 output=gpu/'public.bge-m3.jsonl';os.replace(part,output)
 result=dict(state='ready_for_independent_validation' if not failures else 'partial_export_documents_held',complete=not failures,documents_prepared=len(receipts),documents_expected=len(items),passages=n,occurrences=count,tokens=t,input_bytes=output.stat().st_size,input_sha256=sha(output),catalogue_sha256=sha(target),failures=failures,gpu_launched=False,paid_compute_authorized=False,ocr_pages=sum(r.get('ocr_pages',0) for r in receipts),pages_with_alerts=sum(r.get('pages_with_alerts',0) for r in receipts),validation_required=True)
 save(OUT/'export-status.json',result)
 save(gpu/'contract.json',settings|result|dict(input=output.name,catalogue='../catalogue.sqlite',input_count=n,input_tokens=t))
 return result

def main(workers=2,limit=0):
 settings=freeze();items=inventory();items=items[:limit] if limit else items
 receipts=[];failures=[];started=time.time()
 with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
  futures={pool.submit(stage_one,item,settings):item for item in items}
  for future in concurrent.futures.as_completed(futures):
   item=futures[future]
   try:result=future.result();receipts.append(result)
   except Exception as e:failures.append(dict(source_id=item['source']['id'],source_sha256=item['source']['sha256'],error=str(e)[:250],type=type(e).__name__))
   status=dict(state='preparing',done=len(receipts),held=len(failures),expected=len(items),passages=sum(r['chunks'] for r in receipts),tokens=sum(r['tokens'] for r in receipts),elapsed_seconds=round(time.time()-started,1),gpu_launched=False)
   save(OUT/'status.json',status);save(OUT/'receipts.json',receipts);save(OUT/'held-documents.json',failures)
   if (len(receipts)+len(failures))%25==0 or failures and failures[-1]['source_id']==item['source']['id']:print(dump(status|dict(last_source=item['source']['id'])),flush=True)
 result=export(settings,items,receipts,failures);save(OUT/'status.json',result);print(dump(result),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=2,choices=(1,2,3,4));parser.add_argument('--limit',type=int,default=0)
 args=parser.parse_args();main(args.workers,args.limit)

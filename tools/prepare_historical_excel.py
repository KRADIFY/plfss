"""Reuse the main Nos Deniers Excel extractor, serializer and chunker unchanged.

Separate checkpoints preserve the previously prepared complement-profile
documents. No encoder input is replaced and no paid computation is started.
"""
from pathlib import Path
import argparse,ast,collections,gzip,hashlib,itertools,json,os,shutil,sys,time,unicodedata,re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'vectorization/historical-main-excel'
HIST=Path('C:/Users/Jean-Christophe/Documents/ChatGPT/Mises à jour auto/nos_deniers_preparation_20260909')

def dump(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
def sha(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.partial');temp.write_text(dump(value)+'\n','utf-8');os.replace(temp,path)
def defs(path,names,env):
 tree=ast.parse(Path(path).read_text('utf-8'));nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names]
 if {n.name for n in nodes}!=set(names):raise ValueError('Historical definition missing')
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env)

def freeze():
 comparison=json.loads((ROOT/'reports/comparaison-protocole-nos-deniers.json').read_text('utf-8'))
 assert comparison['encoder_identical'] and not comparison['invented_range_compaction_enabled']
 code=ROOT/'vectorization/historical-main-code';code.mkdir(exist_ok=True)
 expected={r['name']:r['historical_sha256'] for r in comparison['shared_code']}
 expected['prepare.py']=comparison['historical_main']['table_lines_code_sha256']
 files={}
 for name in ('common.py','extractors.py','prepare.py'):
  origin=HIST/name;target=code/name;value=sha(origin)
  if value!=expected[name]:raise ValueError('Historical code changed: '+name)
  if target.exists() and sha(target)!=value:raise ValueError('Preserve incompatible frozen code')
  if not target.exists():shutil.copyfile(origin,target)
  files[name]=value
 config=json.loads(Path(comparison['historical_main']['path'],'encoding_config.json').read_text('utf-8'))
 config['tokenizer']=str(ROOT/'vectorization/assets/tokenizer.json')
 assert sha(config['tokenizer'])==comparison['tokenizer_sha256']
 assert config['max_tokens_including_context']==800 and config['overlap_max_tokens']==150
 contract=dict(profile='nos-deniers-main-generation-20260911-excel',code=files,extractor_changed=False,serializer_changed=False,chunker_changed=False,
  context_project_name='PLFSS',legacy_overlap_max_tokens=150,max_tokens=800,rows_per_batch=32,source_blank_fields_retained=True,blank_fields_repeated_in_encoder_text=False,
  invented_range_compaction_enabled=False,adapter_sha256=sha(Path(__file__)),tokenizer_sha256=comparison['tokenizer_sha256'],gpu_launched=False,paid_compute_authorized=False)
 contract['identity']=hashlib.sha256(dump(contract).encode('utf-8')).hexdigest()
 dest=OUT/'contract.json'
 if dest.exists() and json.loads(dest.read_text('utf-8'))['identity']!=contract['identity']:raise ValueError('Preserve historical Excel checkpoints from another adapter')
 save(dest,contract);return contract,config,code

def runtime(config,code):
 # Function bodies are executed directly from the frozen historical files.
 # The project's old CLI/database operations are never imported or executed.
 env={'json':json,'re':re,'unicodedata':unicodedata}
 defs(code/'common.py',{'clean','dumps','Chunker'},env)
 defs(code/'prepare.py',{'table_lines','context_for'},env)
 import importlib.util
 if str(code) not in sys.path:sys.path.insert(0,str(code))
 spec=importlib.util.spec_from_file_location('historical_plfss_extractors',code/'extractors.py')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return env,env['Chunker'](config),module

def prepare(item,contract,config,code,pilot_records=0):
 sid=item['source']['sha256'];source=ROOT/'data'/item['source']['path'];assert sha(source)==sid
 directory=OUT/('pilot' if pilot_records else 'documents');directory.mkdir(exist_ok=True)
 dest=directory/(sid+'.jsonl.gz');receipt=directory/(sid+'.receipt.json')
 if receipt.exists():
  old=json.loads(receipt.read_text('utf-8'))
  if old['identity']!=contract['identity'] or sha(dest)!=old['sha256']:raise ValueError('Historical checkpoint changed')
  return old
 env,chunker,extractors=runtime(config,code);started=time.time();counts=collections.Counter();headers={};pending_records=[];pending_lines=[];pending_locators=[];sheet=None
 refs=[dict(years=[s['publication_year']],stage_documentaire=s['family']) for s in item['references']]
 context=env['context_for'](refs).replace('Nos Deniers.','PLFSS.',1)
 temp=dest.with_name(dest.name+'.partial')
 iterator=extractors.xlsx_records(source)
 try:
  with gzip.open(temp,'wt',encoding='utf-8',compresslevel=3) as stream:
   def flush():
    if not pending_records:return
    full_context=context+('. Section : '+sheet if sheet else '')
    chunks=[dict(text=text,body=body,tokens=chunker.count(text)) for text,body in chunker.chunks(full_context,pending_lines)] if pending_lines else []
    assert all(0<ch['tokens']<=800 for ch in chunks)
    original=dump(pending_records)
    # An independent second invocation checks the exact original chunker's result.
    replay=[(text,body) for text,body in chunker.chunks(full_context,pending_lines)] if pending_lines else []
    assert [(ch['text'],ch['body']) for ch in chunks]==replay
    assert dump(pending_records)==original
    stream.write(dump(dict(source_sha256=sid,records=pending_records,source_locators=pending_locators,section=sheet,context=full_context,serialized_blocks=pending_lines,chunks=chunks,allow_automatic_numeric_fact=False))+'\n')
    counts['batches']+=1;counts['chunks']+=len(chunks);counts['tokens']+=sum(ch['tokens'] for ch in chunks)
    pending_records.clear();pending_lines.clear();pending_locators.clear()
   for rec in itertools.islice(iterator,pilot_records or None):
    kind=rec['kind'];counts['source_records']+=1
    if kind=='structure':
     flush();stream.write(dump(dict(source_sha256=sid,structure=rec,chunks=[],allow_automatic_numeric_fact=False))+'\n');continue
    assert kind=='table'
    current=rec.get('sheet','')
    if current!=sheet:flush();sheet=current
    candidates=headers.setdefault(current,[])
    if len(candidates)<5:candidates.extend(rec['rows'][:5-len(candidates)])
    width=max((len(row) for row in candidates),default=0)
    labels=['contexte non certifie: '+' / '.join(env['clean'](row[col])[:120] for row in candidates if col<len(row) and row[col] is not None) for col in range(width)]
    blocks=list(env['table_lines'](rec,labels))
    pending_records.append(rec);pending_lines.extend(blocks);pending_locators.append(rec['locator']+'/table:1')
    for row in rec['rows']:
     counts['source_fields']+=len(row);counts['source_nulls']+=sum(x is None for x in row)
     counts['numeric_zeros']+=sum(type(x) in (int,float) and x==0 for x in row)
    if len(pending_lines)>=32:flush()
   flush()
 finally:iterator.close()
 os.replace(temp,dest)
 result=dict(source_sha256=sid,source_id=item['source']['id'],identity=contract['identity'],sha256=sha(dest),path=dest.relative_to(ROOT/'vectorization').as_posix(),**counts,elapsed_seconds=round(time.time()-started,2),pilot=bool(pilot_records),source_bytes_changed=False,zero_values_replaced=False,range_compaction_enabled=False)
 save(receipt,result);return result

def main(source_id=None,pilot_records=0):
 contract,config,code=freeze();items=json.loads((ROOT/'vectorization/source-inventory.json').read_text('utf-8'))['items'];items=[i for i in items if i['format']=='xlsx' and (not source_id or i['source']['id']==source_id)]
 if not items:raise ValueError('No matching historical Excel source')
 if pilot_records and not source_id:raise ValueError('Select one source for the pilot')
 (OUT/'prepare.pid').write_text(str(os.getpid())+'\n','ascii');done=[]
 for item in items:
  result=prepare(item,contract,config,code,pilot_records);done.append(result)
  status=dict(profile=contract['profile'],documents_prepared=len(done),documents_expected=len(items),pilot=bool(pilot_records),passages=sum(r.get('chunks',0) for r in done),tokens=sum(r.get('tokens',0) for r in done),gpu_launched=False,original_complement_checkpoints_preserved=True)
  save(OUT/'status.json',status);print(dump(status),flush=True)
 save(OUT/'receipts.json',done)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source-id');p.add_argument('--pilot-records',type=int,default=0);a=p.parse_args();main(a.source_id,a.pilot_records)

"""Retry the held PDF with the unchanged serializer and a counted safety margin.

The original historical algorithm and source/table evidence stay intact. Its
public max_tokens parameter is decreased only when a final word boundary makes
an 800-token trial become 801. No truncation or artificial overlap is enabled.
"""
from pathlib import Path
import argparse,json,shutil
import prepare_vectorization as prep

def main(source_id='641a2fb3a1933d25b182e75f'):
 settings=json.loads((prep.OUT/'preparation-contract.json').read_text('utf-8'))
 assert prep.sha(Path(prep.__file__))==settings['adapter_sha256']
 _,tables,_,_=prep.runtime(settings)
 original=tables.serialize_table;events=[]
 code_sha=prep.sha(Path(__file__));frozen=prep.OUT/'code'/('serialization_token_guard-'+code_sha[:16]+'.py')
 if not frozen.exists():shutil.copyfile(Path(__file__),frozen)
 assert prep.sha(frozen)==code_sha
 def guarded(table,context,tokenizer,max_tokens=800):
  try:return original(table,context,tokenizer,max_tokens=max_tokens)
  except ValueError as e:
   if str(e)!='Serialized chunk exceeds its token contract':raise
  for ceiling in range(max_tokens-1,max(63,max_tokens-32),-1):
   try:
    result=original(table,context,tokenizer,max_tokens=ceiling)
    assert all(c['tokens']==len(tokenizer.encode(c['text']).ids)<=800 for c in result['chunks'])
    events.append(dict(page=context['page'],table_id=context['table_id'],requested_ceiling=max_tokens,successful_ceiling=ceiling,source_characters=result['contract']['source_characters'],source_text_conserved=result['contract']['source_text_conserved']))
    return result
   except ValueError as e:
    if str(e)!='Serialized chunk exceeds its token contract':raise
  raise ValueError('No checked safety margin fits the original serializer; keep PDF held')
 tables.serialize_table=guarded
 items=json.loads((prep.OUT/'source-inventory.json').read_text('utf-8'))['items']
 item=next(i for i in items if i['source']['id']==source_id)
 receipt=prep.OUT/'documents'/(item['source']['sha256']+'.receipt.json')
 if receipt.is_file():
  result=json.loads(receipt.read_text('utf-8'))
  assert result['preparation_identity']==settings['preparation_identity'] and prep.sha(prep.OUT/result['path'])==result['sha256']
  print(prep.dump(dict(source_id=source_id,already_completed=True)),flush=True);return
 result=prep.stage_one(item,settings)
 result['serialization_token_guard']=dict(code_sha256=code_sha,path=frozen.relative_to(prep.OUT).as_posix(),events=events,max_contract_tokens=800,extractor_changed=False,source_text_conserved=True)
 prep.save(prep.OUT/'documents'/(result['source_sha256']+'.receipt.json'),result)
 prep.save(prep.ROOT/'reports'/('held-pdf-retry-'+source_id+'.json'),dict(source_id=item['source']['id'],source_sha256=result['source_sha256'],completed=True,guard=result['serialization_token_guard'],gpu_launched=False))
 print(prep.dump(dict(source_id=item['source']['id'],completed=True,records=result['records'],chunks=result['chunks'],guard_events=events)),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--source-id',default='641a2fb3a1933d25b182e75f');parser.add_argument('--held',action='store_true');args=parser.parse_args()
 if args.held:
  for item in json.loads((prep.OUT/'held-documents.json').read_text('utf-8')):
   if item['error']=='Serialized chunk exceeds its token contract':main(item['source_id'])
 else:main(args.source_id)

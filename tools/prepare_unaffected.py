"""Continue unchanged PDF/HTML extraction while the Excel decision is pending.

This controller does not edit the extractor, exported input or financial data.
The original per-document contract and receipts are reused. No GPU is started.
"""
from pathlib import Path
import concurrent.futures,os,time
import prepare_vectorization as prep

def main():
 config=prep.json.loads((prep.OUT/'preparation-contract.json').read_text('utf-8'))
 assert prep.sha(Path(prep.__file__))==config['adapter_sha256']
 for name,value in config['code'].items():assert prep.sha(prep.OUT/'code'/name)==value
 items=prep.json.loads((prep.OUT/'source-inventory.json').read_text('utf-8'))['items']
 complete={i['source']['sha256']:prep.json.loads((prep.OUT/'documents'/(i['source']['sha256']+'.receipt.json')).read_text('utf-8')) for i in items if (prep.OUT/'documents'/(i['source']['sha256']+'.receipt.json')).is_file()}
 waiting=[i for i in items if i['source']['sha256'] not in complete and i['format']=='xlsx']
 pending=[i for i in items if i['source']['sha256'] not in complete and i['format']!='xlsx']
 errors=prep.json.loads((prep.OUT/'held-documents.json').read_text('utf-8'))
 prep.save(prep.OUT/'unaffected-run.json',dict(controller_sha256=prep.sha(Path(__file__)),pid=os.getpid(),scheduled=len(pending),excel_awaiting_decision=len(waiting),extractor_changed=False,gpu_launched=False))
 (prep.OUT/'prepare.pid').write_text(str(os.getpid())+'\n',encoding='ascii')
 started=time.time()
 def checkpoint(running):
  state=dict(state='preparing_unaffected_documents' if running else 'awaiting_excel_layout_decision',decision_required=True,
   done=len(complete),held=len(errors),expected=len(items),excel_awaiting_decision=len(waiting),
   passages=sum(r['chunks'] for r in complete.values()),tokens=sum(r['tokens'] for r in complete.values()),
   elapsed_seconds=round(time.time()-started,1),gpu_launched=False,paid_compute_authorized=False,input_export_complete=False)
  prep.save(prep.OUT/'status.json',state);prep.save(prep.OUT/'receipts.json',list(complete.values()));prep.save(prep.OUT/'held-documents.json',errors)
  return state
 print(prep.dump(checkpoint(True)),flush=True)
 with concurrent.futures.ProcessPoolExecutor(max_workers=2) as pool:
  futures={pool.submit(prep.stage_one,i,config):i for i in pending}
  for future in concurrent.futures.as_completed(futures):
   item=futures[future]
   try:r=future.result();complete[r['source_sha256']]=r
   except Exception as e:errors.append(dict(source_id=item['source']['id'],source_sha256=item['source']['sha256'],error=str(e)[:250],type=type(e).__name__))
   state=checkpoint(True)
   if len(complete)%10==0:print(prep.dump(state),flush=True)
 print(prep.dump(checkpoint(False)),flush=True)

if __name__=='__main__':main()

"""Finish the authorized LOCAL memo preparation; never call a paid service.

Wait only for known preparation/check workers, repair proven word boundaries,
close the export, then require independent validation before a review manifest.
"""
from pathlib import Path
import argparse,contextlib,json,msvcrt,os,subprocess,sys,time
import prepare_memo_vectorization as prep


@contextlib.contextmanager
def single_instance():
    path=prep.OUT/'finish.lock'
    with path.open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        try:yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def run(name,*args,allow_failed=False):
    result=subprocess.run([sys.executable,'-B',str(prep.ROOT/'tools'/name),*args],cwd=prep.ROOT)
    if result.returncode and not allow_failed:raise RuntimeError(name+' did not pass')
    return result.returncode


def wait_workers(pids):
    while pids:
        command='Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in @('+','.join(map(str,pids))+') } | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress'
        result=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,check=True)
        rows=json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(rows,dict):rows=[rows]
        for row in rows:
            if not any(name in row['CommandLine'] for name in ('prepare_memo_vectorization.py',
                    'verify_memo_vectorization.py','prepare_compact_context_pdf.py')):
                raise RuntimeError('A recorded PID belongs to a different process; leave it untouched')
        pids=[r['ProcessId'] for r in rows]
        prep.save(prep.OUT/'finish-status.json',dict(state='waiting_for_local_workers',pids=pids,gpu_launched=False))
        if pids:time.sleep(30)


def verify_compact_guards():
    settings=json.loads((prep.BASE/'preparation-contract.json').read_text('utf-8'))
    checks=[]
    for receipt_path in (prep.BASE/'documents').glob('*.receipt.json'):
        receipt=json.loads(receipt_path.read_text('utf-8'));guard=receipt.get('compact_context_guard')
        if not guard:continue
        if guard['source_fields_changed'] is not False or guard['optional_prefix_budget']!=0:
            raise ValueError('Compact guard altered source fields')
        if guard['original_serializer_sha256']!=settings['code']['vectorisation_table_text_word_safe.py']:
            raise ValueError('Compact guard used a different serializer')
        if guard['code_sha256']!=prep.sha(prep.BASE/guard['path']):raise ValueError('Frozen compact guard changed')
        if not all(e['source_text_conserved'] is True and e['successful_ceiling']<=800 for e in guard['events']):
            raise ValueError('Compact context conservation did not pass')
        checks.append(dict(source_sha256=receipt['source_sha256'],guard_code_sha256=guard['code_sha256'],
            prepared_sha256=receipt['sha256'],events=guard['events']))
    prep.save(prep.OUT/'compact-context-guard-audit.json',dict(passed=True,checks=checks,gpu_launched=False))


def main(pids):
    with single_instance():
        wait_workers(pids);verify_compact_guards()
        run('prepare_memo_vectorization.py')
        state=json.loads((prep.OUT/'status.json').read_text('utf-8'))
        if not state.get('complete'):raise RuntimeError('Documents still held; keep this batch local')
        run('verify_memo_vectorization.py','--available',allow_failed=True)
        partial=json.loads((prep.OUT/'preparation-audit.partial.json').read_text('utf-8'))
        if partial['critical_pages']:raise RuntimeError('Source page requires a documented review')
        if any(e['error']!='A legacy body differs from its normalized source' for e in partial['errors']):
            raise RuntimeError('Unqualified preparation errors; do not hide or bypass them')
        if partial['errors']:
            run('guard_memo_boundaries.py')
            run('prepare_memo_vectorization.py')
        run('verify_memo_vectorization.py')
        audit_path=prep.OUT/'preparation-audit.json';audit=json.loads(audit_path.read_text('utf-8'))
        if audit['passed'] is not True:raise RuntimeError('Full input is not independently validated')
        state=json.loads((prep.OUT/'export-status.json').read_text('utf-8'))
        manifest=dict(state='ready_for_runpod_budget_review',input_sha256=state['input_sha256'],
            input_bytes=state['input_bytes'],passages=state['passages'],tokens=state['tokens'],
            documents=state['documents_prepared'],audit_sha256=prep.sha(audit_path),
            model='BAAI/bge-m3',revision='5617a9f61b028005a4858fdac845db406aefb181',
            dense_dimensions=1024,dense_dtype='float16',dense_normalized=True,sparse_dtype='float32',
            colbert=False,max_tokens=800,gpu_launched=False,launch_authorized=False,
            budget_approved_usd=None,cost_estimate_pending=True)
        prep.save(prep.OUT/'READY_FOR_REVIEW.json',manifest)
        prep.save(prep.OUT/'finish-status.json',manifest)
        print(prep.dump(manifest),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--wait-pids',nargs='*',type=int,default=[])
    args=parser.parse_args()
    try:main(args.wait_pids)
    except Exception as exc:
        prep.save(prep.OUT/'finish-status.json',dict(state='local_review_required',error=str(exc),
            type=type(exc).__name__,gpu_launched=False,launch_authorized=False))
        raise

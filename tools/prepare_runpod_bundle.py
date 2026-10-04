"""Prepare the closed PLFSS GPU job locally, locked pending paid approval.

Reuse the previously verified BGE-M3 encoder, checkpoint validation and budget
guards. No API mutation, GPU startup, credential copy or production write.
"""
from pathlib import Path
import ast,json,shutil
import prepare_memo_vectorization as prep

OLD=prep.ROOT.parent/'backups/nos-deniers-20260929-optimisation/reports/source-refresh-20261001/runpod-batch-20261001/runpod-controller'
FILES=('bootstrap_budget_guard.py','campaign_budget.py','checkpoint_store.py','pod_safety_guard.py',
    'remote_worker.py','selftest.py','test_final_safety.py')
VENDOR=('bge_encoder.py','hatvp_core.py','runpod_embedding_job_resilient.py')


def write(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_text('utf-8')!=text:raise ValueError('Preserve incompatible prepared file: '+str(path))
    else:path.write_text(text,'utf-8',newline='\n')


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('Inherited controller differs from the reviewed adapter point')
    return text.replace(old,new,1)


def main():
    ready=json.loads((prep.OUT/'READY_FOR_REVIEW.json').read_text('utf-8'))
    audit=prep.OUT/'preparation-audit.json';result=json.loads(audit.read_text('utf-8'))
    status=json.loads((prep.OUT/'export-status.json').read_text('utf-8'))
    if not result['passed'] or not result['input_checked'] or not result['all_documents_checked']:
        raise ValueError('Full preparation is not validated')
    if ready['audit_sha256']!=prep.sha(audit) or ready['input_sha256']!=prep.sha(prep.OUT/'gpu_input/public.bge-m3.jsonl'):
        raise ValueError('Validated input or audit changed')
    runtime=prep.OUT/'runpod-controller';here=runtime/'controller';here.mkdir(parents=True,exist_ok=True)
    if (runtime/'CAMPAIGN_BUDGET.json').exists():raise ValueError('Do not rebuild an existing paid campaign')
    job='lexmachine-plfss-20261004-'+ready['input_sha256'][:12]
    origins={};bundle={}
    for name in FILES+tuple('vendor/'+name for name in VENDOR):
        source=OLD/'controller'/name;target=here/name;write(target,source.read_text('utf-8'))
        origins[name]=dict(path=str(source),sha256=prep.sha(source));bundle[name]=prep.sha(target)
    policy='''def validate_preparation_policy(contract):
    required = {'profile': 'nos-deniers-memo-20261001-routes-historiques',
                'artificial_overlap': 'by_route', 'generic_overlap_max_tokens': 150,
                'pdf_table_artificial_overlap': 0, 'max_tokens': 800,
                'source_blank_states_retained': True, 'range_compaction_enabled': False}
    for name, expected in required.items():
        if contract.get(name) != expected:
            raise RuntimeError('PLFSS preparation policy differs: ' + name)


'''
    source=OLD/'controller/runpod_controller.py';text=source.read_text('utf-8')
    start=text.index('def notify(');end=text.index('def validate_frozen_contract(',start)
    text=text[:start]+'''def notify(subject, body, state=None, field=None):
    # Job progress stays local; no inherited SMTP script is called.
    print('PLFSS_JOB_NOTICE', subject, flush=True)
    if state is not None and field:
        state[field] = True


'''+policy+text[end:]
    text=replace_once(text,'required.update(dense_normalized=True, colbert=False, truncate=False, artificial_overlap=0)',
        'required.update(dense_normalized=True, colbert=False, truncate=False)\n    validate_preparation_policy(contract)')
    text=replace_once(text,"    bundle_path = HERE / 'BUNDLE_SHA256.json'",'''    audit_path = SOURCE_ROOT.parent / 'preparation-audit.json'
    if file_sha(audit_path) != handoff['preparation_audit_sha256']:
        raise RuntimeError('PLFSS preparation audit changed')
    audit = json.loads(audit_path.read_text('utf-8'))
    if audit.get('passed') is not True or audit.get('input_checked') is not True or audit.get('all_documents_checked') is not True:
        raise RuntimeError('PLFSS input has not passed full independent validation')
    if audit['input_sha256'] != INPUT_SHA256 or audit['documents_verified'] != 2086:
        raise RuntimeError('PLFSS audit belongs to another input')
    if file_sha(FROZEN_MANIFEST) != handoff['source_inventory_sha256']:
        raise RuntimeError('PLFSS source inventory changed')
    if file_sha(SOURCE_ROOT.parent / 'catalogue.sqlite') != handoff['catalogue_sha256']:
        raise RuntimeError('PLFSS source-proof catalogue changed')
    bundle_path = HERE / 'BUNDLE_SHA256.json' ''')
    write(here/'runpod_controller.py',text);origins['runpod_controller.py']=dict(path=str(source),sha256=prep.sha(source),
        adaptations=['Route-specific memo policy and full audit bound to input', 'Local progress notices without inherited email'])
    settings=f'''from pathlib import Path
HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent
SOURCE_ROOT = RUNTIME.parent / 'gpu_input'
INPUT = SOURCE_ROOT / 'public.bge-m3.jsonl'
CONTRACT = SOURCE_ROOT / 'contract.json'
HANDOFF = SOURCE_ROOT / 'HANDOFF.json'
FROZEN_MANIFEST = SOURCE_ROOT.parent / 'source-inventory.json'
AUTHORIZATION = RUNTIME / 'AUTHORIZATION.json'
JOB_NAME = {job!r}
REMOTE_ROOT = '/workspace/plfss_jobs/20261004-{ready['input_sha256'][:12]}'
INPUT_COUNT = {ready['passages']}
INPUT_BYTES = {ready['input_bytes']}
INPUT_SHA256 = {ready['input_sha256']!r}
MODEL = 'BAAI/bge-m3'
REVISION = {ready['revision']!r}
PART_SIZE = 8192
INITIAL_BATCH_SIZE = 64
GPU_TYPE = 'NVIDIA H200'
GPU_PREFERENCE = ('NVIDIA H200', 'NVIDIA H100 80GB HBM3', 'NVIDIA H100 NVL')
GPU_QUOTED_RATE_OVERRIDES = {{}}
MAX_RATE_USD_H = 4.60
MISSION_CAP_USD = 6.00
RECHARGE_ALERT_USD = 5.00
CHECKPOINT_DRAIN_SECONDS = 300
BUDGET_AUTOSTOP = True
BUDGET_ALERTS = True
HISTORICAL_BILLED_USD = 0.0
NETWORK_VOLUME_ID = '0veq3wcq7g'
NETWORK_DATA_CENTER = 'EU-FR-1'
IMAGE = 'runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404'
TRANSPORT_HELPERS = HERE / 'vendor' / 'runpod_embedding_job_resilient.py'
HATVP_PROJECT = HERE / 'vendor'
'''
    write(here/'settings.py',settings)
    input_manifest=dict(input_count=ready['passages'],input_sha256=ready['input_sha256'],input_bytes=ready['input_bytes'],
        preparation_audit_sha256=ready['audit_sha256'],source_inventory_sha256=prep.sha(prep.OUT/'source-inventory.json'),
        catalogue_sha256=status['catalogue_sha256'],profile=prep.PROFILE,paid_compute_authorized=False)
    write(prep.OUT/'gpu_input/HANDOFF.json',prep.dump(input_manifest)+'\n')
    authorization=dict(job_name=job,input_sha256=ready['input_sha256'],launch_authorized=False,
        mission_cap_usd=6.0,budget_status='PROPOSED_NOT_APPROVED',approved_by_user=False)
    write(runtime/'AUTHORIZATION.json',prep.dump(authorization)+'\n')
    for name in ('numpy','numpy.libs','numpy-2.2.6.dist-info'):
        target=runtime/'python-libs'/name
        if not target.exists():shutil.copytree(OLD/'python-libs'/name,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    invoke='''#!/usr/bin/env bash
set -euo pipefail
PROJECT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$PROJECT/../python-libs"
cd "$PROJECT"
if [[ "${1:-runpod_controller.py}" == "runpod_controller.py" && -z "${RUNPOD_API_KEY:-}" ]]; then
  printf '%s\\n' 'Cle RunPod absente du lanceur.' >&2
  exit 2
fi
exec /usr/bin/python3 -B -u "${1:-runpod_controller.py}"
'''
    write(here/'invoke.sh',invoke)
    launcher='''$ErrorActionPreference='Stop'
$runtime=$PSScriptRoot
$authorization=Get-Content -LiteralPath (Join-Path $runtime 'AUTHORIZATION.json') -Raw -Encoding utf8 | ConvertFrom-Json
if($authorization.launch_authorized -ne $true -or $authorization.approved_by_user -ne $true){throw 'Lancement payant bloque : accord sur le lot et le plafond encore attendu.'}
if(-not $env:RUNPOD_API_KEY){throw 'Cle RunPod absente de cet environnement.'}
$env:WSLENV=(@($env:WSLENV,'RUNPOD_API_KEY/u') | Where-Object {$_}) -join ':'
$windowsInvoke=Join-Path $runtime 'controller\\invoke.sh'
if($windowsInvoke -notmatch '^([A-Za-z]):'){throw 'Chemin Windows du lanceur non reconnu'}
$invoke='/mnt/'+$Matches[1].ToLower()+'/'+$windowsInvoke.Substring(3).Replace('\\','/')
$job=Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d','Ubuntu-24.04','--','bash',$invoke) -WorkingDirectory $runtime -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'launch.log') -RedirectStandardError (Join-Path $runtime 'launch-errors.log') -PassThru
Write-Output ('Controleur PLFSS lance, PID '+$job.Id+'. Resultats et journaux : '+$runtime)
'''
    write(runtime/'LANCER_RUNPOD_PLFSS.ps1',launcher)
    pause='''$ErrorActionPreference='Stop'
$path=Join-Path $PSScriptRoot 'PAUSE_REQUESTED.json'
@{requested_at=(Get-Date).ToUniversalTime().ToString('o');job='PLFSS'} | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding utf8
Write-Output 'Pause demandee : fin du lot courant, sauvegarde et arret du GPU de cette campagne.'
'''
    write(runtime/'PAUSER_RUNPOD_PLFSS.ps1',pause)
    for name in ('runpod_controller.py','settings.py','invoke.sh'):bundle[name]=prep.sha(here/name)
    write(here/'BUNDLE_SHA256.json',prep.dump(bundle)+'\n')
    write(runtime/'CODE_ORIGINS.json',prep.dump(origins)+'\n')
    for path in here.rglob('*.py'):ast.parse(path.read_text('utf-8'))
    review=dict(state='PREPARED_LOCKED',job_name=job,passages=ready['passages'],tokens=ready['tokens'],
        input_sha256=ready['input_sha256'],model=ready['model'],dense=True,sparse=True,colbert=False,
        proposed_cap_usd=6.0,cap_approved=False,gpu_launched=False,launch_authorized=False,
        runtime=str(runtime),retrieval='Immutable parts of at most 8192 rows, hash and vector validation before remote deletion')
    write(runtime/'PREPARATION.json',prep.dump(review)+'\n');print(prep.dump(review),flush=True)


if __name__=='__main__':main()

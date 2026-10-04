"""Resume the unchanged extraction adapter; deduplicate documentary reference IDs.

After supporting sources are added to the application catalogue, they can also
remain in the reconciliation catalogue. This wrapper removes ONLY identical
reference IDs from that combined inventory. Source bytes, chunks and the
frozen extraction contract are untouched; its own hash is retained separately.
"""
from pathlib import Path
import argparse,os,subprocess,sys
import prepare_vectorization as prep

def main(workers=2):
 choice=prep.OUT/'historical-protocol-choice.json'
 if choice.is_file() and prep.json.loads(choice.read_text('utf-8')).get('profile')=='nos-deniers-memo-20261001-routes-historiques':
  memo_pid=prep.OUT/'memo-20261004/prepare.pid'
  if sys.platform=='win32' and memo_pid.is_file():
   pid=int(memo_pid.read_text().strip())
   running=subprocess.run(['powershell','-NoProfile','-Command',f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"],capture_output=True,text=True,check=True)
   if 'prepare_memo_vectorization.py' in running.stdout:
    print('La préparation du mémo tourne déjà ; consulter vectorization/memo-20261004/status.json.');return
  from prepare_memo_vectorization import main as selected_preparation
  selected_preparation()
  return
 if choice.is_file() and prep.json.loads(choice.read_text('utf-8')).get('alignment_required'):
  raise SystemExit('Méthode de la grande base Nos Deniers demandée : alignement historique encore à terminer avant reprise complète. Aucune décision sur une compression NULL à redemander. Lire reports/COMPARAISON_PROTOCOLE_NOS_DENIERS.html.')
 state_path=prep.OUT/'status.json'
 if state_path.is_file() and (prep.json.loads(state_path.read_text('utf-8')).get('state')=='awaiting_excel_layout_decision' or prep.json.loads(state_path.read_text('utf-8')).get('decision_required')):
  raise SystemExit('Préparation conservée : décision requise sur les plages vides Excel. Lire reports/PROPOSITION_PLAGES_VIDES_EXCEL.html avant toute reprise.')
 pid_file=prep.OUT/'prepare.pid'
 if sys.platform=='win32' and pid_file.is_file():
  pid=int(pid_file.read_text().strip())
  result=subprocess.run(['powershell','-NoProfile','-Command',f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"],capture_output=True,text=True,check=True)
  if any(name in result.stdout for name in ('prepare_vectorization.py','resume_vectorization.py','prepare_unaffected.py')):
   print('La préparation PLFSS tourne déjà ; consulter vectorization/status.json.');return
 original=prep.inventory
 def inventory():
  items=original();removed=0
  for item in items:
   unique={}
   for ref in item['references']:
    if ref['id'] in unique:
     if ref['sha256']!=unique[ref['id']]['sha256']:raise ValueError('Two contents share a reference ID; preserve both and qualify')
     removed+=1;continue
    unique[ref['id']]=ref
   item['references']=list(unique.values())
  data=prep.json.loads((prep.OUT/'source-inventory.json').read_text('utf-8'));data['items']=items
  data['source_entries']=len({r['id'] for i in items for r in i['references']}|{r['id'] for r in data['omitted']})
  prep.save(prep.OUT/'source-inventory.json',data)
  prep.save(prep.OUT/'reference-deduplication.json',dict(wrapper_sha256=prep.sha(Path(__file__)),identical_reference_ids_removed=removed,source_bytes_changed=False,passage_method_changed=False))
  return items
 prep.inventory=inventory
 pid_file.write_text(str(os.getpid())+'\n',encoding='ascii')
 prep.main(workers)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,choices=(1,2,3,4),default=2);args=parser.parse_args();main(args.workers)

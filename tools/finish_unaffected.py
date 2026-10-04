"""Finish this local run after its two workers, without GPU or Excel adaptation."""
from pathlib import Path
import argparse,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]

def main(parent_pid):
 while True:
  check=subprocess.run(['powershell','-NoProfile','-Command',f"(Get-CimInstance Win32_Process -Filter 'ProcessId={parent_pid}').CommandLine"],capture_output=True,text=True,check=True)
  if 'tools\\prepare_unaffected.py' not in check.stdout:break
  time.sleep(10)
 subprocess.run([sys.executable,'-B','tools/prepare_held_pdf.py','--held'],cwd=ROOT,check=True)
 subprocess.run([sys.executable,'-B','tools/verify_vectorization.py','--available'],cwd=ROOT,check=True)
 subprocess.run([sys.executable,'-B','tools/prepare_delivery.py'],cwd=ROOT,check=True)
 print(json.dumps(dict(unaffected_run_finished=True,excel_decision_still_required=True,gpu_launched=False)),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--parent-pid',type=int,required=True);main(parser.parse_args().parent_pid)

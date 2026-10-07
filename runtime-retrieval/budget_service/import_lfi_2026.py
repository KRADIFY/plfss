"""Publish the checked legal LFI 2026 extraction, with an immutable backup."""
import hashlib,json,sqlite3,shutil
from pathlib import Path
from datetime import datetime,timezone
DATA=Path('/data');PLAN=Path('/plan/plan.json');EXPORT=Path('/export')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(db,limit):
 h=hashlib.sha256()
 for r in db.execute('select * from facts where rowid<=? order by rowid',(limit,)):h.update(json.dumps(r,ensure_ascii=False,separators=(',',':')).encode());h.update(b'\n')
 return h.hexdigest()
def main():
 p=json.loads(PLAN.read_text());assert all(c['expected']==c['actual'] for c in p['checks'])
 target=DATA/'derived/budget.sqlite';db=sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)
 assert db.execute("select count(*) from facts where year=2026 and stage='LFI'").fetchone()[0]==0
 count=db.execute('select count(*) from facts').fetchone()[0];before=digest(db,count)
 meta={k:json.loads(v) for k,v in db.execute('select key,value from meta')}
 backup=DATA/'imports/developpement-lfi-2026';backup.mkdir(exist_ok=True)
 assert not (backup/'budget-before.sqlite').exists()
 with sqlite3.connect(backup/'budget-before.sqlite') as dest:db.backup(dest)
 staged=DATA/'derived/budget.lfi2026-staged.sqlite';assert not staged.exists()
 new=sqlite3.connect(staged);db.backup(new)
 for r in p['sources']:
  src=EXPORT/r['original_export_path'];assert sha(src)==r['sha256']
  dst=DATA/r['path'];dst.parent.mkdir(parents=True,exist_ok=True)
  if dst.exists():assert sha(dst)==r['sha256']
  else:shutil.copyfile(src,dst);dst.chmod(0o644)
  assert sha(dst)==r['sha256'];new.execute('insert into sources values (?,?)',(r['id'],json.dumps(r,ensure_ascii=False)))
 new.executemany('insert into facts values ('+','.join('?'*19)+')',p['facts'])
 new.executemany('insert into published_nodes values (?,?,?,?,?,?,?,?)',p['published_nodes'])
 for c in p['checks']:new.execute('insert into reconciled_totals values (?,?,?,?,?,?,?)',(2026,'LFI',c['measure'],c['budget'],c['path'],c['expected'],p['facts'][0][15]))
 new.execute('create table if not exists nomenclature_provenance(year integer,budget text,mission text,label text,code_basis text,primary key(year,budget,mission))')
 for m in p['mission_mapping']:new.execute('insert into nomenclature_provenance values (?,?,?,?,?)',(2026,m['budget'],m['mission'],m['label'],m['code_basis']))
 now=datetime.now(timezone.utc).isoformat();updated=dict(built_at=now,source_count=meta['source_count']+len(p['sources']),fact_count=count+len(p['facts']),imported_source_count=meta['imported_source_count']+1,catalogue_updated_at=now,data_version=hashlib.sha256((meta['data_version']+sha(PLAN)).encode()).hexdigest())
 for k,v in updated.items():new.execute('insert or replace into meta values (?,?)',(k,json.dumps(v)))
 assert digest(new,count)==before
 new.commit();assert new.execute('pragma integrity_check').fetchone()[0]=='ok';new.close();db.close();staged.chmod(0o644);staged.replace(target)
 receipt=dict(at=now,facts_added=len(p['facts']),sources_added=len(p['sources']),checks=len(p['checks']),original_facts_sha256=before,original_facts_preserved=count,updated=updated)
 (backup/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));shutil.copyfile(PLAN,backup/'plan.json')
 normal=DATA/'derived/normalization-report.json';shutil.copyfile(normal,backup/'normalization-report-before.json');m=json.loads(normal.read_text());m.update(updated);normal.write_text(json.dumps(m,ensure_ascii=False,indent=2))
 print(json.dumps(receipt))
if __name__=='__main__':main()

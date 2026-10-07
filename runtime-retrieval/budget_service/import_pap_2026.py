"""Transactional, idempotent import of reviewed PAP Ecology 2026 amounts."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,sqlite3,shutil

FIELDS='year stage measure budget mission mission_label program program_label action action_label subaction subaction_label category title cents source line field approximate'.split()

def rows_digest(db,limit):
    h=hashlib.sha256()
    for row in db.execute('SELECT * FROM facts WHERE rowid<=? ORDER BY rowid',(limit,)):
        h.update(json.dumps(tuple(row),ensure_ascii=False,separators=(',',':')).encode());h.update(b'\n')
    return h.hexdigest()

def validate_plan(plan):
    rows=plan['rows']
    if len(rows)!=34 or len({tuple(r[k] for k in ('year','stage','measure','budget','mission','program')) for r in rows})!=34:
        raise ValueError('Duplicate or unexpected rows')
    for row in rows:
        if row['year']!=2026 or row['stage'] not in ('PLF','FDC_PREVU') or row['budget']!='BG' or row['mission']!='TA' or row['program']=='362' or not isinstance(row['cents'],int) or row['cents']<0:
            raise ValueError('Invalid reviewed observation')
    for stage,measures in plan['totals'].items():
        for measure,total in measures.items():
            if sum(r['cents'] for r in rows if r['stage']==stage and r['measure']==measure)!=total*100:
                raise ValueError('PAP mission total mismatch')
    if not all(c['passed'] for c in plan['checks']):raise ValueError('Unchecked PAP row')

def install(data=Path('/data')):
    plan_path=Path(__file__).parent/'data/pap-ecologie-2026.json'
    plan=json.loads(plan_path.read_text(encoding='utf8'));validate_plan(plan)
    plan_sha=hashlib.sha256(plan_path.read_bytes()).hexdigest()
    target=data/'derived/budget.sqlite'
    db=sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)
    source=plan['source'];actual=json.loads(db.execute('SELECT data FROM sources WHERE id=?',(source['id'],)).fetchone()[0])
    with (data/actual['path']).open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if actual['sha256']!=source['sha256'] or digest!=source['sha256']:raise ValueError('Source hash mismatch')
    prior=list(db.execute("SELECT "+','.join(FIELDS)+" FROM facts WHERE year=2026 AND mission='TA' AND stage IN ('PLF','FDC_PREVU') ORDER BY stage,measure,program"))
    expected=sorted([tuple(r[k] for k in FIELDS) for r in plan['rows']],key=lambda r:(r[1],r[2],r[6]))
    if prior:
        if prior!=expected:raise ValueError('Existing 2026 figures differ; explicit reconciliation required')
        print(json.dumps({'state':'already_installed','facts':len(prior)}));db.close();return
    count=db.execute('SELECT count(*) FROM facts').fetchone()[0]
    last=db.execute('SELECT max(rowid) FROM facts').fetchone()[0]
    before=rows_digest(db,last);meta={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM meta')}
    backup=data/'imports/pap-ecologie-2026-20260919';backup.mkdir(parents=True,exist_ok=True)
    backup_file=backup/'budget-before.sqlite'
    if not backup_file.exists():
        with sqlite3.connect(backup_file) as dst:db.backup(dst)
    staged=data/'derived/budget.pap2026-staged.sqlite'
    if staged.exists():raise ValueError('Staging exists; inspect it before resuming')
    new=sqlite3.connect(staged);new.execute('PRAGMA temp_store=MEMORY');db.backup(new)
    new.executemany('INSERT INTO facts('+','.join(FIELDS)+') VALUES('+','.join('?' for _ in FIELDS)+')',expected)
    for stage,measures in plan['totals'].items():
        for measure,total in measures.items():
            new.execute('INSERT INTO reconciled_totals VALUES(?,?,?,?,?,?,?)',(2026,stage,measure,'BG','TA',total*100,source['id']))
    actual['imported']=True;new.execute('UPDATE sources SET data=? WHERE id=?',(json.dumps(actual,ensure_ascii=False),source['id']))
    now=datetime.now(timezone.utc).isoformat()
    updates=dict(fact_count=count+len(expected),built_at=now,data_version=hashlib.sha256((meta['data_version']+plan_sha).encode()).hexdigest(),pap2026_ecology=dict(source=source['id'],sha256=source['sha256'],pages=plan['reviewed_pages'],limits=plan['limits'],observations=len(expected)))
    updates.update(imported_source_count=meta['imported_source_count']+1,stats=dict(new.execute("SELECT year||'/'||stage||'/'||budget,count(*) FROM facts GROUP BY year,stage,budget")))
    for k,v in updates.items():new.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(k,json.dumps(v,ensure_ascii=False)))
    if rows_digest(new,last)!=before:raise ValueError('Original facts changed')
    new.commit()
    if new.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Invalid staged DB')
    new.close();db.close();staged.chmod(0o644)
    old_audit=data/'derived/data-audit.json'
    audit=None
    if old_audit.exists():
        shutil.copyfile(old_audit,backup/'data-audit-before.json')
        audit=json.loads(old_audit.read_text(encoding='utf8'))
    staged.replace(target)
    if audit and audit.get('success') and audit.get('built_at')==meta['built_at']:
        audit.update(built_at=now,checked_at=now,fact_count=updates['fact_count'],pap2026_checks={'source_sha256':digest,'mission_totals':plan['totals'],'original_facts_preserved':count,'original_facts_sha256':before})
        old_audit.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8');old_audit.chmod(0o644)
    receipt=dict(installed_at=now,facts_added=len(expected),previous_fact_count=count,current_fact_count=updates['fact_count'],source_sha256=digest,original_facts_sha256=before,plan_sha256=plan_sha,totals=plan['totals'])
    (backup/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')
    shutil.copyfile(plan_path,backup/'plan.json')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':install()
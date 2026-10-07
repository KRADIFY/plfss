"""Add sourced zero totals transactionally, preserving every existing fact."""
import hashlib, json, shutil, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .import_pap_2026_national import FIELDS, KEY_FIELDS, rows_digest

def install(data=Path('/data')):
    plan_path=Path(__file__).parent/'data/rap-explicit-zeros.json'
    plan=json.loads(plan_path.read_text(encoding='utf8'));sha=hashlib.sha256(plan_path.read_bytes()).hexdigest()
    assert plan['version']=='rap-explicit-zeros-1'
    assert len(plan['rows'])==len(plan['proofs'])==46
    target=data/'derived/budget.sqlite'
    db=sqlite3.connect(target.as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    meta={k:json.loads(v) for k,v in db.execute('select key,value from meta')}
    additions=[];verified=set();keys=set()
    for row,proof in zip(plan['rows'],plan['proofs']):
        key=tuple(row[k] for k in KEY_FIELDS)
        assert key not in keys;keys.add(key)
        assert row['cents']==proof['published_total_euros']==0 and row['line']==proof['page']>0
        assert not row['action'] and not row['subaction'] and not row['title']
        assert row['source']==proof['source'] and row['year'] in (2023,2024,2025)
        assert row['stage'] in ('LFI','EXEC','OUVERT') and row['measure'] in ('AE','CP')
        source=json.loads(db.execute('select data from sources where id=?',(row['source'],)).fetchone()[0])
        assert source['sha256']==proof['sha256']
        if row['source'] not in verified:
            with (data/source['path']).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==proof['sha256']
            verified.add(row['source'])
        found=db.execute('select '+','.join(FIELDS)+" from facts where year=? and stage=? and measure=? and budget=? and mission=? and program=? and action='' and subaction=''",key).fetchall()
        expected=tuple(row[k] for k in FIELDS)
        if found:assert len(found)==1 and tuple(found[0])==expected,('conflicting_existing_fact',key)
        else:additions.append(expected)
    if not additions:
        assert meta.get('rap_explicit_zeros',{}).get('plan_sha256')==sha
        print(json.dumps(dict(state='already_installed',facts=len(keys))));return
    count=db.execute('select count(*) from facts').fetchone()[0]
    last=db.execute('select max(rowid) from facts').fetchone()[0];before=rows_digest(db,last)
    backup=data/'imports/rap-explicit-zeros-20260920';backup.mkdir(parents=True,exist_ok=True)
    if (backup/'budget-before.sqlite').exists():
        with sqlite3.connect((backup/'budget-before.sqlite').as_uri()+'?mode=ro',uri=True) as saved:
            assert rows_digest(saved,last)==before and saved.execute('select count(*) from facts').fetchone()[0]==count
    else:
        with sqlite3.connect(backup/'budget-before.sqlite') as saved:db.backup(saved)
    staged=data/'derived/budget.rap-zeros-staged.sqlite'
    if staged.exists():
        with sqlite3.connect(staged.as_uri()+'?mode=ro',uri=True) as prior:
            assert prior.execute('pragma integrity_check').fetchone()[0]=='ok'
            assert rows_digest(prior,last)==before and prior.execute('select count(*) from facts').fetchone()[0]==count
    new=sqlite3.connect(staged);new.execute('pragma temp_store=MEMORY');db.backup(new)
    new.executemany('insert into facts('+','.join(FIELDS)+') values('+','.join('?' for _ in FIELDS)+')',additions)
    receipt=dict(plan_sha256=sha,facts_added=len(additions),previous_fact_count=count,current_fact_count=count+len(additions),
                 original_facts_sha256=before,sources_verified=len(verified),zeroes_from_blank_cells=0)
    updates=dict(fact_count=count+len(additions),built_at=datetime.now(timezone.utc).isoformat(),
                 data_version=hashlib.sha256((meta['data_version']+sha).encode()).hexdigest(),rap_explicit_zeros=receipt,
                 stats=dict(new.execute("select year||'/'||stage||'/'||budget,count(*) from facts group by year,stage,budget")))
    for k,v in updates.items():new.execute('insert or replace into meta values(?,?)',(k,json.dumps(v,ensure_ascii=False)))
    assert rows_digest(new,last)==before
    new.commit();assert new.execute('pragma integrity_check').fetchone()[0]=='ok'
    new.close();db.close();staged.chmod(0o644)
    audit=data/'derived/data-audit.json'
    if audit.exists():shutil.copyfile(audit,backup/'data-audit-before.json')
    staged.replace(target)
    # A new independent audit must run; never reuse the previous success flag.
    (backup/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    shutil.copyfile(plan_path,backup/'plan.json')
    print(json.dumps(receipt))

if __name__=='__main__':install()

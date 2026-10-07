"""Archive a validated manual collection without altering monetary observations.

Run offline with /incoming read-only, /inputs read-only and /data writable.
The host publishes manifest-merged.json as MANIFEST-COLLECTE.json after success.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from budget_service import topics

DATA=Path('/data')
BATCH_NAME=os.environ.get('BUDGET_IMPORT_BATCH','import-collecte-20260908')
if not re.fullmatch(r'import-[a-z0-9-]+',BATCH_NAME):raise ValueError('Invalid batch name')
BATCH=Path('/inputs')/BATCH_NAME
INCOMING=Path('/incoming')

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def safe(root,relative):
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Path outside archive root')
    return path

def facts_digest(db):
    h=hashlib.sha256()
    for row in db.execute('SELECT * FROM facts ORDER BY rowid'):
        h.update(json.dumps(tuple(row),ensure_ascii=False,separators=(',',':')).encode())
        h.update(b'\n')
    return h.hexdigest()

def main():
    plan=json.loads((BATCH/'plan.json').read_text())
    manifest=json.loads((BATCH/'manifest-merged.json').read_text())
    database=DATA/'derived/budget.sqlite'
    old=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
    old_sources={sid:json.loads(raw) for sid,raw in old.execute('SELECT id,data FROM sources')}
    old_meta={k:json.loads(v) for k,v in old.execute('SELECT key,value FROM meta')}
    before=facts_digest(old)
    ids={hashlib.sha256(r['path'].encode()).hexdigest()[:20] for r in manifest}
    if not set(old_sources)<=ids:raise ValueError('Merged manifest would drop existing sources')
    topic_hashes={r['sha256'] for r in topics.sources()}
    if any(r['sha256'] in topic_hashes for r in plan['new_records']):raise ValueError('Topic source duplicate requires reconciliation')
    for item in plan['items']:
        source=safe(INCOMING,item['filename'])
        if not source.is_file() or source.stat().st_size!=item['bytes'] or digest(source)!=item['sha256']:
            raise ValueError('Incoming file changed since validation: '+item['filename'])
    backup=DATA/'imports'/BATCH_NAME.removeprefix('import-')
    backup.mkdir(parents=True,exist_ok=True)
    if not (backup/'budget-before.sqlite').exists():
        with sqlite3.connect(backup/'budget-before.sqlite') as dest:old.backup(dest)
        shutil.copyfile(DATA/'derived/normalization-report.json',backup/'normalization-report-before.json')
    for item in plan['items']:
        target=safe(DATA,item['path'])
        if target.exists():
            if digest(target)!=item['sha256']:raise ValueError('Existing archive differs: '+item['path'])
            continue
        if item['disposition']=='already_present':raise ValueError('Existing catalogue file missing')
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_suffix(target.suffix+'.importing')
        shutil.copyfile(safe(INCOMING,item['filename']),temporary)
        if digest(temporary)!=item['sha256']:raise ValueError('Copy verification failed')
        temporary.chmod(0o644);temporary.replace(target)
    temporary=DATA/'derived/budget.collection.sqlite'
    if temporary.exists():raise ValueError('An earlier staged database requires inspection')
    new=sqlite3.connect(temporary)
    try:
        old.backup(new)
        for record in manifest:
            sid=hashlib.sha256(record['path'].encode()).hexdigest()[:20]
            obj={**old_sources.get(sid,{}),**record,'id':sid}
            obj['imported']=old_sources.get(sid,{}).get('imported',False)
            obj['title']=record.get('title') or record.get('dataset_title') or record.get('dataset_id') or Path(record['path']).name
            new.execute('INSERT OR REPLACE INTO sources(id,data) VALUES (?,?)',(sid,json.dumps(obj,ensure_ascii=False)))
        now=datetime.now(timezone.utc).isoformat()
        for key,value in [('source_count',len(manifest)),('catalogue_updated_at',now)]:
            new.execute('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)',(key,json.dumps(value)))
        new.commit()
        if new.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity failure')
        if facts_digest(new)!=before:raise ValueError('Monetary observations changed')
        if new.execute('SELECT COUNT(*) FROM sources').fetchone()[0]!=len(manifest):raise ValueError('Source count mismatch')
        for key in ['built_at','fact_count','imported_source_count']:
            if json.loads(new.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()[0])!=old_meta[key]:
                raise ValueError('Numeric metadata changed: '+key)
    finally:new.close();old.close()
    temporary.chmod(0o644);temporary.replace(database)
    report_path=DATA/'derived/normalization-report.json'
    report=json.loads(report_path.read_text());report.update(source_count=len(manifest),catalogue_updated_at=now)
    staged=report_path.with_suffix('.importing');staged.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');staged.chmod(0o644);staged.replace(report_path)
    receipt=dict(at=now,summary=plan['summary'],fact_count=old_meta['fact_count'],facts_sha256=before,
                 numeric_built_at=old_meta['built_at'],source_count=len(manifest),public_source_count=len(manifest)+len(topics.sources()),
                 database_sha256=digest(database),files=plan['items'])
    (backup/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='files'},ensure_ascii=False))

if __name__=='__main__':main()

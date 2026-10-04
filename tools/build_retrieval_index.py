"""Resume assembly of existing dense/sparse vectors. No encoding or paid API."""
import argparse,collections,hashlib,json,sqlite3,sys
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plfss_service.retrieval_contract import VERSION,MODEL,REVISION,DIMENSION,digest,read_db,write_json

def schema(db):
 db.executescript('''PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; PRAGMA temp_store=MEMORY;
 CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS parts(name TEXT PRIMARY KEY,sha256 TEXT NOT NULL,count INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS passages(seq INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,text TEXT NOT NULL,tokens INTEGER NOT NULL,text_sha256 TEXT NOT NULL,sparse_ids BLOB NOT NULL,sparse_weights BLOB NOT NULL);
 CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY,reference_id TEXT UNIQUE NOT NULL,source_sha256 TEXT NOT NULL,source_id TEXT NOT NULL,title TEXT NOT NULL,url TEXT NOT NULL,format TEXT NOT NULL,years_key TEXT NOT NULL,stage TEXT NOT NULL,source_kind TEXT NOT NULL,table_layout TEXT NOT NULL,numeric_status TEXT NOT NULL,local_available INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS citations(seq INTEGER NOT NULL,document_id INTEGER NOT NULL,locator TEXT NOT NULL,PRIMARY KEY(seq,document_id,locator));
 CREATE INDEX IF NOT EXISTS document_citations ON citations(document_id,seq);
 CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(text,content='passages',content_rowid='seq',tokenize='unicode61 remove_diacritics 2');''')

def validate_vectors(rows,np):
 dense=np.vstack([np.frombuffer(r['dense'],dtype='<f2') for r in rows]).astype('float32')
 if dense.shape!=(len(rows),DIMENSION) or not np.isfinite(dense).all() or not np.all(np.abs(np.linalg.norm(dense,axis=1)-1)<.006):raise ValueError('Invalid dense vectors')
 for r in rows:
  ids=np.frombuffer(r['sparse_ids'],dtype='<i4');weights=np.frombuffer(r['sparse_weights'],dtype='<f4')
  if len(ids)!=r['nnz'] or len(weights)!=r['nnz'] or len(set(ids))!=len(ids) or not np.isfinite(weights).all() or (weights<0).any() or (ids<0).any():raise ValueError('Invalid sparse vector')
 return dense

def build(args):
 import numpy as np,faiss
 faiss.omp_set_num_threads(args.threads)
 out=args.output.resolve();out.mkdir(parents=True,exist_ok=True);(out/'shards').mkdir(exist_ok=True)
 def progress(phase,**extra):
  value=dict(at=datetime.now(timezone.utc).isoformat(),phase=phase,encoding=False,**extra);write_json(out/'progress.json',value);print(json.dumps(value),flush=True)
 backup=json.loads((args.run/'LOCAL_BACKUP_VERIFIED.json').read_text(encoding='utf-8'))
 terminal=backup['terminal'];parts=terminal['parts'];expected=backup['verified_count'];identity=backup['input_sha256']
 if terminal['status']!='complete' or terminal['unpublished_rows'] or terminal['produced_count']!=expected:raise ValueError('Incomplete RunPod result')
 position=0
 for p in parts:
  if p['start_line']!=position or p['end_line']-position!=p['count'] or p['input_sha256']!=identity or Path(p['file']).name!=p['file']:raise ValueError('Mixed or incomplete vector generation')
  position=p['end_line']
 if position!=expected:raise ValueError('Vector coverage mismatch')
 ready=out/'manifest.json'
 if ready.exists():
  m=json.loads(ready.read_text(encoding='utf-8'))
  if m.get('version')==VERSION and m.get('state')=='ready' and m.get('input_sha256')==identity and all(digest(out/f['path'])==f['sha256'] for f in m['files']):
   progress('complete',completed=expected,expected=expected,already_complete=True);return
 db=sqlite3.connect(out/'search.sqlite');db.row_factory=sqlite3.Row;schema(db)
 old=dict(db.execute('SELECT key,value FROM metadata'))
 if old and (old.get('input_sha256')!=identity or old.get('version')!=VERSION):raise ValueError('Another generation already exists')
 db.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[('input_sha256',identity),('version',VERSION),('state','building')]);db.commit()
 source=read_db(args.catalogue);references=collections.defaultdict(list);checked={}
 current={s['id']:s for s in json.loads((args.data/'catalogue/normalized-sources.json').read_text(encoding='utf-8'))}
 for r in source.execute('SELECT * FROM sources ORDER BY id'):
  s=json.loads(r['metadata']);active=current.get(s['id']);sha=r['asset_sha']
  if not active or active.get('status')!='downloaded' or active.get('sha256')!=sha:raise ValueError('Source no longer matches prepared catalogue')
  target=(args.data/s['path']).resolve()
  if not target.is_relative_to(args.data.resolve()) or not target.is_file():raise ValueError('Missing source file')
  if sha not in checked:checked[sha]=digest(target)
  if checked[sha]!=sha:raise ValueError('Source checksum mismatch')
  url=active['url']
  if urlsplit(url).scheme not in ('http','https'):raise ValueError('Invalid official URL')
  fmt=target.suffix.lower().lstrip('.');fmt='html' if fmt in ('htm','asp') else fmt
  fields=[s['id'],sha,s['id'],s['title'],url,fmt,'|'+str(s['publication_year'])+'|',s.get('kind',''),s['family'],'source_locators','not_validated_budget_fact',1]
  db.execute('INSERT OR IGNORE INTO documents(reference_id,source_sha256,source_id,title,url,format,years_key,stage,source_kind,table_layout,numeric_status,local_available) VALUES('+','.join('?' for _ in fields)+')',fields)
  references[sha].append(db.execute('SELECT id FROM documents WHERE reference_id=?',(s['id'],)).fetchone()[0])
 db.commit();progress('sources_verified',physical_files=len(checked),documents=sum(map(len,references.values())))
 part_dir=args.run/'parts'/terminal['job_name'];trained=out/'trained.faiss'
 if not trained.exists():
  samples=[]
  for p in parts:
   with closing(read_db(part_dir/p['file'])) as con:
    meta=dict(con.execute('SELECT key,value FROM metadata'))
    if (meta.get('model'),meta.get('revision'),meta.get('input_sha256'))!=(MODEL,REVISION,identity):raise ValueError('Part encoding contract mismatch')
    for r in con.execute('SELECT dense FROM vectors WHERE seq % 32 = 0 ORDER BY seq'):samples.append(np.frombuffer(r[0],dtype='<f2'))
  sample=np.asarray(samples,dtype='float32');del samples
  nlist=min(512,max(1,len(sample)//48));progress('training_search_index',sample_vectors=len(sample),expected=expected)
  idx=faiss.IndexIVFScalarQuantizer(faiss.IndexFlatIP(DIMENSION),DIMENSION,nlist,faiss.ScalarQuantizer.QT_8bit,faiss.METRIC_INNER_PRODUCT)
  idx.cp.niter=12;idx.cp.seed=20261004;idx.train(sample);faiss.write_index(idx,str(trained));del idx,sample
 complete=dict(db.execute('SELECT name,sha256 FROM parts'))
 for p in parts:
  name=p['file'];shard=out/'shards'/(name+'.faiss')
  if name in complete:
   if complete[name]!=p['sha256'] or not shard.is_file():raise ValueError('Bad index checkpoint')
   continue
  if digest(part_dir/name)!=p['sha256']:raise ValueError('Part checksum mismatch')
  with closing(read_db(part_dir/name)) as con:
   meta=dict(con.execute('SELECT key,value FROM metadata'));rows=con.execute('SELECT * FROM vectors ORDER BY seq').fetchall()
  if (meta.get('model'),meta.get('revision'),meta.get('input_sha256'))!=(MODEL,REVISION,identity):raise ValueError('Part model mismatch')
  if [r['seq'] for r in rows]!=list(range(p['start_line'],p['end_line'])):raise ValueError('Bad part sequence')
  dense=validate_vectors(rows,np);idx=faiss.read_index(str(trained));idx.add_with_ids(dense,np.asarray([r['seq']+1 for r in rows],dtype='int64'))
  temp=shard.with_suffix('.tmp');faiss.write_index(idx,str(temp));temp.replace(shard);del idx,dense
  with db:
   for start in range(0,len(rows),400):
    batch=rows[start:start+400];by_id={r['chunk_id']:r for r in batch};marks=','.join('?' for _ in batch)
    texts=source.execute('SELECT * FROM passages WHERE id IN ('+marks+')',list(by_id)).fetchall()
    if len(texts)!=len(batch):raise ValueError('Missing original passage')
    for t in texts:
     v=by_id[t['id']]
     if hashlib.sha256(t['text'].encode('utf-8')).hexdigest()!=v['text_sha256'] or t['tokens']>800:raise ValueError('Passage changed since encoding')
     db.execute('INSERT INTO passages VALUES(?,?,?,?,?,?,?)',(v['seq']+1,t['id'],t['text'],t['tokens'],v['text_sha256'],v['sparse_ids'],v['sparse_weights']))
     db.execute('INSERT INTO passages_fts(rowid,text) VALUES(?,?)',(v['seq']+1,t['text']))
    cited=set()
    for occ in source.execute('SELECT passage_id,asset_sha,locator FROM occurrences WHERE passage_id IN ('+marks+')',list(by_id)):
     for docid in references.get(occ['asset_sha'],[]):
      db.execute('INSERT OR IGNORE INTO citations VALUES(?,?,?)',(by_id[occ['passage_id']]['seq']+1,docid,occ['locator']));cited.add(occ['passage_id'])
    if cited!=set(by_id):raise ValueError('Passage without source citation')
   db.execute('INSERT INTO parts VALUES(?,?,?)',(name,p['sha256'],p['count']))
  progress('indexing',completed=p['end_line'],expected=expected,part=name)
 index_path=out/'dense.faiss'
 if not index_path.exists():
  progress('merging',completed=expected,expected=expected);idx=faiss.read_index(str(trained))
  for p in parts:idx.merge_from(faiss.read_index(str(out/'shards'/(p['file']+'.faiss'))),0)
  if idx.ntotal!=expected:raise ValueError('Dense index count mismatch')
  idx.nprobe=min(64,idx.nlist);temp=out/'dense.faiss.tmp';faiss.write_index(idx,str(temp));temp.replace(index_path);del idx
 if db.execute('SELECT count(*) FROM passages').fetchone()[0]!=expected or db.execute('SELECT count(*) FROM passages WHERE seq NOT IN(SELECT seq FROM citations)').fetchone()[0]:raise ValueError('Incomplete search index')
 if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Search database integrity failure')
 documents=db.execute('SELECT count(DISTINCT document_id) FROM citations').fetchone()[0]
 with db:db.executemany('INSERT OR REPLACE INTO metadata VALUES(?,?)',[('state','ready'),('passage_count',str(expected)),('document_count',str(documents))])
 db.close();source.close();progress('checksums',completed=expected,expected=expected)
 manifest=dict(version=VERSION,state='ready',model=MODEL,revision=REVISION,dimension=DIMENSION,input_sha256=identity,passages=expected,documents=documents,physical_files=len(checked),quantization='IVF/SQ8',sparse='candidate_reranking_float32',colbert=False,numeric_facts_certified=False,generated_at=datetime.now(timezone.utc).isoformat(),files=[dict(path=n,bytes=(out/n).stat().st_size,sha256=digest(out/n)) for n in ['search.sqlite','dense.faiss']])
 write_json(out/'manifest.json',manifest);progress('complete',completed=expected,expected=expected,documents=documents)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for n in ['run','catalogue','data','output']:p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--threads',type=int,default=3);build(p.parse_args())

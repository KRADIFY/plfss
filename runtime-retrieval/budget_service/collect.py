"""Archive public budget sources. No shared corpus or credential is modified."""
import concurrent.futures,csv,hashlib,json,os,re,shutil,time,zipfile
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.parse import urlparse
from urllib.error import HTTPError
ROOT=Path('/data');META=ROOT/'metadata';RAW=ROOT/'raw';LIMIT=512*1024*1024
class Invalid(Exception):pass
def stamp():return datetime.now(timezone.utc).isoformat()
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def write_json(p,j):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp')
 with t.open('w',encoding='utf-8') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 t.replace(p)
def slug(s):return re.sub('[^a-zA-Z0-9._-]+','_',s)[:85]+'-'+hashlib.sha256(s.encode()).hexdigest()[:8]
def validate(p,kind):
 with p.open('rb') as f:head=f.read(4096)
 if not head:raise Invalid('empty_file')
 if b'<html' in head.lower() or b'<!doctype html' in head.lower():raise Invalid('html_instead_of_file')
 if kind=='pdf':
  if not head.startswith(b'%PDF-'):raise Invalid('pdf_signature_missing')
  with p.open('rb') as f:
   f.seek(max(0,p.stat().st_size-4096));tail=f.read()
  if b'%%EOF' not in tail:raise Invalid('pdf_end_marker_missing')
  return {'format':'pdf'}
 if kind in ('zip','xlsx'):
  if not zipfile.is_zipfile(p):raise Invalid('invalid_zip')
  with zipfile.ZipFile(p) as z:
   entries=z.infolist()
   if sum(x.file_size for x in entries)>2*1024**3:raise Invalid('zip_uncompressed_limit')
   bad=z.testzip()
   if bad:raise Invalid('zip_crc_failed')
   return {'format':kind,'archive_entries':len(entries),'archive_members':[x.filename for x in entries][:500]}
 if kind=='xls':
  if not head.startswith(bytes.fromhex('d0cf11e0a1b11ae1')) and not head.startswith(b'PK'):raise Invalid('xls_signature_missing')
  return {'format':'xls','validation':'signature_only'}
 if kind=='csv':
  enc=None
  for encoding in ('utf-8-sig','cp1252','latin-1'):
   try:
    with p.open(encoding=encoding,newline='') as f:
     sample=f.read(16384);f.seek(0)
     try:delim=csv.Sniffer().sniff(sample,delimiters=';,\t|').delimiter
     except csv.Error:delim=';'
     reader=csv.reader(f,delimiter=delim);header=next(reader,[]);n=sum(1 for row in reader if any(row))
    enc=encoding;break
   except UnicodeError:continue
  if not enc:raise Invalid('csv_decode_failed')
  return {'format':'csv','rows':n,'columns':header,'encoding':enc,'delimiter':delim}
 return {'format':kind,'validation':'nonempty_nonhtml'}
def fetch_job(job):
 start=time.monotonic();result={**job,'checked_at':stamp()};p=ROOT/job['path'];p.parent.mkdir(parents=True,exist_ok=True)
 receipt=p.with_suffix(p.suffix+'.receipt.json')
 try:
  if p.exists() and receipt.exists():
   old=json.loads(receipt.read_text())
   if digest(p)==old.get('sha256') and old.get('url')==job['url'] and old.get('repair_revision')==job.get('repair_revision'):
    return {**old,'reused':True,'checked_at':stamp()}
  u=urlparse(job['url'])
  if u.scheme!='https' or not (u.hostname.endswith('.gouv.fr') or u.hostname in ('www.assemblee-nationale.fr','www2.assemblee-nationale.fr','questions.assemblee-nationale.fr','www.senat.fr','bdm.insee.fr')):raise Invalid('unapproved_public_host')
  temp=p.with_suffix(p.suffix+'.part')
  with urlopen(Request(job['url'],headers={'User-Agent':'LexMachine-Budget/0.1'}),timeout=45) as response,temp.open('wb') as out:
   size=0;declared=response.headers.get('Content-Length')
   result['http_status']=response.status;result['declared_bytes']=int(declared) if declared else None
   for b in iter(lambda:response.read(1024*1024),b''):
    size+=len(b)
    if size>LIMIT:raise Invalid('file_exceeds_512MiB')
    out.write(b)
   if declared and size!=int(declared):raise Invalid('incomplete_http_body')
   out.flush();os.fsync(out.fileno())
   result['content_type']=response.headers.get('Content-Type');result['final_url']=response.url
  info=validate(temp,job['kind']);result.update(info)
  if job.get('expected_rows') is not None and info.get('rows')!=job['expected_rows']:
   result['row_count_warning']={'catalogue':job['expected_rows'],'received':info.get('rows')}
  result.update(status='downloaded',bytes=temp.stat().st_size,sha256=digest(temp))
  if p.exists() and job.get('repair_revision'):
   archived=ROOT/'quarantine'/('before-repair-'+str(job['repair_revision']))/job['path'];archived.parent.mkdir(parents=True,exist_ok=True)
   shutil.copyfile(p,archived)
   if receipt.exists():shutil.copyfile(receipt,archived.with_suffix(archived.suffix+'.receipt.json'))
  temp.replace(p);write_json(receipt,result)
 except HTTPError as e:result.update(status='failed',error='http_'+str(e.code))
 except Invalid as e:result.update(status='failed',error=str(e))
 except Exception as e:result.update(status='failed',error=type(e).__name__)
 result['duration_ms']=round((time.monotonic()-start)*1000);return result

def fetch_with_retries(job):
 for attempt in range(1,4):
  r=fetch_job(job)
  if r['status']=='downloaded':return r
  r['attempts']=attempt
 return r

def main():
 for p in (META,RAW,ROOT/'manual'):p.mkdir(parents=True,exist_ok=True)
 catalogue=json.loads(Path('/inputs/catalogue-budget-selection.json').read_text());write_json(META/'catalogue-budget.json',catalogue)
 write_json(META/'catalogue-complet.json',json.loads(Path('/inputs/catalogue-data-economie.json').read_text()))
 jobs=[]
 for d in catalogue:
  ds=d['dataset_id'];m=d['metas']['default'];version=hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:12]
  folder='raw/api/'+slug(ds)+'/'+version
  common={'dataset_id':ds,'dataset_title':m['title'],'years_title':sorted(set(re.findall(r'20\d{2}',m['title']))),'license':m.get('license'),'modified':m.get('modified')}
  if d.get('has_records') and (m.get('records_count') or 0)>0:
   jobs.append({**common,'url':'https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/'+ds+'/exports/csv?use_labels=false&delimiter=%3B','path':folder+'/records.csv','kind':'csv','expected_rows':m['records_count'],'role':'complete_api_export'})
  for a in d.get('attachments',[]):
   ext=Path(a['title']).suffix.lower().lstrip('.')
   if ext not in ('csv','xls','xlsx','zip','pdf','xml','json','txt','ods'):ext={'text/csv':'csv','application/pdf':'pdf','application/zip':'zip'}.get(a.get('mimetype'),'bin')
   jobs.append({**common,'url':a['url'],'path':folder+'/'+slug(a['title'])+'.'+ext,'kind':ext,'title':a['title'],'role':'attachment'})
 # Extra public resources supplied in a reviewed manifest.
 extra=Path('/inputs/additional-public-links.json')
 if extra.exists():jobs+=json.loads(extra.read_text())
 # Archive the user-supplied PDF unchanged.
 source=Path('/incoming/FR_2025_PLRG_TA_PGM_205.pdf');target=ROOT/'manual/2025/FR_2025_PLRG_TA_PGM_205.pdf';target.parent.mkdir(parents=True,exist_ok=True)
 manual={'role':'user_supplied','path':str(target.relative_to(ROOT)),'title':'RAP 2025 programme 205','status':'downloaded','checked_at':stamp()}
 validate(source,'pdf');shutil.copyfile(source,target);manual.update(bytes=target.stat().st_size,sha256=digest(target),source_sha256=digest(source));write_json(META/'manual-receipt.json',manual)
 # Deduplicate requests by URL, retaining metadata for aliases.
 unique={}
 for job in jobs:unique.setdefault(job['url'],job)
 jobs=list(unique.values());write_json(META/'download-plan.json',jobs)
 results=[manual];write_json(META/'progress.json',{'phase':'running','planned':len(jobs),'done':0,'at':stamp()})
 with (META/'events.jsonl').open('a',encoding='utf-8') as log,concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  futures=[pool.submit(fetch_with_retries,j) for j in jobs]
  for f in concurrent.futures.as_completed(futures):
   r=f.result();results.append(r);log.write(json.dumps(r,ensure_ascii=False)+'\n');log.flush();os.fsync(log.fileno())
   done=len(results)-1
   write_json(META/'progress.json',{'phase':'running','planned':len(jobs),'done':done,'downloaded':sum(x['status']=='downloaded' for x in results),'failed':sum(x['status']=='failed' for x in results),'bytes':sum(x.get('bytes',0) for x in results),'at':stamp()})
   if done%20==0 or r['status']=='failed':print(json.dumps({'done':done,'total':len(jobs),'status':r['status'],'title':r.get('title',r.get('dataset_title')),'error':r.get('error')},ensure_ascii=False),flush=True)
 write_json(META/'manifest.json',results)
 summary={'phase':'finished','at':stamp(),'catalogue_datasets':len(catalogue),'planned_downloads':len(jobs),'files_received':sum(x['status']=='downloaded' for x in results),'failed':sum(x['status']=='failed' for x in results),'bytes':sum(x.get('bytes',0) for x in results),'row_count_warnings':sum('row_count_warning' in x for x in results),'csv_rows':sum(x.get('rows',0) for x in results),'complete_national_history':False}
 write_json(META/'summary.json',summary);write_json(META/'progress.json',summary);print(json.dumps(summary),flush=True)
if __name__=='__main__':main()

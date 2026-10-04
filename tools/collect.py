"""Official-source collection, resumable, hashes and explicit failures. No inference of availability."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin,urlsplit,unquote
import lxml.html

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
BASE='https://www.securite-sociale.fr'
INDEX=BASE+'/la-secu-en-detail/loi-de-financement/annees-passees'
HOSTS=('securite-sociale.fr','assemblee-nationale.fr','senat.fr','legifrance.gouv.fr','ccomptes.fr','conseil-constitutionnel.fr','gouv.fr','insee.fr','tricoteuses.fr')
EXTENSIONS={'.pdf','.xlsx','.xls','.csv','.zip','.ods','.odt','.doc','.docx','.xml'}


def now():return datetime.now(timezone.utc).isoformat()
def identity(url):return hashlib.sha256(url.encode()).hexdigest()[:24]
def allowed(url):
 p=urlsplit(url)
 return p.scheme=='https' and not p.username and not p.password and any(p.hostname==h or (p.hostname or '').endswith('.'+h) for h in HOSTS)
def atomic(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix('.new')
 tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
 tmp.replace(path)
def safe_name(text):return re.sub(r'[^A-Za-z0-9._-]+','_',text)[:140] or 'document'
def fetch(url,path):
 if not allowed(url):raise ValueError('Nonofficial source refused')
 path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix(path.suffix+'.partial')
 exe=shutil.which('curl.exe') or shutil.which('curl')
 if not exe:raise RuntimeError('curl with verified TLS required')
 result=subprocess.run([exe,'--fail','--silent','--show-error','--location','--max-time','120','--retry','1','--user-agent','NosDeniers-PLFSS/1.0','--output',str(temp),'--write-out','%{http_code}|%{url_effective}|%{content_type}',url],capture_output=True,text=True,timeout=260)
 if result.returncode:
  temp.unlink(missing_ok=True)
  raise RuntimeError('HTTP retrieval failed, curl='+str(result.returncode))
 status,final,mime=result.stdout.strip().split('|',2)
 if status!='200' or not allowed(final):
  temp.unlink(missing_ok=True)
  raise RuntimeError('Invalid final source')
 if temp.stat().st_size==0:raise ValueError('Empty document')
 temp.replace(path)
 return dict(final_url=final,mime=mime.split(';')[0],bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def anchors(raw,url):
 doc=lxml.html.fromstring(raw)
 body=doc
 for a in body.xpath('.//a[@href]'):
  target=urljoin(url,a.get('href')).split('#')[0]
  # Historical official catalogue links still use HTTP; retain the observed
  # path and request it over authenticated HTTPS.
  if target.startswith('http://') and allowed('https://'+target[7:]):target='https://'+target[7:]
  if allowed(target):yield (' '.join(a.itertext()).strip(),target,a)

def classify(title,url):
 t=(title+' '+unquote(url)).lower()
 if 'placss' in t or 'lacss' in t:return 'PLACSS'
 if 'lfrss' in t or 'rectificative' in t:return 'LFRSS'
 if any(w in t for w in ['rep ss','repss','pqe','qualit','efficience']):return 'REPSS-PQE'
 if 'commission' in t and 'comptes' in t:return 'CCSS'
 if 'ccomptes.fr' in t:return 'Cour des comptes'
 if 'legifrance' in t:return 'LFSS promulguée'
 return 'PLFSS et annexes'

def row(title,url,year,parent,kind='document'):
 return dict(id=identity(url),title=title or unquote(urlsplit(url).path.rsplit('/',1)[-1]),url=url,publication_year=year,parent_url=parent,kind=kind,family=classify(title,url),status='inventoried',collected_at=None)

def document_worker(r):
 r=dict(r)
 path=DATA/'documents'/str(r['publication_year'])/(r['id']+'_'+safe_name(unquote(urlsplit(r['url']).path.rsplit('/',1)[-1])))
 if '.' not in path.name:path=path.with_suffix('.html')
 try:
  result=fetch(r['url'],path)
  head=path.read_bytes()[:1200].lstrip()
  suffix=path.suffix.lower()
  if suffix=='.pdf' and not head.startswith(b'%PDF-'):raise ValueError('PDF expected, other content received')
  if suffix in ('.zip','.xlsx','.ods','.docx') and not head.startswith(b'PK'):raise ValueError('Archive expected, other content received')
  if head.startswith(b'%PDF-') and suffix!='.pdf':
   new=path.with_suffix('.pdf');path.replace(new);path=new
  r.update(result,status='downloaded',path=str(path.relative_to(DATA)).replace('\\','/'),collected_at=now())
  if path.suffix.lower()=='.zip':
   children=[]
   folder=path.with_suffix('')
   with zipfile.ZipFile(path) as z:
    for member in z.infolist():
     target=(folder/member.filename).resolve()
     if member.is_dir():continue
     if not target.is_relative_to(folder.resolve()) or member.file_size>150_000_000 or (member.external_attr >> 16)&0o170000==0o120000:
      raise ValueError('Unsafe archive member')
     if target.suffix.lower() not in EXTENSIONS:continue
     target.parent.mkdir(parents=True,exist_ok=True)
     with z.open(member) as source,target.open('wb') as out:shutil.copyfileobj(source,out)
     child=dict(r,id=identity(r['id']+'!'+member.filename),title=r['title']+' / '+member.filename,
                path=str(target.relative_to(DATA)).replace('\\','/'),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bytes=target.stat().st_size,
                archive_id=r['id'],archive_member=member.filename,kind='archive_member')
     children.append(child)
   r['children']=children
 except Exception as error:
  r.update(status='failed',error_type=type(error).__name__,error=str(error)[:160])
 return r

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--workers',type=int,default=4)
 args=parser.parse_args()
 page_rows=[];records={};coverage=[]
 initial=DATA/'catalogue/dss-index.html'
 fetch(INDEX,initial)
 pages={}
 for title,url,a in anchors(initial.read_bytes(),INDEX):
  match=re.search(r'(?<!\d)(20\d\d)(?!\d)',title)
  if match and 2017<=int(match[1])<=2027 and any(s in title.upper() for s in ('PLFSS','LFSS','LACSS','PLACSS','LFRSS')):
   pages[url]=(int(match[1]),title)
 if not {2017,2026,2027}.issubset({year for year,title in pages.values()}):raise RuntimeError('Annual catalogue discovery incomplete')
 for url,(year,title) in pages.items():
  saved=DATA/'catalogue'/(identity(url)+'.html')
  p=row(title,url,year,INDEX,'catalogue')
  try:
   p.update(fetch(url,saved),status='downloaded',path=str(saved.relative_to(DATA)).replace('\\','/'),collected_at=now())
   raw=saved.read_bytes();doc=lxml.html.fromstring(raw)
   actual=' '.join(doc.xpath('//h1//text()')).strip()
   p['page_title']=actual
   text=' '.join(doc.itertext())
   if year==2027 and 'venir' in text.lower():
    coverage.append(dict(year=year,source=url,note='Des annexes 2027 sont annoncees a venir par la DSS. Aucun chiffre invente.',checked_at=now()))
   for label,target,a in anchors(raw,url):
    ext=Path(urlsplit(target).path).suffix.lower()
    if ext in EXTENSIONS or 'file-download' in target or ('assemblee-nationale.fr' in target and any(s in target for s in ['/projets/','/dyn/opendata/','_projet-loi','plfss'])) or 'legifrance.gouv.fr' in target or ('conseil-constitutionnel.fr' in target and 'decision/' in target):
     # The page's publication year is only document metadata, never the accounting year of a value.
     records.setdefault(identity(target),row(label,target,year,url))
  except Exception as error:p.update(status='failed',error=str(error)[:160])
  page_rows.append(p)
  print(json.dumps(dict(catalogue_year=year,status=p['status'],documents=len(records))),flush=True)
 # The deposited PLFSS 2027 identity was verified in Moulineuse, not inferred from a filename.
 an2027='https://www.assemblee-nationale.fr/dyn/opendata/PRJLANR5L17B3211.html'
 records[identity(an2027)]=row('PLFSS 2027 - texte initial depose (PRJLANR5L17B3211)',an2027,2027,'https://www.tricoteuses.fr/redirection/PRJLANR5L17B3211')
 extra=DATA/'catalogue/additional-sources.json'
 if extra.exists():
  for r in json.loads(extra.read_text(encoding='utf-8')):records.setdefault(r['id'],r)
 previous=DATA/'catalogue/documents.json'
 cached={r['id']:r for r in json.loads(previous.read_text(encoding='utf-8'))} if previous.exists() else {}
 # A source disappearing from today's catalogue is not grounds to erase a
 # verified historical download from this project's documentary inventory.
 for old in cached.values():
  if old.get('status')=='downloaded' and not old.get('archive_id'):records.setdefault(old['id'],old)
 pending=[];done=[]
 for r in records.values():
  old=cached.get(r['id'])
  if old and old.get('status')=='downloaded' and (DATA/old['path']).is_file() and hashlib.sha256((DATA/old['path']).read_bytes()).hexdigest()==old['sha256']:
   merged=dict(old)
   for key in ('title','publication_year','parent_url','family','source_role','uid','deposit_date'):
    if key in r:merged[key]=r[key]
   done.append(merged)
  else:pending.append(r)
 atomic(DATA/'catalogue/pages.json',page_rows)
 atomic(DATA/'catalogue/coverage.json',coverage)
 with concurrent.futures.ThreadPoolExecutor(max_workers=min(max(args.workers,1),4)) as pool:
  for r in pool.map(document_worker,pending):
   children=r.pop('children',[])
   done.extend([r,*children])
   atomic(previous,done)
   print(json.dumps(dict(downloaded=sum(x['status']=='downloaded' for x in done),failed=sum(x['status']=='failed' for x in done),remaining=len(pending)-sum(x.get('kind')!='archive_member' and x['id'] in {p['id'] for p in pending} for x in done))),flush=True)
 # Preserve already catalogued archive members on resumed collection.
 for old in cached.values():
  if old.get('archive_id') in records and old['id'] not in {r['id'] for r in done}:done.append(old)
 atomic(previous,done)
 result=dict(checked_at=now(),catalogue_pages=len(page_rows),documents=len(done),downloaded=sum(r['status']=='downloaded' for r in done),failed=sum(r['status']=='failed' for r in done),bytes=sum(r.get('bytes',0) for r in done),years=sorted({r['publication_year'] for r in done}),site_modified=False)
 atomic(ROOT/'reports/collection.json',result)
 print(json.dumps(result),flush=True)

if __name__=='__main__':main()

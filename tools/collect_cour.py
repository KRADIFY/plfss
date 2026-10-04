"""Discover observed official Cour des comptes files, without inventing PDF URLs."""
import concurrent.futures,json
from urllib.parse import urlsplit
from pathlib import Path
from collect import DATA,ROOT,fetch,anchors,identity,row,atomic

def annual(year):
 url=f'https://www.ccomptes.fr/fr/publications/securite-sociale-{year}'
 saved=DATA/'catalogue'/f'cour-{year}.html'
 try:
  meta=fetch(url,saved);refs=[]
  for title,target,node in anchors(saved.read_bytes(),url):
   if Path(urlsplit(target).path).suffix.lower() in ('.pdf','.zip','.xlsx','.csv'):
    r=row(title,target,year,url);r['family']='Cour des comptes';refs.append(r)
  return {'year':year,'url':url,'status':'downloaded','files':len(refs),**meta},refs
 except Exception as exc:return {'year':year,'url':url,'status':'not_retrieved','reason':str(exc)},[]

def main():
 extra=DATA/'catalogue/additional-sources.json'
 records={r['id']:r for r in json.loads(extra.read_text(encoding='utf-8'))}
 pages=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  for page,refs in pool.map(annual,range(2017,2027)):
   pages.append(page)
   for r in refs:records.setdefault(r['id'],r)
   print(json.dumps(page),flush=True)
 atomic(extra,list(records.values()));atomic(ROOT/'reports/cour-discovery.json',pages)
if __name__=='__main__':main()

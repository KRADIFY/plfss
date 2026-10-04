"""Check complete import and live retrieval without rewriting financial data."""
import hashlib,json,sqlite3,sys,time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from plfss_service.retrieval_contract import VERSION,MODEL,REVISION,DIMENSION,digest,read_db
from plfss_service.store import Store
BASE='http://127.0.0.1:18895'
def get(path):
 with urlopen(BASE+path,timeout=125) as response:return json.load(response)
def main():
 manifest=json.loads((ROOT/'data/search/manifest.json').read_text(encoding='utf-8'))
 receipt=json.loads((ROOT/'vectorization/memo-20261004/runpod-controller/LOCAL_BACKUP_VERIFIED.json').read_text(encoding='utf-8'))
 if (manifest['version'],manifest['model'],manifest['revision'],manifest['dimension'])!=(VERSION,MODEL,REVISION,DIMENSION):raise ValueError('Wrong search model or contract')
 assert manifest['input_sha256']==receipt['input_sha256'] and manifest['passages']==receipt['verified_count']==311791
 for f in manifest['files']:assert digest(ROOT/'data/search'/f['path'])==f['sha256']
 with closing(read_db(ROOT/'data/search/search.sqlite')) as db:
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  assert db.execute('SELECT count(*) FROM passages').fetchone()[0]==311791
  assert db.execute('SELECT count(*) FROM passages WHERE seq NOT IN(SELECT seq FROM citations)').fetchone()[0]==0
  assert db.execute('SELECT count(*) FROM passages WHERE tokens>800 OR tokens<1').fetchone()[0]==0
  for row in db.execute('SELECT text,text_sha256,sparse_ids,sparse_weights FROM passages'):
   assert hashlib.sha256(row['text'].encode('utf-8')).hexdigest()==row['text_sha256']
   assert len(row['sparse_ids'])==len(row['sparse_weights'])
 meta=get('/api/meta');assert meta['vectorized'] and meta['indexed_passages']==311791 and meta['data_version']==Store(ROOT/'data').meta()['data_version']
 assert get('/api/search/status')['available']
 checked_citations=0;checks=[];hybrid_methods=set()
 sources={s['id']:s for s in json.loads((ROOT/'data/catalogue/normalized-sources.json').read_text(encoding='utf-8'))}
 cases=[dict(q='ONDAM',year=str(y),mode='text',limit=5) for y in range(2017,2028)]
 cases += [dict(q=q,year='2027',mode='hybrid',limit=5) for q in ['ONDAM','autonomie','maladie']]
 cases += [dict(q='ONDAM',year='2027',format='pdf',family='PLFSS et annexes',mode='hybrid',limit=5)]
 example=None
 for case in cases:
  started=time.monotonic();result=get('/api/search?'+urlencode(case));assert result['available']
  assert result['count']>0,(case,result)
  for item in result['items']:
   if case['mode']=='hybrid':hybrid_methods.update(item['retrieval_methods'])
   for cite in item['citations']:
    s=sources[cite['source_id']];assert s['publication_year']==int(case['year']);assert s['sha256']==cite['source_sha256'];assert cite['local_available'];checked_citations+=1
    if case.get('format'):assert cite['format']==case['format']
    if case.get('family'):assert cite['source_kind']==case['family']
   example=item
  checks.append(dict(**case,results=result['count'],seconds=round(time.monotonic()-started,3)))
 assert {'text','dense','sparse_rerank'}.issubset(hybrid_methods),hybrid_methods
 passage=get('/api/passage/'+example['id']);assert hashlib.sha256(passage['text'].encode('utf-8')).hexdigest()==example['text_sha256']
 assert passage['numeric_status']=='not_validated_budget_fact'
 missing=get('/api/search?'+urlencode(dict(q='zzxy123aucunpassageinexistant',mode='text',year=2027)));assert missing['count']==0 and not missing['missing_result_is_absence_proof']
 result=dict(passed=True,data_version=meta['data_version'],passages=manifest['passages'],indexed_documents=manifest['documents'],physical_files=manifest['physical_files'],checked_citations=checked_citations,hybrid_methods=sorted(hybrid_methods),checks=checks,financial_database_sha256=digest(ROOT/'data/derived/plfss.sqlite'),search_input_sha256=manifest['input_sha256'],model=MODEL,revision=REVISION,scope='Intégrité de tous les passages importés et recherches réelles filtrées ; ne certifie pas tous les tableaux financiers des annexes.')
 (ROOT/'reports/retrieval-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False))
if __name__=='__main__':main()

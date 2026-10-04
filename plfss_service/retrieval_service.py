"""Offline BGE-M3 query encoding and hybrid search, independent of Nos Deniers."""
import json,logging,os,re,sqlite3,threading,time
from collections import defaultdict
from contextlib import closing
from functools import lru_cache
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from .retrieval_contract import VERSION,MODEL,REVISION,DIMENSION,read_db
ROOT=Path(os.getenv('PLFSS_SEARCH_ROOT','/search'))
MODEL_PATH=Path(os.getenv('PLFSS_MODEL_PATH','/opt/lexmachine-models/models--BAAI--bge-m3/snapshots/'+REVISION))
GATE=threading.BoundedSemaphore(1)
FILTER="(?='' OR d.years_key='|' || ? || '|') AND (?='' OR d.format=?) AND (?='' OR d.source_kind=?)"

@lru_cache(maxsize=1)
def manifest():
 m=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
 if (m.get('version'),m.get('state'),m.get('model'),m.get('revision'),m.get('dimension'))!=(VERSION,'ready',MODEL,REVISION,DIMENSION):raise ValueError('Incompatible index')
 for f in m['files']:
  p=ROOT/f['path']
  if not p.resolve().is_relative_to(ROOT.resolve()) or p.stat().st_size!=f['bytes']:raise ValueError('Invalid index file')
 return m
def status():
 try:
  m=manifest();return dict(available=True,state='ready',passages=m['passages'],documents=m['documents'],physical_files=m['physical_files'],model=MODEL,revision=REVISION,method='Texte intégral + dense BGE-M3 + reclassement sparse des candidats',numeric_facts_certified=False)
 except (OSError,ValueError,KeyError):return dict(available=False,state='preparing',message='L’index documentaire PLFSS n’est pas disponible.')
@lru_cache(maxsize=1)
def encoder():
 import torch
 from transformers import AutoModel,AutoTokenizer
 if MODEL_PATH.name!=REVISION:raise ValueError('Pinned model required')
 torch.set_num_threads(int(os.getenv('PLFSS_ENCODER_THREADS','2')))
 tokenizer=AutoTokenizer.from_pretrained(str(MODEL_PATH),local_files_only=True)
 model=AutoModel.from_pretrained(str(MODEL_PATH),local_files_only=True,dtype=torch.float16).eval()
 linear=torch.nn.Linear(DIMENSION,1,dtype=torch.float16)
 linear.load_state_dict(torch.load(MODEL_PATH/'sparse_linear.pt',map_location='cpu',weights_only=True))
 return torch,tokenizer,model,linear.eval()
@lru_cache(maxsize=128)
def encode(text):
 torch,tokenizer,model,linear=encoder();inputs=tokenizer(text,return_tensors='pt',truncation=False)
 if inputs['input_ids'].shape[1]>512:raise ValueError('Query exceeds token limit')
 with torch.inference_mode():
  hidden=model(**inputs).last_hidden_state;dense=torch.nn.functional.normalize(hidden[:,0].float(),p=2,dim=1).numpy();weights=torch.relu(linear(hidden)).squeeze(-1)[0].tolist()
 sparse={};specials=set(tokenizer.all_special_ids)
 for token,weight in zip(inputs['input_ids'][0].tolist(),weights):
  if token not in specials and weight>0:sparse[token]=max(weight,sparse.get(token,0))
 return dense,sparse
@lru_cache(maxsize=1)
def dense_index():
 import faiss
 m=manifest();faiss.omp_set_num_threads(int(os.getenv('PLFSS_SEARCH_THREADS','2')))
 idx=faiss.read_index(str(ROOT/'dense.faiss'),faiss.IO_FLAG_MMAP|faiss.IO_FLAG_READ_ONLY)
 if idx.d!=DIMENSION or idx.ntotal!=m['passages']:raise ValueError('Dense index mismatch')
 idx.nprobe=min(64,idx.nlist);return idx
def parameters(query):
 one=lambda k,d='':str(query.get(k,[d])[0])
 q=one('q').strip();year=one('year');fmt=one('format');family=one('family');mode=one('mode','hybrid');limit=int(one('limit','20'))
 if len(q)>200 or (year and (not year.isdigit() or not 2017<=int(year)<=2027)):raise ValueError('Invalid query or year')
 if fmt not in ('','pdf','html','csv','xlsx','txt') or mode not in ('hybrid','text') or len(family)>100 or not 1<=limit<=50:raise ValueError('Invalid search filters')
 return q,year,fmt,family,mode,limit
def citations(db,seq,args=('','','','','','')):
 rows=db.execute('SELECT d.*,c.locator FROM citations c JOIN documents d ON d.id=c.document_id WHERE c.seq=? AND '+FILTER+' ORDER BY d.title,c.locator LIMIT 8',[seq,*args])
 out=[]
 for r in rows:
  c=dict(r);c.pop('id');c.pop('reference_id');c['local_available']=bool(c['local_available']);c['years']=[int(x) for x in c.pop('years_key').strip('|').split('|') if x]
  m=re.search(r'(?:^|[|/])page:(\d+)(?:/|[|]|$)',c['locator']);c['page']=int(m[1]) if m else None;out.append(c)
 return out
def lexical(q):
 stop={'le','la','les','de','du','des','un','une','et','en','au','aux','pour','dans','sur','a','à','est','quel','quelle'}
 return ' AND '.join('"'+s+'"' for s in re.findall(r'[^\W_]+',q,flags=re.UNICODE)[:24] if s.casefold() not in stop)
def search(query):
 q,year,fmt,family,mode,limit=parameters(query);info=status();result=dict(info,query=q,items=[],count=0,mode=mode,exhaustive=False,filter_scope='document_year',missing_result_is_absence_proof=False)
 if not info['available'] or not q:return result
 started=time.monotonic();args=(year,year,fmt,fmt,family,family);scores=defaultdict(float);methods=defaultdict(set)
 with closing(read_db(ROOT/'search.sqlite')) as db:
  deadline=started+120;db.set_progress_handler(lambda:1 if time.monotonic()>deadline else 0,10000)
  match=lexical(q)
  if match:
   rows=db.execute('SELECT f.rowid FROM passages_fts f WHERE passages_fts MATCH ? AND EXISTS(SELECT 1 FROM citations c JOIN documents d ON d.id=c.document_id WHERE c.seq=f.rowid AND '+FILTER+') ORDER BY rank LIMIT 240',[match,*args])
   for rank,r in enumerate(rows):scores[r[0]]+=1/(60+rank);methods[r[0]].add('text')
  db.set_progress_handler(None,0);sparse={}
  if mode=='hybrid':
   vector,sparse=encode(q+(' · exercice '+year if year else ''));distances,ids=dense_index().search(vector,4000 if any((year,fmt,family)) else 400)
   candidates=[int(n) for n in ids[0] if n>=1];accepted=[]
   for offset in range(0,len(candidates),400):
    batch=candidates[offset:offset+400]
    allowed={r[0] for r in db.execute('SELECT DISTINCT c.seq FROM citations c JOIN documents d ON d.id=c.document_id WHERE c.seq IN ('+','.join('?' for _ in batch)+') AND '+FILTER,[*batch,*args])}
    accepted.extend(n for n in batch if n in allowed)
    if len(accepted)>=240:break
   for rank,n in enumerate(accepted[:240]):scores[n]+=1/(60+rank);methods[n].add('dense')
  if sparse:
   import numpy as np
   weighted=[]
   for n in scores:
    r=db.execute('SELECT sparse_ids,sparse_weights FROM passages WHERE seq=?',(n,)).fetchone()
    weight=sum(sparse.get(int(i),0)*float(w) for i,w in zip(np.frombuffer(r[0],dtype='<i4'),np.frombuffer(r[1],dtype='<f4')))
    if weight>0:weighted.append((weight,n))
   for rank,(_,n) in enumerate(sorted(weighted,reverse=True)):scores[n]+=.5/(60+rank);methods[n].add('sparse_rerank')
  pages=set()
  for n in sorted(scores,key=lambda n:(-scores[n],n)):
   cites=citations(db,n,args)
   if not cites:continue
   key=(cites[0]['source_sha256'],cites[0]['page'] or cites[0]['locator'])
   if key in pages:continue
   pages.add(key);r=db.execute('SELECT id,text,tokens,text_sha256 FROM passages WHERE seq=?',(n,)).fetchone()
   result['items'].append(dict(id=r['id'],excerpt=r['text'][:1900],tokens=r['tokens'],text_sha256=r['text_sha256'],citations=cites,retrieval_methods=sorted(methods[n]),numeric_status='not_validated_budget_fact'))
   if len(result['items'])>=limit:break
 result.update(count=len(result['items']),elapsed_seconds=round(time.monotonic()-started,3));return result
def passage(ident):
 if not re.fullmatch('[0-9a-f]{64}',ident):raise ValueError('Invalid passage ID')
 with closing(read_db(ROOT/'search.sqlite')) as db:
  r=db.execute('SELECT * FROM passages WHERE id=?',(ident,)).fetchone()
  if not r:raise LookupError('Passage absent')
  return dict(id=r['id'],text=r['text'],tokens=r['tokens'],text_sha256=r['text_sha256'],citations=citations(db,r['seq']),numeric_status='not_validated_budget_fact')
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,obj,status=200):
  body=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):
  if len(self.path)>4096:return self.reply(dict(error='Requête trop longue.'),414)
  url=urlsplit(self.path)
  if url.path=='/healthz':return self.reply(status())
  if not GATE.acquire(blocking=False):return self.reply(dict(error='Recherche déjà en cours. Réessayez dans quelques instants.'),503)
  try:
   if url.path=='/search':return self.reply(search(parse_qs(url.query,keep_blank_values=True,max_num_fields=8)))
   if url.path.startswith('/passage/'):return self.reply(passage(url.path.rsplit('/',1)[-1]))
   self.reply(dict(error='Page introuvable.'),404)
  except (ValueError,TypeError):self.reply(dict(error='Paramètres de recherche invalides.'),400)
  except LookupError:self.reply(dict(error='Passage introuvable.'),404)
  except Exception:
   logging.exception('PLFSS retrieval failed');self.reply(dict(error='Recherche momentanément indisponible.'),503)
  finally:GATE.release()
def main():
 logging.basicConfig(level=logging.INFO)
 # Load the pinned model once locally; no outside model download or paid API.
 if os.getenv('PLFSS_PRELOAD','1')=='1':encode('Sécurité sociale');dense_index()
 ThreadingHTTPServer(('0.0.0.0',8090),Handler).serve_forever()
if __name__=='__main__':main()

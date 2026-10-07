"""Private Docker service for public corpus retrieval. No financial inference."""
from collections import defaultdict
from contextlib import closing, ExitStack
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit, quote, unquote
from .retrieval_contract import VERSION, MODEL, REVISION, DIMENSION, read_db, query_terms, lexical_query, mentions_mpr

ROOT = Path(os.environ.get('BUDGET_RETRIEVAL_ROOT','/search'))
SUPPLEMENT = Path(os.environ['BUDGET_RETRIEVAL_SUPPLEMENT_ROOT']) if os.environ.get('BUDGET_RETRIEVAL_SUPPLEMENT_ROOT') else None
SUPPLEMENT2 = Path(os.environ['BUDGET_RETRIEVAL_SUPPLEMENT2_ROOT']) if os.environ.get('BUDGET_RETRIEVAL_SUPPLEMENT2_ROOT') else None


def supplement_roots():
    return [root for root in (SUPPLEMENT, SUPPLEMENT2) if root is not None]
MODEL_PATH = Path(os.environ.get('BUDGET_MODEL_PATH','/opt/lexmachine-models/models--BAAI--bge-m3/snapshots/'+REVISION))
GATE = threading.BoundedSemaphore(1)


@lru_cache(maxsize=3)
def manifest(root=None):
    root = Path(root) if root is not None else ROOT
    data=json.loads((root/'manifest.json').read_text())
    if (data.get('version'),data.get('state'),data.get('model'),data.get('revision'),data.get('dimension'))!=(VERSION,'ready',MODEL,REVISION,DIMENSION):
        raise ValueError('Incompatible retrieval manifest')
    for item in data['files']:
        path=root/item['path']
        if not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size!=item['bytes']:
            raise ValueError('Invalid index file')
    if root != ROOT:
        from .retrieval_contract import digest
        base_identity=manifest().get('input_sha256')
        if not isinstance(base_identity,str) or not re.fullmatch('[0-9a-f]{64}',base_identity) or data.get('base_input_sha256') != base_identity:
            raise ValueError('Supplement belongs to another base generation')
        if any(digest(root/item['path']) != item['sha256'] for item in data['files']):
            raise ValueError('Supplement checksum mismatch')
    return data


def status():
    try:
        m=manifest(); supplements=[manifest(root) for root in supplement_roots()]
        return dict(available=True,state='ready',documents=m['documents']+sum(x['documents'] for x in supplements),
                    passages=m['passages']+sum(x['passages'] for x in supplements),version=m['version'],
                    supplement_documents=sum(x['documents'] for x in supplements),
                    supplement_passages=sum(x['passages'] for x in supplements),
                    supplement_generated_at=max((x['generated_at'] for x in supplements),default=None),
                    generated_at=m['generated_at'],model=MODEL,revision=REVISION,
                    method='Texte intégral + recherche dense BGE-M3 + reclassement sparse des candidats',
                    numeric_facts_certified=False,message='Recherche documentaire disponible, avec références aux sources.')
    except (OSError,ValueError,KeyError):
        return dict(available=False,state='preparing',message='L’index documentaire est en cours de préparation.')


@lru_cache(maxsize=1)
def encoder():
    import torch
    from transformers import AutoModel,AutoTokenizer
    if MODEL_PATH.name!=REVISION:raise ValueError('Expected the pinned BGE-M3 snapshot')
    torch.set_num_threads(int(os.environ.get('BUDGET_ENCODER_THREADS','2')))
    tokenizer=AutoTokenizer.from_pretrained(str(MODEL_PATH),local_files_only=True)
    dtype=getattr(torch,os.environ.get('BUDGET_MODEL_DTYPE','float16'))
    if dtype not in (torch.float32,torch.float16):raise ValueError('Unsupported encoder dtype')
    model=AutoModel.from_pretrained(str(MODEL_PATH),local_files_only=True,dtype=dtype).eval()
    linear=torch.nn.Linear(DIMENSION,1,dtype=dtype)
    linear.load_state_dict(torch.load(MODEL_PATH/'sparse_linear.pt',map_location='cpu',weights_only=True))
    return torch,tokenizer,model,linear.eval()


@lru_cache(maxsize=128)
def encode(text):
    torch,tokenizer,model,linear=encoder()
    inputs=tokenizer(text,return_tensors='pt',truncation=False)
    if inputs['input_ids'].shape[1]>512:raise ValueError('Query token limit exceeded')
    with torch.inference_mode():
        hidden=model(**inputs).last_hidden_state
        dense=torch.nn.functional.normalize(hidden[:,0].float(),p=2,dim=1).numpy()
        weights=torch.relu(linear(hidden)).squeeze(-1)[0].tolist()
    sparse={};specials=set(tokenizer.all_special_ids)
    for token,weight in zip(inputs['input_ids'][0].tolist(),weights):
        if token not in specials and weight>0:sparse[token]=max(weight,sparse.get(token,0))
    return dense,sparse


@lru_cache(maxsize=3)
def dense_index(root=None):
    import faiss
    m=manifest() if root is None else manifest(root)
    faiss.omp_set_num_threads(int(os.environ.get('BUDGET_SEARCH_THREADS','2')))
    index=faiss.read_index(str((Path(root) if root is not None else ROOT)/'dense.faiss'),faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
    if index.d!=DIMENSION or index.ntotal!=m['passages']:raise ValueError('Vector index mismatch')
    if hasattr(index,'nlist'):index.nprobe=min(64,index.nlist)
    return index


def citations(db,seq,year='',fmt=''):
    rows=db.execute('''SELECT d.*,c.locator FROM citations c JOIN documents d ON d.id=c.document_id
        WHERE c.seq=? AND (?='' OR d.format=?) AND (?='' OR instr(d.years_key,'|' || ? || '|')>0)
        ORDER BY d.local_available DESC,d.title,c.locator LIMIT 8''',(seq,fmt,fmt,year,year)).fetchall()
    result=[]
    for r in rows:
        x=dict(r);x.pop('reference_id');x.pop('id');x['local_available']=bool(x['local_available'])
        x['years']=[int(y) for y in x.pop('years_key').strip('|').split('|') if y]
        match=re.match(r'page:(\d+)(?:/|$)',x['locator'])
        x['page']=int(match[1]) if match else None
        html=re.fullmatch(r'html:(?:#([A-Za-z0-9_.:-]+)|(body))/section:([^/]*)/chars:(\d+)-(\d+)/part:(\d+)',x['locator'])
        if x['format']=='html' and html:
            x['source_locator']=x['locator']
            x['locator']=unquote(html[3])+' · extrait '+html[6]
            x['html_anchor']=html[1]
            if html[1]:x['url']=x['url'].split('#',1)[0]+'#'+quote(html[1],safe='_.:-')
        result.append(x)
    return result


def parameters(query):
    one=lambda k,d='':str(query.get(k,[d])[0])
    q=one('q').strip();year=one('year');fmt=one('format');mode=one('mode','hybrid')
    if len(q)>200 or (year and (not year.isdigit() or not 1900<=int(year)<=2100)):raise ValueError('Invalid query or year')
    if fmt not in {'','pdf','html','csv','xls','xlsx','ods','md','xml'} or mode not in {'hybrid','text'}:raise ValueError('Invalid format or mode')
    limit=int(one('limit','20'))
    if not 1<=limit<=50:raise ValueError('Invalid limit')
    return q,year,fmt,mode,limit


def search(query):
    q,year,fmt,mode,limit=parameters(query);info=status()
    result=dict(info,query=q,count=0,items=[],mode=mode)
    if not info['available'] or not q:return result
    started=time.monotonic()
    roots=[None]+supplement_roots()
    with ExitStack() as stack:
        databases=[stack.enter_context(closing(read_db((root or ROOT)/'search.sqlite'))) for root in roots]
        deadline=time.monotonic()+20
        match=lexical_query(q,hybrid=mode=='hybrid')
        scores=defaultdict(float);methods=defaultdict(set)
        # Fuse FTS ranks per collection; BM25 magnitudes depend on corpus size.
        # Dense similarities and sparse weights are comparable across both indexes.
        for collection,db in enumerate(databases):
            db.set_progress_handler(lambda:1 if time.monotonic()>deadline else 0,10000)
            if match:
                lexical=[r[0] for r in db.execute("""SELECT f.rowid FROM passages_fts f
                    WHERE passages_fts MATCH ? AND EXISTS(SELECT 1 FROM citations c JOIN documents d ON d.id=c.document_id
                     WHERE c.seq=f.rowid AND (?='' OR d.format=?) AND (?='' OR instr(d.years_key,'|' || ? || '|')>0))
                    ORDER BY rank LIMIT 240""",(match,fmt,fmt,year,year))]
                for rank,seq in enumerate(lexical):
                    key=(collection,seq);scores[key]+=1/(60+rank);methods[key].add('text')
            db.set_progress_handler(None,0)
        sparse={}
        if mode=='hybrid':
            vector,sparse=encode(q + (' · exercice ' + year if year else ''))
            candidate_limit=4000 if year or fmt else 400
            candidates=[]
            for collection,root in enumerate(roots):
                index=dense_index() if root is None else dense_index(root)
                distances,seqs=index.search(vector,candidate_limit)
                candidates.extend((float(distance),collection,int(seq)) for distance,seq in zip(distances[0],seqs[0]) if seq>=1)
            # Apply citation filters before limiting the accepted global ranks.
            # Irrelevant supplement years/formats must not displace base candidates.
            candidates=sorted(candidates,key=lambda entry:(-entry[0],entry[1],entry[2]))
            accepted=[];require_mpr=mentions_mpr(q)
            for offset in range(0,len(candidates),400):
                batch=candidates[offset:offset+400];keep=set()
                for collection,db in enumerate(databases):
                    ids=[seq for _,which,seq in batch if which==collection]
                    if not ids:continue
                    keep.update((collection,row[0]) for row in db.execute("""SELECT DISTINCT c.seq FROM citations c JOIN documents d ON d.id=c.document_id
                        WHERE c.seq IN ("""+','.join('?' for _ in ids)+""") AND (?='' OR d.format=?)
                        AND (?='' OR instr(d.years_key,'|' || ? || '|')>0)""",ids+[fmt,fmt,year,year]))
                selected=[(which,seq) for _,which,seq in batch if (which,seq) in keep]
                # Apply the named-scheme anchor before counting accepted ranks too.
                # Unrelated supplement candidates must not exhaust the dense quota.
                if require_mpr:
                    selected=[key for key in selected if mentions_mpr(databases[key[0]].execute('SELECT text FROM passages WHERE seq=?',(key[1],)).fetchone()[0])]
                accepted.extend(selected)
                if len(accepted)>=240:break
            for rank,key in enumerate(accepted[:240]):scores[key]+=1/(60+rank);methods[key].add('dense')
        if sparse and scores:
            import numpy as np
            weighted=[]
            for key in scores:
                row=databases[key[0]].execute('SELECT sparse_ids,sparse_weights FROM passages WHERE seq=?',(key[1],)).fetchone()
                score=sum(sparse.get(int(i),0)*float(w) for i,w in zip(np.frombuffer(row[0],dtype='<i4'),np.frombuffer(row[1],dtype='<f4')))
                if score>0:weighted.append((score,key))
            for rank,(_,key) in enumerate(sorted(weighted,reverse=True)):
                scores[key]+=.5/(60+rank);methods[key].add('sparse_rerank')
        pages=set();items=[]
        for candidate in sorted(scores,key=lambda s:(-scores[s],s)):
            collection,seq=candidate;db=databases[collection]
            cites=citations(db,seq,year,fmt)
            if not cites:continue
            key=(cites[0]['source_sha256'],cites[0]['page'] or cites[0]['locator'])
            if key in pages:continue
            pages.add(key)
            row=db.execute('SELECT id,text,tokens,text_sha256 FROM passages WHERE seq=?',(seq,)).fetchone()
            items.append(dict(id=row['id'],excerpt=row['text'][:1900],tokens=row['tokens'],text_sha256=row['text_sha256'],
                              citations=cites,retrieval_methods=sorted(methods[candidate]),score=scores[candidate],numeric_status='not_validated_budget_fact'))
            if len(items)>=limit:break
    result.update(items=items,count=len(items),elapsed_seconds=round(time.monotonic()-started,3),
                  exhaustive=False,filter_scope='document_year',missing_result_is_absence_proof=False)
    return result


def passage(ident):
    if not re.fullmatch('[0-9a-f]{64}',ident):raise ValueError('Invalid passage ID')
    for root in [ROOT]+supplement_roots():
        if root != ROOT:manifest(root)
        with closing(read_db(root/'search.sqlite')) as db:
            row=db.execute('SELECT seq,id,text,tokens,text_sha256 FROM passages WHERE id=?',(ident,)).fetchone()
            if row:
                return dict(id=row['id'],text=row['text'],tokens=row['tokens'],text_sha256=row['text_sha256'],
                            citations=citations(db,row['seq']),numeric_status='not_validated_budget_fact')
    raise LookupError('Passage absent')


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,obj,status=200):
        body=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if len(self.path)>4096:return self.reply({'error':'Request too long'},414)
        url=urlsplit(self.path)
        if url.path=='/healthz':return self.reply(status())
        if not GATE.acquire(blocking=False):return self.reply({'error':'Recherche en cours. Réessayez dans quelques instants.'},503)
        try:
            if url.path=='/search':return self.reply(search(parse_qs(url.query,keep_blank_values=True,max_num_fields=8)))
            if url.path.startswith('/passage/'):return self.reply(passage(url.path.rsplit('/',1)[-1]))
            self.reply({'error':'Not found'},404)
        except (ValueError,TypeError):self.reply({'error':'Paramètres de recherche invalides.'},400)
        except LookupError as exc:
            if type(exc) is LookupError:self.reply({'error':'Passage introuvable.'},404)
            else:
                logging.exception('Retrieval lookup failure')
                self.reply({'error':'Recherche momentanément indisponible.'},503)
        except (OSError,sqlite3.Error):self.reply({'error':'Recherche momentanément indisponible.'},503)
        finally:GATE.release()


if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',8090),Handler).serve_forever()

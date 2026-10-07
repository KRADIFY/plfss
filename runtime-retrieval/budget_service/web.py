"""Nos Deniers HTTP application. Serves public budget data, never connector secrets."""
import json
import gzip
import os
import shutil
from contextlib import closing
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote
from . import api, document_search, exports, events, reserves, rap_movements, retrieval_client

ROOT=Path(os.environ.get('BUDGET_PUBLIC_DIR','/app/public'))
STATE=Path(os.environ.get('BUDGET_STATE_DIR','/state'))
ASSETS={'/':('explorer.html','text/html; charset=utf-8'), '/diagnostic':('diagnostic.html','text/html; charset=utf-8')}
for name in ('explorer.js','diagnostic.js'): ASSETS['/assets/'+name]=('assets/'+name,'text/javascript; charset=utf-8')
for name in ('explorer.css','diagnostic.css'): ASSETS['/assets/'+name]=('assets/'+name,'text/css; charset=utf-8')
for name in ('nos-deniers-horizontal.svg','nos-deniers-icone.svg','nos-deniers-logo.svg','lexmachine-entete.svg'): ASSETS['/assets/'+name]=('assets/'+name,'image/svg+xml')
ASSETS['/assets/InterVariable.woff2']=('assets/InterVariable.woff2','font/woff2')

def download_path(record):
    path=(api.DATA/record['path']).resolve()
    if not path.is_relative_to(api.DATA.resolve()) or not path.is_file(): raise LookupError('Fichier indisponible')
    return path

def accepts_gzip(header):
    codings={}
    for part in header.lower().split(','):
        token,*options=part.strip().split(';');quality=1.0
        for option in options:
            name,separator,value=option.strip().partition('=')
            if name=='q':
                try:quality=float(value)
                except ValueError:quality=0.0
        codings[token]=quality if 0<=quality<=1 else 0.0
    return codings.get('gzip',codings.get('*',0))>0

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send_headers(self,status,kind,length,disposition=None,encoding=None,vary=False):
        self.send_response(status)
        for k,v in {'Content-Type':kind,'Content-Length':str(length),'Cache-Control':'no-store',
                    'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
                    'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items(): self.send_header(k,v)
        if disposition: self.send_header('Content-Disposition',disposition)
        if vary:self.send_header('Vary','Accept-Encoding')
        if encoding:self.send_header('Content-Encoding',encoding)
        self.end_headers()

    def reply(self,obj,status=200,kind='application/json; charset=utf-8',disposition=None):
        body=obj if isinstance(obj,bytes) else json.dumps(obj,ensure_ascii=False,allow_nan=False).encode('utf-8')
        compressible=kind.startswith(('application/json','text/'));encoding=None
        if compressible and len(body)>=1024 and accepts_gzip(self.headers.get('Accept-Encoding','')):
            packed=gzip.compress(body,compresslevel=3,mtime=0)
            if len(packed)<len(body):body=packed;encoding='gzip'
        self.send_headers(status,kind,len(body),disposition,encoding=encoding,vary=compressible)
        if self.command!='HEAD': self.wfile.write(body)

    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        if len(self.path)>8192: return self.reply({'error':'Requête trop longue'},414)
        request=urlsplit(self.path); path=request.path
        try:
            query=parse_qs(request.query,max_num_fields=30,keep_blank_values=True)
            if path=='/healthz': return self.reply({'service':'nos-deniers','status':'ok','version':'0.3'})
            if path=='/api/status':
                try: body=(STATE/'connections.json').read_bytes()
                except FileNotFoundError: body=b'{"sources":[],"phase":"pending"}'
                return self.reply(body)
            if path=='/readyz':
                ready=(api.DATA/'derived/budget.sqlite').is_file()
                return self.reply({'ready':ready,'meaning':'Tables normalisées disponibles ; couverture détaillée dans /api/bootstrap'},200 if ready else 503)
            if path in ASSETS:
                file,kind=ASSETS[path]; return self.reply((ROOT/file).read_bytes(),kind=kind)
            if not path.startswith('/api/'): return self.reply({'error':'Page introuvable'},404)
            with closing(api.connect()) as db:
                if path=='/api/bootstrap': return self.reply(api.bootstrap(db))
                if path=='/api/reserves':
                    result=reserves.query(api.parameters(query),api.metadata(db))
                    return self.reply(result,disposition='attachment; filename=nos-deniers-reserves.json' if query.get('download') else None)
                if path=='/api/rap-movements':
                    summary=query.get('view')==['summary'] and not query.get('download')
                    offset=int(query.get('offset',['0'])[0]);limit=int(query.get('limit',['500'])[0])
                    if summary and (offset<0 or not 1<=limit<=500):raise ValueError('Invalid movement page')
                    result=rap_movements.query(db,api.parameters(query),api.metadata(db),include_evidence=not summary)
                    if summary:result=rap_movements.page_result(result,offset,limit)
                    return self.reply(result,disposition='attachment; filename=nos-deniers-mouvements-rap.json' if query.get('download') else None)
                if path=='/api/events':
                    result=events.query(api.DATA,api.parameters(query),api.metadata(db))
                    return self.reply(result,disposition='attachment; filename=nos-deniers-evenements.json' if query.get('download') else None)
                if path in ('/api/document-search/status','/api/semantic-search/status'):
                    return self.reply(retrieval_client.status() if retrieval_client.configured() or path=='/api/semantic-search/status' else document_search.status())
                if path=='/api/document-search':
                    result=retrieval_client.search(dict(query,mode=['text'])) if retrieval_client.configured() else document_search.search(query)
                    return self.reply(retrieval_client.resolve_sources(result,db))
                if path=='/api/semantic-search':
                    return self.reply(retrieval_client.resolve_sources(retrieval_client.search(dict(query,mode=['hybrid'])),db))
                if path.startswith('/api/document-passage/'):
                    return self.reply(retrieval_client.resolve_sources(retrieval_client.passage(path.rsplit('/',1)[-1]),db))
                if path=='/api/documents': return self.reply(api.documents(db,query))
                if path.startswith('/api/source/'): return self.reply(api.source(db,path.rsplit('/',1)[-1]))
                if path.startswith('/api/download/'):
                    r=api.source(db,path.rsplit('/',1)[-1]); file=download_path(r)
                    kind='application/pdf' if r.get('format')=='pdf' else 'application/octet-stream'
                    filename=Path(r['path']).name
                    self.send_headers(200,kind,file.stat().st_size,('inline' if kind=='application/pdf' else 'attachment')+"; filename*=UTF-8''"+quote(filename,safe=''))
                    if self.command!='HEAD':
                        with file.open('rb') as stream: shutil.copyfileobj(stream,self.wfile)
                    return
                if path in ('/api/explorer','/api/export','/api/export.xlsx','/api/selection','/api/provenance'):
                    p=api.parameters(query)
                    if path=='/api/provenance': return self.reply(api.provenance(db,p,int(query.get('year',['0'])[0]),query.get('stage',[''])[0],query.get('cell_scope',[p['scope']])[0]))
                    data=api.explorer(db,p)
                    if path in ('/api/export.xlsx','/api/selection'):
                        ids=sorted({sid for series in [data['totals']]+[row['series'] for row in data['rows']] for annual in series for stage in api.STAGES for sid in annual[stage].get('sources',[])})
                        sources=[api.source(db,sid) for sid in ids]
                        if path=='/api/export.xlsx': return self.reply(exports.xlsx(data,sources),kind='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',disposition='attachment; filename="nos-deniers.xlsx"')
                        return self.reply(dict(data,sources=sources),disposition='attachment; filename="nos-deniers-selection.json"')
                    if path=='/api/export': return self.reply(api.export_csv(data,db),kind='text/csv; charset=utf-8',disposition='attachment; filename="nos-deniers.csv"')
                    return self.reply(data)
            self.reply({'error':'Route introuvable'},404)
        except (ValueError,TypeError): self.reply({'error':'Paramètres invalides. Vérifiez les années et le périmètre.'},400)
        except LookupError: self.reply({'error':'Source ou fichier introuvable.'},404)
        except (sqlite3.Error,FileNotFoundError): self.reply({'error':'La base de données est momentanément indisponible.'},503)
        except (BrokenPipeError,ConnectionResetError): pass

if __name__=='__main__': ThreadingHTTPServer(('0.0.0.0',8080),Handler).serve_forever()

"""Read-only preparation dashboard. No credentials or corpus content are served."""
import json, os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT=Path('/app/public')
STATE=Path(os.environ.get('BUDGET_STATE_DIR','/state'))
ASSETS={'/':('index.html','text/html; charset=utf-8'),'/assets/app.js':('assets/app.js','text/javascript; charset=utf-8'),'/assets/style.css':('assets/style.css','text/css; charset=utf-8'),'/assets/lexmachine-entete.svg':('assets/lexmachine-entete.svg','image/svg+xml'),'/assets/InterVariable.woff2':('assets/InterVariable.woff2','font/woff2')}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        path=self.path.split('?',1)[0]
        status=200
        if path=='/healthz': body=b'{"service":"budget","status":"ok"}'; kind='application/json'
        elif path=='/api/status':
            try: body=(STATE/'connections.json').read_bytes()
            except FileNotFoundError: body=json.dumps({'version':'0.1','checked_at':None,'sources':[],'phase':'pending'}).encode()
            kind='application/json; charset=utf-8'
        elif path=='/readyz':
            try:
                report=json.loads((STATE/'connections.json').read_text())
                ready=report.get('core_ready',False)
            except (FileNotFoundError,ValueError): ready=False
            status=200 if ready else 503
            body=json.dumps({'ready':ready,'meaning':'core public data connections; not a complete budget database'}).encode(); kind='application/json'
        elif path in ASSETS:
            file,kind=ASSETS[path];body=(ROOT/file).read_bytes()
        else: body=b'Not found';kind='text/plain';status=404
        self.send_response(status)
        self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(body)
if __name__=='__main__': ThreadingHTTPServer(('0.0.0.0',8080),Handler).serve_forever()

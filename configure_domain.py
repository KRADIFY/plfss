"""Only create the PLFSS nginx host. Existing hosts and services stay intact."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path

DOMAIN='plfss.lexmachine.net'
ROOT=Path('/opt/plfss')
SITE=Path('/etc/nginx/sites-available/nos-deniers-plfss')
ENABLED=Path('/etc/nginx/sites-enabled/nos-deniers-plfss')
ACME=Path('/var/www/plfss-acme')
CERT=Path('/etc/letsencrypt/live')/DOMAIN
def run(*args):return subprocess.run(args,check=True)
def pinned(path):
    return subprocess.check_output(['curl','--fail','--silent','--show-error','--max-time','20','--resolve','budget.lexmachine.net:443:127.0.0.1','https://budget.lexmachine.net'+path],text=True)
def other_configs():
    return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/etc/nginx/sites-enabled').iterdir() if p!=ENABLED}
def routed(url,resolve):
    # Reload signals nginx asynchronously; allow old workers to hand over.
    for attempt in range(10):
        p=subprocess.run(['curl','--fail','--silent','--show-error','--max-time','15','--resolve',resolve,url],capture_output=True,text=True)
        if p.returncode==0:return p.stdout
        if attempt<9:time.sleep(1)
    raise RuntimeError('Domain routing did not become ready: '+p.stderr)
HTTP='''server {
    listen 80;
    listen [::]:80;
    server_name plfss.lexmachine.net;
    location ^~ /.well-known/acme-challenge/ { root /var/www/plfss-acme; }
    location / { return 301 https://$host$request_uri; }
}
'''
HTTPS='''server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name plfss.lexmachine.net;
    ssl_certificate /etc/letsencrypt/live/plfss.lexmachine.net/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/plfss.lexmachine.net/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 1m;
    auth_basic off;
    location / {
        proxy_pass http://127.0.0.1:18895;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 5s;
        proxy_read_timeout 140s;
        proxy_send_timeout 30s;
    }
}
'''
mode=sys.argv[1]
assert mode in ('http','https')
ROOT.mkdir(parents=True,exist_ok=True)
record=ROOT/'publication-20261004'
record.mkdir(exist_ok=True)
before=other_configs()
if not (record/'other-nginx-before.json').exists():
    (record/'other-nginx-before.json').write_text(json.dumps(before,indent=2))
    (record/'nos-deniers-ready-before.json').write_text(pinned('/readyz'))
old=SITE.read_bytes() if SITE.exists() else None
if old is not None and not (record/'plfss-nginx-before.conf').exists():
    (record/'plfss-nginx-before.conf').write_bytes(old)
if ENABLED.exists() and ENABLED.resolve()!=SITE:
    raise ValueError('PLFSS enabled path already belongs to another configuration')
ACME.mkdir(parents=True,exist_ok=True)
if mode=='https':
    assert CERT.joinpath('fullchain.pem').is_file() and CERT.joinpath('privkey.pem').is_file()
    live=json.loads(subprocess.check_output(['curl','--fail','--silent','--max-time','10','http://127.0.0.1:18895/api/meta'],text=True))
    assert live['data_version']=='7711a46a263ae522cd77b805ea6862bdd60f839644090006a9811ae433a1a34d'
    assert live['facts']==5412 and live['indexed_passages']==311791
SITE.write_text(HTTP+(HTTPS if mode=='https' else ''))
created=not ENABLED.is_symlink()
if created:ENABLED.symlink_to(SITE)
try:
    run('nginx','-t')
    assert other_configs()==before,'Another nginx host changed'
    run('systemctl','reload','nginx')
except Exception:
    if old is None:SITE.unlink(missing_ok=True)
    else:SITE.write_bytes(old)
    if created:ENABLED.unlink(missing_ok=True)
    raise
if mode=='http':
    challenge=ACME/'.well-known/acme-challenge/plfss-deployment-check'
    challenge.parent.mkdir(parents=True,exist_ok=True)
    challenge.write_text('plfss-domain-routing-ok')
    try:
        got=routed('http://'+DOMAIN+'/.well-known/acme-challenge/plfss-deployment-check',DOMAIN+':80:127.0.0.1')
        assert got=='plfss-domain-routing-ok'
    finally:challenge.unlink(missing_ok=True)
    run('certbot','certonly','--non-interactive','--agree-tos','--webroot','--webroot-path',str(ACME),'--domain',DOMAIN,'--cert-name',DOMAIN,'--email','admin@lexmachine.net','--keep-until-expiring')
    deploy_hook=Path('/etc/letsencrypt/renewal-hooks/deploy/plfss-nginx-reload.sh')
    if not deploy_hook.exists():
        deploy_hook.write_text('#!/bin/sh\nif [ "$RENEWED_LINEAGE" = "/etc/letsencrypt/live/plfss.lexmachine.net" ]; then\n    nginx -t && systemctl reload nginx\nfi\n')
        deploy_hook.chmod(0o755)
else:
    result=json.loads(routed('https://'+DOMAIN+'/api/meta',DOMAIN+':443:127.0.0.1'))
    assert result['facts']==5412 and result['indexed_passages']==311791
assert other_configs()==before
assert json.loads(pinned('/readyz'))['ready']
print(json.dumps(dict(mode=mode,domain=DOMAIN,other_hosts_unchanged=True,nos_deniers_ready=True)))

"""Install the fixed PLFSS release and build on the exact cached runtime."""
import hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
assert ROOT.is_relative_to(Path('/opt/plfss/releases'))
manifest=json.loads((ROOT/'public-manifest.json').read_text(encoding='utf-8'))
def run(*args,**kwargs):return subprocess.run(args,check=True,**kwargs)
def output(*args):return run(*args,capture_output=True,text=True).stdout.strip()
for item in manifest['files']:
    p=(ROOT/item['path']).resolve()
    assert p.is_relative_to(ROOT) and p.is_file(),item['path']
    assert p.stat().st_size==item['bytes'],item['path']
    with p.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    assert actual==item['sha256'],item['path']
print(json.dumps(dict(stage='files_verified',files=len(manifest['files']))),flush=True)
assert output('docker','image','inspect','lexmachine-budget-retrieval:20260924-final','--format','{{.Id}}')==manifest['retrieval_base_id'],'Different embedding runtime'
run('docker','load','--input',str(ROOT/'web-image.tar.gz'))
assert output('docker','image','inspect',manifest['web_image'],'--format','{{.Id}}')==manifest['web_image_id'],'Web image changed'
run('docker','build','--network=none','--pull=false','--file',str(ROOT/'Dockerfile.retrieval'),'--tag',manifest['retrieval_image'],str(ROOT))
compose=['docker','compose','-p','nos-deniers-plfss-public','-f',str(ROOT/'compose.yaml')]
run(*compose,'config','--quiet')
run(*compose,'up','-d','--no-build','--wait','--wait-timeout','240')
for _ in range(6):
    try:
        meta=json.loads(output('curl','--fail','--silent','--max-time','15','http://127.0.0.1:18895/api/meta'))
        search=json.loads(output('curl','--fail','--silent','--max-time','15','http://127.0.0.1:18895/api/search/status'))
        assert meta['data_version']==manifest['data_version'] and meta['facts']==5412 and meta['indexed_passages']==311791
        assert search['available'] and search['passages']==311791
        break
    except (subprocess.CalledProcessError,AssertionError):time.sleep(2)
else:raise ValueError('PLFSS health not ready')
current=Path('/opt/plfss/current')
if current.exists() and not current.is_symlink():raise ValueError('Current path is not a release symlink')
tmp=Path('/opt/plfss/current.new')
assert not tmp.exists() and not tmp.is_symlink()
tmp.symlink_to(ROOT);os.replace(tmp,current)
result=dict(installed=True,published=False,release=str(ROOT),data_version=manifest['data_version'],files_verified=len(manifest['files']),facts=meta['facts'],passages=search['passages'])
(ROOT/'installed.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result),flush=True)

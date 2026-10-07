"""Capture the active PLFSS site and demo for the user's private Git backup."""
from pathlib import Path
import hashlib,io,json,shutil,subprocess,tarfile,urllib.request
stage=Path('/opt/plfss/git-backup-20261007');stage.mkdir(exist_ok=False)
tree=stage/'tree';tree.mkdir()
def output(*args):return subprocess.check_output(args)
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def app(container,names,prefix=''):
 with tarfile.open(fileobj=io.BytesIO(output('docker','exec',container,'tar','-C','/app','-cf','-',*names))) as t:
  for m in t.getmembers():
   p=Path(m.name);assert not p.is_absolute() and '..' not in p.parts
   if not m.isfile() or '__pycache__' in p.parts or p.suffix=='.pyc':continue
   assert p.name!='.env' and p.suffix not in ('.pem','.key')
   d=tree/prefix/p;d.parent.mkdir(parents=True,exist_ok=True);d.write_bytes(t.extractfile(m).read())
def copy(source,destination):
 d=tree/destination;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,d)
names=['nos-deniers-plfss-public-web-1','nos-deniers-plfss-public-retrieval-1','plfss-demo-demo-1']
containers={n:json.loads(output('docker','inspect',n))[0] for n in names}
app(names[0],['plfss_service','public','reports','requirements.txt'])
app(names[1],['budget_service','plfss_service'],'runtime-retrieval')
app(names[2],['public','server.py'],'demo')
release=Path('/opt/plfss/current')
for directory in ['derived','catalogue']:
 for p in (release/'data'/directory).rglob('*'):
  if p.is_file():copy(p,str(p.relative_to(release)))
copy(release/'data/search/manifest.json','data/search/manifest.json')
copy(release/'compose.yaml','compose.yaml')
copy('/etc/nginx/sites-enabled/nos-deniers-plfss','proofs/nginx-plfss.conf')
demo=Path('/opt/plfss-demo/releases/20261006-voix')
for name in ['Dockerfile','compose.yaml']:copy(demo/name,'demo/'+name)
for name in ['entry-buttons.css','plfss-refinements.css']:copy(demo/'public'/name,'presentations/'+name)
copy('/opt/nos-deniers/presentations/audience-20261006/tracker.js','presentations/tracker.js')
meta=json.load(urllib.request.urlopen('https://plfss.lexmachine.net/api/meta',timeout=30))
db=release/'data/derived/plfss.sqlite'
assert digest(db)==digest(tree/'data/derived/plfss.sqlite')
files={p.relative_to(tree).as_posix():{'sha256':digest(p),'bytes':p.stat().st_size} for p in tree.rglob('*') if p.is_file()}
assert max(v['bytes'] for v in files.values())<95000000
receipt={'captured':'2026-10-07','published_url':'https://plfss.lexmachine.net/','database_sha256':digest(db),'meta':meta,
 'containers':{n:{'image':i['Config']['Image'],'image_id':i['Image'],'mounts':i['Mounts']} for n,i in containers.items()},
 'large_documents_and_vector_indexes':'Preserved in existing en-ligne-20261004 GitHub release and dedicated backups',
 'production_modified':False,'files':files}
(tree/'proofs/VERSION-EN-LIGNE-20261007.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False))
for n,i in containers.items():assert json.loads(output('docker','inspect',n))[0]['Id']==i['Id']
archive=stage/'snapshot.tar.gz'
with tarfile.open(archive,'w:gz') as t:
 for p in tree.rglob('*'):
  if p.is_file():t.add(p,arcname=p.relative_to(tree).as_posix())
print(json.dumps({'archive':str(archive),'sha256':digest(archive),'bytes':archive.stat().st_size,'files':len(files),'database_sha256':receipt['database_sha256'],'production_modified':False}))

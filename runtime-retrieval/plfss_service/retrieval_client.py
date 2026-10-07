"""Bridge to PLFSS's own fixed Docker retrieval endpoint."""
import json,os,re
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError,URLError
def unavailable(message):return dict(available=False,items=[],count=0,message=message)
def request(path):
 endpoint=os.getenv('PLFSS_RETRIEVAL_URL','').rstrip('/')
 if not endpoint:return unavailable('La recherche dans le contenu n’est pas raccordée.')
 try:
  with urlopen(endpoint+path,timeout=120) as response:result=json.load(response)
  if not isinstance(result,dict):raise ValueError('Invalid search response')
  return result
 except HTTPError as e:return unavailable('Recherche en cours ou momentanément indisponible. Réessayez.' if e.code==503 else 'Le passage ou la recherche demandé est indisponible.')
 except (URLError,TimeoutError,OSError,ValueError):return unavailable('Le moteur documentaire PLFSS est momentanément indisponible. Réessayez.')
def search(params):
 from .retrieval_service import parameters
 q,year,fmt,family,mode,limit=parameters(params)
 return request('/search?'+urlencode(dict(q=q,year=year,format=fmt,family=family,mode=mode,limit=limit)))
def passage(ident):
 if not re.fullmatch('[0-9a-f]{64}',ident):raise ValueError('Identifiant de passage invalide')
 return request('/passage/'+ident)
def resolve_sources(result,store):
 for item in result.get('items',[])+([result] if 'citations' in result else []):
  for c in item.get('citations',[]):
   s=store.source(c.get('source_id',''));valid=bool(s and s.get('status')=='downloaded' and s.get('sha256')==c.get('source_sha256'))
   if valid:
    target=(store.data/s['path']).resolve();valid=target.is_relative_to(store.data.resolve()) and target.is_file()
   c['local_available']=valid
   if not valid:c['source_id']=''
 return result

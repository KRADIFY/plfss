"""Run with the existing authorized client; export public sources only, never credentials."""
import importlib.util,json,os,sys
os.environ['DANAIDES_TRICOTEUSES_CONFIG_FILE']='/home/marie/.config/nos-aides/tricoteuses/oauth.json'
spec=importlib.util.spec_from_file_location('plfss_existing_client','/opt/lexmachine-danaides/releases/20260912-connections/danaides_service/tricoteuses.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
client=module._Client()
def query(schema,sql,params):
 r=client.rpc('tools/call',dict(name='query_sql',arguments=dict(schema=schema,query=sql,params=params)))
 if r.get('isError'):raise RuntimeError('Official source query failed')
 data=json.loads(''.join(c.get('text','') for c in r.get('content',[]) if c.get('type')=='text'))
 if not isinstance(data,list):raise ValueError('Source is not a list')
 return data
numbers=['2016-1827','2017-1836','2018-1203','2019-1446','2020-1576','2021-1754','2022-1616','2023-1250','2025-199','2025-1403']
laws=query('legifrance',"SELECT id,data->'META'->'META_SPEC'->'META_TEXTE_VERSION'->>'TITREFULL' AS title FROM legifrance.texte_version WHERE id LIKE 'JORFTEXT%' AND nature='LOI' AND data->'META'->'META_SPEC'->'META_TEXTE_CHRONICLE'->>'NUM' = ANY($1::text[]) ORDER BY id",[numbers])
laws=[r for r in laws if 'rectificatif' not in r['title'].lower()]
if len(laws)!=10:raise RuntimeError('Ten LFSS identities expected; no inference permitted')
articles=[]
for law in laws:
 cursor=''
 while True:
  rows=query('legifrance',"SELECT id,num,data->'CONTEXTE'->'TEXTE'->>'@cid' AS text_id,data->'CONTEXTE'->'TEXTE'->>'@date_publi' AS publication_date,data->'BLOC_TEXTUEL'->>'CONTENU' AS html FROM legifrance.article WHERE data->'CONTEXTE'->'TEXTE'->>'@cid'=$1 AND id LIKE 'JORFARTI%' AND id>$2 ORDER BY id LIMIT 25",[law['id'],cursor])
  articles.extend([dict(r,title=law['title']) for r in rows])
  if len(rows)<25:break
  cursor=rows[-1]['id']
 print('law collected '+law['id']+' articles='+str(sum(r['text_id']==law['id'] for r in articles)),file=sys.stderr,flush=True)
print(json.dumps(dict(source='Moulineuse - Legifrance JORF, original promulgated articles',laws=laws,articles=articles),ensure_ascii=True))

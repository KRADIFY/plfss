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
dossiers=['DLR5L15N36030','DLR5L15N36892','DLR5L15N37831','DLR5L15N40633','DLR5L15N43709','DLR5L16N46347','DLR5L16N48683','DLR5L17N50588','DLR5L17N52922','DLR5L17N54951']
rows=query('assemblee',"SELECT d.uid,d.data->>'dossierRef' AS dossier,d.data->'titres'->>'titrePrincipal' AS title,d.data->'cycleDeVie'->'chrono'->>'dateDepot' AS deposit_date FROM assemblee.documents d WHERE d.data->>'dossierRef'=ANY($1::text[]) AND d.data->'classification'->'type'->>'code'='PRJL' ORDER BY d.data->'cycleDeVie'->'chrono'->>'dateDepot',d.uid",[dossiers])
print(json.dumps(rows,ensure_ascii=True))

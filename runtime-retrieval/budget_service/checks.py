"""Bounded read-only connection checks, explicitly run by the operator inside Docker."""
import ast,base64,concurrent.futures,csv,hashlib,io,json,os,socket,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen,build_opener,HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError
from xml.etree import ElementTree
STATE=Path(os.environ.get('BUDGET_STATE_DIR','/state'))
MAX_BYTES=8*1024*1024
class CheckError(Exception): pass
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def fetch(url,*,data=None,headers=None,private=False):
    h={'User-Agent':'LexMachine-Budget/0.1 contact admin@lexmachine.net',**(headers or {})}
    request=Request(url,data=data,headers=h)
    opener=build_opener(NoRedirect()) if private else build_opener()
    with opener.open(request,timeout=25) as res:
        raw=res.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES: raise CheckError('Réponse trop volumineuse pour cette sonde bornée')
        return raw,dict(res.headers),res.status

def as_json(raw):
    try: return json.loads(raw)
    except (ValueError,UnicodeDecodeError): raise CheckError('Réponse reçue mais JSON attendu absent') from None

def evidence(key,raw):
    folder=STATE/'evidence';folder.mkdir(exist_ok=True)
    path=folder/(key+'.bin');path.write_bytes(raw);path.chmod(0o600)
    return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}

def ods(ds,key):
    url='https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/'+ds+'/records?limit=1'
    raw,_,_=fetch(url);j=as_json(raw)
    if not j.get('results'):raise CheckError('Jeu joignable mais aucune ligne reçue')
    return {'status':'ok','detail':'Une ligne structurée lue ; historique complet à importer.','url':url,'records':j.get('total_count'),'fields':list(j['results'][0]),'evidence':evidence(key,raw)}

def attachments():
    ds='projet-de-loi-relatif-aux-resultats-de-la-gestion-et-portant-approbation-des-comptes-de-lannee-plrg-2025'
    base='https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/'+ds
    meta=as_json(fetch(base)[0]);items=meta.get('attachments',[])
    item=next(x for x in items if 'annexe1_etat_ae_cp' in x['id'])
    raw,_,_=fetch(item['url']);txt=raw.decode('utf-8-sig')
    if '<html' in txt[:500].lower() or '<!doctype' in txt[:500].lower():raise CheckError('Page HTML reçue à la place du CSV')
    rows=list(csv.reader(io.StringIO(txt),delimiter=';'))
    if len(rows)<2 or len(rows[0])<2:raise CheckError('CSV sans tableau exploitable')
    return {'status':'ok','detail':'Annexe AE/CP 2025 téléchargée et lue.','url':item['url'],'rows':len(rows)-1,'evidence':evidence('plrg2025',raw)}

def document(url='https://www.budget.gouv.fr/documentation/file-download/32842',key='rap205',label='RAP 2025 du programme 205'):
    raw,_,_=fetch(url)
    if not raw.startswith(b'%PDF-'):raise CheckError('Téléchargement filtré par le site : page HTML reçue à la place du PDF')
    return {'status':'ok','detail':label+' téléchargé ; extraction des tableaux à développer.','url':url,'evidence':evidence(key,raw)}

def web_document(url,marker,key,detail):
    raw,_,_=fetch(url);txt=raw.decode('utf-8',errors='replace')
    if marker.casefold() not in txt.casefold() or 'id="anubis_challenge"' in txt:raise CheckError('Page reçue sans le contenu attendu')
    return {'status':'ok','detail':detail,'url':url,'evidence':evidence(key,raw)}

def insee():
    url='https://bdm.insee.fr/series/sdmx/data/SERIES_BDM/011814639?startPeriod=2024'
    raw,_,_=fetch(url,headers={'Accept':'application/vnd.sdmx.structurespecificdata+xml'})
    try:root=ElementTree.fromstring(raw)
    except ElementTree.ParseError:raise CheckError('XML SDMX attendu absent') from None
    obs=[x for x in root.iter() if x.tag.split('}')[-1]=='Obs']
    if not obs:raise CheckError('Aucune observation de prix renvoyée')
    return {'status':'ok','detail':'Observations de l’IPC annuel lues ; 2026 reste un exercice en cours.','url':url,'observations':len(obs),'evidence':evidence('insee',raw)}

def piste():
    path=Path('/run/secrets/piste_config.py')
    tree=ast.parse(path.read_text(encoding='utf-8-sig'));cfg={}
    for n in tree.body:
        if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):
            for target in n.targets:
                if isinstance(target,ast.Name):cfg[target.id]=n.value.value
    if not all(cfg.get(x) for x in ('API_KEY','OAUTH_CLIENT_ID','OAUTH_CLIENT_SECRET')):raise CheckError('Configuration PISTE incomplète dans le montage')
    encoded=base64.b64encode((cfg['OAUTH_CLIENT_ID']+':'+cfg['OAUTH_CLIENT_SECRET']).encode()).decode()
    raw,_,_=fetch('https://oauth.piste.gouv.fr/api/oauth/token',data=b'grant_type=client_credentials',headers={'Authorization':'Basic '+encoded,'Content-Type':'application/x-www-form-urlencoded'},private=True)
    token=as_json(raw).get('access_token')
    if not token:raise CheckError('Jeton OAuth non reçu')
    url='https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/jorf'
    raw,_,_=fetch(url,data=json.dumps({'textCid':'JORFTEXT000049180270'}).encode(),headers={'Authorization':'Bearer '+token,'X-Gravitee-Api-Key':cfg['API_KEY'],'Content-Type':'application/json'},private=True)
    j=as_json(raw)
    if '2024-124' not in json.dumps(j,ensure_ascii=False):raise CheckError('API authentifiée mais décret témoin non retrouvé')
    return {'status':'ok','detail':'OAuth et lecture du décret d’annulation 2024-124 réussis.','url':'https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000049180270','evidence':{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}}

def rpc_decode(raw):
    try:return as_json(raw)
    except CheckError:
        for line in raw.decode('utf-8').splitlines():
            if line.startswith('data:'):
                try:j=json.loads(line[5:])
                except ValueError:continue
                if 'result' in j or 'error' in j:return j
        raise CheckError('Réponse MCP non exploitable') from None

def mcp():
    cfg=json.loads(Path('/run/secrets/moulineuse/oauth.json').read_text())
    auth='https://auth.code4code.eu/realms/code4code/protocol/openid-connect/token'
    try:
        raw,_,_=fetch(auth,data=urlencode({'grant_type':'client_credentials','client_id':cfg['client_id'].strip(),'client_secret':cfg['client_secret'].strip(),'scope':'moulineuse:read moulineuse:sql'}).encode(),headers={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},private=True)
    except HTTPError as e:
        try: code=as_json(e.read(16384)).get('error')
        except CheckError: code=None
        if e.code==401 and code=='invalid_client':
            raise CheckError('OAuth refuse les identifiants partagés avec LexMachine : HTTP 401 invalid_client. Compte existant ; raccordement à réparer.') from None
        raise

    token=as_json(raw).get('access_token')
    if not token:raise CheckError('Jeton Tricoteuses non reçu')
    url='https://mcp.code4code.eu/mcp'
    h={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream','Content-Type':'application/json','MCP-Protocol-Version':'2024-11-05'}
    def call(method,params,ident=1):
        payload={'jsonrpc':'2.0','method':method,'params':params}
        if ident is not None:payload['id']=ident
        raw,headers,_=fetch(url,data=json.dumps(payload).encode(),headers=h,private=True)
        for key,value in headers.items():
            if key.lower()=='mcp-session-id':h['Mcp-Session-Id']=value
        if not raw:return {}
        result=rpc_decode(raw)
        if result.get('error'):raise CheckError('Le serveur MCP renvoie une erreur de protocole ou de service')
        return result.get('result',{})
    init=call('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'lexmachine-budget','version':'0.1'}})
    if init.get('protocolVersion'):h['MCP-Protocol-Version']=init['protocolVersion']
    call('notifications/initialized',{},None)
    result=call('tools/list',{},2);names=[x.get('name') for x in result.get('tools',[])]
    if not names:raise CheckError('Authentification obtenue, mais aucun outil MCP reçu')
    if 'search_recipes' in names:
        recipe=call('tools/call',{'name':'search_recipes','arguments':{'q':'budget','limit':1}},3)
        if recipe.get('isError'):return {'status':'partial','detail':'OAuth et liste des outils réussis ; recherche de recette en erreur.','url':url,'tools':len(names)}
    return {'status':'ok','detail':'OAuth, session MCP et outils accessibles.','url':url,'tools':len(names),'recipe_check':'search_recipes' in names}

CORPORA={'an':('Assemblée nationale','marie.db'),'senat':('Sénat','marie.db'),'ppl':('Propositions de loi','ppl.db'),'plf':('Projets de loi de finances','plf_pli.db'),'questions':('Questions écrites','questions_ecrites.db'),'codes':('Codes et lois','legi_dole.db'),'jorf':('Journal officiel','. JURISPRUDENCE V2/dila_complement_juridique.db'),'kali':('KALI','. JURISPRUDENCE V2/dila_complement_juridique.db'),'cnil':('CNIL','. JURISPRUDENCE V2/dila_complement_juridique.db'),'circulaires':('Circulaires','. JURISPRUDENCE V2/dila_complement_juridique.db'),'ccomptes':('Cour des comptes','ccomptes_chunks.sqlite'),'jurisprudence':('Jurisprudence','. JURISPRUDENCE V2/jurisprudence_officielle_fine_chunks_consolidated_20260516.db')}
def corpus(rel):
    guard=as_json(Path('/run/budget/corpus-preflight.json').read_bytes())
    if abs(time.time()-guard['checked_at_epoch']) > 120:
        raise CheckError('Contrôle hôte périmé : lancer run-checks.ps1 avant de lire les corpus.')
    host=guard['databases'].get(rel)
    if not host or not host['exists']:
        raise CheckError('Base absente du contrôle hôte.')
    if host['active_journal']:
        return {'status':'partial','detail':'Lecture différée : journal SQLite non vide sur l’hôte. Utiliser un instantané cohérent avant la recherche.','database_read':False,'semantic_query_tested':False}
    p=Path('/corpus')/rel
    if not p.is_file():raise CheckError('Base absente du montage')
    for suffix in ('-wal','-journal'):
        side=Path(str(p)+suffix)
        if side.exists() and side.stat().st_size:raise CheckError('Journal SQLite actif : contrôle différé pour préserver la cohérence')
    with sqlite3.connect(p.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=3) as db:
        db.execute('PRAGMA query_only=ON')
        names=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 40")]
        if not names:raise CheckError('Base sans table')
        preferred=next((x for x in names if x in ('chunks','documents','records','decisions','textes')),names[0])
        quoted='"'+preferred.replace('"','""')+'"'
        found=db.execute('SELECT 1 FROM '+quoted+' LIMIT 1').fetchone()
        if not found:raise CheckError('Table témoin vide')
    return {'status':'partial','detail':'Base lue en lecture seule. Recherche vectorielle et couverture du fonds à raccorder et valider.','tables':len(names),'database_read':True,'semantic_query_tested':False}

def run_one(key,name,fn):
    started=time.monotonic()
    try:result=fn()
    except HTTPError as e:result={'status':'blocked','detail':'Réponse HTTP '+str(e.code)+' ; aucun accès réussi à la ressource testée.','http_status':e.code}
    except CheckError as e:result={'status':'blocked','detail':str(e)}
    except FileNotFoundError:result={'status':'blocked','detail':'Fichier de configuration ou de données absent du montage.'}
    except Exception as e:result={'status':'blocked','detail':'Échec technique : '+type(e).__name__+'.'}
    return {'id':key,'name':name,'checked_at':datetime.now(timezone.utc).isoformat(),'duration_ms':round((time.monotonic()-started)*1000),**result}

def main():
    STATE.mkdir(exist_ok=True)
    tasks=[('plf','Crédits proposés PLF',lambda:ods('plf25-depenses-2025-selon-destination','plf2025')),('nomenclature','Nomenclatures annuelles',lambda:ods('nomenclature-par-destination-lfi-2023','nomenclature2023')),('execution','Exécution PLR détaillée',lambda:ods('projet-de-loi-de-reglement-2019-plr-20190','plr2018')),('plrg','Mouvements PLRG',attachments),('lfi','Crédits votés LFI',lfi),('pap','Documents PAP',lambda:document('https://www.assemblee-nationale.fr/dyn/dyn/contenu/visualisation/1087969/file/PAP2026_BG_Ecologie_developpement_mobilites_durables_TA.pdf','pap2026','PAP 2026 Écologie')),('rap','Documents RAP',document),('piste','Légifrance / PISTE',piste),('insee','Inflation Insee',insee),('tricoteuses','Tricoteuses MCP',mcp),('an_open','Amendements AN',lambda:web_document('https://data.assemblee-nationale.fr/travaux-parlementaires/amendements/tous-les-amendements','Amendements.json.zip','an','Catalogue et lien de téléchargement disponibles ; import des archives à développer.')),('senat_open','Amendements Sénat',lambda:web_document('https://data.senat.fr/aide/liste-des-amendements/','CSV','senat','Documentation des fichiers CSV accessible ; extraction des dossiers à développer.')),('gels','Gels et surgels publiés',lambda:web_document('https://www.senat.fr/rap/r25-702/r25-7023.html','surgel','gels','Rapport public consulté ; couverture non exhaustive des gels.')),('datagouv','Catalogue data.gouv.fr',lambda:catalog())]
    tasks += [('corpus_'+key,'Corpus · '+name,lambda rel=rel:corpus(rel)) for key,(name,rel) in CORPORA.items()]
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(run_one,*task):task[0] for task in tasks}
        for future in concurrent.futures.as_completed(futures):
            value=future.result();results.append(value);print(json.dumps(value,ensure_ascii=False),flush=True)
    results.sort(key=lambda x:next(i for i,t in enumerate(tasks) if t[0]==x['id']))
    counts={s:sum(r['status']==s for r in results) for s in ('ok','partial','blocked')}
    core=('plf','nomenclature','execution','plrg','piste')
    report={'version':'0.1','phase':'connection_checks','checked_at':datetime.now(timezone.utc).isoformat(),'counts':counts,'core_ready':all(any(r['id']==k and r['status']=='ok' for r in results) for k in core),'all_connections_ready':all(r['status']=='ok' for r in results),'sources':results,'limitations':['Chorus exclu du périmètre de connexion.','La lecture d’un échantillon ne prouve pas un historique exhaustif.', 'Gels, dégels, annulations, reports, transferts et fonds de concours : accès aux sources de preuve, collecte et rapprochement restant à développer.','Les corpus locaux sont distincts d’un raccordement fonctionnel des moteurs vectoriels.']}
    tmp=STATE/'connections.tmp';tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');tmp.chmod(0o644);tmp.replace(STATE/'connections.json')
    with sqlite3.connect(STATE/'connections.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS checks (checked_at TEXT, source TEXT, status TEXT, report TEXT)')
        db.executemany('INSERT INTO checks VALUES (?,?,?,?)',[(r['checked_at'],r['id'],r['status'],json.dumps(r,ensure_ascii=False)) for r in results])
    print(json.dumps({'summary':counts,'core_ready':report['core_ready']},ensure_ascii=False))

def lfi():
    result=ods('credits-ae-et-cp-votes-nomenclature-par-destination-et-nature-lfi-2023','lfi2023')
    result.update(status='partial',detail='API et ligne LFI 2023 accessibles. Anomalie connue sur les montants : rapprochement avec le fichier officiel requis avant utilisation.')
    return result

def catalog():
    url='https://www.data.gouv.fr/api/1/datasets/?q=budget&page_size=1'
    raw,_,_=fetch(url);j=as_json(raw)
    if not j.get('data'):raise CheckError('Catalogue sans résultat')
    return {'status':'ok','detail':'Recherche de jeux de données réussie.','url':url,'evidence':evidence('datagouv',raw)}
if __name__=='__main__':main()

"""Read-only PLFSS data access. Published consolidated totals remain separate from branch sums."""
import json,sqlite3
from decimal import Decimal
from pathlib import Path
from functools import lru_cache
from .model import BRANCHES,ONDAM,STAGES,METRICS
PERIMETERS={'ROBSS':'Tous les régimes de base','RG':'Régime général','ROBSS_FSV':'Tous les régimes de base et FSV','RG_FSV':'Régime général et FSV','FSV':'Fonds de solidarité vieillesse'}

@lru_cache(maxsize=4)
def read_notices(path,mtime,size):return json.loads(Path(path).read_text(encoding='utf-8'))

class Store:
 def __init__(self,data):self.data=Path(data)
 def connect(self):
  db=sqlite3.connect((self.data/'derived/plfss.sqlite').resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row;return db
 def notices(self,fact):
  if 'table_index' not in fact or 'row_index' not in fact:return []
  path=self.data/'derived/source-notices.json'
  if not path.is_file():return []
  stat=path.stat();notices=read_notices(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
  key=[fact['source_id'],fact['table_index'],fact['exercise'],fact['perimeter'],fact['entity'],fact.get('balance_row_index',fact['row_index'])]
  return [n for n in notices if n['key']==key and n['source_sha']==fact['source_sha'] and n['values_cents'].get(fact['metric'])==fact['amount_cents']]
 def facts(self,domain='EQUILIBRE',perimeter='ROBSS',start=2023,end=2027,metric='DEPENSES',stages=('PLFSS','LFSS','CONSTATE')):
  with self.connect() as db:
   rows=db.execute('SELECT id,payload FROM facts WHERE domain=? AND perimeter=? AND exercise BETWEEN ? AND ? AND metric=? ORDER BY edition DESC,priority DESC,id',(domain,perimeter,start,end,metric))
   return [dict(json.loads(r['payload']),id=r['id']) for r in rows if json.loads(r['payload'])['stage'] in stages]
 def cell(self,facts,year,stage,entity):
  found=[r for r in facts if r['exercise']==year and r['stage']==stage and r['entity']==entity]
  if not found:return dict(status='missing',amount_cents=None,reason=self.missing_reason(year,stage,entity),references=[])
  # Prefer the direct normative table for voted/proposed objectives. Historical
  # results can be documented by an annex: this provenance stays visible.
  def ranking(r):
   if stage=='PROJECTION':return (r['priority'],r['edition'],int(r['kind']=='LFSS'),r.get('reference_date') or '')
   return (r['priority'],int(r['kind']=='LFSS') if stage=='CONSTATE' else 0,r.get('reference_date') or f"{r['edition']-1:04d}-00",r['edition'])
  rank=max(ranking(r) for r in found)
  chosen=[r for r in found if ranking(r)==rank]
  values={r['amount_cents'] for r in chosen}
  # Source rounding is an interval, not a blanket euro tolerance. Keep both
  # values and prefer finer raw data only when the stated intervals overlap.
  compatible=max(2*r['amount_cents']-int(Decimal(r['precision_eur'])*100) for r in chosen)<=min(2*r['amount_cents']+int(Decimal(r['precision_eur'])*100) for r in chosen)
  def raw_quantum(r):
   raw=str(r['raw']).replace(',','.').replace(' ','').replace('−','-').replace('‑','-').replace('–','-').replace('‐','-').strip('()')
   places=max(0,-Decimal(raw).as_tuple().exponent)
   return Decimal(r['unit_eur'])/(10**places)
  first=min(chosen,key=raw_quantum)
  status='published' if len(values)==1 else ('rounded_consistency' if compatible else 'divergence')
  notices={json.dumps(n,sort_keys=True):n for r in chosen for n in self.notices(r)}
  notice_reason=' '.join(n['explanation'] for n in notices.values())
  return dict(status=status,amount_cents=first['amount_cents'] if compatible else None,
   precision_eur=first['precision_eur'],edition=first['edition'],references=[r['id'] for r in chosen],
   source_notices=list(notices.values()),
   reason=('Plusieurs valeurs dans les tableaux retenus : consulter les sources.' if status=='divergence' else ('Les valeurs sont compatibles avec les arrondis publiés. La valeur numérique la plus détaillée est présentée ; les deux tableaux sont conservés.' if status=='rounded_consistency' else ('Valeur publiée dans une annexe historique.' if first['priority']<100 else '')))+(' Constat daté '+first['reference_date']+'.' if first.get('reference_date') else '')+(' '+notice_reason if notice_reason else ''),
   earlier_references=[r['id'] for r in found if r not in chosen],
   alternatives=[dict(id=r['id'],amount_cents=r['amount_cents'],source_id=r['source_id']) for r in chosen] if len(values)>1 else [])
 @staticmethod
 def missing_reason(year,stage,entity):
  if year==2027 and stage=='LFSS':return 'La LFSS 2027 n’est pas encore votée dans ce lot. Le PLFSS reste une proposition.'
  if year>=2026 and stage=='CONSTATE':return 'L’exercice annuel n’est pas clôturé à la date de la collecte du 3 octobre 2026.'
  return 'Aucune valeur qualifiée dans ce lot pour cette année, cette étape et ce périmètre. Cela ne prouve pas son absence des publications.'
 def matrix(self,domain,perimeter,start,end,metric,stages,excluded=()):
  facts=self.facts(domain,perimeter,start,end,metric,stages)
  names=ONDAM if domain=='ONDAM' else BRANCHES
  entities=[] if perimeter=='FSV' else (list(ONDAM)[1:] if domain=='ONDAM' else [x for x in BRANCHES if x!='FSV'])
  if perimeter.endswith('_FSV'):entities=[]
  total_entity='ONDAM' if domain=='ONDAM' else ('TOTAL_FSV' if perimeter.endswith('_FSV') else ('FSV' if perimeter=='FSV' else 'TOTAL'))
  columns=[dict(year=y,stage=s,label=STAGES[s]) for y in range(start,end+1) for s in stages]
  rows=[]
  for entity in entities:
   rows.append(dict(entity=entity,label=names[entity],excluded=entity in excluded,cells=[self.cell(facts,c['year'],c['stage'],entity) for c in columns]))
  total=dict(entity=total_entity,label=('FSV · montant publié' if perimeter=='FSV' else 'Total consolidé publié') if domain=='EQUILIBRE' else 'Total ONDAM publié',cells=[self.cell(facts,c['year'],c['stage'],total_entity) for c in columns])
  selected=None
  if excluded and rows:
   cells=[]
   for i in range(len(columns)):
    parts=[r['cells'][i] for r in rows if not r['excluded']]
    known=[p for p in parts if p['amount_cents'] is not None]
    notices={json.dumps(n,sort_keys=True):n for p in known for n in p.get('source_notices',[])}
    reason='Aucun poste sélectionné.' if not parts else ('Seuls les postes renseignés sont additionnés.' if len(known)!=len(parts) else '')
    if notices:reason+=' Cette somme comprend des cellules dont le tableau source présente un écart arithmétique ; consulter les preuves.'
    cells.append(dict(status='empty_selection' if not parts else ('partial' if len(known)!=len(parts) else 'computed'),amount_cents=sum(p['amount_cents'] for p in known) if known else None,references=[ref for p in known for ref in p['references']],reason=reason,source_notices=list(notices.values())))
   selected=dict(entity='SELECTION',label='Somme des branches sélectionnées · transferts non neutralisés' if domain=='EQUILIBRE' else 'Somme des sous-objectifs sélectionnés',cells=cells)
  return dict(domain=domain,perimeter=perimeter,metric=metric,unit='EUR',columns=columns,total=total,selection=selected,rows=rows,
   note='Le total consolidé publié neutralise les transferts entre branches. La somme des branches est distincte. L’ONDAM n’est jamais ajouté aux dépenses de la branche Maladie.')
 def source(self,sid):
  with self.connect() as db:
   r=db.execute('SELECT payload FROM sources WHERE id=?',(sid,)).fetchone()
  return json.loads(r[0]) if r else None
 def proof(self,fid):
  with self.connect() as db:
   r=db.execute('SELECT payload FROM facts WHERE id=?',(fid,)).fetchone()
  if not r:return None
  f=dict(json.loads(r[0]),id=fid);f['source']=self.source(f['source_id']);f['source_notices']=self.notices(f);return f
 def documents(self,year=None,family='',q=''):
  with self.connect() as db:sources=[json.loads(r[0]) for r in db.execute('SELECT payload FROM sources')]
  if year is not None:sources=[s for s in sources if s['publication_year']==year]
  if family:sources=[s for s in sources if s['family']==family]
  if q:sources=[s for s in sources if q.casefold() in (s['title']+' '+s['url']).casefold()]
  return sorted(sources,key=lambda s:(-s['publication_year'],s['title']))
 def meta(self):
  with self.connect() as db:
   version=db.execute("SELECT value FROM metadata WHERE key='data_version'").fetchone()[0]
   facts=db.execute('SELECT COUNT(*) FROM facts').fetchone()[0]
  sources=self.documents();files=[s for s in sources if s.get('status')=='downloaded'];families=sorted({s['family'] for s in sources})
  articles=[s for s in files if s.get('kind')=='moulineuse_journal_officiel']
  documents=[s for s in files if s.get('kind')!='moulineuse_journal_officiel']
  search={}
  try:
   from .retrieval_contract import VERSION,MODEL,REVISION,DIMENSION
   search=json.loads((self.data/'search/manifest.json').read_text(encoding='utf-8'))
   if (search.get('version'),search.get('state'),search.get('model'),search.get('revision'),search.get('dimension'))!=(VERSION,'ready',MODEL,REVISION,DIMENSION):search={}
  except (OSError,ValueError):pass
  return dict(data_version=version,facts=facts,files=len(documents),jorf_articles=len(articles),bytes=sum(s.get('bytes',0) for s in files),years=list(range(2017,2028)),stages=STAGES,metrics=METRICS,perimeters=PERIMETERS,families=families,
   collected_on='2026-10-03',vectorized=bool(search),indexed_passages=search.get('passages',0),indexed_documents=search.get('documents',0),vectorization_model=search.get('model'),publication_note='PLFSS 2027 : texte initial, annexe 9 et dossier de presse collectés. Annexes DSS 1 à 8 annoncées à venir lors de la collecte. Données votées et résultats annuels futurs laissés distincts.')

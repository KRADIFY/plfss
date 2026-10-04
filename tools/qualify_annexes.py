"""Qualify annex structure without inventing a financial meaning for numeric cells.

The inventory distinguishes source tables from amounts integrated into the
accounts matrix. A candidate monetary unit/year is not a certified assignment.
"""
import collections,csv,json,re,sys,zipfile
from pathlib import Path
from decimal import Decimal
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.excel_source import strings,sheets,styles,N
from tools.collect import atomic
from plfss_service.model import norm

def unit_candidates(text):
 text=str(text)
 found=[]
 for key,pattern in [('MdEUR',r'(?i)\bmd\s*€|milliards?\s*(?:d.?euros|€)|\bmd\s*eur'),('MEUR',r'(?i)\bm\s*€|millions?\s*(?:d.?euros|€)|\bm\s*eur'),('EUR',r'(?i)\ben\s*euros?\b|\(\s*€\s*\)')]:
  if re.search(pattern,text):found.append(key)
 return found

def annex_number(source):
 text=source['title']+' '+source['path']
 match=re.search(r'annexe[\s_\-]*(\d{1,2})',text,re.I)
 return int(match[1]) if match else None

def main():
 sources=json.loads((ROOT/'data/catalogue/normalized-sources.json').read_text('utf-8'))
 facts=json.loads((ROOT/'data/derived/facts.json').read_text('utf-8'))
 used=collections.Counter((f['source_id'],f.get('sheet')) for f in facts)
 details_path=ROOT/'data/derived/annex-detail-observations.json'
 details=json.loads(details_path.read_text('utf-8')) if details_path.is_file() else {'records':[]}
 detail_used=collections.Counter((f['source_id'],f['sheet']) for f in details['records'])
 entries=[];errors=[]
 for source in sources:
  if source['status']!='downloaded' or not source.get('path','').lower().endswith('.xlsx'):continue
  try:
   with zipfile.ZipFile(ROOT/'data'/source['path']) as z:
    ss=strings(z);formats=styles(z)
    for name,path in sheets(z):
     root=ET.fromstring(z.read(path));labels=[];numbers=[];counts=collections.Counter()
     for cell in root.findall('.//s:sheetData/s:row/s:c',N):
      coord=cell.attrib['r'];row=int(re.sub('[A-Z]','',coord));v=cell.find('s:v',N);raw=v.text if v is not None else None;t=cell.attrib.get('t','n');fmt=formats[int(cell.attrib.get('s','0'))]
      if t=='s':value=ss[int(raw)] if raw is not None else ''
      elif t=='inlineStr':value=''.join(cell.find('s:is',N).itertext())
      else:value=raw
      if t in ('s','inlineStr','str') and value and row<=14:labels.append(dict(cell=coord,text=value))
      if t=='n' and raw is not None:
       dec=Decimal(raw)
       if not dec.is_finite():continue
       counts['numeric_cells']+=1;counts['explicit_zero_cells']+=dec==0
       if '%' in fmt:counts['percent_format_cells']+=1
       if re.fullmatch(r'20\d\d',raw) and 1900<=dec<=2100:counts['year_like_cells']+=1
       numbers.append(dict(cell=coord,raw=raw,format=fmt))
     text=' '.join(l['text'] for l in labels);units=unit_candidates(text)
     period_headers=[l for l in labels if re.fullmatch(r'\s*(?:PLFSS|LFSS|PLF|LFI|constat(?:é)?|réalisation)?\s*20\d\d\s*(?:\(p\)|\(prev\.?\))?\s*',l['text'],re.I)]
     n=norm(text+' '+name)
     topics=[]
     for topic,words in [('recettes',('recette','cotisation','contribution','csg','exoneration')),('prestations',('prestation','allocation','pension')),('organismes',('regime','organisme','caisse')),('dette',('dette','cades','amortissement')),('reserves',('reserve','actif','frr')),('sante',('ondam','soins','hopit','etablissement')),('autonomie',('autonomie','handicap','dependance')),('complementaires',('complementaire','chomage','agirc','arrco'))]:
      if any(w in n for w in words):topics.append(topic)
     scope='regimes_complementaires_distincts_ROBSS' if source['publication_year']>=2023 and annex_number(source)==8 and 'PLFSS' in source['path'].upper() else 'annexe_perimetre_a_lire'
     if 'effortnational' in n or 'effortdelanation' in n:scope='effort_national_plus_large_que_ROBSS'
     if not counts['numeric_cells']:status='documentary_structure_no_numeric_cells'
     elif used[(source['id'],name)]:status='selected_amounts_integrated_other_cells_retained'
     elif detail_used[(source['id'],name)]:status='selected_detail_series_qualified_other_cells_retained'
     elif len(units)>1:status='mixed_units_column_qualification_required'
     elif counts['percent_format_cells']==counts['numeric_cells']:status='rates_not_budget_amounts'
     elif units and period_headers:status='monetary_table_identified_financial_mapping_pending'
     else:status='context_or_unit_qualification_required'
     entries.append(dict(source_id=source['id'],source_sha=source['sha256'],url=source['url'],publication_year=source['publication_year'],family=source['family'],annex=annex_number(source),sheet=name,title=next((l['text'] for l in labels if len(l['text'])>25),' / '.join(l['text'] for l in labels[:3])),headers=labels,unit_candidates=units,year_headers=period_headers,topics=topics,scope=scope,status=status,integrated_observations=used[(source['id'],name)],qualified_separate_detail_observations=detail_used[(source['id'],name)],**counts))
  except Exception as e:errors.append(dict(source_id=source['id'],error=str(e),type=type(e).__name__))
 result=dict(data_version=json.loads((ROOT/'reports/normalized.json').read_text('utf-8'))['data_version'],workbooks=len({x['source_id'] for x in entries}),worksheets=len(entries),numeric_cells=sum(x.get('numeric_cells',0) for x in entries),explicit_zero_cells=sum(x.get('explicit_zero_cells',0) for x in entries),status_counts=dict(collections.Counter(x['status'] for x in entries)),errors=errors,all_tables_financially_qualified=False,entries=entries,scope='Inventaire des feuilles Excel, titres, unités candidates, périodes candidates et exploitation démontrée. Les cellules numériques ne sont pas automatiquement des montants en euros ; tous les détails PDF restent dans les preuves de préparation documentaire.')
 atomic(ROOT/'reports/annex-qualification.json',result)
 with (ROOT/'reports/annexes-a-qualifier.csv').open('w',encoding='utf-8-sig',newline='') as out:
  fields=['publication_year','family','annex','source_id','sheet','title','numeric_cells','explicit_zero_cells','percent_format_cells','unit_candidates','scope','status','integrated_observations','qualified_separate_detail_observations','url']
  w=csv.DictWriter(out,fieldnames=fields,delimiter=';',extrasaction='ignore');w.writeheader()
  for x in entries:
   y=dict(x);y['unit_candidates']=' / '.join(y['unit_candidates']);w.writerow(y)
 print(json.dumps({k:v for k,v in result.items() if k not in ('entries','scope')}),flush=True)

if __name__=='__main__':main()

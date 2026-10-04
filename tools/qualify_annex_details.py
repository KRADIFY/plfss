"""Qualify explicitly labelled annex series; do not append them to branch totals.

The rules target consolidated receipts/expenses, CADES and FRR tables whose
scope and monetary unit are printed. Rates and mixed-unit tables stay apart.
Original figures, formula caches, labels and physical cells remain the proof.
"""
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
import collections,csv,gzip,hashlib,json,re,sys,zipfile
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.excel_source import strings,sheets,styles,N
from plfss_service.model import norm

def year_header(value):
 match=re.fullmatch(r'\s*(20\d\d)\s*(?:\(\s*p\s*\))?\s*',str(value),re.I)
 return int(match[1]) if match and 2017<=int(match[1])<=2027 else None

def to_cents(raw,unit,fmt):
 fmt=fmt.split(';')[0]
 tail=re.search(r'[0#](,+)(?:[^0#,]*$)',fmt)
 scale=1000**len(tail[1]) if tail else 1
 multiplier=Decimal({'MEUR':10**6,'MdEUR':10**9,'EUR':1}[unit])/scale
 return int((Decimal(raw)*multiplier*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)),str(multiplier),scale

def rule(title,sheet):
 n=norm(title)
 if 'produitsnetsconsolides' in n and 'typederecette' in n:return ('recettes_detaillees','consolide_ROBSS_FSV','columns')
 if 'repartitiondeschargesnettes' in n and 'regimesdebase' in n:return ('depenses_detaillees','consolide_ROBSS_FSV','columns')
 if 'amortissementdeladettesociale' in n:return ('dette_sociale','CADES','rows')
 if sheet.casefold().startswith('frr tab') and 'comptes' in n:return ('comptes_fonds_reserves','FRR','columns')
 return None

def main():
 register=json.loads((ROOT/'reports/annex-qualification.json').read_text('utf-8'))
 sources={s['id']:s for s in json.loads((ROOT/'data/catalogue/normalized-sources.json').read_text('utf-8'))}
 selected=[(x,rule(x['title'],x['sheet'])) for x in register['entries'] if rule(x['title'],x['sheet'])]
 records=[];tables=[];held=[]
 for entry,kind in selected:
  source=sources[entry['source_id']];path=ROOT/'data'/source['path']
  with path.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==entry['source_sha']
  if len(entry['unit_candidates'])!=1:
   held.append(dict(source_id=source['id'],sheet=entry['sheet'],reason='unit_not_unique'));continue
  unit=entry['unit_candidates'][0]
  with zipfile.ZipFile(path) as z:
   ss=strings(z);formats=styles(z);root=ET.fromstring(z.read(dict(sheets(z))[entry['sheet']]))
   cells={}
   for cell in root.findall('.//s:sheetData/s:row/s:c',N):
    coord=cell.attrib['r'];v=cell.find('s:v',N);raw=v.text if v is not None else None;t=cell.get('t','n')
    value=ss[int(raw)] if t=='s' and raw is not None else ''.join(cell.find('s:is',N).itertext()) if t=='inlineStr' else raw
    formula=cell.find('s:f',N)
    if value is not None:cells[coord]=dict(value=value,raw=raw,type=t,format=formats[int(cell.get('s','0'))],formula=formula.text if formula is not None else None)
  group,scope,orientation=kind;start=len(records);omitted=collections.Counter()
  if orientation=='columns':
   candidates=collections.defaultdict(dict)
   for coord,c in cells.items():
    row=int(re.sub('[A-Z]','',coord));year=year_header(c['value'])
    if row<=14 and year:candidates[row][re.sub('[0-9]','',coord)]=(year,coord,c['value'])
   candidates={r:cols for r,cols in candidates.items() if len(cols)>=2 and len({x[0] for x in cols.values()})==len(cols)}
   if len(candidates)!=1:
    held.append(dict(source_id=source['id'],sheet=entry['sheet'],reason='year_header_row_not_unique'));continue
   heading,columns=next(iter(candidates.items()))
   from openpyxl.utils.cell import column_index_from_string
   first_col=min(column_index_from_string(c) for c in columns)
   for coord,c in cells.items():
    col=re.sub('[0-9]','',coord);row=int(re.sub('[A-Z]','',coord))
    if row<=heading or col not in columns or c['type']!='n':continue
    if '%' in c['format']:omitted['percent_format']+=1;continue
    labels=[(k,v['value']) for k,v in cells.items() if int(re.sub('[A-Z]','',k))==row and column_index_from_string(re.sub('[0-9]','',k))<first_col and v['type'] in ('s','inlineStr','str')]
    if not labels:omitted['row_label_absent']+=1;continue
    year,hcoord,hlabel=columns[col];label=' / '.join(str(v) for _,v in labels)
    value,multiplier,scale=to_cents(c['raw'],unit,c['format'])
    records.append(dict(source_id=source['id'],source_sha=source['sha256'],url=source['url'],edition=source['publication_year'],sheet=entry['sheet'],title=entry['title'],topic=group,perimeter=scope,exercise=year,cell=coord,row_label=label,label_cells=[k for k,_ in labels],header_cell=hcoord,column_label=hlabel,raw=c['raw'],source_unit=unit,unit_eur=multiplier,excel_scale=scale,number_format=c['format'],formula=c['formula'],amount_cents=value,explicit_zero=Decimal(c['raw'])==0,period_status='prevision_explicitement_etiquetee' if re.search(r'\(\s*p\s*\)',str(hlabel),re.I) else 'serie_documentaire_etape_non_inferree',added_to_branch_totals=False))
  else:
   # CADES table: years run vertically; stock and annual flow columns stay
   # distinct, and neither is added to branches or to the ONDAM envelope.
   heading_rows=[int(re.sub('[A-Z]','',k)) for k,c in cells.items() if int(re.sub('[A-Z]','',k))<=8 and c['type'] in ('s','inlineStr','str') and 'anneedereprise' in norm(c['value'])]
   if len(heading_rows)!=1:
    held.append(dict(source_id=source['id'],sheet=entry['sheet'],reason='CADES_year_column_not_unique'));continue
   heading=heading_rows[0]
   headers={re.sub('[0-9]','',k):(k,c['value']) for k,c in cells.items() if int(re.sub('[A-Z]','',k))==heading and c['type'] in ('s','inlineStr','str')}
   year_cols=[col for col,(_,label) in headers.items() if 'anneedereprise' in norm(label)]
   if len(year_cols)!=1:
    held.append(dict(source_id=source['id'],sheet=entry['sheet'],reason='CADES_year_column_not_unique'));continue
   year_col=year_cols[0]
   for coord,c in cells.items():
    col=re.sub('[0-9]','',coord);row=int(re.sub('[A-Z]','',coord));yc=year_col+str(row)
    if row<=heading or col==year_col or col not in headers or c['type']!='n' or yc not in cells:continue
    year=year_header(cells[yc]['value'])
    if not year:omitted['year_outside_2017_2027_or_unqualified']+=1;continue
    if '%' in c['format']:omitted['percent_format']+=1;continue
    hcoord,label=headers[col];value,multiplier,scale=to_cents(c['raw'],unit,c['format'])
    records.append(dict(source_id=source['id'],source_sha=source['sha256'],url=source['url'],edition=source['publication_year'],sheet=entry['sheet'],title=entry['title'],topic=group,perimeter=scope,exercise=year,cell=coord,row_label=str(cells[yc]['value']),label_cells=[yc],header_cell=hcoord,column_label=label,raw=c['raw'],source_unit=unit,unit_eur=multiplier,excel_scale=scale,number_format=c['format'],formula=c['formula'],amount_cents=value,explicit_zero=Decimal(c['raw'])==0,period_status='serie_documentaire_etape_non_inferree',added_to_branch_totals=False))
  tables.append(dict(source_id=source['id'],sheet=entry['sheet'],topic=group,perimeter=scope,qualified_cells=len(records)-start,other_cells_not_integrated=dict(omitted)))
 # Independent earlier inventory: every selected raw value and physical cell
 # must already exist verbatim in the separately produced source-cell register.
 indexed={(r['source_id'],r['sheet'],r['cell']):r for r in records};checked=set()
 with gzip.open(ROOT/'data/extracted/excel-cells.jsonl.gz','rt',encoding='utf-8') as stream:
  for line in stream:
   cell=json.loads(line);key=(cell['source_id'],cell['sheet'],cell['cell'])
   if key in indexed:
    r=indexed[key];assert r['raw']==cell['raw'] and r['source_sha']==cell['source_sha'] and r['number_format']==cell['format'];checked.add(key)
 assert checked==set(indexed)
 result=dict(qualified_observations=len(records),unique_positions=len(indexed),tables=tables,held=held,source_cells_rechecked=len(checked),explicit_zeros=sum(r['explicit_zero'] for r in records),added_to_branch_totals=False,financial_database_modified=False,all_annex_details_qualified=False,records=records)
 (ROOT/'data/derived/annex-detail-observations.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
 summary={k:v for k,v in result.items() if k!='records'}
 (ROOT/'reports/annex-detail-qualification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 with (ROOT/'reports/annex-details-qualifies.csv').open('w',encoding='utf-8-sig',newline='') as f:
  fields=['edition','exercise','topic','perimeter','sheet','cell','row_label','column_label','raw','source_unit','unit_eur','amount_cents','explicit_zero','period_status','url']
  w=csv.DictWriter(f,fieldnames=fields,delimiter=';',extrasaction='ignore');w.writeheader();w.writerows(records)
 print(json.dumps({k:v for k,v in summary.items() if k not in ('tables','held')}|dict(tables=len(tables),held=len(held))))

if __name__=='__main__':main()

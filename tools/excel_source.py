"""Inventory exact XML values and formats; qualify only explicit ONDAM result tables."""
import gzip,json,re,sys,zipfile,posixpath
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from plfss_service.model import norm,ondam
N={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

def strings(z):
 if 'xl/sharedStrings.xml' not in z.namelist():return []
 return [''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',N)]

def sheets(z):
 rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
 for s in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',N):
  path=rels[s.attrib['{'+N['r']+'}id']];path=path.lstrip('/') if path.startswith('/') else posixpath.normpath('xl/'+path)
  yield s.attrib['name'],path

def styles(z):
 from openpyxl.styles.numbers import BUILTIN_FORMATS
 root=ET.fromstring(z.read('xl/styles.xml'));formats=dict(BUILTIN_FORMATS)
 for f in root.findall('s:numFmts/s:numFmt',N):formats[int(f.attrib['numFmtId'])]=f.attrib['formatCode']
 return [formats.get(int(x.attrib.get('numFmtId','0')),'General') for x in root.findall('s:cellXfs/s:xf',N)]

def main():
 docs=json.loads((ROOT/'data/catalogue/documents.json').read_text(encoding='utf-8'));facts=[];book_inventory=[];count=0;zero=0
 outpath=ROOT/'data/extracted/excel-cells.jsonl.gz';outpath.parent.mkdir(exist_ok=True)
 with gzip.open(outpath,'wt',encoding='utf-8') as out:
  for source in docs:
   if source['status']!='downloaded' or not source.get('path','').lower().endswith('.xlsx'):continue
   try:
    with zipfile.ZipFile(ROOT/'data'/source['path']) as z:
     ss=strings(z);formats=styles(z);sheet_notes=[]
     for name,path in sheets(z):
      root=ET.fromstring(z.read(path));cells={};numbers=[]
      for cell in root.findall('.//s:sheetData/s:row/s:c',N):
       coord=cell.attrib['r'];v=cell.find('s:v',N);formula=cell.find('s:f',N);t=cell.attrib.get('t','n');fmt=formats[int(cell.attrib.get('s','0'))]
       raw=v.text if v is not None else None
       if t=='s':value=ss[int(raw)] if raw is not None else ''
       elif t=='inlineStr':value=''.join(cell.find('s:is',N).itertext())
       else:value=raw
       cells[coord]=dict(value=value,raw=raw,type=t,format=fmt,formula=formula.text if formula is not None else None)
       if t=='n' and raw is not None:
        try:dec=Decimal(raw)
        except Exception:continue
        if not dec.is_finite():continue
        numbers.append(coord);count+=1;zero+=dec==0
        out.write(json.dumps(dict(source_id=source['id'],source_sha=source['sha256'],sheet=name,cell=coord,raw=raw,format=fmt,formula=cells[coord]['formula'],status='published_numeric_cell'),ensure_ascii=False)+'\n')
      text=' '.join(str(c['value'] or '') for k,c in cells.items() if c['type'] in ('s','inlineStr','str') and int(re.sub('[A-Z]','',k))<=10)
      captured=0
      if 'ondam' in norm(text) and any(w in norm(text) for w in ('realisation','constat','execution')) and re.search(r'(?:Md\s*€|milliards?|Md\s*EUR)',text,re.I):
       headers={}
       # Only a column explicitly called Constat/Réalisation/Exécution, or a
       # year column in a table explicitly describing realizations, qualifies.
       for coord,c in cells.items():
        if c['type'] not in ('s','inlineStr','str') or int(re.sub('[A-Z]','',coord))>8:continue
        n=norm(c['value']);ys=re.findall(r'(?<!\d)20\d\d(?!\d)',str(c['value']))
        # Differences "par rapport au constat" and dates of a revision are not
        # annual results. Require the column heading itself to name a result.
        actual_header=bool(re.match(r'^(?:constat|realisation|execution|depensesconstate)',n)) and not any(w in n for w in ('ecart','revision','evolution','taux','prevision','base'))
        stated=re.search(r'^(?:constat(?:é|ée|és|ées)?|réalisations?|exécution|dépenses constatées)\D{0,20}(20\d\d|\d{2})(?!\d)',str(c['value']).strip(),re.I) if actual_header else None
        if stated:ys=[str(int(stated[1])+(2000 if len(stated[1])==2 else 0))]
        if len(ys)!=1:continue
        year=int(ys[0])
        if not 2017<=year<=2025:continue
        if actual_header or (n==str(year) and 'realisation' in norm(text) and 'prevision' not in norm(text)):
         headers[re.sub('[0-9]','',coord)]=(year,coord,str(c['value']))
       for coord in numbers:
        col=re.sub('[0-9]','',coord);row=int(re.sub('[A-Z]','',coord));c=cells[coord]
        if col not in headers or '%' in c['format']:continue
        year,hcoord,label=headers[col]
        if row<=int(re.sub('[A-Z]','',hcoord)):continue
        labelcells=[(k,v) for k,v in cells.items() if int(re.sub('[A-Z]','',k))==row and v['type'] in ('s','inlineStr','str')]
        entities=[(k,v,ondam(v['value'])) for k,v in labelcells if ondam(v['value'])]
        if len(entities)!=1:continue
        lk,lv,entity=entities[0]
        # Excel trailing format commas scale the visual value by 1,000 each.
        fmt=c['format'].split(';')[0];tail=re.search(r'[0#](,+)(?:[^0#,]*$)',fmt);scale=1000**len(tail[1]) if tail else 1
        unit=Decimal(10**9)/scale;dec=Decimal(c['raw']);cents=int((dec*unit*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        precision=Decimal(10**9)/(10**(len(re.search(r'\.([0#]+)',fmt)[1]) if re.search(r'\.([0#]+)',fmt) else 0))
        months={'janvier':1,'février':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'août':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12}
        dated=re.findall(r'('+'|'.join(months)+r')\s*(20\d\d)',label,re.I)
        refdate=max((f'{int(y):04d}-{months[m.lower()]:02d}' for m,y in dated),default='')
        facts.append(dict(exercise=year,edition=source['publication_year'],kind='DSS_RESULTATS',stage='CONSTATE',domain='ONDAM',perimeter='ROBSS',entity=entity,metric='DEPENSES',amount_cents=cents,raw=c['raw'],unit_eur=str(unit),precision_eur=str(precision),source_id=source['id'],source_sha=source['sha256'],sheet=name,cell=coord,label_cell=lk,header_cell=hcoord,reference_date=refdate,number_format=c['format'],excel_scale=scale,row_label=lv['value'],column_label=label,context=text[:1600],priority=100))
        captured+=1
      sheet_notes.append(dict(sheet=name,numeric_cells=len(numbers),normalized_ondam_results=captured,status='qualified_selected_results' if captured else 'inventoried_not_financially_qualified'))
     book_inventory.append(dict(source_id=source['id'],sheets=sheet_notes,status='inventoried'))
   except Exception as exc:book_inventory.append(dict(source_id=source['id'],status='failed',error=type(exc).__name__))
 (ROOT/'data/extracted/excel-facts.json').write_text(json.dumps(facts,ensure_ascii=False),encoding='utf-8')
 (ROOT/'reports/excel-inventory.json').write_text(json.dumps(book_inventory,ensure_ascii=False,indent=2),encoding='utf-8')
 result=dict(workbooks=len(book_inventory),numeric_cells=count,explicit_zero_cells=zero,qualified_ondam_observations=len(facts),inventory_errors=sum(b['status']=='failed' for b in book_inventory))
 (ROOT/'reports/excel-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()

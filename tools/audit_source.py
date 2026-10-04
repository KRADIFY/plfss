"""Independent cell reread with hashes and Decimal, without the application conversion function."""
import hashlib,json,re,sys,zipfile,posixpath,unicodedata
import xml.etree.ElementTree as ET
from functools import lru_cache
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
import lxml.html
ROOT=Path(__file__).resolve().parents[1]

@lru_cache(maxsize=16)
def read_source(path,mtime,size,utf8):
 body=Path(path).read_bytes()
 digest=hashlib.sha256(body).hexdigest()
 if Path(path).suffix.lower() in ('.xlsx','.pdf'):return digest,None
 return digest,lxml.html.fromstring(body.decode('utf-8')) if utf8 else lxml.html.fromstring(body)

@lru_cache(maxsize=8)
def read_excel(path,mtime,size,sheet):
 ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
 with zipfile.ZipFile(path) as z:
  relationships={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
  entry=next(s for s in ET.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet',ns) if s.attrib['name']==sheet)
  target=relationships[entry.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
  target=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
  from openpyxl.styles.numbers import BUILTIN_FORMATS
  styles=ET.fromstring(z.read('xl/styles.xml'));number_formats=dict(BUILTIN_FORMATS)
  for f in styles.findall('m:numFmts/m:numFmt',ns):number_formats[int(f.attrib['numFmtId'])]=f.attrib['formatCode']
  xf=[number_formats.get(int(f.attrib.get('numFmtId','0')),'General') for f in styles.findall('m:cellXfs/m:xf',ns)]
  shared=[''.join(s.itertext()) for s in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',ns)] if 'xl/sharedStrings.xml' in z.namelist() else []
  cells,labels,formats={},{},{}
  for c in ET.fromstring(z.read(target)).findall('.//m:sheetData/m:row/m:c',ns):
   coordinate=c.attrib['r'];value=c.find('m:v',ns);raw=value.text if value is not None else None
   formats[coordinate]=xf[int(c.attrib.get('s','0'))]
   if c.attrib.get('t')=='s':labels[coordinate]=shared[int(raw)] if raw is not None else ''
   elif c.attrib.get('t')=='inlineStr':labels[coordinate]=''.join(c.find('m:is',ns).itertext())
   elif c.attrib.get('t')=='str':labels[coordinate]=raw or ''
   elif raw is not None:cells[coordinate]=raw
  return cells,labels,formats

@lru_cache(maxsize=8)
def read_pdf(path,mtime,size,page_number):
 import pdfplumber
 with pdfplumber.open(path) as pdf:
  page=pdf.pages[page_number-1]
  return page.extract_text(),[(t.extract(),[r.cells for r in t.rows]) for t in page.find_tables()]

def check(fact,source,data):
 path=Path(data)/source['path'];stat=path.stat()
 digest,tree=read_source(str(path),stat.st_mtime_ns,stat.st_size,source.get('kind')=='moulineuse_journal_officiel')
 if digest!=fact['source_sha']:return 'source_hash_changed'
 if fact.get('page_number'):
  body,tables=read_pdf(str(path),stat.st_mtime_ns,stat.st_size,fact['page_number'])
  rows,positions=tables[fact['table_index']]
  raw=rows[fact['row_index']][fact['column_index']]
  if fact.get('line_index') is not None:raw=raw.splitlines()[fact['line_index']]
  if raw!=fact['raw']:return 'source_cell_differs'
  bbox=positions[fact['row_index']][fact['column_index']]
  if [round(v,3) for v in bbox]!=fact['pdf_bbox']:return 'source_cell_position_differs'
  expected=int((Decimal(raw.replace(',','.'))*Decimal(fact['unit_eur'])*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
  if expected!=fact['amount_cents']:return 'amount_differs'
  if fact['unit_eur']!=10**9 or not re.search(r'Md\s*€|milliards?',body,re.I):return 'unit_not_found'
  header=re.sub(r'\s+',' ',rows[0][fact['column_index']]).strip()
  if header!=fact['column_label']:return 'source_column_differs'
  if header!='Constat '+str(fact['exercise']):return 'annual_result_not_named'
  return None
 if fact.get('sheet'):
  cells,labels,formats=read_excel(str(path),stat.st_mtime_ns,stat.st_size,fact['sheet']);raw=cells.get(fact['cell'])
  if raw!=fact['raw']:return 'source_cell_differs'
  header=labels.get(fact['header_cell'],'')
  if header!=fact['column_label']:return 'source_column_differs'
  if labels.get(fact['label_cell'])!=fact['row_label']:return 'source_row_differs'
  stated=re.match(r'^(?:constat(?:é|ée|és|ées)?|réalisations?|exécution|dépenses constatées)\D{0,20}(20\d\d|\d{2})(?!\d)',header.strip(),re.I)
  if not stated or int(stated[1])+(2000 if len(stated[1])==2 else 0)!=fact['exercise']:return 'annual_result_not_named'
  source_context=' '.join(t for coordinate,t in labels.items() if int(re.sub('[A-Z]','',coordinate))<=10)
  if not re.search(r'(?:Md\s*€|milliards?|Md\s*EUR)',source_context,re.I):return 'unit_not_found'
  fmt=formats.get(fact['cell'],'')
  if fmt!=fact['number_format']:return 'source_format_differs'
  positive=re.sub(r'"[^"]*"|\\.', '',fmt.split(';')[0])
  commas=re.search(r'[0#](,+)(?:[^0#,]*$)',positive)
  visual_scale=1000**len(commas[1]) if commas else 1
  if Decimal(fact['unit_eur'])!=Decimal(10**9)/visual_scale:return 'unit_differs'
  expected=int((Decimal(raw)*Decimal(fact['unit_eur'])*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
  if expected!=fact['amount_cents']:return 'amount_differs'
  if not re.search(r'(?:Md\s*€|milliards?|Md\s*EUR)',fact['context'],re.I):return 'unit_not_found'
  if not re.match(r'^(?:constat|réalisation|exécution)',fact['column_label'].strip(),re.I):return 'annual_result_not_named'
  return None
 table=tree.xpath('//table')[fact['table_index']]
 row=table.xpath('.//tr')[fact['row_index']]
 cells=row.xpath('./th|./td');cell=cells[fact['column_index']]
 raw=re.sub(r'\s+',' ',' '.join(cell.itertext())).strip()
 if raw!=fact['raw']:return 'source_cell_differs'
 normalized=raw.replace('−','-').replace('–','-').replace('‑','-').replace('‐','-').replace(',','.')
 normalized=re.sub(r'\s','',normalized)
 if normalized.startswith('(') and normalized.endswith(')'):normalized='-'+normalized[1:-1]
 expected=int((Decimal(normalized)*Decimal(fact['unit_eur'])*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
 if expected!=fact['amount_cents']:return 'amount_differs'
 if 'year_header_row_index' in fact:
  source_rows=table.xpath('.//tr')
  header=source_rows[fact['year_header_row_index']].xpath('./th|./td')[fact['year_header_column_index']]
  header_text=re.sub(r'\s+',' ',' '.join(header.itertext())).strip()
  if header_text!=fact['column_label'] or re.findall(r'(?<!\d)20\d\d(?!\d)',header_text)!=[str(fact['exercise'])]:return 'source_year_differs'
  year_positions=[i for i,c in enumerate(source_rows[fact['year_header_row_index']].xpath('./th|./td')) if len(re.findall(r'(?<!\d)20\d\d(?!\d)',' '.join(c.itertext())))==1]
  numeric_positions=[]
  for i,c in enumerate(cells):
   if i<=fact['metric_column_index']:continue
   text=re.sub(r'\s','', ' '.join(c.itertext())).replace(',','.').replace('−','-').replace('‑','-').replace('–','-').replace('‐','-')
   try:
    if Decimal(text).is_finite():numeric_positions.append(i)
   except Exception:pass
  if len(numeric_positions)!=len(year_positions):return 'ambiguous_year_alignment'
  if numeric_positions.index(fact['column_index'])!=year_positions.index(fact['year_header_column_index']):return 'cell_in_wrong_year'
  label=fact['row_label']
  if fact.get('entity_row_index') is not None:
   label=' '.join(source_rows[fact['entity_row_index']].xpath('./th|./td')[0].itertext())
   label=re.sub(r'\s+',' ',label).strip()
   if label!=fact['row_label']:return 'source_row_differs'
  token=re.sub('[^a-z0-9]','',unicodedata.normalize('NFKD',label).encode('ascii','ignore').decode().lower())
  aliases={'maladie':'MALADIE','accidentsdutravail':'ATMP','atmp':'ATMP','vieillesse':'VIEILLESSE','famille':'FAMILLE','autonomie':'AUTONOMIE','fsv':'FSV','fondsdesolidaritevieillesse':'FSV','rgconsolide':'TOTAL','robssconsolide':'TOTAL','rgfsv':'TOTAL_FSV','robssfsv':'TOTAL_FSV'}
  named=next((value for key,value in aliases.items() if token==key or (key not in ('fsv','rgconsolide','robssconsolide','rgfsv','robssfsv') and token.startswith(key))),None)
  if named and fact['entity']!=named:return 'entity_differs'
  metric_text=' '.join(cells[fact['metric_column_index']].itertext()).strip().casefold()
  metric_name={'recettes':'RECETTES','dépenses':'DEPENSES','solde':'SOLDE'}.get(metric_text)
  if metric_name and metric_name!=fact['metric']:return 'metric_differs'
 # Re-read the unit near the table; an asserted unit must actually be stated.
 context=' '.join(' '.join(p.itertext()) for p in table.xpath('preceding::p[position()<=6]'))+' '+' '.join(table.itertext())[:600]
 if fact['unit_eur']==10**9 and not re.search(r'milliards?|Md\s*[€eE]',context,re.I):return 'unit_not_found'
 if fact['unit_eur']==10**6 and not re.search(r'millions?',context,re.I):return 'unit_not_found'
 # Direct normative year must be present in the current table's introduction.
 if fact['priority']==100 and str(fact['exercise']) not in context:return 'exercise_not_found'
 return None

def main():
 data=ROOT/'data';facts=json.loads((data/'derived/facts.json').read_text(encoding='utf-8'));sources={s['id']:s for s in json.loads((data/'catalogue/normalized-sources.json').read_text(encoding='utf-8'))}
 anomalies=[]
 for index,f in enumerate(facts):
  try:error=check(f,sources[f['source_id']],data)
  except Exception as exc:error=type(exc).__name__
  if error:anomalies.append(dict(index=index,source_id=f['source_id'],table=f.get('table_index'),row=f.get('row_index'),column=f.get('column_index'),page=f.get('page_number'),reason=error))
 version=hashlib.sha256(json.dumps(facts,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 result=dict(data_version=version,checked=len(facts),source_cell_anomalies=anomalies,passed=not anomalies,scope='Relecture des cellules intégrées et des unités ; ne certifie pas l’exploitation complète des publications ni toutes les qualifications sémantiques.')
 (ROOT/'reports/source-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(dict(checked=len(facts),anomalies=len(anomalies),passed=not anomalies)))
 if anomalies:sys.exit(1)
if __name__=='__main__':main()

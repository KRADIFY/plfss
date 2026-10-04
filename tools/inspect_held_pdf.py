"""Read-only diagnosis of the historical serializer on a held PDF page.

The exception includes the exact token count and offsets; no extractor or
prepared output is replaced. Keep the source PDF and raw page text intact.
"""
from pathlib import Path
import json,sys
import prepare_vectorization as prep

def main():
 config=json.loads((prep.OUT/'preparation-contract.json').read_text('utf-8'))
 extractors,tables,tk,_=prep.runtime(config)
 source=next(i for i in json.loads((prep.OUT/'source-inventory.json').read_text('utf-8'))['items'] if i['source']['id']=='641a2fb3a1933d25b182e75f')
 original=prep.OUT/'code/vectorisation_table_text_word_safe.py'
 code=original.read_text('utf-8').replace("raise ValueError('Serialized chunk exceeds its token contract')", "raise ValueError(json.dumps(dict(message='Serialized chunk exceeds its token contract',tokens=tokens,max_tokens=max_tokens,table_id=context['table_id'],pending=pending),ensure_ascii=False))")
 namespace={};exec(compile(code,str(original)+' [read-only diagnostic]','exec'),namespace)
 tables.serialize_table=namespace['serialize_table']
 import fitz
 path=prep.ROOT/'data'/source['source']['path'];findings=[]
 with fitz.open(path) as doc:
  for rec in extractors.pdf_records(path,config):
   if rec['page']!=34:continue
   try:tables.page_payload(rec,doc[33],source['source']['sha256'],tk,'PLFSS. Source officielle. Années documentaires : 2025. PLFSS et annexes. ')
   except ValueError as e:
    finding=json.loads(str(e));findings.append(finding)
   break
 report=dict(source_id=source['source']['id'],source_sha256=source['source']['sha256'],page=34,original_code_sha256=prep.sha(original),diagnostic_only=True,source_bytes_changed=False,findings=findings)
 (prep.ROOT/'reports/held-pdf-diagnosis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(dict(source_id=report['source_id'],page=34,findings=[dict(tokens=x['tokens'],max_tokens=x['max_tokens'],table_id=x['table_id']) for x in findings])))

if __name__=='__main__':main()

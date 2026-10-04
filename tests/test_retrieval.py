import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from plfss_service import retrieval_service as r,retrieval_client as client
from plfss_service.retrieval_contract import VERSION,MODEL,REVISION,DIMENSION
from tools.build_retrieval_index import schema

class SearchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  db=sqlite3.connect(self.root/'search.sqlite');schema(db)
  docs=[(1,'2017','pdf','Commission des comptes'),(2,'2027','pdf','PLFSS et annexes'),(3,'2027','html','Journal officiel'),(4,'2027','pdf','Cour des comptes')]
  for n,y,fmt,family in docs:
   db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(n,str(n),str(n)*64,str(n)*24,'Document '+y,'https://example.org/source',fmt,'|'+y+'|','PLFSS',family,'source_locators','not_validated_budget_fact',1))
   ident=format(n,'064x');text='ONDAM maladie 0 123,45'
   db.execute('INSERT INTO passages VALUES(?,?,?,?,?,?,?)',(n,ident,text,10,'a'*64,b'',b''));db.execute('INSERT INTO passages_fts(rowid,text) VALUES(?,?)',(n,text));db.execute('INSERT INTO citations VALUES(?,?,?)',(n,n,'page:9/table:2/row:4'))
  db.commit();db.close();(self.root/'dense.faiss').write_bytes(b'index')
  manifest=dict(version=VERSION,state='ready',model=MODEL,revision=REVISION,dimension=DIMENSION,passages=4,documents=4,physical_files=4,files=[dict(path=n,bytes=(self.root/n).stat().st_size) for n in ['search.sqlite','dense.faiss']])
  (self.root/'manifest.json').write_text(json.dumps(manifest))
  self.saved=r.ROOT;r.ROOT=self.root;r.manifest.cache_clear();r.dense_index.cache_clear()
 def tearDown(self):
  r.ROOT=self.saved;r.manifest.cache_clear();r.dense_index.cache_clear();self.tmp.cleanup()
 def params(self,**kw):return {k:[str(v)] for k,v in dict(q='ONDAM',mode='text',**kw).items()}
 def test_document_year_does_not_leak(self):
  got=r.search(self.params(year=2027))
  self.assertEqual(got['count'],3);self.assertTrue(all(c['years']==[2027] for i in got['items'] for c in i['citations']))
 def test_format_and_family_filters_together(self):
  got=r.search(self.params(year=2027,format='pdf',family='PLFSS et annexes'))
  self.assertEqual(got['count'],1);self.assertEqual(got['items'][0]['citations'][0]['source_kind'],'PLFSS et annexes')
 def test_dense_candidates_are_filtered_before_acceptance(self):
  class Index:
   def search(self,vector,limit):return None,[[1,3,4,2]]
  p=self.params(year=2027,format='pdf',family='PLFSS et annexes');p['mode']=['hybrid']
  with patch.object(r,'encode',return_value=(None,{})),patch.object(r,'dense_index',return_value=Index()):got=r.search(p)
  self.assertEqual(got['count'],1);self.assertIn('dense',got['items'][0]['retrieval_methods'])
  self.assertEqual(got['items'][0]['citations'][0]['years'],[2027])
 def test_pdf_page_and_original_text_retained(self):
  got=r.passage(format(2,'064x'));self.assertEqual(got['text'],'ONDAM maladie 0 123,45');self.assertEqual(got['citations'][0]['page'],9)
  self.assertEqual(got['numeric_status'],'not_validated_budget_fact')
 def test_unknown_query_is_not_claimed_absent_in_publications(self):
  got=r.search(dict(q=['inexistantzzxy'],mode=['text']));self.assertEqual(got['count'],0);self.assertFalse(got['missing_result_is_absence_proof'])
 def test_generation_model_mismatch_blocks_search(self):
  p=self.root/'manifest.json';m=json.loads(p.read_text());m['revision']='wrong';p.write_text(json.dumps(m));r.manifest.cache_clear()
  self.assertFalse(r.status()['available'])
 def test_invalid_queries_rejected(self):
  for kw in [dict(q=['x'*201]),dict(q=['x'],year=['2028']),dict(q=['x'],mode=['bad']),dict(q=['x'],limit=['51'])]:
   with self.subTest(kw=kw),self.assertRaises(ValueError):r.parameters(kw)
 def test_passage_path_is_not_a_fetch_url(self):
  with self.assertRaises(ValueError):client.passage('https://example.org/')
 def test_bad_source_hash_has_no_download(self):
  class Store:
   data=Path('.')
   def source(self,sid):return dict(status='downloaded',sha256='b'*64,path='no.pdf')
  got=client.resolve_sources(dict(citations=[dict(source_id='a',source_sha256='a'*64)]),Store())
  self.assertFalse(got['citations'][0]['local_available']);self.assertEqual(got['citations'][0]['source_id'],'')

if __name__=='__main__':unittest.main()

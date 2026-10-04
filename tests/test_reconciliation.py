import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from plfss_service.store import Store

class ReconciliationTests(unittest.TestCase):
 def test_nine_notices_documented_without_numeric_replacement(self):
  notices=json.loads((ROOT/'data/derived/source-notices.json').read_text('utf-8'))
  self.assertEqual(len(notices),9)
  for n in notices:
   self.assertEqual(n['status'],'source_difference_documented_values_retained')
   self.assertIs(n['resolved_value'],False)
   self.assertTrue(n['supporting_documents'])
   self.assertIn('Rapprochement documentaire',n['explanation'])
 def test_signed_divergence_is_explained_and_original_retained(self):
  store=Store(ROOT/'data');cell=store.matrix('EQUILIBRE','RG_FSV',2018,2018,'SOLDE',('CONSTATE',))['total']['cells'][0]
  self.assertEqual(cell['amount_cents'],120000000000)
  notice=cell['source_notices'][0]
  self.assertEqual(notice['documentary_category'],'divergence_signe_article_annexe')
  self.assertIn('−1,2',notice['explanation'])
 def test_annex_inventory_does_not_certify_all_numeric_cells(self):
  r=json.loads((ROOT/'reports/annex-qualification.json').read_text('utf-8'))
  self.assertEqual(r['workbooks'],82);self.assertEqual(r['worksheets'],3495)
  self.assertEqual(r['numeric_cells'],1063782)
  self.assertIs(r['all_tables_financially_qualified'],False)
  self.assertFalse(r['errors'])
  self.assertTrue(r['status_counts']['rates_not_budget_amounts'])
 def test_supporting_pdf_has_page_in_source_link(self):
  notices=json.loads((ROOT/'data/derived/source-notices.json').read_text('utf-8'))
  docs=[d for n in notices for d in n['supporting_documents'] if d['url'].endswith('pl4523.pdf')]
  self.assertTrue(docs);self.assertTrue(all(d['page_number']==165 for d in docs))

if __name__=='__main__':unittest.main()

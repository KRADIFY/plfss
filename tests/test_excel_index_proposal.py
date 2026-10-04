import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.propose_excel_index import row_preview

class ExcelProposalTests(unittest.TestCase):
 def test_zero_and_explicit_empty_string_are_not_tail_nulls(self):
  row=[None,0,'',None,None];p=row_preview(row,[],9)
  self.assertEqual(p['retained_values'],[None,0,'']);self.assertEqual(p['tail']['first_column'],4)
  self.assertIn('Colonne 2 : 0',p['text']);self.assertIn('Colonne 3 : [VIDE chaîne vide]',p['text'])
 def test_original_line_can_be_reconstructed(self):
  for row in ([None]*16384,[4,None,7]+[None]*16381,[{'formula':'SUM(A1:A2)','cached':None},None],['',None]):
   p=row_preview(row,[],5);tail=p['tail']['count'] if p['tail'] else 0
   self.assertEqual(p['retained_values']+[None]*tail,row)
 def test_interior_null_keeps_its_physical_column(self):
  p=row_preview([3,None,8,None],['Recettes','Dépenses','Solde'],10)
  self.assertIn('Colonne 2 [en-tête candidat Dépenses] : [ABSENT NULL]',p['text'])
  self.assertIn('Colonne 3 [en-tête candidat Solde] : 8',p['text']);self.assertEqual(p['tail']['first_column'],4)

if __name__=='__main__':unittest.main()

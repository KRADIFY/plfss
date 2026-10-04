import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_vectorization import literal_table_lines,recover

class EvidenceTests(unittest.TestCase):
 def test_blank_null_and_zero_are_distinct(self):
  lines=literal_table_lines(dict(rows=[[None,'',0]],row_start=9,header_candidates=['Vide','Chaîne','Zéro']))
  self.assertIn('[ABSENT NULL]',lines[0]);self.assertIn('[VIDE chaîne vide]',lines[0]);self.assertIn('Colonne 3 [en-tête candidat Zéro] : 0',lines[0])
 def test_character_gap_and_overlap_are_rejected(self):
  initial=dict(block=0,char_start=0,char_end=4,text='mot ')
  for start in (3,5):
   with self.assertRaises(ValueError):recover([dict(segments=[initial]),dict(segments=[dict(block=0,char_start=start,char_end=start+5,text='suite')])])
 def test_in_word_boundary_is_rejected(self):
  with self.assertRaises(ValueError):recover([dict(segments=[dict(block=0,char_start=0,char_end=3,text='bud')]),dict(segments=[dict(block=0,char_start=3,char_end=6,text='get')])])
 def test_natural_boundary_preserves_all_characters(self):
  parts=[dict(segments=[dict(block=0,char_start=0,char_end=7,text='budget ')]),dict(segments=[dict(block=0,char_start=7,char_end=17,text='2027 : 0 €')])]
  self.assertEqual(recover(parts)[0],'budget 2027 : 0 €')

if __name__=='__main__':unittest.main()

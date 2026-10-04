import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.qualify_annex_details import year_header,to_cents,rule

class AnnexDetailsTests(unittest.TestCase):
 def test_calendar_date_and_rate_are_not_annual_headers(self):
  for value in ('20/12/2025','2025-2026','Structure 2023',0.2025):self.assertIsNone(year_header(value))
  self.assertEqual(year_header('2025 (p)'),2025);self.assertEqual(year_header(2017),2017)
 def test_large_values_are_converted_without_float(self):
  self.assertEqual(to_cents('572447','MEUR','General')[0],57244700000000)
  self.assertEqual(to_cents('2323.6000000000004','MEUR','0.0')[0],232360000000)
 def test_source_display_scale_and_zero_are_preserved(self):
  self.assertEqual(to_cents('625333000000','MEUR','0,,')[0],62533300000000)
  self.assertEqual(to_cents('0','MdEUR','General')[0],0)
 def test_similarly_named_graph_does_not_qualify(self):
  self.assertIsNone(rule('Graphique - Dette des ménages','Dette'))
  self.assertEqual(rule('Tableau - Répartition des charges nettes des régimes de base et du FSV','III.tab12')[1],'consolide_ROBSS_FSV')

if __name__=='__main__':unittest.main()

import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from prepare_memo_vectorization import selected_pdf,digest,dump
from verify_memo_vectorization import check_generic_coverage,verify_record
from guard_memo_boundaries import word_safe_class


class MemoChecks(unittest.TestCase):
    def test_continuity_with_permitted_overlap(self):
        blocks=['Le programme reçoit 50 millions.','La réserve est de zéro.','Le périmètre exclut les frais.']
        chunks=[dict(body=blocks[0]+'\n\n'+blocks[1]),dict(body=blocks[1]+'\n\n'+blocks[2])]
        self.assertEqual(check_generic_coverage(blocks,chunks),1)

    def test_a_missing_exception_is_rejected(self):
        blocks=['Le programme reçoit 50 millions.','Sauf les frais de fonctionnement.']
        with self.assertRaises(ValueError):check_generic_coverage(blocks,[dict(body=blocks[0])])

    def test_a_modified_amount_is_rejected(self):
        with self.assertRaises(ValueError):check_generic_coverage(['Crédits : 50 euros.'],[dict(body='Crédits : 500 euros.')])

    def test_pdf_route_uses_documentary_evidence(self):
        self.assertFalse(selected_pdf(dict(tables=[],issues=[],method='native')))
        self.assertTrue(selected_pdf(dict(tables=[dict(rows=[[0]])],issues=[],method='native')))
        self.assertTrue(selected_pdf(dict(tables=[],issues=['grid_candidate_not_resolved'],method='native')))
        self.assertTrue(selected_pdf(dict(tables=[],issues=[],method='ocr_fra_eng')))

    def table(self,line):
        rec=dict(kind='historical_batch',source_sha256='a'*64,locator='Feuille!row:8',
            source_records=[dict(kind='table',rows=[[None,'',0]],row_start=8)],serialized_blocks=[line])
        ref=digest(rec['source_sha256']+'\n'+rec['locator']+'\n'+dump(rec))
        return dict(record=rec,record_ref=ref,chunks=[],route='generic_conditional_150')

    def test_a_published_zero_must_not_disappear(self):
        with self.assertRaisesRegex(ValueError,'cell or column missing'):
            verify_record(self.table('Ligne 8. Colonne 3 : 1'),None)

    def test_a_zero_in_another_column_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'cell or column missing'):
            verify_record(self.table('Ligne 8. Colonne 2 : 0'),None)

    def test_a_colon_in_the_header_is_not_a_cell_value(self):
        obj=self.table('Ligne 8. Colonne 3 [Montant : euros] : 1')
        with self.assertRaisesRegex(ValueError,'cell or column missing'):verify_record(obj,None)

    def guarded_chunker(self):
        from prepare_historical_excel import freeze,runtime
        _,config,code=freeze();env,legacy,_=runtime(config,code)
        return word_safe_class(type(legacy),env['clean'])(config)

    def test_long_paragraph_keeps_whole_words_and_amounts(self):
        chunker=self.guarded_chunker()
        paragraph=' '.join(['crédits extraordinaires 123456789,00 euros']*180)
        chunks=[dict(text=text,body=body) for text,body in chunker.chunks('PLFSS 2027',[paragraph])]
        self.assertGreater(len(chunks),1)
        check_generic_coverage([paragraph],chunks)
        self.assertTrue(all(chunker.count(c['text'])<=800 for c in chunks))

    def test_guard_does_not_disable_conditional_overlap(self):
        chunker=self.guarded_chunker()
        blocks=[f'Article {n} réserve assurance maladie crédits spécifiques.' for n in range(200)]
        chunks=[dict(body=body) for _,body in chunker.chunks('PLFSS',blocks)]
        self.assertGreater(check_generic_coverage(blocks,chunks),0)

    def test_indivisible_overlong_word_is_held(self):
        chunker=self.guarded_chunker()
        with self.assertRaisesRegex(ValueError,'Indivisible source word'):
            list(chunker.atoms('extraordinaire'*2000,50))


if __name__=='__main__':unittest.main()

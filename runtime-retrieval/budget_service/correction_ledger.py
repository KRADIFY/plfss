"""Verify reviewed corrections without rewriting independent control sources."""
from collections import defaultdict
import json

KEY=('year','stage','measure','budget','mission','program','title','action','subaction','category')


def verify(db,meta,check_source):
    ledger=meta.get('recent_reconciliation_corrections',{})
    changes=ledger.get('fact_replacements',[])+ledger.get('fact_insertions',[])
    impacts=defaultdict(int);ids=defaultdict(list)
    assert len({c['id'] for c in changes})==len(changes)
    for change in changes:
        after=change['after'];key={k:after[k]for k in KEY}
        actual=db.execute('SELECT * FROM facts WHERE '+' AND '.join(k+'=?'for k in key),tuple(key.values())).fetchall()
        assert len(actual)==1 and dict(actual[0])==after,(change['id'],'current fact differs')
        proof=change.get('rap_evidence') or change['proof']
        check_source(proof['source'],proof.get('sha256')or proof.get('source_sha256'))
        assert after['source']==proof['source'] and after['line']==proof['page']
        before=change.get('before');delta=after['cents']-(before['cents']if before else 0)
        k=tuple(after[x]for x in ('year','stage','measure','budget','mission'))
        impacts[k]+=delta;ids[k].append(change['id'])
    adjustments={}
    for row in ledger.get('affected_aggregate_adjustments',[]):
        k=tuple(row[x]for x in ('year','stage','measure','budget','mission'))
        assert k not in adjustments
        assert row['correction_cents']==impacts[k] and set(row['correction_ids'])==set(ids[k])
        assert row['previous_fact_sum_cents']+row['correction_cents']==row['corrected_fact_sum_cents']
        actual=db.execute('SELECT sum(cents) FROM facts WHERE year=? AND stage=? AND measure=? AND budget=? AND mission=?',k).fetchone()[0]
        assert actual==row['corrected_fact_sum_cents'],(k,actual,row)
        adjustments[k]=row
    assert set(adjustments)==set(impacts)
    return adjustments


HISTORICAL_KEY = ('year', 'budget', 'program', 'stage', 'measure')



from decimal import Decimal

def euro_cents(raw):
 assert isinstance(raw,str) and raw.strip(),'blank source amount'
 return Decimal(raw.replace(' ','').replace('\u00a0','').replace('\u202f','').replace(',','.').replace('−','-').removesuffix('€'))*100

def validate_historical_amount(row,proof):
 assert proof['source_units']=='EUR' and proof['stored_units']=='integer_cents'
 assert proof['amount_cents']==row['cents']
 if proof.get('kind')!='exact_algebraic_reconstruction_from_published_balance':
  c=proof['selected_total_cell'];assert c['amount_cents']==row['cents'] and euro_cents(c['raw_text'])==row['cents'];return
 # This exception is bound to the reviewed original P869 page, not arbitrary arithmetic.
 assert tuple(row[k]for k in HISTORICAL_KEY)==(2018,'CCF','869','OUVERT','CP')
 assert proof['sha256']=='9e44560acc7fcfa80c98064c9adc5a4370a595ec2ecae74537bc49c6e189e349' and proof['page']==6
 assert proof['source']==row['source']=='5a7f13b14297211eb877'
 assert proof['source_grain']==proof['published_grain']=='programme_total_all_titles'
 assert proof['selected_total_cell'] is None and proof['amount_cents']==row['cents']==0
 d=proof['derivation'];assert d['operator']=='add' and d['formula']=='opened = consumed + (opened - consumed)'
 assert d['measure']=='CP' and d['same_page'] is True and d['same_total_column'] is True
 assert [t['role']for t in d['terms']]==['consumed','opened_minus_consumed']
 assert [t['cell']for t in d['terms']]==proof['cells']
 expected=[([530,357,539,369],'Total des crédits consommés / CP Total y.c. FDC et ADP'),([530,370,539,382],'Crédits ouverts - crédits consommés / CP Total y.c. FDC et ADP')]
 for term,(bbox,label)in zip(d['terms'],expected):
  cell=term['cell'];assert cell['bbox']==bbox and cell['label']==label
  assert cell['raw_text']=='0' and type(cell['amount_cents'])is int and cell['amount_cents']==0
 assert sum(t['cell']['amount_cents']for t in d['terms'])==d['result_cents']==row['cents']
 assert proof['blank_published_opened_cell']==dict(raw_text='',bbox=[480,344,539,357],label='Cellule total CP ouverts laissée vide dans le RAP')
 assert proof['headers'][1]['raw_text']=='Total des crédits consommés'
 assert proof['headers'][2]['raw_text']=='Crédits ouverts - crédits consommés'
 assert 'Crédits de paiement' in proof['headers'][0]['raw_text'] and 'Total\ny.c. FDC et ADP' in proof['headers'][0]['raw_text']


def validate_historical_absence_batch(ledger, change):
    absence = change['canonical_absence_check']
    if absence['database_sha256'] == ledger['source_database_sha256']:
        return
    # The second independent baseline is explicitly reviewed; never accept an
    # arbitrary hash merely because it is present in the ledger.
    approved_sha = '5b13a4bf27069d909bb77182f7e87d0d9303f7ba5186c86da8f0707d776698d7'
    approved_candidate = 'c5e08537084f45082d6cc6eb1be71cc0bffcc1a394424ff3b060f2ce4a9425c8'
    expected_ids = {
        'historical-2019-CAS-721-OUVERT-AE', 'historical-2019-CAS-721-OUVERT-CP',
        'historical-2019-CAS-796-OUVERT-AE', 'historical-2019-CAS-796-OUVERT-CP',
        'historical-2019-CCF-853-OUVERT-AE', 'historical-2019-CCF-854-OUVERT-AE',
        'historical-2019-CCF-854-OUVERT-CP', 'historical-2018-CCF-869-LFI-CP',
        'historical-2018-CCF-869-OUVERT-CP'}
    batches = [b for b in ledger.get('approved_absence_batches', [])
               if change['id'] in b.get('correction_ids', [])]
    assert len(batches) == 1
    batch = batches[0]
    assert batch['database_sha256'] == absence['database_sha256'] == approved_sha
    assert batch['fact_count'] == 122961 and batch['candidate_sha256'] == approved_candidate
    assert set(batch['correction_ids']) == expected_ids and len(batch['correction_ids']) == 9
    changes = [c for c in ledger['fact_insertions'] if c['id'] in expected_ids]
    assert len(changes) == 9
    assert all(c['canonical_absence_check']['database_sha256'] == approved_sha for c in changes)


def verify_historical(db, meta, check_source):
    """Check the independently reviewed programme totals, separately from fixes."""
    from collections import Counter
    from decimal import Decimal
    from .import_pap_2026_national import FIELDS
    ledger = meta.get('historical_canonical_import')
    if not ledger:
        return {'facts': 0, 'sources_verified': 0, 'explicit_zero_facts': 0, 'by_budget_stage': {}}
    assert ledger['id'] and not ledger.get('fact_replacements')
    assert ledger['independent_published_totals_modified'] is False
    changes = ledger['fact_insertions']
    assert len(changes) == ledger['facts_added']
    assert len({c['id'] for c in changes}) == len(changes)
    seen = set(); sources = set(); counts = Counter(); zeros = 0; derived_zeros = 0
    impacts = defaultdict(int); correction_ids = defaultdict(list)
    for change in changes:
        row = change['after']; proof = change['proof']
        assert not change.get('before') and set(row) == set(FIELDS)
        assert type(row['cents']) is int and row['year'] in range(2017, 2023)
        assert row['budget'] in ('BA', 'CAS', 'CCF') and row['stage'] in ('LFI', 'OUVERT')
        assert row['measure'] in ('AE', 'CP')
        assert all(row[k] == '' for k in ('action', 'subaction', 'category', 'title'))
        assert set(change['absence_key_fields']) == set(HISTORICAL_KEY)
        key = tuple(row[k] for k in HISTORICAL_KEY)
        assert key not in seen; seen.add(key)
        absence = change['canonical_absence_check']
        assert absence['matching_rows'] == 0
        validate_historical_absence_batch(ledger, change)
        assert absence['where'] == {k: row[k] for k in HISTORICAL_KEY}
        actual = db.execute('SELECT * FROM facts WHERE ' + ' AND '.join(k+'=?' for k in HISTORICAL_KEY), key).fetchall()
        # This query intentionally spans mission, action and title, so an exact
        # parent alongside a detail row is still a duplicate scope and fails.
        assert len(actual) == 1 and dict(actual[0]) == row, (change['id'], 'programme scope differs')
        source = check_source(proof['source'], proof['sha256'])
        assert row['source'] == proof['source'] and row['line'] == proof['page'] > 0
        if source and source.get('pages'): assert proof['page'] <= source['pages']
        assert row['stage'] == proof['stage'] and row['measure'] == proof['measure']
        validate_historical_amount(row, proof)
        assert proof['source_grain'] == 'programme_total_all_titles' or (
            row['budget']=='BA' and row['stage']=='OUVERT'
            and proof['source_grain']=='programme_total_all_titles_including_FDC'
            and proof.get('origin')=='independent_PLR_annex2_programme_total'
            and proof.get('column_header_cells') and proof.get('total_column_header'))
        assert proof['source_units'] == 'EUR' and proof['stored_units'] == 'integer_cents'
        sources.add(row['source']); counts[row['budget']+'/'+row['stage']] += 1
        derived = proof.get('kind') == 'exact_algebraic_reconstruction_from_published_balance'
        zeros += row['cents'] == 0 and not derived
        derived_zeros += row['cents'] == 0 and derived
        aggregate = tuple(row[k] for k in ('year', 'stage', 'measure', 'budget', 'mission'))
        impacts[aggregate] += row['cents']; correction_ids[aggregate].append(change['id'])
    seen_aggregates = set()
    for item in ledger['affected_aggregate_adjustments']:
        key = tuple(item[k] for k in ('year', 'stage', 'measure', 'budget', 'mission'))
        assert key not in seen_aggregates; seen_aggregates.add(key)
        assert item['correction_cents'] == impacts[key] and set(item['correction_ids']) == set(correction_ids[key])
        assert item['previous_fact_sum_cents'] + item['correction_cents'] == item['corrected_fact_sum_cents']
        total = db.execute('SELECT SUM(cents) FROM facts WHERE year=? AND stage=? AND measure=? AND budget=? AND mission=?', key).fetchone()[0]
        assert total == item['corrected_fact_sum_cents']
    assert seen_aggregates == set(impacts)
    assert dict(counts) == ledger['counts']['by_budget_stage'] and zeros == ledger['counts']['explicit_zero_facts']
    assert derived_zeros == ledger['counts'].get('exactly_derived_zero_facts', 0)
    return dict(facts=len(changes), sources_verified=len(sources), explicit_zero_facts=zeros, exactly_derived_zero_facts=derived_zeros,
                by_budget_stage=dict(counts), prior_facts_modified=False,
                programme_scope_unique=True, blank_cells_converted_to_zero=False)

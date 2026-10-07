"""Independent reconciliation of imported programme amounts against mission totals."""
import hashlib
import json
import os
from collections import Counter
from decimal import Decimal
from datetime import datetime,timezone
from pathlib import Path
from .api import connect,metadata
from .normalize import DATA,INPUTS,read_table,source_id
from .rap_validation import validate_action,validate_movements,validate_reserve,validate_action_subactions
from . import correction_ledger,action_details,reserves,rap_movements
from .data_signature import signature,digest as file_digest
from .reconciliation import assess_difference,capped_rounding_bound,action_cents as detail_cents

def original_cents(value):
    return int(Decimal(str(value).replace(' ','').replace('\u00a0','').replace(',','.'))*100)

def main():
    manifest=json.loads((INPUTS/'MANIFEST-COLLECTE.json').read_text(encoding='utf-8-sig'))
    db=connect();meta=metadata(db);checks=[];files=0;verified_sources={}
    def check_source(identifier,expected=None):
        source=json.loads(db.execute('SELECT data FROM sources WHERE id=?',(identifier,)).fetchone()[0])
        if expected is not None:assert source['sha256']==expected,identifier
        if identifier not in verified_sources:
            assert file_digest(DATA/source['path'])==source['sha256'],identifier
            verified_sources[identifier]=source['sha256']
        return source
    adjustments=correction_ledger.verify(db,meta,check_source)
    historical_canonical=correction_ledger.verify_historical(db,meta,check_source)
    used={r[0] for r in db.execute('SELECT DISTINCT source FROM facts')}
    for source in manifest:
        if source_id(source) in used:
            digest=hashlib.sha256((DATA/source['path']).read_bytes()).hexdigest()
            assert digest==source['sha256'],source.get('title')
            files+=1
        name=source.get('title','')
        if name not in ('Annexe1-Etat_AE_CP-2024.csv','Annexe1-Etat_AE_CP-2025.csv'):continue
        year=int(name[-8:-4]);rows=read_table(source)
        for number,row in enumerate(rows[1:],2):
            for stage,measure,index in [('OUVERT','AE',1),('EXEC','AE',2),('OUVERT','CP',3),('EXEC','CP',4)]:
                expected=original_cents(row[index])
                actual=db.execute('SELECT SUM(cents) FROM facts WHERE year=? AND stage=? AND measure=? AND budget=? AND mission_label=?',(year,stage,measure,'BG',row[0])).fetchone()[0]
                difference=None if actual is None else actual-expected
                codes={r[0]for r in db.execute('SELECT DISTINCT mission FROM facts WHERE year=? AND budget=? AND mission_label=?',(year,'BG',row[0]))}
                assert len(codes)==1,(year,row[0],codes)
                adjustment=adjustments.get((year,stage,measure,'BG',next(iter(codes))))
                corrected_difference=difference
                if adjustment:
                    assert abs(expected-adjustment['previous_fact_sum_cents'])<=2,(year,row[0],adjustment)
                    corrected_difference=difference-adjustment['correction_cents']
                check={'year':year,'mission':row[0],'stage':stage,'measure':measure,'difference_cents':difference,'source':source_id(source),'row':number,
                    'documented_adjustment':adjustment,'difference_after_documented_adjustment_cents':corrected_difference}
                checks.append(check)
                assert corrected_difference is not None and abs(corrected_difference)<=2,check
    # Concrete independent example: AE and CP of programme 105 must stay distinct.
    expected={('LFI','AE'):264536959000,('LFI','CP'):264993860200,
              ('EXEC','AE'):258594862169,('EXEC','CP'):261387916274}
    for (stage,measure),amount in expected.items():
        actual=db.execute("SELECT SUM(cents) FROM facts WHERE year=2025 AND program='105' AND stage=? AND measure=?",(stage,measure)).fetchone()[0]
        assert actual==amount,(stage,measure,actual,amount)
    assert db.execute("SELECT count(*) FROM facts WHERE year=2023 AND stage='LFI' AND action<>''").fetchone()[0]==0
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert db.execute("SELECT count(*) FROM facts WHERE measure NOT IN ('AE','CP') OR year NOT BETWEEN 2017 AND 2026").fetchone()[0]==0
    pap2026={}
    if meta.get('pap2026_national'):
        pap=meta['pap2026_national']
        pap_facts=db.execute("SELECT count(*) FROM facts WHERE year=2026 AND budget='BG' AND stage IN ('PLF','FDC_PREVU') AND action='' AND subaction=''").fetchone()[0]
        assert pap_facts==pap['observations']==372
        assert db.execute("SELECT count(*) FROM facts WHERE year=2026 AND budget='BG' AND stage IN ('PLF','FDC_PREVU') AND cents<=0").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM facts WHERE year=2026 AND mission='TA' AND program='362' AND stage IN ('PLF','FDC_PREVU')").fetchone()[0]==0
        duplicates=db.execute("""SELECT count(*) FROM (
            SELECT year,stage,measure,budget,mission,program,count(*) n FROM facts
            WHERE year=2026 AND budget='BG' AND stage IN ('PLF','FDC_PREVU') AND action='' AND subaction=''
            GROUP BY year,stage,measure,budget,mission,program HAVING n>1)""").fetchone()[0]
        assert duplicates==0
        source_pairs=list(db.execute("SELECT DISTINCT mission,source FROM facts WHERE year=2026 AND budget='BG' AND stage IN ('PLF','FDC_PREVU')"))
        assert len(source_pairs)==pap['missions']==32
        for mission,identifier in source_pairs:
            stored=db.execute('SELECT data FROM sources WHERE id=?',(identifier,)).fetchone()
            assert stored,(mission,identifier)
            source=json.loads(stored[0])
            digest=hashlib.sha256((DATA/source['path']).read_bytes()).hexdigest()
            assert digest==source['sha256']==pap['sources'][mission],mission
        rollups=list(db.execute("SELECT stage,measure,path,cents FROM reconciled_totals WHERE year=2026 AND budget='BG' AND stage IN ('PLF','FDC_PREVU')"))
        assert len(rollups)==pap['mission_totals_checked']==110
        for stage,measure,mission,total in rollups:
            actual=db.execute("""SELECT sum(cents) FROM facts WHERE year=2026 AND budget='BG'
                AND stage=? AND measure=? AND mission=? AND action='' AND subaction=''""",(stage,measure,mission)).fetchone()[0]
            assert actual==total,(mission,stage,measure,actual,total)
        pap2026={'sources_verified':len(source_pairs),'observations':pap_facts,
                 'programme_checks':pap['programmes_checked'],'mission_totals':len(rollups),
                 'blank_cells_converted_to_zero':False,'duplicate_programme_facts':duplicates}
    # Independently re-check the derived national RAP action registry. It does not
    # replace canonical facts: every group must still match its complete parent
    # rows, reconcile to the published programme total and point to the exact PDF.
    national=json.loads((Path(__file__).parent/'data/actions-national.json').read_text(encoding='utf-8'))
    groups=national['groups']
    group_keys=[tuple(g[k] for k in ('year','stage','measure','budget','mission','program')) for g in groups]
    assert len(groups)==1401 and len(group_keys)==len(set(group_keys))
    source_ids=set();action_count=0;subaction_count=0;programme_years=set();mission_years=set()
    for group in groups:
        if group.get('review_required'):
            assert not group['reconciliation']['accepted'] and group['reconciliation_note']
            assert abs(group['reconciliation']['difference_cents'])>1000
        else:validate_action(group)
        where=(group['year'],group['stage'],group['measure'],group['budget'],group['mission'],group['program'])
        columns=('year','stage','measure','budget','mission','mission_label','program','program_label',
                 'action','action_label','subaction','subaction_label','category','title','cents','source',
                 'line','field','approximate')
        actual=[dict(zip(columns,row)) for row in db.execute("""SELECT year,stage,measure,budget,mission,mission_label,
            program,program_label,action,action_label,subaction,subaction_label,category,title,cents,source,
            line,field,approximate FROM facts WHERE year=? AND stage=? AND measure=? AND budget=? AND mission=?
            AND program=? AND action='' AND subaction='' ORDER BY source,line,title""",where)]
        expected=sorted(group['parents'],key=lambda r:(r['source'],r['line'],r['title']))
        assert actual==expected,(where,'parent_rows')
        parent_cents=sum(r['cents'] for r in actual)
        assert group['published_total_euros']*100-parent_cents==group['published_total_minus_parent_cents'],where
        action_cents=sum(detail_cents(a) for a in group['actions'])
        if group.get('action_reconstruction'):
            rec=group['action_reconstruction']
            for proof in (rec['scope_proof'],rec['title2_parent']):check_source(proof['source'],proof['sha256'])
            proof=rec['title2_parent'];source=check_source(proof['source'],proof['sha256'])
            csv_rows=read_table(source);raw=dict(zip(csv_rows[0],csv_rows[proof['row']-1]))
            assert raw==proof['raw_columns'] and raw[proof['field']]==proof['raw_value']
            assert original_cents(raw[proof['field']])==proof['cents']
        assert action_cents-parent_cents==group['action_sum_minus_parent_cents'],where
        assert all(a['code'] and a['label'].strip() and a.get('page',group['page'])>0 for a in group['actions']),where
        for action in group['actions']:
            children=action.get('subactions',[])
            if children:
                validate_action_subactions(group,action)
                assert all(i['code'] and i['label'].strip() and i.get('page',group['page'])>0 for i in children),(where,action['code'])
            subaction_count+=len(children)
        action_count+=len(group['actions'])
        programme_years.add((group['year'],group['mission'],group['program']))
        mission_years.add((group['year'],group['mission']))
        source_ids.add(group['source'])
    assert (action_count,subaction_count,len(programme_years),len(mission_years))==(7120,2770,351,94)
    for identifier in source_ids:
        stored=db.execute('SELECT data FROM sources WHERE id=?',(identifier,)).fetchone()
        assert stored,identifier
        source=json.loads(stored[0])
        digests={g['sha256'] for g in groups if g['source']==identifier}
        assert digests=={source['sha256']},identifier
        assert hashlib.sha256((DATA/source['path']).read_bytes()).hexdigest()==source['sha256'],identifier
    rap_actions_national={'groups':len(groups),'accepted_groups':sum(not g.get('review_required',False)for g in groups),
                          'review_required_groups':sum(bool(g.get('review_required'))for g in groups),
                          'subaction_branches_requiring_review':[dict(year=g['year'],program=g['program'],stage=g['stage'],measure=g['measure'],action=a['code'],difference_cents=a['subactions_review']['difference_cents'])
                              for g in groups for a in g['actions'] if a.get('subactions_review',{}).get('status')=='review_required'],
                          'documented_reconstructions':[dict(year=g['year'],program=g['program'],stage=g['stage'],measure=g['measure'],action=g['action_reconstruction']['action'],published_total_cents=g['published_total_euros']*100,reconstructed_action_cents=g['action_reconstruction']['amount_cents'],action_sum_cents=g['action_reconstruction']['action_sum_cents'],difference_cents=g['action_sum_minus_parent_cents'],sources_verified=3) for g in groups if g.get('action_reconstruction')],
                          'actions':action_count,'subactions':subaction_count,
                          'programme_years':len(programme_years),'mission_years':len(mission_years),
                          'source_hashes_verified':len(source_ids),'canonical_facts_rewritten':False}
    movements=json.loads((Path(__file__).parent/'data/mouvements-rap-national.json').read_text(encoding='utf-8'))
    movement_registries=movements['registries']
    movement_keys=[(r['scope']['years'][0],r['scope']['mission'],r['scope']['program']) for r in movement_registries]
    assert len(movement_registries)==354 and len(movement_keys)==len(set(movement_keys))
    assert not any(m=='TA' and p=='174' for _,m,p in movement_keys)
    movement_sources=set();movement_items=0;movement_evidence=0;movement_tables=0
    for registry in movement_registries:
        validate_movements(registry)
        scope=registry['scope'];year=scope['years'][0]
        assert all(row['year']==year and row['mission']==scope['mission'] and row['program']==scope['program'] for row in registry['items'])
        assert len(registry['items'])==len({row['id'] for row in registry['items']})
        assert {row['measure'] for row in registry['reconciliations']}=={'AE','CP'}
        for row in registry['reconciliations']:
            for stage,field in [('LFI','lfi_cents'),('OUVERT','canonical_cents')]:
                actual=db.execute("SELECT sum(cents) FROM facts WHERE year=? AND budget='BG' AND mission=? AND program=? AND measure=? AND stage=? AND action='' AND subaction=''",
                    (year,scope['mission'],scope['program'],row['measure'],stage)).fetchone()[0]
                assert actual==row[field],(scope,stage,row['measure'],actual,row[field])
        assert all(len(row['cells'])==8 for row in registry['evidence_rows'])
        movement_items+=len(registry['items']);movement_evidence+=len(registry['evidence_rows'])
        movement_tables+=len(registry['table_totals'])
        movement_sources.update(source['id'] for source in registry['sources'])
    assert (movement_items,movement_evidence,movement_tables,len(movement_sources))==(10451,4798,2323,96)
    for identifier in movement_sources:
        stored=db.execute('SELECT data FROM sources WHERE id=?',(identifier,)).fetchone()
        assert stored,identifier
        source=json.loads(stored[0])
        expected={item['sha256'] for registry in movement_registries for item in registry['sources'] if item['id']==identifier}
        assert expected=={source['sha256']},identifier
        assert hashlib.sha256((DATA/source['path']).read_bytes()).hexdigest()==source['sha256'],identifier
    rap_movements_national={'programme_years':len(movement_registries),'items':movement_items,
                            'evidence_rows':movement_evidence,'table_totals':movement_tables,
                            'source_hashes_verified':len(movement_sources),'canonical_facts_rewritten':False}
    reserves_national=json.loads((Path(__file__).parent/'data/reserves-national.json').read_text(encoding='utf-8'))
    reserve_records=reserves_national['records']
    reserve_keys={(r['year'],r['mission'],r['program'],r['measure']) for r in reserve_records}
    reserve_sources={r['source'] for r in reserve_records}
    assert len(reserve_records)==len(reserve_keys)==606 and len({k[:3] for k in reserve_keys})==303
    assert len(reserve_sources)==85
    for row in reserve_records:
        validate_reserve(row)
        assert db.execute("SELECT count(*) FROM facts WHERE year=? AND budget='BG' AND mission=? AND program=?",
                          (row['year'],row['mission'],row['program'])).fetchone()[0]>0,(row['year'],row['mission'],row['program'])
    for identifier in reserve_sources:
        stored=db.execute('SELECT data FROM sources WHERE id=?',(identifier,)).fetchone()
        assert stored,identifier
        source=json.loads(stored[0])
        assert {r['source_sha256'] for r in reserve_records if r['source']==identifier}=={source['sha256']},identifier
        assert hashlib.sha256((DATA/source['path']).read_bytes()).hexdigest()==source['sha256'],identifier
    rap_reserves_national={'programme_years':303,'records':len(reserve_records),
                           'arithmetic_checks':sum(len(r['checks']) for r in reserve_records),
                           'source_hashes_verified':len(reserve_sources),'canonical_facts_rewritten':False}
    topic=json.loads((Path(__file__).parent/'data/maprimerenov.json').read_text(encoding='utf-8'))
    mpr2025=[r for r in topic['facts'] if (r['year'],r['stage'],r['measure'])==(2025,'PLF','CP')]
    expected_mpr2025={('TA','174'):0,('PR','362'):0,('VA','135'):137800000000}
    assert len(mpr2025)==3
    assert {(r['mission'],r['program']):r['cents'] for r in mpr2025}==expected_mpr2025
    assert all(r['source']=='0bda7f84a57258b9143c' and r['page']==18
               and r['published_unit']=='M€' and r['precision']=='1 M€' for r in mpr2025)
    mpr_coverage=[r for r in topic['coverage']
                  if (r['year'],r['stage'],r['measure'])==(2025,'PLF','CP')]
    assert len(mpr_coverage)==1 and set(mpr_coverage[0]['paths'])=={'TA/174','PR/362','VA/135'}
    mpr_source_id='0bda7f84a57258b9143c'
    stored=db.execute('SELECT data FROM sources WHERE id=?',(mpr_source_id,)).fetchone()
    assert stored,mpr_source_id
    mpr_source=json.loads(stored[0])
    assert mpr_source['sha256']=='b5e07637ba4a60d3cbab583f3bf0edd6524c03306efdbcc7d3844c872cc8a1a9'
    assert hashlib.sha256((DATA/mpr_source['path']).read_bytes()).hexdigest()==mpr_source['sha256']
    mpr2025_plf_cp_checks={'facts':len(mpr2025),'national_cp_cents':sum(r['cents'] for r in mpr2025),
                           'programmes':3,'published_zero_programmes':2,
                           'source_hashes_verified':1,'blank_cells_converted_to_zero':False,
                           'canonical_facts_rewritten':False}
    from .audit_registries import run as audit_all_registries
    all_registries=audit_all_registries(db,check_source)
    report={'built_at':meta['built_at'],'checked_at':datetime.now(timezone.utc).isoformat(),'success':True,'fact_count':meta['fact_count'],
            'data_signature':signature(DATA/'derived/budget.sqlite'),'all_registries':all_registries,
            'documented_fact_corrections':len(meta.get('recent_reconciliation_corrections',{}).get('fact_replacements',[]))+len(meta.get('recent_reconciliation_corrections',{}).get('fact_insertions',[])),
            'historical_canonical_facts':historical_canonical,
            'source_hashes_verified':files,'mission_reconciliations_2024_2025':len(checks),'programme_105_examples':4,
            'remaining_source_notes':dict(Counter(i['kind'] for i in meta['issues'])),'pap2026_national_checks':pap2026,
            'rap_actions_national_checks':rap_actions_national,'rap_movements_national_checks':rap_movements_national,'rap_reserves_national_checks':rap_reserves_national,'mpr2025_plf_cp_checks':mpr2025_plf_cp_checks,'checks':checks}
    Path(os.environ.get('BUDGET_AUDIT_OUTPUT',str(DATA/'derived/data-audit.json'))).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
    db.close()

if __name__=='__main__':main()

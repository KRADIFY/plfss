"""Release-wide checks, including legacy pilot and historical registries."""
import json
from . import action_details,reserves,rap_movements,rap_quality
from .rap_validation import validate_action,validate_reserve,validate_movements
from .reconciliation import assess_difference,capped_rounding_bound,published_cents


def run(db,check_source):
    accepted=0;pending=[]
    for group in action_details.registry()[0]['groups']:
        parents=group.get('parents')or[group['parent']]
        key=tuple(group[k]for k in ('year','stage','measure','budget','mission','program'))
        rows=[dict(r)for r in db.execute("SELECT * FROM facts WHERE year=? AND stage=? AND measure=? AND budget=? AND mission=? AND program=? AND action='' AND subaction=''",key)]
        assert sorted(rows,key=lambda x:json.dumps(x,sort_keys=True))==sorted(parents,key=lambda x:json.dumps(x,sort_keys=True)),(key,'action parents changed')
        check_source(group['source'],group['sha256'])
        if group.get('review_required'):
            assessment=assess_difference(published_cents(group),sum(r['cents']for r in parents))
            assert not assessment['accepted'] and group['reconciliation_note']
            attached=action_details.attach([dict(r)for r in parents],db)
            scope=group['mission']+'/'+group['program']
            resolved=list(action_details.resolve(attached,scope+'/'+group['actions'][0]['code'],[]))
            if action_details.published_disagreement(group):
                assert any(r['action'] and r.get('_source_disagreement') for r in resolved), 'Reviewed RAP action missing its alert'
            else:
                assert any(r.get('_detail_review_required') for r in attached)
                assert not any(r['action'] for r in resolved), 'Unreviewed action was usable'
            pending.append(dict(year=group['year'],program=group['program'],stage=group['stage'],measure=group['measure'],difference_cents=assessment['difference_cents'],
                                displayed_with_alert=action_details.published_disagreement(group)))
        else:validate_action(group);accepted+=1
    reserve_rows=reserves.registry()['records']
    for row in reserve_rows:validate_reserve(row);check_source(row['source'],row['source_sha256'])
    historical_bg=rap_movements.historical_detail_registry()['registries']
    historical_other=rap_movements.other_budget_historical_registry()['registries']
    historical=historical_bg+historical_other
    annual=rap_movements.historical_registry()['registries']
    detailed_by_key={(r['scope']['years'][0],r['scope']['budget'],r['scope']['mission'],r['scope']['program']):r for r in historical}
    reference_fallbacks=0;partial_annual=[];annual_adjustments_checked=0
    for reg in historical+annual:
        validate_movements(reg)
        for source in reg['sources']:check_source(source['id'],source['sha256'])
        scope=reg['scope']
        for adjustment in reg.get('annual_adjustments',[]):
            check_source(adjustment['source'],adjustment['sha256'])
            annual_adjustments_checked+=1
        if reg.get('source_validation',{}).get('independent_annual_reference_check') is False:
            assert reg['source_validation']['publication_basis']=='source_rows_and_independent_printed_totals_only'
            assert scope['budget']=='BA'
            for rec in reg['reconciliations']:
                assert rec['status']=='annual_reference_unavailable' and rec['canonical_cents'] is None and rec['difference_cents'] is None
                actual=db.execute("SELECT sum(cents) FROM facts WHERE year=? AND stage='OUVERT' AND measure=? AND budget=? AND program=?",(rec['year'],rec['measure'],scope['budget'],scope['program'])).fetchone()[0]
                assert actual is None,(scope,rec['measure'],'annual source now exists: review the partial register')
            partial_annual.append(dict(years=scope['years'],budget=scope['budget'],mission=scope['mission'],program=scope['program'],
                status='source_tables_verified_annual_reference_unavailable',items=len(reg['items'])))
            continue
        for rec in reg['reconciliations']:
            for stage,field in [('LFI','lfi_cents'),('OUVERT','canonical_cents')]:
                actual=db.execute("SELECT sum(cents) FROM facts WHERE year=? AND stage=? AND measure=? AND budget=? AND mission=? AND program=?",(rec['year'],stage,rec['measure'],scope['budget'],scope['mission'],scope['program'])).fetchone()[0]
                if actual is None:
                    # Superseded annual records may use the same explicit RAP
                    # reference as their newer dated registry, never an inferred zero.
                    detailed=detailed_by_key.get((rec['year'],scope['budget'],scope['mission'],scope['program']),{})
                    proofs=reg.get('source_validation',{}).get('reference_fallback_proofs',[])+detailed.get('source_validation',{}).get('reference_fallback_proofs',[])
                    proof=next((r for r in proofs if r['stage']==stage and r['measure']==rec['measure'] and r['source']==rec['source']),None)
                    assert proof and proof['amount_cents']==rec[field] and proof['page']>0 and proof.get('canonical_fact_missing'),(scope,stage,rec['measure'],'missing fallback proof')
                    check_source(proof['source'],proof['sha256']);reference_fallbacks+=1
                else:assert actual==rec[field],(scope,stage,rec['measure'],actual,rec[field])
    pilot=rap_movements.registry();items={r['id']:r for r in pilot['items']}
    for source in pilot['sources']:check_source(source['id'],source['sha256'])
    for rec in pilot['reconciliations']:
        selected=([r for r in items.values()if (r['year'],r['measure'])==(rec['year'],rec['measure'])]
                  if rec['stage']=='OUVERT' else [items[i]for i in rec['item_ids']])
        canonical=db.execute("SELECT sum(cents) FROM facts WHERE year=? AND stage=? AND measure=? AND budget='BG' AND mission='TA' AND program='174' AND action='' AND subaction=''",(rec['year'],rec['stage'],rec['measure'])).fetchone()[0]
        assert canonical==rec['canonical_cents']
        if rec['reported_net_cents'] is None:
            assert not selected and rec['difference_cents'] is None and rec['status']=='no_rows_in_rap_not_zero'
            continue
        actual=sum(r['sign']*r['amount_cents']for r in selected)
        assert actual==rec['reported_net_cents']
        if rec['stage']=='OUVERT':
            lfi=db.execute("SELECT sum(cents) FROM facts WHERE year=? AND stage='LFI' AND measure=? AND budget='BG' AND mission='TA' AND program='174'",(rec['year'],rec['measure'])).fetchone()[0]
            assert lfi==rec['lfi_cents'];actual+=lfi
            assert actual==rec['lfi_plus_reported_cents']
        assert actual-rec['canonical_cents']==rec['difference_cents']
        assert assess_difference(actual,rec['canonical_cents'],len(selected))['accepted']
    for total in pilot['table_totals']:
        selected=[r for r in pilot['evidence_rows']if r['year']==total['year'] and(total['is_grand_total']or r['table_id']==total['table_id'])]
        assert selected
        for i,cell in enumerate(total['cells']):
            values=[r['cells'][i]['amount_cents']for r in selected if r['cells'][i]['amount_cents']is not None]
            assert abs((cell['amount_cents']or 0)-sum(values))<=capped_rounding_bound(len(values),0)
    documentary=rap_quality.registry()[0]
    for source in documentary['sources']:check_source(source['id'],source['sha256'])
    coverage_counts=rap_movements.historical_validation_counts()
    integrated_historical=[r for r in rap_movements._all_registries() if all(y<=2022 for y in r['scope']['years'])]
    integrated_keys=[key for r in integrated_historical for key in rap_movements._registry_keys(r)]
    assert len(integrated_keys)==len(set(integrated_keys))
    assert coverage_counts['detailed_without_annual_reference']==len(partial_annual)
    assert coverage_counts['detailed_reconciled']+coverage_counts['detailed_without_annual_reference']+coverage_counts['annual_only']==len(integrated_keys)
    return dict(accepted_action_groups=accepted,action_groups_requiring_review=pending,
        documentary_sources_checked=len(documentary['sources']),documentary_investigations=len(documentary.get('investigations',[])),
        reserve_observations_checked=len(reserve_rows),historical_movement_programme_years=len(historical_bg),
        other_budget_historical_movement_programme_years=len(historical_other),
        other_budget_historical_fully_reconciled=len(historical_other)-len(partial_annual),
        historical_movement_annual_reference_unavailable=partial_annual,
        historical_integrated_coverage=coverage_counts,historical_unique_programme_years=len(integrated_keys),
        annual_movement_registries_checked=len(annual),explicit_source_fallback_references=reference_fallbacks,
        historical_annual_adjustments_checked=annual_adjustments_checked,
        pilot_reconciliations_checked=len(pilot['reconciliations']))

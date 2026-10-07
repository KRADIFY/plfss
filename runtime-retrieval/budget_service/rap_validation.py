"""Independent arithmetic checks for published RAP registries, in integer cents."""
import re
from decimal import Decimal
from .reconciliation import assess_difference, capped_rounding_bound, action_cents, published_cents

def validate_action_subactions(group,action):
    """A contradictory retained branch is evidence only, with two exact source cells."""
    children=action.get('subactions',[])
    review=action.get('subactions_review')
    if not review:
        assert not children or sum(action_cents(a) for a in children)==action_cents(action)
        return
    assert children and review['status']=='review_required' and review['accepted'] is False
    assert review['cause']=='inconsistent_published_action_presentations' and review['note']
    assert review['derived_subaction_replacement_allowed'] is False
    assert review['source']==group['source'] and review['sha256']==group['sha256']
    assert review['original_subactions']==children
    original=group['source_correction_review']['original_group']
    assert original['source']==group['source'] and original['sha256']==group['sha256']
    prior=next(a for a in original['actions'] if a['code']==action['code'])
    assert prior['subactions']==children
    published=action_cents(dict(euros=review['published_parent_euros']))
    retained=action_cents(dict(euros=review['reviewed_parent_euros']))
    assert published==sum(action_cents(a) for a in children)==action_cents(prior)
    assert retained==action_cents(action)
    assert published-retained==review['difference_cents']
    assert not assess_difference(published,retained,len(children))['accepted']
    citations={(c['source'],c['page']) for c in review['citations']}
    cells=set()
    for proof in review['proofs']:
        assert proof['source']==group['source'] and proof['sha256']==group['sha256']
        assert proof['units']=='EUR' and type(proof['page']) is int and proof['page']>0
        assert len(proof['bbox'])==4 and proof['bbox'][0]<proof['bbox'][2] and proof['bbox'][1]<proof['bbox'][3]
        assert (proof['source'],proof['page']) in citations
        raw=re.sub(r'\s','',proof['raw_text'])
        assert re.fullmatch(r'[+-]?\d+(?:,\d{1,2})?',raw)
        cells.add((proof['page'],int(Decimal(raw.replace(',','.'))*100)))
    assert (action['page'],retained) in cells and (prior['page'],published) in cells
    assert action['page']!=prior['page']

def validate_action_reconstruction(group):
    """Only the reviewed, explicit P224 scope identity permits this reconstruction.

    The RAP total remains a distinct, unreconciled publication. No difference is
    allocated: the canonical title-2 fact is added to the printed action HT2 cell.
    """
    rec=group['action_reconstruction'];original=rec['original_group']
    keys=('year','stage','measure','budget','mission','program')
    assert tuple(group[k] for k in keys)==(2023,'EXEC','AE','BG','CB','224')
    assert all(rec[k]==group[k]==original[k] for k in keys)
    assert rec['status']=='validated_documented_identity'
    assert rec['method']=='single_action_title2_plus_published_ht2' and rec['action']=='07'
    assert rec['canonical_facts_rewritten'] is False and group.get('review_required') is False
    for key in ('parents','source','sha256','published_total_euros','published_total_minus_parent_cents','reconciliation'):
        assert group[key]==original[key],key
    assert not group['reconciliation']['accepted']
    assert 'published_total_cents' not in group
    assert [a['code'] for a in group['actions']]==[a['code'] for a in original['actions']]==['06','07']
    assert all(not a.get('subactions') for a in group['actions'])
    scope=rec['scope_proof']
    assert (scope['source'],scope['sha256'],scope['page'])==('5fe28bfb37bca3a29b3d','efa6d4687e4f200abf58419ae94aec2d85d69f03e1cb390cf8a14619b3771fd1',291)
    assert (scope['year'],scope['program'],scope['action'],scope['title'],scope['kind'])==(2023,'224','07','2','explicit_accounting_scope')
    assert scope['raw_text']==('La totalité des emplois et crédits de titre 2 du ministère est regroupée sur le seul programme 224 « Soutien aux politiques du ministère de la culture » et sur la seule action 07 « Fonctions de soutien du ministère ».')
    assert scope['bboxes'] and all(len(b)==4 and b[0]<b[2] and b[1]<b[3] for b in scope['bboxes'])
    parents=group['parents'];assert len(parents)==2 and {p['title'] for p in parents}=={'2','HT2'}
    assert all(not p['action'] and not p['subaction'] and not p['category'] for p in parents)
    title2=next(p for p in parents if p['title']=='2');csv=rec['title2_parent']
    assert all(csv[k]==title2[k] for k in ('source','field','title','year','program','stage','measure','cents'))
    assert csv['row']==title2['line'] and csv['units']=='EUR'
    assert csv['source']=='6f9032fe6759bc16a73a' and csv['sha256']=='f266d080eacdd1534f13d59b13420a98b3ceab0773042b0fcccf0523d1c77813'
    assert csv['raw_columns'][csv['field']]==csv['raw_value']
    assert re.fullmatch(r'\d+(?:,\d{1,2})?',csv['raw_value'])
    assert Decimal(csv['raw_value'].replace(',','.'))*100==csv['cents']
    components=rec['ht2_components'];assert [c['action'] for c in components]==['06','07']
    for proof in components+[rec['printed_title2']]:
        assert proof['source']==group['source'] and proof['sha256']==group['sha256']
        assert (proof['page'],proof['year'],proof['program'],proof['stage'],proof['measure'],proof['units'])==(426,2023,'224','EXEC','AE','EUR')
        assert len(proof['bbox'])==4 and proof['bbox'][0]<proof['bbox'][2] and proof['bbox'][1]<proof['bbox'][3]
        raw=re.sub(r'\s','',proof['raw_text']);assert re.fullmatch(r'\d+',raw)
        assert int(raw)*100==proof['amount_cents']
    assert all(c['title']=='HT2' and c['column']=='Autorisations d’engagement · Consommation · Autres titres' for c in components)
    printed=rec['printed_title2'];assert (printed['action'],printed['title'])==('07','2')
    assert group['actions'][0]==original['actions'][0]
    assert action_cents(original['actions'][0])==components[0]['amount_cents']
    assert action_cents(original['actions'][1])==printed['amount_cents']+components[1]['amount_cents']
    assert sum(action_cents(a) for a in original['actions'])==published_cents(original)
    action=group['actions'][1]
    expected=dict(original['actions'][1]);expected.pop('euros');expected.update(cents=rec['amount_cents'],page=426,amount_kind='reconstructed')
    assert action==expected
    assert type(action['cents']) is int and rec['amount_cents']==csv['cents']+components[1]['amount_cents']
    total=sum(action_cents(a) for a in group['actions']);parent=sum(p['cents'] for p in parents)
    assert rec['action_sum_cents']==total and rec['unallocated_residual_cents']==parent-total
    assert group['action_reconciliation']==assess_difference(total,parent,len(group['actions']))
    assert group['action_reconciliation']['accepted']
    assert rec['citations']==[dict(source=scope['source'],page=291),dict(source=group['source'],page=426),dict(source=csv['source'],page=None,line=csv['row'],field=csv['field'])]
    money=lambda v:f'{v//100:,}'.replace(',',' ')+f',{v%100:02d}'
    assert rec['formula']==f"{money(csv['cents'])} € (titre 2 du programme, annexe PLRG) + {money(components[1]['amount_cents'])} € (HT2 de l’action 07, RAP p. 426) = {money(action['cents'])} €"
    assert group.get('reconciliation_note')
    return rec


def validate_action(group):
    parent=sum(r['cents'] for r in (group.get('parents') or [group['parent']]))
    published=published_cents(group)
    actions=sum(action_cents(a) for a in group['actions'])
    assert published-parent==group.get('published_total_minus_parent_cents',published-parent)
    assert actions-parent==group['action_sum_minus_parent_cents']
    if group.get('action_reconstruction'):
        validate_action_reconstruction(group)
    else:
        assert assess_difference(published,parent)['accepted']
        assert abs(actions-published)<=capped_rounding_bound(len(group['actions']))
    assert assess_difference(actions,parent,len(group['actions']))['accepted']
    assert group['actions'] and len({a['code'] for a in group['actions']})==len(group['actions'])
    for action in group['actions']:validate_action_subactions(group,action)
    if assess_difference(published,parent)['status']=='source_difference':
        assert group.get('reconciliation_note') and group['reconciliation']['status']=='source_difference'

def validate_annual_adjustments(registry):
    """Annual AE recycling is a separate, sourced amount, never a dated RAP row."""
    adjustments=registry.get('annual_adjustments',[])
    assert len({a['id'] for a in adjustments})==len(adjustments)
    sources={s['id']:s['sha256'] for s in registry['sources']}
    scope=registry['scope']; totals={}
    for adjustment in adjustments:
        assert adjustment['kind']=='AE_RECYCLING' and adjustment['measure']=='AE'
        assert adjustment['date'] is None and adjustment['date_precision']=='annual'
        assert adjustment['year'] in scope['years'] and adjustment['budget']=='BA'
        assert all(adjustment[k]==scope[k] for k in ('budget','mission','program'))
        assert type(adjustment['amount_cents']) is int and adjustment['amount_cents']>0
        assert adjustment['sign']==1 and adjustment.get('note') and adjustment.get('field')
        assert adjustment['source'] in sources and adjustment['sha256']==sources[adjustment['source']]
        assert type(adjustment['page']) is int and adjustment['page']>0
        proof=adjustment['proof'];cell=proof['selected_total_cell']
        assert all(proof[k]==adjustment[k] for k in ('source','sha256','page','year','budget','program','measure','field'))
        assert proof['origin']=='independent_PLR_annex2_recycled_AE'
        assert proof['source_grain']=='programme_total_all_titles' and proof['source_units']=='EUR'
        assert proof['amount_cents']==cell['amount_cents']==adjustment['amount_cents']
        assert proof['cells']==[cell] and len(cell['bbox'])==4 and len(proof['bbox'])==4
        assert proof.get('program_headers') and proof.get('document_year_proof')
        headers=proof['column_header_cells']
        heading=' '.join(h['text'].lower() for h in headers)
        assert ('recyclage' in heading and 'ae' in heading) or ('reprise' in heading and 'engagement' in heading)
        assert all(len(h['bbox'])==4 for h in headers)
        bounds=cell['visual_column_bounds'];b=cell['display_bbox']
        assert bounds[0]<=b[0]<b[2]<=bounds[1]
        assert all(bounds[0]<=h['display_bbox'][0]<h['display_bbox'][2]<=bounds[1] for h in headers)
        token=re.sub(r'\s+','',cell['raw_text'])
        assert re.fullmatch(r'\d+(?:,\d{2})?',token)
        assert int(Decimal(token.replace(',','.'))*100)==adjustment['amount_cents']
        key=(adjustment['year'],adjustment['measure'])
        assert key not in totals, 'Only one independently printed programme recycling total per year'
        totals[key]=adjustment['amount_cents']
    return totals


def validate_movements(registry):
    rows=registry['evidence_rows'];totals=registry['table_totals'];items=registry['items']
    grands=[t for t in totals if t['is_grand_total']]
    assert len(grands)==1
    assert len({r['row_id'] for r in rows})==len(rows)
    assert len({r['table_id'] for r in totals})==len(totals)
    # Reconstruct the observations from the eight original cells, including
    # explicit zeroes while omitting empty cells.
    expected={(r['row_id'],c['measure'],c['title'],c['direction']):c
              for r in rows for c in r['cells'] if c['amount_cents'] is not None}
    actual={(x['row_id'],x['measure'],x['title'],'opening' if x['sign']==1 else 'cancellation'):x for x in items}
    assert len(actual)==len(items) and set(actual)==set(expected)
    for k,c in expected.items():
        assert actual[k]['sign']==c['sign'] and actual[k]['amount_cents']==c['amount_cents']>=0
    for total in totals:
        selected=rows if total['is_grand_total'] else [r for r in rows if r['table_id']==total['table_id']]
        assert selected
        assert len(total['cells'])==8
        for i,cell in enumerate(total['cells']):
            amounts=[r['cells'][i]['amount_cents'] for r in selected if r['cells'][i]['amount_cents'] is not None]
            difference=(cell['amount_cents'] or 0)-sum(amounts)
            assert abs(difference)<=(capped_rounding_bound(len(amounts),0) if amounts else 0)
    assert {c['measure'] for c in registry['reconciliations']}=={'AE','CP'}
    annual_adjustments=validate_annual_adjustments(registry)
    partial=registry.get('source_validation',{}).get('independent_annual_reference_check') is False
    if partial:
        assert not annual_adjustments
        validation=registry['source_validation']
        assert validation.get('publication_basis')=='source_rows_and_independent_printed_totals_only'
        assert all(validation.get(k) is True for k in ('independent_printed_totals','all_table_boundaries_classified','continuations_included'))
        sources={s['id']:s['sha256'] for s in registry['sources']}
        assert sources and all(len(k)==20 and len(v)==64 for k,v in sources.items())
        for obj in rows+totals+items:
            assert obj['source'] in sources and obj['sha256']==sources[obj['source']]
            assert type(obj['page']) is int and obj['page']>0
            assert obj['budget']==registry['scope']['budget'] and obj['program']==registry['scope']['program']
        table_by_id={t['table_id']:t for t in totals if not t['is_grand_total']}
        hierarchy=validation.get('column_hierarchy_proofs',[])
        assert len(hierarchy)==len(totals) and {h['table_id'] for h in hierarchy}=={t['table_id'] for t in totals}
        label=lambda text:' '.join(text.lower().replace('’',"'").split())
        for total in totals:
            proof=next(h for h in hierarchy if h['table_id']==total['table_id'])
            assert proof['page']==total['page'] and proof['title_headers']==total['headers']
            assert [label(h['text']) for h in proof['direction_headers']]==['ouvertures','annulations']
            assert [label(h['text']) for h in proof['measure_headers']]==["autorisations d'engagement",'crédits de paiement']*2
            assert [label(h['printed_label']) for h in total['headers']]==['titre 2','autres titres']*4
            assert any(c['amount_cents'] is not None for c in total['cells'])
            for i,c in enumerate(total['cells']):
                assert (c['measure'],c['title'],c['sign'])==('AE' if (i//2)%2==0 else 'CP','2' if i%2==0 else 'HT2',1 if i<4 else -1)
        for row in rows:
            assert row['table_id'] in table_by_id and row['kind']==table_by_id[row['table_id']]['kind']
            assert row.get('source_date') and row.get('date')
            for i,c in enumerate(row['cells']):
                assert (c['measure'],c['title'],c['sign'])==('AE' if (i//2)%2==0 else 'CP','2' if i%2==0 else 'HT2',1 if i<4 else -1)
        by_row={r['row_id']:r for r in rows}
        for item in items:
            source_row=by_row[item['row_id']]
            assert all(item[k]==source_row[k] for k in ('kind','date','source','sha256','page','reconciles_stage'))
        for check in registry['reconciliations']:
            assert check['status']=='annual_reference_unavailable' and check['canonical_cents'] is None and check['difference_cents'] is None
            assert check.get('canonical_reference_sql_fact') is False and check.get('note')
            assert not any(check.get(k) is not None for k in ('lfi_plus_reported_cents','printed_difference_cents'))
        return
    for check in registry['reconciliations']:
        chosen=[x for x in items if x['measure']==check['measure']]
        net=sum(x['sign']*x['amount_cents'] for x in chosen)
        annual=annual_adjustments.get((check['year'],check['measure']),0)
        assert check.get('annual_adjustment_cents',0)==annual
        if annual:
            expected_ids=[a['id'] for a in registry['annual_adjustments'] if (a['year'],a['measure'])==(check['year'],check['measure'])]
            assert check['annual_adjustment_ids']==expected_ids
            assert check['reconciled_total_cents']==check['lfi_cents']+net+annual
            assert check['lfi_plus_reported_cents']==check['lfi_cents']+net
        delta=check['lfi_cents']+net+annual-check['canonical_cents']
        assert net==check['reported_net_cents'] and delta==check['difference_cents']
        assessment=assess_difference(check['lfi_cents']+net+annual,check['canonical_cents'],len(chosen))
        assert assessment['accepted'] and assessment['status']==check['status']
        cells=[c for c in grands[0]['cells'] if c['measure']==check['measure'] and c['amount_cents'] is not None]
        printed=sum(c['sign']*c['amount_cents'] for c in cells)
        assert printed==check['printed_net_cents']
        assert assess_difference(check['lfi_cents']+printed+annual,check['canonical_cents'],len(cells))['accepted']
        if delta:assert check.get('note')

def validate_reserve(row):
    assert {'initial','surgels','degels','remaining'} <= row['cells'].keys()
    differences=[]
    for field,cell in row['cells'].items():
        assert cell['total_cents'] is not None
        delta=cell['total_cents']-sum(cell[k] or 0 for k in ('title2_cents','other_titles_cents'))
        assert abs(delta)<=100,(field,delta)
        stored=next(c for c in row['checks'] if c['check']=='printed_columns' and c['field']==field)
        assert stored['difference_cents']==delta and stored['passed']==(delta==0)
        differences.append(delta)
    for column in ('title2_cents','other_titles_cents','total_cents'):
        if any(c[column] is None for c in row['cells'].values()):
            # A blank is not a published zero and cannot support a balance check.
            stored=next((c for c in row['checks'] if c['check']=='printed_balance' and c['field']==column),None)
            assert stored is None or (stored['difference_cents'] is None and not stored['passed'])
            continue
        delta=row['cells']['remaining'][column]-sum(c[column] for k,c in row['cells'].items() if k!='remaining')
        differences.append(delta)
        assert abs(delta)<=100
        stored=next(c for c in row['checks'] if c['check']=='printed_balance' and c['field']==column)
        assert stored['difference_cents']==delta and stored['passed']==(delta==0)
    if any(differences):
        assert row['numeric_validation'] in ('published_with_balance_difference','published_with_column_difference') and row['note']

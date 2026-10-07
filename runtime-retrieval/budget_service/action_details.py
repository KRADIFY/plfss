"""Reviewed RAP action totals, alongside (never added to) the original totals."""
import hashlib
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from .reconciliation import assess_difference, difference_note, action_cents, published_cents
from .rap_validation import validate_action


FILE = Path(__file__).parent / 'data/actions-p174.json'
NOTE = ('Les totaux de programme conservent leurs sources. Le détail par action ou sous-action '
        'conserve la précision du document : au centime dans les synthèses Excel, à l’euro dans les tableaux PDF. '
        'Aucun écart d’arrondi n’est réparti entre les actions.')

# Exception limitée aux 16 tableaux RAP contrôlés, jamais aux nouveaux écarts.
POLICY_VERSION = 'reviewed-disagreements-20260924'
PUBLISHED_DISAGREEMENTS = frozenset({
    (2023, 'EXEC', 'AE', 'BG', 'AB', '354'), (2023, 'EXEC', 'CP', 'BG', 'AB', '354'),
    (2023, 'EXEC', 'AE', 'BG', 'EC', '140'), (2023, 'EXEC', 'AE', 'BG', 'EC', '141'),
    (2023, 'EXEC', 'AE', 'BG', 'GA', '156'), (2023, 'EXEC', 'AE', 'BG', 'GA', '302'),
    (2023, 'EXEC', 'AE', 'BG', 'JA', '166'), (2023, 'EXEC', 'AE', 'BG', 'PR', '364'),
    (2023, 'EXEC', 'AE', 'BG', 'RA', '150'), (2023, 'EXEC', 'AE', 'BG', 'SB', '176'),
    (2023, 'EXEC', 'AE', 'BG', 'SE', '124'), (2023, 'EXEC', 'AE', 'BG', 'SF', '219'),
    (2023, 'EXEC', 'AE', 'BG', 'TR', '368'), (2024, 'EXEC', 'AE', 'BG', 'JA', '166'),
    (2024, 'EXEC', 'AE', 'BG', 'SB', '176'), (2025, 'EXEC', 'AE', 'BG', 'TB', '155'),
})


def published_disagreement(group):
    """Show reviewed RAP actions without accepting their sum as canonical."""
    if key(group) not in PUBLISHED_DISAGREEMENTS or not group.get('review_required'):
        return False
    canonical = sum(p['cents'] for p in (group.get('parents') or [group['parent']]))
    published = published_cents(group)
    actions = sum(action_cents(a) for a in group['actions'])
    return (bool(group.get('reconciliation_note')) and canonical != published
            and abs(actions-published) <= 100
            and abs(published-canonical) * 10000 <= abs(canonical) * 150)


def display_note(group):
    note=group.get('reconciliation_note','')
    if not published_disagreement(group):return note
    return (note.replace('Aucun rapprochement validé, aucun détail utilisé automatiquement dans les calculs ou exclusions.',
                         'Détail RAP affiché avec alerte ; total de référence inchangé.')
                .replace('Le détail AE reste à traiter séparément : aucune soustraction automatique au total AE de référence, aucun rapprochement validé.',
                         'Le détail AE du RAP est affiché avec alerte ; les exclusions soustraient ses montants au total AE de référence sans répartir l’écart.'))


def disagreement(group, parents):
    canonical = sum(p['cents'] for p in parents)
    published = published_cents(group)
    difference = published-canonical
    ratio = abs(difference)*100/abs(canonical)
    ratio_text = f'{ratio:.8f}'.replace('.', ',')
    cents = lambda value: f'{value/100:,.2f}'.replace(',', ' ').replace('.', ',')
    summary = (f'Écart entre sources : le total retenu pour le programme est {cents(canonical)} €. '
               f'Le RAP indique {cents(published)} € : la différence est de {cents(abs(difference))} €, '
               f'soit {ratio_text} % du total retenu. Le site garde le chiffre de référence pour le programme '
               'et les chiffres du RAP pour les actions ; il ne répartit pas cette différence entre elles.')
    citations = [dict(source=group['source'], page=group.get('total_page', group.get('page')))]
    citations += [dict(source=p['source'], page=p.get('page')) for p in parents]
    return dict(summary=summary, canonical_cents=canonical, rap_cents=published,
                difference_cents=difference, percentage=ratio,
                citations=list({(c['source'], c['page']): c for c in citations}.values()))


@lru_cache(maxsize=1)
def registry():
    raw = FILE.read_bytes()
    data = json.loads(raw)
    for name in ('actions-ecologie.json', 'actions-multititres.json', 'actions-sousactions.json', 'actions-national.json', 'actions-dette.json', 'actions-rap-historique.json'):
        extension = FILE.with_name(name)
        if not extension.exists():
            continue
        added = extension.read_bytes()
        data['groups'] += json.loads(added)['groups']
        raw += b'\0' + added
    years=sorted({g['year']for g in data['groups']})
    data['coverage'] = f'Détail des actions LFI/consommé AE/CP, {years[0]}–{years[-1]}, selon les sources publiées et rapprochées. Seize groupes RAP en désaccord sont affichés avec une alerte ; les autres détails non rapprochés restent indisponibles.'
    assert len({key(g) for g in data['groups']}) == len(data['groups']), 'Duplicate action detail group'
    return data, hashlib.sha256(raw).hexdigest()


def within(path, parent):
    return not parent or path == parent or path.startswith(parent + '/')


def path_of(row):
    return '/'.join(row[k] for k in ('mission', 'program', 'action', 'subaction') if row[k])


def key(row):
    return tuple(row[k] for k in ('year', 'stage', 'measure', 'budget', 'mission', 'program'))


def public_row(row):
    return {k: v for k, v in row.items() if not k.startswith('_')}


def published_row(item, base, group, level='action'):
    label = ('action ' + item['code']) if level == 'action' else ('action ' + base['action'] + ' · sous-action ' + item['code'])
    spreadsheet=group.get('source_format') in ('xls','xlsx')
    page=None if spreadsheet else item.get('page',group['page'])
    precision=('Montant publié au centime dans la synthèse RAP. ' if spreadsheet else 'Montant publié à l’euro dans le RAP. ')+display_note(group)
    row = dict(public_row(base), **{level: item['code'], level + '_label': item['label']},
               title='', category='', cents=action_cents(item),
               source=group['source'], line=item['line'] if spreadsheet else page, page=page,
               field=item['field'] if spreadsheet else f"{group['stage']} {group['measure']} {group['year']} · {label} · colonne Total (hors FdC/AdP prévus)",
               approximate=int((not spreadsheet and group['stage'] == 'EXEC') or bool(group.get('reconciliation',{}).get('difference_cents'))),
               precision=precision,
               _detail_note=NOTE+' '+display_note(group))
    if spreadsheet:row['source_location']=item['source_location']
    if item.get('amount_kind')=='reconstructed':
        rec=group['action_reconstruction']
        row['reconstruction']={k:rec[k] for k in ('method','formula','title2_parent','ht2_components','scope_proof','citations')}
        row['amount_kind']='reconstructed'
        row['precision']='Montant reconstitué. '+display_note(group)
        row['field']=f"{group['stage']} {group['measure']} {group['year']} · {label} · Montant reconstitué : titre 2 du programme + HT2 de l’action"

    if item.get('subactions'):
        row['_action_details'] = [published_row(s, row, group, 'subaction') for s in item['subactions']]
        comparison=assess_difference(sum(action_cents(s) for s in item['subactions']),action_cents(item),len(item['subactions']))
        review=item.get('subactions_review',{})
        if review.get('status')=='review_required' or not comparison['accepted']:
            note=review.get('note') or difference_note(comparison)
            row['_detail_review_required']=True
            row['_detail_note']=note
            row['precision']=precision+' '+note
            row['_detail_comparisons']=review.get('citations',[])
    return row


def attach(records, db):
    """Attach only to the complete, unchanged set of reviewed programme facts.

    A new canonical source, amount, grain, or changed PDF disables the detail until
    it has been reconciled again. The facts table is never rewritten.
    """
    data, _ = registry()
    groups = defaultdict(list)
    for row in records:
        groups[key(row)].append(row)
    for group in data['groups']:
        parents = groups.get(key(group), [])
        expected = group.get('parents') or [group['parent']]
        unmatched = list(parents)
        for wanted in expected:
            match = next((i for i, row in enumerate(unmatched) if all(row.get(k) == v for k, v in wanted.items())), None)
            if match is None:
                break
            unmatched.pop(match)
        else:
            match = True
        if len(parents) != len(expected) or unmatched or match is not True:
            continue
        entry = db.execute('SELECT data FROM sources WHERE id=?', (group['source'],)).fetchone()
        if not entry or json.loads(entry[0]).get('sha256') != group['sha256']:
            continue
        parent = parents[0]
        comparison=assess_difference(published_cents(group),sum(p['cents'] for p in parents))
        action_comparison=assess_difference(sum(action_cents(a) for a in group['actions']),sum(p['cents'] for p in parents),len(group['actions']))
        reconstructed=False
        if group.get('action_reconstruction'):
            try:
                validate_action(group)
                rec=group['action_reconstruction']
                for proof in (rec['scope_proof'],rec['title2_parent']):
                    stored=db.execute('SELECT data FROM sources WHERE id=?',(proof['source'],)).fetchone()
                    assert stored and json.loads(stored[0]).get('sha256')==proof['sha256']
                reconstructed=True
            except (AssertionError,KeyError,ValueError,TypeError,StopIteration):
                # Retain original programme facts when this reviewed identity is stale.
                continue
        show_disagreement=published_disagreement(group)
        needs_review=(bool(group.get('review_required')) or (not reconstructed and not comparison['accepted']) or not action_comparison['accepted']) and not show_disagreement
        if comparison['status']=='source_difference' or needs_review or reconstructed:
            note=display_note(group) or difference_note(comparison if not comparison['accepted'] else action_comparison)
            parent['_detail_note']=note
            parent['precision']=note
            parent['_detail_comparison']=dict(source=group['source'],page=group.get('total_page',group.get('page')))
            if group.get('source_location'):parent['_detail_comparison']['source_location']=group['source_location']
        if reconstructed:
            parent['_detail_comparisons']=[c for c in group['action_reconstruction']['citations'] if c['page']]
        if needs_review:
            parent['_detail_review_required']=True
        children = [published_row(a, parent, group) for a in group['actions']]
        parent['_action_details'] = children
        if show_disagreement:
            warning=disagreement(group, parents)
            parent['_source_disagreement']=warning
            for child in navigation(children):
                child['_source_disagreement']=warning
        if len(parents) > 1:
            parent['_detail_parent_rows'] = [public_row(p) for p in parents]
            for sibling in parents[1:]:
                sibling['_detail_sibling'] = True
    return records


def navigation(records):
    for row in records:
        yield row
        yield from navigation(row.get('_action_details', []))


def detail_records(records, scope, excluded):
    """Combine reviewed title rows only when an action needs to be resolved.

    At programme/mission level without fine exclusions, retain every original
    row, source, precision flag and count. The temporary aggregate has all its
    original signed proof rows and is never stored in the canonical database.
    """
    records = list(records)
    active = {key(r) for r in records if r.get('_detail_parent_rows') and
              ((scope != path_of(r) and within(scope, path_of(r))) or
               any(e != path_of(r) and within(e, path_of(r)) for e in excluded))}
    for row in records:
        if not (row.get('_detail_parent_rows') or row.get('_detail_sibling')) or key(row) not in active:
            yield row
        elif row.get('_detail_parent_rows'):
            parents = row['_detail_parent_rows']
            yield dict(row, cents=sum(p['cents'] for p in parents), title='', category='',
                       approximate=int(any(p.get('approximate') for p in parents)),
                       _proof_rows=parents)
        elif not row.get('_detail_sibling'):
            yield row


def excluded_parts(row, fine):
    """Find disjoint published nodes to subtract, collapsing complete branches."""
    path = path_of(row)
    if path in fine:
        return [public_row(row)], True, True
    if row.get('_detail_review_required'):
        return [], False, False
    children = row.get('_action_details', [])
    branches = defaultdict(set)
    for excluded in fine:
        matching = [c for c in children if within(excluded, path_of(c))]
        if len(matching) != 1:
            return [], False, False
        branches[path_of(matching[0])].add(excluded)
    removed = []
    complete = 0
    for child in children:
        selected = branches.get(path_of(child))
        if not selected:
            continue
        parts, full, valid = excluded_parts(child, selected)
        if not valid:
            return [], False, False
        removed.extend(parts)
        complete += int(full)
    full = bool(children) and complete == len(children)
    return ([public_row(row)] if full else removed), full, True


def resolve(records, scope, excluded):
    """Resolve only the requested grain; keep authoritative totals for ancestors.

    An exclusion subtracts its published action amount from the original parent.
    We never invent a balancing action. Selecting all published actions for
    exclusion excludes the entire programme, including any rounding residual.
    Unknown actions and subactions stay unresolved.
    """
    for row in detail_records(records, scope, excluded):
        children = row.get('_action_details')
        if not children or row.get('_detail_review_required'):
            yield row
            continue
        parent = path_of(row)
        if scope != parent and within(scope, parent):
            matched = [c for c in children if within(path_of(c), scope) or within(scope, path_of(c))]
            if matched:
                yield from resolve(matched, scope, excluded)
            else:
                yield row
            continue
        if not within(parent, scope) or any(within(parent, e) for e in excluded):
            yield row
            continue
        fine = {e for e in excluded if e != parent and within(e, parent)}
        fine = {e for e in fine if not any(e != other and within(e, other) for other in fine)}
        if not fine:
            yield row
            continue
        removed, complete, valid = excluded_parts(row, fine)
        if not valid:
            yield row
            continue
        if complete:
            yield dict(row, _fully_excluded=True)
            continue
        proofs = row.get('_proof_rows', [public_row(row)]) + [dict(public_row(c), cents=-c['cents'], operation='subtract_action') for c in removed]
        yield dict(row, cents=row['cents'] - sum(c['cents'] for c in removed),
                   _resolved_exclusions={e for e in excluded if any(within(e, f) for f in fine)}, _proof_rows=proofs,
                   _detail_note='Total du périmètre source moins les postes exclus, avant correction de l’inflation. ' + NOTE + (' ' + row['_source_disagreement']['summary'] if row.get('_source_disagreement') else ''),
                   approximate=int(bool(row.get('approximate')) or any(c['approximate'] for c in removed)),
                   precision='Total source moins les montants des postes détaillés et sourcés. '+
                             ' '.join(dict.fromkeys(c.get('precision','') for c in removed)))


def is_excluded(row, excluded):
    return row.get('_fully_excluded') or any(within(path_of(row), e) for e in excluded)


def effective_exclusions(records, scope, excluded):
    """Tell the topic calculator when all reviewed actions exclude a programme."""
    return sorted(set(excluded) | {path_of(r) for r in resolve(records, scope, excluded) if r.get('_fully_excluded')})


def unresolved_exclusion(row, excluded):
    return any(within(e, path_of(row)) and e not in row.get('_resolved_exclusions', ()) for e in excluded)


def proofs(values):
    return [p for row in values for p in row.get('_proof_rows', [public_row(row)])]


def review_rows(records, scope, excluded):
    """Return relevant blocked branches, without treating a whole action as blocked."""
    for row in navigation(records):
        if not row.get('_detail_review_required') or is_excluded(row,excluded):
            continue
        path=path_of(row)
        selected=within(scope,path)
        excluded_child=within(path,scope) and any(e!=path and within(e,path) for e in excluded)
        programme_review=not row.get('action') and within(path,scope)
        if selected or excluded_child or programme_review:
            yield row


def annotations(values):
    used = proofs(values)
    notes = list(dict.fromkeys(r['_detail_note'] for r in values if r.get('_detail_note')))
    extra = {}
    disagreements=list({(r['_source_disagreement']['canonical_cents'],r['_source_disagreement']['rap_cents'],tuple((c['source'],c['page']) for c in r['_source_disagreement']['citations'])):r['_source_disagreement']
                       for r in values if r.get('_source_disagreement')}.values())
    if disagreements:
        extra['source_disagreements']=disagreements
        for warning in disagreements:
            if warning['summary'] not in notes:notes.append(warning['summary'])
    if notes:
        extra['precision'] = ' '.join(dict.fromkeys(r['precision'] for r in values if r.get('precision')))
        citations={(r['source'],r['page']) for r in used if r.get('page')}
        citations.update((c['source'],c['page']) for r in values for c in r.get('_detail_comparisons',[]))
        citations.update((c['source'],c['page']) for warning in disagreements for c in warning['citations'] if c['page'])
        extra['citations'] = [dict(source=s,page=p) for s,p in sorted(citations)]
        for row in used:
            for citation in row.get('reconstruction',{}).get('citations',[]):
                if citation not in extra['citations']:extra['citations'].append(citation)
        extra['spreadsheet_cells']=[dict(source=s,sheet=sheet,column=column,row=row)
            for s,sheet,column,row in sorted({(r['source'],r['source_location']['sheet'],r['source_location']['column'],r['source_location']['row'])
                for r in used if r.get('source_location')})]
    reconstruction_sources={c['source'] for r in used for c in r.get('reconstruction',{}).get('citations',[])}
    return sorted({r['source'] for r in used}|reconstruction_sources|{c['source'] for warning in disagreements for c in warning['citations']}), ' '.join(notes), extra



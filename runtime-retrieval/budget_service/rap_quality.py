"""RAP coverage and explanations, kept outside the monetary registries."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from . import topics, data_quality


@lru_cache(maxsize=1)
def registry():
    raw = (Path(__file__).parent / 'data/rap-coverage.json').read_bytes()
    data=json.loads(raw)
    extra=Path(__file__).parent/'data/rap-investigation.json'
    if extra.exists():
        extra_raw=extra.read_bytes();research=json.loads(extra_raw);raw+=b'\0'+extra_raw
        data['investigations']=research['records'];data['checked_at']=research['checked_at']
        known={s['id']for s in data['sources']}
        data['sources'] += [s for s in research['sources']if s['id']not in known]
    historical=Path(__file__).parent/'data/historical-no-recap-reviewed.json'
    if historical.exists():
        extra_raw=historical.read_bytes();research=json.loads(extra_raw);raw+=b'\0'+extra_raw
        data.setdefault('investigations',[]).extend(research['records'])
        data['gaps'].extend(research['gaps'])
        known={s['id']for s in data['sources']}
        data['sources'] += [s for s in research['sources']if s['id']not in known]
        data['checked_at']=max(data['checked_at'],research['checked_at'])
    return data, hashlib.sha256(raw).hexdigest()


def selected(row, p):
    path = row['mission'] + '/' + row['program']
    within = topics.within
    carriers = {c['path'] for c in topics.registry()['carriers']}
    return (row['budget'] == p['budget'] and p['start'] <= row['year'] <= p['end']
            and (within(path, p['scope']) or within(p['scope'], path))
            and not any(within(path,e) or within(p['scope'],e) for e in p['exclude'])
            and not (p.get('topic') and p.get('topic_mode','only') == 'only' and path not in carriers))


def gaps(p, kind):
    return [dict(r) for r in registry()[0]['gaps'] if kind in r['missing'] and selected(r,p)]


def reserve_placeholders():
    return [dict(year=r['year'], budget=r['budget'], mission=r['mission'], program=r['program'],
                 program_label=r['program_label'], measure=measure, source=r['source'], source_sha256=r['sha256'],
                 page=r['page'], context_pages=r['context_pages'], cells={}, table_unavailable=True,
                 coverage_status=r.get('reserve_status','table_unavailable'),
                 note=r.get('reserve_note', f'Aucun tableau standard de réserve identifié dans la section P{r["program"]} du RAP, pages {r["context_pages"][0]} à {r["page_end"]}. Aucune valeur n’est déduite de cette absence.'),
                 remaining_label='Réserve disponible avant mise en place du schéma de fin de gestion',
                 numeric_validation='table_unavailable')
            for r in registry()[0]['gaps'] if 'reserves' in r['missing'] for measure in ('AE','CP')]


def explanation(p, row, kind, status, reason='', field=''):
    reserve = kind == 'reserves'
    label = 'réserves de précaution' if reserve else 'mouvements budgétaires'
    year = row['year']
    path = row.get('path') or '/'.join(str(row.get(k,'')) for k in ('mission','program')).strip('/') or p['scope']
    needs_detail = status not in ('published','not_applicable','source_unverified','inflation_missing')
    result = dict(status=status, title='Source et portée du montant' if status=='published' else 'Pourquoi ce montant est indisponible ?',
                  summary=reason or row.get('note',''), details=[], references=[], contacts=[], request_text='',
                  checked_at=registry()[0]['checked_at'])
    if row.get('source') and status != 'source_unverified':
        result['references'] = [data_quality.citation(row['source'], page, f'RAP {year} · P{row.get("program", "")}')
                                for page in dict.fromkeys([row['page']] + row.get('context_pages', []))]
    if reserve:
        result['details'].append('Le tableau suit le programme entier. Son solde précède le schéma de fin de gestion et ne mesure pas le stock au 31 décembre. Les crédits non consommés ne permettent pas de déduire le gel.')
        if field == 'cancellations' and status == 'not_reported':
            result['details'].append('La ligne séparée d’annulations sur réserve est absente. Cela ne prouve pas l’absence d’annulations : un dégel peut précéder une annulation décrite ailleurs dans le RAP.')
    else:
        result['details'].append('Les opérations datées et les totaux annuels sont distincts. Les mouvements expliquent des crédits déjà compris dans les ouverts ; ils ne s’ajoutent pas une seconde fois aux actes publiés.')
    if status in ('table_unavailable','not_integrated'):
        result['details'].append('L’absence de tableau intégré n’est ni un montant nul ni la preuve qu’aucun document public ne contient l’information. Les montants annuels déjà sourcés restent accessibles dans « La vie des crédits ».')
    if status == 'not_applicable':
        result['title'] = 'Sans objet — justification documentaire'
    if status == 'inflation_missing':
        result['details'].append('Le montant nominal est conservé. Désactivez la correction de l’inflation pour le consulter.')
    if status == 'source_unverified':
        result['details'].append('Le lien ou l’empreinte du RAP n’est pas confirmé dans le catalogue. Le montant est masqué jusqu’au contrôle de la source.')
    investigation=next((r for r in registry()[0].get('investigations',[])if
        (r['year'],r.get('budget',p['budget']),r['program'],r['kind'])==(year,p['budget'],row.get('program'),kind)),None)
    if investigation and status!='source_unverified':
        outcome=investigation['outcome']
        titles={'exemption_documented':'Réserve : exemption documentée',
            'no_open_credits_documented':'Absence de crédits ouverts documentée',
            'partial_initial_exemption_only':'Réserve initiale : exemption documentée',
            'partial_initial_exemption_and_annual_CP_no_freeze':'Exemption initiale et absence de gel des CP documentées'}
        if reserve and outcome in titles:result['title']=titles[outcome]
        result['details'].append(investigation['limitation'])
        result['details']+=investigation.get('evidence_notes',[])
        result['references']+=investigation['references']
        result['research_note']=investigation.get('research_note','Relecture du 23 septembre 2026 : RAP, notes de la Cour des comptes et textes officiels complémentaires. La portée précise de chaque pièce est conservée.')
        if not reserve and investigation.get('annual_net_cents') is not None:
            proof=investigation['references'][-1]
            result['contextual_title']='Programme entier : solde annuel documenté'
            result['contextual_amounts']=[dict(proof,label=f'P{row.get("program", "")} · crédits ouverts moins LFI · '+p['measure'],
                cents=investigation['annual_net_cents'][p['measure']],
                caution='Ce solde concerne le programme entier, sans ventilation par action ni par dispositif et sans application des exclusions. Il ne représente pas une sélection fine. Un solde nul ne prouve pas l’absence de mouvements bruts qui se compensent ; aucune date ni catégorie n’est déduite.')]
    if year == 2026:
        result['details'].append('Au 20 septembre 2026, l’exercice est en cours. Une situation datée peut être demandée, mais elle ne constitue pas un RAP annuel définitif.')
    # Only request the device split where it actually affects this programme.
    carrier = path in {c['path'] for c in topics.registry()['carriers']}
    topic = bool(p.get('topic') and carrier and year >= 2020)
    if needs_detail:
        result['contacts'] = data_quality.CONTACTS[:2] if topic else data_quality.CONTACTS[:1]
        subject = 'la ventilation propre à MaPrimeRénov’' if topic else f'le programme {path or "sélectionné"}'
        fine = p['scope'] if p['scope'].count('/') > 1 else ', '.join(e for e in p['exclude'] if e.startswith(path+'/'))
        result['request_text'] = (f'Objet : demande de tableau de {label} — {year}, {p["measure"]}, {path}\n\n'
            f'Bonjour,\n\nJe souhaite obtenir le tableau ou l’export existant des {label} pour {subject}, exercice {year}, en {p["measure"]}.'
            + (f' La ventilation nécessaire porte sur {fine}.' if fine else '')
            + (' Merci de distinguer réserve initiale, surgels, dégels, annulations sur réserve et solde, avec leur date de situation et le schéma de fin de gestion.' if reserve else
               ' Merci de distinguer reports, fonds de concours, attributions de produits, transferts, virements, ouvertures et annulations, avec dates, actes et sens des opérations.')
            + ' Merci de préciser l’unité, les titres 2 et hors titre 2, le périmètre, la source et le total de rapprochement.'
            + (' Pour 2026, je demande la dernière situation disponible et sa date, sans l’assimiler à une exécution annuelle définitive.' if year == 2026 else '')
            + ' Si cette ventilation n’existe pas, merci de l’indiquer et d’orienter la demande vers le responsable du programme ou le service financier compétent. Un fichier CSV ou XLSX accompagné des définitions serait utile.\n\nMerci.')
    return result


def year_explanations(p, years, kind):
    return [dict(year=year, explanation=explanation(p, dict(year=year, path=p['scope']), kind, 'not_integrated',
                 'Aucun tableau intégré pour cette année et cette sélection.')) for year in years]

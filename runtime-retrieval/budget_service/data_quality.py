"""Explanations and request routes; never inputs to the monetary calculation."""
from .model import STAGES

CHECKED_AT = '2026-09-23'
CONTACTS = [
    dict(name='Direction du Budget', role='Tableaux de financement de l’État et ventilation des dotations par programme.',
         url='https://www.budget.gouv.fr/contact', label='Formulaire officiel de la direction du Budget'),
    dict(name='Ministère chargé du logement et de la transition écologique',
         role='Demande à orienter vers la DGALN/DHUP pour le P135 et la DGEC pour le P174 historique. La PRADA est le point de contact pour l’accès aux documents administratifs.',
         url='https://www.ecologie.gouv.fr/repertoire-informations-publiques',
         label='Coordonnées officielles de la PRADA', email='prada.sg@developpement-durable.gouv.fr'),
    dict(name='Anah — à l’attention du service financier',
         role='Rapprochement entre les versements des programmes de l’État et les aides financées par l’agence, avec leur dictionnaire de périmètre.',
         url='https://www.anah.gouv.fr/mentions-legales', label='Adresse officielle de l’Anah',
         address='8 avenue de l’Opéra, 75001 Paris'),
]


def citation(source, page, label):
    return dict(source=source, page=page, label=label)


def request_text(p, year, stage, scope, topic=True):
    subject = 'MaPrimeRénov’' if topic else 'les crédits budgétaires'
    return (f'Objet : demande de tableau budgétaire détaillé — {subject}, exercice {year}\n\n'
            f'Bonjour,\n\nJe souhaite obtenir le tableau ou l’export existant permettant d’isoler {subject} '
            f'pour l’exercice {year}, à l’étape « {STAGES[stage]} », en {p["measure"]}, '
            f'sur le périmètre {scope or "budget général de l’État, ensemble des programmes porteurs"}.\n\n'
            'Merci de préciser les programmes et actions de financement, l’unité, la date de situation, '
            'le périmètre couvert, les montants bruts et nets des mouvements et la source permettant de rapprocher le total. '
            + ('Pour MaPrimeRénov’, merci de distinguer les aides par geste, les parcours accompagnés, les copropriétés, '
               'les autres aides de l’Anah, les frais de gestion et les financements hors budget de l’État (notamment CEE). '
               'Les versements de l’État à l’agence et les paiements de l’agence aux bénéficiaires doivent être distingués.\n\n' if topic else '\n\n')
            + 'Si cette ventilation n’existe pas dans un document disponible, merci d’indiquer les limites du suivi '
              'et le service susceptible de détenir les données. Un fichier CSV ou XLSX accompagné des définitions serait utile.\n\nMerci.')


def general(result, p, year, stage, scope):
    missing = result.get('value') is None
    inflation = result.get('status') == 'inflation_missing'
    details = ['L’absence d’une valeur importée ne prouve ni une dépense nulle ni l’absence d’un document public.'] if missing and not inflation else []
    if missing and not inflation and year == 2026 and stage in ('EXEC','OUVERT','PLRG_OUVERTURE','PLRG_ANNULATION','REPORT_SORTANT'):
        details.append('L’exercice 2026 est en cours à la date de cet audit. Un bilan annuel définitif ne peut pas être fourni ; une situation mensuelle ou un acte daté reste distinct du résultat annuel.')
    if missing and not inflation and year <= 2022 and stage in ('OUVERT','FDC','LEGIS','REGLEMENT','REPORT_ENTRANT','REPORT_SORTANT'):
        from .rap_movements import historical_coverage_counts
        detailed,annual=historical_coverage_counts()
        details.append(f'Les mouvements RAP 2017–2022 sont intégrés acte par acte pour {detailed} programmes-années, avec dates, catégories et colonnes AE/CP Titre 2/autres titres. {annual} programmes-années supplémentaires sont disponibles sous forme de total annuel net. Une récapitulation de mouvements ne suffit pas toujours à établir chaque étape de crédit. Les périmètres restants demandent des sources ou des rapprochements complémentaires ; cela ne prouve pas que le chiffre est absent des archives.')
    partial=result['status']=='partial'
    if partial:
        summary=result.get('coverage_reason') or result.get('reason') or 'Ce total ne couvre que les montants renseignés.'
    elif result.get('source_disagreements'):
        summary=('Écart entre sources : le RAP et la source de référence ne donnent pas exactement le même total. '
                 'Le site affiche le total de référence pour le programme et les chiffres du RAP pour les actions.')
    else:
        summary=result.get('reason') or 'Montant issu des lignes sources ci-dessous.'
    return dict(status=result['status'], title='Pourquoi ce montant est indisponible ?' if missing else 'Pourquoi ce total est partiel ?' if partial else 'Portée du montant affiché',
                summary=summary, details=details,
                missing_programs=result.get('missing_programs',[]) if partial else [],
                technical_note=result.get('detail_note',''),
                known_components=[], contextual_amounts=[], references=[], checked_at=CHECKED_AT,
                contacts=CONTACTS[:1] if missing and not inflation else [],
                request_text=request_text(p, year, stage, scope, False) if missing and not inflation else '')


def source_discrepancies(rows, issues):
    """Attach only anomalies from the actual contributing source lines."""
    selected = {(r.get('source'), r.get('line')) for r in rows}
    notes=[]
    for issue in issues:
        if issue.get('kind')!='opening_identity' or (issue.get('source'),issue.get('row')) not in selected:
            continue
        amount=f"{abs(issue['difference_cents'])/100:,.2f}".replace(',', ' ').replace('.', ',')
        notes.append(f"À la ligne {issue['row']} du document source, le total des crédits ouverts publié diffère de {amount} € de la somme des mouvements indiqués. Le site conserve le montant publié, sans inventer de correction. Cette différence ne mesure pas des crédits gelés.")
    return list(dict.fromkeys(notes))


def mpr(result, p, year, stage, scope):
    from . import topics
    missing = result.get('value') is None
    status = result['status']
    explanation = dict(status=status, title='Pourquoi ce montant est indisponible ?' if missing else 'Source et périmètre du montant',
                       summary=result.get('reason', ''), details=[], known_components=[], contextual_amounts=[],
                       references=[], checked_at=CHECKED_AT, contacts=[], request_text='')
    if year < 2020 or p['budget'] != 'BG' or status in ('not_applicable', 'excluded'):
        return explanation
    if status == 'inflation_missing':
        explanation['details'] = ['Le montant en euros courants reste documenté. C’est l’indice annuel nécessaire à la conversion qui manque ; désactivez la correction de l’inflation pour consulter le montant nominal.']
        return explanation
    if not missing and result.get('evidence') and not topics.rows_for(p, year, stage, scope):
        explanation['title'] = 'Règle de périmètre documentée'
        return explanation
    explanation['details'].append('Les montants suivent le périmètre publié chaque année. Ils ne constituent pas automatiquement une série à périmètre constant. Les paiements de l’Anah aux ménages ne sont pas additionnés aux versements de l’État à l’agence.')
    # Scope evidence remains visible even when the selected amount is available.
    relevant_p362 = (not scope or topics.within('PR/362',scope) or topics.within(scope,'PR/362')) and not any(topics.within('PR/362',e) or topics.within(scope,e) for e in p['exclude'])
    if year == 2022 and relevant_p362 and stage in ('OUVERT','EXEC'):
        explanation['details'].append('Le RAP distingue 818 M€ de CP pour la prime, 47,2 M€ pour les copropriétés et l’intensification des plans Anah, et 5 M€ de communication : ces postes expliquent les 870 M€ arrondis de l’enveloppe large. Ils ne doivent pas être confondus. Les 1 092 M€ de CP ouverts ne peuvent pas être ventilés à partir de ces montants consommés.')
        explanation['references'] += [citation('72bbb96691ae9ed15695',39,'RAP 2022 : prime et aides connexes'),citation('72bbb96691ae9ed15695',40,'RAP 2022 : communication')]
    if year == 2021 and stage == 'OUVERT' and p['measure'] == 'CP':
        explanation['details'].append('740 M€ de CP ouverts sont isolés au P174. La prose de la NEB et le Sénat confirment l’étape ouvert ; le titre LFI du tableau ne permet pas de reclasser les crédits de relance, qui comprennent une ouverture en cours d’année.')
    if not missing:
        explanation['details'].append('Le tableau conserve la précision des sources : le signe ≈ signale un montant publié sous une forme arrondie. Les lignes et les pages utilisées sont consultables ci-dessous.')
        if scope.startswith('TA'):
            explanation['details'].append('Cette sélection porte sur la part rattachée à la mission Écologie ; elle ne représente pas, à elle seule, tous les financements nationaux du dispositif.')
        if year == 2025 and stage == 'PLF':
            explanation['details'].append('Les 1 378 M€ de CP du jaune 2025 concernent la prime de transition énergétique. Leur définition ne couvre pas nécessairement toutes les aides regroupées sous le nom MaPrimeRénov’ dans les budgets de l’Anah.')
        return explanation
    rows = topics.rows_for(p, year, stage, scope)
    explanation['known_components'] = [dict(label='Part identifiée du P'+r['program'], cents=r['cents'],
            precision=r['precision'], source=r['source'], page=r['page']) for r in rows if r['cents']]
    refs = topics.row_citations(rows) + explanation['references']
    if rows:
        explanation['details'].append('Les parts identifiées ci-dessous sont documentées, mais ne suffisent pas à calculer le total demandé. Elles ne sont pas substituées au montant complet et ne déclenchent pas de retrait partiel silencieux.')
    if p.get('topic_mode') == 'without' and 'total de départ' in result.get('reason','').lower():
        explanation['title'] = 'Total de départ nécessaire au retrait'
        explanation['details'] = ['La part MaPrimeRénov’ est documentée. Le total du périmètre de départ manque à cette étape ; le reste ne peut pas être calculé sans ce total.']
        explanation['references'] = refs
        explanation['contacts'] = CONTACTS[:1]
        explanation['request_text'] = request_text(p, year, stage, scope, False)
        return explanation
    if status == 'detail_unavailable':
        explanation['details'].append('Le niveau de détail sélectionné ou le rapprochement avec le total de départ n’est pas établi. Un montant au niveau du programme ne suffit pas à ventiler une action ou une sous-action.')
    main_stages = {'PLF', 'LFI', 'OUVERT', 'EXEC'}
    if stage not in main_stages:
        explanation['details'].append('Les fonds de concours, reports et mouvements des programmes porteurs ne sont pas automatiquement ceux de MaPrimeRénov’. Une ventilation propre au dispositif est nécessaire pour les isoler.')
    elif year == 2020:
        explanation['details'].append('La prime 2020 est rapprochée au P174 : 390 M€ initiaux, puis 575 M€ disponibles, comprenant 85 M€ transférés du P135. Ce transfert ne s’ajoute pas une seconde fois. Les autres aides de l’Anah restent hors de ce périmètre. Une case encore indisponible correspond à une ventilation ou à un total de départ absent pour la sélection demandée.')
        refs += [citation('2ee68df9e243bf45b79d',31,'Financement 2020 et transfert du P135'),citation('2ee68df9e243bf45b79d',32,'Tableau des étapes 2020–2022')]
        refs += [citation('46eea38db98f94b6af13',27,'PAP 2020 : prime et autres aides du P135'), citation('df8d92ccd79f7b889547',415,'RAP 2020 : part du P174')]
    elif year in (2021, 2022, 2023):
        explanation['details'].append('La part du P174 est isolée pour le PLF et la LFI. Les enveloppes de relance et les aides de l’Anah ne sont pas toutes ventilées selon le même périmètre et la même étape. Une dotation de rénovation, des crédits ouverts en cours d’année ou des reports ne peuvent pas être pris pour la LFI du seul dispositif.')
        sid, page = {2021:('2f15709320cdd6cb8d0a',54),2022:('a954f39135465e66a745',42),2023:('8a04f40171b880b41ba2',39)}[year]
        refs.append(citation(sid,page,'Cour des comptes : financement et étapes budgétaires'))
    elif year == 2024:
        explanation['details'].append('Le PAP isole MaPrimeRénov’ au P174. La subvention de rénovation thermique du P135 couvre un ensemble d’aides de l’Anah ; sa ventilation exacte selon le périmètre demandé n’est pas établie dans les pièces examinées. Le PLF initial reste distinct des amendements, de la LFI et des annulations ultérieures.')
        refs += [citation('ad1d42da63958bf4a275',400,'PAP 2024 : part du P174'),citation('b7dd7c6577809efa3c84',116,'PAP 2024 : ensemble d’aides du P135')]
        relevant_p135 = (not scope or topics.within('VA/135',scope) or topics.within(scope,'VA/135')) and not any(topics.within('VA/135',e) or topics.within(scope,e) for e in p['exclude'])
        if stage in ('LFI','OUVERT','EXEC'):
            explanation['details'].append('Le tableau 12 de la note de la Cour des comptes intitule MaPrimeRénov’ une enveloppe que le RAP définit comme subvention globale de l’Anah, couvrant aussi habitat indigne, MaPrimeAdapt’, fonctionnement et investissement. Les six observations P135 de 2024 ont donc été retirées du calcul du seul dispositif et restent consultables comme contexte. Les parts du P174 ne sont pas modifiées.')
            refs += [citation('dca85104653c2c5a3d17',126,'RAP 2024 : usages de la subvention Anah'),citation('793f09813e0448b0055c',61,'NEB : subvention globale'),citation('793f09813e0448b0055c',62,'NEB : tableau 12, intitulé et montants')]
            if relevant_p135:
                amount={'LFI':112400000000,'OUVERT':38000000000,'EXEC':38020000000}[stage]
                explanation['contextual_amounts'].append(dict(label=f'Enveloppe globale Anah — {STAGES[stage]}, {p["measure"]}',cents=amount,source='793f09813e0448b0055c',page=62,caution='Cette enveloppe comprend MaPrimeRénov’ et d’autres aides ainsi que le fonctionnement/investissement. Elle ne peut être ni additionnée ni soustraite comme montant propre au dispositif. Montant arrondi tel que publié dans la NEB.'))
        elif stage == 'PLF' and relevant_p135:
            explanation['contextual_amounts'].append(dict(label='Subvention Anah pour la rénovation thermique — PLF 2024',cents=103830000000,source='b7dd7c6577809efa3c84',page=116,caution='Enveloppe de rénovation thermique publiée à 0,1 M€, distincte de MaPrimeAdapt’ et du fonctionnement. La ventilation exacte du seul périmètre MaPrimeRénov’ n’est pas établie ; ce montant ne remplace pas le total du dispositif.'))
    elif year in (2025, 2026):
        explanation['details'].append('La Cour des comptes rapporte que la direction du Budget distingue une brique directement fléchée vers MaPrimeRénov’ et une subvention générale à l’Anah qui le finance aussi, dans des proportions non définies. La brique connue ne constitue donc pas le total du dispositif (page 55, note 116).')
        refs += [citation('270aaa96aa51346f908e',55,'Cour des comptes : ventilation Anah, note 116'),citation('d2c406b7e2bc73904e50',122,'RAP 2025 : subventions Anah et aides regroupées')]
        relevant_p135 = (not scope or topics.within('VA/135',scope) or topics.within(scope,'VA/135')) and not any(topics.within('VA/135',e) or topics.within(scope,e) for e in p['exclude'])
        if relevant_p135 and stage == 'LFI' and p['measure'] == 'CP':
            amount = 77990000000 if year == 2025 else 60460000000
            explanation['contextual_amounts'].append(dict(label=f'Brique directement fléchée — LFI {year}, CP',cents=amount,
                caution='Part seulement : le complément financé par la subvention générale n’est pas ventilé. Ce chiffre n’est pas le total affichable ou soustrayable du dispositif.',source='270aaa96aa51346f908e',page=55))
        if year == 2025 and relevant_p135 and stage in ('LFI','OUVERT','EXEC'):
            values={'LFI':(226530000000,203530000000),'OUVERT':(211020000000,200580000000),'EXEC':(210990000000,200560000000)}
            explanation['contextual_amounts'].append(dict(label=f'Enveloppe Anah — {STAGES[stage]}, {p["measure"]}',cents=values[stage][p['measure']=='CP'],
                caution='Le tableau 11 est intitulé MaPrimeRénov’, mais le RAP détaille une enveloppe Anah comprenant aussi d’autres aides et des subventions de fonctionnement/investissement. Elle n’est pas retenue comme montant du seul dispositif.',source='270aaa96aa51346f908e',page=55))
        if year == 2026:
            refs.append(citation('dbfe025ccdf7c863dd3d',17,'Jaune 2026 : crédits de rénovation et estimation Anah'))
            refs.append(citation('49e40a23762335975cf2',9,'Anah : programmation 2026 et réserve budgétaire propre'))
            explanation['details'].append('La programmation propre de l’Anah pour 2026 prévoit une réserve budgétaire de 178,1 M€ pour les parcours accompagnés et les copropriétés. Ce document de programmation ne mesure pas un gel de précaution des programmes de l’État ni un solde constaté en fin d’année.')
            explanation['details'].append('Les montants globaux du budget de l’Anah et les estimations du jaune ne suffisent pas à définir un montant de crédits de l’État propre au dispositif, à une étape et en AE ou CP précises.')
            if stage == 'EXEC':
                explanation['details'].append('Au 23 septembre 2026, l’exercice 2026 est en cours : une consommation annuelle définitive ne peut pas encore être fournie. Une situation infra-annuelle doit porter sa date et rester distincte du RAP annuel.')
    explanation['references'] = list({(r['source'],r['page']):r for r in refs}.values())
    explanation['contacts'] = CONTACTS
    explanation['request_text'] = request_text(p, year, stage, scope)
    explanation['research_note'] = ('Vérification complétée le 23 septembre 2026 : recherche dans le corpus local indexé et LexMachine, confrontation des PAP, RAP, notes de la Cour des comptes, rapports parlementaires et programmation Anah. Les catalogues API de Bercy et data.gouv.fr avaient également été examinés. Aucune série complète répondant à cette ventilation n’a été établie. Ce constat ne signifie pas que l’administration ne possède pas les données.')
    return explanation

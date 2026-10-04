"""Freeze a portable LOCAL delivery and document remaining qualification work.

No deployment, paid encoding, external write or SMTP send.
"""
import argparse
import collections
import hashlib
import html
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from plfss_service.model import BRANCHES
from plfss_service.store import Store,PERIMETERS


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main(pack=False):
    fmt=lambda n:format(n,',').replace(',',' ')
    deploy=ROOT/'deploy';deploy.mkdir(exist_ok=True)
    delivery=read(ROOT/'reports/delivery-check.json')
    audit=read(ROOT/'reports/source-audit.json')
    browser=read(ROOT/'reports/browser-check.json')
    coverage=read(ROOT/'reports/coverage.json')
    collection=read(ROOT/'reports/collection.json')
    meta=Store(ROOT/'data').meta()
    annex=read(ROOT/'reports/annex-qualification.json') if (ROOT/'reports/annex-qualification.json').is_file() else None
    details=read(ROOT/'reports/annex-detail-qualification.json') if (ROOT/'reports/annex-detail-qualification.json').is_file() else None
    vector_state=read(ROOT/'vectorization/status.json') if (ROOT/'vectorization/status.json').is_file() else None
    if vector_state and (ROOT/'vectorization/documents').is_dir():
        # A targeted retry can finish outside the initial controller. Compatible
        # completed receipts take precedence over its older failed list.
        config=read(ROOT/'vectorization/preparation-contract.json')
        receipts=[read(p) for p in (ROOT/'vectorization/documents').glob('*.receipt.json')]
        receipts=[r for r in receipts if r['preparation_identity']==config['preparation_identity'] and (ROOT/'vectorization'/r['path']).is_file()]
        done={r['source_sha256'] for r in receipts}
        held=read(ROOT/'vectorization/held-documents.json')
        unresolved=[r for r in held if r['source_sha256'] not in done]
        for r in held:
            if r['source_sha256'] in done:
                receipt=next(n for n in receipts if n['source_sha256']==r['source_sha256'])
                if sha(ROOT/'vectorization'/receipt['path'])!=receipt['sha256']:raise ValueError('Reprise PDF modifiée après sa clôture')
        vector_state.update(done=len(done),held=len(unresolved),passages=sum(r['chunks'] for r in receipts),tokens=sum(r['tokens'] for r in receipts),resolved_document_retries=len(held)-len(unresolved))
        choice=ROOT/'vectorization/historical-protocol-choice.json'
        if choice.is_file():
            selected=read(choice)
            vector_state.update(decision_required=selected.get('decision_required',False),historical_alignment_required=selected.get('alignment_required',True),selected_historical_profile=selected['profile'],range_compaction_enabled=False)
        save(ROOT/'reports/current-preparation-state.json',vector_state)
    memo_state=ROOT/'vectorization/memo-20261004/status.json'
    if memo_state.is_file():
        vector_state=read(memo_state)
        save(ROOT/'reports/current-preparation-state.json',vector_state)
    if any(r.get('data_version')!=meta['data_version'] for r in (delivery,coverage,audit,browser)):
        raise ValueError('Rapports et base ne portent pas sur la même version')
    if not all(r['passed'] for r in (delivery,audit,browser)):
        raise ValueError('Un contrôle de restitution n’est pas validé')
    sources=read(ROOT/'data/catalogue/normalized-sources.json')
    # Exact binary deduplication only. Chapters/full reports may overlap in
    # content and still need passage deduplication during preparation.
    unique={};containers=[]
    for source in sources:
        if source['status']!='downloaded':continue
        suffix=Path(source['path']).suffix.lower()
        if suffix=='.zip':containers.append(source['id']);continue
        if suffix not in ('.pdf','.html','.htm','.asp','.xlsx','.csv','.txt'):continue
        item=unique.setdefault(source['sha256'],dict(sha256=source['sha256'],bytes=source['bytes'],path=source['path'],
            type=suffix,source_ids=[],extraction_mode='pdf_pages_and_tables' if suffix=='.pdf' else ('cells_and_headers' if suffix in ('.xlsx','.csv') else 'articles_paragraphs_and_tables')))
        item['source_ids'].append(source['id'])
    historical=ROOT.parent/'budget/consolidation-vectorisation-20260924/preparation-conforme/gpu_input/contract.json'
    contract=read(historical)
    keep=('model','revision','max_tokens','artificial_overlap','dimension','dense_dimensions','dense_dtype','dense_normalized','sparse_dtype','colbert','context_included_in_token_limit','truncation','word_boundary_required')
    parameters={key:contract[key] for key in keep if key in contract}
    preparation=dict(status='inventory_only_not_encoder_input',sources=list(unique.values()),
        unique_files=len(unique),bytes=sum(s['bytes'] for s in unique.values()),archive_containers_excluded=containers,
        historical_contract=dict(path=str(historical),sha256=sha(historical),parameters=parameters),
        passages_prepared=False,vectorized=False,paid_compute_authorized=False,gpu_launched=False,
        notes=['Les nombres, années, articles, pages, lignes et colonnes doivent conserver leur contexte et leurs preuves.',
               'Reprendre les extracteurs et le contrat historique, sans inventer un nouveau découpage ni un chevauchement.',
               'Dédupliquer aussi les passages communs aux chapitres et rapports complets ; les empreintes binaires seules ne suffisent pas.',
               'Contrôler l’OCR des pages sans texte et la lecture des tableaux avant d’exporter les passages.',
               'Aucun volume de tokens ni coût GPU n’est annoncé tant que les passages n’ont pas été préparés et contrôlés.'])
    if vector_state:
        preparation['local_preparation']=vector_state
        preparation['status']='preparing_local_passages' if vector_state.get('state','').startswith('preparing') else 'local_passages_pending_independent_validation'
        preparation['passages_prepared']=vector_state.get('complete',False)
    vector_note='Les vecteurs dense et sparse restent à préparer selon le contrat historique, puis à encoder après volume et budget convenus.'
    if vector_state:
        vector_note=(f"Préparation locale des passages : {vector_state.get('done',vector_state.get('documents_prepared',0))} documents traités sur {vector_state.get('expected',vector_state.get('documents_expected',0))}. "
                     "Les extracteurs historiques sont figés et leurs empreintes vérifiées. Le contrôle indépendant des caractères, pages, cellules et limites de tokens précède tout encodage. Aucun GPU lancé ni coût engagé.")
        if vector_state.get('decision_required') or vector_state.get('state')=='awaiting_excel_layout_decision':
            vector_note+=' Les Excel restants attendent une décision sur la représentation des grandes plages vides ; les PDF et HTML poursuivent leur préparation inchangée.'
    if meta['vectorized']:
        search=read(ROOT/'data/search/manifest.json')
        retrieval=read(ROOT/'reports/retrieval-check.json')
        if not retrieval['passed'] or retrieval['search_input_sha256']!=search['input_sha256']:
            raise ValueError('Index non contrôlé ou génération mélangée')
        vector_note=(f"Vectorisation dense et sparse intégrée : {fmt(search['passages'])} passages, {fmt(search['physical_files'])} fichiers physiques. "
                     "BAAI/bge-m3, révision figée, dense 1 024 dimensions et sparse float32. ColBERT désactivé. Recherche et citations contrôlées ; aucun GPU encore actif.")
        preparation.update(status='vectorized_and_integrated',passages_prepared=True,vectorized=True,
            paid_compute_authorized=True,gpu_launched=True,gpu_active=False,pod_deleted=True,
            search_index=search,runpod_receipt=read(ROOT/'vectorization/memo-20261004/runpod-controller/receipts/lexmachine-plfss-20261004-3ab0e1a4256b.json'))
    details_note=''
    if details:
        details_note=(f"<li>{fmt(details['qualified_observations'])} observations détaillées de recettes, dépenses, FRR et CADES qualifiées dans {len(details['tables'])} tableaux, "
                      f"dont {details['explicit_zeros']} zéros explicites. Elles sont relues dans le registre source et gardées séparées des totaux de branches. "
                      f"{len(details['held'])} tableaux restent en attente d’une unité explicitement démontrée. "
                      '<a href="annex-details-qualifies.csv">Séries détaillées qualifiées</a> · <a href="annex-detail-qualification.json">État de qualification</a>.</li>')
    save(deploy/'preparation-vectorisation.json',preparation)
    esc=html.escape
    issues=''.join('<tr><td>'+str(n['exercise'])+'</td><td>'+esc(PERIMETERS[n['perimeter']])+'</td><td>'+esc(BRANCHES.get(n['entity'],n['entity']))+'</td><td>'+esc(n['explanation'])+'<br><a href="'+esc(n['url'],quote=True)+'">Publication source</a></td></tr>' for n in delivery['source_arithmetic_notices'])
    failed=''.join('<li><a href="'+esc(n['url'],quote=True)+'">'+esc(n['title'])+'</a> — '+esc(str(n.get('error') or 'Lien à reprendre'))+'</li>' for n in delivery['failed_downloads'])
    report=f'''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PLFSS · bilan de préparation</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#173a55}}h1,h2{{color:#08183f}}.notice{{padding:18px;border:1px solid #e8cc9f;background:#fff8eb;border-radius:10px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:12px;border:1px solid #d4e2f1;text-align:left;vertical-align:top}}td:last-child{{width:60%}}a{{color:#173a55}}code{{overflow-wrap:anywhere}}li{{margin:8px 0}}</style>
<h1>PLFSS · préparation mise à jour le 4 octobre 2026</h1>
<p><a href="http://127.0.0.1:18895/">Ouvrir la copie locale</a> · <a href="../README.txt">Instructions de lancement</a></p>
<p class="notice"><strong>Restitution contrôlée ; qualification documentaire complète encore à terminer.</strong> Application locale autonome ; aucun site public ni serveur modifié. Vectorisation intégrée : {fmt(meta.get('indexed_passages',0))} passages. Cette recherche ne certifie pas tous les chiffres des annexes.</p>
<h2>Ce qui est disponible</h2><ul>
<li>{fmt(meta['files'])} fichiers récupérés (PDF, Excel, CSV, HTML et archives), plus {fmt(meta['jorf_articles'])} articles JORF des LFSS. Environ {collection['bytes']/10**9:.2f} Go pour la collecte documentaire.</li>
<li>{fmt(meta['facts'])} observations chiffrées, avec montants, unités, exercices et positions sources ; plusieurs observations peuvent documenter une même case.</li>
<li>2017–2027 : recettes, dépenses et soldes par branche et périmètre ; ONDAM et ses sous-objectifs séparés ; projets, lois, rectifications et résultats distingués.</li>
<li>Filtres, exclusions, preuves, liens PDF vers la page, export Excel numérique et compteur central. Recherche dans le contenu par dense, sparse et plein texte, ou dans les titres ; millésime documentaire et sources contrôlés.</li>
</ul><h2>Contrôles réussis</h2><ul>
<li>{fmt(audit['checked'])} cellules relues dans les fichiers sources ; zéro erreur de copie détectée.</li>
<li>{fmt(delivery['checked_files'])} références de fichiers vérifiées par taille et SHA-256.</li>
<li>{fmt(delivery['balance_checks'])} rapprochements recettes–dépenses–solde ; les {len(delivery['source_arithmetic_notices'])} lignes signalées disposent d’une explication documentaire et de références complémentaires. Les valeurs originales restent conservées avec un avertissement. <a href="RAPPROCHEMENT_9_LIGNES.html">Lire les neuf rapprochements et leur portée</a>.</li>
<li>{delivery['matrix_scenarios']} scénarios de tableaux et {delivery['exclusion_checks']} contrôles des sommes de sélection. Aucun total consolidé publié n’est remplacé par une somme de branches.</li>
<li>{len(browser['checks'])} parcours navigateur enregistrés, avec {fmt(sum(c.get('cells',0) for c in browser['checks']))} cellules d’écran comparées. Présentation ordinateur/téléphone inspectée. Cela ne démontre pas toutes les combinaisons possibles.</li>
</ul><h2>Ce qui reste à qualifier</h2><ul>
<li>Les détails des annexes : nature des recettes, prestations, organismes, dette et réserves. Les {fmt(read(ROOT/'reports/excel-summary.json')['numeric_cells'])} cellules numériques Excel inventoriées ne sont pas toutes intégrées à la base des montants.</li>
<li>{fmt(annex['worksheets']) if annex else 'Les'} feuilles Excel ont un état d’exploitation détaillé : unités et périodes candidates, taux, données documentaires ou cellules sélectionnées intégrées. Ce registre ne certifie pas financièrement toutes les cellules. <a href="annexes-a-qualifier.csv">Inventaire des annexes</a>.</li>
{details_note}
<li>Dans la matrice principale ROBSS et ONDAM : {coverage['summary'].get('published',0)} cases renseignées, {coverage['summary'].get('publication_future',0)} publications futures (loi 2027 ou résultats annuels 2026–2027), {coverage['summary'].get('ligne_historique_distincte_non_reperee',0)} cases historiques sans ligne Autonomie distincte. Ces deux dernières catégories ne sont pas converties en zéros.</li>
<li>Annexes DSS PLFSS 2027 1 à 8 annoncées à venir lors de la collecte. Aucun chiffre créé pour les remplacer.</li>
<li>{vector_note} Le manifeste de livraison reste distinct du lot GPU et de sa validation.</li>
<li>Le VPS de destination reste à choisir. Le Docker est local ; aucun bouton PLFSS n’est ajouté sur Nos Deniers.</li>
</ul><h2>Écarts dans les publications : rapprochements documentés</h2>
<p>Le rapport conserve les chiffres lus. Il ne remplace pas un solde publié par le résultat d’une soustraction, ni ne déclare automatiquement une publication fausse. Les cellules concernées affichent un avis et des preuves.</p>
<table><thead><tr><th>Exercice</th><th>Périmètre</th><th>Poste</th><th>Constat</th></tr></thead><tbody>{issues}</tbody></table>
<h2>{len(delivery['failed_downloads'])} liens de téléchargement à reprendre</h2><p>Plusieurs liens directs du Journal officiel sont filtrés ; les articles JORF originaux ont été récupérés par le client Moulineuse existant. Un échec de lien ne signifie pas automatiquement un chiffre perdu.</p><ul>{failed}</ul>
<h2>Version examinée</h2><p><code>{meta['data_version']}</code></p>
<p>Voir <a href="source-audit.json">la relecture source</a>, <a href="delivery-check.json">le contrôle de livraison</a>, <a href="browser-check.json">les parcours navigateur</a>, <a href="coverage.json">la couverture</a> et <a href="donnees-a-traiter.csv">les états de cases</a>.</p></html>'''
    (ROOT/'reports/BILAN_PREPARATION.html').write_text(report,encoding='utf-8')
    fixed=['Dockerfile','Dockerfile.retrieval','compose.yaml','requirements.txt','.dockerignore','LANCER_PLFSS.bat','PREPARER_VECTORISATION.bat','VERIFIER_VECTORISATION.bat','README.txt','POINT_DE_REPRISE.md']
    files=[ROOT/name for name in fixed]
    for name in ('data','plfss_service','public','tests','tools'):
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.tmp') and '.new.' not in p.name and not ('search' in p.parts and (p.name=='trained.faiss' or 'shards' in p.parts)))
    files.extend(ROOT/'reports'/name for name in ('BILAN_PREPARATION.html','collection.json','normalized.json','coverage.json','source-audit.json','delivery-check.json','browser-check.json','table-inventory.json','excel-summary.json','excel-inventory.json','donnees-a-traiter.csv','plfss-desktop.png','plfss-mobile.png','reuse-manifest.json'))
    for name in ('RAPPROCHEMENT_9_LIGNES.html','source-reconciliation.json','annex-qualification.json','annexes-a-qualifier.csv','annex-detail-qualification.json','annex-details-qualifies.csv','PROPOSITION_PLAGES_VIDES_EXCEL.html','excel-index-proposal.json','current-preparation-state.json','held-pdf-diagnosis.json','held-pdf-retry.json'):
        if (ROOT/'reports'/name).is_file():files.append(ROOT/'reports'/name)
    files.extend(p for p in (ROOT/'reports/reconciliation-inspection').glob('*') if p.is_file())
    files.append(deploy/'preparation-vectorisation.json')
    files=sorted(set(files))
    if meta['vectorized']:files.extend(ROOT/'reports'/name for name in ['retrieval-check.json','runpod-final.json'])
    manifest=dict(data_version=meta['data_version'],published=False,vectorized=meta['vectorized'],scope='Application locale et recherche intégrée, restitution contrôlée ; limites dans BILAN_PREPARATION.html',
        files=[dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in files])
    save(deploy/'release-manifest.json',manifest)
    if pack:
        target=deploy/'PLFSS-preparation-20261004.zip'
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as out:
            for p in files+[deploy/'release-manifest.json']:out.write(p,p.relative_to(ROOT).as_posix())
        with zipfile.ZipFile(target) as check:
            if check.testzip():raise ValueError('Archive corrompue')
        receipt=dict(path=str(target),bytes=target.stat().st_size,sha256=sha(target),data_version=meta['data_version'])
        save(deploy/'package-receipt.json',receipt)
        print(json.dumps(receipt),flush=True)
    else:print(json.dumps(dict(files=len(files),data_version=meta['data_version'],vectorization_unique_files=len(unique),vectorization_source_bytes=preparation['bytes'])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pack',action='store_true')
    main(parser.parse_args().pack)

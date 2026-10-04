PLFSS — application autonome et recherche documentaire — 4 octobre 2026

Site public : https://plfss.lexmachine.net/ (HTTPS, sans mot de passe).
Consultation locale : http://127.0.0.1:18895/
Windows : LANCER_PLFSS.bat (Docker Desktop démarré).
Linux, avec les images installées : docker compose -p nos-deniers-plfss-local up -d --no-build --wait --wait-timeout 180 web
Arrêter toute l’application locale : docker compose -p nos-deniers-plfss-local stop web retrieval

Le web consulte sa propre base et ses documents dans data, en lecture seule.
Le moteur documentaire privé utilise son index PLFSS et son modèle BGE-M3 local.
Aucun accès au moteur, à la base ou au VPS Nos Deniers n’est requis. Aucun GPU,
service d’IA distant ou monitoring n’est lancé par une consultation.

Dans Rapports et documents : saisir un texte puis Rechercher.
- Recherche dans le contenu : texte intégral, dense BGE-M3 et reclassement sparse.
- Mots dans le contenu : recherche dans le texte indexé.
- Titres et références : filtre du catalogue documentaire.
Sans saisie : catalogue complet avec pagination. Les filtres de millésime et
famille portent sur les documents, pas chaque montant qu’ils citent. Les
passages complets et leurs repères sont consultables. Les PDF s’ouvrent à la
page physique indiquée. Le compteur central accompagne recherches et exports.

Vectorisation récupérée : 311 791 passages distincts, 2 086 fichiers physiques,
39 parties sauvegardées avec leurs empreintes. Profil du mémo du 1 octobre :
tuilage conditionnel jusqu’à 150 tokens sur la route générique, pas de tuilage
artificiel sur les tableaux PDF corrigés, contexte et repères conservés,
plafond 800 tokens, aucune troncature, aucun blanc transformé en zéro.
Modèle : BAAI/bge-m3, révision 5617a9f61b028005a4858fdac845db406aefb181.
Dense : 1 024 dimensions, normalisé, float16 conservé dans les parties brutes.
Sparse : poids float32 conservés ; reclassement des candidats à la recherche.
ColBERT désactivé. L’index IVF/SQ8 réduit le coût de recherche ; vecteurs bruts
et preuves originales conservés dans vectorization. RunPod : pod supprimé,
coût estimé 2,83 USD. Reçu dans reports/runpod-final.json.

Les montants financiers restent des centimes entiers. ROBSS, RG et FSV sont
séparés, ainsi que proposé, voté, rectifications, constaté et projections.
Le total consolidé vient de la source ; une exclusion donne une somme séparée
sans neutraliser les transferts. ONDAM n’est jamais ajouté à la branche Maladie.
Un zéro publié reste 0 ; une absence reste expliquée. La recherche documentaire
ne fabrique ni ne certifie automatiquement des montants financiers.

5 412 observations principales sont qualifiées et relues. Les neuf écarts
arithmétiques des publications restent signalés et rapprochés : voir
reports/RAPPROCHEMENT_9_LIGNES.html. Aucun montant original modifié.
Les 1 402 observations de 19 tableaux détaillés, dont 264 zéros, restent
séparées des totaux de branches. Trois tableaux CADES attendent une unité
démontrée. Toutes les cellules des 82 classeurs ne sont pas encore qualifiées.
Les annexes DSS PLFSS 2027 1–8 étaient annoncées à venir lors de la collecte.
Voir Sources et couverture et reports/BILAN_PREPARATION.html.

Contrôles : python -B -m unittest discover -s tests
python -B tools/audit_source.py ; python -B tools/check_delivery.py
python -B tools/check_retrieval.py ; node tools/check_browser.cjs
Ces outils ne lancent pas de GPU. La préparation du corpus reste archivée
avec son audit passed=true ; ne pas la relancer pour consulter le site.

Images autonomes : nos-deniers-plfss:20261004-public et
nos-deniers-plfss-retrieval:20261004-vectorise. Pour reconstruire cette dernière,
la base locale lexmachine-budget-retrieval:20260924-final fournit les poids figés.
Transporter l’image PLFSS construite suffit pour l’exécution sur un autre serveur.
Données de consultation : data, plfss_service, public ; l’index actif utilise
search.sqlite et dense.faiss, plus manifest.json. Les parties d’encodage et
points de reprise ne sont pas nécessaires sur le serveur de consultation.

Publié le 4 octobre 2026 sur le VPS 5.189.145.254, projet Docker
nos-deniers-plfss-public. Version : /opt/plfss/releases/20261004-vectorise-7711a46a ;
/opt/plfss/current pointe vers cette version. Web : 1 CPU / 768 Mio ; recherche
privée : 2 CPU / 4 Gio. Aucun GPU. Ces limites sont propres à PLFSS.
Démarrage sur le VPS : docker compose -p nos-deniers-plfss-public -f /opt/plfss/current/compose.yaml up -d --no-build --wait --wait-timeout 240
Arrêt ciblé : docker compose -p nos-deniers-plfss-public -f /opt/plfss/current/compose.yaml stop web retrieval
Contrôle public : 1 056 cellules identiques à la version locale ; 59 parcours
navigateur / 858 cellules, sans échec. PDF, recherche hybride et export vérifiés.
Preuves et reçu : deploy/publication-20261004. Les limites documentaires restent
celles indiquées ci-dessus : ces tests ne certifient pas tous les détails d'annexes.
Aucun bouton PLFSS ajouté à Nos Deniers. Nos Deniers, ses données et ses quatre
instances web inchangés ; les configurations nginx des autres sites sont conservées.

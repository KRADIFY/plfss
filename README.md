# PLFSS — sauvegarde du site en ligne au 7 octobre 2026

Branche privée `sauvegarde-en-ligne-20261007`, tag `en-ligne-20261007`.
Cette capture provient des trois conteneurs actifs : site, moteur documentaire et démo.
Le manifeste actuel est `proofs/VERSION-EN-LIGNE-20261007.json` : 185 fichiers
contrôlés par SHA-256, images Docker et montages de production, métadonnées financières.

La démo actuelle à trois parcours et ses voix sont dans `demo`. Les feuilles de
présentation réellement injectées sont dans `presentations`, et la configuration
d'entrée par la démo dans `proofs/nginx-plfss.conf`. Le bouton Stop ouvre le site
avec `?demo=off` ; le bouton Démo relance la visite. Le code de recherche actif
est aussi archivé dans `runtime-retrieval`.

La base financière est inchangée : SHA-256
`8c37953ef9c4bb222c132b8134bf652aebe86670818a4202f7c9dfc67083da24`.
Les documents et index volumineux restent dans la publication du 4 octobre
décrite ci-dessous ; cette nouvelle branche conserve les actualisations de code,
de présentation et de démo. Les manifestes anciens restent des preuves historiques.
Les configurations conservent les chemins VPS ; les styles du domaine Budget
et le service externe de comptage ne sont pas déployés par ce dépôt.
Aucun site, chiffre, conteneur ou réglage de production n'a été modifié par cette sauvegarde.

## Sauvegarde de référence du 4 octobre 2026

Site : https://plfss.lexmachine.net/ ; VPS : 5.189.145.254.
Ce dépôt privé conserve le code, la base financière et les fichiers de preuve
de la version effectivement publiée, vérifiés par SHA-256 contre son manifeste.
5 412 observations principales ; 311 791 passages documentaires.

## Données volumineuses et restauration

Dans la publication GitHub `en-ligne-20261004`, télécharger les deux fichiers :

1. `PLFSS-public-20261004.tar.gz` : corpus, index dense/sparse, données, code,
   image web et manifeste original vérifiés avant déploiement.
2. `PLFSS-public-20261004-final-overlay.tar.gz` : configuration finale 4 Gio,
   documentation publiée, manifeste actif et résultats des tests.

Extraire le premier, puis le second par-dessus, dans un dossier neuf.
Les index et les PDF sont conservés dans ces archives et pas dans les objets Git.
`proofs/GITHUB-BACKUP-MANIFEST.json` liste les fichiers et leurs empreintes.
Le runtime de recherche utilise la base Docker figée
`lexmachine-budget-retrieval:20260924-final`, dont l'identifiant exact est conservé
dans le manifeste ; cette image lourde et les checkpoints GPU bruts ne sont pas
inclus dans les archives. La base reste disponible sur le VPS et en local.
Ne pas relancer RunPod pour restaurer les index.

## Contrôles et limites

Public : 1 056 cellules comparées au local ; 59 parcours navigateur, 858 cellules,
zéro échec. Recherche hybride, PDF, exports et affichage mobile vérifiés.
Les neuf divergences dans les publications sources restent documentées ;
les détails d'annexes non qualifiés restent indiqués. Aucun changement de chiffre
ni modification de Nos Deniers effectué pour cette sauvegarde.

# PLFSS — version en ligne du 8 octobre 2026

Dépôt privé : https://github.com/KRADIFY/plfss.
Branche `sauvegarde-en-ligne-20261008`, tag `en-ligne-20261008`.
La branche principale reçoit également cette version par avance simple, sans effacement de l'historique.
Site capturé : https://plfss.lexmachine.net/.

## Dernière version sauvegardée

La capture provient des trois conteneurs actifs : site, moteur documentaire et démo.
Le manifeste actuel est `proofs/VERSION-EN-LIGNE-20261008.json` : 215 fichiers vérifiés par SHA-256, images Docker, montages et métadonnées financières.

La démo comporte trois parcours, les textes révisés du 7 octobre et **30 nouveaux extraits audio**, avec les passages musicaux finaux conservés. Les explications utilisent le dernier correctif de placement pour laisser visibles les exemples. Les fichiers sont dans `demo/public` ; les feuilles de présentation injectées sont dans `presentations`. L'entrée par la démo et le comptage partagé sont conservés dans les fichiers de configuration capturés.

La base financière est inchangée : **5 412 observations principales et 1 402 détails distincts**. La recherche compte **311 791 passages**.
SHA-256 de `data/derived/plfss.sqlite` :
`8c37953ef9c4bb222c132b8134bf652aebe86670818a4202f7c9dfc67083da24`.

Aucun site, chiffre, texte, style, conteneur ou réglage de production n'a été modifié pour réaliser cette sauvegarde.

## Où se trouve le dépôt local ?

`D:/ChatGPT/docker/backups/plfss-20261004-public/git`.
Le nom historique du dossier indique sa création ; son contenu est actualisé au 8 octobre.
Ce dépôt contient le code et l'historique Git sur le PC. GitHub en est la copie distante ; les changements futurs ne sont pas sauvegardés automatiquement sans un nouveau commit et un push.

Les données volumineuses, les index et les images Docker sont également conservés en local dans :
`H:/Sauvegardes-Nos-Deniers/20261008-version-en-ligne`.
Consulter le manifeste de vérification et les instructions de restauration de ce dossier. Les anciens index n'ont pas été recalculés. La publication GitHub du 4 octobre, décrite ci-dessous, reste conservée.

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

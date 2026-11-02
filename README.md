# Le Grand Dépouillement — installation

Les scripts qui installent l'appli « Le Grand Dépouillement » sur un PC Windows.

## Pour installer

1. Télécharger `INSTALLMOI.bat` et le mettre dans un dossier vide.
2. Double-cliquer dessus.

Le fichier :

1. installe Python et Git avec winget s'ils manquent ;
2. télécharge ce dépôt ;
3. installe les bibliothèques ;
4. récupère les données en ligne (data.gouv, INSEE, Wikidata) et les met en forme.

Tout s'installe dans ce dossier, sauf Python et Git.

## Contenu

| Fichier | Rôle |
| --- | --- |
| `INSTALLMOI.bat` | l'installateur, le seul fichier à envoyer |
| `requirements.txt` | les bibliothèques Python |
| `installation/` | la récupération et la mise en forme des données (à venir) |

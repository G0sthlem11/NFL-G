# NFL Gameday

Web app personnelle qui affiche les résultats des matchs NFL de la saison en cours. Pour chaque match, on trouve les statistiques des deux équipes et une fiche des joueurs clés :

- en attaque : QB, RB1, WR1, WR2, TE1 ;
- en défense : les edges titulaires, le meilleur plaqueur, et les auteurs de sacks, d'interceptions et de fumbles forcés.

L'app propose aussi un classement par division et une page par joueur.

Les données viennent de [nflverse](https://github.com/nflverse), via le package Python [`nflreadpy`](https://pypi.org/project/nflreadpy/). **L'app ne fait pas de suivi en direct** : les matchs terminés apparaissent quelques heures après la fin de la rencontre, et les matchs à venir avec leur date et leur heure (heure de Paris).

## Installation sous Windows

Prérequis : Python 3.13 ou plus récent, lancé avec la commande `py`, et Git. Toutes les commandes ci-dessous sont à taper dans **PowerShell**.

```powershell
git clone <url-du-depot> nfl-gameday   # ou copier le dossier
cd nfl-gameday
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

Si PowerShell refuse d'exécuter `Activate.ps1` (« l'exécution de scripts est désactivée sur ce système »), autorise les scripts locaux pour ton utilisateur, puis relance l'activation :

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Une fois le venv activé, la commande `py` utilise le Python du venv. Tu peux le vérifier avec `py -c "import sys; print(sys.executable)"`, qui doit afficher un chemin dans `.venv`.

## Lancement

```powershell
.venv\Scripts\Activate.ps1
py -m uvicorn app.main:app --reload
```

Ouvre ensuite <http://127.0.0.1:8000>.

Au tout premier lancement, l'app télécharge la saison, ce qui prend 5 à 10 secondes. Les lancements suivants lisent le cache local.

La documentation interactive de l'API se trouve à l'adresse <http://127.0.0.1:8000/docs>.

### Pages

| Page | Adresse | Contenu |
|---|---|---|
| Semaine | `#/week/8` | Les matchs de la semaine, groupés par jour (heure de Paris), avec le score final ou l'heure du coup d'envoi. Sélecteur Week 1 à 18, puis playoffs. Les flèches ← et → du clavier changent de semaine. |
| Match | `#/game/2026_08_CAR_GB` | Score final et par quart-temps, stade, météo si elle est connue, statistiques d'équipe comparées, cartes des joueurs clés. |
| Classement | `#/standings` | AFC et NFC, une table par division. |
| Joueur | `#/player/00-0036264` | Totaux de la saison et ligne match par match. |

## Actualisation des données

Les données sont gardées en cache dans `data/<saison>/`, sous forme de fichiers Parquet (environ 1,5 Mo) et d'un fichier `meta.json`.

- **Automatique** : si le cache a plus de **6 heures**, la requête suivante retélécharge la saison, ce qui la ralentit de quelques secondes.
- **Bouton « Actualiser »** : il se trouve en haut de la page et force un nouveau téléchargement.
- **En ligne de commande** :

  ```powershell
  py -m app.refresh                # saison en cours
  py -m app.refresh --season 2025  # une autre saison
  ```

Si le téléchargement échoue (réseau coupé, GitHub indisponible…), l'app continue d'afficher les données déjà en cache et ne réessaie pas avant 10 minutes.

Pour repartir de zéro, supprime le dossier `data\`.

## Tests

```powershell
py -m pytest
```

| Fichier | Ce qui est testé |
|---|---|
| `tests/test_key_players.py` | Logique des joueurs clés, sur les jeux d'exemple de `tests/fixtures/` (4-3, 3-4, absence de depth chart). |
| `tests/test_standings.py` | Calcul du classement. |
| `tests/test_data_layer.py` | Cache et normalisation. |
| `tests/test_api.py` | API de bout en bout, sur une mini-saison fictive sans accès réseau. |

Pour contrôler la sélection des joueurs clés sur un vrai match :

```powershell
py -m scripts.check_key_players 2026_08_CAR_GB
```

## Comment sont choisis les joueurs clés

Le détail est documenté en tête de [`app/data/key_players.py`](app/data/key_players.py). En résumé :

1. **Depth chart** : on prend le snapshot le plus récent pris **avant le coup d'envoi** du match.
2. **Attaque** : QB, RB1 et TE1 sont les joueurs de rang 1 à leur poste. WR1 et WR2 sont les deux premiers receveurs du classement des WR.
3. **Edges** : le choix dépend du schéma défensif de l'équipe.
   - En **4-3**, ce sont les DE gauche et droit (LDE et RDE).
   - En **3-4**, LDE et RDE jouent en fait à l'intérieur de la ligne. Les vrais pass rushers sont les linebackers extérieurs, SLB et WLB, affichés « OLB ».
4. **Titulaire qui n'a pas joué** : s'il n'a aucune stat dans le match, il est remplacé par le joueur du même poste le plus productif. Une mention discrète l'indique, par exemple « Remplace X (inactif) ». Le motif (inactif, en réserve, actif sans stat) vient du roster hebdomadaire.
5. **Sans depth chart** : le choix se fait sur la production du match. Par exemple, WR1 et WR2 sont les deux WR avec le plus de yards en réception.
6. **Défense** : on ajoute le meilleur plaqueur (plaquages solo et assistés), puis tous les joueurs ayant réussi un sack, une interception ou un fumble forcé.

## Architecture

```
app/
  main.py            FastAPI : API JSON et service du front
  refresh.py         commande py -m app.refresh
  data/
    cache.py         téléchargement nflverse, cache Parquet (TTL 6 h)
    derive.py        scores par quart-temps et 1ers downs, tirés du play-by-play
    models.py        modèles Pydantic (Game, TeamStats, PlayerLine, KeyPlayers…)
    normalize.py     lignes nflverse vers modèles (heure de Paris, valeurs manquantes)
    key_players.py   logique des joueurs clés
    standings.py     classement
    repository.py    accès aux données normalisées
  static/            front HTML/CSS/JS vanilla (routage par #)
scripts/             exploration des données et contrôles
tests/               pytest et jeux d'exemple (fixtures/)
```

Le front ne voit jamais les DataFrames bruts : il ne reçoit que les modèles Pydantic, en JSON.

| Endpoint | Rôle |
|---|---|
| `GET /api/meta` | Saison, semaines disponibles, semaine courante, date de mise à jour. |
| `GET /api/teams` | Les 32 équipes. |
| `GET /api/weeks/{n}` | Les matchs d'une semaine (19 à 22 pour les playoffs). |
| `GET /api/games/{game_id}` | Un match, avec stats d'équipe et joueurs clés. |
| `GET /api/standings` | Le classement. |
| `GET /api/players/{player_id}` | La saison d'un joueur. |
| `POST /api/refresh` | Forcer l'actualisation. |

## Source et limites

- **Source** : nflverse publie ses jeux de données sur GitHub. On utilise le calendrier et les résultats, les stats par joueur et par équipe, les depth charts (des snapshots ESPN datés), les rosters hebdomadaires, les équipes et le play-by-play.
- **Pas de direct** : nflverse met à jour ses données **quelques heures après les matchs**. Un match qui vient de se terminer peut donc encore apparaître « À venir », ou sans statistiques.
- **Météo** : elle n'est renseignée que pour une partie des matchs en extérieur, et quasiment jamais sous dôme. Elle s'affiche seulement quand elle existe.
- **Statistiques des joueurs** : `player_stats` ne contient que les joueurs ayant au moins une stat dans le match. Un titulaire présent sur le terrain mais sans aucune stat est donc traité comme un remplacé, avec la mention « actif sans stat ».
- **Classement** : le départage des égalités est simplifié (confrontations directes, puis division, conférence et différence de points). Les règles officielles de la NFL vont plus loin. Dans de rares cas d'égalité, l'ordre peut différer du classement officiel.
- **Playoffs** : les semaines WC, DIV, CONF et SB apparaissent dès que nflverse les ajoute au calendrier.
- **Visuels** : aucun logo officiel, les équipes sont désignées par leur abréviation. Les photos des joueurs (`headshot_url`) sont chargées depuis le CDN de la NFL et affichées en niveaux de gris.
- **Python** : le projet a été développé et testé avec Python 3.13.

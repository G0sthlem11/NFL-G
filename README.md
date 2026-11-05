# NFL Gameday

Web app personnelle qui affiche les résultats des matchs NFL de la saison en cours. Pour chaque match, on trouve les statistiques des deux équipes et une fiche des joueurs clés :

- en attaque : QB, RB1, WR1, WR2, TE1 ;
- en défense : les edges titulaires, le meilleur plaqueur, et les auteurs de sacks, d'interceptions et de fumbles forcés.

L'app propose aussi un classement par division et une page par joueur.

Les données viennent de [nflverse](https://github.com/nflverse), via le package Python [`nflreadpy`](https://pypi.org/project/nflreadpy/). **L'app ne fait pas de suivi en direct** : les matchs terminés apparaissent quelques heures après la fin de la rencontre, et les matchs à venir avec leur date et leur heure (heure de Paris).

## Deux façons de l'utiliser

| | Mode local | Mode statique (en ligne) |
|---|---|---|
| Lancement | `py -m uvicorn app.main:app --reload` | Site sur Vercel, accès réservé à ton compte |
| Données | API FastAPI (`/api/...`), cache local rafraîchi toutes les 6 h | Fichiers JSON (`/data/....json`) régénérés toutes les 6 h par une GitHub Action |
| Bouton « Actualiser » | Oui | Non : à la place, la mention « Données du [date, heure] » |
| Usage | Développement | Consultation depuis n'importe où (PC, téléphone) |

Le front est le même dans les deux cas. Il détecte le mode tout seul grâce au fichier `config.js`, que l'export statique remplace. Tu n'as rien à modifier.

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

## Export statique

```powershell
py -m app.export                       # saison en cours, dans dist\
py -m app.export --season 2025 --out build
py -m app.export --refresh             # force le téléchargement nflverse (échoue s'il échoue)
```

L'export interroge l'app FastAPI elle-même, en mémoire et sans réseau. Chaque fichier JSON est donc exactement la réponse de l'endpoint correspondant (un test le vérifie) :

| Endpoint | Fichier |
|---|---|
| `/api/meta` | `data/meta.json`, avec en plus `generated_at`, la date de génération |
| `/api/teams` | `data/teams.json` |
| `/api/standings` | `data/standings.json` |
| `/api/weeks/{n}` | `data/weeks/{n}.json` (playoffs inclus dès qu'ils sont au calendrier) |
| `/api/games/{game_id}` | `data/games/{game_id}.json` (matchs à venir inclus) |
| `/api/players/{player_id}` | `data/players/{player_id}.json` |

Le front (`app/static/`) est copié à la racine de `dist/`, en mode statique.

Repères pour la saison 2026 à la Week 8 :
- environ 2 000 fichiers, pour 9,4 Mo ;
- environ 70 s de génération.

Pour tester le site statique en local, **sans FastAPI** :

```powershell
py -m http.server 8080 -d dist
```

Ouvre ensuite <http://127.0.0.1:8080>.

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

## Déploiement (Vercel, accès privé)

### Comment ça marche

Le fichier `.github/workflows/deploy.yml` est une GitHub Action. Elle se déclenche dans trois cas :
- toutes les 6 h (à 00:17, 06:17, 12:17 et 18:17 UTC) ;
- à chaque push sur `main` ;
- à la demande, depuis l'onglet Actions.

À chaque exécution, elle enchaîne ces étapes :

1. Installer Python 3.13 et les dépendances.
2. Lancer `python -m app.export --refresh`, qui télécharge les données nflverse et génère `dist/`. **Si nflverse est injoignable, le workflow s'arrête ici** et le site garde sa version précédente.
3. Lancer les tests. S'ils échouent, rien n'est déployé.
4. Comparer l'empreinte des données à celle du dernier déploiement. Si rien n'a changé et que l'exécution est planifiée, le déploiement est sauté. Un push ou un lancement manuel déploie toujours.
5. Déployer `dist/` en production avec la CLI Vercel (`vercel pull`, `vercel build`, `vercel deploy --prebuilt --prod`).

Les données ne sont jamais commitées dans le dépôt. Vercel ne déploie rien de lui-même à chaque push (`"git": { "deploymentEnabled": false }` dans `vercel.json`) : seule l'Action déploie.

### Mise en place, étape par étape

Ces étapes se font une seule fois, dans ton navigateur.

**1. Créer le compte et le projet Vercel**

1. Va sur <https://vercel.com/signup>, choisis le plan **Hobby** (gratuit), puis **Continue with GitHub**.
2. Dans le tableau de bord, clique sur **Add New… → Project**.
3. Dans **Import Git Repository**, autorise Vercel à accéder à ton compte GitHub. Choisis **Only select repositories → NFL-G**, puis clique sur **Import**.
4. Sur l'écran de configuration :
   - garde le nom proposé, ou choisis-en un (il donnera l'adresse `<nom>.vercel.app`) ;
   - laisse **Framework Preset** et les réglages de build tels quels : `vercel.json` les remplace.
5. Clique sur **Deploy**. **Ce premier déploiement peut échouer** (« No Output Directory named "dist" found ») : c'est normal, `dist/` n'existe pas dans le dépôt. Ce sont les déploiements de l'Action qui comptent.

**2. Créer le token et récupérer les deux identifiants**

1. **Le token** :
   1. Ouvre <https://vercel.com/account/tokens> et clique sur **Create**.
   2. Nom : `github-actions-nfl-g`. Portée (scope) : ton compte. Expiration : à ton choix. Note la date : il faudra recréer le token et mettre à jour le secret à l'échéance.
   3. **Copie-le tout de suite** : il ne sera plus jamais affiché. C'est la valeur de `VERCEL_TOKEN`.
2. **`VERCEL_PROJECT_ID`** : dans le projet, ouvre **Settings → General**. Copie **Project ID**, qui commence par `prj_`.
3. **`VERCEL_ORG_ID`** :
   1. Avec le sélecteur d'équipe en haut à gauche, va sur ton compte (ta « team » personnelle).
   2. Ouvre **Settings → General**.
   3. Copie **Team ID**, qui commence par `team_`.

**3. Ajouter les trois secrets dans GitHub**

1. Sur <https://github.com/G0sthlem11/NFL-G>, va dans **Settings → Secrets and variables → Actions**.
2. Clique sur **New repository secret**, trois fois :

   | Name | Secret |
   |---|---|
   | `VERCEL_TOKEN` | le token de l'étape 2 |
   | `VERCEL_ORG_ID` | l'identifiant `team_…` |
   | `VERCEL_PROJECT_ID` | l'identifiant `prj_…` |

Tant que ces secrets manquent, l'Action fait l'export et les tests, puis saute le déploiement avec un avertissement (pas d'échec).

**4. Rendre le site privé**

1. Dans le projet Vercel, ouvre **Settings → Deployment Protection**.
2. Active **Vercel Authentication**.
3. Choisis la portée **All Deployments**, et non « Standard Protection », qui laisse l'URL de production publique.
4. Clique sur **Save**.

Avec cette portée, **toutes** les adresses demandent une connexion à ton compte Vercel, y compris l'URL de production. C'est disponible sur le plan Hobby, sans option payante.

**5. Premier déploiement et vérification**

1. Sur GitHub, va dans l'onglet **Actions**, choisis **Déploiement Vercel**, puis **Run workflow → main → Run workflow**.
2. Attends la coche verte, environ 4 à 5 minutes. Le résumé de l'exécution affiche l'URL déployée.
3. Dans Vercel, ton adresse de production apparaît dans **Project → Domains**, sous la forme `<nom>.vercel.app`.
4. Ouvre cette adresse dans une **fenêtre de navigation privée**. Tu dois tomber sur la page de connexion Vercel, et non sur le site. Connecte-toi : le site s'affiche.
5. Sur ton téléphone, connecte-toi une fois à Vercel dans le navigateur, puis ajoute le site à l'écran d'accueil.

### Limites de la version en ligne

- **Fraîcheur des données** : il faut compter jusqu'à **6 h de délai en plus** de celui de nflverse, qui publie quelques heures après les matchs. GitHub peut aussi retarder les exécutions planifiées de quelques minutes, parfois davantage. Pour forcer une mise à jour, lance le workflow à la main.
- **Minutes GitHub Actions** : une exécution dure environ 4 à 5 minutes, soit environ 500 minutes par mois. Le quota gratuit d'un dépôt privé est de 2 000 minutes par mois.
- **Token Vercel** : à son expiration, les déploiements échouent et le site reste sur sa dernière version. Il suffit alors de recréer le token et de mettre à jour le secret `VERCEL_TOKEN`.

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
  export.py          commande py -m app.export (site statique dans dist/)
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
vercel.json          configuration Vercel (sert dist/, en-têtes de cache)
.github/workflows/   deploy.yml : export et déploiement automatiques
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

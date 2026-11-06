# NFL Gameday

Web app personnelle qui affiche les résultats des matchs NFL de la saison en cours. Pour chaque match, on trouve les statistiques des deux équipes et les joueurs clés de chaque équipe :

- ses quarterbacks ;
- son top 5 offensif (yards et TD) et son top 3 défensif (interceptions, sacks, passes défendues, QB hits, pressions, plaquages) ;
- son kicker.

L'app propose aussi un classement par division et une page par joueur.

Les données viennent de [nflverse](https://github.com/nflverse), via le package Python [`nflreadpy`](https://pypi.org/project/nflreadpy/). **L'app ne fait pas de suivi en direct** : les matchs terminés apparaissent quelques heures après la fin de la rencontre, et les matchs à venir avec leur date et leur heure (heure de Paris).

## Deux façons de l'utiliser

| | Mode local | Mode statique (en ligne) |
|---|---|---|
| Lancement | `py -m uvicorn app.main:app --reload` | Site sur Vercel, accès réservé à ton compte |
| Données | API FastAPI (`/api/...`), cache local rafraîchi toutes les 6 h | Fichiers JSON (`/data/....json`) régénérés par une GitHub Action, chaque lendemain de matchs |
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
| Équipes | `#/standings` | Classement AFC et NFC, une table par division. |
| Joueurs | `#/rankings/WR` | Le titulaire de chaque équipe à chaque poste (QB, RB, WR, TE, EDGE, DT, LB, CB, S, K), classé de 1 à 32. Tri par colonne, total de la saison ou moyenne par match. |
| Joueur | `#/player/00-0036264` | Totaux de la saison et ligne match par match, limités aux stats clés du poste (QB, offensif, défensif ; fiche complète pour les autres postes). |

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
| `tests/test_key_players.py` | Joueurs clés par équipe : quarterbacks, scores et départages, pressions absentes, kickers, joueur échangé, abréviations d'équipe, fichier de pondérations. |
| `tests/test_rankings.py` | Classements par poste : sources de position, titulaire aux snaps, joueur échangé, moyenne par match et minimum de matchs, kicker. |
| `tests/test_team_assets.py` | Couleurs d'équipe (contraste), chemins des logos, et version 48 px de chaque logo. |
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
- une fois par jour à 08:17 UTC (09:17 à Paris l'hiver), seulement les lendemains de matchs (dimanche, lundi, mardi, vendredi) et seulement de septembre à février ;
- à chaque push sur `main`, sauf si seuls des fichiers `.md` ou `scripts/` changent. Le push réutilise les données en cache si elles ont moins de 6 h ;
- à la demande, depuis l'onglet Actions (**Run workflow**), avec ou sans retéléchargement des données.

Consommation : environ 1 minute par exécution. Le calendrier prévoit 4 exécutions par semaine (dimanche, lundi, mardi, vendredi), soit environ 17 par mois de septembre à février, et aucune hors saison. Cela fait **une vingtaine de minutes par mois** en saison, plus une minute par push ou par lancement manuel (quota gratuit d'un dépôt privé : 2 000). Les dépendances pip, les paquets npm de la CLI Vercel et les données nflverse sont en cache entre deux exécutions ; la saison précédente, figée, n'est jamais retéléchargée. Une exécution bloquée s'arrête au bout de 15 minutes, et une nouvelle exécution annule celle en cours.

À chaque exécution, elle enchaîne ces étapes :

1. Installer Python 3.13 et les dépendances.
2. Lancer `python -m app.export --refresh` (sans `--refresh` sur un push), qui télécharge les données nflverse et génère `dist/`. **Si nflverse est injoignable, le workflow s'arrête ici** et le site garde sa version précédente.
3. Lancer les tests Python, puis ceux du middleware de protection (`node --test`). S'ils échouent, rien n'est déployé.
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

**4. Créer le mot de passe et la clé de session**

Le site est protégé par un mot de passe, vérifié par `middleware.js` (voir « Protection du site » plus bas). Il lit deux variables d'environnement Vercel. **Elles ne doivent jamais apparaître dans le code ni dans le dépôt.**

1. Génère les deux valeurs sur ton PC, dans PowerShell. Chaque commande affiche une valeur aléatoire à copier :

   ```powershell
   # Mot de passe (24 caractères) : à garder dans ton gestionnaire de mots de passe
   $b = New-Object byte[] 18; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)
   # Clé de session (64 caractères) : tu n'en auras plus besoin après l'avoir collée dans Vercel
   $b = New-Object byte[] 48; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)
   ```

2. Dans le projet Vercel, ouvre **Settings → Environment Variables**. Ajoute les deux variables, en cochant au moins l'environnement **Production** :

   | Key | Value |
   |---|---|
   | `APP_PASSWORD` | le mot de passe (12 caractères minimum) |
   | `SESSION_SECRET` | la clé de session (32 caractères minimum) |

   Si tu le peux, coche **Sensitive** : la valeur ne sera plus affichée.

3. Une variable ajoutée ou modifiée ne prend effet **qu'au déploiement suivant**. Relance le workflow depuis l'onglet Actions.

Tant qu'une variable manque ou est trop courte, le site refuse tout avec une erreur 503, sauf les icônes. Il ne s'ouvre jamais par défaut.

**5. Régler la protection Vercel**

1. Dans le projet Vercel, ouvre **Settings → Deployment Protection**.
2. Laisse **Vercel Authentication** activé, mais choisis la portée **Standard Protection** au lieu de « All Deployments ».
3. Clique sur **Save**.

Avec ce réglage :
- l'adresse de production (`nfl-g.vercel.app`) est protégée par ton mot de passe, ce qui permet à Chrome et à Google de récupérer le manifeste et les icônes ;
- les adresses techniques de chaque déploiement (`nfl-g-xxxx.vercel.app`) restent derrière la connexion Vercel.

**6. Premier déploiement et vérification**

1. Sur GitHub, va dans l'onglet **Actions**, choisis **Déploiement Vercel**, puis **Run workflow → main → Run workflow**.
2. Attends la coche verte, environ 1 minute. Le résumé de l'exécution affiche l'URL déployée.
3. Ouvre <https://nfl-g.vercel.app> dans une **fenêtre de navigation privée** : la page « Accès privé » de Gameday doit s'afficher. Saisis le mot de passe : le site s'affiche.
4. Sur ton téléphone, ouvre le site dans Chrome et connecte-toi. Choisis ensuite **⋮ → Installer l'application** (ou « Ajouter à l'écran d'accueil » puis « Installer »). L'app s'ouvre alors en plein écran. La session dure un an.

Pour contrôler la protection depuis un terminal, sans session :

```powershell
curl.exe -s -o NUL -w "%{http_code} %{redirect_url}`n" https://nfl-g.vercel.app/              # 302 vers /login
curl.exe -s -o NUL -w "%{http_code}`n" https://nfl-g.vercel.app/data/meta.json                # 401
curl.exe -s -o NUL -w "%{http_code} %{content_type}`n" https://nfl-g.vercel.app/icon-512.png  # 200 image/png
```

### Protection du site

C'est `middleware.js`, un Routing Middleware Vercel, qui protège le site en ligne. Il s'exécute avant chaque requête, sans aucune dépendance.

- **Accessibles sans connexion** : uniquement `manifest.webmanifest`, les quatre icônes PNG, `favicon.svg` et la page `/login`. C'est ce qu'il faut à Chrome, et aux serveurs de Google, pour créer l'application installable sur Android.
- **Tout le reste exige un cookie de session valide**, y compris `/data/*.json`. Sans cookie, les pages renvoient vers `/login` et les données répondent 401 ; le front renvoie alors vers la connexion, puis ramène sur la page demandée.
- **Cookie `gd_session`** : signé en HMAC-SHA256 avec `SESSION_SECRET`, `HttpOnly`, `Secure`, `SameSite=Lax`, valable **un an**.
  - Le lien « Se déconnecter », en pied de page, efface le cookie de l'appareil.
  - **Changer `SESSION_SECRET` puis redéployer déconnecte tous les appareils.**
- **Essais en boucle** : chaque échec ajoute un délai d'environ 1,5 s. Au-delà de 5 échecs en 15 minutes depuis une même adresse IP, la connexion est refusée (429). Ce compteur vit dans la mémoire de chaque instance du middleware et n'est pas partagé. **La vraie protection reste un mot de passe long et aléatoire**, d'où la commande de génération ci-dessus.
- **Tests** : `node --test "tests/js/*.test.js"` (Node 22).
- **Mode local** : le middleware ne sert que sur Vercel. Le mode local avec FastAPI n'est pas protégé, et n'a pas besoin de l'être.

### Limites de la version en ligne

- **Fraîcheur des données** : les stats d'un match arrivent le lendemain matin (exécution de 08:17 UTC), à condition que nflverse les ait publiées ; sinon, à l'exécution suivante. GitHub peut aussi retarder les exécutions planifiées de quelques minutes, parfois davantage. Pour forcer une mise à jour, lance le workflow à la main.
- **Minutes GitHub Actions** : une exécution dure environ 1 minute, soit **une vingtaine de minutes par mois** en saison (environ 17 exécutions planifiées), plus une minute par push ou par lancement manuel. Le quota gratuit d'un dépôt privé est de 2 000 minutes par mois.
- **Token Vercel** : à son expiration, les déploiements échouent et le site reste sur sa dernière version. Il suffit alors de recréer le token et de mettre à jour le secret `VERCEL_TOKEN`.
- **Niveau de protection** : un mot de passe unique protège moins bien qu'un compte Vercel avec double authentification. Pour des statistiques NFL publiques, c'est un compromis acceptable. Garde le mot de passe pour toi seul, et change `SESSION_SECRET` en cas de doute.

## Comment sont choisis les joueurs clés

Le détail est documenté en tête de [`app/data/key_players.py`](app/data/key_players.py). Tout est calculé sur les stats du match (`load_player_stats`, niveau hebdomadaire), **séparément pour chaque équipe**. La page affiche une colonne par équipe, dans l'ordre du tableau de score : l'équipe à l'extérieur à gauche, l'équipe à domicile à droite (l'une sous l'autre sur mobile). Pour chaque équipe :

1. **Quarterbacks** : tous les QB qui ont tenté au moins une passe.
2. **Top 5 offensif**, QB exclus : `yards course + yards réception + 20 × TD (course + réception)`.
3. **Top 3 défensif** : `6 × INT + 4 × sacks + 3 × passes défendues + 2 × QB hits + 1,5 × pressions + 1 × plaquages (solo + assistés)`.
   - Les pressions viennent des stats avancées PFR (`load_pfr_advstats`, type `def`), reliées aux joueurs nflverse par `load_players` (`pfr_id` → `gsis_id`), puis jointes par joueur et par match.
   - Si PFR ne couvre pas un match, le score est calculé sans les pressions, et la page le signale.
4. **Kicker**, avec ses field goals réussis sur tentés, son plus long FG et ses extra points.

Une équipe qui a moins de 5 joueurs offensifs ou de 3 défensifs avec des stats n'affiche que ceux qui existent.

**Équipe d'un joueur** : c'est celle de sa ligne de stats pour ce match (colonne `team`), pas son équipe actuelle. Un joueur échangé en cours de saison apparaît avec l'équipe pour laquelle il a joué ce jour-là : en 2026, Marvin Harrison Jr. figure avec ARI en Week 4, puis avec HOU en Week 7. Les abréviations sont ramenées à celles du calendrier (LAR → LA, JAC → JAX, WSH → WAS, OAK → LV…). Un joueur qui n'appartient à aucune des deux équipes du match est écarté et signalé par une erreur dans les logs.

Les égalités se départagent toujours dans le même ordre :
- **attaque** : le plus de TD, puis de yards, puis de réceptions ;
- **défense** : le plus d'interceptions et de sacks, puis de plaquages ;
- **en dernier recours** : le nom, puis l'identifiant du joueur.

**MVP du match** : un seul joueur, choisi parmi les joueurs clés de l'équipe gagnante (des deux équipes en cas de match nul). Chaque catégorie a son score brut :
- **QB** : `0,4 × yards passe + 15 × TD passe − 20 × INT + yards course + 20 × TD course` ;
- **offensif** et **défensif** : les scores des tops ;
- **kicker** : `3 × FG réussi + 1 × extra point + 1 par FG réussi de 50 yards ou plus`.

Ces scores n'ont pas la même échelle : un grand match défensif fait environ 35 points, un grand match offensif environ 200. Chaque score est donc converti en **percentile dans sa catégorie**. La référence est la distribution, sur la saison, du meilleur score de chaque équipe dans chaque match, parmi les joueurs réellement impliqués (QB avec au moins 10 passes, au moins une touche de balle, au moins une stat défensive, au moins une tentative au pied).

Comparer au meilleur de chaque équipe, plutôt qu'à toutes les lignes, évite un biais : une équipe a une vingtaine de défenseurs avec une stat mais un seul QB. Contre toutes les lignes, la défense remportait 77 MVP sur 121 en 2026, et les QB 5.

Le MVP est le percentile le plus élevé. Celui du kicker est multiplié par 0,66, pour qu'il ne gagne que sur un match décisif. En début de saison (moins de 48 matchs joués), la saison précédente complète les distributions. Les scores bruts des tops ne changent pas : le percentile ne sert qu'à désigner le MVP.

Dans les joueurs clés, la carte du MVP porte un badge « MVP » et un fin liseré à la couleur de son équipe. Pour vérifier les choix sur la saison, ou sur des matchs précis : `py -m scripts.calibrate_mvp [game_id ...]`.

Les pondérations, la taille des classements et le barème du MVP sont dans [`app/data/key_players.toml`](app/data/key_players.toml). Après une modification, relance l'app ou l'export. La page du match affiche les pondérations réellement utilisées.

Pour vérifier le classement d'un match, avec le détail des scores : `py -m scripts.check_key_players 2026_08_CAR_GB`.

## Comment sont faits les classements par poste

Réglages : section `[rankings]` de [`app/data/key_players.toml`](app/data/key_players.toml) ; logique : `app/data/rankings.py`.

- **Poste** : la première position reconnue parmi `pff_position`, `ngs_position` et `position` (table `load_players`), puis la position des snaps et celle de `player_stats`. `pff_position` passe en premier parce qu'il distingue les pass rushers (`ED`) des linebackers (`LB`), alors que `position` met LB ou OLB pour les deux. Les codes de chaque poste (EDGE = ED, EDGE, DE, OLB…) sont dans la config.
- **Titulaire** : dans chaque équipe, le joueur du poste qui a le plus de snaps sur la saison (`load_snap_counts`, offensifs ou défensifs selon le poste) ; pour le kicker, le plus de matchs joués. Un joueur échangé compte pour l'équipe où il a le plus joué (en 2026, Jeffery Simmons compte pour TEN, pas pour CHI).
- **Score** : celui de la catégorie (score QB, offensif, défensif ou barème kicker du MVP), additionné sur toute la saison, puis divisé par les matchs joués. Sous `min_games` matchs (4), le joueur est grisé en fin de classement.

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
    key_players.py   joueurs clés d'un match (QB, tops offensif et défensif, kickers)
    key_players.toml pondérations des joueurs clés
    rankings.py      classements par poste (titulaire de chaque équipe)
    standings.py     classement
    team_assets.py   couleurs d'équipe (contraste) et chemins des logos (128 et 48 px)
    repository.py    accès aux données normalisées
  static/            front HTML/CSS/JS vanilla (routage par #)
    anim.js          animations discrètes (fondus, cascade, compteurs), coupées si prefers-reduced-motion
    vendor/motion.js Motion 14.4.0 (https://motion.dev, MIT), copie locale
    logos/           logos des équipes (128 px), logos/dark/ pour le thème sombre, logos/48/ en petit
scripts/             exploration des données et contrôles
tests/               pytest et jeux d'exemple (fixtures/)
vercel.json          configuration Vercel (sert dist/, en-têtes de cache)
middleware.js        protection par mot de passe du site en ligne (Routing Middleware)
package.json         déclare middleware.js en module ES ; aucune dépendance
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
| `GET /api/rankings` | Les classements par poste. |
| `GET /api/players/{player_id}` | La saison d'un joueur. |
| `POST /api/refresh` | Forcer l'actualisation. |

## Source et limites

- **Source** : nflverse publie ses jeux de données sur GitHub. On utilise le calendrier et les résultats, les stats par joueur et par équipe, les stats avancées défensives de PFR (pressions), la table des joueurs (correspondance des identifiants PFR et nflverse, positions), les snaps par match (PFR), les équipes et le play-by-play.
- **Pas de direct** : nflverse met à jour ses données **quelques heures après les matchs**. Un match qui vient de se terminer peut donc encore apparaître « À venir », ou sans statistiques.
- **Météo** : elle n'est renseignée que pour une partie des matchs en extérieur, et quasiment jamais sous dôme. Elle s'affiche seulement quand elle existe.
- **Statistiques des joueurs** : `player_stats` ne contient que les joueurs ayant au moins une stat dans le match. Un titulaire présent sur le terrain mais sans aucune stat est donc traité comme un remplacé, avec la mention « actif sans stat ».
- **Classement** : le départage des égalités est simplifié (confrontations directes, puis division, conférence et différence de points). Les règles officielles de la NFL vont plus loin. Dans de rares cas d'égalité, l'ordre peut différer du classement officiel.
- **Playoffs** : les semaines WC, DIV, CONF et SB apparaissent dès que nflverse les ajoute au calendrier.
- **Couleurs et logos** :
  - **Couleurs** : `team_color` / `team_color2` de nflverse. Elles ne servent plus qu'aux liserés (carte du MVP, gagnant dans l'en-tête d'un match). Chaque équipe prend sa couleur secondaire quand la principale contraste trop peu avec le fond (moins de 2:1, calcul WCAG dans `app/data/team_assets.py`), séparément pour le thème clair et le sombre.
  - **Logos partout** : chaque équipe s'affiche avec son logo et son abréviation de 3 lettres, sans son nom en toutes lettres (il apparaît au survol). Un seul composant les produit, `teamBadge` dans `app.js` : page Semaine, équipes au repos, classement, classements par poste, page joueur, titres des joueurs clés. Seuls les tableaux par quart-temps et de stats d'équipe gardent l'abréviation seule, puisque les grands logos sont juste au-dessus.
  - **Tailles** : 22 px dans les listes, 20 px dans le classement, 18 px dans les tableaux, 24 px dans les titres. Les grands logos de l'en-tête d'un match font 88 px (64 px sur mobile).
  - **Fichiers** : les logos (ESPN, via `team_logo_espn`) sont copiés dans `app/static/logos/` en 128 px, avec la variante ESPN pour fond sombre dans `logos/dark/`. Le thème sombre bascule tout seul sur cette variante (`<picture>` et `prefers-color-scheme`). Pour les retélécharger : `py -m scripts.fetch_logos`.
  - **Petits logos** : les grands logos de 128 px servent à l'en-tête d'un match ; partout ailleurs, on utilise des versions de 48 px (`logos/48/` et `logos/48/dark/`), qui suffisent pour un écran haute densité. Avec une palette de 256 couleurs, les 72 fichiers passent de 494 Ko à 124 Ko (75 % de moins, environ 1,7 Ko par logo). Pour les régénérer après `fetch_logos` : `py -m scripts.resize_logos`. Ce script exige Pillow (`py -m pip install pillow`), dont ni l'app ni l'Action n'ont besoin, puisque les fichiers sont versionnés.
  - **Chargement et accessibilité** : `width` et `height` fixes (pas de saut de mise en page), et `loading="lazy"` hors de l'écran initial. L'`alt` est vide, car l'abréviation, juste à côté, est lue une seule fois. Si un logo ne charge pas, il disparaît et l'abréviation reste.
- **Photos des joueurs** : les photos des joueurs (`headshot_url`) sont chargées depuis le CDN de la NFL, qui les recadre sur le visage à 4 fois la taille affichée (l'original fait 3400 × 2450 px et 4 à 6 Mo). Sans photo, une silhouette neutre s'affiche.
- **Python** : le projet a été développé et testé avec Python 3.13.

"""Joueurs clés d'un match, calculés sur les stats du match (player_stats,
niveau hebdomadaire de nflverse), **séparément pour chacune des deux équipes**.

Pour chaque équipe :

1. **Quarterbacks** : ses QB qui ont tenté au moins une passe, par nombre de
   passes tentées.

2. **Top offensif** (5 par défaut), QB exclus puisqu'ils ont leur section :
   ``score = yards course + yards réception + 20 × TD (course + réception)``.
   Égalités : plus de TD, puis plus de yards, puis plus de réceptions.

3. **Top défensif** (3 par défaut) :
   ``score = 6 × INT + 4 × sacks + 3 × passes défendues + 2 × QB hits
   + 1,5 × pressions + 1 × plaquages (solo + assistés)``.
   Égalités : plus de « gros jeux » (INT + sacks), puis plus de plaquages.
   Les pressions viennent des stats avancées PFR (``load_pfr_advstats``,
   type « def »), jointes par joueur et par match. Si PFR n'a rien pour ce
   match, le score est calculé sans les pressions (``pressures_available``
   vaut alors False) ; un joueur absent des lignes PFR d'un match couvert
   compte 0 pression. Seuls les joueurs présents dans player_stats sont
   classés : ceux qui n'ont que des pressions (aucune autre stat) culminent à
   2 pressions sur la saison 2026, soit 3 points, loin d'un top 3.

4. **Kicker** : le ou les kickers ayant tenté un field goal ou un extra point
   (ou listés K), avec FG réussis/tentés, plus long FG et extra points.

Une équipe qui a moins de joueurs avec des stats que la taille du classement
n'affiche que ceux qui existent.

**Équipe d'un joueur** : celle de la colonne ``team`` de sa ligne de stats
*pour ce match*, pas son équipe actuelle. Un joueur échangé en cours de saison
apparaît donc avec l'équipe pour laquelle il a joué ce jour-là. Les
abréviations sont ramenées à celles du calendrier (``canonical_team`` : LAR →
LA, JAC → JAX…). Une ligne dont l'équipe n'est aucune des deux du match est
écartée et signalée dans les logs (erreur), de même que tout joueur classé
qui ne serait pas dans l'équipe de sa colonne.

**MVP** : un seul joueur par match, choisi parmi les joueurs clés de
l'équipe gagnante (des deux équipes en cas de match nul). Chaque catégorie a
son score brut (section ``[mvp]`` du TOML) :

- QB : ``0,4 × yards passe + 15 × TD passe − 20 × INT + yards course
  + 20 × TD course`` ;
- offensif : le score du top offensif ;
- défensif : le score du top défensif ;
- kicker : ``3 × FG réussis + 1 × extra point + 1 par FG réussi de 50 yards
  ou plus``.

Ces scores n'ont pas la même échelle (un grand match défensif fait ~35
points, un grand match offensif ~200). Pour les comparer, chacun est converti
en **percentile au sein de sa catégorie** (``MvpScale``). La référence de
chaque catégorie est la distribution, sur la saison, du **meilleur score de
chaque équipe dans chaque match** (une valeur par équipe et par match), parmi
les joueurs réellement impliqués : QB avec au moins 10 passes tentées, joueur
offensif avec au moins une touche de balle, défenseur avec au moins une stat
défensive, kicker avec au moins une tentative. Comparer au meilleur de chaque
équipe plutôt qu'à toutes les lignes évite un biais de taille : une équipe a
une vingtaine de défenseurs avec une stat, mais un seul QB ; contre toutes les
lignes, le meilleur défenseur d'une équipe serait toujours vers le 95e
percentile, et un bon QB vers le 50e.

Le kicker reçoit un malus (``kicker_factor`` × son percentile), pour qu'il ne
soit MVP que sur un match vraiment décisif. En début de saison (moins de
``min_reference_games`` matchs joués), la saison précédente complète les
distributions. Les scores bruts des tops par catégorie ne changent pas : le
percentile ne sert qu'à désigner le MVP.

Un joueur présent dans deux catégories garde son meilleur percentile.
Égalité : le score brut, puis le nom et l'identifiant du joueur.

Dernier départage, dans tous les cas : le nom puis l'identifiant du joueur,
pour un ordre toujours identique d'un calcul à l'autre.

Les pondérations et tailles des classements sont dans ``key_players.toml``.
"""
from __future__ import annotations

import bisect
import logging
import tomllib
from collections.abc import Iterable
from pathlib import Path

import polars as pl

from .models import MatchKeyPlayers, Mvp, PlayerLine, RankedPlayer, TeamKeyPlayers
from .normalize import to_player_line

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).with_name("key_players.toml")

DEFAULTS = {
    "offense": {"top": 5, "rushing_yards": 1.0, "receiving_yards": 1.0, "touchdowns": 20.0},
    "defense": {"top": 3, "interceptions": 6.0, "sacks": 4.0, "passes_defended": 3.0,
                "qb_hits": 2.0, "pressures": 1.5, "tackles": 1.0},
    "mvp": {"qb_passing_yards": 0.4, "qb_passing_tds": 15.0, "qb_interceptions": 20.0,
            "qb_rushing_yards": 1.0, "qb_rushing_tds": 20.0,
            "kicker_fg": 3.0, "kicker_xp": 1.0, "kicker_fg_50_bonus": 1.0,
            "kicker_factor": 0.66, "qb_min_attempts": 10, "offense_min_touches": 1,
            "kicker_min_attempts": 1, "min_reference_games": 48},
    "rankings": {
        "min_games": 4,
        "position_sources": ["pff_position", "ngs_position", "position", "snaps", "stats"],
        "groups": {
            "QB": {"score": "qb", "codes": ["QB"]},
            "RB": {"score": "offense", "codes": ["RB", "HB"]},
            "WR": {"score": "offense", "codes": ["WR", "SLOT_WR"]},
            "TE": {"score": "offense", "codes": ["TE"]},
            "EDGE": {"score": "defense", "codes": ["ED", "EDGE", "DE", "OLB"]},
            "DT": {"score": "defense", "codes": ["DI", "DT", "NT", "DL", "INTERIOR_LINE"]},
            "LB": {"score": "defense", "codes": ["LB", "ILB", "MLB"]},
            "CB": {"score": "defense", "codes": ["CB", "SLOT_CB", "DB"]},
            "S": {"score": "defense", "codes": ["S", "FS", "SS", "SAF", "SAFETY", "HIGH_SAFETY"]},
            "K": {"score": "kicker", "codes": ["K", "PK", "FK"]},
        },
    },
}

# Variantes d'abréviations rencontrées selon les sources et les saisons,
# ramenées à celles du calendrier nflverse (schedules).
TEAM_ALIASES = {
    "LAR": "LA", "STL": "LA", "SL": "LA",
    "JAC": "JAX",
    "WSH": "WAS",
    "OAK": "LV", "LVR": "LV",
    "SD": "LAC", "SDG": "LAC",
    "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU",
    "GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB",
}


def canonical_team(abbr: str | None) -> str | None:
    if abbr is None:
        return None
    a = str(abbr).strip().upper()
    return TEAM_ALIASES.get(a, a)


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Pondérations du fichier TOML, complétées par les valeurs par défaut."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    return {section: {**values, **raw.get(section, {})} for section, values in DEFAULTS.items()}


def _n(v) -> float:
    return float(v) if v is not None else 0.0


def offense_score(p: PlayerLine, w: dict) -> float:
    tds = _n(p.rushing_tds) + _n(p.receiving_tds)
    return (w["rushing_yards"] * _n(p.rushing_yards) + w["receiving_yards"] * _n(p.receiving_yards)
            + w["touchdowns"] * tds)


def defense_score(p: PlayerLine, w: dict, with_pressures: bool) -> float:
    score = (w["interceptions"] * _n(p.def_interceptions) + w["sacks"] * _n(p.sacks)
             + w["passes_defended"] * _n(p.passes_defended) + w["qb_hits"] * _n(p.qb_hits)
             + w["tackles"] * _n(p.tackles))
    if with_pressures:
        score += w["pressures"] * _n(p.pressures)
    return score


def qb_mvp_score(p: PlayerLine, w: dict) -> float:
    return (w["qb_passing_yards"] * _n(p.passing_yards) + w["qb_passing_tds"] * _n(p.passing_tds)
            - w["qb_interceptions"] * _n(p.interceptions)
            + w["qb_rushing_yards"] * _n(p.rushing_yards) + w["qb_rushing_tds"] * _n(p.rushing_tds))


def kicker_mvp_score(p: PlayerLine, w: dict) -> float:
    return (w["kicker_fg"] * _n(p.fg_made) + w["kicker_xp"] * _n(p.pat_made)
            + w["kicker_fg_50_bonus"] * _n(p.fg_made_50))


CATEGORIES = ("qb", "offense", "defense", "kicker")


def _raw_scores(p: PlayerLine, cfg: dict, with_pressures: bool) -> dict[str, float]:
    """Scores bruts d'une ligne de stats, pour les catégories où le joueur est
    réellement impliqué (seuils de la section [mvp])."""
    w = cfg["mvp"]
    out: dict[str, float] = {}
    if p.position == "QB" and _n(p.attempts) >= w["qb_min_attempts"]:
        out["qb"] = qb_mvp_score(p, w)
    if p.position != "QB" and _n(p.carries) + _n(p.receptions) >= w["offense_min_touches"]:
        out["offense"] = offense_score(p, cfg["offense"])
    if _is_defensive_contributor(p):
        out["defense"] = defense_score(p, cfg["defense"], with_pressures)
    if p.position == "K" and _n(p.fg_att) + _n(p.pat_att) >= w["kicker_min_attempts"]:
        out["kicker"] = kicker_mvp_score(p, w)
    return out


class MvpScale:
    """Distributions de référence du MVP : pour chaque catégorie, le meilleur
    score brut de chaque équipe dans chaque match (voir l'en-tête du module)."""

    def __init__(self, leaders: dict[str, list[float]], games: int = 0, seasons: tuple[int, ...] = ()):
        self.sorted = {c: sorted(leaders.get(c, [])) for c in CATEGORIES}
        self.games = games
        self.seasons = seasons

    @classmethod
    def from_stats(cls, frames: Iterable[tuple[pl.DataFrame, pl.DataFrame | None]], cfg: dict | None = None,
                   seasons: tuple[int, ...] = ()) -> "MvpScale":
        """``frames`` : couples (player_stats, pressions PFR) d'une ou plusieurs saisons."""
        cfg = cfg or load_config()
        best: dict[str, dict[tuple[str, str], float]] = {c: {} for c in CATEGORIES}
        games: set[str] = set()
        for stats, pfr in frames:
            if stats is None or stats.is_empty():
                continue
            press: dict[tuple[str, str], float] = {}
            covered: set[str] = set()
            if pfr is not None and not pfr.is_empty():
                covered = set(pfr["game_id"].unique().to_list())
                for r in pfr.drop_nulls("player_id").iter_rows(named=True):
                    k = (r["game_id"], r["player_id"])
                    press[k] = press.get(k, 0.0) + _n(r["pressures"])
            for row in stats.iter_rows(named=True):
                if not row.get("player_id") or not row.get("game_id"):
                    continue
                p = to_player_line({**row, "team": canonical_team(row.get("team")) or ""})
                wp = row["game_id"] in covered
                if wp:
                    p.pressures = press.get((row["game_id"], p.player_id), 0.0)
                games.add(row["game_id"])
                key = (row["game_id"], p.team)
                for cat, score in _raw_scores(p, cfg, wp).items():
                    if score > best[cat].get(key, float("-inf")):
                        best[cat][key] = score
        return cls({c: list(v.values()) for c, v in best.items()}, games=len(games), seasons=seasons)

    def percentile(self, category: str, score: float) -> float | None:
        """Rang centile (0 à 100) : part des références sous ce score, les
        égalités comptant pour moitié. None si la catégorie n'a pas de référence."""
        ref = self.sorted.get(category) or []
        if not ref:
            return None
        lo, hi = bisect.bisect_left(ref, score), bisect.bisect_right(ref, score)
        return round(100.0 * (lo + hi) / 2 / len(ref), 1)


def mvp_candidates(side: TeamKeyPlayers, cfg: dict, scale: MvpScale) -> list[Mvp]:
    """Joueurs clés d'une équipe, chacun avec son percentile MVP (meilleure catégorie)."""
    w = cfg["mvp"]
    best: dict[str, Mvp] = {}

    def add(p: PlayerLine, category: str, raw: float) -> None:
        pct = scale.percentile(category, raw)
        if pct is None:
            return
        value = pct * (w["kicker_factor"] if category == "kicker" else 1.0)
        cur = best.get(p.player_id)
        if cur is None or (value, raw) > (cur.normalized, cur.score):
            best[p.player_id] = Mvp(player=p, category=category, score=round(raw, 1),
                                    percentile=pct, normalized=round(value, 1))

    for p in side.quarterbacks:
        add(p, "qb", qb_mvp_score(p, w))
    for r in side.offense:
        add(r.player, "offense", r.score)
    for r in side.defense:
        add(r.player, "defense", r.score)
    for p in side.kickers:
        add(p, "kicker", kicker_mvp_score(p, w))
    return list(best.values())


def select_mvp(away: TeamKeyPlayers, home: TeamKeyPlayers, away_score: int | None,
               home_score: int | None, cfg: dict, scale: MvpScale | None) -> Mvp | None:
    """MVP parmi les joueurs clés de l'équipe gagnante (des deux en cas de nul)."""
    if away_score is None or home_score is None or scale is None:
        return None
    sides = [away] if away_score > home_score else [home] if home_score > away_score else [away, home]
    pool = [c for s in sides for c in mvp_candidates(s, cfg, scale)]
    if not pool:
        return None
    return min(pool, key=lambda c: (-c.normalized, -c.score, c.player.name, c.player.player_id))


def _is_offensive_contributor(p: PlayerLine) -> bool:
    return any(_n(v) for v in (p.carries, p.targets, p.receptions, p.rushing_yards,
                               p.receiving_yards, p.rushing_tds, p.receiving_tds))


def _is_defensive_contributor(p: PlayerLine) -> bool:
    return any(_n(v) for v in (p.tackles, p.sacks, p.def_interceptions, p.passes_defended,
                               p.qb_hits, p.pressures))


def _rank(scored: list[tuple[float, tuple, PlayerLine]], top: int) -> list[RankedPlayer]:
    scored.sort(key=lambda t: (-t[0], *t[1], t[2].name, t[2].player_id))
    return [RankedPlayer(rank=i + 1, score=round(s, 1), player=p) for i, (s, _, p) in enumerate(scored[:top])]


def _team_key_players(team: str, players: list[PlayerLine], cfg: dict, with_pressures: bool) -> TeamKeyPlayers:
    qbs = sorted((p for p in players if p.position == "QB" and _n(p.attempts) >= 1),
                 key=lambda p: (-_n(p.attempts), p.name, p.player_id))

    wo = cfg["offense"]
    offense = _rank([
        (offense_score(p, wo),
         (-(_n(p.rushing_tds) + _n(p.receiving_tds)), -(_n(p.rushing_yards) + _n(p.receiving_yards)),
          -_n(p.receptions)),
         p)
        for p in players if p.position != "QB" and _is_offensive_contributor(p)
    ], int(wo["top"]))

    wd = cfg["defense"]
    defense = _rank([
        (defense_score(p, wd, with_pressures),
         (-(_n(p.def_interceptions) + _n(p.sacks)), -_n(p.tackles)),
         p)
        for p in players if _is_defensive_contributor(p)
    ], int(wd["top"]))

    kickers = sorted((p for p in players if p.position == "K" or _n(p.fg_att) or _n(p.pat_att)),
                     key=lambda p: (-(_n(p.fg_att) + _n(p.pat_att)), p.name, p.player_id))
    return TeamKeyPlayers(team=team, quarterbacks=qbs, offense=offense, defense=defense, kickers=kickers)


def _check_teams(game_id: str, side: TeamKeyPlayers) -> None:
    """Contrôle : tout joueur affiché dans une colonne appartient à son équipe."""
    shown = side.quarterbacks + [r.player for r in side.offense + side.defense] + side.kickers
    for p in shown:
        if p.team != side.team:
            log.error("Joueurs clés %s : %s (%s) affiché avec %s mais a joué pour %s",
                      game_id, p.name, p.player_id, side.team, p.team)


def select_match_key_players(
    stats: pl.DataFrame,
    away: str,
    home: str,
    pressures: pl.DataFrame | None = None,
    config: dict | None = None,
    game_id: str = "",
    away_score: int | None = None,
    home_score: int | None = None,
    mvp_scale: MvpScale | None = None,
) -> MatchKeyPlayers:
    """``stats`` : lignes player_stats du match (les deux équipes).
    ``pressures`` : lignes PFR du match (colonnes player_id, pressures), ou
    vide si PFR ne couvre pas ce match."""
    cfg = config or load_config()
    away, home = canonical_team(away), canonical_team(home)
    with_pressures = pressures is not None and not pressures.is_empty()
    press_by_id: dict[str, float] = {}
    if with_pressures:
        for r in pressures.drop_nulls("player_id").to_dicts():
            press_by_id[r["player_id"]] = press_by_id.get(r["player_id"], 0.0) + _n(r.get("pressures"))

    by_team: dict[str, list[PlayerLine]] = {away: [], home: []}
    for row in (stats.to_dicts() if not stats.is_empty() else []):
        if not row.get("player_id"):
            continue  # lignes sans joueur identifié (il y en a quelques-unes dans nflverse)
        team = canonical_team(row.get("team"))
        if team not in by_team:
            log.error("Joueurs clés %s : %s (%s) a l'équipe %r, qui ne joue pas ce match (%s @ %s) : ignoré",
                      game_id, row.get("player_display_name"), row["player_id"], row.get("team"), away, home)
            continue
        p = to_player_line({**row, "team": team})
        if with_pressures:
            p.pressures = press_by_id.get(p.player_id, 0.0)
        by_team[team].append(p)

    sides = {t: _team_key_players(t, players, cfg, with_pressures) for t, players in by_team.items()}
    for side in sides.values():
        _check_teams(game_id, side)

    return MatchKeyPlayers(
        away=sides[away], home=sides[home],
        mvp=select_mvp(sides[away], sides[home], away_score, home_score, cfg, mvp_scale),
        pressures_available=with_pressures,
        weights={section: {k: float(v) for k, v in values.items()}
                 for section, values in cfg.items() if section != "rankings"},
    )

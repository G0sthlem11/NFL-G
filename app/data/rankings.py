"""Classements par poste : le titulaire de chaque équipe, classé de 1 à 32.

Réglages dans la section ``[rankings]`` de ``key_players.toml``.

1. **Poste d'un joueur** : la première position reconnue parmi les sources
   de ``position_sources`` (champs de ``load_players`` de nflverse, puis la
   position des snaps PFR, puis celle de player_stats), ramenée à un poste
   par les codes de ``[rankings.groups]`` (un code inconnu, comme un rôle de
   special teams, passe à la source suivante). ``pff_position`` vient en premier
   parce qu'il sépare les pass rushers (« ED ») des linebackers (« LB ») :
   ``position`` met souvent LB ou OLB pour les deux.

2. **Équipe d'un joueur** : celle où il a le plus de snaps sur la saison
   (le plus de matchs pour un kicker). Un joueur échangé compte donc pour une
   seule équipe.

3. **Titulaire** : dans chaque équipe et à chaque poste, le joueur qui a le
   plus de snaps sur la saison, offensifs pour un poste d'attaque, défensifs
   pour un poste de défense (le plus de matchs joués pour le kicker).
   Égalité : le nom puis l'identifiant.

4. **Score** : celui de la catégorie, match par match (``qb_mvp_score``,
   ``offense_score``, ``defense_score`` avec les pressions PFR quand le match
   est couvert, ``kicker_mvp_score``), additionné sur la saison, toutes
   équipes confondues. Classement sur la **moyenne par match joué**.
   Matchs joués : ceux où le joueur a au moins un snap de son côté du ballon
   (pour un match absent des snaps, sa présence dans player_stats compte).
   Kicker : les matchs où il apparaît dans player_stats.
   Sous ``min_games`` matchs joués, il passe en fin de classement.
   Égalité : le total, puis le nom et l'identifiant.
"""
from __future__ import annotations

import logging

import polars as pl

from .key_players import (canonical_team, defense_score, kicker_mvp_score, load_config, offense_score,
                          qb_mvp_score)
from .models import PlayerLine, PositionRanking, RankingRow, Rankings
from .normalize import as_str, to_player_line

log = logging.getLogger(__name__)

# Colonnes player_stats additionnées pour les totaux (fg_long : maximum).
SUM_COLUMNS = [
    "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
    "carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds",
    "def_tackles_solo", "def_tackle_assists", "def_tackles_for_loss", "def_sacks", "def_qb_hits",
    "def_interceptions", "def_pass_defended", "def_fumbles_forced",
    "fg_made", "fg_att", "fg_made_50_59", "fg_made_60_", "pat_made", "pat_att",
]
# Côté du ballon dont on compte les snaps, selon le score du poste.
SNAP_SIDE = {"qb": "off", "offense": "off", "defense": "def", "kicker": None}


def _mode(values: list) -> str | None:
    """Valeur la plus fréquente (la plus récente en cas d'égalité)."""
    counts: dict = {}
    last: dict = {}
    for i, v in enumerate(values):
        if v:
            counts[v] = counts.get(v, 0) + 1
            last[v] = i
    return max(counts, key=lambda v: (counts[v], last[v])) if counts else None


def code_to_group(cfg: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for group, spec in cfg["rankings"]["groups"].items():
        for code in spec["codes"]:
            out.setdefault(str(code).upper(), group)
    return out


def resolve_group(sources: dict[str, str | None], cfg: dict, codes: dict[str, str] | None = None) -> str | None:
    """Poste d'un joueur : la première source dont le code correspond à un
    poste (None si aucune, ex. OL)."""
    codes = codes if codes is not None else code_to_group(cfg)
    for name in cfg["rankings"]["position_sources"]:
        code = as_str(sources.get(name))
        if code and code.upper() in codes:
            return codes[code.upper()]
    return None


def _snaps_with_ids(snaps: pl.DataFrame, players: pl.DataFrame, stats: pl.DataFrame) -> pl.DataFrame:
    """Snaps avec l'identifiant GSIS du joueur : par pfr_id, sinon par nom et
    équipe dans player_stats."""
    if snaps.is_empty():
        return pl.DataFrame(schema={"game_id": pl.Utf8, "week": pl.Int64, "player_id": pl.Utf8,
                                    "team": pl.Utf8, "position": pl.Utf8, "off": pl.Float64, "def": pl.Float64})
    s = snaps.with_columns(pl.col("team").map_elements(canonical_team, return_dtype=pl.Utf8),
                           pl.col("offense_snaps").fill_null(0).cast(pl.Float64).alias("off"),
                           pl.col("defense_snaps").fill_null(0).cast(pl.Float64).alias("def"))
    if not players.is_empty():
        ids = players.select("pfr_id", "gsis_id").drop_nulls().unique("pfr_id", keep="first")
        s = s.join(ids, left_on="pfr_player_id", right_on="pfr_id", how="left")
    else:
        s = s.with_columns(pl.lit(None, pl.Utf8).alias("gsis_id"))
    by_name = (stats.select(pl.col("player_display_name").alias("player"), "team",
                            pl.col("player_id").alias("by_name"))
               .drop_nulls().unique(["player", "team"], keep="first"))
    s = (s.join(by_name, on=["player", "team"], how="left")
         .with_columns(pl.coalesce("gsis_id", "by_name").alias("player_id")))
    missing = s.filter(pl.col("player_id").is_null() & ((pl.col("off") + pl.col("def")) > 0))
    if missing.height:
        log.info("Snaps sans identifiant GSIS ignorés : %s", sorted(set(missing["player"].to_list())))
    return (s.filter(pl.col("player_id").is_not_null())
            .select("game_id", "week", "player_id", "team", "position", "off", "def"))


def _line_score(line: PlayerLine, score: str, cfg: dict, with_pressures: bool) -> float:
    if score == "qb":
        return qb_mvp_score(line, cfg["mvp"])
    if score == "offense":
        return offense_score(line, cfg["offense"])
    if score == "defense":
        return defense_score(line, cfg["defense"], with_pressures)
    return kicker_mvp_score(line, cfg["mvp"])


def _totals(rows: pl.DataFrame, player_id: str, last: dict, pressures: float | None) -> PlayerLine:
    sums = rows.select([pl.col(c).sum() for c in SUM_COLUMNS if c in rows.columns]).to_dicts()[0]
    line = to_player_line({**sums, "player_id": player_id, "player_display_name": last.get("player_display_name"),
                           "position": last.get("position"), "team": last["team"],
                           "headshot_url": last.get("headshot_url")})
    fg_long = rows["fg_long"].max() if "fg_long" in rows.columns else None
    return line.model_copy(update={"fg_long": int(fg_long) if fg_long is not None else None,
                                   "pressures": pressures})


def _best_team(per_team: list[tuple[str, float, int]]) -> str:
    """Équipe où le joueur a le plus joué ; égalité : la plus récente, puis l'ordre alphabétique."""
    return min(per_team, key=lambda t: (-t[1], -t[2], t[0]))[0]


def compute_rankings(season: int, stats: pl.DataFrame, snaps: pl.DataFrame, players: pl.DataFrame,
                     pfr: pl.DataFrame | None, cfg: dict | None = None) -> Rankings:
    cfg = cfg or load_config()
    rk = cfg["rankings"]
    groups = rk["groups"]
    min_games = int(rk["min_games"])
    if stats.is_empty():
        return Rankings(season=season, min_games=min_games)
    stats = (stats.filter(pl.col("player_id").is_not_null())
             .with_columns(pl.col("team").map_elements(canonical_team, return_dtype=pl.Utf8))
             .sort("week"))
    snaps = _snaps_with_ids(snaps, players, stats)
    snap_games = set(snaps["game_id"].to_list())

    # Postes, toutes sources confondues.
    src: dict[str, dict] = {}
    if not players.is_empty():
        src = {r["gsis_id"]: r for r in players.select("gsis_id", "pff_position", "ngs_position", "position").to_dicts()}
    stat_pos = {pid: _mode(v) for pid, v in stats.group_by("player_id", maintain_order=True).agg("position").iter_rows()}
    snap_pos = {pid: _mode(v) for pid, v in
                snaps.sort("week").group_by("player_id", maintain_order=True).agg("position").iter_rows()}
    codes = code_to_group(cfg)

    def group_of(pid: str) -> str | None:
        return resolve_group({**src.get(pid, {}), "snaps": snap_pos.get(pid), "stats": stat_pos.get(pid)}, cfg, codes)

    # Pressions PFR par (joueur, match), et matchs couverts par PFR.
    press: dict[tuple[str, str], float] = {}
    covered: set[str] = set()
    if pfr is not None and not pfr.is_empty():
        covered = set(pfr["game_id"].to_list())
        for pid, gid, v in pfr.filter(pl.col("player_id").is_not_null()).select("player_id", "game_id", "pressures").iter_rows():
            press[(pid, gid)] = press.get((pid, gid), 0.0) + (v or 0.0)

    # Volume de jeu par joueur et par équipe : snaps de chaque côté, matchs pour le kicker.
    volume: dict[str, dict[str, list[tuple[str, float, int]]]] = {"off": {}, "def": {}, None: {}}
    for side in ("off", "def"):
        agg = (snaps.filter(pl.col(side) > 0).group_by("player_id", "team")
               .agg(pl.col(side).sum().alias("n"), pl.col("week").max().alias("last")))
        for pid, team, n, last in agg.iter_rows():
            volume[side].setdefault(pid, []).append((team, float(n), int(last)))
    for pid, team, n, last in (stats.group_by("player_id", "team")
                               .agg(pl.len().alias("n"), pl.col("week").max().alias("last")).iter_rows()):
        volume[None].setdefault(pid, []).append((team, float(n), int(last)))

    last_rows = {r["player_id"]: r for r in stats.unique("player_id", keep="last").to_dicts()}
    names = {pid: (r.get("player_display_name") or pid) for pid, r in last_rows.items()}

    # Titulaire de chaque équipe à chaque poste. Seuls les joueurs avec au
    # moins une ligne de stats sont classables.
    starters: dict[str, dict[str, tuple[str, float]]] = {g: {} for g in groups}
    for pid in last_rows:
        g = group_of(pid)
        if g is None:
            continue
        per_team = volume[SNAP_SIDE[groups[g]["score"]]].get(pid)
        if not per_team:
            continue
        team, total = _best_team(per_team), sum(n for _, n, _ in per_team)
        cur = starters[g].get(team)
        if cur is None or (-total, names[pid], pid) < (-cur[1], names[cur[0]], cur[0]):
            starters[g][team] = (pid, total)

    positions = []
    for g, spec in groups.items():
        kind = spec["score"]
        side = SNAP_SIDE[kind]
        rows: list[RankingRow] = []
        for team, (pid, vol) in starters[g].items():
            prow = stats.filter(pl.col("player_id") == pid)
            total = 0.0
            for r in prow.to_dicts():
                line = to_player_line(r).model_copy(update={"pressures": press.get((pid, r["game_id"]))})
                total += _line_score(line, kind, cfg, r["game_id"] in covered)
            if side is None:
                games = prow.height
            else:
                played = set(snaps.filter((pl.col("player_id") == pid) & (pl.col(side) > 0))["game_id"].to_list())
                played |= {gid for gid in prow["game_id"].to_list() if gid not in snap_games}
                games = max(len(played), 1)
            p_total = sum(v for (p, _), v in press.items() if p == pid) if kind == "defense" else None
            last = last_rows[pid]
            rows.append(RankingRow(
                rank=0, player_id=pid, name=names[pid], team=team,
                position=as_str(last.get("position")), headshot_url=as_str(last.get("headshot_url")),
                games=games, snaps=None if side is None else int(vol), eligible=games >= min_games,
                score_total=round(total, 1), score_avg=round(total / games, 1),
                totals=_totals(prow, pid, last, p_total),
            ))
        rows.sort(key=lambda r: (not r.eligible, -r.score_total / r.games, -r.score_total, r.name, r.player_id))
        if len(rows) != 32:
            log.warning("Classement %s : %d équipes au lieu de 32", g, len(rows))
        positions.append(PositionRanking(key=g, score=kind,
                                         rows=[r.model_copy(update={"rank": i + 1}) for i, r in enumerate(rows)]))
    return Rankings(season=season, min_games=min_games, positions=positions)

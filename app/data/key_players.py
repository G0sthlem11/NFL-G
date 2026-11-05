"""Sélection des joueurs clés d'une équipe pour un match.

Règles, appliquées à chaque équipe et à chaque match :

1. **Snapshot de depth chart.** On prend le snapshot le plus récent pris
   *avant* le match : ``dt <= gameday`` et, si l'heure du coup d'envoi est
   connue, ``dt < kickoff`` pour ne pas prendre un snapshot publié le soir
   même après la rencontre. Les snapshots sont en UTC.

2. **Titulaires d'attaque.** On trie le depth chart du poste par ``pos_rank``,
   puis ``pos_slot`` :

   - QB, RB1 et TE1 : le joueur de rang 1 au poste QB, RB ou TE ;
   - WR1 et WR2 : les deux premiers WR.

   ``pos_rank`` est un classement global des WR, réparti sur les slots X, Z
   et slot. Le tri ``(pos_rank, pos_slot)`` reste correct même si une
   équipe le code par slot.

3. **Edges (« DE titulaires »).** Ça dépend du schéma défensif, lu dans
   ``pos_grp`` :

   - en **4-3**, les edges sont LDE et RDE (libellé « DE ») ;
   - en **3-4**, LDE et RDE sont des joueurs de ligne intérieure : les pass
     rushers sont les linebackers extérieurs SLB et WLB (libellé « OLB »).
     C'est vérifié sur la saison 2026 : 2 à 3 fois plus de sacks.

4. **Titulaire qui n'a pas joué.** S'il n'a aucune ligne dans ``player_stats``
   pour ce match, on le remplace par le joueur du même poste le plus
   productif du match. Le motif vient du roster hebdomadaire :

   - INA → « inactif » ;
   - RES → « en réserve » ;
   - ACT → « actif sans stat » ;
   - absent du roster → « absent de l'effectif ».

   Le « même poste » regroupe les joueurs listés à ce poste dans le
   snapshot (tous rangs confondus) et ceux dont la position dans
   ``player_stats`` correspond.

5. **Pas de depth chart pour l'équipe.** Tout est choisi sur la production
   du match :

   - WR1 et WR2 : les deux WR avec le plus de yards en réception ;
   - TE1 : le TE le plus productif ;
   - edges : les deux DE ou OLB au meilleur score de pass rush, etc.

6. **Défense, en plus.** Le meilleur plaqueur (solo + assistés, puis solo,
   puis sacks), et tous les joueurs avec au moins un sack, une interception
   ou un fumble forcé.

Un même joueur n'occupe jamais deux rôles : un remplaçant de WR2 ne peut pas
être le WR1.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import polars as pl

from .models import KeyPlayer, KeyPlayers
from .normalize import as_float, as_int, to_player_line

STATUS_REASONS = {
    "INA": "inactif",
    "RES": "en réserve",
    "ACT": "actif sans stat",
    "DEV": "équipe d'entraînement",
    "CUT": "libéré",
}


def _n(v) -> float:
    return as_float(v) or 0.0


# --- Mesures de productivité (pour les remplacements et le repli) ---------
def qb_score(r: dict) -> float:
    return _n(r.get("attempts")) * 10 + _n(r.get("passing_yards")) + _n(r.get("rushing_yards"))


def rb_score(r: dict) -> float:
    return (_n(r.get("rushing_yards")) + _n(r.get("receiving_yards"))
            + 0.1 * (_n(r.get("carries")) + _n(r.get("receptions"))))


def rec_score(r: dict) -> float:
    return _n(r.get("receiving_yards")) + 0.1 * _n(r.get("receptions")) + 0.01 * _n(r.get("targets"))


def edge_score(r: dict) -> float:
    tackles = _n(r.get("def_tackles_solo")) + _n(r.get("def_tackle_assists"))
    return (3 * _n(r.get("def_sacks")) + 2 * _n(r.get("def_tackles_for_loss"))
            + 1.5 * _n(r.get("def_qb_hits")) + 0.5 * tackles)


@dataclass(frozen=True)
class RoleSpec:
    role: str
    label: str
    depth_pos: tuple[str, ...]   # postes du depth chart dont on prend le titulaire
    rank_index: int              # 0 = premier, 1 = deuxième (WR2)
    pool_depth_pos: tuple[str, ...]  # postes du depth chart du « même poste »
    pool_stats_pos: tuple[str, ...]  # positions player_stats du « même poste »
    score: Callable[[dict], float]


OFFENSE = [
    RoleSpec("QB", "QB", ("QB",), 0, ("QB",), ("QB",), qb_score),
    RoleSpec("RB1", "RB1", ("RB",), 0, ("RB",), ("RB",), rb_score),
    RoleSpec("WR1", "WR1", ("WR",), 0, ("WR",), ("WR",), rec_score),
    RoleSpec("WR2", "WR2", ("WR",), 1, ("WR",), ("WR",), rec_score),
    RoleSpec("TE1", "TE1", ("TE",), 0, ("TE",), ("TE",), rec_score),
]

EDGES_43 = [
    RoleSpec("EDGE1", "DE", ("LDE",), 0, ("LDE", "RDE"), ("DE",), edge_score),
    RoleSpec("EDGE2", "DE", ("RDE",), 0, ("LDE", "RDE"), ("DE",), edge_score),
]
EDGES_34 = [
    RoleSpec("EDGE1", "OLB", ("SLB",), 0, ("SLB", "WLB"), ("OLB",), edge_score),
    RoleSpec("EDGE2", "OLB", ("WLB",), 0, ("SLB", "WLB"), ("OLB",), edge_score),
]
# Sans depth chart : schéma inconnu, on prend DE et OLB ensemble.
EDGES_UNKNOWN = [
    RoleSpec("EDGE1", "DE", (), 0, (), ("DE", "OLB"), edge_score),
    RoleSpec("EDGE2", "DE", (), 0, (), ("DE", "OLB"), edge_score),
]


def latest_snapshot(depth: pl.DataFrame, gameday: str, kickoff: datetime | None) -> pl.DataFrame:
    """Snapshot de depth chart le plus récent antérieur au match (voir règle 1)."""
    if depth.is_empty():
        return depth
    cand = depth.filter(pl.col("dt").str.slice(0, 10) <= gameday[:10])
    if kickoff is not None:
        k = kickoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cand = cand.filter(pl.col("dt") < k)  # ISO 8601 UTC : l'ordre lexical = l'ordre chronologique
    if cand.is_empty():
        return cand
    return cand.filter(pl.col("dt") == cand["dt"].max())


def detect_scheme(snapshot: pl.DataFrame) -> str | None:
    if snapshot.is_empty() or "pos_grp" not in snapshot.columns:
        return None
    groups = set(snapshot["pos_grp"].drop_nulls().to_list())
    if any("3-4" in g for g in groups):
        return "3-4"
    if any("4-3" in g for g in groups):
        return "4-3"
    return None


def select_key_players(
    team: str,
    gameday: str,
    kickoff: datetime | None,
    stats: pl.DataFrame,
    depth: pl.DataFrame,
    roster: pl.DataFrame,
) -> KeyPlayers:
    """Joueurs clés d'une équipe pour un match.

    - ``stats`` : lignes ``player_stats`` de **cette équipe dans ce match** ;
    - ``depth`` : tous les snapshots de depth chart de l'équipe ;
    - ``roster`` : roster hebdomadaire de l'équipe pour la semaine du match.
    """
    # Certaines lignes nflverse n'ont pas de player_id (actions d'équipe) : ignorées.
    stat_rows = {r["player_id"]: r for r in stats.to_dicts() if r.get("player_id")} \
        if not stats.is_empty() else {}
    snap = latest_snapshot(depth, gameday, kickoff)
    scheme = detect_scheme(snap)
    has_depth = not snap.is_empty()

    status_by_id: dict[str, str] = {}
    if not roster.is_empty():
        for r in roster.to_dicts():
            if r.get("gsis_id"):
                status_by_id[r["gsis_id"]] = r.get("status") or ""

    # Snapshot trié et indexé par poste
    by_pos: dict[str, list[dict]] = {}
    if has_depth:
        for r in snap.sort("pos_rank", "pos_slot").to_dicts():
            by_pos.setdefault(r["pos_abb"], []).append(r)

    used: set[str] = set()  # un joueur n'occupe qu'un rôle

    def best_in_pool(spec: RoleSpec) -> str | None:
        dc_ids = {r["gsis_id"] for p in spec.pool_depth_pos for r in by_pos.get(p, []) if r.get("gsis_id")}
        pool = [
            r for pid, r in stat_rows.items()
            if pid not in used and (pid in dc_ids or (r.get("position") in spec.pool_stats_pos))
        ]
        pool = [r for r in pool if spec.score(r) > 0] or pool
        if not pool:
            return None
        return max(pool, key=lambda r: (spec.score(r), r["player_id"]))["player_id"]

    def starter_for(spec: RoleSpec) -> dict | None:
        rows: list[dict] = []
        for p in spec.depth_pos:
            rows.extend(by_pos.get(p, []))
        rows.sort(key=lambda r: (as_int(r.get("pos_rank")) or 99, as_int(r.get("pos_slot")) or 99))
        distinct: list[dict] = []
        for r in rows:
            gid = r.get("gsis_id")
            if gid and gid not in {s["gsis_id"] for s in distinct}:
                distinct.append(r)
        # rank_index : 0 = premier du poste, 1 = deuxième (WR2)
        return distinct[spec.rank_index] if len(distinct) > spec.rank_index else None

    if not has_depth:
        edge_specs = EDGES_UNKNOWN
    elif scheme == "3-4":
        edge_specs = EDGES_34
    else:
        edge_specs = EDGES_43  # 4-3, ou schéma illisible : codage LDE/RDE standard
    specs = OFFENSE + edge_specs
    picked: dict[str, KeyPlayer] = {}

    # Passe 1 : les titulaires du depth chart qui ont joué sont réservés d'abord,
    # pour qu'un remplaçant ne puisse pas « voler » un titulaire présent.
    starters: dict[str, dict | None] = {}
    if has_depth:
        for spec in specs:
            starter = starter_for(spec)
            starters[spec.role] = starter
            if starter is not None and starter["gsis_id"] in stat_rows and starter["gsis_id"] not in used:
                used.add(starter["gsis_id"])
                picked[spec.role] = KeyPlayer(
                    role=spec.role, label=spec.label, depth_pos=starter.get("pos_abb"),
                    player=to_player_line(stat_rows[starter["gsis_id"]]), source="depth_chart")

    # Passe 2 : rôles restants -> joueur le plus productif du même poste.
    for spec in specs:
        if spec.role in picked:
            continue
        starter = starters.get(spec.role)
        replaced = reason = None
        if starter is not None:
            replaced = starter.get("player_name")
            status = status_by_id.get(starter["gsis_id"])
            reason = STATUS_REASONS.get(status, status.lower() if status else "absent de l'effectif")
        depth_pos = starter.get("pos_abb") if starter else None
        pid = best_in_pool(spec)
        if pid is None:
            picked[spec.role] = KeyPlayer(role=spec.role, label=spec.label, depth_pos=depth_pos,
                                          source="none", replaced_starter=replaced, replaced_reason=reason)
            continue
        used.add(pid)
        picked[spec.role] = KeyPlayer(
            role=spec.role, label=spec.label, depth_pos=depth_pos,
            player=to_player_line(stat_rows[pid]),
            source="replacement" if starter is not None else "fallback",
            replaced_starter=replaced, replaced_reason=reason)

    offense = [picked[s.role] for s in OFFENSE]
    edges = [picked[s.role] for s in edge_specs]

    # Défense : meilleur plaqueur et auteurs de big plays (tous rôles confondus)
    lines = [to_player_line(r) for r in stat_rows.values()]
    tacklers = [p for p in lines if (p.tackles or 0) > 0]
    tackle_leader = max(
        tacklers, key=lambda p: (p.tackles or 0, p.tackles_solo or 0, p.sacks or 0, p.name), default=None)
    playmakers = sorted(
        (p for p in lines if (p.sacks or 0) > 0 or (p.def_interceptions or 0) > 0 or (p.fumbles_forced or 0) > 0),
        key=lambda p: (-(p.def_interceptions or 0), -(p.fumbles_forced or 0), -(p.sacks or 0), p.name),
    )

    return KeyPlayers(
        team=team,
        scheme=scheme,
        depth_chart_dt=snap["dt"][0] if has_depth else None,
        offense=offense,
        edges=edges,
        tackle_leader=tackle_leader,
        playmakers=playmakers,
    )

"""Effectif de chaque équipe (onglet « Effectifs »).

Sources (voir cache.py) :

- ``rosters`` : ``load_rosters_weekly``, dernière photo de chaque équipe (une
  équipe au repos n'a pas de ligne cette semaine-là : on prend sa dernière
  semaine, pas la dernière semaine globale) ;
- ``depth_charts`` : ``load_depth_charts`` (ESPN), dernière photo de chaque
  équipe, souvent plus fraîche que le roster.

Règles :

1. **Effectif principal** : statuts ACT (dont les joueurs de l'équipe
   d'entraînement appelés pour le match) et INA (inactif le jour du match).
   Les autres statuts vont dans une section à part : réserve (RES, EXE, SUS),
   équipe d'entraînement (DEV). Les joueurs libérés (CUT) ou retraités (RET)
   sont écartés.
2. **Depth chart** : ESPN y laisse les blessés. On ne garde que les lignes des
   joueurs de l'effectif principal, puis on recalcule le rang dans chaque
   case (``pos_grp`` + ``pos_slot``) : un titulaire blessé laisse sa place au
   suivant. Les rôles de retour et de holder (KR, PR, H) sont ignorés.
3. **Poste d'un joueur** : sa meilleure case (rang le plus bas, puis l'ordre
   des cases). Titulaire = rang 1 dans cette case.
4. **Ordre** : unité (Attaque, Défense, Équipes spéciales), puis groupe de
   postes dans un ordre fixe (QB, RB, WR, TE, ligne offensive…), puis rang
   et ordre des cases (les titulaires d'abord, dans l'ordre du depth chart :
   LT, LG, C, RG, RT), puis numéro. Un joueur absent du depth chart est rangé
   d'après son poste nflverse, après les autres, par numéro. Sans depth chart
   pour l'équipe, tout est rangé par numéro.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from .key_players import canonical_team
from .models import (RosterGroup, RosterIndex, RosterPlayer, RosterTeam, RosterTeamSummary,
                     RosterUnit, StandingRow)
from .normalize import as_int, as_str

# --- Groupes de postes ----------------------------------------------------
# (clé, libellé, unité), dans l'ordre d'affichage.
GROUPS: list[tuple[str, str, str]] = [
    ("QB", "Quarterbacks", "offense"),
    ("RB", "Running backs", "offense"),
    ("WR", "Wide receivers", "offense"),
    ("TE", "Tight ends", "offense"),
    ("OL", "Ligne offensive", "offense"),
    ("DL", "Ligne défensive", "defense"),
    ("LB", "Linebackers", "defense"),
    ("CB", "Cornerbacks", "defense"),
    ("S", "Safeties", "defense"),
    ("K", "Kickers", "special"),
    ("P", "Punters", "special"),
    ("LS", "Long snappers", "special"),
    ("OTHER", "Autres", "special"),
]
UNITS: list[tuple[str, str]] = [("offense", "Attaque"), ("defense", "Défense"), ("special", "Équipes spéciales")]
GROUP_ORDER = {g: i for i, (g, _, _) in enumerate(GROUPS)}
GROUP_INFO = {g: (label, unit) for g, label, unit in GROUPS}

# Cases du depth chart (pos_abb ESPN) -> groupe. KR, PR et H : ignorés.
DEPTH_GROUP = {
    "QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE",
    "LT": "OL", "LG": "OL", "C": "OL", "RG": "OL", "RT": "OL",
    "LDE": "DL", "RDE": "DL", "LDT": "DL", "RDT": "DL", "NT": "DL", "DE": "DL", "DT": "DL",
    "WLB": "LB", "SLB": "LB", "MLB": "LB", "LILB": "LB", "RILB": "LB", "LOLB": "LB", "ROLB": "LB",
    "OLB": "LB", "ILB": "LB", "LB": "LB",
    "LCB": "CB", "RCB": "CB", "NB": "CB", "CB": "CB",
    "SS": "S", "FS": "S", "S": "S",
    "PK": "K", "K": "K", "P": "P", "LS": "LS",
}
# Ordre des formations dans le depth chart ESPN.
DEPTH_UNIT_ORDER = {"offense": 0, "defense": 1, "special": 2}

# Postes nflverse du roster (depth_chart_position, puis position) -> groupe.
ROSTER_GROUP = {
    "QB": "QB", "RB": "RB", "HB": "RB", "FB": "RB", "WR": "WR", "TE": "TE",
    "T": "OL", "OT": "OL", "G": "OL", "OG": "OL", "C": "OL", "OL": "OL",
    "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL",
    "OLB": "LB", "ILB": "LB", "MLB": "LB", "LB": "LB",
    "CB": "CB", "DB": "CB", "FS": "S", "SS": "S", "S": "S", "SAF": "S",
    "K": "K", "PK": "K", "P": "P", "LS": "LS",
}

# --- Statuts --------------------------------------------------------------
MAIN_STATUSES = {"ACT", "INA"}
RESERVE_STATUSES = {"RES", "EXE", "SUS"}
PRACTICE_STATUSES = {"DEV"}
HIDDEN_STATUSES = {"CUT", "RET"}
# Section repliée : (clé, libellé), dans l'ordre d'affichage.
OUT_SECTIONS = [("reserve", "Réserve"), ("practice", "Équipe d'entraînement"), ("other", "Autres statuts")]

# Libellés des codes détaillés de la réserve (status_description_abbr). Code
# inconnu : « Réserve ».
RESERVE_LABELS = {
    "R01": "IR",
    "R48": "IR, retour désigné",
    "R04": "PUP",
    "R05": "NFI",
}

ROSTER_COLUMNS = ["season", "week", "team", "gsis_id", "full_name", "football_name", "last_name",
                  "jersey_number", "position", "depth_chart_position", "status", "status_description_abbr",
                  "height", "weight", "birth_date", "years_exp", "college", "rookie_year", "entry_year",
                  "draft_number", "headshot_url"]
DEPTH_COLUMNS = ["dt", "team", "gsis_id", "player_name", "pos_grp", "pos_slot", "pos_abb", "pos_rank"]


def latest_rosters(df: pl.DataFrame) -> pl.DataFrame:
    """Dernière semaine de chaque équipe (abréviations du calendrier)."""
    if df.is_empty():
        return df
    df = df.select([c for c in ROSTER_COLUMNS if c in df.columns])
    df = df.with_columns(pl.col("team").map_elements(canonical_team, return_dtype=pl.Utf8))
    last = df.group_by("team").agg(pl.col("week").max().alias("_last"))
    return df.join(last, on="team").filter(pl.col("week") == pl.col("_last")).drop("_last")


def latest_depth_charts(df: pl.DataFrame) -> pl.DataFrame:
    """Dernière photo du depth chart de chaque équipe. Format ESPN (saisons
    2025 et suivantes) seulement : sinon, table vide (tri par numéro)."""
    if df.is_empty() or any(c not in df.columns for c in DEPTH_COLUMNS):
        return pl.DataFrame()
    df = df.select(DEPTH_COLUMNS).with_columns(
        pl.col("team").map_elements(canonical_team, return_dtype=pl.Utf8))
    last = df.group_by("team").agg(pl.col("dt").max().alias("_last"))
    return df.join(last, on="team").filter(pl.col("dt") == pl.col("_last")).drop("_last")


def _depth_unit(pos_grp: str | None) -> str:
    g = (pos_grp or "").lower()
    if "special" in g:
        return "special"
    if g.endswith(" d") or "defense" in g or g.startswith("base"):
        return "defense"
    return "offense"


def _roster_group(row: dict) -> str:
    for key in ("depth_chart_position", "position"):
        g = ROSTER_GROUP.get((as_str(row.get(key)) or "").upper())
        if g:
            return g
    return "OTHER"


def depth_assignments(depth_rows: Iterable[dict], active_ids: set[str]) -> dict[str, dict]:
    """Meilleure case de chaque joueur actif : {gsis_id: {group, pos, rank, slot, starter}}.

    ``depth_rows`` : lignes du depth chart d'une équipe (dernière photo).
    ``active_ids`` : joueurs de l'effectif principal (les blessés et les
    joueurs absents du roster sont ignorés, puis les rangs recalculés).
    """
    cells: dict[tuple, list[dict]] = {}
    for r in depth_rows:
        pid, pos = r.get("gsis_id"), (r.get("pos_abb") or "").upper()
        group = DEPTH_GROUP.get(pos)
        if not pid or pid not in active_ids or group is None:
            continue
        unit = _depth_unit(r.get("pos_grp"))
        key = (DEPTH_UNIT_ORDER[unit], as_int(r.get("pos_slot")) or 0, pos)
        cells.setdefault(key, []).append(r)

    best: dict[str, dict] = {}
    for (unit_order, slot, pos), rows in cells.items():
        rows = sorted(rows, key=lambda r: (as_int(r.get("pos_rank")) or 99, r["gsis_id"]))
        seen: set[str] = set()
        rank = 0
        for r in rows:
            pid = r["gsis_id"]
            if pid in seen:  # même joueur deux fois dans une case
                continue
            seen.add(pid)
            rank += 1
            cand = {"group": DEPTH_GROUP[pos], "pos": "K" if pos == "PK" else pos, "rank": rank,
                    "slot": (unit_order, slot), "starter": rank == 1}
            cur = best.get(pid)
            if cur is None or (cand["rank"], cand["slot"]) < (cur["rank"], cur["slot"]):
                best[pid] = cand
    return best


def _college(raw: Any) -> tuple[str | None, list[str]]:
    """« Iowa State; Eastern Kentucky » : la première est la dernière fréquentée."""
    s = as_str(raw)
    if not s:
        return None, []
    parts = [p.strip() for p in s.split(";") if p.strip()]
    return (parts[0] if parts else None), parts


def first_college(raw: Any) -> str | None:
    return _college(raw)[0]


# Logos des universités (ESPN), téléchargés par scripts.fetch_college_logos :
# nom nflverse -> {"logo": "logos/college/<id>.png", "logo_dark": ...}.
COLLEGE_MAP_PATH = Path(__file__).with_name("college_logos.json")
# Racine des chemins de logos (logos/college/<id>.png), comme pour les équipes.
LOGO_ROOT = Path(__file__).resolve().parents[1] / "static"
# Correspondances saisies à la main (cas ambigus), lues par le script.
COLLEGE_OVERRIDES_PATH = Path(__file__).with_name("college_logos.toml")


@lru_cache(maxsize=1)
def college_logos() -> dict[str, dict]:
    try:
        return json.loads(COLLEGE_MAP_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _birth(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = as_str(v)
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def to_roster_player(row: dict, depth: dict | None, has_page: bool) -> RosterPlayer:
    status = (as_str(row.get("status")) or "").upper()
    detail = (as_str(row.get("status_description_abbr")) or "").upper()
    label = None
    if status == "INA":
        label = "inactif"
    elif status == "ACT" and detail.startswith("P"):
        label = "appelé"  # joueur de l'équipe d'entraînement appelé pour le match
    elif status in RESERVE_STATUSES:
        label = {"EXE": "exempté", "SUS": "suspendu"}.get(status) or RESERVE_LABELS.get(detail, "réserve")
    college, colleges = _college(row.get("college"))
    logo = college_logos().get(college or "", {})
    # entry_year : l'année de draft pour un joueur drafté (identique à
    # load_draft_picks sur toute la saison 2026).
    pick = as_int(row.get("draft_number"))
    year = as_int(row.get("entry_year")) or as_int(row.get("rookie_year"))
    group = depth["group"] if depth else _roster_group(row)
    return RosterPlayer(
        player_id=row["gsis_id"],
        name=as_str(row.get("full_name")) or row["gsis_id"],
        jersey=as_int(row.get("jersey_number")),
        position=depth["pos"] if depth else (as_str(row.get("depth_chart_position")) or as_str(row.get("position"))),
        group=group,
        starter=bool(depth and depth["starter"]),
        depth=depth["rank"] if depth else None,
        status=status,
        status_label=label,
        birth_date=_birth(row.get("birth_date")),
        height_in=as_int(row.get("height")),
        weight_lb=as_int(row.get("weight")),
        years_exp=as_int(row.get("years_exp")),
        college=college,
        colleges=colleges,
        college_logo=logo.get("logo"),
        college_logo_dark=logo.get("logo_dark"),
        draft_year=year if pick is not None else None,
        draft_pick=pick,
        headshot_url=as_str(row.get("headshot_url")),
        has_page=has_page,
    )


def _sort_key(p: RosterPlayer, depth: dict | None) -> tuple:
    jersey = p.jersey if p.jersey is not None else 999
    if depth:
        return (GROUP_ORDER.get(p.group, 99), 0, depth["rank"], depth["slot"], jersey, p.name)
    return (GROUP_ORDER.get(p.group, 99), 1, 0, (0, 0), jersey, p.name)


def section_of(status: str) -> str | None:
    """Section d'un statut : "main", "reserve", "practice", "other" ou None (écarté)."""
    if status in MAIN_STATUSES:
        return "main"
    if status in HIDDEN_STATUSES:
        return None
    if status in RESERVE_STATUSES:
        return "reserve"
    if status in PRACTICE_STATUSES:
        return "practice"
    return "other"


def build_team_roster(abbr: str, name: str, season: int, roster: pl.DataFrame, depth: pl.DataFrame,
                      page_ids: set[str], standing: StandingRow | None,
                      conference: str | None = None, division: str | None = None) -> RosterTeam:
    """Effectif d'une équipe. ``roster`` et ``depth`` : déjà filtrés sur l'équipe
    (dernières photos), éventuellement vides."""
    rows = [r for r in roster.to_dicts() if r.get("gsis_id")] if not roster.is_empty() else []
    rows = list({r["gsis_id"]: r for r in rows}.values())  # une ligne par joueur
    by_section: dict[str, list[dict]] = {}
    for r in rows:
        sec = section_of((as_str(r.get("status")) or "").upper())
        if sec:
            by_section.setdefault(sec, []).append(r)

    main_rows = by_section.get("main", [])
    depth_rows = depth.to_dicts() if not depth.is_empty() else []
    assign = depth_assignments(depth_rows, {r["gsis_id"] for r in main_rows})

    players = []
    for r in main_rows:
        d = assign.get(r["gsis_id"])
        p = to_roster_player(r, d, r["gsis_id"] in page_ids)
        players.append((_sort_key(p, d), p))
    players.sort(key=lambda x: x[0])

    units = []
    for unit, unit_label in UNITS:
        groups = []
        for g, label, gu in GROUPS:
            if gu != unit:
                continue
            members = [p for _, p in players if p.group == g]
            if members:
                groups.append(RosterGroup(key=g, label=label, players=members))
        if groups:
            units.append(RosterUnit(key=unit, label=unit_label, groups=groups))

    out_groups = []
    for key, label in OUT_SECTIONS:
        members = [to_roster_player(r, None, r["gsis_id"] in page_ids)
                   for r in by_section.get(key, [])]
        members.sort(key=lambda p: (GROUP_ORDER.get(p.group, 99), p.jersey if p.jersey is not None else 999, p.name))
        if members:
            out_groups.append(RosterGroup(key=key, label=label, players=members))

    week = as_int(roster["week"].max()) if not roster.is_empty() and "week" in roster.columns else None
    dt = depth["dt"].max() if not depth.is_empty() else None
    return RosterTeam(
        team=abbr, name=name, season=season, conference=conference, division=division,
        wins=standing.wins if standing else None, losses=standing.losses if standing else None,
        ties=standing.ties if standing else None,
        roster_week=week, depth_chart_at=_parse_dt(dt),
        active_count=sum(1 for _, p in players), units=units, out=out_groups,
    )


def _parse_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    s = as_str(v)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_index(season: int, teams: list[dict], rosters: pl.DataFrame, depth: pl.DataFrame,
                standings: dict[str, StandingRow]) -> RosterIndex:
    """Liste des 32 équipes, groupées par conférence et division."""
    counts: dict[str, dict[str, int]] = {}
    if not rosters.is_empty():
        for r in rosters.select("team", "status", "gsis_id").unique(["team", "gsis_id"]).to_dicts():
            sec = section_of((as_str(r.get("status")) or "").upper())
            if sec:
                c = counts.setdefault(r["team"], {})
                c[sec] = c.get(sec, 0) + 1
    out = []
    for t in sorted(teams, key=lambda t: (t.get("conference") or "", t.get("division") or "", t["name"])):
        c, s = counts.get(t["abbr"], {}), standings.get(t["abbr"])
        out.append(RosterTeamSummary(
            team=t["abbr"], name=t["name"], conference=t.get("conference"), division=t.get("division"),
            wins=s.wins if s else None, losses=s.losses if s else None, ties=s.ties if s else None,
            active_count=c.get("main", 0), practice_count=c.get("practice", 0),
            reserve_count=c.get("reserve", 0) + c.get("other", 0),
        ))
    week = as_int(rosters["week"].max()) if not rosters.is_empty() and "week" in rosters.columns else None
    dt = depth["dt"].max() if not depth.is_empty() else None
    return RosterIndex(season=season, roster_week=week, depth_chart_at=_parse_dt(dt), teams=out)

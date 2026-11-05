"""Conversion des lignes nflverse vers les modèles Pydantic de l'app."""
from __future__ import annotations

import math
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from .models import Game, PlayerLine, QuarterScore, TeamStats

# Les heures `gametime` de nflverse sont en heure de l'Est américain.
ET = ZoneInfo("America/New_York")
PARIS = ZoneInfo("Europe/Paris")

PLAYOFF_LABELS = {"WC": "Wild Card", "DIV": "Divisional", "CON": "Conférence", "SB": "Super Bowl"}


def as_int(v: Any) -> int | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def as_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def week_label(game_type: str, week: int) -> str:
    return PLAYOFF_LABELS.get(game_type, f"Week {week}")


def kickoff_paris(gameday: str | None, gametime: str | None) -> datetime | None:
    """« 2026-10-29 » + « 20:15 » (heure de l'Est) -> datetime à l'heure de Paris."""
    if not gameday or not gametime:
        return None
    try:
        d = date.fromisoformat(str(gameday)[:10])
        h, m = (int(x) for x in str(gametime).split(":")[:2])
    except ValueError:
        return None
    return datetime.combine(d, time(h, m), tzinfo=ET).astimezone(PARIS)


def to_game(row: dict, quarters: list[dict] | None = None) -> Game:
    """``row`` : une ligne de ``load_schedules``. ``quarters`` : lignes de
    ``derive.quarter_scores`` pour ce match (vide si pas de play-by-play)."""
    away_score, home_score = as_int(row.get("away_score")), as_int(row.get("home_score"))
    final = away_score is not None and home_score is not None
    qs = [
        QuarterScore(period="OT" if q["qtr"] >= 5 else str(q["qtr"]),
                     away=as_int(q["away"]), home=as_int(q["home"]))
        for q in sorted(quarters or [], key=lambda q: q["qtr"])
    ] if final else []
    return Game(
        game_id=row["game_id"],
        season=as_int(row["season"]),
        week=as_int(row["week"]),
        week_label=week_label(row["game_type"], as_int(row["week"])),
        game_type=row["game_type"],
        status="final" if final else "scheduled",
        kickoff_paris=kickoff_paris(row.get("gameday"), row.get("gametime")),
        away_team=row["away_team"],
        home_team=row["home_team"],
        away_score=away_score,
        home_score=home_score,
        overtime=bool(as_int(row.get("overtime"))),
        quarters=qs,
        stadium=as_str(row.get("stadium")),
        roof=as_str(row.get("roof")),
        surface=as_str(row.get("surface")),
        temp_f=as_int(row.get("temp")),
        wind_mph=as_int(row.get("wind")),
        div_game=bool(as_int(row.get("div_game"))),
        away_coach=as_str(row.get("away_coach")),
        home_coach=as_str(row.get("home_coach")),
        away_qb_name=as_str(row.get("away_qb_name")),
        home_qb_name=as_str(row.get("home_qb_name")),
    )


def _sum(*vals: int | None) -> int | None:
    present = [v for v in vals if v is not None]
    return sum(present) if present else None


def to_team_stats(team: str, row: dict | None, fd: dict | None) -> TeamStats:
    """``row`` : ligne de ``load_team_stats`` ; ``fd`` : ligne de
    ``derive.first_downs``. L'un ou l'autre peut manquer."""
    row = row or {}
    fd = fd or {}
    passing = as_int(row.get("passing_yards"))
    rushing = as_int(row.get("rushing_yards"))
    sack_yds = as_int(row.get("sack_yards_lost"))
    sack_yds = abs(sack_yds) if sack_yds is not None else None  # signe variable selon les versions
    net_passing = passing - (sack_yds or 0) if passing is not None else None
    ints = as_int(row.get("passing_interceptions"))
    fumbles_lost = as_int(row.get("fumbles_lost_total"))
    if fumbles_lost is None:
        fumbles_lost = _sum(*(as_int(row.get(c)) for c in
                              ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost")))
    # 1ers downs : le play-by-play (avec pénalités) en priorité, sinon passe + course.
    fd_pass = as_int(fd.get("first_downs_pass"))
    fd_rush = as_int(fd.get("first_downs_rush"))
    if fd_pass is None:
        fd_pass = as_int(row.get("passing_first_downs"))
    if fd_rush is None:
        fd_rush = as_int(row.get("rushing_first_downs"))
    first_downs = as_int(fd.get("first_downs"))
    if first_downs is None:
        first_downs = _sum(fd_pass, fd_rush)
    return TeamStats(
        team=team,
        total_yards=_sum(net_passing, rushing) if net_passing is not None and rushing is not None else None,
        net_passing_yards=net_passing,
        passing_yards=passing,
        rushing_yards=rushing,
        completions=as_int(row.get("completions")),
        attempts=as_int(row.get("attempts")),
        passing_tds=as_int(row.get("passing_tds")),
        carries=as_int(row.get("carries")),
        rushing_tds=as_int(row.get("rushing_tds")),
        first_downs=first_downs,
        first_downs_pass=fd_pass,
        first_downs_rush=fd_rush,
        first_downs_penalty=as_int(fd.get("first_downs_penalty")),
        turnovers=_sum(ints, fumbles_lost) if ints is not None or fumbles_lost is not None else None,
        interceptions_thrown=ints,
        fumbles_lost=fumbles_lost,
        sacks_suffered=as_int(row.get("sacks_suffered")),
        sack_yards_lost=sack_yds,
        def_sacks=as_float(row.get("def_sacks")),
        def_interceptions=as_int(row.get("def_interceptions")),
        penalties=as_int(row.get("penalties")),
        penalty_yards=as_int(row.get("penalty_yards")),
    )


def to_player_line(row: dict) -> PlayerLine:
    """``row`` : une ligne de ``load_player_stats``."""
    solo, ast = as_int(row.get("def_tackles_solo")), as_int(row.get("def_tackle_assists"))
    return PlayerLine(
        player_id=row["player_id"],
        name=as_str(row.get("player_display_name")) or as_str(row.get("player_name")) or row["player_id"],
        position=as_str(row.get("position")),
        team=row["team"],
        headshot_url=as_str(row.get("headshot_url")),
        completions=as_int(row.get("completions")),
        attempts=as_int(row.get("attempts")),
        passing_yards=as_int(row.get("passing_yards")),
        passing_tds=as_int(row.get("passing_tds")),
        interceptions=as_int(row.get("passing_interceptions")),
        sacks_suffered=as_int(row.get("sacks_suffered")),
        carries=as_int(row.get("carries")),
        rushing_yards=as_int(row.get("rushing_yards")),
        rushing_tds=as_int(row.get("rushing_tds")),
        targets=as_int(row.get("targets")),
        receptions=as_int(row.get("receptions")),
        receiving_yards=as_int(row.get("receiving_yards")),
        receiving_tds=as_int(row.get("receiving_tds")),
        tackles=_sum(solo, ast),
        tackles_solo=solo,
        tackle_assists=ast,
        tackles_for_loss=as_float(row.get("def_tackles_for_loss")),
        sacks=as_float(row.get("def_sacks")),
        qb_hits=as_int(row.get("def_qb_hits")),
        def_interceptions=as_int(row.get("def_interceptions")),
        passes_defended=as_int(row.get("def_pass_defended")),
        fumbles_forced=as_int(row.get("def_fumbles_forced")),
    )

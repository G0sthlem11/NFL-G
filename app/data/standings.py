"""Classement par division, calculé à partir des résultats de saison régulière.

Le pourcentage compte un match nul pour une demi-victoire, comme la NFL :
``(V + 0,5 × N) / matchs``.

Départage simplifié, entre équipes d'une même division à pourcentage égal :

1. pourcentage dans les confrontations directes entre les équipes à égalité ;
2. pourcentage en division ;
3. pourcentage en conférence ;
4. différence de points ;
5. ordre alphabétique (pour un ordre stable).

Les règles officielles vont plus loin (adversaires communs, force du
calendrier…) : ces critères suffisent en cours de saison, mais le classement
final peut différer dans de rares cas d'égalité.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import polars as pl

from .models import DivisionStandings, StandingRow


@dataclass
class _Rec:
    w: int = 0
    l: int = 0  # noqa: E741
    t: int = 0

    def add(self, diff: int) -> None:
        if diff > 0:
            self.w += 1
        elif diff < 0:
            self.l += 1
        else:
            self.t += 1

    @property
    def games(self) -> int:
        return self.w + self.l + self.t

    @property
    def pct(self) -> float:
        return (self.w + 0.5 * self.t) / self.games if self.games else 0.0

    def __str__(self) -> str:
        return f"{self.w}-{self.l}" + (f"-{self.t}" if self.t else "")


@dataclass
class _Team:
    abbr: str
    conf: str
    div: str
    overall: _Rec = field(default_factory=_Rec)
    division: _Rec = field(default_factory=_Rec)
    conference: _Rec = field(default_factory=_Rec)
    home: _Rec = field(default_factory=_Rec)
    away: _Rec = field(default_factory=_Rec)
    pf: int = 0
    pa: int = 0
    results: list[tuple[str, str, int]] = field(default_factory=list)  # (date, adversaire, écart)


def compute_standings(schedules: pl.DataFrame, teams: pl.DataFrame) -> list[DivisionStandings]:
    info = {r["team_abbr"]: r for r in teams.to_dicts()}
    table = {a: _Team(a, r["team_conf"], r["team_division"]) for a, r in info.items()}

    games = (
        schedules.filter((pl.col("game_type") == "REG") & pl.col("home_score").is_not_null())
        .sort("gameday", "gametime", "game_id")
        .to_dicts()
    )
    for g in games:
        h, a = g["home_team"], g["away_team"]
        if h not in table or a not in table:
            continue
        hs, as_ = int(g["home_score"]), int(g["away_score"])
        for me, opp, pf, pa, at_home in ((h, a, hs, as_, True), (a, h, as_, hs, False)):
            t, o = table[me], table[opp]
            diff = pf - pa
            t.overall.add(diff)
            (t.home if at_home else t.away).add(diff)
            if t.div == o.div:
                t.division.add(diff)
            if t.conf == o.conf:
                t.conference.add(diff)
            t.pf += pf
            t.pa += pa
            t.results.append((g["gameday"], opp, diff))

    def h2h_pct(t: _Team, group: set[str]) -> float:
        r = _Rec()
        for _, opp, diff in t.results:
            if opp in group:
                r.add(diff)
        return r.pct if r.games else 0.5

    def streak(t: _Team) -> str | None:
        if not t.results:
            return None
        sign = lambda d: (d > 0) - (d < 0)  # noqa: E731
        last = sign(t.results[-1][2])
        n = 0
        for *_, d in reversed(t.results):
            if sign(d) != last:
                break
            n += 1
        return f"{'V' if last > 0 else 'D' if last < 0 else 'N'}{n}"

    by_div: dict[str, list[_Team]] = defaultdict(list)
    for t in table.values():
        by_div[t.div].append(t)

    out: list[DivisionStandings] = []
    for div in sorted(by_div):
        members = by_div[div]
        # Groupes d'égalité au pourcentage, puis départage à l'intérieur de chaque groupe.
        ties: dict[float, set[str]] = defaultdict(set)
        for t in members:
            ties[round(t.overall.pct, 6)].add(t.abbr)

        def key(t: _Team):
            group = ties[round(t.overall.pct, 6)]
            return (-t.overall.pct, -h2h_pct(t, group - {t.abbr}) if len(group) > 1 else 0,
                    -t.division.pct, -t.conference.pct, -(t.pf - t.pa), t.abbr)

        rows = [
            StandingRow(
                team=t.abbr, name=info[t.abbr]["team_name"], conference=t.conf, division=t.div,
                wins=t.overall.w, losses=t.overall.l, ties=t.overall.t, pct=round(t.overall.pct, 3),
                points_for=t.pf, points_against=t.pa, diff=t.pf - t.pa,
                div_record=str(t.division), conf_record=str(t.conference),
                home_record=str(t.home), away_record=str(t.away), streak=streak(t),
            )
            for t in sorted(members, key=key)
        ]
        out.append(DivisionStandings(name=div, conference=members[0].conf, rows=rows))
    return out

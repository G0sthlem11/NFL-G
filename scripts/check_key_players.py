"""Affiche les joueurs clés d'un ou plusieurs matchs, avec le détail des scores.

Usage : py -m scripts.check_key_players [game_id ...]
Sans argument : le dernier match terminé de la saison en cache.
"""
import sys

import nflreadpy as nfl
import polars as pl

from app.data.cache import SeasonCache
from app.data.repository import NflRepository

repo = NflRepository(SeasonCache(nfl.get_current_season()))


def n(v) -> float:
    return v or 0


def show(game_id: str) -> None:
    d = repo.game_detail(game_id)
    if d is None or d.key_players is None:
        print(f"\n{game_id} : match introuvable ou pas encore joué")
        return
    g, k = d.game, d.key_players
    print(f"\n{g.game_id}  {g.away_team} {g.away_score} - {g.home_score} {g.home_team}"
          f"   (pressions PFR : {'oui' if k.pressures_available else 'non'})")
    for side in (k.away, k.home):
        print(f"\n  === {side.team} ===")
        print("  QB")
        for p in side.quarterbacks:
            print(f"    {p.team:3} {p.name:24} {n(p.completions)}/{n(p.attempts)}  {n(p.passing_yards)} yds"
                  f"  {n(p.passing_tds)} TD  {n(p.interceptions)} INT")
        print("  Top offensif  (yds course + yds réc. + 20 × TD)")
        for r in side.offense:
            p = r.player
            print(f"    {r.rank}. {p.team:3} {p.name:24} {p.position or '':3} {r.score:6.1f}"
                  f"   course {n(p.rushing_yards):4}  réc. {n(p.receiving_yards):4}"
                  f"  TD {n(p.rushing_tds) + n(p.receiving_tds)}")
        print("  Top défensif  (6 INT + 4 sacks + 3 PD + 2 QB hits + 1,5 press. + 1 plaq.)")
        for r in side.defense:
            p = r.player
            press = "—" if p.pressures is None else f"{p.pressures:g}"
            print(f"    {r.rank}. {p.team:3} {p.name:24} {p.position or '':3} {r.score:6.1f}"
                  f"   INT {n(p.def_interceptions)}  sacks {n(p.sacks):g}  PD {n(p.passes_defended)}"
                  f"  hits {n(p.qb_hits)}  press. {press}  plaq. {n(p.tackles)}")
        print("  Kicker")
        for p in side.kickers:
            print(f"    {p.team:3} {p.name:24} FG {n(p.fg_made)}/{n(p.fg_att)}  long {p.fg_long or '—'}"
                  f"  XP {n(p.pat_made)}/{n(p.pat_att)}")


if __name__ == "__main__":
    ids = sys.argv[1:]
    if not ids:
        s = repo.cache.get("schedules").filter(pl.col("home_score").is_not_null())
        ids = [s.sort("gameday")["game_id"][-1]]
    for gid in ids:
        show(gid)

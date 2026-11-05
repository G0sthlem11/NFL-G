"""Contrôle de la logique joueurs clés sur toute la saison en cache.

Usage : py -m scripts.check_key_players [game_id]
"""
import sys
from collections import Counter

import nflreadpy as nfl
import polars as pl

from app.data.cache import SeasonCache
from app.data.repository import NflRepository

repo = NflRepository(SeasonCache(nfl.get_current_season()))


def show(game_id: str) -> None:
    d = repo.game_detail(game_id)
    g = d.game
    print(f"\n{g.game_id}  {g.away_team} {g.away_score} - {g.home_score} {g.home_team}")
    for kp in (d.away_key, d.home_key):
        print(f"  {kp.team}  schéma {kp.scheme}  snapshot {kp.depth_chart_dt}")
        for k in kp.offense + kp.edges:
            name = k.player.name if k.player else "—"
            note = f"  (remplace {k.replaced_starter}, {k.replaced_reason})" if k.replaced_starter else ""
            print(f"    {k.label:4} {k.depth_pos or '':5} {name:24} [{k.source}]{note}")
        tl = kp.tackle_leader
        print(f"    plaquages : {tl.name if tl else '—'} ({tl.tackles if tl else '—'})")
        print("    big plays :", ", ".join(
            f"{p.name} ({'INT ' if p.def_interceptions else ''}{'FF ' if p.fumbles_forced else ''}"
            f"{str(p.sacks) + ' sk' if p.sacks else ''})".replace(" )", ")") for p in kp.playmakers) or "—")


if len(sys.argv) > 1:
    show(sys.argv[1])
    sys.exit()

finals = repo._schedules().filter(pl.col("home_score").is_not_null())["game_id"].to_list()
sources, reasons, none_roles = Counter(), Counter(), Counter()
for gid in finals:
    d = repo.game_detail(gid)
    for kp in (d.away_key, d.home_key):
        for k in kp.offense + kp.edges:
            sources[k.source] += 1
            if k.replaced_reason:
                reasons[(k.role, k.replaced_reason)] += 1
            if k.source == "none":
                none_roles[(kp.team, gid, k.role)] += 1
print(f"{len(finals)} matchs, {sum(sources.values())} rôles")
print("sources :", dict(sources))
print("remplacements (rôle, motif) :", reasons.most_common(15))
print("rôles vides :", list(none_roles)[:10])
show(finals[-1])
show("2026_08_CAR_GB")

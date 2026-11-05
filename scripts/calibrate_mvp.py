"""Vérification du MVP normalisé (percentiles par catégorie, key_players.toml).

Usage : py -m scripts.calibrate_mvp [game_id ...]

Affiche, pour la saison en cache :

1. les distributions de référence (meilleur score de chaque équipe dans
   chaque match, par catégorie) ;
2. la répartition des MVP par catégorie selon le malus du kicker ;
3. les « grosses performances défensives » de l'équipe gagnante (3 sacks ou
   plus, ou 2 interceptions ou plus) et si elles donnent le MVP ;
4. pour les matchs demandés (sinon quelques matchs de la saison), le meilleur
   joueur de chaque catégorie de l'équipe gagnante avec son score brut et son
   percentile, puis le MVP retenu.
"""
from __future__ import annotations

import sys
from collections import Counter

import nflreadpy as nfl
import polars as pl

from app.data.cache import SeasonCache
from app.data.key_players import CATEGORIES, load_config, mvp_candidates, select_mvp
from app.data.repository import NflRepository

repo = NflRepository(SeasonCache(nfl.get_current_season()))
LABEL = {"qb": "QB", "offense": "Offensif", "defense": "Défensif", "kicker": "Kicker"}
DEFAULT_GAMES = ["2026_08_CAR_GB", "2026_08_ARI_DAL", "2026_07_NYG_HOU", "2026_05_CLE_NYJ",
                 "2026_06_ARI_LA", "2026_02_CAR_ATL"]


def is_big_defense(p) -> bool:
    return (p.sacks or 0) >= 3 or (p.def_interceptions or 0) >= 2


def winners(d):
    g, k = d.game, d.key_players
    if g.away_score > g.home_score:
        return [k.away]
    if g.home_score > g.away_score:
        return [k.home]
    return [k.away, k.home]


def finals():
    s = repo.cache.get("schedules").filter(pl.col("home_score").is_not_null()).sort("gameday")
    return [d for gid in s["game_id"].to_list() if (d := repo.game_detail(gid)) and d.key_players]


def main(game_ids: list[str]) -> None:
    cfg = load_config()
    scale = repo.mvp_scale()
    details = finals()
    print(f"Référence : saison(s) {', '.join(map(str, scale.seasons))}, {scale.games} matchs\n")
    print(f"  {'catégorie':9} {'n':>4} {'p25':>6} {'p50':>6} {'p75':>6} {'p90':>6} {'max':>6}")
    for c in CATEGORIES:
        v = scale.sorted[c]
        q = lambda f: v[min(len(v) - 1, int(len(v) * f))] if v else 0  # noqa: E731
        print(f"  {LABEL[c]:9} {len(v):4} {q(.25):6.1f} {q(.5):6.1f} {q(.75):6.1f} {q(.9):6.1f} {v[-1] if v else 0:6.1f}")

    print(f"\nMVP par catégorie selon le malus kicker ({len(details)} matchs)")
    for kf in (1.0, 0.8, cfg["mvp"]["kicker_factor"]):
        c2 = {**cfg, "mvp": {**cfg["mvp"], "kicker_factor": kf}}
        n = Counter(select_mvp(d.key_players.away, d.key_players.home, d.game.away_score,
                               d.game.home_score, c2, scale).category for d in details)
        print(f"  × {kf:<4g}  QB {n['qb']:3}   offensif {n['offense']:3}   défensif {n['defense']:3}   kicker {n['kicker']:3}")

    print("\nGrosses performances défensives de l'équipe gagnante")
    won = total = 0
    for d in details:
        mvp = d.key_players.mvp
        for c in (c for s in winners(d) for c in mvp_candidates(s, cfg, scale)):
            if c.category == "defense" and is_big_defense(c.player):
                total += 1
                won += mvp.player.player_id == c.player.player_id
                p = c.player
                print(f"  {d.game.game_id:17} {p.name:22} {p.sacks or 0:g} sacks {p.def_interceptions or 0} INT"
                      f"  brut {c.score:5.1f}  p{c.percentile:5.1f}  -> MVP : {mvp.player.name}"
                      f" ({LABEL[mvp.category]}, p{mvp.normalized:g})")
    print(f"  => {won}/{total} désignées MVP")

    for gid in game_ids or DEFAULT_GAMES:
        d = repo.game_detail(gid)
        if not d or not d.key_players or not d.key_players.mvp:
            print(f"\n{gid} : pas de MVP (match introuvable ou non joué)")
            continue
        g, mvp = d.game, d.key_players.mvp
        print(f"\n{gid}  {g.away_team} {g.away_score} - {g.home_score} {g.home_team}")
        pool = [c for s in winners(d) for c in mvp_candidates(s, cfg, scale)]
        for cat in CATEGORIES:
            best = max((c for c in pool if c.category == cat), key=lambda c: (c.normalized, c.score), default=None)
            if best:
                malus = f" × {cfg['mvp']['kicker_factor']:g} = {best.normalized:g}" if cat == "kicker" else ""
                print(f"  {LABEL[cat]:9} {best.player.name:24} brut {best.score:6.1f}   percentile {best.percentile:5.1f}{malus}")
        print(f"  => MVP : {mvp.player.name} ({mvp.player.team}, {LABEL[mvp.category]})")


if __name__ == "__main__":
    main(sys.argv[1:])

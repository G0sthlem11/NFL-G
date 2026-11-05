"""Phase 1 — scores par quart-temps reconstituables depuis le play-by-play ?"""
import time
import polars as pl
import nflreadpy as nfl

t = time.time()
pbp = nfl.load_pbp([nfl.get_current_season()])
print(f"load_pbp : {pbp.height} actions, {pbp.width} colonnes, {time.time() - t:.1f}s, "
      f"~{pbp.estimated_size('mb'):.0f} Mo en mémoire")

gid = "2026_08_CAR_GB"
g = pbp.filter(pl.col("game_id") == gid)
q = (g.group_by("qtr").agg(pl.col("total_away_score").max().alias("away_cum"),
                           pl.col("total_home_score").max().alias("home_cum"))
     .sort("qtr")
     .with_columns(pl.col("away_cum").diff().fill_null(pl.col("away_cum")).alias("away"),
                   pl.col("home_cum").diff().fill_null(pl.col("home_cum")).alias("home")))
print(q)

# Contrôle sur tous les matchs : somme des quarts == score final ?
sched = nfl.load_schedules([nfl.get_current_season()]).filter(pl.col("home_score").is_not_null())
fin = pbp.group_by("game_id").agg(pl.col("total_home_score").max().alias("h"),
                                  pl.col("total_away_score").max().alias("a"))
chk = sched.join(fin, on="game_id", how="left")
ok = chk.filter((pl.col("h") == pl.col("home_score")) & (pl.col("a") == pl.col("away_score"))).height
print(f"Scores finaux pbp == schedules : {ok}/{chk.height}")

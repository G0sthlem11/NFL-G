"""Phase 2 — vérifie le codage des edges en 3-4 (SLB/WLB) et les colonnes pbp utiles."""
import polars as pl
import nflreadpy as nfl

pl.Config.set_tbl_rows(80)
pl.Config.set_tbl_width_chars(200)
season = nfl.get_current_season()
dc = nfl.load_depth_charts([season])
ps = nfl.load_player_stats([season])

last = dc.join(dc.group_by("team").agg(pl.col("dt").max()), on=["team", "dt"])
front = last.filter((pl.col("pos_rank") == 1)
                    & pl.col("pos_abb").is_in(["LDE", "RDE", "SLB", "WLB", "LILB", "RILB", "MLB"]))
season_tot = ps.group_by("player_id").agg(
    pl.col("position").last(), pl.col("def_sacks").sum().alias("sacks"),
    pl.col("def_qb_hits").sum().alias("qb_hits"),
    (pl.col("def_tackles_solo") + pl.col("def_tackle_assists")).sum().alias("tkl"))
out = front.join(season_tot, left_on="gsis_id", right_on="player_id", how="left")
print(out.filter(pl.col("team").is_in(["GB", "PIT", "BAL", "DAL", "KC", "DET"]))
      .select("team", "pos_grp", "pos_abb", "player_name", "position", "sacks", "qb_hits", "tkl")
      .sort("team", "pos_abb"))

print("\nMoyenne de sacks saison par pos_abb, selon le schéma :")
print(out.group_by("pos_grp", "pos_abb").agg(pl.col("sacks").mean().round(2),
                                             pl.col("qb_hits").mean().round(2),
                                             pl.col("position").mode().first().alias("pos_stats"))
      .sort("pos_grp", "pos_abb"))

pbp = nfl.load_pbp([season])
print("\npbp, colonnes first_down* :", [c for c in pbp.columns if c.startswith("first_down")])
print("qtr distincts :", sorted(pbp["qtr"].drop_nulls().unique().to_list()))

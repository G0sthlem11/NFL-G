"""Phase 1 — vérifications ciblées complémentaires."""
import polars as pl
import nflreadpy as nfl

pl.Config.set_tbl_rows(40)
pl.Config.set_tbl_width_chars(200)
season = nfl.get_current_season()
sched = nfl.load_schedules([season])
ps = nfl.load_player_stats([season])
ts = nfl.load_team_stats([season])
dc = nfl.load_depth_charts([season])

print("PLAYER_STATS COLS:", ", ".join(ps.columns))
print("\nTEAM_STATS COLS:", ", ".join(ts.columns))

print("\n--- Colonnes équipe utiles (1ers downs, pénalités, turnovers) ---")
for kw in ("first_down", "penalt", "fumble", "interception", "sack", "turnover"):
    print(kw, "->", [c for c in ts.columns if kw in c])

played = sched.filter(pl.col("home_score").is_not_null())
print("\n--- Météo ---")
print(played.group_by("roof").agg(pl.len(), pl.col("temp").is_not_null().sum().alias("temp_ok"),
                                  pl.col("wind").is_not_null().sum().alias("wind_ok")))

print("\n--- Fuseau gametime : exemples ---")
print(sched.select("game_id", "gameday", "gametime", "weekday").unique("gametime").head(10))

print("\n--- Depth chart : WR / TE / RB / QB / DE pour une équipe, dernier snapshot ---")
last = dc.filter(pl.col("team") == "GB")["dt"].max()
snap = dc.filter((pl.col("team") == "GB") & (pl.col("dt") == last))
print(snap.filter(pl.col("pos_abb").is_in(["QB", "RB", "WR", "TE", "LDE", "RDE"]))
      .select("pos_grp", "pos_abb", "pos_slot", "pos_rank", "player_name", "gsis_id")
      .sort("pos_abb", "pos_slot", "pos_rank"))

print("\n--- Snapshots par équipe et fréquence ---")
per = dc.select("team", "dt").unique().group_by("team").len()
print("snapshots/équipe : min", per["len"].min(), "max", per["len"].max())
print("équipes :", dc["team"].n_unique())
print("10 derniers dt :", sorted(dc["dt"].unique().to_list())[-10:])

print("\n--- 3-4 vs 4-3 : y a-t-il des LDE/RDE dans les équipes 3-4 ? ---")
lastsnap = dc.join(dc.group_by("team").agg(pl.col("dt").max()), on=["team", "dt"])
print(lastsnap.filter(pl.col("pos_rank") == 1).group_by("team")
      .agg(pl.col("pos_grp").filter(pl.col("pos_grp").str.contains("Base")).first().alias("def"),
           pl.col("pos_abb").filter(pl.col("pos_abb").is_in(["LDE", "RDE", "NT", "LDT", "RDT"]))
           .sort().alias("dl"))
      .sort("team").head(32))

print("\n--- gsis_id -> player_id ---")
ids = set(ps["player_id"].drop_nulls().to_list())
dcid = dc.filter(pl.col("pos_rank") == 1)["gsis_id"]
print("gsis_id nuls (rang 1) :", dcid.is_null().sum(), "/", dcid.len())
u = set(dcid.drop_nulls().unique().to_list())
print("gsis_id titulaires retrouvés dans player_stats :", len(u & ids), "/", len(u))

print("\n--- player_stats : positions ---")
print(ps.group_by("position").len().sort("len", descending=True))
print("headshot_url non nul :", ps["headshot_url"].is_not_null().mean())

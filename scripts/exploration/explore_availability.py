"""Jalon 4 — comment savoir si un titulaire a joué ? (rosters hebdo, snap counts)"""
import polars as pl
import nflreadpy as nfl

pl.Config.set_tbl_rows(30)
pl.Config.set_tbl_width_chars(220)
pl.Config.set_tbl_cols(-1)
season = nfl.get_current_season()

rw = nfl.load_rosters_weekly([season])
print("ROSTERS_WEEKLY cols:", rw.columns)
print(rw.group_by("status").len().sort("len", descending=True))
if "status_description_abbr" in rw.columns:
    print(rw.group_by("status", "status_description_abbr").len().sort("len", descending=True).head(20))
print("semaines :", sorted(rw["week"].unique().to_list()))

sc = nfl.load_snap_counts([season])
print("\nSNAP_COUNTS cols:", sc.columns)
print(sc.head(3))

# Les titulaires de rang 1 absents de player_stats, ont-ils des snaps ?
ps = nfl.load_player_stats([season])
g = "2026_08_CAR_GB"
gps = ps.filter(pl.col("game_id") == g)
roster = rw.filter((pl.col("week") == 8) & pl.col("team").is_in(["CAR", "GB"]))
gsc = sc.filter(pl.col("game_id") == g)
print(f"\n{g}: {gps.height} lignes player_stats, {gsc.height} lignes snap_counts, roster {roster.height}")
missing = roster.filter(~pl.col("gsis_id").is_in(gps["player_id"].to_list())
                        & pl.col("position").is_in(["QB", "RB", "WR", "TE", "DE", "OLB", "LB", "DL"]))
print(missing.select("team", "full_name", "position", "status", *[c for c in ("status_description_abbr",) if c in rw.columns]).sort("team", "position"))

# Correspondance d'identifiants pour les snap counts
if "pfr_id" in rw.columns:
    print("\nrosters_weekly contient pfr_id : jointure snap_counts possible")
    j = gsc.join(roster.select("pfr_id", "gsis_id"), left_on="pfr_player_id", right_on="pfr_id", how="left")
    print("snap rows sans gsis :", j["gsis_id"].is_null().sum(), "/", j.height)

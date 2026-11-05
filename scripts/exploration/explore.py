"""Phase 1 — exploration des données nflverse pour la saison en cours."""
import polars as pl
import nflreadpy as nfl

pl.Config.set_tbl_cols(-1)
pl.Config.set_tbl_rows(60)
pl.Config.set_fmt_str_lengths(40)
pl.Config.set_tbl_width_chars(250)


def section(t):
    print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


season = nfl.get_current_season()
section(f"Saison en cours : {season}")

# --- Calendrier ---
sched = nfl.load_schedules([season])
section("schedules : colonnes")
print(sched.columns)
played = sched.filter(pl.col("home_score").is_not_null())
print(f"\nMatchs : {sched.height} au total, {played.height} terminés")
print("Types de match :", sched["game_type"].unique().to_list())
last_week = played["week"].max()
print("Dernière semaine avec résultats :", last_week)
print(played.group_by("week").len().sort("week"))

# --- Stats joueurs ---
ps = nfl.load_player_stats([season])
section("player_stats : colonnes")
print(ps.columns)
print("Semaines présentes :", sorted(ps["week"].unique().to_list()))
print("Colonne game_id présente :", "game_id" in ps.columns)

# --- Stats équipe ---
ts = nfl.load_team_stats([season])
section("team_stats : colonnes")
print(ts.columns)
print("Semaines présentes :", sorted(ts["week"].unique().to_list()))

# --- Depth charts ---
dc = nfl.load_depth_charts([season])
section("depth_charts : colonnes")
print(dc.columns)
print(dc.head(5))
for c in ("pos_abb", "pos_grp", "pos_name", "pos_slot"):
    if c in dc.columns:
        print(f"\nValeurs distinctes de {c} :")
        print(dc.group_by(c).len().sort("len", descending=True))
if "dt" in dc.columns:
    print("\nSnapshots (dt) distincts :", dc["dt"].n_unique(),
          "| min", dc["dt"].min(), "| max", dc["dt"].max())

# --- Scores par quart-temps ? ---
section("Scores par quart-temps")
qcols = [c for c in sched.columns if "q1" in c.lower() or "quarter" in c.lower() or "qtr" in c.lower()]
print("Colonnes 'quart-temps' dans schedules :", qcols or "aucune")
print("Colonnes 'quart-temps' dans team_stats :",
      [c for c in ts.columns if "q1" in c.lower() or "quarter" in c.lower()] or "aucune")

# --- Exemple de match complet ---
g = played.filter(pl.col("week") == last_week).row(0, named=True)
gid = g["game_id"]
section(f"Exemple de match : {gid}")
for k, v in g.items():
    print(f"  {k:22} {v}")

section("team_stats du match")
tsg = ts.filter((pl.col("week") == g["week"]) & pl.col("team").is_in([g["away_team"], g["home_team"]]))
print(tsg.transpose(include_header=True, column_names="team") if tsg.height else "aucune ligne")

section("player_stats du match (colonnes non nulles et non nulles à zéro)")
psg = ps.filter(pl.col("game_id") == gid) if "game_id" in ps.columns else \
    ps.filter((pl.col("week") == g["week"]) & pl.col("team").is_in([g["away_team"], g["home_team"]]))
print(f"{psg.height} joueurs")
num = [c for c, t in psg.schema.items() if t.is_numeric() and c not in ("season", "week")]
keep = [c for c in num if psg[c].fill_null(0).abs().sum() > 0]
print(psg.select(["team", "player_display_name", "position"] + keep)
      .sort(["team", "position"]))

section(f"Depth chart le plus récent avant {g['gameday']} — {g['home_team']}")
if "dt" in dc.columns:
    sub = dc.filter((pl.col("team") == g["home_team"])
                    & (pl.col("dt").cast(pl.Utf8).str.slice(0, 10) <= g["gameday"]))
    if sub.height:
        last = sub["dt"].max()
        print("Snapshot :", last)
        print(sub.filter(pl.col("dt") == last).sort(["pos_abb", "pos_rank"]))
    else:
        print("aucun snapshot antérieur")

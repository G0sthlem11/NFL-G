"""Classements par poste : poste, titulaire, équipe d'un joueur échangé, moyenne par match."""
import polars as pl

from app.data.key_players import DEFAULTS
from app.data.rankings import compute_rankings, resolve_group

TEAMS = ("AAA", "BBB")


def stat(pid, team, position, week, **stats):
    return {"player_id": pid, "player_display_name": pid, "position": position, "team": team,
            "game_id": f"2026_{week:02d}_AAA_BBB", "week": week, "season": 2026, **stats}


def snap(pid, team, position, week, off=0, deff=0):
    return {"game_id": f"2026_{week:02d}_AAA_BBB", "week": week, "player": pid, "pfr_player_id": f"pfr_{pid}",
            "position": position, "team": team, "offense_snaps": float(off), "defense_snaps": float(deff),
            "st_snaps": 0.0}


def player(pid, position, pff=None, ngs=None):
    return {"gsis_id": pid, "pfr_id": f"pfr_{pid}", "display_name": pid, "position": position,
            "ngs_position": ngs, "pff_position": pff}


def rank(stats, snaps, players, cfg=None):
    df = lambda rows: pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()  # noqa: E731
    return {p.key: p for p in compute_rankings(2026, df(stats), df(snaps), df(players), None, cfg or DEFAULTS).positions}


def ids(pos):
    return [r.player_id for r in pos.rows]


def test_position_sources_in_priority_order():
    # pff_position sépare le pass rusher (ED) du linebacker, que « position » confond.
    assert resolve_group({"pff_position": "ED", "position": "LB"}, DEFAULTS) == "EDGE"
    assert resolve_group({"pff_position": "LB", "position": "OLB"}, DEFAULTS) == "LB"
    assert resolve_group({"pff_position": None, "ngs_position": "FK", "position": None}, DEFAULTS) == "K"
    # Code inconnu (rôle de special teams) : source suivante.
    assert resolve_group({"ngs_position": "KL4", "position": "LB"}, DEFAULTS) == "LB"
    assert resolve_group({"pff_position": "T", "position": "OT"}, DEFAULTS) is None


def test_starter_is_the_player_with_most_snaps():
    stats = [stat("WR1", "AAA", "WR", w, receiving_yards=50) for w in range(1, 5)]
    stats += [stat("WR2", "AAA", "WR", w, receiving_yards=120) for w in range(1, 5)]
    snaps = [snap("WR1", "AAA", "WR", w, off=60) for w in range(1, 5)]
    snaps += [snap("WR2", "AAA", "WR", w, off=30) for w in range(1, 5)]
    r = rank(stats, snaps, [player("WR1", "WR", "WR"), player("WR2", "WR", "WR")])
    assert ids(r["WR"]) == ["WR1"]  # plus de snaps, même s'il a moins de yards
    assert r["WR"].rows[0].snaps == 240


def test_traded_player_counts_for_team_where_he_played_most():
    stats = [stat("LB1", "AAA", "LB", w, def_tackles_solo=5) for w in range(1, 4)]
    stats += [stat("LB1", "BBB", "LB", w, def_tackles_solo=5) for w in range(4, 6)]
    snaps = [snap("LB1", "AAA", "LB", w, deff=50) for w in range(1, 4)]
    snaps += [snap("LB1", "BBB", "LB", w, deff=50) for w in range(4, 6)]
    stats += [stat("LB2", "BBB", "LB", w, def_tackles_solo=1) for w in range(1, 6)]
    snaps += [snap("LB2", "BBB", "LB", w, deff=40) for w in range(1, 6)]
    r = rank(stats, snaps, [player("LB1", "LB", "LB"), player("LB2", "LB", "LB")])
    by_team = {row.team: row for row in r["LB"].rows}
    assert by_team["AAA"].player_id == "LB1"
    assert by_team["BBB"].player_id == "LB2"  # LB1 ne compte pas pour BBB
    assert by_team["AAA"].games == 5 and by_team["AAA"].totals.tackles == 25  # toute sa saison


def test_ranked_on_average_with_few_games_last():
    # WR_A : 4 matchs à 100 ; WR_B : 2 matchs à 150 (sous le minimum) ; moyenne, pas total.
    stats = [stat("WR_A", "AAA", "WR", w, receiving_yards=100) for w in range(1, 5)]
    stats += [stat("WR_B", "BBB", "WR", w, receiving_yards=150) for w in range(1, 3)]
    snaps = [snap("WR_A", "AAA", "WR", w, off=50) for w in range(1, 5)]
    snaps += [snap("WR_B", "BBB", "WR", w, off=50) for w in range(1, 3)]
    r = rank(stats, snaps, [player("WR_A", "WR", "WR"), player("WR_B", "WR", "WR")])
    rows = r["WR"].rows
    assert ids(r["WR"]) == ["WR_A", "WR_B"]
    assert (rows[0].eligible, rows[1].eligible) == (True, False)
    assert (rows[0].score_avg, rows[0].score_total) == (100.0, 400.0)
    assert [x.rank for x in rows] == [1, 2]

    cfg = {**DEFAULTS, "rankings": {**DEFAULTS["rankings"], "min_games": 2}}
    r = rank(stats, snaps, [player("WR_A", "WR", "WR"), player("WR_B", "WR", "WR")], cfg)
    assert ids(r["WR"]) == ["WR_B", "WR_A"]  # 150 de moyenne > 100


def test_games_played_count_snaps_without_stats():
    # 4 matchs joués (snaps), stats dans 2 seulement : moyenne sur 4.
    stats = [stat("CB1", "AAA", "CB", w, def_pass_defended=2) for w in (1, 2)]
    snaps = [snap("CB1", "AAA", "CB", w, deff=60) for w in range(1, 5)]
    r = rank(stats, snaps, [player("CB1", "CB", "CB")])
    row = r["CB"].rows[0]
    assert row.games == 4 and row.score_total == 12.0 and row.score_avg == 3.0


def test_kicker_by_games_played_and_kicker_score():
    stats = [stat("K1", "AAA", "K", w, fg_made=2, fg_att=2, pat_made=1, pat_att=1, fg_long=48) for w in range(1, 5)]
    stats += [stat("K2", "AAA", "K", 5, fg_made=1, fg_att=1, fg_made_50_59=1, fg_long=55)]
    r = rank(stats, [], [player("K1", "K", None, "FK"), player("K2", "K", "K")])
    row = r["K"].rows[0]
    assert ids(r["K"]) == ["K1"] and row.games == 4 and row.snaps is None
    assert row.score_avg == 7.0  # 3 × 2 FG + 1 XP
    assert (row.totals.fg_made, row.totals.fg_att, row.totals.fg_long, row.totals.pat_made) == (8, 8, 48, 4)

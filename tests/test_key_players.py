"""Tests de la logique « joueurs clés » sur de petits jeux de données (tests/fixtures)."""
import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from app.data.key_players import latest_snapshot, select_key_players

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def df(rows):
        return pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()

    kickoff = datetime.fromisoformat(raw["kickoff_utc"]) if raw["kickoff_utc"] else None
    kp = select_key_players(
        team=raw["team"], gameday=raw["gameday"], kickoff=kickoff,
        stats=df(raw["player_stats"]), depth=df(raw["depth_charts"]), roster=df(raw["rosters"]),
    )
    return raw, kp


def by_role(kp):
    return {k.role: k for k in kp.offense + kp.edges}


# --- 4-3, titulaires absents ---------------------------------------------
@pytest.fixture(scope="module")
def aaa():
    return load("team_43_injuries.json")[1]


def test_uses_latest_snapshot_before_kickoff(aaa):
    # Le snapshot du 04/10 à 23:00Z (après le match) fait de A_QB2 le titulaire : ignoré.
    assert aaa.depth_chart_dt == "2026-10-03T07:00:00Z"
    assert by_role(aaa)["QB"].player.player_id == "A_QB1"


def test_old_snapshot_is_not_used(aaa):
    assert by_role(aaa)["WR1"].player.player_id == "A_WR1"  # pas A_WR_OLD (snapshot du 28/09)


def test_starters_who_played_come_from_depth_chart(aaa):
    r = by_role(aaa)
    assert r["RB1"].player.player_id == "A_RB1" and r["RB1"].source == "depth_chart"
    assert r["TE1"].player.player_id == "A_TE1"
    assert r["EDGE1"].player.player_id == "A_DE1" and r["EDGE1"].depth_pos == "LDE"
    assert aaa.scheme == "4-3" and r["EDGE1"].label == "DE"


def test_inactive_wr2_replaced_by_most_productive_wr(aaa):
    wr2 = by_role(aaa)["WR2"]
    assert wr2.source == "replacement"
    assert wr2.player.player_id == "A_WR3"  # 95 yds, devant A_WR4 (20 yds)
    assert wr2.replaced_starter == "Wide Two" and wr2.replaced_reason == "inactif"


def test_reserve_rde_replaced_by_other_de(aaa):
    edge2 = by_role(aaa)["EDGE2"]
    assert edge2.player.player_id == "A_DE3"
    assert edge2.replaced_starter == "Right End" and edge2.replaced_reason == "en réserve"


def test_no_player_holds_two_roles(aaa):
    ids = [k.player.player_id for k in aaa.offense + aaa.edges if k.player]
    assert len(ids) == len(set(ids))


def test_tackle_leader_counts_solo_plus_assists(aaa):
    # A_LB1 : 7 + 5 = 12 ; A_LB2 : 9 + 1 = 10
    assert aaa.tackle_leader.player_id == "A_LB1" and aaa.tackle_leader.tackles == 12


def test_playmakers_sack_int_ff(aaa):
    assert [p.player_id for p in aaa.playmakers] == ["A_CB1", "A_S1", "A_DE3"]
    assert aaa.playmakers[2].sacks == 1.5


# --- 3-4 : edges = SLB/WLB -----------------------------------------------
@pytest.fixture(scope="module")
def bbb():
    return load("team_34_edges.json")[1]


def test_34_edges_are_outside_linebackers(bbb):
    r = by_role(bbb)
    assert bbb.scheme == "3-4"
    assert (r["EDGE1"].player.player_id, r["EDGE1"].depth_pos, r["EDGE1"].label) == ("B_OLB1", "SLB", "OLB")
    assert (r["EDGE2"].player.player_id, r["EDGE2"].depth_pos) == ("B_OLB2", "WLB")


def test_active_starter_without_stats_is_replaced(bbb):
    te = by_role(bbb)["TE1"]
    assert te.player.player_id == "B_TE2"
    assert te.replaced_starter == "Bravo TE1" and te.replaced_reason == "actif sans stat"


def test_34_playmakers_include_interior_sack(bbb):
    assert [p.player_id for p in bbb.playmakers] == ["B_OLB2", "B_OLB1", "B_DL1"]


# --- Pas de depth chart : repli ------------------------------------------
@pytest.fixture(scope="module")
def ccc():
    return load("team_no_depth_chart.json")[1]


def test_fallback_without_depth_chart(ccc):
    r = by_role(ccc)
    assert ccc.depth_chart_dt is None and ccc.scheme is None
    assert all(k.source == "fallback" for k in ccc.offense + ccc.edges)
    assert r["QB"].player.player_id == "C_QB"
    assert r["RB1"].player.player_id == "C_RB2"
    assert (r["WR1"].player.player_id, r["WR2"].player.player_id) == ("C_WR2", "C_WR3")
    assert r["TE1"].player.player_id == "C_TE"
    assert (r["EDGE1"].player.player_id, r["EDGE2"].player.player_id) == ("C_OLB", "C_DE1")


def test_rows_without_player_id_are_ignored(ccc):
    # La fixture contient une ligne sans player_id avec 9 plaquages et un FF.
    assert ccc.tackle_leader.player_id == "C_LB"
    assert all(p.player_id for p in ccc.playmakers)


def test_missing_role_is_none_not_error():
    kp = select_key_players("ZZZ", "2026-10-04", None, pl.DataFrame(), pl.DataFrame(), pl.DataFrame())
    assert all(k.source == "none" and k.player is None for k in kp.offense + kp.edges)
    assert kp.tackle_leader is None and kp.playmakers == []


def test_latest_snapshot_same_day_without_kickoff():
    depth = pl.DataFrame({"dt": ["2026-10-04T07:00:00Z", "2026-10-05T07:00:00Z"], "x": [1, 2]})
    assert latest_snapshot(depth, "2026-10-04", None)["x"].to_list() == [1]

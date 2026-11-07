"""Effectifs : sélection des dernières photos, depth chart, tri et regroupement."""
import json
import tomllib

import polars as pl
import pytest

from app.data.rosters import (COLLEGE_MAP_PATH, COLLEGE_OVERRIDES_PATH, LOGO_ROOT, build_index, build_team_roster,
                              college_logos, depth_assignments, latest_depth_charts, latest_rosters)
from scripts.fetch_college_logos import match, normalize, pick_dark


def player(gsis, name, pos, dcp, jersey, status="ACT", detail="A01", **kw):
    return {"season": 2026, "week": kw.pop("week", 9), "team": kw.pop("team", "HOU"), "gsis_id": gsis,
            "full_name": name, "jersey_number": jersey, "position": pos, "depth_chart_position": dcp,
            "status": status, "status_description_abbr": detail, "height": 75, "weight": 220,
            "birth_date": "2001-10-03", "years_exp": 3, "college": kw.pop("college", "Ohio State"),
            "rookie_year": 2023, "entry_year": 2023, "draft_club": kw.pop("draft_club", None),
            "draft_number": kw.pop("draft_number", None), "headshot_url": None, **kw}


def depth(gsis, grp, slot, abb, rank, dt="2026-11-07T13:54:10Z"):
    return {"dt": dt, "team": "HOU", "gsis_id": gsis, "player_name": gsis, "pos_grp": grp,
            "pos_slot": slot, "pos_abb": abb, "pos_rank": rank}


OFF, DEF, ST = "3WR 1TE", "Base 4-3 D", "Special Teams"

ROSTER = pl.DataFrame([
    player("QB1", "Starter QB", "QB", "QB", 7, draft_number=2, draft_club="HOU"),
    player("QB2", "Backup QB", "QB", "QB", 10),
    player("QB3", "Blessé QB", "QB", "QB", 18, status="RES", detail="R01"),
    player("LT", "Left Tackle", "OL", "T", 74),
    player("C", "Centre", "OL", "C", 63),
    player("G", "Guard Polyvalent", "OL", "G", 77),
    player("RT2", "Right Tackle Remplaçant", "OL", "T", 71),
    player("RT1", "Right Tackle Blessé", "OL", "T", 70, status="RES", detail="R48"),
    player("WR1", "Receveur Un", "WR", "WR", 12, status="INA"),
    player("WR9", "Receveur Hors Depth", "WR", "WR", 19),
    player("K", "Kicker", "K", "K", 15),
    player("CB", "Cornerback", "DB", "CB", 24, college="Iowa State; Eastern Kentucky"),
    player("PS", "Practice Squad", "WR", "WR", 85, status="DEV", detail="P01"),
    player("EL", "Appelé", "RB", "RB", 31, detail="P01"),
    player("CUT", "Libéré", "TE", "TE", 88, status="CUT", detail="W03"),
    player("RET", "Retraité", "LB", "LB", 50, status="RET", detail="R02"),
])

DEPTH = pl.DataFrame([
    depth("QB3", OFF, 9, "QB", 1),  # blessé, encore en tête chez ESPN
    depth("QB1", OFF, 9, "QB", 2),
    depth("QB2", OFF, 9, "QB", 3),
    depth("LT", OFF, 3, "LT", 1),
    depth("G", OFF, 4, "LG", 1),
    depth("C", OFF, 5, "C", 1),
    depth("G", OFF, 5, "C", 2),  # aussi remplaçant au centre : on garde LG
    depth("RT1", OFF, 7, "RT", 1),
    depth("RT2", OFF, 7, "RT", 2),
    depth("WR1", OFF, 1, "WR", 1),
    depth("CB", DEF, 8, "LCB", 1),
    depth("CB", ST, 5, "KR", 1),  # rôle de retour : ignoré
    depth("K", ST, 1, "PK", 1),
    depth("EL", OFF, 11, "RB", 1),
    depth("XX", OFF, 11, "RB", 2),  # absent du roster : ignoré
])


def build(roster=ROSTER, dc=DEPTH, pages=frozenset({"QB1"})):
    return build_team_roster("HOU", "Houston Texans", 2026, roster, dc, set(pages), None, "AFC", "AFC South")


def names(team, unit, group):
    u = next(u for u in team.units if u.key == unit)
    g = next(g for g in u.groups if g.key == group)
    return [p.player_id for p in g.players]


def test_latest_photo_per_team_not_global():
    df = pl.DataFrame([player("A", "A", "QB", "QB", 1, week=8, team="BYE"),
                       player("A", "A", "QB", "QB", 1, week=7, team="BYE"),
                       player("B", "B", "QB", "QB", 2, week=9, team="HOU"),
                       player("B", "B", "QB", "QB", 2, week=8, team="HOU"),
                       player("C", "C", "QB", "QB", 3, week=9, team="LAR")])
    out = latest_rosters(df)
    assert sorted(zip(out["team"], out["week"])) == [("BYE", 8), ("HOU", 9), ("LA", 9)]
    dc = pl.DataFrame([depth("A", OFF, 1, "QB", 1, dt="2026-11-06T08:00:00Z"),
                       depth("B", OFF, 1, "QB", 1, dt="2026-11-07T13:54:10Z")])
    assert latest_depth_charts(dc)["gsis_id"].to_list() == ["B"]
    assert latest_depth_charts(pl.DataFrame({"club_code": ["HOU"]})).is_empty()  # ancien format


def test_units_and_groups_in_display_order():
    t = build()
    assert [u.key for u in t.units] == ["offense", "defense", "special"]
    assert [g.key for g in t.units[0].groups] == ["QB", "RB", "WR", "OL"]
    assert [g.label for g in t.units[1].groups] == ["Cornerbacks"]
    assert names(t, "special", "K") == ["K"]


def test_injured_player_leaves_his_depth_spot():
    t = build()
    assert names(t, "offense", "QB") == ["QB1", "QB2"]  # QB3 (IR) n'est pas dans l'effectif principal
    qb1 = t.units[0].groups[0].players[0]
    assert qb1.starter and qb1.depth == 1
    # Ligne offensive : titulaires dans l'ordre du depth chart (LT, LG, C, RT), le
    # remplaçant de RT blessé devient titulaire.
    assert names(t, "offense", "OL") == ["LT", "G", "C", "RT2"]
    ol = {p.player_id: p for p in t.units[0].groups[3].players}
    assert ol["G"].position == "LG" and ol["RT2"].starter and ol["RT2"].position == "RT"


def test_players_outside_depth_chart_come_last_by_number():
    t = build()
    assert names(t, "offense", "WR") == ["WR1", "WR9"]
    wr = t.units[0].groups[2].players
    assert wr[0].status_label == "inactif" and wr[1].depth is None and not wr[1].starter
    assert names(t, "defense", "CB") == ["CB"]  # KR ignoré : reste cornerback


def test_without_depth_chart_sorted_by_number():
    t = build(dc=pl.DataFrame())
    assert names(t, "offense", "QB") == ["QB1", "QB2"]
    assert names(t, "offense", "OL") == ["C", "RT2", "LT", "G"]  # 63, 71, 74, 77
    assert not any(p.starter for u in t.units for g in u.groups for p in g.players)
    assert t.depth_chart_at is None


def test_out_section_and_hidden_statuses():
    t = build()
    assert [(g.key, [p.player_id for p in g.players]) for g in t.out] == [
        ("reserve", ["QB3", "RT1"]), ("practice", ["PS"])]
    labels = {p.player_id: p.status_label for g in t.out for p in g.players}
    assert labels == {"QB3": "IR", "RT1": "IR, retour désigné", "PS": None}
    every = {p.player_id for u in t.units for g in u.groups for p in g.players} | set(labels)
    assert "CUT" not in every and "RET" not in every
    el = next(p for p in t.units[0].groups[1].players if p.player_id == "EL")
    assert el.status_label == "appelé"  # joueur d'entraînement appelé pour le match
    assert t.active_count == 11


def test_player_details():
    t = build()
    qb1 = t.units[0].groups[0].players[0]
    assert (qb1.draft_year, qb1.draft_pick) == (2023, 2)
    assert qb1.has_page and not t.units[0].groups[0].players[1].has_page
    assert str(qb1.birth_date) == "2001-10-03"
    cb = t.units[1].groups[0].players[0]
    assert cb.college == "Iowa State" and cb.colleges == ["Iowa State", "Eastern Kentucky"]
    assert cb.draft_pick is None and cb.draft_year is None
    assert t.roster_week == 9 and t.depth_chart_at.isoformat() == "2026-11-07T13:54:10+00:00"


def test_depth_assignments_skips_duplicates_and_return_roles():
    rows = [depth("A", OFF, 1, "WR", 1), depth("A", ST, 4, "PR", 1), depth("B", OFF, 1, "WR", 2),
            depth("B", OFF, 8, "WR", 3)]
    got = depth_assignments([r for r in rows], {"A", "B"})
    assert got["A"]["pos"] == "WR" and got["A"]["starter"]
    assert got["B"]["slot"] == (0, 8) and got["B"]["starter"]  # seul à sa case 8


def test_index_groups_counts_by_team():
    teams = [{"abbr": "HOU", "name": "Houston Texans", "conference": "AFC", "division": "AFC South"},
             {"abbr": "BUF", "name": "Buffalo Bills", "conference": "AFC", "division": "AFC East"}]
    idx = build_index(2026, teams, ROSTER, DEPTH, {})
    assert [t.team for t in idx.teams] == ["BUF", "HOU"]  # AFC East avant AFC South
    hou = idx.teams[1]
    assert (hou.active_count, hou.practice_count, hou.reserve_count) == (11, 1, 2)
    assert idx.teams[0].active_count == 0 and idx.roster_week == 9


# --- Logos des universités -----------------------------------------------


def test_college_logo_attached_when_known(monkeypatch):
    import app.data.rosters as rosters
    monkeypatch.setattr(rosters, "college_logos", lambda: {"Ohio State": {"logo": "logos/college/194.png"}})
    t = build()
    qb1 = t.units[0].groups[0].players[0]
    assert qb1.college_logo == "logos/college/194.png" and qb1.college_logo_dark is None
    cb = t.units[1].groups[0].players[0]  # Iowa State : pas dans la correspondance
    assert cb.college == "Iowa State" and cb.college_logo is None


def test_college_logo_files_exist():
    """Chaque logo cité dans college_logos.json est bien versionné dans app/static."""
    mapping = json.loads(COLLEGE_MAP_PATH.read_text(encoding="utf-8"))
    assert len(mapping) > 200 and mapping == college_logos()
    for name, e in mapping.items():
        for key in ("logo", "logo_dark"):
            if key in e:
                assert e[key].startswith("logos/college/"), name
                f = LOGO_ROOT / e[key]
                assert f.is_file(), (name, e[key])
                # Carré de 48 px (recadré et centré par le script) : en-tête PNG.
                head = f.read_bytes()[:24]
                assert head[1:4] == b"PNG", name
                assert (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")) == (48, 48), name
    # Homonymes : Miami (Floride) et Miami (Ohio) ont deux logos différents.
    assert mapping["Miami"]["logo"] != mapping["Miami (Ohio)"]["logo"]


def test_college_name_matching():
    teams = [{"id": "1", "location": "Miami", "displayName": "Miami Hurricanes"},
             {"id": "2", "location": "Miami (OH)", "displayName": "Miami (OH) RedHawks"},
             {"id": "3", "location": "Texas", "displayName": "Texas Longhorns"},
             {"id": "4", "location": "Texas College", "displayName": "Texas College Steers"},
             {"id": "5", "location": "NC State", "displayName": "NC State Wolfpack"}]
    assert normalize("N.C. State") == normalize("NC State") == "nc state"
    got = match({"Miami": 1, "N.C. State": 1, "Texas": 1, "Miami (Ohio)": 1, "Friends U.": 1}, teams,
                {"Miami (Ohio)": "2", "Friends U.": False})
    # « Texas » désigne deux équipes (« College » est ignoré) : jamais choisi tout seul.
    assert got == {"Miami": "1", "N.C. State": "5", "Miami (Ohio)": "2"}


def test_overrides_file_is_valid():
    data = tomllib.loads(COLLEGE_OVERRIDES_PATH.read_text(encoding="utf-8"))["colleges"]
    assert data["Miami"] == "2390" and data["Miami (Ohio)"] == "193" and data["USC"] == "30"
    assert all(v is False or (isinstance(v, str) and v.isdigit()) for v in data.values())


def _png(rgb, size=8):
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGBA", (size, size), (*rgb, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_dark_variant_choice():
    pytest.importorskip("PIL")
    navy, white, orange = _png((10, 20, 60)), _png((255, 255, 255)), _png((230, 120, 20))
    assert pick_dark(orange, None, None) is None  # lisible sur fond sombre : logo clair partout
    assert pick_dark(navy, white, None) == white  # silhouette blanche plutôt qu'un logo invisible
    assert pick_dark(navy, orange, None) == orange  # variante sombre en couleur
    assert pick_dark(navy, navy, white) == white  # logo ESPN pour fond noir en dernier recours

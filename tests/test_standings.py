import polars as pl

from app.data.standings import compute_standings

TEAMS = pl.DataFrame({
    "team_abbr": ["AAA", "BBB", "CCC", "DDD", "EEE"],
    "team_name": ["Alpha", "Bravo", "Charlie", "Delta", "Echo"],
    "team_conf": ["AFC", "AFC", "AFC", "AFC", "NFC"],
    "team_division": ["AFC East", "AFC East", "AFC East", "AFC North", "NFC West"],
})


def games(*rows):
    return pl.DataFrame(
        [{"game_id": f"G{i}", "game_type": gt, "gameday": f"2026-09-{10 + i:02d}", "gametime": "13:00",
          "away_team": a, "home_team": h, "away_score": as_, "home_score": hs}
         for i, (a, h, as_, hs, gt) in enumerate(rows)],
        schema_overrides={"away_score": pl.Int64, "home_score": pl.Int64},
    )


def division(result, name):
    return next(d for d in result if d.name == name)


def test_records_ties_and_unplayed_games():
    s = games(
        ("BBB", "AAA", 10, 20, "REG"),   # AAA bat BBB (division)
        ("AAA", "DDD", 17, 17, "REG"),   # nul AAA-DDD (conférence, hors division)
        ("CCC", "EEE", 3, 30, "REG"),    # CCC perd hors conférence
        ("AAA", "CCC", None, None, "REG"),  # pas encore joué : ignoré
        ("AAA", "BBB", 0, 50, "PRE"),    # présaison : ignorée
    )
    east = division(compute_standings(s, TEAMS), "AFC East")
    a = east.rows[0]
    assert a.team == "AAA" and (a.wins, a.losses, a.ties) == (1, 0, 1)
    assert a.pct == 0.75  # (1 + 0,5) / 2
    assert a.div_record == "1-0" and a.conf_record == "1-0-1"
    assert a.home_record == "1-0" and a.away_record == "0-0-1"
    assert (a.points_for, a.points_against, a.diff) == (37, 27, 10)
    assert a.streak == "N1"


def test_head_to_head_breaks_tie():
    # BBB et CCC à 1-1. CCC a battu BBB, mais BBB a une meilleure différence de points.
    s = games(
        ("BBB", "CCC", 10, 13, "REG"),
        ("BBB", "EEE", 40, 0, "REG"),
        ("CCC", "EEE", 0, 3, "REG"),
    )
    east = division(compute_standings(s, TEAMS), "AFC East")
    order = [r.team for r in east.rows]
    assert order.index("CCC") < order.index("BBB")


def test_streak_counts_consecutive_results():
    s = games(
        ("AAA", "EEE", 0, 7, "REG"),
        ("AAA", "DDD", 21, 7, "REG"),
        ("AAA", "BBB", 21, 7, "REG"),
    )
    east = division(compute_standings(s, TEAMS), "AFC East")
    assert next(r for r in east.rows if r.team == "AAA").streak == "V2"
    assert next(r for r in east.rows if r.team == "CCC").streak is None


def test_every_team_listed_once():
    result = compute_standings(games(("AAA", "BBB", 1, 0, "REG")), TEAMS)
    teams = [r.team for d in result for r in d.rows]
    assert sorted(teams) == ["AAA", "BBB", "CCC", "DDD", "EEE"]

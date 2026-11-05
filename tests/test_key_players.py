"""Joueurs clés d'un match, équipe par équipe : QB, top offensif, top défensif, kicker."""
import logging

import polars as pl
import pytest

from app.data.key_players import DEFAULTS, canonical_team, load_config, select_match_key_players

AWAY, HOME = "AAA", "BBB"
GAME = "2026_01_AAA_BBB"


def row(pid, team, position, **stats):
    return {"player_id": pid, "player_display_name": pid, "position": position, "team": team,
            "game_id": GAME, **stats}


def frame(rows):
    return pl.DataFrame(rows, infer_schema_length=None)


def select(rows, pressures=None, config=None, away=AWAY, home=HOME):
    return select_match_key_players(frame(rows), away, home, pressures, config or DEFAULTS, game_id=GAME)


def ids(items):
    return [getattr(x, "player", x).player_id for x in items]


def test_each_team_gets_its_own_players():
    k = select([
        row("QB_A", AWAY, "QB", attempts=25), row("QB_B", HOME, "QB", attempts=30),
        row("WR_A", AWAY, "WR", receiving_yards=40), row("WR_B", HOME, "WR", receiving_yards=150),
        row("LB_A", AWAY, "LB", def_tackles_solo=3), row("LB_B", HOME, "LB", def_tackles_solo=9),
        row("K_A", AWAY, "K", fg_att=1, fg_made=1), row("K_B", HOME, "K", pat_att=2, pat_made=2),
    ])
    assert (k.away.team, k.home.team) == (AWAY, HOME)
    assert (ids(k.away.quarterbacks), ids(k.home.quarterbacks)) == (["QB_A"], ["QB_B"])
    assert (ids(k.away.offense), ids(k.home.offense)) == (["WR_A"], ["WR_B"])
    assert (ids(k.away.defense), ids(k.home.defense)) == (["LB_A"], ["LB_B"])
    assert (ids(k.away.kickers), ids(k.home.kickers)) == (["K_A"], ["K_B"])
    # Le classement est propre à chaque équipe : chacune a son n° 1.
    assert k.away.offense[0].rank == k.home.offense[0].rank == 1


def test_quarterbacks_need_a_pass_attempt():
    k = select([
        row("QB1", AWAY, "QB", attempts=25), row("QB2", AWAY, "QB", attempts=2),
        row("KNEEL", AWAY, "QB", attempts=0, carries=1),   # aucune passe : exclu
        row("TRICK", AWAY, "RB", attempts=1, carries=10),  # passe d'un RB : pas un QB
    ])
    assert ids(k.away.quarterbacks) == ["QB1", "QB2"]


def test_offense_score_and_qb_excluded():
    k = select([
        row("QB", AWAY, "QB", attempts=30, carries=8, rushing_yards=90, rushing_tds=2),
        row("RB", AWAY, "RB", carries=20, rushing_yards=100, rushing_tds=1, receptions=2, receiving_yards=10),
        row("WR", AWAY, "WR", targets=10, receptions=8, receiving_yards=150),
        row("TE", AWAY, "TE", targets=5, receptions=4, receiving_yards=40, receiving_tds=2),
    ])
    assert [(r.player.player_id, r.score) for r in k.away.offense] == [("WR", 150.0), ("RB", 130.0), ("TE", 80.0)]


def test_offense_ties_break_on_tds_then_yards_then_receptions_then_name():
    k = select([
        row("B_YARDS", AWAY, "WR", receiving_yards=60, receptions=3),
        row("A_TD", AWAY, "WR", receiving_yards=40, receiving_tds=1, receptions=2),
        row("D_REC", AWAY, "WR", receiving_yards=60, receptions=5),
        row("C_SAME", AWAY, "WR", receiving_yards=60, receptions=3),
    ])
    assert ids(k.away.offense) == ["A_TD", "D_REC", "B_YARDS", "C_SAME"]


def test_top_n_per_team_and_fewer_players_shown_as_is():
    rows = [row(f"WR{i}", AWAY, "WR", receiving_yards=10 * i) for i in range(1, 9)]
    rows += [row("ONLY_WR", HOME, "WR", receiving_yards=5), row("ONLY_LB", HOME, "LB", def_tackles_solo=1)]
    k = select(rows)
    assert ids(k.away.offense) == ["WR8", "WR7", "WR6", "WR5", "WR4"]
    assert ids(k.home.offense) == ["ONLY_WR"] and ids(k.home.defense) == ["ONLY_LB"]
    assert k.away.defense == [] and k.home.quarterbacks == [] and k.home.kickers == []


def test_defense_score_with_pressures():
    rows = [
        row("LB", HOME, "LB", def_tackles_solo=8, def_tackle_assists=4),                          # 12
        row("CB", HOME, "CB", def_interceptions=1, def_pass_defended=2, def_tackles_solo=2),      # 14
        row("DE", HOME, "DE", def_sacks=1.5, def_qb_hits=2, def_tackles_solo=2),                  # 12 + 6
    ]
    press = pl.DataFrame({"player_id": ["DE", "LB"], "pressures": [4.0, 0.0]})
    k = select(rows, press)
    assert k.pressures_available is True
    assert [(r.player.player_id, r.score) for r in k.home.defense] == [("DE", 18.0), ("CB", 14.0), ("LB", 12.0)]


def test_defense_without_pressures_does_not_fail():
    rows = [row("LB", HOME, "LB", def_tackles_solo=8, def_tackle_assists=4),
            row("DE", HOME, "DE", def_sacks=1.5, def_qb_hits=2, def_tackles_solo=2)]
    for missing in (None, pl.DataFrame(schema={"player_id": pl.Utf8, "pressures": pl.Float64})):
        k = select(rows, missing)
        assert k.pressures_available is False
        # Égalité à 12 : départage sur INT + sacks (DE), pas sur les plaquages (LB).
        assert [(r.player.player_id, r.score) for r in k.home.defense] == [("DE", 12.0), ("LB", 12.0)]


def test_kicker_stats():
    k = select([row("K", HOME, "K", fg_made=2, fg_att=3, fg_long=51, pat_made=3, pat_att=3),
                row("P", HOME, "P")])  # punter sans coup de pied tenté : exclu
    kh = k.home.kickers
    assert ids(kh) == ["K"] and (kh[0].fg_made, kh[0].fg_att, kh[0].fg_long, kh[0].pat_made) == (2, 3, 51, 3)


def test_traded_player_counted_for_his_team_in_this_game():
    # Même joueur (TRADED), deux matchs : la colonne team de la ligne de stats fait foi.
    before = select([row("TRADED", AWAY, "WR", receiving_yards=90)])
    after = select([row("TRADED", HOME, "WR", receiving_yards=70)])
    assert ids(before.away.offense) == ["TRADED"] and before.home.offense == []
    assert ids(after.home.offense) == ["TRADED"] and after.away.offense == []


def test_team_aliases_match_schedule_abbreviations():
    assert [canonical_team(t) for t in ("LAR", "JAC", "WSH", "OAK", "SD", "STL", "la", "KC")] == \
        ["LA", "JAX", "WAS", "LV", "LAC", "LA", "LA", "KC"]
    k = select([row("WR_LAR", "LAR", "WR", receiving_yards=80), row("WR_JAC", "JAC", "WR", receiving_yards=60)],
               away="LA", home="JAX")
    assert ids(k.away.offense) == ["WR_LAR"] and k.away.offense[0].player.team == "LA"
    assert ids(k.home.offense) == ["WR_JAC"] and k.home.offense[0].player.team == "JAX"


def test_player_from_another_team_is_logged_and_dropped(caplog):
    with caplog.at_level(logging.ERROR, logger="app.data.key_players"):
        k = select([row("WR", AWAY, "WR", receiving_yards=50), row("INTRUS", "ZZZ", "WR", receiving_yards=500)])
    assert ids(k.away.offense) == ["WR"] and k.home.offense == []
    assert any("INTRUS" in r.getMessage() and "ZZZ" in r.getMessage() for r in caplog.records)


def test_rows_without_player_are_ignored():
    rows = [row("WR", AWAY, "WR", receiving_yards=50), {**row("X", AWAY, "WR", receiving_yards=900), "player_id": None}]
    assert ids(select(rows).away.offense) == ["WR"]


def test_empty_match():
    k = select_match_key_players(pl.DataFrame(), AWAY, HOME)
    for side in (k.away, k.home):
        assert (side.quarterbacks, side.offense, side.defense, side.kickers) == ([], [], [], [])


def test_config_file_overrides_defaults(tmp_path):
    path = tmp_path / "kp.toml"
    path.write_text("[offense]\ntop = 2\ntouchdowns = 6\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg["offense"]["top"] == 2 and cfg["offense"]["touchdowns"] == 6
    assert cfg["offense"]["rushing_yards"] == 1.0 and cfg["defense"] == DEFAULTS["defense"]


@pytest.mark.parametrize("section", ["offense", "defense", "mvp"])
def test_shipped_config_matches_spec(section):
    assert load_config()[section] == DEFAULTS[section]


# --- MVP ----------------------------------------------------------------
from app.data.key_players import MvpScale  # noqa: E402

# Références fictives : 10 valeurs par catégorie (meilleur score par équipe-match).
SCALE = MvpScale({
    "qb": [60, 80, 90, 100, 110, 120, 130, 150, 170, 200],
    "offense": [50, 70, 90, 100, 110, 120, 130, 150, 180, 220],
    "defense": [10, 12, 14, 16, 18, 20, 22, 25, 30, 35],
    "kicker": [3, 5, 6, 7, 8, 9, 10, 12, 15, 20],
})


def mvp_of(rows, away_score, home_score, scale=SCALE, config=None):
    return select_match_key_players(frame(rows), AWAY, HOME, None, config or DEFAULTS, game_id=GAME,
                                    away_score=away_score, home_score=home_score, mvp_scale=scale).mvp


def test_mvp_raw_scores_per_category():
    from app.data.key_players import kicker_mvp_score, qb_mvp_score
    from app.data.models import PlayerLine
    w = DEFAULTS["mvp"]
    qb = PlayerLine(player_id="Q", name="Q", team=AWAY, passing_yards=300, passing_tds=3, interceptions=1,
                    rushing_yards=20, rushing_tds=1)
    assert qb_mvp_score(qb, w) == pytest.approx(0.4 * 300 + 15 * 3 - 20 + 20 + 20)  # 185
    k = PlayerLine(player_id="K", name="K", team=AWAY, fg_made=3, fg_made_50=1, pat_made=2)
    assert kicker_mvp_score(k, w) == 3 * 3 + 2 + 1


def test_percentile_is_mid_rank():
    assert SCALE.percentile("defense", 22) == 65.0   # 6 valeurs dessous, 1 égale -> (6 + 7) / 2 / 10
    assert SCALE.percentile("defense", 99) == 100.0 and SCALE.percentile("defense", 1) == 0.0
    assert MvpScale({}).percentile("qb", 150) is None


def test_mvp_compares_percentiles_not_raw_scores():
    rows = [row("QB", HOME, "QB", attempts=30, passing_yards=220, passing_tds=1),   # brut 103 -> p35
            row("WR", HOME, "WR", receiving_yards=125),                             # brut 125 -> p60
            row("EDGE", HOME, "DE", def_sacks=3, def_qb_hits=3, def_tackles_solo=5)]  # brut 23 -> p70
    m = mvp_of(rows, 10, 24)
    assert (m.player.player_id, m.category, m.score, m.percentile) == ("EDGE", "defense", 23.0, 70.0)


def test_qb_can_be_mvp():
    rows = [row("QB", HOME, "QB", attempts=35, passing_yards=350, passing_tds=3),   # brut 185 -> p90
            row("WR", HOME, "WR", receiving_yards=140)]                             # p70
    m = mvp_of(rows, 10, 24)
    assert (m.player.player_id, m.category, m.percentile) == ("QB", "qb", 90.0)


def test_kicker_malus():
    rows = [row("K", HOME, "K", fg_made=5, fg_att=5, pat_made=0, pat_att=0),       # brut 15 -> p85
            row("WR", HOME, "WR", receiving_yards=140)]                             # p70
    m = mvp_of(rows, 10, 15)
    assert m.category == "offense"                                                  # 85 × 0,66 = 56,1 < 70
    no_malus = {**DEFAULTS, "mvp": {**DEFAULTS["mvp"], "kicker_factor": 1.0}}
    m = mvp_of(rows, 10, 15, config=no_malus)
    assert (m.player.player_id, m.normalized) == ("K", 85.0)


def test_mvp_comes_from_winning_team_only():
    rows = [row("QB_LOSER", AWAY, "QB", attempts=40, passing_yards=450, passing_tds=4),  # p100, mais perdant
            row("RB_WIN", HOME, "RB", carries=20, rushing_yards=110, rushing_tds=1)]    # brut 130
    m = mvp_of(rows, 20, 27)
    assert (m.player.player_id, m.category, m.score) == ("RB_WIN", "offense", 130.0)


def test_mvp_on_tie_considers_both_teams():
    rows = [row("WR_A", AWAY, "WR", receiving_yards=120), row("WR_B", HOME, "WR", receiving_yards=90)]
    assert mvp_of(rows, 20, 20).player.player_id == "WR_A"


def test_no_mvp_without_score_players_or_scale():
    assert mvp_of([row("WR", AWAY, "WR", receiving_yards=120)], None, None) is None
    assert mvp_of([row("WR", AWAY, "WR", receiving_yards=120)], 7, 3, scale=None) is None
    assert mvp_of([], 7, 3) is None


def test_scale_uses_best_score_per_team_and_game_among_involved_players():
    stats = frame([
        row("QB1", AWAY, "QB", attempts=30, passing_yards=250),                       # 100
        row("QB_FEW", AWAY, "QB", attempts=5, passing_yards=80),                      # < 10 passes : exclu
        row("WR1", AWAY, "WR", receptions=5, receiving_yards=90),
        row("WR2", AWAY, "WR", receptions=2, receiving_yards=40),                     # pas le meilleur : exclu
        row("LB1", HOME, "LB", def_tackles_solo=6),
        row("K1", HOME, "K", fg_att=2, fg_made=2, pat_att=1, pat_made=1),             # 7
        {**row("WR3", HOME, "WR", receptions=3, receiving_yards=30), "game_id": "2026_02_BBB_AAA"},
    ])
    pfr = pl.DataFrame({"game_id": [GAME], "team": [HOME], "player_id": ["LB1"], "pressures": [2.0]})
    scale = MvpScale.from_stats([(stats, pfr)], DEFAULTS)
    assert scale.sorted == {"qb": [100.0], "offense": [30.0, 90.0], "defense": [9.0], "kicker": [7.0]}
    assert scale.games == 2

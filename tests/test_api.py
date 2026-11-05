"""Tests de bout en bout de l'API sur une mini-saison fictive (aucun accès réseau).

Les données sont volontairement incomplètes (pas de stats d'équipe, pas de
stats PFR, pas de play-by-play) : l'API doit répondre avec des valeurs
nulles, jamais une erreur.
"""
import polars as pl
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.data.cache import SeasonCache
from app.data.repository import NflRepository


def fake_season(season: int) -> dict[str, pl.DataFrame]:
    schedules = pl.DataFrame({
        "game_id": ["2026_01_AAA_BBB", "2026_02_BBB_AAA"],
        "season": [2026, 2026], "game_type": ["REG", "REG"], "week": [1, 2],
        "gameday": ["2026-09-13", "2026-09-20"], "gametime": ["13:00", "20:20"],
        "away_team": ["AAA", "BBB"], "home_team": ["BBB", "AAA"],
        "away_score": [24, None], "home_score": [17, None],
        "overtime": [0, None], "stadium": ["Stade B", None], "roof": ["dome", None],
        "temp": [None, None], "wind": [None, None], "div_game": [1, 1],
    }, schema_overrides={"away_score": pl.Int64, "home_score": pl.Int64, "overtime": pl.Int64,
                         "temp": pl.Int64, "wind": pl.Int64})
    teams = pl.DataFrame({
        "team_abbr": ["AAA", "BBB"], "team_name": ["Alpha", "Bravo"], "team_nick": ["A", "B"],
        "team_conf": ["AFC", "AFC"], "team_division": ["AFC East", "AFC East"],
        "team_color": ["#112233", "#445566"], "team_color2": ["#ffffff", "#000000"],
    })
    player_stats = pl.DataFrame({
        "player_id": ["P1"], "player_display_name": ["Alpha Passeur"], "position": ["QB"],
        "position_group": ["QB"], "headshot_url": [None], "season": [2026], "week": [1],
        "game_id": ["2026_01_AAA_BBB"], "team": ["AAA"], "completions": [20], "attempts": [30],
        "passing_yards": [250],
    })
    return {"schedules": schedules, "teams": teams, "player_stats": player_stats}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    cache = SeasonCache(2026, data_dir=tmp_path, downloader=fake_season,
                        datasets=("schedules", "teams", "player_stats"))
    monkeypatch.setattr(main, "repo", NflRepository(cache))
    return TestClient(main.app)


def test_meta_and_week(client):
    meta = client.get("/api/meta").json()
    assert meta["season"] == 2026 and meta["current_week"] == 1
    games = client.get("/api/weeks/1").json()
    assert games[0]["status"] == "final" and games[0]["quarters"] == []
    assert games[0]["kickoff_paris"].startswith("2026-09-13T19:00")
    assert client.get("/api/weeks/2").json()[0]["status"] == "scheduled"
    assert client.get("/api/weeks/9").status_code == 404


def test_game_with_missing_data_does_not_fail(client):
    d = client.get("/api/games/2026_01_AAA_BBB").json()
    assert d["away_stats"]["total_yards"] is None
    k = d["key_players"]
    assert (k["away"]["team"], k["home"]["team"]) == ("AAA", "BBB")
    assert [q["name"] for q in k["away"]["quarterbacks"]] == ["Alpha Passeur"]
    assert k["away"]["quarterbacks"][0]["passing_tds"] is None
    assert k["home"] == {"team": "BBB", "quarterbacks": [], "offense": [], "defense": [], "kickers": []}
    # Pas de pfr_def dans cette mini-saison : score défensif sans pressions.
    assert k["pressures_available"] is False and k["weights"]["defense"]["top"] == 3
    assert client.get("/api/games/inconnu").status_code == 404


def test_standings_and_player(client):
    rows = client.get("/api/standings").json()[0]["rows"]
    assert [(r["team"], r["wins"]) for r in rows] == [("AAA", 1), ("BBB", 0)]
    p = client.get("/api/players/P1").json()
    assert p["games_played"] == 1 and p["games"][0]["result"] == "V"
    assert p["games"][0]["home"] is False and p["games"][0]["opponent"] == "BBB"
    assert client.get("/api/players/P9").status_code == 404


def test_front_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "NFL Gameday" in r.text
    assert client.get("/favicon.svg").status_code == 200
    assert 'mode: "api"' in client.get("/config.js").text
    assert client.get("/api/inconnu").status_code == 404


def test_manifest_served_with_manifest_content_type(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")


def test_mvp_reference_adds_previous_season_early(tmp_path):
    """Peu de matchs joués : la saison précédente complète les distributions du MVP."""
    def with_prev(season):
        frames = fake_season(season)
        frames["prev_player_stats"] = pl.DataFrame({
            "player_id": ["OLD"], "player_display_name": ["Ancien"], "position": ["WR"], "team": ["AAA"],
            "game_id": ["2025_10_AAA_BBB"], "receptions": [6], "receiving_yards": [140],
        })
        return frames

    cache = SeasonCache(2026, data_dir=tmp_path, downloader=with_prev,
                        datasets=("schedules", "teams", "player_stats", "prev_player_stats"))
    scale = NflRepository(cache).mvp_scale()
    assert scale.seasons == (2025, 2026)
    # Ligne 2025 (WR, 140 yds) + QB 2026 de la mini-saison (250 yds -> 0,4 × 250 = 100).
    assert scale.sorted["offense"] == [140.0] and scale.sorted["qb"] == [100.0]

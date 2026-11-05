"""Tests de bout en bout de l'API sur une mini-saison fictive (aucun accès réseau).

Les données sont volontairement incomplètes (pas de stats d'équipe, pas de
depth chart, pas de play-by-play) : l'API doit répondre avec des valeurs
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
    qb = d["away_key"]["offense"][0]
    assert qb["source"] == "fallback" and qb["player"]["name"] == "Alpha Passeur"
    assert qb["player"]["passing_tds"] is None
    assert d["home_key"]["tackle_leader"] is None
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

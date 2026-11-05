import json
from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from app.data import derive
from app.data.cache import SeasonCache as _SeasonCache
from app.data.normalize import kickoff_paris, to_game, to_team_stats


def test_quarter_scores_from_cumulative_scores():
    pbp = pl.DataFrame({
        "game_id": ["G"] * 6,
        "qtr": [1.0, 1.0, 2.0, 3.0, 4.0, 5.0],
        "total_away_score": [0, 3, 10, 10, 17, 17],
        "total_home_score": [7, 7, 7, 14, 17, 23],
    })
    q = derive.quarter_scores(pbp).to_dicts()
    assert [(r["qtr"], r["away"], r["home"]) for r in q] == [
        (1, 3, 7), (2, 7, 0), (3, 0, 7), (4, 7, 3), (5, 0, 6)]


def test_first_downs_by_team():
    pbp = pl.DataFrame({
        "game_id": ["G"] * 4,
        "posteam": ["A", "A", "B", None],
        "first_down": [1, 1, 1, None],
        "first_down_pass": [1, 0, 0, None],
        "first_down_rush": [0, 0, 1, None],
        "first_down_penalty": [0, 1, 0, None],
    })
    fd = {r["team"]: r for r in derive.first_downs(pbp).to_dicts()}
    assert fd["A"]["first_downs"] == 2 and fd["A"]["first_downs_penalty"] == 1
    assert fd["B"]["first_downs_rush"] == 1


def test_kickoff_converted_to_paris_time():
    # 20:15 heure de l'Est le 29/10/2026 (EDT, UTC-4) ; Paris est passé en CET (UTC+1)
    k = kickoff_paris("2026-10-29", "20:15")
    assert (k.day, k.hour, k.minute) == (30, 1, 15)
    # 13:00 ET le 13/09 : EDT (UTC-4) et CEST (UTC+2) -> 19:00
    assert kickoff_paris("2026-09-13", "13:00").hour == 19
    assert kickoff_paris(None, "13:00") is None


def test_scheduled_game_has_no_score_nor_quarters():
    g = to_game({"game_id": "X", "season": 2026, "week": 12, "game_type": "REG",
                 "gameday": "2026-11-26", "gametime": "16:30", "away_team": "PHI",
                 "home_team": "DAL", "away_score": None, "home_score": None},
                [{"qtr": 1, "away": 0, "home": 0}])
    assert g.status == "scheduled" and g.quarters == [] and g.temp_f is None


def test_team_stats_missing_values_are_none():
    ts = to_team_stats("KC", None, None)
    assert ts.total_yards is None and ts.turnovers is None and ts.first_downs is None
    ts = to_team_stats("KC", {"passing_yards": 250, "sack_yards_lost": -20, "rushing_yards": 100,
                              "passing_interceptions": 1, "fumbles_lost_total": 2,
                              "passing_first_downs": 12, "rushing_first_downs": 5}, None)
    assert ts.net_passing_yards == 230 and ts.total_yards == 330
    assert ts.turnovers == 3 and ts.first_downs == 17


def _fake_downloader(calls):
    def dl(season):
        calls.append(season)
        return {"schedules": pl.DataFrame({"game_id": ["G"], "week": [1]})}
    return dl


def SeasonCache(season, data_dir, downloader, datasets=("schedules",)):  # noqa: N802
    return _SeasonCache(season, data_dir=data_dir, downloader=downloader, datasets=datasets)


def test_cache_redownloads_when_a_dataset_is_missing(tmp_path):
    calls = []
    SeasonCache(2026, tmp_path, _fake_downloader(calls)).get("schedules")
    SeasonCache(2026, tmp_path, _fake_downloader(calls), datasets=("schedules", "teams")).get("schedules")
    assert len(calls) == 2


def test_cache_downloads_once_then_reuses(tmp_path):
    calls = []
    c = SeasonCache(2026, data_dir=tmp_path, downloader=_fake_downloader(calls))
    assert c.get("schedules").height == 1
    assert c.get("schedules").height == 1
    assert calls == [2026]
    assert (tmp_path / "2026" / "schedules.parquet").exists()
    assert c.get("unknown").is_empty()


def test_cache_refreshes_after_ttl(tmp_path):
    calls = []
    c = SeasonCache(2026, data_dir=tmp_path, downloader=_fake_downloader(calls))
    c.get("schedules")
    meta = json.loads((tmp_path / "2026" / "meta.json").read_text())
    meta["fetched_at"] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    (tmp_path / "2026" / "meta.json").write_text(json.dumps(meta))
    c.get("schedules")
    assert len(calls) == 2


def test_cache_keeps_old_data_when_download_fails(tmp_path):
    calls = []
    SeasonCache(2026, data_dir=tmp_path, downloader=_fake_downloader(calls)).refresh()
    meta_path = tmp_path / "2026" / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["fetched_at"] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    meta_path.write_text(json.dumps(meta))

    def broken(season):
        raise ConnectionError("hors ligne")

    c = SeasonCache(2026, data_dir=tmp_path, downloader=broken)
    assert c.get("schedules").height == 1  # ancien cache servi


def test_cache_without_data_and_offline_raises(tmp_path):
    def broken(season):
        raise ConnectionError("hors ligne")

    with pytest.raises(ConnectionError):
        SeasonCache(2026, data_dir=tmp_path, downloader=broken).get("schedules")

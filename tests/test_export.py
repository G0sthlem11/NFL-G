"""L'export statique doit produire exactement les réponses de l'API."""
import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.data.cache import SeasonCache
from app.data.repository import NflRepository
from app.export import content_hash, export
from tests.test_api import fake_season

DATASETS = ("schedules", "teams", "player_stats", "rosters")


@pytest.fixture()
def exported(tmp_path, monkeypatch):
    repo = NflRepository(SeasonCache(2026, data_dir=tmp_path / "cache", downloader=fake_season,
                                     datasets=DATASETS))
    monkeypatch.setattr(main, "repo", repo)
    res = export(repo, tmp_path / "dist")
    return res, TestClient(main.app)


def endpoint_for(rel: str) -> str:
    """data/weeks/1.json -> /api/weeks/1"""
    return "/api/" + rel.removeprefix("data/").removesuffix(".json")


def test_every_file_matches_its_endpoint(exported):
    res, client = exported
    data_files = sorted(p.relative_to(res.out).as_posix() for p in (res.out / "data").rglob("*.json"))
    assert data_files == [
        "data/games/2026_01_AAA_BBB.json", "data/games/2026_02_BBB_AAA.json",
        "data/meta.json", "data/players/P1.json", "data/rankings.json",
        "data/rosters.json", "data/rosters/AAA.json", "data/rosters/BBB.json",
        "data/standings.json", "data/teams.json",
        "data/weeks/1.json", "data/weeks/2.json",
    ]
    for rel in data_files:
        body = (res.out / rel).read_bytes()
        api = client.get(endpoint_for(rel))
        assert api.status_code == 200, rel
        if rel == "data/meta.json":
            meta = json.loads(body)
            assert meta.pop("generated_at")  # seul ajout par rapport à l'endpoint
            assert meta == api.json()
        else:
            assert body == api.content, rel  # identique octet pour octet


def test_front_copied_in_static_mode(exported):
    res, _ = exported
    assert (res.out / "index.html").exists() and (res.out / "app.js").exists()
    assert 'mode: "static"' in (res.out / "config.js").read_text(encoding="utf-8")
    html = (res.out / "index.html").read_text(encoding="utf-8")
    # Versions = empreinte du contenu de chaque fichier (et non plus ?v=28…).
    versioned = re.findall(r'(?:href|src)="([\w.-][\w./-]*)\?v=([^"]*)"', html)
    assert "app.js" in dict(versioned)
    for path, ver in versioned:
        assert ver == hashlib.sha256((res.out / path).read_bytes()).hexdigest()[:10], path


def test_content_hash_ignores_generation_time(exported, tmp_path):
    res, _ = exported
    meta_path = res.out / "data" / "meta.json"
    h1 = content_hash(res.out / "data")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["generated_at"] = "2030-01-01T00:00:00+00:00"
    meta["fetched_at"] = "2030-01-01T00:00:00Z"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    assert content_hash(res.out / "data") == h1
    (res.out / "data" / "teams.json").write_text("[]", encoding="utf-8")
    assert content_hash(res.out / "data") != h1


def test_refuses_to_wipe_unrelated_folder(tmp_path):
    other = tmp_path / "mes-documents"
    other.mkdir()
    (other / "important.txt").write_text("ne pas effacer")
    repo = NflRepository(SeasonCache(2026, data_dir=tmp_path / "cache", downloader=fake_season,
                                     datasets=DATASETS))
    with pytest.raises(SystemExit):
        export(repo, other)
    assert (other / "important.txt").exists()


ICONS = ("apple-touch-icon.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png")


def test_home_screen_icons_and_manifest_exported(exported):
    res, _ = exported
    for name in ICONS + ("manifest.webmanifest",):
        assert (res.out / name).is_file(), name
    manifest = json.loads((res.out / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == manifest["short_name"] == "Gameday"
    assert manifest["start_url"] == manifest["scope"] == "/" and manifest["display"] == "standalone"
    by_purpose = {(i["sizes"], i["purpose"]) for i in manifest["icons"]}
    assert by_purpose == {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")}
    for icon in manifest["icons"]:  # chaque icône citée existe dans dist/
        assert (res.out / icon["src"].lstrip("/").split("?")[0]).is_file(), icon["src"]
    html = (res.out / "index.html").read_text(encoding="utf-8")
    assert '<link rel="manifest" href="/manifest.webmanifest?v=2" crossorigin="use-credentials">' in html
    assert 'href="/apple-touch-icon.png?v=2"' in html  # version explicite conservée par l'export

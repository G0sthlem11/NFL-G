"""Export statique de NFL Gameday (fichiers JSON + front), pour Vercel.

Usage :
    py -m app.export                       # saison en cours, dans dist/
    py -m app.export --season 2025 --out build
    py -m app.export --refresh             # force le téléchargement nflverse (échoue s'il échoue)
    py -m app.export --status-file s.json  # écrit aussi l'état des matchs (alerte de l'Action)

Principe : l'export interroge l'application FastAPI elle-même, en mémoire et
sans réseau (client ASGI de Starlette). Chaque fichier est donc *exactement*
la réponse de l'endpoint correspondant : aucune logique n'est dupliquée.

    /api/meta                ->  data/meta.json        (+ generated_at)
    /api/teams               ->  data/teams.json
    /api/standings           ->  data/standings.json
    /api/rankings            ->  data/rankings.json
    /api/weeks/{n}           ->  data/weeks/{n}.json
    /api/games/{game_id}     ->  data/games/{game_id}.json
    /api/players/{player_id} ->  data/players/{player_id}.json
    /api/rosters             ->  data/rosters.json
    /api/rosters/{abbr}      ->  data/rosters/{abbr}.json

Le front (app/static/) est copié à la racine de la sortie. ``config.js`` y
passe en mode "static", et les ``?v=`` d'index.html sont remplacés par une
empreinte du contenu, ce qui permet un cache long sur CSS et JS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import warnings

with warnings.catch_warnings():  # avertissement interne à Starlette (httpx), sans effet ici
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from . import main
from .data.cache import SeasonCache
from .data.repository import NflRepository

STATIC = main.STATIC
STATIC_CONFIG = 'window.GAMEDAY_CONFIG = { mode: "static" };\n'
# Champs de meta.json qui changent à chaque exécution sans que les données changent.
VOLATILE_META_FIELDS = ("fetched_at", "generated_at")


@dataclass
class ExportResult:
    out: Path
    files: int
    bytes: int
    content_hash: str
    counts: dict[str, int]


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _compact(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _prepare_out(out: Path) -> None:
    """Vide le dossier de sortie, en refusant d'effacer un dossier étranger."""
    if out.exists() and any(out.iterdir()) and not (out / "data" / "meta.json").exists():
        raise SystemExit(f"{out} n'est pas vide et ne ressemble pas à un export : arrêt par sécurité.")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)


def _version_assets(out: Path) -> None:
    """Remplace ``fichier?v=…`` dans index.html par une empreinte de son contenu.

    Seuls les chemins relatifs (app.js, styles.css…) sont concernés : les URL
    absolues (/manifest.webmanifest?v=2, icônes) gardent leur version explicite.
    """
    index = out / "index.html"
    html = index.read_text(encoding="utf-8")

    def repl(m: re.Match) -> str:
        asset = out / m.group(2)
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()[:10] if asset.exists() else m.group(3)
        return f'{m.group(1)}="{m.group(2)}?v={digest}"'

    html = re.sub(r'(href|src)="([\w.-][\w./-]*)\?v=([^"]*)"', repl, html)
    index.write_text(html, encoding="utf-8")


def content_hash(data_dir: Path) -> str:
    """Empreinte du contenu de data/, hors champs volatils de meta.json."""
    h = hashlib.sha256()
    for path in sorted(p for p in data_dir.rglob("*.json")):
        rel = path.relative_to(data_dir).as_posix()
        body = path.read_bytes()
        if rel == "meta.json":
            meta = json.loads(body)
            for k in VOLATILE_META_FIELDS:
                meta.pop(k, None)
            body = _compact(meta)
        h.update(rel.encode() + b"\0" + body + b"\0")
    return h.hexdigest()


def status(repo: NflRepository) -> dict:
    """État des matchs après l'export, lu par scripts/check_updates.py (alerte
    « stats en retard » de l'Action). Hors de dist/ : rien de public."""
    games = []
    for g in repo.all_games():
        kickoff = g.kickoff_paris.astimezone(timezone.utc).isoformat() if g.kickoff_paris else None
        games.append({"game_id": g.game_id, "label": f"{g.away_team} @ {g.home_team}, {g.week_label}",
                      "kickoff_utc": kickoff, "final": g.status == "final", "stats_pending": g.stats_pending})
    fetched = repo.cache.fetched_at()
    return {"season": repo.season, "exported_at": datetime.now(timezone.utc).isoformat(),
            "fetched_at": fetched.isoformat() if fetched else None, "games": games}


def export(repo: NflRepository, out: Path) -> ExportResult:
    previous_repo = main.repo
    main.repo = repo  # les endpoints lisent ce dépôt
    logging.getLogger("httpx").setLevel(logging.WARNING)  # pas une ligne par requête interne
    # Client ouvert une seule fois (bloc with) : sinon Starlette démarre une
    # boucle d'événements par requête, ce qui multiplie la durée par ~5.
    with TestClient(main.app) as client:
        return _export_with(client, repo, out, previous_repo)


def _export_with(client: TestClient, repo: NflRepository, out: Path, previous_repo) -> ExportResult:
    try:
        def get(path: str) -> bytes:
            r = client.get(path)
            if r.status_code != 200:
                raise RuntimeError(f"{path} : HTTP {r.status_code} {r.text[:200]}")
            return r.content

        _prepare_out(out)
        data = out / "data"

        meta = json.loads(get("/api/meta"))
        meta["generated_at"] = datetime.now(timezone.utc).isoformat()
        _write(data / "meta.json", _compact(meta))
        _write(data / "teams.json", get("/api/teams"))
        _write(data / "standings.json", get("/api/standings"))
        _write(data / "rankings.json", get("/api/rankings"))
        _write(data / "rosters.json", get("/api/rosters"))
        team_abbrs = [t["abbr"] for t in json.loads(get("/api/teams"))]
        for abbr in team_abbrs:
            _write(data / "rosters" / f"{abbr}.json", get(f"/api/rosters/{abbr}"))

        weeks = [w["week"] for w in meta["weeks"]]
        for n in weeks:
            _write(data / "weeks" / f"{n}.json", get(f"/api/weeks/{n}"))

        game_ids = repo._schedules()["game_id"].to_list()
        for gid in game_ids:
            _write(data / "games" / f"{gid}.json", get(f"/api/games/{gid}"))

        ps = repo.cache.get("player_stats")
        player_ids = sorted(ps["player_id"].drop_nulls().unique().to_list()) if not ps.is_empty() else []
        for pid in player_ids:
            _write(data / "players" / f"{pid}.json", get(f"/api/players/{pid}"))
    finally:
        main.repo = previous_repo

    # Front : copie de app/static/ à la racine, puis bascule en mode statique.
    shutil.copytree(STATIC, out, dirs_exist_ok=True)
    (out / "config.js").write_text(STATIC_CONFIG, encoding="utf-8")
    _version_assets(out)

    files = [p for p in out.rglob("*") if p.is_file()]
    return ExportResult(
        out=out, files=len(files), bytes=sum(p.stat().st_size for p in files),
        content_hash=content_hash(data),
        counts={"weeks": len(weeks), "games": len(game_ids), "players": len(player_ids),
                "rosters": len(team_abbrs)},
    )


def main_cli(argv: list[str] | None = None) -> int:
    import nflreadpy as nfl

    p = argparse.ArgumentParser(description="Génère la version statique de NFL Gameday.")
    p.add_argument("--season", type=int, default=nfl.get_current_season())
    p.add_argument("--out", type=Path, default=Path("dist"))
    p.add_argument("--refresh", action="store_true",
                   help="force le téléchargement nflverse ; échoue (sans rien écrire) s'il échoue")
    p.add_argument("--hash-file", type=Path,
                   help="écrit l'empreinte du contenu de data/ dans ce fichier")
    p.add_argument("--status-file", type=Path,
                   help="écrit l'état des matchs (terminés, stats en attente) dans ce fichier JSON")
    args = p.parse_args(argv)

    t = time.time()
    cache = SeasonCache(args.season)
    if args.refresh:
        print(f"Téléchargement nflverse, saison {args.season}…")
        cache.refresh()  # lève une exception en cas d'échec : rien n'est exporté
    repo = NflRepository(cache)
    res = export(repo, args.out)
    if args.hash_file:
        args.hash_file.write_text(res.content_hash + "\n", encoding="utf-8")
    if args.status_file:
        state = status(repo)
        args.status_file.parent.mkdir(parents=True, exist_ok=True)
        args.status_file.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        pending = [g["game_id"] for g in state["games"] if g["stats_pending"]]
        if pending:
            print(f"  stats en attente de publication : {', '.join(pending)}")

    mb = res.bytes / 1_000_000
    print(f"Export saison {args.season} -> {res.out}/ en {time.time() - t:.1f} s")
    print(f"  {res.counts['weeks']} semaines, {res.counts['games']} matchs, {res.counts['players']} joueurs, "
          f"{res.counts['rosters']} effectifs")
    print(f"  {res.files} fichiers, {mb:.1f} Mo")
    print(f"  empreinte des données : {res.content_hash[:16]}")
    if mb > 30:
        print(f"  ATTENTION : {mb:.0f} Mo, c'est plus que prévu (quelques dizaines de Mo au maximum).")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())

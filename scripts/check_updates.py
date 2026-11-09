"""Vérification légère avant un déploiement (GitHub Action, job « check »).

Bibliothèque standard uniquement : le job tourne sur le Python du runner, sans
installer les dépendances de l'app. Trois commandes :

    python scripts/check_updates.py snapshot --out sources.json
        Relève l'état des sources nflverse utilisées pour les matchs :
        - date de mise à jour (API GitHub des releases nflverse-data) des
          fichiers de stats de la saison (WATCHED_ASSETS) ;
        - empreinte des scores du calendrier (games.csv), qui est republié
          toutes les heures même sans nouveau score : on compare donc son
          contenu utile, pas sa date.
        Les rosters et depth charts ne sont pas surveillés : ils changent
        plusieurs fois par jour et sont rafraîchis par chaque export complet,
        et au moins une fois par jour (MAX_AGE).

    python scripts/check_updates.py decide --state .deploy-state
        Compare un relevé frais à celui du dernier export réussi
        (.deploy-state/sources.json, gardé dans le cache de l'Action). Écrit
        ``changed=true|false`` et ``reason=…`` dans $GITHUB_OUTPUT.

    python scripts/check_updates.py alert --state .deploy-state
        Lit .deploy-state/status.json (écrit par ``app.export --status-file``)
        et échoue avec un message clair si un match terminé depuis plus de 24 h
        n'a toujours pas de stats sur le site, ou si un match commencé depuis
        plus de 28 h n'a toujours pas de score. GitHub envoie alors un e-mail.

GITHUB_TOKEN (fourni par l'Action) évite la limite de 60 appels par heure de
l'API GitHub sans authentification.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/{tag}"
GAMES_CSV = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
# Fichiers de match surveillés : (release, nom du fichier, avec {season}).
WATCHED_ASSETS = [
    ("stats_player", "stats_player_week_{season}.parquet"),
    ("stats_team", "stats_team_week_{season}.parquet"),
    ("pbp", "play_by_play_{season}.parquet"),
    ("pfr_advstats", "advstats_week_def_{season}.parquet"),
    ("snap_counts", "snap_counts_{season}.parquet"),
]
# Export complet au moins une fois par jour de vérification (effectifs, depth charts).
MAX_AGE = timedelta(hours=24)
# Alerte : un match dure environ 3 h 30 ; « terminé depuis plus de 24 h » =
# coup d'envoi il y a plus de GAME_LENGTH + STATS_DELAY.
GAME_LENGTH = timedelta(hours=4)
STATS_DELAY = timedelta(hours=24)
HEADERS = {"User-Agent": "nfl-gameday-check/1.0", "Accept": "application/vnd.github+json"}


# --- Saison ---------------------------------------------------------------
def current_season(today: date) -> int:
    """Même règle que nflreadpy.get_current_season() : la saison N commence le
    jeudi qui suit le Labor Day (premier lundi de septembre)."""
    sept1 = date(today.year, 9, 1)
    labor_day = sept1 + timedelta(days=(0 - sept1.weekday()) % 7)
    kickoff = labor_day + timedelta(days=3)
    return today.year if today >= kickoff else today.year - 1


# --- Relevé des sources -----------------------------------------------------
def _get(url: str) -> bytes:
    headers = dict(HEADERS)
    if os.environ.get("GITHUB_TOKEN") and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as res:
        return res.read()


def schedule_signature(csv_text: str, season: int) -> tuple[str, int]:
    """Empreinte des matchs terminés de la saison (identifiant et score) et leur nombre."""
    finals = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("season") != str(season):
            continue
        if row.get("away_score") not in ("", "NA", None) and row.get("home_score") not in ("", "NA", None):
            finals.append(f"{row['game_id']}:{row['away_score']}-{row['home_score']}")
    finals.sort()
    return hashlib.sha256("\n".join(finals).encode()).hexdigest()[:16], len(finals)


def snapshot(season: int) -> dict:
    assets = {}
    for tag, pattern in WATCHED_ASSETS:
        name = pattern.format(season=season)
        release = json.loads(_get(API.format(tag=tag)))
        assets[f"{tag}/{name}"] = next((a["updated_at"] for a in release.get("assets", []) if a["name"] == name), None)
    sig, finals = schedule_signature(_get(GAMES_CSV).decode("utf-8"), season)
    return {"season": season, "assets": assets, "schedule": sig, "finals": finals}


# --- Décision -----------------------------------------------------------------
def decide(previous: dict | None, current: dict, last_export: datetime | None, now: datetime) -> tuple[bool, str]:
    """(changed, raison) : faut-il lancer l'export complet ?"""
    if not previous:
        return True, "aucun export précédent en cache"
    if previous.get("season") != current["season"]:
        return True, f"nouvelle saison {current['season']}"
    if previous.get("schedule") != current["schedule"]:
        return True, f"nouveaux scores au calendrier ({previous.get('finals', '?')} -> {current['finals']} matchs terminés)"
    changed = [k for k, v in current["assets"].items() if v and v != previous.get("assets", {}).get(k)]
    if changed:
        return True, "fichiers mis à jour : " + ", ".join(changed)
    if last_export is None or now - last_export >= MAX_AGE:
        return True, "rafraîchissement quotidien (effectifs, depth charts)"
    return False, "aucune nouvelle donnée nflverse depuis le dernier export"


# --- Alerte -----------------------------------------------------------------
def alerts(status: dict, now: datetime) -> list[str]:
    """Matchs en retard d'après l'état du dernier export (status.json)."""
    late = []
    for g in status.get("games", []):
        if not g.get("kickoff_utc"):
            continue
        kickoff = datetime.fromisoformat(g["kickoff_utc"])
        label = f"{g['game_id']} ({g.get('label', '')}, coup d'envoi {kickoff:%d/%m %H:%M} UTC)"
        if g.get("final") and g.get("stats_pending") and now - kickoff > GAME_LENGTH + STATS_DELAY:
            late.append(f"{label} : terminé depuis plus de 24 h, toujours sans stats sur le site")
        elif not g.get("final") and now - kickoff > GAME_LENGTH + STATS_DELAY:
            late.append(f"{label} : commencé il y a plus de 28 h, toujours sans score sur le site")
    return late


# --- Ligne de commande ------------------------------------------------------
def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _output(**values: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in values.items())
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(lines)
    print(lines, end="")


def _summary(text: str) -> None:
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Vérification légère des sources nflverse.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--season", type=int)
    d = sub.add_parser("decide")
    d.add_argument("--state", type=Path, required=True)
    d.add_argument("--season", type=int)
    a = sub.add_parser("alert")
    a.add_argument("--state", type=Path, required=True)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)

    if args.cmd == "snapshot":
        snap = snapshot(args.season or current_season(now.date()))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snap, indent=1), encoding="utf-8")
        print(json.dumps(snap, indent=1))
        return 0

    if args.cmd == "decide":
        current = snapshot(args.season or current_season(now.date()))
        previous = _read_json(args.state / "sources.json")
        status = _read_json(args.state / "status.json") or {}
        last = datetime.fromisoformat(status["exported_at"]) if status.get("exported_at") else None
        changed, reason = decide(previous, current, last, now)
        _output(changed=str(changed).lower(), reason=reason)
        _summary(f"Vérification nflverse : {'export complet' if changed else 'rien à faire'} ({reason}).")
        return 0

    status = _read_json(args.state / "status.json")
    if status is None:
        print("Pas d'état d'export en cache : alerte non évaluée.")
        return 0
    late = alerts(status, now)
    if not late:
        print("Aucun match en retard de publication.")
        return 0
    msg = ("Données en retard sur le site. nflverse n'a peut-être pas encore publié, "
           "ou l'export a échoué. Lancer le workflow à la main, ou vérifier "
           "https://github.com/nflverse/nflverse-data/releases :\n" + "\n".join(f"- {x}" for x in late))
    print(msg)
    _summary(msg)
    for x in late:
        print(f"::error title=Stats en retard::{x}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

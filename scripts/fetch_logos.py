"""Télécharge les logos des équipes (ESPN, via nflverse) dans app/static/logos/.

Usage : py -m scripts.fetch_logos

Les fichiers sont versionnés dans le dépôt : le site ne contacte jamais ESPN.
À relancer seulement si une équipe change de logo. Les logos sont demandés
en 128 px (64 px affichés, x2 pour les écrans haute densité) au service de
redimensionnement d'ESPN, avec repli sur l'image d'origine en 500 px.

Deux variantes par équipe : logos/<ABBR>.png pour le thème clair, et
logos/dark/<ABBR>.png (variante ESPN « 500-dark », prévue pour les fonds
sombres) pour le thème sombre.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import nflreadpy as nfl

from app.data.team_assets import LOGO_DIR

SIZE = 128
HEADERS = {"User-Agent": "nfl-gameday-logos/1.0"}


# Sous-dossier de app/static/logos/ -> répertoire ESPN de la variante.
VARIANTS = {"": "500", "dark": "500-dark"}


def candidates(url: str, variant: str) -> list[str]:
    # nflverse donne parfois déjà la variante sombre (CAR) : on la normalise.
    path = urllib.parse.urlparse(url).path.replace("/500-dark/", "/500/")  # /i/teamlogos/nfl/500/kc.png
    path = path.replace("/500/", f"/{variant}/")
    return [f"https://a.espncdn.com/combiner/i?img={path}&w={SIZE}&h={SIZE}", f"https://a.espncdn.com{path}"]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as res:
        data = res.read()
    if not data.startswith(b"\x89PNG"):
        raise ValueError("réponse qui n'est pas un PNG")
    return data


def main() -> int:
    teams = nfl.load_teams().select(["team_abbr", "team_logo_espn"]).to_dicts()
    failed = []
    jobs = [(t["team_abbr"], t["team_logo_espn"], sub, variant)
            for t in teams for sub, variant in VARIANTS.items()]
    for abbr, url, sub, variant in jobs:
        out_dir = LOGO_DIR / sub if sub else LOGO_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        label = f"{abbr}{' (' + sub + ')' if sub else ''}"
        if not url:
            failed.append(label)
            continue
        for attempt, src in enumerate(candidates(url, variant) * 2):
            try:
                data = fetch(src)
                break
            except (urllib.error.URLError, ValueError, TimeoutError) as err:
                last = err
                time.sleep(0.5 * (attempt + 1))
        else:
            print(f"  {label:11} échec : {last}")
            failed.append(label)
            continue
        (out_dir / f"{abbr}.png").write_bytes(data)
        print(f"  {label:11} {len(data) / 1024:5.1f} Ko")
    print(f"{len(jobs) - len(failed)} logos sur {len(jobs)} dans {LOGO_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

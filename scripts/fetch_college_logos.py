"""Logos des universités (ESPN) pour l'onglet Effectifs.

Usage :
    py -m scripts.fetch_college_logos             # correspondance + téléchargement
    py -m scripts.fetch_college_logos --dry-run   # correspondance et rapport seulement

Étapes :

1. Universités des effectifs : la plus récente de chaque joueur (première de
   la colonne ``college`` de nflverse), dans le cache de la saison en cours
   (``data/<saison>/rosters.parquet`` ; lancer l'app ou ``py -m app.refresh``
   avant si besoin).
2. Équipes universitaires d'ESPN (API publique, sans clé) : identifiant, noms
   et logos.
3. Correspondance nom nflverse -> équipe ESPN :
   - d'abord ``app/data/college_logos.toml`` (cas ambigus, saisis à la main) ;
   - sinon le nom normalisé (minuscules, sans accents ni ponctuation, sans
     « University ») comparé aux noms ESPN (lieu, nom court, nom complet). Un
     nom qui désigne plusieurs équipes ESPN n'est jamais choisi tout seul.
4. Téléchargement en 128 px (service de redimensionnement d'ESPN, comme
   ``scripts.fetch_logos``), puis même traitement que les petits logos NFL
   (``scripts.resize_logos.fit_square``) : recadrage sur la partie visible
   (les marges transparentes d'ESPN varient beaucoup d'une université à
   l'autre), poids visuel équilibré, centrage dans un carré de 48 px. Fichier
   écrit dans ``app/static/logos/college/<id>.png``.
   Thème sombre (``logos/college/dark/<id>.png``) : on mesure la part du logo
   qui contraste avec le fond sombre, et on garde la version la plus lisible
   parmi la variante ESPN « 500-dark » (préférée si elle a ses couleurs), le
   logo clair, et le logo ESPN « pour fond noir » en dernier recours. Sans
   fichier sombre, le logo clair sert dans les deux thèmes. Exige Pillow
   (``py -m pip install pillow``) ; palette réduite à 256 couleurs.
5. Écriture de ``app/data/college_logos.json`` (nom nflverse -> fichiers), lu
   par l'app, et rapport : couverture en joueurs, universités sans logo.

Les fichiers sont versionnés : le site ne contacte jamais ESPN. À relancer
quand de nouvelles universités apparaissent dans les effectifs.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import tomllib
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import polars as pl

from app.data.cache import DATA_DIR
from app.data.rosters import COLLEGE_MAP_PATH, COLLEGE_OVERRIDES_PATH, HIDDEN_STATUSES, first_college
from app.data.team_assets import LOGO_DIR, PAPER_DARK

TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000"
OUT_DIR = LOGO_DIR / "college"
SIZE = 128  # téléchargé, puis réduit à SMALL_LOGO_PX (48 px)
HEADERS = {"User-Agent": "nfl-gameday-logos/1.0"}
# Mots ignorés pour comparer les noms.
STOP = {"university", "univ", "college", "of", "the", "u"}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace(".", "").replace("'", "")  # N.C. -> nc, Hawai'i -> hawaii
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in STOP)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.read()


def espn_teams() -> list[dict]:
    d = json.loads(fetch(TEAMS_URL))
    return [t["team"] for t in d["sports"][0]["leagues"][0]["teams"]]


def name_index(teams: list[dict]) -> dict[str, set[str]]:
    """Nom normalisé -> identifiants ESPN (plusieurs = ambigu)."""
    idx: dict[str, set[str]] = defaultdict(set)
    for t in teams:
        for key in ("location", "shortDisplayName", "displayName", "nickname"):
            if t.get(key):
                idx[normalize(t[key])].add(t["id"])
    return idx


def roster_colleges(season: int | None) -> Counter:
    """Université la plus récente -> nombre de joueurs (hors libérés et retraités)."""
    dirs = sorted((p for p in DATA_DIR.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: p.name)
    path = (DATA_DIR / str(season) if season else dirs[-1]) / "rosters.parquet"
    df = pl.read_parquet(path).filter(~pl.col("status").is_in(list(HIDDEN_STATUSES)))
    df = df.unique(["team", "gsis_id"])
    return Counter(c for c in (first_college(v) for v in df["college"].to_list()) if c)


def match(colleges: Counter, teams: list[dict], overrides: dict[str, str | bool]) -> dict[str, str]:
    by_id = {t["id"]: t for t in teams}
    idx = name_index(teams)
    out: dict[str, str] = {}
    for name in colleges:
        if name in overrides:
            target = overrides[name]
            if target is False:  # pas de logo, volontairement
                continue
            if str(target) not in by_id:
                print(f"  ATTENTION : {name!r} -> {target!r} inconnu chez ESPN")
                continue
            out[name] = str(target)
            continue
        ids = idx.get(normalize(name), set())
        if len(ids) == 1:
            out[name] = next(iter(ids))
    return out


def _pixels(png: bytes) -> list[tuple[int, int, int, int]]:
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    data = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
    return [p for p in data if p[3] > 128]


def colorful(png: bytes) -> bool:
    """Le logo a-t-il de la couleur (et pas seulement du blanc ou du gris) ?"""
    px = _pixels(png)
    sat = sum(1 for r, g, b, _ in px if max(r, g, b) - min(r, g, b) > 40)
    return bool(px) and sat / len(px) > 0.03


def _lum(r: int, g: int, b: int) -> float:
    def ch(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def visibility(png: bytes, paper: str = PAPER_DARK) -> float:
    """Part des pixels visibles du logo qui contrastent (WCAG >= 2:1) avec le fond."""
    bg = _lum(*(int(paper[i:i + 2], 16) for i in (1, 3, 5)))
    px = _pixels(png)
    if not px:
        return 0.0
    ok = sum(1 for r, g, b, _ in px if (max(_lum(r, g, b), bg) + 0.05) / (min(_lum(r, g, b), bg) + 0.05) >= 2)
    return ok / len(px)


# Seuil de lisibilité sur fond sombre (part du logo qui contraste).
MIN_VISIBLE = 0.4


def pick_dark(light: bytes, dark: bytes | None, on_black: bytes | None) -> bytes | None:
    """Fichier pour le thème sombre, ou None : le logo clair suffit."""
    if dark and dark != light and colorful(dark) and visibility(dark) >= MIN_VISIBLE:
        return dark
    if visibility(light) >= MIN_VISIBLE:
        return None
    options = [(visibility(x), i, x) for i, x in enumerate((dark, on_black)) if x and x != light]
    best = max(options, default=None)
    return best[2] if best and best[0] > visibility(light) else None


def write_small(png: bytes, dst: Path) -> None:
    """Recadré, équilibré et centré en 48 px, comme les petits logos NFL."""
    from PIL import Image

    from scripts.resize_logos import fit_square, save_small
    save_small(fit_square(Image.open(io.BytesIO(png))), dst)


def download(espn_id: str, variant: str) -> bytes | None:
    return download_path(f"/i/teamlogos/ncaa/{variant}/{espn_id}.png")


def on_black_path(team: dict) -> str | None:
    """Logo ESPN prévu pour fond noir (guid), chemin relatif au CDN."""
    for logo in team.get("logos", []):
        if "primary_logo_on_black_color" in logo.get("rel", []):
            return logo["href"].replace("https://a.espncdn.com", "")
    return None


def download_path(path: str) -> bytes | None:
    for attempt in range(3):
        try:
            data = fetch(f"https://a.espncdn.com/combiner/i?img={path}&w={SIZE}&h={SIZE}")
            return data if data.startswith(b"\x89PNG") else None
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            time.sleep(0.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5 * (attempt + 1))
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int)
    ap.add_argument("--dry-run", action="store_true", help="correspondance et rapport, sans téléchargement")
    args = ap.parse_args(argv)

    colleges = roster_colleges(args.season)
    teams = espn_teams()
    overrides = tomllib.loads(COLLEGE_OVERRIDES_PATH.read_text(encoding="utf-8")).get("colleges", {})
    matched = match(colleges, teams, overrides)
    print(f"{len(colleges)} universités, {len(teams)} équipes ESPN, {len(matched)} correspondances")

    files: dict[str, dict] = {}
    if args.dry_run:
        files = {n: {"id": i} for n, i in matched.items()}
    else:
        (OUT_DIR / "dark").mkdir(parents=True, exist_ok=True)
        by_id = {t["id"]: t for t in teams}
        for espn_id in sorted(set(matched.values()), key=int):
            light = download(espn_id, "500")
            if light is None:
                continue
            write_small(light, OUT_DIR / f"{espn_id}.png")
            entry = {"id": espn_id, "logo": f"logos/college/{espn_id}.png"}
            dark = download(espn_id, "500-dark")
            on_black = None
            if visibility(light) < MIN_VISIBLE and not (dark and colorful(dark) and visibility(dark) >= MIN_VISIBLE):
                path = on_black_path(by_id[espn_id])
                on_black = download_path(path) if path else None
            chosen = pick_dark(light, dark, on_black)
            dark_file = OUT_DIR / "dark" / f"{espn_id}.png"
            if chosen:
                write_small(chosen, dark_file)
                entry["logo_dark"] = f"logos/college/dark/{espn_id}.png"
            elif dark_file.exists():
                dark_file.unlink()
            files[espn_id] = entry
        mapping = {name: {k: v for k, v in files[i].items() if k != "id"}
                   for name, i in sorted(matched.items()) if i in files}
        COLLEGE_MAP_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        files = {n: files[i] for n, i in matched.items() if i in files}

    total = sum(colleges.values())
    covered = sum(n for c, n in colleges.items() if c in files)
    missing = sorted(((n, c) for c, n in colleges.items() if c not in files), key=lambda x: (-x[0], x[1]))
    note = " (correspondances, avant téléchargement)" if args.dry_run else ""
    print(f"Couverture{note} : {covered} joueurs sur {total} ({100 * covered / total:.1f} %), "
          f"{len(colleges) - len(missing)} universités sur {len(colleges)}")
    print(f"Sans logo ({len(missing)}) :")
    for n, c in missing:
        print(f"  {n:3}  {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

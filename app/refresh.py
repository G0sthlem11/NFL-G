"""Force le retéléchargement des données nflverse.

Usage : ``py -m app.refresh`` (saison en cours) ou ``py -m app.refresh --season 2025``
"""
import argparse
import time

import nflreadpy as nfl

from .data.cache import SeasonCache


def main() -> None:
    p = argparse.ArgumentParser(description="Actualise le cache local nflverse.")
    p.add_argument("--season", type=int, default=nfl.get_current_season())
    args = p.parse_args()
    t = time.time()
    print(f"Téléchargement de la saison {args.season}…")
    meta = SeasonCache(args.season).refresh()
    print(f"OK en {time.time() - t:.1f} s — {meta['fetched_at']}")
    for name, rows in meta["rows"].items():
        print(f"  {name:15} {rows:>7} lignes")


if __name__ == "__main__":
    main()

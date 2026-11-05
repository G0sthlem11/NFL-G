"""Cache local des jeux de données nflverse.

Chaque saison est stockée dans ``data/<saison>/`` sous forme de fichiers
Parquet, plus un ``meta.json`` qui contient la date du dernier
téléchargement. Les données ne sont retéléchargées que si le cache a plus de
6 h, ou sur demande (bouton « Actualiser », ``py -m app.refresh``).

Si le téléchargement échoue (réseau coupé, GitHub indisponible…), on continue
avec l'ancien cache s'il existe et on ne réessaie pas avant 10 minutes.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import nflreadpy as nfl
import polars as pl

from . import derive

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TTL = timedelta(hours=6)
RETRY_AFTER_FAILURE = timedelta(minutes=10)


DATASETS = ("schedules", "teams", "player_stats", "team_stats", "depth_charts",
            "quarter_scores", "first_downs")

TEAM_COLUMNS = ["team_abbr", "team_name", "team_nick", "team_conf", "team_division",
                "team_color", "team_color2"]


def _download(season: int) -> dict[str, pl.DataFrame]:
    """Télécharge tous les jeux de données d'une saison via nflreadpy."""
    pbp = nfl.load_pbp([season])
    schedules = nfl.load_schedules([season])
    # load_teams contient aussi d'anciennes franchises (OAK, SD, STL…) :
    # on ne garde que les équipes présentes au calendrier de la saison.
    current = set(schedules["home_team"].to_list()) | set(schedules["away_team"].to_list())
    teams = nfl.load_teams().select(TEAM_COLUMNS).filter(pl.col("team_abbr").is_in(current))
    return {
        "schedules": schedules,
        "teams": teams,
        "player_stats": nfl.load_player_stats([season]),
        "team_stats": nfl.load_team_stats([season]),
        "depth_charts": nfl.load_depth_charts([season]),
        "quarter_scores": derive.quarter_scores(pbp),
        "first_downs": derive.first_downs(pbp),
    }


class SeasonCache:
    def __init__(
        self,
        season: int,
        data_dir: Path = DATA_DIR,
        downloader: Callable[[int], dict[str, pl.DataFrame]] = _download,
        datasets: tuple[str, ...] = DATASETS,
    ) -> None:
        self.season = season
        self.dir = data_dir / str(season)
        self._downloader = downloader
        self._datasets = datasets
        self._lock = threading.RLock()
        self._frames: dict[str, pl.DataFrame] = {}
        self._frames_version: str | None = None
        self._last_failure: datetime | None = None

    # --- Métadonnées -----------------------------------------------------
    @property
    def _meta_path(self) -> Path:
        return self.dir / "meta.json"

    def meta(self) -> dict | None:
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def fetched_at(self) -> datetime | None:
        m = self.meta()
        return datetime.fromisoformat(m["fetched_at"]) if m else None

    def is_stale(self) -> bool:
        """Trop vieux (> 6 h), ou un jeu de données attendu manque (cache
        créé par une version antérieure de l'app)."""
        m = self.meta()
        if m is None:
            return True
        if any(name not in m.get("rows", {}) for name in self._datasets):
            return True
        return datetime.now(timezone.utc) - datetime.fromisoformat(m["fetched_at"]) > TTL

    # --- Rafraîchissement ------------------------------------------------
    def refresh(self) -> dict:
        """Retélécharge tout, écrit les Parquet de façon atomique, renvoie meta."""
        with self._lock:
            frames = self._downloader(self.season)
            self.dir.mkdir(parents=True, exist_ok=True)
            for name, df in frames.items():
                tmp = self.dir / f"{name}.parquet.tmp"
                df.write_parquet(tmp)
                os.replace(tmp, self.dir / f"{name}.parquet")
            meta = {
                "season": self.season,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "rows": {k: v.height for k, v in frames.items()},
            }
            tmp = self._meta_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            os.replace(tmp, self._meta_path)
            self._frames.clear()
            self._frames_version = None
            self._last_failure = None
            log.info("Cache %s rafraîchi : %s", self.season, meta["rows"])
            return meta

    def ensure_fresh(self) -> None:
        if not self.is_stale():
            return
        with self._lock:  # une seule requête télécharge, les autres attendent
            if not self.is_stale():
                return
            now = datetime.now(timezone.utc)
            if self._last_failure and now - self._last_failure < RETRY_AFTER_FAILURE:
                return
            try:
                self.refresh()
            except Exception:
                self._last_failure = now
                if self.meta() is None:
                    raise  # pas de cache du tout : impossible de continuer
                log.warning("Échec du rafraîchissement, utilisation de l'ancien cache", exc_info=True)

    # --- Lecture ---------------------------------------------------------
    def get(self, name: str) -> pl.DataFrame:
        """Renvoie un jeu de données (rafraîchi au besoin, gardé en mémoire)."""
        self.ensure_fresh()
        version = (self.meta() or {}).get("fetched_at")
        if version != self._frames_version:
            self._frames.clear()
            self._frames_version = version
        if name not in self._frames:
            path = self.dir / f"{name}.parquet"
            self._frames[name] = pl.read_parquet(path) if path.exists() else pl.DataFrame()
        return self._frames[name]

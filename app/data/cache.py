"""Cache local des jeux de données nflverse.

Chaque saison est stockée dans ``data/<saison>/`` sous forme de fichiers
Parquet, plus un ``meta.json`` qui contient la date du dernier
téléchargement. Les données ne sont retéléchargées que si le cache a plus de
6 h, ou sur demande (bouton « Actualiser », ``py -m app.refresh``).

Si le téléchargement échoue (réseau coupé, GitHub indisponible…), on continue
avec l'ancien cache s'il existe et on ne réessaie pas avant 10 minutes.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import nflreadpy as nfl
import polars as pl

from . import derive, rosters

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TTL = timedelta(hours=6)
RETRY_AFTER_FAILURE = timedelta(minutes=10)


# Jeux de données de la saison précédente : figés une fois la saison
# terminée. S'ils sont déjà en cache, une actualisation les garde au lieu de
# les retélécharger (moins de réseau, et une Action GitHub plus courte).
STABLE_DATASETS = ("prev_player_stats", "prev_pfr_def")

DATASETS = ("schedules", "teams", "player_stats", "team_stats", "pfr_def",
            "quarter_scores", "first_downs", "prev_player_stats", "prev_pfr_def",
            "snap_counts", "players", "rosters", "depth_charts")

TEAM_COLUMNS = ["team_abbr", "team_name", "team_nick", "team_conf", "team_division",
                "team_color", "team_color2"]
# Pressions par joueur et par match (stats avancées PFR), avec l'identifiant
# GSIS de nflverse pour la jointure avec player_stats.
PFR_DEF_SCHEMA = {"game_id": pl.Utf8, "team": pl.Utf8, "pfr_player_id": pl.Utf8,
                  "pfr_player_name": pl.Utf8, "player_id": pl.Utf8, "pressures": pl.Float64}


# Saison précédente : seulement les colonnes qui servent aux scores du MVP
# (distributions de référence en début de saison, voir key_players.MvpScale).
PREV_STATS_COLUMNS = [
    "player_id", "player_display_name", "position", "team", "game_id", "season", "week",
    "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
    "carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards",
    "receiving_tds", "def_tackles_solo", "def_tackle_assists", "def_sacks", "def_qb_hits",
    "def_interceptions", "def_pass_defended", "fg_made", "fg_att", "fg_made_50_59",
    "fg_made_60_", "pat_made", "pat_att",
]


# Table des joueurs (load_players) : identifiants et positions, qui servent
# aux jointures PFR et aux postes des classements (app/data/rankings.py).
PLAYERS_SCHEMA = {"gsis_id": pl.Utf8, "pfr_id": pl.Utf8, "display_name": pl.Utf8,
                  "position": pl.Utf8, "ngs_position": pl.Utf8, "pff_position": pl.Utf8}
SNAP_COLUMNS = ["game_id", "week", "player", "pfr_player_id", "position", "team",
                "offense_snaps", "defense_snaps", "st_snaps"]


def _players() -> pl.DataFrame:
    """Joueurs nflverse (identifiants et positions), ou table vide si indisponible."""
    try:
        df = nfl.load_players()
    except Exception:  # noqa: BLE001 — donnée d'appoint, ne doit pas bloquer
        log.warning("Table des joueurs indisponible : pressions PFR et postes ignorés", exc_info=True)
        return pl.DataFrame(schema=PLAYERS_SCHEMA)
    return df.select(list(PLAYERS_SCHEMA)).filter(pl.col("gsis_id").is_not_null()).unique("gsis_id", keep="first")


def _player_ids(players: pl.DataFrame) -> pl.DataFrame | None:
    """Correspondance pfr_id -> gsis_id, ou None si la table des joueurs manque."""
    if players.is_empty():
        return None
    return players.select("pfr_id", "gsis_id").drop_nulls().unique("pfr_id", keep="first")


def _snap_counts(season: int) -> pl.DataFrame:
    """Snaps par joueur et par match (PFR via nflverse), ou table vide."""
    try:
        df = nfl.load_snap_counts([season])
    except Exception:  # noqa: BLE001 — donnée d'appoint, ne doit pas bloquer
        log.warning("Snaps %s indisponibles : classements sans titulaires", season, exc_info=True)
        return pl.DataFrame()
    return df.select([c for c in SNAP_COLUMNS if c in df.columns])


def _rosters(season: int) -> pl.DataFrame:
    """Dernier roster de chaque équipe (onglet Effectifs), ou table vide."""
    try:
        df = nfl.load_rosters_weekly([season])
    except Exception:  # noqa: BLE001 — donnée d'appoint, ne doit pas bloquer
        log.warning("Rosters %s indisponibles : onglet Effectifs vide", season, exc_info=True)
        return pl.DataFrame()
    return rosters.latest_rosters(df)


def _depth_charts(season: int) -> pl.DataFrame:
    """Dernière photo du depth chart de chaque équipe, ou table vide (les
    effectifs sont alors rangés par numéro)."""
    try:
        df = nfl.load_depth_charts([season])
    except Exception:  # noqa: BLE001 — donnée d'appoint, ne doit pas bloquer
        log.warning("Depth charts %s indisponibles : effectifs rangés par numéro", season, exc_info=True)
        return pl.DataFrame()
    return rosters.latest_depth_charts(df)


def _pfr_pressures(season: int, ids: pl.DataFrame | None) -> pl.DataFrame:
    """Pressions PFR de la saison. Facultatif : en cas d'échec (données pas
    encore publiées, réseau…), table vide et les scores défensifs se font sans."""
    if ids is None:
        return pl.DataFrame(schema=PFR_DEF_SCHEMA)
    try:
        adv = nfl.load_pfr_advstats([season], stat_type="def", summary_level="week")
    except Exception:  # noqa: BLE001 — donnée d'appoint, ne doit pas bloquer
        log.warning("Stats avancées PFR %s indisponibles : pressions ignorées", season, exc_info=True)
        return pl.DataFrame(schema=PFR_DEF_SCHEMA)
    return (adv.select("game_id", "team", "pfr_player_id", "pfr_player_name",
                       pl.col("def_pressures").cast(pl.Float64).alias("pressures"))
            .join(ids, left_on="pfr_player_id", right_on="pfr_id", how="left")
            .rename({"gsis_id": "player_id"})
            .select(list(PFR_DEF_SCHEMA)))


def _prev_player_stats(season: int) -> pl.DataFrame:
    """Stats par match de la saison précédente (colonnes utiles au MVP), ou
    table vide si elles sont indisponibles."""
    try:
        df = nfl.load_player_stats([season - 1])
    except Exception:  # noqa: BLE001 — donnée d'appoint, ne doit pas bloquer
        log.warning("Stats %s indisponibles : MVP sans référence de la saison précédente",
                    season - 1, exc_info=True)
        return pl.DataFrame()
    return df.select([c for c in PREV_STATS_COLUMNS if c in df.columns])


def _download(season: int, keep: dict[str, pl.DataFrame] | None = None) -> dict[str, pl.DataFrame]:
    """Télécharge tous les jeux de données d'une saison via nflreadpy.
    ``keep`` : jeux déjà en cache et figés (STABLE_DATASETS), repris tels quels."""
    keep = keep or {}
    pbp = nfl.load_pbp([season])
    schedules = nfl.load_schedules([season])
    # load_teams contient aussi d'anciennes franchises (OAK, SD, STL…) :
    # on ne garde que les équipes présentes au calendrier de la saison.
    current = set(schedules["home_team"].to_list()) | set(schedules["away_team"].to_list())
    teams = nfl.load_teams().select(TEAM_COLUMNS).filter(pl.col("team_abbr").is_in(current))
    players = _players()
    ids = _player_ids(players)
    return {
        "schedules": schedules,
        "teams": teams,
        "player_stats": nfl.load_player_stats([season]),
        "team_stats": nfl.load_team_stats([season]),
        "pfr_def": _pfr_pressures(season, ids),
        "quarter_scores": derive.quarter_scores(pbp),
        "first_downs": derive.first_downs(pbp),
        "prev_player_stats": keep["prev_player_stats"] if "prev_player_stats" in keep else _prev_player_stats(season),
        "prev_pfr_def": keep["prev_pfr_def"] if "prev_pfr_def" in keep else _pfr_pressures(season - 1, ids),
        "snap_counts": _snap_counts(season),
        "players": players,
        "rosters": _rosters(season),
        "depth_charts": _depth_charts(season),
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
        """Retélécharge tout (sauf les jeux figés déjà en cache), écrit les
        Parquet de façon atomique, renvoie meta."""
        with self._lock:
            if "keep" in inspect.signature(self._downloader).parameters:
                frames = self._downloader(self.season, keep=self._stable_frames())
            else:
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

    def _stable_frames(self) -> dict[str, pl.DataFrame]:
        """Jeux figés (saison précédente) déjà en cache et non vides."""
        out = {}
        for name in STABLE_DATASETS:
            path = self.dir / f"{name}.parquet"
            if path.exists():
                try:
                    df = pl.read_parquet(path)
                except Exception:  # noqa: BLE001 — fichier abîmé : on retélécharge
                    continue
                if df.height:
                    out[name] = df
        return out

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

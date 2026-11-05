"""Application FastAPI : API JSON + front vanilla (app/static).

Lancement : ``py -m uvicorn app.main:app --reload``
"""
from __future__ import annotations

import logging
from pathlib import Path

import nflreadpy as nfl
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .data.cache import SeasonCache
from .data.models import DivisionStandings, Game, GameDetail, Meta, PlayerSeason, Team
from .data.repository import NflRepository

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="NFL Gameday")
repo = NflRepository(SeasonCache(nfl.get_current_season()))


@app.get("/api/meta", response_model=Meta)
def meta() -> Meta:
    return repo.meta()


@app.get("/api/teams", response_model=list[Team])
def teams() -> list[Team]:
    return repo.teams()


@app.get("/api/weeks/{week}", response_model=list[Game])
def week(week: int) -> list[Game]:
    games = repo.games_for_week(week)
    if not games:
        raise HTTPException(404, f"Aucun match en semaine {week}")
    return games


@app.get("/api/games/{game_id}", response_model=GameDetail)
def game(game_id: str) -> GameDetail:
    detail = repo.game_detail(game_id)
    if detail is None:
        raise HTTPException(404, f"Match inconnu : {game_id}")
    return detail


@app.get("/api/standings", response_model=list[DivisionStandings])
def standings() -> list[DivisionStandings]:
    return repo.standings()


@app.get("/api/players/{player_id}", response_model=PlayerSeason)
def player(player_id: str) -> PlayerSeason:
    season = repo.player_season(player_id)
    if season is None:
        raise HTTPException(404, f"Joueur inconnu : {player_id}")
    return season


@app.post("/api/refresh", response_model=Meta)
def refresh() -> Meta:
    try:
        repo.cache.refresh()
    except Exception as exc:  # réseau coupé, GitHub indisponible… : l'ancien cache reste utilisable
        logging.getLogger(__name__).exception("Échec de l'actualisation")
        raise HTTPException(502, f"Téléchargement nflverse impossible ({type(exc).__name__}). "
                                 "Les données précédentes restent affichées.") from exc
    return repo.meta()


# --- Front -------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")

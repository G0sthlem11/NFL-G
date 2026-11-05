"""Modèles Pydantic exposés par l'API.

Le front ne voit que ces modèles, jamais les DataFrames nflverse bruts.
Toute stat absente vaut ``None`` (affichée « — » côté front).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class QuarterScore(BaseModel):
    period: str  # "1", "2", "3", "4", "OT"
    away: int | None = None
    home: int | None = None


class Game(BaseModel):
    game_id: str
    season: int
    week: int
    week_label: str
    game_type: str  # REG, WC, DIV, CON, SB
    status: Literal["final", "scheduled"]
    gameday: str | None = None  # date du match, heure de l'Est (YYYY-MM-DD)
    kickoff_paris: datetime | None = None
    away_team: str
    home_team: str
    away_score: int | None = None
    home_score: int | None = None
    overtime: bool = False
    quarters: list[QuarterScore] = []
    stadium: str | None = None
    roof: str | None = None
    surface: str | None = None
    temp_f: int | None = None
    wind_mph: int | None = None
    div_game: bool = False
    away_coach: str | None = None
    home_coach: str | None = None
    away_qb_name: str | None = None
    home_qb_name: str | None = None


class TeamStats(BaseModel):
    team: str
    total_yards: int | None = None
    net_passing_yards: int | None = None
    passing_yards: int | None = None
    rushing_yards: int | None = None
    completions: int | None = None
    attempts: int | None = None
    passing_tds: int | None = None
    carries: int | None = None
    rushing_tds: int | None = None
    first_downs: int | None = None
    first_downs_pass: int | None = None
    first_downs_rush: int | None = None
    first_downs_penalty: int | None = None
    turnovers: int | None = None
    interceptions_thrown: int | None = None
    fumbles_lost: int | None = None
    sacks_suffered: int | None = None
    sack_yards_lost: int | None = None
    def_sacks: float | None = None
    def_interceptions: int | None = None
    penalties: int | None = None
    penalty_yards: int | None = None


class PlayerLine(BaseModel):
    """Ligne de stats d'un joueur pour un match."""

    player_id: str
    name: str
    position: str | None = None
    team: str
    headshot_url: str | None = None
    # Passe
    completions: int | None = None
    attempts: int | None = None
    passing_yards: int | None = None
    passing_tds: int | None = None
    interceptions: int | None = None
    sacks_suffered: int | None = None
    # Course
    carries: int | None = None
    rushing_yards: int | None = None
    rushing_tds: int | None = None
    # Réception
    targets: int | None = None
    receptions: int | None = None
    receiving_yards: int | None = None
    receiving_tds: int | None = None
    # Défense
    tackles: int | None = None
    tackles_solo: int | None = None
    tackle_assists: int | None = None
    tackles_for_loss: float | None = None
    sacks: float | None = None
    qb_hits: int | None = None
    def_interceptions: int | None = None
    passes_defended: int | None = None
    fumbles_forced: int | None = None


class KeyPlayer(BaseModel):
    role: str  # QB, RB1, WR1, WR2, TE1, EDGE1, EDGE2
    label: str  # libellé affiché : QB, RB1, WR1, WR2, TE1, DE, OLB
    depth_pos: str | None = None  # poste du depth chart (LDE, WLB…)
    player: PlayerLine | None = None
    # depth_chart : le titulaire du depth chart a joué
    # replacement : il n'a pas joué, remplacé par le plus productif du poste
    # fallback    : pas de depth chart, choix sur la production du match
    # none        : personne à afficher
    source: Literal["depth_chart", "replacement", "fallback", "none"] = "none"
    replaced_starter: str | None = None
    replaced_reason: str | None = None  # « inactif », « en réserve »…


class KeyPlayers(BaseModel):
    team: str
    scheme: str | None = None  # "3-4" ou "4-3"
    depth_chart_dt: str | None = None
    offense: list[KeyPlayer] = []
    edges: list[KeyPlayer] = []
    tackle_leader: PlayerLine | None = None
    playmakers: list[PlayerLine] = []  # sack, interception ou fumble forcé


class GameDetail(BaseModel):
    game: Game
    away_stats: TeamStats | None = None
    home_stats: TeamStats | None = None
    away_key: KeyPlayers | None = None
    home_key: KeyPlayers | None = None


class Team(BaseModel):
    abbr: str
    name: str
    nick: str | None = None
    conference: str | None = None
    division: str | None = None
    color: str | None = None
    color2: str | None = None


class WeekInfo(BaseModel):
    week: int
    label: str
    games: int
    finals: int


class Meta(BaseModel):
    season: int
    fetched_at: datetime | None = None
    current_week: int | None = None
    weeks: list[WeekInfo] = []

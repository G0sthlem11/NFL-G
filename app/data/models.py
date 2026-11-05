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
    pressures: float | None = None  # stats avancées PFR, jointes au match
    # Coups de pied
    fg_made: int | None = None
    fg_att: int | None = None
    fg_long: int | None = None
    fg_made_50: int | None = None  # FG réussis de 50 yards ou plus
    pat_made: int | None = None
    pat_att: int | None = None


class RankedPlayer(BaseModel):
    """Joueur classé (top offensif ou défensif d'un match)."""

    rank: int
    score: float
    player: PlayerLine


class TeamKeyPlayers(BaseModel):
    """Joueurs clés d'une équipe pour un match (app/data/key_players.py)."""

    team: str
    quarterbacks: list[PlayerLine] = []
    offense: list[RankedPlayer] = []
    defense: list[RankedPlayer] = []
    kickers: list[PlayerLine] = []


class Mvp(BaseModel):
    """MVP du match (app/data/key_players.py)."""

    player: PlayerLine
    category: Literal["qb", "offense", "defense", "kicker"]
    score: float  # score brut de sa catégorie
    percentile: float  # rang centile dans sa catégorie (0 à 100)
    normalized: float  # percentile après malus éventuel (kicker) : sert au choix


class MatchKeyPlayers(BaseModel):
    """Joueurs clés d'un match, équipe par équipe."""

    away: TeamKeyPlayers
    home: TeamKeyPlayers
    mvp: Mvp | None = None
    # False : PFR ne couvre pas ce match, le score défensif ignore les pressions.
    pressures_available: bool = False
    # Pondérations utilisées (key_players.toml), pour les afficher telles quelles.
    weights: dict[str, dict[str, float]] = {}


class GameDetail(BaseModel):
    game: Game
    away_stats: TeamStats | None = None
    home_stats: TeamStats | None = None
    key_players: MatchKeyPlayers | None = None


class Team(BaseModel):
    abbr: str
    name: str
    nick: str | None = None
    conference: str | None = None
    division: str | None = None
    color: str | None = None
    color2: str | None = None
    # Couleur du point d'équipe par thème, choisie selon le contraste avec le
    # fond (voir app/data/team_assets.py).
    dot_light: str | None = None
    dot_dark: str | None = None
    # Logo local, relatif à la racine du site (logos/KC.png), s'il existe.
    logo: str | None = None
    logo_dark: str | None = None  # variante pour fond sombre (logos/dark/KC.png)


class StandingRow(BaseModel):
    team: str
    name: str
    conference: str
    division: str
    wins: int
    losses: int
    ties: int
    pct: float
    points_for: int
    points_against: int
    diff: int
    div_record: str
    conf_record: str
    home_record: str
    away_record: str
    streak: str | None = None  # « V3 », « D1 », « N1 »


class DivisionStandings(BaseModel):
    name: str  # « AFC East »
    conference: str
    rows: list[StandingRow]


class PlayerGame(BaseModel):
    game_id: str
    week: int
    week_label: str
    team: str
    opponent: str
    home: bool
    result: Literal["V", "D", "N"] | None = None
    team_score: int | None = None
    opponent_score: int | None = None
    line: PlayerLine


class PlayerSeason(BaseModel):
    player_id: str
    name: str
    position: str | None = None
    position_group: str | None = None
    teams: list[str] = []
    headshot_url: str | None = None
    games_played: int = 0
    totals: PlayerLine
    games: list[PlayerGame] = []


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


class RankingRow(BaseModel):
    """Titulaire d'une équipe à un poste (app/data/rankings.py)."""

    rank: int  # rang par moyenne par match (non éligibles en fin de classement)
    player_id: str
    name: str
    team: str  # équipe où il a le plus joué
    position: str | None = None  # position de player_stats (affichage)
    headshot_url: str | None = None
    games: int  # matchs joués
    snaps: int | None = None  # snaps de la saison (None pour le kicker)
    eligible: bool  # au moins min_games matchs joués
    score_total: float
    score_avg: float  # score_total / games
    totals: PlayerLine  # totaux de la saison, toutes équipes confondues


class PositionRanking(BaseModel):
    key: str  # « QB », « EDGE »…
    score: Literal["qb", "offense", "defense", "kicker"]
    rows: list[RankingRow] = []


class Rankings(BaseModel):
    season: int
    min_games: int
    positions: list[PositionRanking] = []

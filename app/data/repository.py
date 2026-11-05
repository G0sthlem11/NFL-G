"""Accès aux données de la saison, déjà normalisées en modèles Pydantic."""
from __future__ import annotations

import polars as pl

from .cache import SeasonCache
from .key_players import select_key_players
from .models import (DivisionStandings, Game, GameDetail, KeyPlayers, Meta, PlayerGame,
                     PlayerSeason, Team, WeekInfo)
from .normalize import as_int, as_str, to_game, to_player_line, to_team_stats, week_label
from .standings import compute_standings

# Colonnes player_stats additionnées pour les totaux de saison.
SEASON_SUM_COLUMNS = [
    "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
    "carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds",
    "def_tackles_solo", "def_tackle_assists", "def_tackles_for_loss", "def_sacks", "def_qb_hits",
    "def_interceptions", "def_pass_defended", "def_fumbles_forced",
]


class NflRepository:
    def __init__(self, cache: SeasonCache) -> None:
        self.cache = cache

    @property
    def season(self) -> int:
        return self.cache.season

    def _schedules(self) -> pl.DataFrame:
        return self.cache.get("schedules")

    def _quarters_by_game(self, game_ids: list[str]) -> dict[str, list[dict]]:
        qs = self.cache.get("quarter_scores")
        out: dict[str, list[dict]] = {}
        if qs.is_empty():
            return out
        for q in qs.filter(pl.col("game_id").is_in(game_ids)).to_dicts():
            out.setdefault(q["game_id"], []).append(q)
        return out

    def _to_games(self, sched: pl.DataFrame) -> list[Game]:
        rows = sched.sort("gameday", "gametime", "game_id").to_dicts()
        quarters = self._quarters_by_game([r["game_id"] for r in rows])
        return [to_game(r, quarters.get(r["game_id"])) for r in rows]

    # --- API publique ----------------------------------------------------
    def teams(self) -> list[Team]:
        df = self.cache.get("teams")
        if df.is_empty():
            return []
        return [
            Team(abbr=r["team_abbr"], name=r["team_name"], nick=as_str(r.get("team_nick")),
                 conference=as_str(r.get("team_conf")), division=as_str(r.get("team_division")),
                 color=as_str(r.get("team_color")), color2=as_str(r.get("team_color2")))
            for r in df.sort("team_abbr").to_dicts()
        ]

    def weeks(self) -> list[WeekInfo]:
        s = self._schedules()
        agg = (
            s.group_by("week")
            .agg(pl.col("game_type").first(), pl.len().alias("games"),
                 pl.col("home_score").is_not_null().sum().alias("finals"))
            .sort("week")
        )
        return [WeekInfo(week=r["week"], label=week_label(r["game_type"], r["week"]),
                         games=r["games"], finals=r["finals"]) for r in agg.to_dicts()]

    def current_week(self) -> int | None:
        """Dernière semaine ayant au moins un résultat (sinon la première)."""
        weeks = self.weeks()
        played = [w.week for w in weeks if w.finals > 0]
        if played:
            return max(played)
        return weeks[0].week if weeks else None

    def meta(self) -> Meta:
        weeks = self.weeks()
        return Meta(season=self.season, fetched_at=self.cache.fetched_at(),
                    current_week=self.current_week(), weeks=weeks)

    def games_for_week(self, week: int) -> list[Game]:
        return self._to_games(self._schedules().filter(pl.col("week") == week))

    def game(self, game_id: str) -> Game | None:
        games = self._to_games(self._schedules().filter(pl.col("game_id") == game_id))
        return games[0] if games else None

    def game_detail(self, game_id: str) -> GameDetail | None:
        game = self.game(game_id)
        if game is None:
            return None
        if game.status != "final":
            return GameDetail(game=game)
        ts = self.cache.get("team_stats")
        fd = self.cache.get("first_downs")

        def rows(df: pl.DataFrame) -> dict[str, dict]:
            if df.is_empty():
                return {}
            return {r["team"]: r for r in df.filter(pl.col("game_id") == game_id).to_dicts()}

        ts_rows, fd_rows = rows(ts), rows(fd)
        return GameDetail(
            game=game,
            away_stats=to_team_stats(game.away_team, ts_rows.get(game.away_team), fd_rows.get(game.away_team)),
            home_stats=to_team_stats(game.home_team, ts_rows.get(game.home_team), fd_rows.get(game.home_team)),
            away_key=self._key_players(game, game.away_team),
            home_key=self._key_players(game, game.home_team),
        )

    def standings(self) -> list[DivisionStandings]:
        teams = self.cache.get("teams")
        if teams.is_empty():
            return []
        return compute_standings(self._schedules(), teams)

    def player_season(self, player_id: str) -> PlayerSeason | None:
        ps = self.cache.get("player_stats")
        if ps.is_empty():
            return None
        rows = ps.filter(pl.col("player_id") == player_id)
        if rows.is_empty():
            return None
        sched = {r["game_id"]: r for r in self._schedules()
                 .filter(pl.col("game_id").is_in(rows["game_id"].to_list())).to_dicts()}

        games: list[PlayerGame] = []
        for r in rows.sort("week").to_dicts():
            g = sched.get(r["game_id"])
            if g is None:
                continue
            home = g["home_team"] == r["team"]
            ts, os_ = (g["home_score"], g["away_score"]) if home else (g["away_score"], g["home_score"])
            result = None
            if ts is not None and os_ is not None:
                result = "V" if ts > os_ else "D" if ts < os_ else "N"
            games.append(PlayerGame(
                game_id=r["game_id"], week=g["week"], week_label=week_label(g["game_type"], g["week"]),
                team=r["team"], opponent=g["away_team"] if home else g["home_team"], home=home,
                result=result, team_score=as_int(ts), opponent_score=as_int(os_), line=to_player_line(r),
            ))

        # Totaux saison : somme des colonnes de stats (les colonnes absentes restent nulles).
        sums = rows.select([pl.col(c).sum() for c in SEASON_SUM_COLUMNS if c in rows.columns]).to_dicts()[0]
        last = rows.sort("week").to_dicts()[-1]
        totals = to_player_line({**sums, "player_id": player_id, "player_display_name": last.get("player_display_name"),
                                 "position": last.get("position"), "team": last["team"]})
        teams_seen: list[str] = []
        for g in games:
            if g.team not in teams_seen:
                teams_seen.append(g.team)
        return PlayerSeason(
            player_id=player_id, name=totals.name, position=as_str(last.get("position")),
            position_group=as_str(last.get("position_group")), teams=teams_seen,
            headshot_url=as_str(last.get("headshot_url")), games_played=len(games),
            totals=totals, games=games,
        )

    def _key_players(self, game: Game, team: str) -> KeyPlayers:
        ps = self.cache.get("player_stats")
        dc = self.cache.get("depth_charts")
        rw = self.cache.get("rosters")
        stats = ps.filter((pl.col("game_id") == game.game_id) & (pl.col("team") == team)) \
            if not ps.is_empty() else ps
        depth = dc.filter(pl.col("team") == team) if not dc.is_empty() else dc
        roster = rw.filter((pl.col("team") == team) & (pl.col("week") == game.week)) \
            if not rw.is_empty() else rw
        return select_key_players(team, game.gameday or "", game.kickoff_paris, stats, depth, roster)

"""Accès aux données de la saison, déjà normalisées en modèles Pydantic."""
from __future__ import annotations

import polars as pl

from .cache import SeasonCache
from .models import Game, GameDetail, Meta, Team, WeekInfo
from .normalize import as_str, to_game, to_team_stats, week_label


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
        )

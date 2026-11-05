"""Tables dérivées du play-by-play, calculées au rafraîchissement.

On ne garde pas le play-by-play complet (~45 Mo par saison) : seulement
les deux petites tables dont l'app a besoin.
"""
import polars as pl


def quarter_scores(pbp: pl.DataFrame) -> pl.DataFrame:
    """Points marqués par quart-temps (qtr 5 = prolongation).

    ``total_*_score`` est le score cumulé après chaque action : son maximum
    sur un quart donne le score à la fin du quart, et la différence avec le
    quart précédent donne les points marqués pendant ce quart.

    Colonnes renvoyées : game_id, qtr, away, home.
    """
    cum = (
        pbp.filter(pl.col("qtr").is_not_null())
        .group_by("game_id", pl.col("qtr").cast(pl.Int32))
        .agg(
            pl.col("total_away_score").max().cast(pl.Int32).alias("away_cum"),
            pl.col("total_home_score").max().cast(pl.Int32).alias("home_cum"),
        )
        .sort("game_id", "qtr")
    )
    return cum.select(
        "game_id",
        "qtr",
        (pl.col("away_cum") - pl.col("away_cum").shift(1).over("game_id").fill_null(0)).alias("away"),
        (pl.col("home_cum") - pl.col("home_cum").shift(1).over("game_id").fill_null(0)).alias("home"),
    )


def first_downs(pbp: pl.DataFrame) -> pl.DataFrame:
    """1ers downs par équipe et par match (total, passe, course, pénalité).

    Colonnes renvoyées : game_id, team, first_downs, first_downs_pass,
    first_downs_rush, first_downs_penalty.
    """
    def s(col: str) -> pl.Expr:
        return pl.col(col).fill_null(0).sum().cast(pl.Int32)

    return (
        pbp.filter(pl.col("posteam").is_not_null())
        .group_by("game_id", pl.col("posteam").alias("team"))
        .agg(
            s("first_down").alias("first_downs"),
            s("first_down_pass").alias("first_downs_pass"),
            s("first_down_rush").alias("first_downs_rush"),
            s("first_down_penalty").alias("first_downs_penalty"),
        )
        .sort("game_id", "team")
    )

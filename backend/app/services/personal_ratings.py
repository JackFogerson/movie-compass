from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Movie, User, UserMovieInteraction


def linked_personal_ratings(
    session: Session, user_slug: str, catalog: pd.DataFrame
) -> dict[int, float]:
    user = session.scalar(select(User).where(User.slug == user_slug))
    if user is None:
        raise ValueError(f"Unknown user: {user_slug}")
    rows = session.execute(
        select(Movie.tmdb_id, UserMovieInteraction.rating)
        .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
        .where(
            UserMovieInteraction.user_id == user.id,
            UserMovieInteraction.rating.is_not(None),
            Movie.tmdb_id.is_not(None),
        )
    ).all()
    rating_by_tmdb = {int(tmdb_id): float(rating) for tmdb_id, rating in rows}
    linked = catalog[catalog["tmdb_id"].notna()]
    return {
        int(row.movieId): rating_by_tmdb[int(row.tmdb_id)]
        for row in linked.itertuples()
        if int(row.tmdb_id) in rating_by_tmdb
    }


def personal_tmdb_ratings(session: Session, user_slug: str) -> dict[int, float]:
    user = session.scalar(select(User).where(User.slug == user_slug))
    if user is None:
        raise ValueError(f"Unknown user: {user_slug}")
    rows = session.execute(
        select(Movie.tmdb_id, UserMovieInteraction.rating)
        .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
        .where(
            UserMovieInteraction.user_id == user.id,
            UserMovieInteraction.rating.is_not(None),
            Movie.tmdb_id.is_not(None),
        )
    ).all()
    return {int(tmdb_id): float(rating) for tmdb_id, rating in rows}


def personal_tmdb_reviews(session: Session, user_slug: str) -> dict[int, str]:
    user = session.scalar(select(User).where(User.slug == user_slug))
    if user is None:
        raise ValueError(f"Unknown user: {user_slug}")
    rows = session.execute(
        select(Movie.tmdb_id, UserMovieInteraction.review_text)
        .join(UserMovieInteraction, UserMovieInteraction.movie_id == Movie.id)
        .where(
            UserMovieInteraction.user_id == user.id,
            UserMovieInteraction.rating.is_not(None),
            UserMovieInteraction.review_text.is_not(None),
            Movie.tmdb_id.is_not(None),
        )
    ).all()
    return {
        int(tmdb_id): str(review)
        for tmdb_id, review in rows
        if review is not None and str(review).strip()
    }

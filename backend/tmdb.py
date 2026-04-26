import os
from datetime import datetime

import requests

from .config import load_env_file


TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w500"

load_env_file()


def enrich_movie(connection, movie_id, language="ru-RU"):
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "message": "TMDB_API_KEY не задан. Добавьте ключ в переменные окружения и повторите запрос.",
        }

    row = connection.execute("SELECT tmdb_id FROM movies WHERE id = ?", (movie_id,)).fetchone()
    if not row or not row["tmdb_id"]:
        return {"ok": False, "message": "У фильма нет tmdb_id в MovieLens links.csv."}

    response = requests.get(
        f"{TMDB_BASE_URL}/movie/{row['tmdb_id']}",
        params={"api_key": api_key, "language": language, "append_to_response": "credits"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    credits = payload.get("credits") or {}
    director = next(
        (person["name"] for person in credits.get("crew", []) if person.get("job") == "Director"),
        None,
    )
    actors = [person["name"] for person in credits.get("cast", [])[:6]]
    poster = f"{TMDB_IMAGE_URL}{payload['poster_path']}" if payload.get("poster_path") else None
    description = payload.get("overview") or ""

    connection.execute(
        """
        UPDATE movie_metadata
        SET poster = COALESCE(?, poster),
            description = COALESCE(NULLIF(?, ''), description),
            actors = ?,
            director = ?,
            source = 'tmdb',
            updated_at = ?
        WHERE movie_id = ?
        """,
        (poster, description, json_dumps(actors), director, datetime.utcnow().isoformat(), movie_id),
    )
    connection.commit()
    return {"ok": True, "movieId": movie_id, "poster": poster, "director": director, "actors": actors}


def json_dumps(value):
    import json

    return json.dumps(value, ensure_ascii=False)

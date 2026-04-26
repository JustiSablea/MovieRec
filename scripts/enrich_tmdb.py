import argparse
import json
import os
import sqlite3
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "movierec.sqlite3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def enrich(limit, language):
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        raise SystemExit("TMDB_API_KEY не задан. Получите ключ TMDb и добавьте его в переменные окружения.")

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT m.id, m.tmdb_id
        FROM movies m
        JOIN movie_metadata mm ON mm.movie_id = m.id
        WHERE m.tmdb_id IS NOT NULL AND mm.source != 'tmdb'
        ORDER BY m.weighted_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    for row in rows:
        response = requests.get(
            f"https://api.themoviedb.org/3/movie/{row['tmdb_id']}",
            params={"api_key": api_key, "language": language, "append_to_response": "credits"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        credits = payload.get("credits") or {}
        director = next((person["name"] for person in credits.get("crew", []) if person.get("job") == "Director"), None)
        actors = [person["name"] for person in credits.get("cast", [])[:6]]
        poster = f"{IMAGE_BASE}{payload['poster_path']}" if payload.get("poster_path") else None
        connection.execute(
            """
            UPDATE movie_metadata
            SET poster = COALESCE(?, poster),
                description = COALESCE(NULLIF(?, ''), description),
                actors = ?,
                director = ?,
                source = 'tmdb',
                updated_at = CURRENT_TIMESTAMP
            WHERE movie_id = ?
            """,
            (poster, payload.get("overview") or "", json.dumps(actors, ensure_ascii=False), director, row["id"]),
        )
        print(f"enriched movieId={row['id']}")

    connection.commit()
    connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--language", default="ru-RU")
    args = parser.parse_args()
    enrich(args.limit, args.language)


if __name__ == "__main__":
    main()

import argparse
import json
import os
import sqlite3
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "movierec.sqlite3"
MOVIES_JSON = ROOT / "data" / "movies.json"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


def load_env_file():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def enrich(limit, language, sync_json=True):
    load_env_file()
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
        if response.status_code == 404:
            print(f"skip movieId={row['id']} tmdb_id={row['tmdb_id']} reason=404")
            continue
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
    if sync_json:
        sync_json_metadata(connection)
    connection.close()


def sync_json_metadata(connection):
    if not MOVIES_JSON.exists():
        return
    data = json.loads(MOVIES_JSON.read_text(encoding="utf-8"))
    rows = connection.execute(
        """
        SELECT movie_id, poster, description, actors, director
        FROM movie_metadata
        WHERE source = 'tmdb'
        """
    ).fetchall()
    metadata = {row["movie_id"]: row for row in rows}
    for movie in data.get("movies", []):
        row = metadata.get(movie["id"])
        if not row:
            continue
        movie["poster"] = row["poster"]
        movie["description"] = row["description"] or movie.get("description", "")
        movie["actors"] = json.loads(row["actors"] or "[]")
        movie["director"] = row["director"]
    MOVIES_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--language", default="ru-RU")
    parser.add_argument("--no-sync-json", action="store_true")
    args = parser.parse_args()
    enrich(args.limit, args.language, sync_json=not args.no_sync_json)


if __name__ == "__main__":
    main()

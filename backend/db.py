import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "movierec.sqlite3"
MOVIES_JSON = ROOT / "data" / "movies.json"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                year INTEGER,
                genres TEXT NOT NULL,
                average_rating REAL NOT NULL,
                rating_count INTEGER NOT NULL,
                weighted_score REAL NOT NULL,
                popularity REAL NOT NULL,
                tmdb_id INTEGER,
                imdb_id TEXT
            );

            CREATE TABLE IF NOT EXISTS movie_metadata (
                movie_id INTEGER PRIMARY KEY,
                poster TEXT,
                palette TEXT NOT NULL,
                tags TEXT NOT NULL,
                description TEXT NOT NULL,
                actors TEXT NOT NULL DEFAULT '[]',
                director TEXT,
                source TEXT NOT NULL DEFAULT 'movielens',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS movie_similarities (
                movie_id INTEGER NOT NULL,
                similar_movie_id INTEGER NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (movie_id, similar_movie_id),
                FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE,
                FOREIGN KEY (similar_movie_id) REFERENCES movies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ratings (
                user_id INTEGER NOT NULL,
                movie_id INTEGER NOT NULL,
                rating REAL NOT NULL CHECK (rating >= 0.5 AND rating <= 5.0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, movie_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                user_id INTEGER NOT NULL,
                movie_id INTEGER NOT NULL,
                score REAL NOT NULL,
                cf_score REAL NOT NULL,
                content_score REAL NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, movie_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS movie_embeddings (
                movie_id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                embedding TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS movie_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT NOT NULL,
                year INTEGER,
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            """
        )
        import_movies(connection)


def import_movies(connection):
    if not MOVIES_JSON.exists():
        return

    data = json.loads(MOVIES_JSON.read_text(encoding="utf-8"))
    imported_ids = {movie["id"] for movie in data["movies"]}
    movie_count = connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    if movie_count == data.get("movieCount"):
        return

    connection.execute("DELETE FROM movie_similarities")
    connection.execute("DELETE FROM movie_metadata")
    connection.execute("DELETE FROM movies")

    for movie in data["movies"]:
        connection.execute(
            """
            INSERT INTO movies (
                id, title, year, genres, average_rating, rating_count,
                weighted_score, popularity, tmdb_id, imdb_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                movie["id"],
                movie["title"],
                movie.get("year"),
                json.dumps(movie.get("genres", []), ensure_ascii=False),
                movie["averageRating"],
                movie["ratingCount"],
                movie["weightedScore"],
                movie["popularity"],
                movie.get("tmdbId"),
                movie.get("imdbId"),
            ),
        )
        connection.execute(
            """
            INSERT INTO movie_metadata (movie_id, poster, palette, tags, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                movie["id"],
                movie.get("poster"),
                json.dumps(movie.get("palette", []), ensure_ascii=False),
                json.dumps(movie.get("tags", []), ensure_ascii=False),
                movie.get("description") or "",
            ),
        )
    for movie in data["movies"]:
        for similar in movie.get("similar", []):
            if similar["id"] not in imported_ids:
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO movie_similarities (movie_id, similar_movie_id, score)
                VALUES (?, ?, ?)
                """,
                (movie["id"], similar["id"], similar["score"]),
            )


def rows_to_movies(rows):
    return [row_to_movie(row) for row in rows]


def row_to_movie(row):
    movie = dict(row)
    return {
        "id": movie["id"],
        "title": movie["title"],
        "year": movie["year"],
        "genres": json.loads(movie["genres"] or "[]"),
        "averageRating": movie["average_rating"],
        "ratingCount": movie["rating_count"],
        "weightedScore": movie["weighted_score"],
        "popularity": movie["popularity"],
        "tmdbId": movie["tmdb_id"],
        "imdbId": movie["imdb_id"],
        "poster": movie.get("poster"),
        "palette": json.loads(movie.get("palette") or "[]"),
        "tags": json.loads(movie.get("tags") or "[]"),
        "description": movie.get("description") or "",
        "actors": json.loads(movie.get("actors") or "[]"),
        "director": movie.get("director"),
    }

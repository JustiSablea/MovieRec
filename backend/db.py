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
                admin_note TEXT NOT NULL DEFAULT '',
                added_movie_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                FOREIGN KEY (added_movie_id) REFERENCES movies(id) ON DELETE SET NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS support_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                guest_name TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT 'Поддержка MovieRec',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                user_id INTEGER,
                sender_role TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (thread_id) REFERENCES support_threads(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            """
        )
        ensure_column(connection, "movie_requests", "admin_note", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "movie_requests", "added_movie_id", "INTEGER")
        ensure_column(connection, "movie_requests", "resolved_at", "TEXT")
        import_movies(connection)


def ensure_column(connection, table, column, definition):
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def import_movies(connection):
    if not MOVIES_JSON.exists():
        return

    data = json.loads(MOVIES_JSON.read_text(encoding="utf-8"))
    imported_ids = {movie["id"] for movie in data["movies"]}
    placeholders = ",".join("?" for _ in imported_ids)
    movie_count = connection.execute(
        f"SELECT COUNT(*) FROM movies WHERE id IN ({placeholders})",
        tuple(imported_ids),
    ).fetchone()[0]
    if movie_count == data.get("movieCount"):
        return

    connection.execute("DELETE FROM movie_similarities")

    for movie in data["movies"]:
        connection.execute(
            """
            INSERT INTO movies (
                id, title, year, genres, average_rating, rating_count,
                weighted_score, popularity, tmdb_id, imdb_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id)
            DO UPDATE SET title = excluded.title,
                          year = excluded.year,
                          genres = excluded.genres,
                          average_rating = excluded.average_rating,
                          rating_count = excluded.rating_count,
                          weighted_score = excluded.weighted_score,
                          popularity = excluded.popularity,
                          tmdb_id = excluded.tmdb_id,
                          imdb_id = excluded.imdb_id
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
            INSERT INTO movie_metadata (movie_id, poster, palette, tags, description, actors, director, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(movie_id)
            DO UPDATE SET poster = excluded.poster,
                          palette = excluded.palette,
                          tags = excluded.tags,
                          description = excluded.description,
                          actors = excluded.actors,
                          director = excluded.director,
                          source = excluded.source,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (
                movie["id"],
                movie.get("poster"),
                json.dumps(movie.get("palette", []), ensure_ascii=False),
                json.dumps(movie.get("tags", []), ensure_ascii=False),
                movie.get("description") or "",
                json.dumps(movie.get("actors", []), ensure_ascii=False),
                movie.get("director"),
                "tmdb" if movie.get("poster") or movie.get("actors") or movie.get("director") else "movielens",
            ),
        )
    if imported_ids:
        connection.execute(f"DELETE FROM movies WHERE id NOT IN ({placeholders}) AND id < 10000000", tuple(imported_ids))
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

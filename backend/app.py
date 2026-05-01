import json
import math
import os
import re
from datetime import datetime
from time import time

import requests
from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import ROOT, get_connection, init_db
from .embeddings import embedding_search, expand_query, rebuild_movie_embeddings
from .recommender import HybridRecommender
from .tmdb import enrich_movie


app = Flask(__name__, static_folder=None)
app.secret_key = "movierec-dev-secret-change-before-production"
APP_VERSION = "2026-04-28-semantic-understanding"

MOVIE_REQUEST_LIMITS = {}
LLM_RERANK_CACHE = {}
QUERY_PARSE_CACHE = {}
TMDB_SEARCH_CACHE = {}
TITLE_RE = re.compile(r"^[\w\s:;,.!?&'’()\-а-яА-ЯёЁ0-9]+$", re.UNICODE)
HINT_STOP_TOKENS = {"the", "a", "an", "of", "and", "из", "и", "в", "на"}
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w500"
DEFAULT_ADMIN_USERNAMES = "admin,azzma,justisablea"
SEARCH_TERM_ALIASES = {
    "animation": ("мультфильм", "анимация", "cartoon", "family"),
    "cartoon": ("мультфильм", "animation"),
    "action": ("боевик", "action"),
    "superhero": ("супергерой", "super hero", "comic book"),
    "sci-fi": ("фантастика", "science fiction", "sci fi"),
    "science fiction": ("фантастика", "sci-fi"),
    "mystery": ("детектив", "тайна", "загадка"),
    "cat": ("кот", "кошка", "кошачий"),
    "orange cat": ("рыжий кот", "оранжевый кот", "cat"),
    "talking cat": ("говорящий кот", "cat"),
    "prison": ("тюрьма", "заключенный"),
    "prison escape": ("побег из тюрьмы", "escape"),
    "heist": ("ограбление", "кража"),
    "dream": ("сон", "сны", "подсознание"),
    "moving castle": ("ходячий замок", "движущийся замок"),
    "castle travels": ("ходячий замок", "движущийся замок"),
    "castle movement": ("ходячий замок", "движущийся замок"),
    "magic castle": ("волшебный замок", "ходячий замок"),
}
GENRE_LABELS = {
    "Action": "боевик",
    "Adventure": "приключения",
    "Animation": "мультфильм",
    "Children": "семейный",
    "Comedy": "комедия",
    "Crime": "криминал",
    "Documentary": "документальный",
    "Drama": "драма",
    "Fantasy": "фэнтези",
    "Film-Noir": "нуар",
    "Horror": "ужасы",
    "IMAX": "IMAX",
    "Musical": "мюзикл",
    "Mystery": "детектив",
    "Romance": "мелодрама",
    "Science Fiction": "фантастика",
    "Sci-Fi": "фантастика",
    "Thriller": "триллер",
    "Family": "семейный",
    "History": "история",
    "Music": "музыка",
    "TV Movie": "телефильм",
    "War": "военный",
    "Western": "вестерн",
}
GENRE_ALIASES = {}
for raw_genre, label in GENRE_LABELS.items():
    GENRE_ALIASES.setdefault(label.lower(), set()).update({raw_genre, label})
    GENRE_ALIASES.setdefault(raw_genre.lower(), set()).update({raw_genre, label})

SEMANTIC_CONCEPTS = {
    "dream": {
        "label": "сны и подсознание",
        "query": ("сон", "сны", "снах", "сын", "dream", "dreams"),
        "movie": ("сон", "сны", "dream", "dreams", "подсозн", "разум"),
    },
    "heist": {
        "label": "ограбление и кража",
        "query": ("ограб", "heist", "вор", "краж", "преступ"),
        "movie": ("ограб", "heist", "вор", "краж", "преступ", "крадет", "крадёт", "crime"),
    },
    "space": {
        "label": "космос",
        "query": ("космос", "space", "планет", "галактик"),
        "movie": ("космос", "space", "планет", "галактик", "sci-fi"),
    },
    "robot": {
        "label": "роботы и ИИ",
        "query": ("робот", "android", "андроид", "искусственный интеллект"),
        "movie": ("робот", "robot", "android", "андроид", "искусственный интеллект"),
    },
    "detective": {
        "label": "тайна и расследование",
        "query": ("детектив", "тайна", "расслед", "убийств", "mystery"),
        "movie": ("детектив", "тайна", "расслед", "убийств", "mystery", "noir"),
    },
    "love": {
        "label": "романтика",
        "query": ("любов", "роман", "relationship", "romance"),
        "movie": ("любов", "роман", "relationship", "romance", "мелодрама"),
    },
}
SEMANTIC_TITLE_HINTS = [
    {
        "label": "фокус, иллюзия и разгадка",
        "groups": (("фокус", "маг", "иллюз", "трюк"), ("разгад", "тайн", "секрет", "сюжет", "обман")),
        "searches": ("The Prestige", "Престиж", "Now You See Me", "Иллюзия обмана", "The Illusionist"),
    },
    {
        "label": "супергерои, костюмы и грубый юмор",
        "groups": (("супергер", "геро", "комикс", "мутант"), ("желт", "красн", "мат", "руга", "пошл")),
        "searches": ("Deadpool Wolverine", "Deadpool", "Wolverine", "Дэдпул", "Росомаха"),
    },
    {
        "label": "побег из тюрьмы",
        "groups": (("побег", "сбеж", "бежать"), ("тюрьм", "заключ", "prison")),
        "searches": ("The Shawshank Redemption", "Побег из Шоушенка", "Escape Plan", "План побега"),
    },
    {
        "label": "роботы против монстров",
        "groups": (("робот", "мех", "егер", "гигант"), ("кайдз", "монстр", "годзил", "kaiju")),
        "searches": ("Pacific Rim", "Тихоокеанский рубеж", "Godzilla", "Transformers"),
    },
    {
        "label": "сны, подсознание и преступление",
        "groups": (("сон", "сны", "снах", "dream", "подсозн"), ("ограб", "краж", "вор", "heist")),
        "searches": ("Inception", "Начало"),
    },
    {
        "label": "мультфильм про кота",
        "groups": (("кот", "котик", "кошка", "кошк", "cat", "puss"), ("мульт", "анимац", "animation", "cartoon")),
        "searches": ("Кот сапогах", "Puss Boots", "talking cat", "cat", "кот"),
        "required_genres": ("мультфильм", "семейный"),
    },
]


def current_user_id():
    return session.get("user_id")


def admin_usernames():
    return {
        name.strip().lower()
        for name in os.environ.get("ADMIN_USERNAMES", DEFAULT_ADMIN_USERNAMES).split(",")
        if name.strip()
    }


def user_is_admin(row):
    return bool(row and row["username"].lower() in admin_usernames())


def public_user(row):
    if not row:
        return None
    return {"id": row["id"], "username": row["username"], "createdAt": row["created_at"], "isAdmin": user_is_admin(row)}


def get_user(connection, user_id):
    if not user_id:
        return None
    return connection.execute("SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)).fetchone()


def require_admin(connection):
    user = get_user(connection, current_user_id())
    if not user_is_admin(user):
        return None, (jsonify({"error": "Нужны права администратора. Войдите под логином admin или добавьте свой логин в ADMIN_USERNAMES."}), 403)
    return user, None


def limited_request(bucket, max_events=5, window_seconds=600):
    now = time()
    events = [stamp for stamp in MOVIE_REQUEST_LIMITS.get(bucket, []) if now - stamp < window_seconds]
    if len(events) >= max_events:
        MOVIE_REQUEST_LIMITS[bucket] = events
        return True
    events.append(now)
    MOVIE_REQUEST_LIMITS[bucket] = events
    return False


def genre_label(genre):
    return GENRE_LABELS.get(genre, genre)


def genre_variants(genre):
    return sorted(GENRE_ALIASES.get(genre.lower(), {genre}))


def pagination_meta(total, limit, offset):
    pages = max(1, math.ceil(total / limit)) if limit else 1
    page = min(pages, offset // limit + 1) if limit else 1
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "page": page,
        "pages": pages,
        "hasPrev": page > 1,
        "hasNext": page < pages,
    }


@app.before_request
def ensure_db():
    init_db()


@app.get("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:path>")
def static_files(path):
    target = ROOT / path
    if target.exists() and target.is_file():
        return send_from_directory(target.parent, target.name)
    return send_from_directory(ROOT, "index.html")


@app.post("/api/register")
def register():
    payload = request.get_json(force=True)
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if len(username) < 3:
        return jsonify({"error": "Логин должен быть не короче 3 символов"}), 400
    if len(password) < 4:
        return jsonify({"error": "Пароль должен быть не короче 4 символов"}), 400

    with get_connection() as connection:
        exists = connection.execute("SELECT id FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()
        if exists:
            return jsonify({"error": "Такой логин уже зарегистрирован"}), 409
        cursor = connection.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        connection.commit()
        session["user_id"] = cursor.lastrowid
        user = get_user(connection, cursor.lastrowid)
        return jsonify({"user": public_user(user), "ratings": []}), 201


@app.post("/api/login")
def login():
    payload = request.get_json(force=True)
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    with get_connection() as connection:
        user = connection.execute("SELECT * FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Неверный логин или пароль"}), 401
        session["user_id"] = user["id"]
        recommender = HybridRecommender(connection)
        return jsonify({"user": public_user(user), "ratings": recommender.user_ratings(user["id"])})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/session")
def session_info():
    with get_connection() as connection:
        user = get_user(connection, current_user_id())
        ratings = HybridRecommender(connection).user_ratings(user["id"]) if user else []
        return jsonify({"user": public_user(user), "ratings": ratings})


@app.get("/api/version")
def version():
    return jsonify({"version": APP_VERSION, "module": __name__, "root": str(ROOT)})


@app.get("/api/movies")
def movies():
    query = request.args.get("q", "")
    limit = max(1, min(int(request.args.get("limit", 12)), 30))
    page = max(1, int(request.args.get("page", 1)))
    offset = max(0, int(request.args.get("offset", (page - 1) * limit)))
    genre = (request.args.get("genre") or "").strip()
    year_from = request.args.get("yearFrom", type=int)
    year_to = request.args.get("yearTo", type=int)
    min_rating = request.args.get("minRating", type=float)
    has_poster = request.args.get("hasPoster") == "1"
    sort = request.args.get("sort", "weighted")
    with get_connection() as connection:
        recommender = HybridRecommender(connection)
        if query:
            found = recommender.search_movies(query, 500)
            if genre:
                variants = set(genre_variants(genre))
                found = [movie for movie in found if variants.intersection(movie.get("genres", []))]
            if year_from:
                found = [movie for movie in found if movie.get("year") and movie["year"] >= year_from]
            if year_to:
                found = [movie for movie in found if movie.get("year") and movie["year"] <= year_to]
            if min_rating:
                found = [movie for movie in found if movie.get("averageRating", 0) >= min_rating]
            if has_poster:
                found = [movie for movie in found if movie.get("poster")]
            total = len(found)
            return jsonify({"movies": found[offset : offset + limit], **pagination_meta(total, limit, offset)})
        clauses = []
        params = []
        if genre:
            variants = genre_variants(genre)
            clauses.append("(" + " OR ".join("m.genres LIKE ?" for _ in variants) + ")")
            params.extend(f"%{variant}%" for variant in variants)
        if year_from:
            clauses.append("m.year >= ?")
            params.append(year_from)
        if year_to:
            clauses.append("m.year <= ?")
            params.append(year_to)
        if min_rating:
            clauses.append("m.average_rating >= ?")
            params.append(min_rating)
        if has_poster:
            clauses.append("mm.poster IS NOT NULL AND mm.poster != ''")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = {
            "rating": "m.average_rating DESC, m.rating_count DESC",
            "year": "m.year DESC, m.weighted_score DESC",
            "popular": "m.rating_count DESC",
        }.get(sort, "m.weighted_score DESC")
        rows = connection.execute(
            f"""
            SELECT m.*, mm.poster, mm.palette, mm.tags, mm.description, mm.actors, mm.director
            FROM movies m
            JOIN movie_metadata mm ON mm.movie_id = m.id
            {where}
            ORDER BY {order_by}
            LIMIT ?
            OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        total = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM movies m
            JOIN movie_metadata mm ON mm.movie_id = m.id
            {where}
            """,
            tuple(params),
        ).fetchone()[0]
        from .db import rows_to_movies

        return jsonify({"movies": rows_to_movies(rows), **pagination_meta(total, limit, offset)})


@app.get("/api/genres")
def genres():
    with get_connection() as connection:
        rows = connection.execute("SELECT genres FROM movies").fetchall()
    values = sorted({genre_label(genre) for row in rows for genre in __import__("json").loads(row["genres"] or "[]")})
    return jsonify({"genres": values})


@app.post("/api/movie-requests")
def create_movie_request():
    bucket = f"{request.remote_addr}:{current_user_id() or 'guest'}"
    if limited_request(bucket):
        return jsonify({"error": "Слишком много заявок. Попробуйте позже."}), 429
    payload = request.get_json(force=True)
    title = (payload.get("title") or "").strip()
    note = (payload.get("note") or "").strip()
    year = payload.get("year")
    if len(title) < 2 or len(title) > 120 or not TITLE_RE.match(title):
        return jsonify({"error": "Название должно быть от 2 до 120 символов без подозрительных символов."}), 400
    if len(note) > 500:
        return jsonify({"error": "Комментарий слишком длинный."}), 400
    if year not in (None, ""):
        year = int(year)
        if year < 1888 or year > 2035:
            return jsonify({"error": "Год фильма выглядит некорректно."}), 400
    else:
        year = None
    with get_connection() as connection:
        exists = connection.execute("SELECT id FROM movies WHERE lower(title) = lower(?)", (title,)).fetchone()
        if exists:
            return jsonify({"ok": False, "message": "Такой фильм уже есть в базе.", "movieId": exists["id"]}), 409
        cursor = connection.execute(
            "INSERT INTO movie_requests (user_id, title, year, note) VALUES (?, ?, ?, ?)",
            (current_user_id(), title, year, note),
        )
        connection.commit()
    return jsonify({"ok": True, "requestId": cursor.lastrowid, "message": "Заявка сохранена. Фильм можно добавить после проверки через TMDb/MovieLens."}), 201


@app.get("/api/movie-requests")
def user_movie_requests():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"requests": []})
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT mr.*, u.username, m.title AS added_movie_title
            FROM movie_requests mr
            LEFT JOIN users u ON u.id = mr.user_id
            LEFT JOIN movies m ON m.id = mr.added_movie_id
            WHERE mr.user_id = ?
            ORDER BY mr.created_at DESC
            LIMIT 50
            """,
            (user_id,),
        ).fetchall()
        return jsonify({"requests": [movie_request_payload(row) for row in rows]})


@app.get("/api/admin/requests")
def admin_movie_requests():
    with get_connection() as connection:
        _, error = require_admin(connection)
        if error:
            return error
        status = (request.args.get("status") or "").strip()
        params = []
        where = ""
        if status:
            where = "WHERE mr.status = ?"
            params.append(status)
        rows = connection.execute(
            f"""
            SELECT mr.*, u.username, m.title AS added_movie_title
            FROM movie_requests mr
            LEFT JOIN users u ON u.id = mr.user_id
            LEFT JOIN movies m ON m.id = mr.added_movie_id
            {where}
            ORDER BY mr.created_at DESC
            LIMIT 80
            """,
            tuple(params),
        ).fetchall()
        return jsonify({"requests": [movie_request_payload(row) for row in rows]})


@app.patch("/api/admin/requests/<int:request_id>")
def admin_update_movie_request(request_id):
    payload = request.get_json(force=True)
    status = (payload.get("status") or "").strip()
    admin_note = (payload.get("adminNote") or "").strip()
    if status not in {"new", "reviewing", "added", "rejected"}:
        return jsonify({"error": "Некорректный статус заявки"}), 400
    if len(admin_note) > 700:
        return jsonify({"error": "Комментарий администратора слишком длинный"}), 400
    resolved_at = datetime.utcnow().isoformat() if status in {"added", "rejected"} else None
    with get_connection() as connection:
        _, error = require_admin(connection)
        if error:
            return error
        connection.execute(
            """
            UPDATE movie_requests
            SET status = ?, admin_note = ?, resolved_at = COALESCE(?, resolved_at)
            WHERE id = ?
            """,
            (status, admin_note, resolved_at, request_id),
        )
        connection.commit()
        row = connection.execute(
            """
            SELECT mr.*, u.username, m.title AS added_movie_title
            FROM movie_requests mr
            LEFT JOIN users u ON u.id = mr.user_id
            LEFT JOIN movies m ON m.id = mr.added_movie_id
            WHERE mr.id = ?
            """,
            (request_id,),
        ).fetchone()
        return jsonify({"request": movie_request_payload(row)})


@app.get("/api/admin/tmdb/search")
def admin_tmdb_search():
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        return jsonify({"error": "TMDB_API_KEY не задан в .env"}), 400
    query = (request.args.get("q") or "").strip()
    year = request.args.get("year", type=int)
    if len(query) < 2:
        return jsonify({"movies": []})
    with get_connection() as connection:
        _, error = require_admin(connection)
        if error:
            return error
    response = requests.get(
        f"{TMDB_BASE_URL}/search/movie",
        params={"api_key": api_key, "language": "ru-RU", "query": query, "year": year, "include_adult": "false"},
        timeout=15,
    )
    response.raise_for_status()
    movies = [tmdb_candidate_payload(item, {}, query) for item in response.json().get("results", [])[:8]]
    return jsonify({"movies": movies})


@app.post("/api/admin/movies/from-tmdb")
def admin_add_movie_from_tmdb():
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        return jsonify({"error": "TMDB_API_KEY не задан в .env"}), 400
    payload = request.get_json(force=True)
    tmdb_id = int(payload.get("tmdbId") or 0)
    request_id = payload.get("requestId")
    if not tmdb_id:
        return jsonify({"error": "Не передан tmdbId"}), 400
    with get_connection() as connection:
        _, error = require_admin(connection)
        if error:
            return error
        existing = connection.execute("SELECT id FROM movies WHERE tmdb_id = ?", (tmdb_id,)).fetchone()
        if existing:
            movie_id = existing["id"]
        else:
            movie_id = insert_tmdb_movie(connection, tmdb_id, api_key)
        if request_id:
            connection.execute(
                """
                UPDATE movie_requests
                SET status = 'added', added_movie_id = ?, admin_note = COALESCE(NULLIF(admin_note, ''), 'Добавлено через TMDb'), resolved_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (movie_id, request_id),
            )
        connection.commit()
        movie = HybridRecommender(connection).movie_details(movie_id, current_user_id())
        return jsonify({"ok": True, "movie": movie})


def movie_request_payload(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "year": row["year"],
        "note": row["note"],
        "status": row["status"],
        "adminNote": row["admin_note"],
        "createdAt": row["created_at"],
        "resolvedAt": row["resolved_at"],
        "username": row["username"] or "Гость",
        "addedMovieId": row["added_movie_id"],
        "addedMovieTitle": row["added_movie_title"],
    }


def insert_tmdb_movie(connection, tmdb_id, api_key):
    response = requests.get(
        f"{TMDB_BASE_URL}/movie/{tmdb_id}",
        params={"api_key": api_key, "language": "ru-RU", "append_to_response": "credits,keywords"},
        timeout=18,
    )
    response.raise_for_status()
    payload = response.json()
    movie_id = 10_000_000 + tmdb_id
    year = parse_tmdb_year(payload.get("release_date"))
    genres = [genre.get("name") for genre in payload.get("genres", []) if genre.get("name")]
    vote_average = float(payload.get("vote_average") or 0)
    average_rating = round(min(5.0, max(0.5, vote_average / 2)), 2) if vote_average else 3.5
    rating_count = int(payload.get("vote_count") or 0)
    weighted_score = round(average_rating + min(0.35, math.log1p(rating_count) / 40), 4)
    popularity = float(payload.get("popularity") or rating_count or 1)
    poster = f"{TMDB_IMAGE_URL}{payload['poster_path']}" if payload.get("poster_path") else None
    credits = payload.get("credits") or {}
    director = next((person.get("name") for person in credits.get("crew", []) if person.get("job") == "Director"), None)
    actors = [person.get("name") for person in credits.get("cast", [])[:6] if person.get("name")]
    keywords = [item.get("name") for item in (payload.get("keywords") or {}).get("keywords", [])[:12] if item.get("name")]
    tags = [*(genres[:4]), *keywords, payload.get("original_title") or ""]
    palette = ["#d33ed5", "#111827"]
    connection.execute(
        """
        INSERT INTO movies (id, title, year, genres, average_rating, rating_count, weighted_score, popularity, tmdb_id, imdb_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            movie_id,
            payload.get("title") or payload.get("original_title") or f"TMDb {tmdb_id}",
            year,
            json.dumps(genres, ensure_ascii=False),
            average_rating,
            rating_count,
            weighted_score,
            popularity,
            tmdb_id,
            (payload.get("imdb_id") or "").replace("tt", "") or None,
        ),
    )
    connection.execute(
        """
        INSERT INTO movie_metadata (movie_id, poster, palette, tags, description, actors, director, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'tmdb')
        """,
        (
            movie_id,
            poster,
            json.dumps(palette, ensure_ascii=False),
            json.dumps([tag for tag in tags if tag], ensure_ascii=False),
            payload.get("overview") or "Фильм добавлен из TMDb по заявке пользователя.",
            json.dumps(actors, ensure_ascii=False),
            director,
        ),
    )
    return movie_id


@app.get("/api/support/thread")
def support_thread():
    with get_connection() as connection:
        thread_id = ensure_support_thread(connection)
        return jsonify({"thread": support_thread_payload(connection, thread_id), "messages": support_messages(connection, thread_id)})


@app.post("/api/support/messages")
def support_send_message():
    payload = request.get_json(force=True)
    body = (payload.get("body") or "").strip()
    if len(body) < 1 or len(body) > 1000:
        return jsonify({"error": "Сообщение должно быть от 1 до 1000 символов"}), 400
    with get_connection() as connection:
        thread_id = ensure_support_thread(connection)
        connection.execute(
            "INSERT INTO support_messages (thread_id, user_id, sender_role, body) VALUES (?, ?, 'user', ?)",
            (thread_id, current_user_id(), body),
        )
        connection.execute("UPDATE support_threads SET updated_at = CURRENT_TIMESTAMP, status = 'open' WHERE id = ?", (thread_id,))
        connection.commit()
        return jsonify({"thread": support_thread_payload(connection, thread_id), "messages": support_messages(connection, thread_id)})


@app.get("/api/admin/support/threads")
def admin_support_threads():
    with get_connection() as connection:
        _, error = require_admin(connection)
        if error:
            return error
        rows = connection.execute(
            """
            SELECT st.*, u.username,
                   (SELECT body FROM support_messages sm WHERE sm.thread_id = st.id ORDER BY sm.created_at DESC, sm.id DESC LIMIT 1) AS last_message,
                   (SELECT COUNT(*) FROM support_messages sm WHERE sm.thread_id = st.id) AS message_count
            FROM support_threads st
            LEFT JOIN users u ON u.id = st.user_id
            ORDER BY st.updated_at DESC
            LIMIT 80
            """
        ).fetchall()
        return jsonify({"threads": [support_thread_payload(connection, row["id"], row) for row in rows]})


@app.get("/api/admin/support/threads/<int:thread_id>/messages")
def admin_support_messages(thread_id):
    with get_connection() as connection:
        _, error = require_admin(connection)
        if error:
            return error
        return jsonify({"thread": support_thread_payload(connection, thread_id), "messages": support_messages(connection, thread_id)})


@app.post("/api/admin/support/threads/<int:thread_id>/messages")
def admin_support_reply(thread_id):
    payload = request.get_json(force=True)
    body = (payload.get("body") or "").strip()
    if len(body) < 1 or len(body) > 1000:
        return jsonify({"error": "Сообщение должно быть от 1 до 1000 символов"}), 400
    with get_connection() as connection:
        admin, error = require_admin(connection)
        if error:
            return error
        connection.execute(
            "INSERT INTO support_messages (thread_id, user_id, sender_role, body) VALUES (?, ?, 'admin', ?)",
            (thread_id, admin["id"], body),
        )
        status = (payload.get("status") or "open").strip()
        if status not in {"open", "closed"}:
            status = "open"
        connection.execute("UPDATE support_threads SET updated_at = CURRENT_TIMESTAMP, status = ? WHERE id = ?", (status, thread_id))
        connection.commit()
        return jsonify({"thread": support_thread_payload(connection, thread_id), "messages": support_messages(connection, thread_id)})


def ensure_support_thread(connection):
    user_id = current_user_id()
    if user_id:
        row = connection.execute(
            "SELECT id FROM support_threads WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row:
            ensure_support_welcome(connection, row["id"])
            return row["id"]
        cursor = connection.execute("INSERT INTO support_threads (user_id) VALUES (?)", (user_id,))
        connection.commit()
        ensure_support_welcome(connection, cursor.lastrowid)
        return cursor.lastrowid
    thread_id = session.get("support_thread_id")
    if thread_id and connection.execute("SELECT id FROM support_threads WHERE id = ?", (thread_id,)).fetchone():
        ensure_support_welcome(connection, thread_id)
        return thread_id
    cursor = connection.execute("INSERT INTO support_threads (guest_name) VALUES ('Гость')")
    connection.commit()
    session["support_thread_id"] = cursor.lastrowid
    ensure_support_welcome(connection, cursor.lastrowid)
    return cursor.lastrowid


def ensure_support_welcome(connection, thread_id):
    exists = connection.execute("SELECT id FROM support_messages WHERE thread_id = ? LIMIT 1", (thread_id,)).fetchone()
    if exists:
        return
    connection.execute(
        """
        INSERT INTO support_messages (thread_id, user_id, sender_role, body)
        VALUES (?, NULL, 'admin', 'Здравствуйте! Столкнулись с проблемой или нужна помощь с рекомендациями? Напишите сюда, и мы подскажем.')
        """,
        (thread_id,),
    )
    connection.execute("UPDATE support_threads SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (thread_id,))
    connection.commit()


def support_thread_payload(connection, thread_id, row=None):
    row = row or connection.execute(
        """
        SELECT st.*, u.username,
               (SELECT body FROM support_messages sm WHERE sm.thread_id = st.id ORDER BY sm.created_at DESC, sm.id DESC LIMIT 1) AS last_message,
               (SELECT COUNT(*) FROM support_messages sm WHERE sm.thread_id = st.id) AS message_count
        FROM support_threads st
        LEFT JOIN users u ON u.id = st.user_id
        WHERE st.id = ?
        """,
        (thread_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "username": row["username"] or row["guest_name"] or "Гость",
        "subject": row["subject"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "lastMessage": row["last_message"] if "last_message" in row.keys() else "",
        "messageCount": row["message_count"] if "message_count" in row.keys() else 0,
    }


def support_messages(connection, thread_id):
    rows = connection.execute(
        """
        SELECT sm.*, u.username
        FROM support_messages sm
        LEFT JOIN users u ON u.id = sm.user_id
        WHERE sm.thread_id = ?
        ORDER BY sm.created_at ASC, sm.id ASC
        """,
        (thread_id,),
    ).fetchall()
    messages = [
        {
            "id": row["id"],
            "threadId": row["thread_id"],
            "senderRole": row["sender_role"],
            "username": row["username"] or ("Администратор" if row["sender_role"] == "admin" else "Гость"),
            "body": row["body"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]
    if not messages or messages[0]["senderRole"] != "admin":
        messages.insert(
            0,
            {
                "id": 0,
                "threadId": thread_id,
                "senderRole": "admin",
                "username": "Поддержка",
                "body": "Здравствуйте! Столкнулись с проблемой или нужна помощь с рекомендациями? Напишите сюда, и мы подскажем.",
                "createdAt": "",
            },
        )
    return messages


@app.get("/api/movies/<int:movie_id>")
def movie_details(movie_id):
    with get_connection() as connection:
        movie = HybridRecommender(connection).movie_details(movie_id, current_user_id())
        if not movie:
            return jsonify({"error": "Фильм не найден"}), 404
        return jsonify({"movie": movie})


@app.post("/api/ratings")
def save_rating():
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "Для сохранения оценки нужно войти"}), 401
    payload = request.get_json(force=True)
    movie_id = int(payload.get("movieId"))
    rating = float(payload.get("rating"))
    if rating < 0.5 or rating > 5:
        return jsonify({"error": "Оценка должна быть от 0.5 до 5"}), 400
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO ratings (user_id, movie_id, rating)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, movie_id)
            DO UPDATE SET rating = excluded.rating, updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, movie_id, rating),
        )
        connection.commit()
        recommender = HybridRecommender(connection)
        return jsonify({"ratings": recommender.user_ratings(user_id)})


@app.delete("/api/ratings/<int:movie_id>")
def delete_rating(movie_id):
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "Для удаления оценки нужно войти"}), 401
    with get_connection() as connection:
        connection.execute("DELETE FROM ratings WHERE user_id = ? AND movie_id = ?", (user_id, movie_id))
        connection.commit()
        return jsonify({"ratings": HybridRecommender(connection).user_ratings(user_id)})


@app.get("/api/recommendations")
def recommendations():
    alpha = max(0.0, min(1.0, float(request.args.get("alpha", 0.7))))
    limit = min(int(request.args.get("limit", 10)), 30)
    with get_connection() as connection:
        recommender = HybridRecommender(connection)
        user_id = current_user_id()
        if not user_id:
            return jsonify({"recommendations": recommender.recommend(0, alpha, limit) if False else recommender._cold_start(limit)})
        return jsonify({"recommendations": recommender.recommend(user_id, alpha, limit)})


@app.get("/api/search/semantic")
def semantic_search():
    query = request.args.get("q", "")
    if not query.strip():
        return jsonify({"movies": []})
    with get_connection() as connection:
        recommender = HybridRecommender(connection)
        query_analysis, parse_mode, parse_error = understand_semantic_query(query)
        search_text = semantic_search_text(query, query_analysis)
        embedding_error = None
        try:
            embedded = embedding_search(connection, recommender, search_text, limit=60)
        except Exception as error:
            embedded = None
            embedding_error = str(error)
        if embedded is not None:
            provider = embedded[0].get("embeddingProvider", "embeddings") if embedded else "embeddings"
            content = recommender.semantic_search(expand_query(search_text), limit=60)
            hinted = semantic_hint_candidates(recommender, query) + semantic_facet_candidates(recommender, query_analysis)
            merged = rerank_semantic_results(query, embedded, content, hinted)
            reranked, rerank_mode, rerank_error = maybe_llm_rerank(query, merged[:12])
            return jsonify(
                {
                    "mode": f"{provider}_embeddings",
                    "parseMode": parse_mode,
                    "parseError": parse_error,
                    "rerankMode": rerank_mode,
                    "rerankError": rerank_error,
                    "embeddingError": embedding_error,
                    "queryAnalysis": query_analysis,
                    "expandedQuery": expand_query(search_text),
                    "movies": reranked[:10],
                    "externalCandidates": tmdb_external_candidates(query, query_analysis, recommender),
                }
            )
        hinted = semantic_hint_candidates(recommender, query) + semantic_facet_candidates(recommender, query_analysis)
        fallback = rerank_semantic_results(query, [], recommender.semantic_search(expand_query(search_text), limit=60), hinted)
        reranked, rerank_mode, rerank_error = maybe_llm_rerank(query, fallback[:12])
        return jsonify(
            {
                "mode": "tfidf_fallback",
                "parseMode": parse_mode,
                "parseError": parse_error,
                "rerankMode": rerank_mode,
                "rerankError": rerank_error,
                "embeddingError": embedding_error,
                "queryAnalysis": query_analysis,
                "expandedQuery": expand_query(search_text),
                "movies": reranked[:10],
                "externalCandidates": tmdb_external_candidates(query, query_analysis, recommender),
            }
        )


def rerank_semantic_results(query, embedded, content, hinted=None):
    merged = {}
    for index, movie in enumerate(hinted or []):
        hint_priority = float(movie.get("hintPriority", index))
        existing = merged.get(movie["id"])
        if existing and existing.get("_hint", 0) >= movie.get("hintScore", 1.0):
            continue
        merged[movie["id"]] = {
            **movie,
            "_embedding": 0.0,
            "_content": 0.0,
            "_hint": max(0.35, float(movie.get("hintScore", 1.0)) - hint_priority * 0.08 - index * 0.01),
            "_rank": index,
        }
    for index, movie in enumerate(embedded):
        normalized_embedding = max(0.0, (float(movie.get("semanticScore") or 0) + 1) / 2)
        entry = merged.get(movie["id"], {**movie, "_content": 0.0, "_hint": 0.0, "_rank": index})
        merged[movie["id"]] = {
            **entry,
            **movie,
            "_embedding": normalized_embedding,
            "_hint": entry.get("_hint", 0.0),
            "_rank": min(entry.get("_rank", index), index),
        }
    for index, movie in enumerate(content):
        entry = merged.get(movie["id"], {**movie, "_embedding": 0.0, "_hint": 0.0, "_rank": 100 + index})
        entry["_content"] = max(entry.get("_content", 0.0), 1 - index / max(1, len(content)))
        entry["semanticScore"] = max(float(entry.get("semanticScore") or 0), float(movie.get("semanticScore") or 0))
        merged[movie["id"]] = entry
    results = []
    for item in merged.values():
        concept_matches = semantic_concept_matches(query, item)
        boost = semantic_intent_boost(concept_matches)
        combined = item["_embedding"] * 0.26 + item["_content"] * 0.3 + item["_hint"] * 1.08 + item.get("weightedScore", 0) / 100 + boost
        item["semanticScore"] = round(combined, 4)
        item["matchedConcepts"] = [concept["label"] for concept in concept_matches]
        item["reason"] = semantic_reason(item, concept_matches, item.get("hintLabel"))
        item.pop("_embedding", None)
        item.pop("_content", None)
        item.pop("_hint", None)
        item.pop("_rank", None)
        results.append(item)
    results.sort(key=lambda movie: (movie["semanticScore"], movie.get("weightedScore", 0)), reverse=True)
    return results


def semantic_concept_matches(query, movie):
    normalized = query.lower().replace("ё", "е")
    text = " ".join(
        [
            movie.get("title", ""),
            movie.get("description", ""),
            " ".join(movie.get("tags", [])),
            " ".join(movie.get("genres", [])),
        ]
    ).lower().replace("ё", "е")
    matches = []
    matched_concepts = []
    for concept in SEMANTIC_CONCEPTS.values():
        query_match = any(term in normalized for term in concept["query"])
        movie_match = any(term in text for term in concept["movie"])
        if query_match and movie_match:
            matched_concepts.append(concept)
            matches.append(concept)
    return matches


def understand_semantic_query(query):
    normalized = normalize_semantic_text(query)
    if normalized in QUERY_PARSE_CACHE:
        cached = QUERY_PARSE_CACHE[normalized]
        return dict(cached["analysis"]), cached["mode"], cached.get("error")
    provider = os.environ.get("SEMANTIC_RERANK_PROVIDER", "").lower()
    if provider in {"ollama", "qwen"}:
        analysis, error = ollama_parse_query(query)
        if analysis:
            QUERY_PARSE_CACHE[normalized] = {"analysis": analysis, "mode": "ollama", "error": error}
            return dict(analysis), "ollama", error
    analysis = heuristic_query_analysis(query)
    QUERY_PARSE_CACHE[normalized] = {"analysis": analysis, "mode": "heuristic", "error": None}
    return analysis, "heuristic", None


def ollama_parse_query(query):
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    prompt = (
        "Разбери пользовательский запрос о фильме в JSON. "
        "Нужны признаки для поиска по базе фильмов, а не ответ пользователю. "
        "Верни строго JSON с ключами: genres, objects, characters, visual, actions, themes, "
        "english_terms, possible_titles, negative_terms. Все значения - массивы строк. "
        "Добавляй английские поисковые термины и вероятные оригинальные названия, если они напрашиваются. "
        "Пример: 'мультфильм про рыжего котика' -> english_terms ['animation','cat','orange cat','talking cat'], "
        "possible_titles ['Garfield','Puss in Boots'].\nЗапрос: "
        + query
    )
    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "keep_alive": "10m",
                "options": {"temperature": 0, "num_predict": 220},
            },
            timeout=35,
        )
        response.raise_for_status()
        raw = response.json().get("message", {}).get("content", "{}")
        return normalize_query_analysis(json.loads(raw)), None
    except Exception as error:
        return None, str(error)


def normalize_query_analysis(value):
    keys = ("genres", "objects", "characters", "visual", "actions", "themes", "english_terms", "possible_titles", "negative_terms")
    analysis = {}
    for key in keys:
        raw_items = value.get(key, []) if isinstance(value, dict) else []
        if isinstance(raw_items, str):
            raw_items = [raw_items]
        clean = []
        for item in raw_items or []:
            text = str(item).strip()
            if text and text.lower() not in {entry.lower() for entry in clean}:
                clean.append(text[:80])
        analysis[key] = clean[:12]
    return analysis


def heuristic_query_analysis(query):
    normalized = normalize_semantic_text(query)
    analysis = normalize_query_analysis({})
    keyword_map = {
        "genres": {
            "мульт": "мультфильм",
            "анимац": "мультфильм",
            "cartoon": "мультфильм",
            "робот": "фантастика",
            "космос": "фантастика",
            "супергер": "боевик",
            "тюрьм": "криминал",
        },
        "objects": {
            "кот": "кот",
            "котик": "кот",
            "кошк": "кошка",
            "робот": "робот",
            "кайдз": "кайдзю",
            "фокус": "фокус",
            "тюрьм": "тюрьма",
        },
        "visual": {
            "рыж": "рыжий",
            "оранж": "оранжевый",
            "желт": "желтый",
            "красн": "красный",
        },
        "actions": {
            "побег": "побег",
            "сбеж": "побег",
            "ограб": "ограбление",
            "разгад": "расследование",
        },
        "themes": {
            "сон": "сны",
            "сны": "сны",
            "маг": "магия",
            "фокус": "иллюзия",
            "супергер": "супергерои",
        },
    }
    english_terms = {
        "кот": ["cat", "talking cat"],
        "котик": ["cat", "orange cat", "talking cat"],
        "кошк": ["cat"],
        "рыж": ["orange", "orange cat"],
        "мульт": ["animation", "cartoon", "family"],
        "робот": ["robot", "giant robot"],
        "кайдз": ["kaiju", "monster"],
        "побег": ["escape", "prison escape"],
        "тюрьм": ["prison"],
        "сон": ["dream"],
        "сны": ["dream"],
        "ограб": ["heist"],
    }
    possible_titles = {
        "кот": ["Puss in Boots", "Garfield"],
        "котик": ["Puss in Boots", "Garfield"],
        "рыж": ["Garfield", "Puss in Boots"],
    }
    for target, rules in keyword_map.items():
        for needle, value in rules.items():
            if needle in normalized:
                analysis[target].append(value)
    for needle, values in english_terms.items():
        if needle in normalized:
            analysis["english_terms"].extend(values)
    for needle, values in possible_titles.items():
        if needle in normalized:
            analysis["possible_titles"].extend(values)
    return normalize_query_analysis(analysis)


def semantic_search_text(query, analysis):
    parts = [query]
    for key in ("genres", "objects", "characters", "visual", "actions", "themes", "english_terms", "possible_titles"):
        parts.extend(expand_search_terms(analysis.get(key, [])))
    return " ".join(parts)


def semantic_facet_candidates(recommender, analysis):
    terms_by_group = {
        "possible_titles": analysis.get("possible_titles", []),
        "genres": expand_search_terms(analysis.get("genres", [])),
        "objects": expand_search_terms(analysis.get("objects", []) + analysis.get("characters", [])),
        "visual": expand_search_terms(analysis.get("visual", [])),
        "actions": expand_search_terms(analysis.get("actions", [])),
        "themes": expand_search_terms(analysis.get("themes", [])),
        "english_terms": expand_search_terms(analysis.get("english_terms", [])),
    }
    candidates = []
    for movie in recommender.movies:
        score, reasons = facet_match_score(movie, terms_by_group)
        if score <= 0:
            continue
        candidates.append(
            {
                **movie,
                "hintLabel": "понятые признаки: " + ", ".join(reasons[:3]),
                "hintPriority": 0 if score >= 1.2 else 2,
                "hintScore": min(1.08, 0.28 + score),
            }
        )
    candidates.sort(key=lambda movie: (movie.get("hintScore", 0), movie.get("weightedScore", 0)), reverse=True)
    return candidates[:40]


def expand_search_terms(terms):
    expanded = []
    for term in terms or []:
        clean = str(term).strip()
        if not clean:
            continue
        variants = [clean, *SEARCH_TERM_ALIASES.get(clean.lower(), ())]
        for variant in variants:
            if variant and variant.lower() not in {item.lower() for item in expanded}:
                expanded.append(variant)
    return expanded


def facet_match_score(movie, terms_by_group):
    title_tokens = set(normalize_semantic_text(movie.get("title", "")).split())
    title_text = normalize_semantic_text(movie.get("title", ""))
    genre_text = normalize_semantic_text(" ".join(movie.get("genres", [])))
    tag_text = normalize_semantic_text(" ".join(movie.get("tags", [])))
    description_text = normalize_semantic_text(movie.get("description", ""))
    full_text = " ".join([normalize_semantic_text(movie.get("title", "")), genre_text, tag_text, description_text])
    score = 0.0
    reasons = []
    score += title_match_score(terms_by_group["possible_titles"], title_text + " " + tag_text, 0.8, reasons)
    score += entity_phrase_score(
        terms_by_group["objects"] + terms_by_group["visual"],
        title_text + " " + tag_text,
        0.7,
        reasons,
    )
    score += group_match_score(terms_by_group["genres"], genre_text, 0.22, reasons, "жанр")
    score += group_match_score(terms_by_group["objects"], full_text, 0.22, reasons, "объект")
    score += group_match_score(terms_by_group["english_terms"], full_text, 0.2, reasons, "англ. тег")
    score += group_match_score(terms_by_group["actions"], full_text, 0.18, reasons, "действие")
    score += group_match_score(terms_by_group["themes"], full_text, 0.18, reasons, "тема")
    score += group_match_score(terms_by_group["visual"], full_text, 0.14, reasons, "визуальный признак")
    if terms_by_group["possible_titles"]:
        tag_tokens = set(tag_text.split())
        for title in terms_by_group["possible_titles"]:
            tokens = [token for token in normalize_semantic_text(title).split() if token not in HINT_STOP_TOKENS]
            if tokens and all(token in title_tokens or token in tag_tokens for token in tokens):
                score += 0.85
                break
            if tokens and normalize_semantic_text(title) in title_text:
                score += 0.85
                break
    return score, reasons


def title_match_score(terms, text, weight, reasons):
    score = 0.0
    text_tokens = set(text.split())
    for term in terms:
        tokens = [token for token in normalize_semantic_text(term).split() if token not in HINT_STOP_TOKENS]
        if not tokens:
            continue
        matches = sum(1 for token in tokens if token in text_tokens)
        if matches == len(tokens):
            score += weight
            reason = f"название: {term}"
            if reason not in reasons:
                reasons.append(reason)
    return min(score, weight * 2)


def entity_phrase_score(terms, text, weight, reasons):
    score = 0.0
    text_tokens = set(text.split())
    for term in terms:
        tokens = [token for token in normalize_semantic_text(term).split() if token not in HINT_STOP_TOKENS]
        if len(tokens) < 2:
            continue
        if all(token in text_tokens for token in tokens):
            score += weight
            reason = f"точный объект: {term}"
            if reason not in reasons:
                reasons.append(reason)
    return min(score, weight * 2)


def group_match_score(terms, text, weight, reasons, label):
    score = 0.0
    text_tokens = set(text.split())
    for term in terms:
        tokens = [token for token in normalize_semantic_text(term).split() if token not in HINT_STOP_TOKENS]
        if not tokens:
            continue
        matches = sum(1 for token in tokens if token in text_tokens)
        needed = 1 if len(tokens) == 1 else max(2, math.ceil(len(tokens) * 0.6))
        if matches >= needed:
            score += weight * (matches / len(tokens))
            reason = f"{label}: {term}"
            if reason not in reasons:
                reasons.append(reason)
    return min(score, weight * 2.5)


def tmdb_external_candidates(query, analysis, recommender):
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        return []
    existing_tmdb = {movie.get("tmdbId") or movie.get("tmdb_id") for movie in recommender.movies if movie.get("tmdbId") or movie.get("tmdb_id")}
    search_queries = []
    search_queries.extend(analysis.get("possible_titles", []))
    search_queries.extend(compound_tmdb_queries(analysis))
    search_queries.append(query)
    candidates = {}
    for search_query in search_queries:
        normalized = normalize_semantic_text(search_query)
        if not normalized or normalized in TMDB_SEARCH_CACHE and TMDB_SEARCH_CACHE[normalized] == []:
            continue
        try:
            results = TMDB_SEARCH_CACHE.get(normalized)
            if results is None:
                response = requests.get(
                    f"{TMDB_BASE_URL}/search/movie",
                    params={
                        "api_key": api_key,
                        "language": "ru-RU",
                        "query": search_query,
                        "include_adult": "false",
                        "page": 1,
                    },
                    timeout=8,
                )
                response.raise_for_status()
                results = response.json().get("results", [])[:5]
                TMDB_SEARCH_CACHE[normalized] = results
            for item in results:
                tmdb_id = item.get("id")
                if not tmdb_id or tmdb_id in existing_tmdb or tmdb_id in candidates:
                    continue
                candidates[tmdb_id] = tmdb_candidate_payload(item, analysis, search_query)
        except Exception:
            continue
    ranked = sorted(candidates.values(), key=lambda item: item["matchScore"], reverse=True)
    return ranked[:4]


def compound_tmdb_queries(analysis):
    values = []
    english = analysis.get("english_terms", [])
    genres = analysis.get("genres", [])
    objects = analysis.get("objects", []) + analysis.get("characters", [])
    visual = analysis.get("visual", [])
    for left in visual[:3]:
        for right in objects[:3]:
            values.append(f"{left} {right}")
    for term in english[:8]:
        values.append(term)
    for genre in genres[:3]:
        for obj in objects[:3]:
            values.append(f"{genre} {obj}")
    return values[:12]


def tmdb_candidate_payload(item, analysis, source_query):
    title = item.get("title") or item.get("original_title") or "TMDb"
    year = parse_tmdb_year(item.get("release_date"))
    overview = item.get("overview") or ""
    text = normalize_semantic_text(" ".join([title, item.get("original_title") or "", overview]))
    score = 0.15 + min(float(item.get("popularity") or 0) / 120, 0.25)
    reasons = []
    for key, label in (
        ("possible_titles", "возможное название"),
        ("english_terms", "английский признак"),
        ("objects", "объект"),
        ("characters", "персонаж"),
        ("visual", "визуальный признак"),
        ("themes", "тема"),
    ):
        for term in analysis.get(key, []):
            tokens = [token for token in normalize_semantic_text(term).split() if token not in HINT_STOP_TOKENS]
            if tokens and any(token in text for token in tokens):
                score += 0.16
                reasons.append(f"{label}: {term}")
                break
    return {
        "tmdbId": item.get("id"),
        "title": title,
        "year": year,
        "poster": f"{TMDB_IMAGE_URL}{item['poster_path']}" if item.get("poster_path") else None,
        "description": overview,
        "matchScore": round(score, 4),
        "sourceQuery": source_query,
        "reason": ", ".join(reasons[:3]) or "Найдено во внешнем поиске TMDb",
    }


def parse_tmdb_year(value):
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def semantic_hint_candidates(recommender, query):
    hints = matching_title_hints(query)
    if not hints:
        return []
    candidates = {}
    for hint in hints:
        for movie, priority in token_scan_movies(recommender.movies, hint["searches"]):
            if not movie_matches_hint(movie, hint):
                continue
            candidate = {
                **movie,
                "hintLabel": hint["label"],
                "hintPriority": min(priority, candidates.get(movie["id"], {}).get("hintPriority", priority)),
                "hintScore": 1.45,
            }
            candidates[movie["id"]] = candidate
    return sorted(
        candidates.values(),
        key=lambda movie: (movie.get("hintPriority", 99), -movie.get("weightedScore", 0)),
    )[:24]


def movie_matches_hint(movie, hint):
    required_genres = set(hint.get("required_genres") or [])
    if required_genres and not required_genres.intersection(movie.get("genres", [])):
        return False
    return True


def matching_title_hints(query):
    normalized = normalize_semantic_text(query)
    query_tokens = set(normalized.split())
    matches = []
    for hint in SEMANTIC_TITLE_HINTS:
        if all(any(term_matches_query(term, normalized, query_tokens) for term in group) for group in hint["groups"]):
            matches.append(hint)
    return matches


def term_matches_query(term, normalized_query, query_tokens):
    tokens = [token for token in normalize_semantic_text(term).split() if token not in HINT_STOP_TOKENS]
    if not tokens:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        return token in query_tokens or (len(token) >= 5 and any(part.startswith(token) for part in query_tokens))
    return all(token in query_tokens or token in normalized_query for token in tokens)


def token_scan_movies(movies, searches):
    found = []
    for priority, search in enumerate(searches):
        tokens = [
            token
            for token in normalize_semantic_text(search).split()
            if len(token) >= 3 and token not in HINT_STOP_TOKENS
        ]
        if not tokens:
            continue
        for movie in movies:
            text_tokens = set(
                normalize_semantic_text(
                    " ".join(
                        [
                            movie.get("title", ""),
                            " ".join(movie.get("tags", [])),
                        ]
                    )
                ).split()
            )
            if all(token in text_tokens for token in tokens):
                found.append((movie, priority))
    return found


def normalize_semantic_text(value):
    return re.sub(r"[^a-zа-я0-9]+", " ", str(value).lower().replace("ё", "е")).strip()


def semantic_intent_boost(matched_concepts):
    boost = 0.0
    if matched_concepts:
        boost += min(0.42, 0.16 * len(matched_concepts))
    if len(matched_concepts) >= 2:
        boost += 0.18
    return boost


def semantic_reason(movie, concept_matches, hint_label=None):
    if hint_label:
        return f"Подсказка запроса: {hint_label}"
    if concept_matches:
        labels = ", ".join(concept["label"] for concept in concept_matches[:3])
        return f"Совпало по смыслу: {labels}"
    if movie.get("semanticScore", 0) > 0:
        return "Похоже по embeddings и описанию"
    return "Похоже по жанрам, тегам и популярности"


def maybe_llm_rerank(query, movies):
    provider = os.environ.get("SEMANTIC_RERANK_PROVIDER", "").lower()
    if provider not in {"gpt", "openai", "ollama", "qwen"}:
        return movies, "local", None
    cache_key = llm_cache_key(provider, query, movies)
    cached = LLM_RERANK_CACHE.get(cache_key)
    if cached:
        return [dict(movie) for movie in cached["movies"]], cached["mode"], None
    if provider in {"ollama", "qwen"}:
        reranked, mode, error = ollama_rerank(query, movies)
    else:
        reranked, mode, error = openai_rerank(query, movies)
    if error is None and mode != "local":
        LLM_RERANK_CACHE[cache_key] = {"mode": mode, "movies": [dict(movie) for movie in reranked]}
        if len(LLM_RERANK_CACHE) > 80:
            LLM_RERANK_CACHE.pop(next(iter(LLM_RERANK_CACHE)))
    return reranked, mode, error


def llm_cache_key(provider, query, movies):
    model = os.environ.get("OLLAMA_MODEL" if provider in {"ollama", "qwen"} else "OPENAI_RERANK_MODEL", "")
    movie_ids = tuple(movie["id"] for movie in movies)
    return provider, model, normalize_semantic_text(query), movie_ids


def rerank_prompt_payload(query, movies):
    return {
        "query": query,
        "movies": [
            {
                "id": movie["id"],
                "title": movie["title"],
                "year": movie.get("year"),
                "genres": movie.get("genres", []),
                "description": (movie.get("description") or "")[:600],
                "matchedConcepts": movie.get("matchedConcepts", []),
                "retrievalReason": movie.get("reason", ""),
                "baseScore": movie.get("semanticScore", 0),
            }
            for movie in movies
        ],
    }


def apply_llm_order(movies, order, mode):
    by_id = {movie["id"]: movie for movie in movies}
    normalized_order = []
    for movie_id in order:
        try:
            normalized_order.append(int(movie_id))
        except (TypeError, ValueError):
            continue
    order_rank = {movie_id: index for index, movie_id in enumerate(normalized_order)}
    for movie in movies:
        rank = order_rank.get(movie["id"])
        llm_boost = 0.0 if rank is None else max(0.0, 0.28 - rank * 0.025)
        movie["llmScore"] = round(float(movie.get("semanticScore") or 0) + llm_boost, 4)
    reranked = sorted(movies, key=lambda movie: (movie["llmScore"], movie.get("weightedScore", 0)), reverse=True)
    for index, movie in enumerate(reranked):
        movie["llmRank"] = index + 1
        movie["rerankProvider"] = mode
    return reranked


def ollama_rerank(query, movies):
    if not movies:
        return movies, "local", "Нет кандидатов для локального rerank."
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
    prompt = (
        "Ты ранжируешь фильмы по смыслу пользовательского описания. "
        "Верни только JSON без markdown и пояснений: {\"ids\":[movie_id...]}. "
        "Ставь выше фильмы, где совпадают сюжет, персонажи и ситуация из запроса. "
        "Не выбирай фильм только потому, что одно слово совпало с названием. "
        "Если retrievalReason говорит о подсказке запроса, учитывай это как сильный сигнал.\n\n"
        + json.dumps(rerank_prompt_payload(query, movies), ensure_ascii=False)
    )
    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "keep_alive": "10m",
                "options": {"temperature": 0, "num_predict": 128},
            },
            timeout=45,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "{}")
        order = json.loads(content).get("ids", [])
        return apply_llm_order(movies, order, "ollama"), "ollama", None
    except Exception as error:
        return movies, "local", f"Ollama/Qwen rerank недоступен: {error}"


def openai_rerank(query, movies):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not movies:
        return movies, "local", "OPENAI_API_KEY не задан или нет кандидатов для rerank."
    try:
        payload = {
            "model": os.environ.get("OPENAI_RERANK_MODEL", "gpt-4o-mini"),
            "messages": [
                {
                    "role": "system",
                    "content": "Ты ранжируешь фильмы по смыслу пользовательского описания. Верни JSON: {\"ids\":[movie_id...]} без пояснений.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        rerank_prompt_payload(query, movies),
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=25,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        order = json.loads(content).get("ids", [])
        return apply_llm_order(movies, order, "gpt"), "gpt", None
    except Exception as error:
        return movies, "local", f"GPT rerank недоступен: {error}"


@app.post("/api/embeddings/rebuild")
def embeddings_rebuild():
    with get_connection() as connection:
        try:
            limit = min(int(request.args.get("limit", 80)), 1500)
            provider = request.args.get("provider")
            return jsonify(rebuild_movie_embeddings(connection, HybridRecommender(connection), limit=limit, provider=provider))
        except Exception as error:
            return jsonify({"ok": False, "message": str(error)}), 502


@app.get("/api/recommendations/explain/<int:movie_id>")
def recommendation_explain(movie_id):
    user_id = current_user_id()
    if not user_id:
        return jsonify({"error": "Для объяснения рекомендации нужно войти"}), 401
    with get_connection() as connection:
        recommender = HybridRecommender(connection)
        recs = recommender.recommend(user_id, float(request.args.get("alpha", 0.65)), 30)
        target = next((movie for movie in recs if movie["id"] == movie_id), None)
        if not target:
            target = recommender.movie_details(movie_id, user_id)
        ratings = recommender.user_ratings(user_id)
        neighbors = []
        for rating in ratings:
            rated_movie = recommender.movie_by_id.get(rating["movie_id"])
            if not rated_movie:
                continue
            raw_cf = recommender.similarity[movie_id].get(rated_movie["id"], 0.0)
            content = recommender._cosine(
                recommender.content_vectors.get(movie_id, {}),
                recommender.content_vectors.get(rated_movie["id"], {}),
            )
            neighbors.append(
                {
                    "movieId": rated_movie["id"],
                    "title": rated_movie["title"],
                    "year": rated_movie["year"],
                    "userRating": rating["rating"],
                    "cfScore": round(raw_cf, 4),
                    "contentScore": round(content, 4),
                }
            )
        neighbors.sort(key=lambda item: (item["cfScore"], item["contentScore"]), reverse=True)
        return jsonify(
            {
                "movie": target,
                "neighbors": neighbors,
                "formula": "score = alpha * normalized_cf + (1 - alpha) * content + quality_bonus + popularity_bonus",
                "alpha": float(request.args.get("alpha", 0.65)),
            }
        )


@app.post("/api/enrich/tmdb/<int:movie_id>")
def tmdb_enrich(movie_id):
    with get_connection() as connection:
        try:
            return jsonify(enrich_movie(connection, movie_id))
        except Exception as error:
            return jsonify({"ok": False, "message": str(error)}), 502


@app.post("/api/enrich/tmdb")
def tmdb_enrich_bulk():
    limit = min(int(request.args.get("limit", 25)), 100)
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT m.id
            FROM movies m
            JOIN movie_metadata mm ON mm.movie_id = m.id
            WHERE m.tmdb_id IS NOT NULL AND mm.source != 'tmdb'
            ORDER BY m.weighted_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        results = []
        for row in rows:
            try:
                results.append(enrich_movie(connection, row["id"]))
            except Exception as error:
                results.append({"ok": False, "movieId": row["id"], "message": str(error)})
        return jsonify({"count": len(results), "results": results})


@app.get("/api/evaluation")
def evaluation():
    report_path = ROOT / "reports" / "evaluation.json"
    if not report_path.exists():
        return jsonify(
            {
                "status": "missing",
                "message": "Запустите scripts/evaluate_model.py, чтобы получить RMSE, Precision@5, Recall@5 и F1@5.",
            }
        )
    return send_from_directory(report_path.parent, report_path.name)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("MOVIEREC_PORT", "8000"))
    app.run(host="127.0.0.1", port=port, debug=False)

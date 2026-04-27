import json
import math
import os
import re
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
APP_VERSION = "2026-04-28-semantic-optimizer"

MOVIE_REQUEST_LIMITS = {}
LLM_RERANK_CACHE = {}
TITLE_RE = re.compile(r"^[\w\s:;,.!?&'’()\-а-яА-ЯёЁ0-9]+$", re.UNICODE)
HINT_STOP_TOKENS = {"the", "a", "an", "of", "and", "из", "и", "в", "на"}
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
]


def current_user_id():
    return session.get("user_id")


def public_user(row):
    if not row:
        return None
    return {"id": row["id"], "username": row["username"], "createdAt": row["created_at"]}


def get_user(connection, user_id):
    if not user_id:
        return None
    return connection.execute("SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)).fetchone()


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
        embedding_error = None
        try:
            embedded = embedding_search(connection, recommender, query, limit=60)
        except Exception as error:
            embedded = None
            embedding_error = str(error)
        if embedded is not None:
            provider = embedded[0].get("embeddingProvider", "embeddings") if embedded else "embeddings"
            content = recommender.semantic_search(expand_query(query), limit=60)
            hinted = semantic_hint_candidates(recommender, query)
            merged = rerank_semantic_results(query, embedded, content, hinted)
            reranked, rerank_mode, rerank_error = maybe_llm_rerank(query, merged[:12])
            return jsonify(
                {
                    "mode": f"{provider}_embeddings",
                    "rerankMode": rerank_mode,
                    "rerankError": rerank_error,
                    "embeddingError": embedding_error,
                    "expandedQuery": expand_query(query),
                    "movies": reranked[:10],
                }
            )
        hinted = semantic_hint_candidates(recommender, query)
        fallback = rerank_semantic_results(query, [], recommender.semantic_search(expand_query(query), limit=60), hinted)
        reranked, rerank_mode, rerank_error = maybe_llm_rerank(query, fallback[:12])
        return jsonify(
            {
                "mode": "tfidf_fallback",
                "rerankMode": rerank_mode,
                "rerankError": rerank_error,
                "embeddingError": embedding_error,
                "expandedQuery": expand_query(query),
                "movies": reranked[:10],
            }
        )


def rerank_semantic_results(query, embedded, content, hinted=None):
    merged = {}
    for index, movie in enumerate(hinted or []):
        hint_priority = float(movie.get("hintPriority", index))
        merged[movie["id"]] = {
            **movie,
            "_embedding": 0.0,
            "_content": 0.0,
            "_hint": max(0.35, 1.0 - hint_priority * 0.08 - index * 0.015),
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
        combined = item["_embedding"] * 0.32 + item["_content"] * 0.32 + item["_hint"] * 0.95 + item.get("weightedScore", 0) / 100 + boost
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


def semantic_hint_candidates(recommender, query):
    hints = matching_title_hints(query)
    if not hints:
        return []
    candidates = {}
    for hint in hints:
        for movie, priority in token_scan_movies(recommender.movies, hint["searches"]):
            candidate = {
                **movie,
                "hintLabel": hint["label"],
                "hintPriority": min(priority, candidates.get(movie["id"], {}).get("hintPriority", priority)),
            }
            candidates[movie["id"]] = candidate
    return sorted(
        candidates.values(),
        key=lambda movie: (movie.get("hintPriority", 99), -movie.get("weightedScore", 0)),
    )[:24]


def matching_title_hints(query):
    normalized = normalize_semantic_text(query)
    matches = []
    for hint in SEMANTIC_TITLE_HINTS:
        if all(any(term in normalized for term in group) for group in hint["groups"]):
            matches.append(hint)
    return matches


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

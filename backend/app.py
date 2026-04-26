import re
from time import time

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from .db import ROOT, get_connection, init_db
from .embeddings import embedding_search, rebuild_movie_embeddings
from .recommender import HybridRecommender
from .tmdb import enrich_movie


app = Flask(__name__, static_folder=None)
app.secret_key = "movierec-dev-secret-change-before-production"

MOVIE_REQUEST_LIMITS = {}
TITLE_RE = re.compile(r"^[\w\s:;,.!?&'’()\-а-яА-ЯёЁ0-9]+$", re.UNICODE)


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


@app.get("/api/movies")
def movies():
    query = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 12)), 30)
    genre = (request.args.get("genre") or "").strip()
    year_from = request.args.get("yearFrom", type=int)
    year_to = request.args.get("yearTo", type=int)
    min_rating = request.args.get("minRating", type=float)
    has_poster = request.args.get("hasPoster") == "1"
    sort = request.args.get("sort", "weighted")
    with get_connection() as connection:
        recommender = HybridRecommender(connection)
        if query:
            found = recommender.search_movies(query, 60)
            if genre:
                found = [movie for movie in found if genre in movie.get("genres", [])]
            if year_from:
                found = [movie for movie in found if movie.get("year") and movie["year"] >= year_from]
            if year_to:
                found = [movie for movie in found if movie.get("year") and movie["year"] <= year_to]
            if min_rating:
                found = [movie for movie in found if movie.get("averageRating", 0) >= min_rating]
            if has_poster:
                found = [movie for movie in found if movie.get("poster")]
            return jsonify({"movies": found[:limit]})
        clauses = []
        params = []
        if genre:
            clauses.append("m.genres LIKE ?")
            params.append(f"%{genre}%")
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
            """,
            (*params, limit),
        ).fetchall()
        from .db import rows_to_movies

        return jsonify({"movies": rows_to_movies(rows)})


@app.get("/api/genres")
def genres():
    with get_connection() as connection:
        rows = connection.execute("SELECT genres FROM movies").fetchall()
    values = sorted({genre for row in rows for genre in __import__("json").loads(row["genres"] or "[]")})
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
        embedded = embedding_search(connection, recommender, query, limit=10)
        if embedded is not None:
            provider = embedded[0].get("embeddingProvider", "embeddings") if embedded else "embeddings"
            return jsonify({"mode": f"{provider}_embeddings", "movies": embedded})
        return jsonify({"mode": "tfidf_fallback", "movies": recommender.semantic_search(query, limit=10)})


@app.post("/api/embeddings/rebuild")
def embeddings_rebuild():
    with get_connection() as connection:
        try:
            limit = min(int(request.args.get("limit", 80)), 220)
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
    app.run(host="127.0.0.1", port=8000, debug=False)

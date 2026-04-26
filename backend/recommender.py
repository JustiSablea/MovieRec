import math
import re
from collections import Counter, defaultdict

from .db import row_to_movie, rows_to_movies


TOKEN_RE = re.compile(r"[a-zа-я0-9]{2,}", re.IGNORECASE)
STOPWORDS = {
    "фильм",
    "про",
    "или",
    "для",
    "как",
    "что",
    "это",
    "года",
    "духе",
    "жанрах",
    "подборке",
    "movieLens".lower(),
    "movie",
    "film",
    "the",
    "and",
    "with",
}
QUERY_SYNONYMS = {
    "сны": ["сон", "dream", "dreams"],
    "снах": ["сон", "dream", "dreams"],
    "ограбление": ["heist", "crime", "вор"],
    "космос": ["space", "sci-fi", "sci"],
    "роботы": ["robot", "artificial", "intelligence"],
}


class HybridRecommender:
    def __init__(self, connection):
        self.connection = connection
        self.movies = []
        self.movie_by_id = {}
        self.similarity = defaultdict(dict)
        self.content_vectors = {}
        self.idf = {}
        self._load()

    def _load(self):
        rows = self.connection.execute(
            """
            SELECT m.*, mm.poster, mm.palette, mm.tags, mm.description, mm.actors, mm.director
            FROM movies m
            JOIN movie_metadata mm ON mm.movie_id = m.id
            """
        ).fetchall()
        self.movies = rows_to_movies(rows)
        self.movie_by_id = {movie["id"]: movie for movie in self.movies}

        for row in self.connection.execute("SELECT movie_id, similar_movie_id, score FROM movie_similarities"):
            self.similarity[row["movie_id"]][row["similar_movie_id"]] = row["score"]

        self._build_content_vectors()

    def _build_content_vectors(self):
        documents = {}
        document_frequency = Counter()
        for movie in self.movies:
            tokens = self._tokens(movie)
            documents[movie["id"]] = Counter(tokens)
            document_frequency.update(set(tokens))

        total = max(1, len(documents))
        self.idf = {token: math.log((1 + total) / (1 + freq)) + 1 for token, freq in document_frequency.items()}

        for movie_id, counts in documents.items():
            vector = {}
            total_terms = sum(counts.values()) or 1
            for token, count in counts.items():
                vector[token] = (count / total_terms) * self.idf[token]
            self.content_vectors[movie_id] = self._normalize(vector)

    def _tokens(self, movie):
        text = " ".join(
            [
                movie["title"],
                " ".join(movie.get("genres", [])) * 3,
                " ".join(movie.get("tags", [])) * 2,
                movie.get("description", ""),
                " ".join(movie.get("actors", [])),
                movie.get("director") or "",
            ]
        )
        return [
            token
            for token in (raw.lower().replace("ё", "е") for raw in TOKEN_RE.findall(text))
            if token not in STOPWORDS
        ]

    @staticmethod
    def _normalize(vector):
        norm = math.sqrt(sum(value * value for value in vector.values()))
        if not norm:
            return {}
        return {token: value / norm for token, value in vector.items()}

    @staticmethod
    def _cosine(left, right):
        if not left or not right:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        return sum(value * right.get(token, 0.0) for token, value in left.items())

    def user_ratings(self, user_id):
        rows = self.connection.execute(
            """
            SELECT r.movie_id, r.rating, m.title, m.year
            FROM ratings r
            JOIN movies m ON m.id = r.movie_id
            WHERE r.user_id = ?
            ORDER BY r.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def movie_details(self, movie_id, user_id=None):
        row = self.connection.execute(
            """
            SELECT m.*, mm.poster, mm.palette, mm.tags, mm.description, mm.actors, mm.director
            FROM movies m
            JOIN movie_metadata mm ON mm.movie_id = m.id
            WHERE m.id = ?
            """,
            (movie_id,),
        ).fetchone()
        if not row:
            return None
        movie = row_to_movie(row)
        movie["similarMovies"] = self.similar_movies(movie_id, limit=8)
        if user_id:
            rating = self.connection.execute(
                "SELECT rating FROM ratings WHERE user_id = ? AND movie_id = ?",
                (user_id, movie_id),
            ).fetchone()
            movie["userRating"] = rating["rating"] if rating else None
        return movie

    def search_movies(self, query, limit=8):
        normalized = query.strip().lower().replace("ё", "е")
        if not normalized:
            return []
        scored = []
        for movie in self.movies:
            title = movie["title"].lower().replace("ё", "е")
            genres = " ".join(movie.get("genres", [])).lower()
            tags = " ".join(movie.get("tags", [])).lower()
            score = 0
            if title.startswith(normalized):
                score += 8
            if normalized in title:
                score += 4
            if normalized in genres or normalized in tags:
                score += 1.5
            score += movie["popularity"] * 0.25
            if score > 0:
                scored.append((score, movie))
        scored.sort(key=lambda item: (item[0], item[1]["weightedScore"]), reverse=True)
        return [item[1] for item in scored[:limit]]

    def semantic_search(self, query, limit=8):
        tokens = []
        for raw in TOKEN_RE.findall(query):
            token = raw.lower().replace("ё", "е")
            if token in STOPWORDS:
                continue
            tokens.append(token)
            tokens.extend(QUERY_SYNONYMS.get(token, []))
        counts = Counter(tokens)
        total = sum(counts.values()) or 1
        query_vector = {
            token: (count / total) * self.idf.get(token, 1.0)
            for token, count in counts.items()
        }
        query_vector = self._normalize(query_vector)
        scored = []
        for movie in self.movies:
            content = self._cosine(query_vector, self.content_vectors.get(movie["id"], {}))
            lexical = 1.0 if query.lower() in movie["title"].lower() else 0.0
            score = content + lexical + movie["weightedScore"] / 100
            scored.append((score, movie, content))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                **movie,
                "semanticScore": round(content, 4),
                "reason": "Найдено по описанию и тегам фильма",
            }
            for _, movie, content in scored[:limit]
        ]

    def recommend(self, user_id, alpha=0.7, limit=10):
        ratings = self.user_ratings(user_id)
        rated_ids = {entry["movie_id"] for entry in ratings}
        if not ratings:
            return self._cold_start(limit)

        candidates = self._candidate_pool(ratings, rated_ids)
        if not candidates:
            candidates = [movie for movie in self.movies if movie["id"] not in rated_ids]

        weighted_values = [movie["weightedScore"] for movie in self.movies]
        min_weighted = min(weighted_values)
        max_weighted = max(weighted_values)
        effective_alpha = min(max(alpha, 0.0), 0.75)
        genre_profile = self._genre_profile(ratings)
        scored = []

        for movie in candidates:
            cf_sum = 0.0
            content_sum = 0.0
            weight_sum = 0.0
            best_cf = (0.0, None)
            best_content = (0.0, None)

            for rating in ratings:
                liked_movie = self.movie_by_id.get(rating["movie_id"])
                if not liked_movie:
                    continue
                preference = max(0.1, (rating["rating"] - 2.5) / 2.5)
                cf_score = self.similarity[movie["id"]].get(liked_movie["id"], 0.0)
                tfidf_score = self._cosine(
                    self.content_vectors.get(movie["id"], {}),
                    self.content_vectors.get(liked_movie["id"], {}),
                )
                genre_score = self._genre_affinity(movie, genre_profile)
                content_score = tfidf_score * 0.68 + genre_score * 0.32
                cf_sum += cf_score * preference
                content_sum += content_score * preference
                weight_sum += preference
                if cf_score > best_cf[0]:
                    best_cf = (cf_score, liked_movie)
                if content_score > best_content[0]:
                    best_content = (content_score, liked_movie)

            cf = cf_sum / weight_sum if weight_sum else 0.0
            content = content_sum / weight_sum if weight_sum else 0.0
            cf_signal = self._cf_signal(cf)
            quality = (movie["weightedScore"] - min_weighted) / (max_weighted - min_weighted or 1)
            profile_penalty = 0.0 if content >= 0.08 or cf >= 0.68 else 0.08
            score = effective_alpha * cf_signal + (1 - effective_alpha) * content + quality * 0.08 + movie["popularity"] * 0.025 - profile_penalty
            reason_movie = best_cf[1] if best_cf[0] >= best_content[0] else best_content[1]
            reason = (
                f"Похож на {reason_movie['title']}"
                if reason_movie
                else "Высокая средняя оценка и популярность MovieLens"
            )
            confidence_rank, confidence = self._confidence(cf_signal, content)
            scored.append(
                {
                    **movie,
                    "score": round(score, 4),
                    "cfScore": round(cf, 4),
                    "contentScore": round(content, 4),
                    "cfSignal": round(cf_signal, 4),
                    "confidenceRank": confidence_rank,
                    "confidence": confidence,
                    "reason": reason,
                    "method": self._method_label(confidence, cf_signal, content),
                }
            )

        scored.sort(key=lambda item: (item["confidenceRank"], item["score"], item["weightedScore"]), reverse=True)
        recommendations = self._diversify(scored, limit)
        self._save_recommendations(user_id, recommendations)
        return recommendations

    @staticmethod
    def _cf_signal(value):
        return max(0.0, min(1.0, (value - 0.45) / 0.35))

    @staticmethod
    def _signal_label(value):
        if value >= 0.58:
            return "сильный"
        if value >= 0.22:
            return "средний"
        return "слабый"

    def _confidence(self, cf_signal, content):
        if cf_signal >= 0.58 or content >= 0.45:
            return 2, "Высокое совпадение"
        if cf_signal >= 0.22 or content >= 0.22:
            return 1, "Хорошее совпадение"
        return 0, "Дополнительная рекомендация"

    def _method_label(self, confidence, cf_signal, content):
        if cf_signal >= 0.22 and content >= 0.22:
            basis = "CF + контент"
        elif cf_signal >= content:
            basis = "совместные оценки"
        else:
            basis = "контентный профиль"
        return f"{confidence} · Основа: {basis}"

    def _genre_profile(self, ratings):
        weights = defaultdict(float)
        total = 0.0
        for rating in ratings:
            movie = self.movie_by_id.get(rating["movie_id"])
            if not movie:
                continue
            preference = max(0.1, (rating["rating"] - 2.5) / 2.5)
            for genre in movie.get("genres", []):
                weights[genre] += preference
                total += preference
        if not total:
            return {}
        return {genre: weight / total for genre, weight in weights.items()}

    @staticmethod
    def _genre_affinity(movie, genre_profile):
        if not genre_profile:
            return 0.0
        return sum(genre_profile.get(genre, 0.0) for genre in movie.get("genres", []))

    def _diversify(self, scored, limit):
        selected = []
        franchise_counts = defaultdict(int)
        genre_counts = defaultdict(int)

        for item in scored:
            key = self._franchise_key(item["title"])
            if franchise_counts[key] >= 1 and len(selected) < max(6, limit // 2):
                continue
            selected.append(item)
            franchise_counts[key] += 1
            for genre in item.get("genres", [])[:2]:
                genre_counts[genre] += 1
            if len(selected) >= limit:
                return selected

        if len(selected) < limit:
            selected_ids = {item["id"] for item in selected}
            for item in scored:
                if item["id"] not in selected_ids:
                    selected.append(item)
                    selected_ids.add(item["id"])
                if len(selected) >= limit:
                    break
        return selected[:limit]

    @staticmethod
    def _franchise_key(title):
        cleaned = title.lower()
        for prefix in ("the ", "a ", "an "):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        return cleaned.split(":")[0].strip()

    def _candidate_pool(self, ratings, rated_ids):
        candidate_ids = set()
        genre_profile = self._genre_profile(ratings)
        liked_ids = [rating["movie_id"] for rating in ratings if rating["rating"] >= 3.5] or [
            rating["movie_id"] for rating in ratings
        ]
        for movie_id in liked_ids:
            for similar_id, _ in sorted(self.similarity[movie_id].items(), key=lambda item: item[1], reverse=True)[:18]:
                candidate_ids.add(similar_id)
            vector = self.content_vectors.get(movie_id, {})
            content_neighbors = sorted(
                (
                    (self._cosine(vector, other_vector), other_id)
                    for other_id, other_vector in self.content_vectors.items()
                    if other_id != movie_id
                ),
                reverse=True,
            )[:18]
            for _, other_id in content_neighbors:
                candidate_ids.add(other_id)

        for movie in sorted(self.movies, key=lambda item: item["weightedScore"], reverse=True)[:40]:
            candidate_ids.add(movie["id"])

        genre_candidates = sorted(
            self.movies,
            key=lambda movie: (self._genre_affinity(movie, genre_profile), movie["weightedScore"], movie["popularity"]),
            reverse=True,
        )[:70]
        for movie in genre_candidates:
            candidate_ids.add(movie["id"])

        return [self.movie_by_id[movie_id] for movie_id in candidate_ids if movie_id not in rated_ids and movie_id in self.movie_by_id]

    def _cold_start(self, limit):
        buckets = {}
        for movie in sorted(self.movies, key=lambda item: (item["weightedScore"], item["popularity"]), reverse=True):
            key = movie["genres"][0] if movie["genres"] else "Other"
            if key not in buckets:
                buckets[key] = {
                    **movie,
                    "score": round(movie["weightedScore"] / 5, 4),
                    "cfScore": 0.0,
                    "contentScore": 0.0,
                    "reason": "Стартовая рекомендация для нового пользователя",
                    "method": "Cold start · популярные фильмы разных жанров",
                }
            if len(buckets) >= limit:
                break
        return list(buckets.values())[:limit]

    def similar_movies(self, movie_id, limit=6):
        similar_ids = sorted(self.similarity[movie_id].items(), key=lambda item: item[1], reverse=True)[:limit]
        result = []
        for similar_id, score in similar_ids:
            movie = self.movie_by_id.get(similar_id)
            if movie:
                result.append({**movie, "similarity": round(score, 4)})
        return result

    def _save_recommendations(self, user_id, recommendations):
        self.connection.execute("DELETE FROM recommendations WHERE user_id = ?", (user_id,))
        for item in recommendations:
            self.connection.execute(
                """
                INSERT INTO recommendations (user_id, movie_id, score, cf_score, content_score, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, item["id"], item["score"], item["cfScore"], item["contentScore"], item["reason"]),
            )
        self.connection.commit()

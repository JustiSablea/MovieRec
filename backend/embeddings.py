import json
import math
import os
import re

import requests

from .config import load_env_file


load_env_file()
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai").lower()
OPENAI_EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
LOCAL_EMBEDDING_MODEL = os.environ.get(
    "LOCAL_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
_LOCAL_MODEL = None
TOKEN_RE = re.compile(r"[a-zа-яё0-9]{2,}", re.IGNORECASE)
QUERY_EXPANSIONS = {
    "сын": ["сны", "сон", "dream", "dreams"],
    "сны": ["сон", "dream", "dreams", "подсознание", "разум"],
    "снах": ["сны", "сон", "dream", "dreams", "подсознание", "разум"],
    "сон": ["сны", "dream", "dreams", "подсознание", "разум"],
    "ограбления": ["ограбление", "heist", "thief", "crime", "кража", "преступление"],
    "ограбление": ["heist", "thief", "crime", "кража", "преступление"],
    "ограблении": ["ограбление", "heist", "crime"],
    "воры": ["heist", "crime", "thief"],
    "космос": ["space", "sci-fi", "interstellar"],
    "робот": ["robot", "robots", "wall-e"],
}


def movie_text(movie):
    return " ".join(
        [
            movie["title"],
            str(movie.get("year") or ""),
            " ".join(movie.get("genres", [])),
            " ".join(movie.get("tags", [])),
            movie.get("description") or "",
            " ".join(movie.get("actors", [])),
            movie.get("director") or "",
        ]
    ).strip()


def expand_query(query):
    tokens = []
    for raw in TOKEN_RE.findall(query.lower().replace("ё", "е")):
        tokens.append(raw)
        tokens.extend(QUERY_EXPANSIONS.get(raw, []))
    return f"{query} {' '.join(tokens)}".strip()


def cosine(left, right):
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def openai_embed(texts):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не задан. Embeddings API недоступен.")

    response = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"model": OPENAI_EMBEDDING_MODEL, "input": texts},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    return [item["embedding"] for item in payload["data"]]


def local_embed(texts, model_name=None):
    global _LOCAL_MODEL
    model_name = model_name or LOCAL_EMBEDDING_MODEL
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "Для локального нейропоиска установите sentence-transformers: "
            "pip install sentence-transformers. После этого задайте EMBEDDING_PROVIDER=local."
        ) from error
    if _LOCAL_MODEL is None:
        _LOCAL_MODEL = SentenceTransformer(model_name, local_files_only=True)
    vectors = _LOCAL_MODEL.encode(texts, normalize_embeddings=True)
    return [vector.tolist() for vector in vectors]


def embed_texts(texts, provider=None, model=None):
    provider = (provider or EMBEDDING_PROVIDER).lower()
    if provider == "local":
        model = model or LOCAL_EMBEDDING_MODEL
        return local_embed(texts, model), "local", model
    model = model or OPENAI_EMBEDDING_MODEL
    return openai_embed(texts), "openai", model


def rebuild_movie_embeddings(connection, recommender, limit=80, provider=None):
    movies = sorted(recommender.movies, key=lambda movie: movie["weightedScore"], reverse=True)[:limit]
    texts = [movie_text(movie) for movie in movies]
    embeddings, provider, model = embed_texts(texts, provider=provider)
    for movie, embedding in zip(movies, embeddings):
        connection.execute(
            """
            INSERT INTO movie_embeddings (movie_id, provider, model, embedding, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(movie_id)
            DO UPDATE SET provider = excluded.provider,
                          model = excluded.model,
                          embedding = excluded.embedding,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (movie["id"], provider, model, json.dumps(embedding)),
        )
    connection.commit()
    return {"ok": True, "provider": provider, "model": model, "count": len(movies)}


def embedding_search(connection, recommender, query, limit=10):
    rows = connection.execute("SELECT movie_id, embedding, provider, model FROM movie_embeddings").fetchall()
    if not rows:
        return None
    provider = rows[0]["provider"]
    model = rows[0]["model"]
    expanded_query = expand_query(query)
    query_embedding = embed_texts([expanded_query], provider=provider, model=model)[0][0]
    scored = []
    for row in rows:
        movie = recommender.movie_by_id.get(row["movie_id"])
        if not movie:
            continue
        score = cosine(query_embedding, json.loads(row["embedding"]))
        scored.append((score, movie, row["provider"], row["model"]))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            **movie,
            "semanticScore": round(score, 4),
            "embeddingProvider": provider,
            "embeddingModel": model,
            "reason": "Найдено через embeddings",
        }
        for score, movie, provider, model in scored[:limit]
    ]

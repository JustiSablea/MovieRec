import argparse
import json
import math
import random
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def load_movies(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return {movie["id"]: movie for movie in data["movies"]}


def read_ratings(zip_path, movie_ids, max_users):
    buckets = defaultdict(list)
    with zipfile.ZipFile(zip_path) as archive:
        for chunk in pd.read_csv(
            archive.open("ml-32m/ratings.csv"),
            usecols=["userId", "movieId", "rating"],
            chunksize=250_000,
        ):
            chunk = chunk[chunk["movieId"].isin(movie_ids)]
            for row in chunk.itertuples(index=False):
                if len(buckets) > max_users * 8 and len([items for items in buckets.values() if len(items) >= 8]) >= max_users:
                    break
                buckets[int(row.userId)].append(
                    {"userId": int(row.userId), "movieId": int(row.movieId), "rating": float(row.rating)}
                )
            if len([items for items in buckets.values() if len(items) >= 8]) >= max_users:
                break
    rows = []
    for items in buckets.values():
        if len(items) >= 8:
            rows.extend(items)
        if len(rows) and len({row["userId"] for row in rows}) >= max_users:
            break
    return pd.DataFrame(rows)


def train_test_split(ratings, seed=42):
    rng = random.Random(seed)
    train = []
    test = []
    for _, group in ratings.groupby("userId"):
        rows = group.to_dict("records")
        positives = [row for row in rows if row["rating"] >= 4.0]
        holdout = rng.choice(positives or rows)
        for row in rows:
            (test if row is holdout else train).append(row)
    return train, test


def build_item_similarity(train):
    by_user = defaultdict(list)
    norms = defaultdict(float)
    dots = defaultdict(float)
    for row in train:
        by_user[row["userId"]].append((row["movieId"], row["rating"]))
    for items in by_user.values():
        for movie_id, rating in items:
            norms[movie_id] += rating * rating
        for index, (left, left_rating) in enumerate(items):
            for right, right_rating in items[index + 1 :]:
                key = tuple(sorted((left, right)))
                dots[key] += left_rating * right_rating
    similarity = defaultdict(dict)
    for (left, right), dot in dots.items():
        denom = math.sqrt(norms[left] * norms[right])
        if denom:
            score = dot / denom
            similarity[left][right] = score
            similarity[right][left] = score
    return similarity


def content_similarity(left, right):
    left_terms = set(left.get("genres", [])) | set(left.get("tags", [])[:8])
    right_terms = set(right.get("genres", [])) | set(right.get("tags", [])[:8])
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def predict_cf(user_train, movie_id, similarity, global_avg):
    numerator = 0.0
    denominator = 0.0
    for rated_id, rating in user_train:
        sim = similarity[movie_id].get(rated_id, 0.0)
        numerator += sim * rating
        denominator += abs(sim)
    return numerator / denominator if denominator else global_avg


def content_score_for_user(user_train, movies, movie_id):
    movie = movies[movie_id]
    liked = [(rated_id, rating) for rated_id, rating in user_train if rating >= 4.0] or user_train
    return max((content_similarity(movie, movies.get(liked_id, movie)) for liked_id, _ in liked), default=0.0)


def recommend(user_train, movies, similarity, alpha, global_avg, topn=5, mode="hybrid"):
    rated = {movie_id for movie_id, _ in user_train}
    scores = []
    for movie_id, movie in movies.items():
        if movie_id in rated:
            continue
        cf = (predict_cf(user_train, movie_id, similarity, global_avg) - 0.5) / 4.5
        content = content_score_for_user(user_train, movies, movie_id)
        quality = movie["weightedScore"] / 80
        if mode == "cf":
            score = cf + quality
        elif mode == "content":
            score = content + quality
        else:
            score = alpha * cf + (1 - alpha) * content + movie["weightedScore"] / 50
        scores.append((score, movie_id, cf, content))
    scores.sort(reverse=True)
    return scores[:topn]


def empty_bucket():
    return {"squaredErrors": [], "hits": 0, "totalRelevant": 0, "users": 0}


def update_bucket(bucket, prediction, actual_rating, holdout_movie_id, top_ids):
    bucket["squaredErrors"].append((prediction - actual_rating) ** 2)
    if actual_rating >= 4.0:
        bucket["totalRelevant"] += 1
        if holdout_movie_id in top_ids:
            bucket["hits"] += 1
    bucket["users"] += 1


def finalize_bucket(bucket):
    users = bucket["users"]
    precision = bucket["hits"] / (users * 5) if users else 0
    recall = bucket["hits"] / bucket["totalRelevant"] if bucket["totalRelevant"] else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    rmse = math.sqrt(sum(bucket["squaredErrors"]) / len(bucket["squaredErrors"])) if bucket["squaredErrors"] else 0
    return {
        "rmse": round(rmse, 4),
        "precisionAt5": round(precision, 4),
        "recallAt5": round(recall, 4),
        "f1At5": round(f1, 4),
    }


def evaluate(zip_path, movies_path, max_users, alpha):
    movies = load_movies(movies_path)
    ratings = read_ratings(zip_path, set(movies), max_users)
    train, test = train_test_split(ratings)
    similarity = build_item_similarity(train)
    global_avg = sum(row["rating"] for row in train) / len(train)

    train_by_user = defaultdict(list)
    for row in train:
        train_by_user[row["userId"]].append((row["movieId"], row["rating"]))

    buckets = {name: empty_bucket() for name in ("cf", "content", "hybrid")}

    for row in test:
        user_train = train_by_user[row["userId"]]
        if not user_train:
            continue
        cf_prediction = predict_cf(user_train, row["movieId"], similarity, global_avg)
        content_prediction = 0.5 + 4.5 * content_score_for_user(user_train, movies, row["movieId"])
        hybrid_prediction = alpha * cf_prediction + (1 - alpha) * content_prediction
        predictions = {"cf": cf_prediction, "content": content_prediction, "hybrid": hybrid_prediction}

        for mode in ("cf", "content", "hybrid"):
            top = recommend(user_train, movies, similarity, alpha, global_avg, topn=5, mode=mode)
            top_ids = {movie_id for _, movie_id, _, _ in top}
            update_bucket(buckets[mode], predictions[mode], row["rating"], row["movieId"], top_ids)

    model_metrics = {name: finalize_bucket(bucket) for name, bucket in buckets.items()}
    return {
        "sampleUsers": max_users,
        "testUsers": buckets["hybrid"]["users"],
        "alpha": alpha,
        **model_metrics["hybrid"],
        "models": model_metrics,
        "note": "Метрики посчитаны на компактной выборке фильмов сайта и holdout-разбиении по одному фильму на пользователя.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", default=str(Path.home() / "Downloads" / "ml-32m.zip"))
    parser.add_argument("--movies", default=str(ROOT / "data" / "movies.json"))
    parser.add_argument("--out", default=str(ROOT / "reports" / "evaluation.json"))
    parser.add_argument("--max-users", type=int, default=500)
    parser.add_argument("--alpha", type=float, default=0.7)
    args = parser.parse_args()

    report = evaluate(Path(args.zip), Path(args.movies), args.max_users, args.alpha)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

import argparse
import json
import math
import os
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
MOVIES_JSON = ROOT / "data" / "movies.json"
EXTENSION_MOVIES_JSON = ROOT / "extension" / "data" / "movies.json"
TMDB_BASE = "https://api.themoviedb.org/3"
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


def tmdb_get(path, **params):
    api_key = os.environ.get("TMDB_API_KEY")
    if not api_key:
        raise SystemExit("TMDB_API_KEY не задан. Добавьте ключ в .env или переменные окружения.")
    response = requests.get(
        f"{TMDB_BASE}{path}",
        params={"api_key": api_key, **params},
        timeout=20,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def genre_palette(genres):
    if "Sci-Fi" in genres:
        return ["#0ea5e9", "#7c3aed"]
    if "Crime" in genres or "Thriller" in genres:
        return ["#ef4444", "#a855f7"]
    if "Animation" in genres or "Family" in genres:
        return ["#f59e0b", "#10b981"]
    if "Romance" in genres:
        return ["#ec4899", "#f97316"]
    if "Adventure" in genres or "Fantasy" in genres:
        return ["#22c55e", "#06b6d4"]
    if "Drama" in genres:
        return ["#a855f7", "#334155"]
    return ["#64748b", "#111827"]


def weighted_rating(avg, count, global_avg, minimum_votes=1200):
    return (count / (count + minimum_votes)) * avg + (minimum_votes / (count + minimum_votes)) * global_avg


def normalize_vote(vote_average):
    return round(max(0.5, min(5.0, float(vote_average or 0) / 2)), 2)


def movie_id_from_tmdb(tmdb_id):
    return 10_000_000 + int(tmdb_id)


def parse_year(date_value):
    if not date_value or len(date_value) < 4:
        return None
    try:
        return int(date_value[:4])
    except ValueError:
        return None


def has_blocked_terms(details):
    text = " ".join(
        [
            details.get("title") or "",
            details.get("original_title") or "",
            details.get("overview") or "",
        ]
    ).lower()
    blocked = ("porn", "porno", "порно")
    return any(term in text for term in blocked)


def build_movie(details, genre_names, global_avg):
    credits = details.get("credits") or {}
    director = next((person["name"] for person in credits.get("crew", []) if person.get("job") == "Director"), None)
    actors = [person["name"] for person in credits.get("cast", [])[:6]]
    genres = [genre_names.get(genre["id"], genre.get("name", "")) for genre in details.get("genres", []) if genre.get("id")]
    average = normalize_vote(details.get("vote_average"))
    count = int(details.get("vote_count") or 0)
    weighted = round(weighted_rating(average, count, global_avg), 4)
    popularity = min(1.0, math.log1p(float(details.get("popularity") or 0)) / 8)
    keywords = tmdb_get(f"/movie/{details['id']}/keywords") or {}
    tags = [item["name"].lower() for item in keywords.get("keywords", [])[:12]]
    return {
        "id": movie_id_from_tmdb(details["id"]),
        "title": details.get("title") or details.get("original_title") or f"TMDb {details['id']}",
        "year": parse_year(details.get("release_date")),
        "genres": genres,
        "averageRating": average,
        "ratingCount": count,
        "weightedScore": weighted,
        "popularity": round(popularity, 4),
        "poster": f"{IMAGE_BASE}{details['poster_path']}" if details.get("poster_path") else None,
        "palette": genre_palette(genres),
        "tags": tags,
        "description": details.get("overview") or "",
        "actors": actors,
        "director": director,
        "tmdbId": details["id"],
        "imdbId": (details.get("imdb_id") or "").replace("tt", "") or None,
        "similar": [],
        "source": "tmdb",
    }


def endpoint_pages(endpoint, pages, language, min_votes):
    for page in range(1, pages + 1):
        if endpoint == "/discover/movie":
            payload = tmdb_get(
                endpoint,
                language=language,
                page=page,
                sort_by="vote_count.desc",
                include_adult="false",
                vote_count_gte=min_votes,
                with_original_language="",
            )
        else:
            payload = tmdb_get(endpoint, language=language, page=page, region="US")
        for item in payload.get("results", []):
            yield item
        time.sleep(0.08)


def expand(max_new, pages, language, endpoint, min_votes):
    load_env_file()
    data = json.loads(MOVIES_JSON.read_text(encoding="utf-8"))
    existing_tmdb = {movie.get("tmdbId") for movie in data["movies"] if movie.get("tmdbId")}
    existing_ids = {movie["id"] for movie in data["movies"]}
    genre_payload = tmdb_get("/genre/movie/list", language=language)
    genre_names = {genre["id"]: genre["name"] for genre in genre_payload.get("genres", [])}
    global_avg = data.get("globalAverage") or 3.5
    added = []

    for item in endpoint_pages(endpoint, pages, language, min_votes):
        tmdb_id = item.get("id")
        if not tmdb_id or tmdb_id in existing_tmdb:
            continue
        new_id = movie_id_from_tmdb(tmdb_id)
        if new_id in existing_ids:
            continue
        details = tmdb_get(f"/movie/{tmdb_id}", language=language, append_to_response="credits")
        if (
            not details
            or details.get("adult")
            or has_blocked_terms(details)
            or int(details.get("vote_count") or 0) < min_votes
            or not details.get("poster_path")
            or not details.get("overview")
        ):
            continue
        movie = build_movie(details, genre_names, global_avg)
        data["movies"].append(movie)
        existing_tmdb.add(tmdb_id)
        existing_ids.add(new_id)
        added.append(movie)
        print(f"added tmdbId={tmdb_id} title={movie['title']}")
        if len(added) >= max_new:
            break
        time.sleep(0.08)

    data["movieCount"] = len(data["movies"])
    data["source"] = f"{data.get('source', 'MovieLens ml-32m')} + TMDb"
    MOVIES_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    EXTENSION_MOVIES_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return added


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new", type=int, default=60)
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--language", default="ru-RU")
    parser.add_argument("--min-votes", type=int, default=500)
    parser.add_argument("--endpoint", default="/movie/popular", choices=["/movie/popular", "/movie/top_rated", "/movie/now_playing", "/discover/movie"])
    args = parser.parse_args()
    added = expand(args.max_new, args.pages, args.language, args.endpoint, args.min_votes)
    print(json.dumps({"added": len(added), "movieCount": len(json.loads(MOVIES_JSON.read_text(encoding="utf-8"))["movies"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()

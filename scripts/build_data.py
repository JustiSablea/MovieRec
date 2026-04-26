import argparse
import csv
import io
import itertools
import json
import math
import re
import zipfile
from collections import defaultdict
from pathlib import Path


POSTERS = {
    1: "https://image.tmdb.org/t/p/w500/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg",
    47: "https://image.tmdb.org/t/p/w500/191nKfP0ehp3uIvWqgPbFmI4lv9.jpg",
    50: "https://image.tmdb.org/t/p/w500/bUPmtQzrRhzqYySeiMpv7GurAfm.jpg",
    110: "https://image.tmdb.org/t/p/w500/or1gBugydmjToAEq7OZY0owwFk.jpg",
    260: "https://image.tmdb.org/t/p/w500/6FfCtAuVAW8XJjZ7eWeLibRLWTw.jpg",
    296: "https://image.tmdb.org/t/p/w500/d5iIlFn5s0ImszYzBPb8JPIfbXD.jpg",
    318: "https://image.tmdb.org/t/p/w500/q6y0Go1tsGEsmtFryDOJo3dEmqu.jpg",
    356: "https://image.tmdb.org/t/p/w500/arw2vcBveWOVZr6pxd9XTd1TdQa.jpg",
    480: "https://image.tmdb.org/t/p/w500/b1xCNnyrPebIc7EWNZIa6jhb1Ww.jpg",
    527: "https://image.tmdb.org/t/p/w500/sF1U4EUQS8YHUYjNl3pMGNIQyr0.jpg",
    541: "https://image.tmdb.org/t/p/w500/63N9uy8nd9j7Eog2axPQ8lbr3Wj.jpg",
    589: "https://image.tmdb.org/t/p/w500/5M0j0B18abtBI5gi2RhfjjurTqb.jpg",
    593: "https://image.tmdb.org/t/p/w500/uS9m8OBk1A8eM9I042bx8XXpqAq.jpg",
    858: "https://image.tmdb.org/t/p/w500/3bhkrj58Vtu7enYsRolD1fZdja1.jpg",
    1196: "https://image.tmdb.org/t/p/w500/nNAeTmF4CtdSgMDplXTDPOpYzsX.jpg",
    1198: "https://image.tmdb.org/t/p/w500/ceG9VzoRAVGwivFU403Wc3AHRys.jpg",
    1213: "https://image.tmdb.org/t/p/w500/aKuFiU82s5ISJpGZp7YkIr3kCUd.jpg",
    1221: "https://image.tmdb.org/t/p/w500/hek3koDUyRQk7FIhPXsa6mT2Zc3.jpg",
    2028: "https://image.tmdb.org/t/p/w500/1wY4psJ5NVEhCuOYROwLH2XExM2.jpg",
    2571: "https://image.tmdb.org/t/p/w500/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg",
    2959: "https://image.tmdb.org/t/p/w500/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
    4226: "https://image.tmdb.org/t/p/w500/fKTPH2WvH8nHTXeBYBVhawtRqtR.jpg",
    4993: "https://image.tmdb.org/t/p/w500/6oom5QYQ2yQTMJIbnvbkBL9cHo6.jpg",
    5952: "https://image.tmdb.org/t/p/w500/5VTN0pR8gcqV3EPUHHfMGnJYN9L.jpg",
    7153: "https://image.tmdb.org/t/p/w500/rCzpDGLbOoPwLjy3OAm5NUPOTrC.jpg",
    58559: "https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
    79132: "https://image.tmdb.org/t/p/w500/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
    109487: "https://image.tmdb.org/t/p/w500/gEU2QniE6E77NI6lCU6MxlNBvIxY.jpg",
}


DESCRIPTIONS = {
    318: "Банкир, несправедливо осужденный за убийство, находит дружбу и надежду в стенах тюрьмы Шоушенк.",
    79132: "Команда специалистов проникает в сны, чтобы внедрить идею в сознание наследника корпорации.",
    2959: "Офисный работник и харизматичный продавец создают подпольный клуб, который выходит из-под контроля.",
    2571: "Хакер узнает, что привычная реальность является симуляцией, и вступает в борьбу за свободу людей.",
    356: "История простодушного Форреста, который оказывается свидетелем ключевых событий американской истории.",
    296: "Несколько криминальных историй переплетаются в ироничной и жесткой мозаике Лос-Анджелеса.",
    858: "Семейная сага о власти, долге и цене решений внутри могущественного мафиозного клана.",
    58559: "Бэтмен сталкивается с Джокером, который превращает Готэм в испытание для морали и порядка.",
    109487: "Группа исследователей отправляется через червоточину в поисках нового дома для человечества.",
    593: "Молодая агентка ФБР обращается к заключенному психиатру, чтобы поймать серийного убийцу.",
    4993: "Хоббит Фродо получает кольцо всевластия и отправляется в путь, от которого зависит судьба Средиземья.",
    260: "Юный Люк Скайуокер присоединяется к повстанцам и открывает для себя силу джедаев.",
    1: "Игрушки оживают, когда людей нет рядом, и переживают ревность, дружбу и большое приключение.",
}


REQUIRED_IDS = set(POSTERS) | {
    318,
    79132,
    2959,
    2571,
    356,
    296,
    858,
    58559,
    109487,
    593,
    4993,
    7153,
    5952,
    260,
    1,
}


GENRE_RU = {
    "Action": "боевика",
    "Adventure": "приключений",
    "Animation": "анимации",
    "Children": "семейного кино",
    "Comedy": "комедии",
    "Crime": "криминальной истории",
    "Documentary": "документального кино",
    "Drama": "драмы",
    "Fantasy": "фэнтези",
    "Film-Noir": "нуара",
    "Horror": "хоррора",
    "IMAX": "зрелищного кино",
    "Musical": "мюзикла",
    "Mystery": "детектива",
    "Romance": "романтической истории",
    "Sci-Fi": "научной фантастики",
    "Thriller": "триллера",
    "War": "военной драмы",
    "Western": "вестерна",
}


TAG_STOPWORDS = {
    "dvd",
    "bd-video",
    "seen more than once",
    "erlend's dvds",
    "want to see again",
    "criterion",
    "based on a book",
}


def parse_title(raw_title):
    match = re.search(r"\((\d{4})\)\s*$", raw_title)
    year = int(match.group(1)) if match else None
    title = re.sub(r"\s*\(\d{4}\)\s*$", "", raw_title).strip()
    article_match = re.match(r"(.+),\s+(The|A|An)$", title)
    if article_match:
        title = f"{article_match.group(2)} {article_match.group(1)}"
    return title, year


def open_csv(archive, name):
    return csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8", newline=""))


def weighted_rating(avg, count, global_avg, minimum_votes=1200):
    return (count / (count + minimum_votes)) * avg + (minimum_votes / (count + minimum_votes)) * global_avg


def genre_palette(genres):
    if "Sci-Fi" in genres:
        return ["#0ea5e9", "#7c3aed"]
    if "Crime" in genres or "Thriller" in genres:
        return ["#ef4444", "#a855f7"]
    if "Animation" in genres or "Children" in genres:
        return ["#f59e0b", "#10b981"]
    if "Romance" in genres:
        return ["#ec4899", "#f97316"]
    if "Adventure" in genres or "Fantasy" in genres:
        return ["#22c55e", "#06b6d4"]
    if "Drama" in genres:
        return ["#a855f7", "#334155"]
    return ["#64748b", "#111827"]


def generated_description(title, year, genres, tags):
    genre_text = ", ".join(GENRE_RU.get(genre, genre.lower()) for genre in genres[:3]) or "кино"
    tag_text = ", ".join(tag for tag in tags[:4] if tag.lower() not in TAG_STOPWORDS)
    year_text = f" {year} года" if year else ""
    if tag_text:
        return (
            f"{title} — фильм{year_text} в духе {genre_text}. "
            f"В подборке MovieLens его чаще связывают с темами: {tag_text}; "
            "поэтому он хорошо подходит для контентного сравнения с вашим профилем."
        )
    return (
        f"{title} — фильм{year_text} в жанрах: {genre_text}. "
        "Рекомендация строится по сочетанию жанрового профиля, средней оценки и сходства с фильмами, которые вы уже оценили."
    )


def build_dataset(zip_path, limit):
    with zipfile.ZipFile(zip_path) as archive:
        movies = {}
        for row in open_csv(archive, "ml-32m/movies.csv"):
            movie_id = int(row["movieId"])
            title, year = parse_title(row["title"])
            genres = [] if row["genres"] == "(no genres listed)" else row["genres"].split("|")
            movies[movie_id] = {
                "id": movie_id,
                "title": title,
                "year": year,
                "genres": genres,
            }

        links = {}
        for row in open_csv(archive, "ml-32m/links.csv"):
            movie_id = int(row["movieId"])
            tmdb_id = row.get("tmdbId") or ""
            imdb_id = row.get("imdbId") or ""
            links[movie_id] = {
                "tmdbId": int(tmdb_id) if tmdb_id.isdigit() else None,
                "imdbId": imdb_id.zfill(7) if imdb_id else None,
            }

        counts = defaultdict(int)
        sums = defaultdict(float)
        total_count = 0
        total_sum = 0.0
        for row in open_csv(archive, "ml-32m/ratings.csv"):
            movie_id = int(row["movieId"])
            rating = float(row["rating"])
            counts[movie_id] += 1
            sums[movie_id] += rating
            total_count += 1
            total_sum += rating

        global_avg = total_sum / total_count
        ranked = []
        for movie_id, count in counts.items():
            if movie_id not in movies:
                continue
            avg = sums[movie_id] / count
            ranked.append((weighted_rating(avg, count, global_avg), count, avg, movie_id))

        ranked.sort(reverse=True)
        selected = {movie_id for _, _, _, movie_id in ranked[:limit]}
        selected.update(movie_id for movie_id in REQUIRED_IDS if movie_id in movies)

        tag_counts = {movie_id: defaultdict(int) for movie_id in selected}
        for row in open_csv(archive, "ml-32m/tags.csv"):
            movie_id = int(row["movieId"])
            if movie_id not in selected:
                continue
            tag = row["tag"].strip().lower()
            if len(tag) < 3 or tag in TAG_STOPWORDS:
                continue
            tag_counts[movie_id][tag] += 1

        norms = defaultdict(float)
        dots = defaultdict(float)
        current_user = None
        bucket = []

        def flush_bucket():
            if not bucket:
                return
            for movie_id, rating in bucket:
                norms[movie_id] += rating * rating
            for (left_id, left_rating), (right_id, right_rating) in itertools.combinations(bucket, 2):
                key = (left_id, right_id) if left_id < right_id else (right_id, left_id)
                dots[key] += left_rating * right_rating

        for row in open_csv(archive, "ml-32m/ratings.csv"):
            user_id = int(row["userId"])
            if current_user is None:
                current_user = user_id
            if user_id != current_user:
                flush_bucket()
                bucket = []
                current_user = user_id

            movie_id = int(row["movieId"])
            if movie_id in selected:
                bucket.append((movie_id, float(row["rating"])))
        flush_bucket()

    similarities = {movie_id: [] for movie_id in selected}
    for (left_id, right_id), dot in dots.items():
        denominator = math.sqrt(norms[left_id] * norms[right_id])
        if denominator:
            similarity = dot / denominator
            similarities[left_id].append({"id": right_id, "score": round(similarity, 4)})
            similarities[right_id].append({"id": left_id, "score": round(similarity, 4)})

    max_count = max(counts[movie_id] for movie_id in selected)
    output_movies = []
    for movie_id in selected:
        count = counts[movie_id]
        avg = sums[movie_id] / count
        base = movies[movie_id]
        link = links.get(movie_id, {})
        genres = base["genres"]
        tags = [
            tag
            for tag, _ in sorted(tag_counts.get(movie_id, {}).items(), key=lambda item: (-item[1], item[0]))[:12]
        ]
        output_movies.append(
            {
                "id": movie_id,
                "title": base["title"],
                "year": base["year"],
                "genres": genres,
                "averageRating": round(avg, 2),
                "ratingCount": count,
                "weightedScore": round(weighted_rating(avg, count, total_sum / total_count), 4),
                "popularity": round(math.log1p(count) / math.log1p(max_count), 4),
                "poster": POSTERS.get(movie_id),
                "palette": genre_palette(genres),
                "tags": tags,
                "description": DESCRIPTIONS.get(movie_id, generated_description(base["title"], base["year"], genres, tags)),
                "tmdbId": link.get("tmdbId"),
                "imdbId": link.get("imdbId"),
                "similar": sorted(similarities[movie_id], key=lambda item: item["score"], reverse=True)[:12],
            }
        )

    output_movies.sort(key=lambda item: item["weightedScore"], reverse=True)
    return {
        "source": "MovieLens ml-32m",
        "generatedFrom": str(zip_path),
        "movieCount": len(output_movies),
        "globalAverage": round(total_sum / total_count, 4),
        "defaultRecommendations": [318, 79132, 2959],
        "movies": output_movies,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", default=str(Path.home() / "Downloads" / "ml-32m.zip"))
    parser.add_argument("--out", default="data/movies.json")
    parser.add_argument("--limit", type=int, default=140)
    args = parser.parse_args()

    data = build_dataset(Path(args.zip), args.limit)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} with {data['movieCount']} movies")


if __name__ == "__main__":
    main()

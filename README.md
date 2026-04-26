# MovieRec

Рабочий прототип гибридной рекомендательной системы фильмов по материалам курсовой работы.

Данные MovieLens используются из набора GroupLens. Постеры, русские описания, актеры и режиссеры могут подтягиваться через TMDb API; при использовании данных/изображений TMDb в интерфейсе сохранена атрибуция TMDb.

## Что внутри

- `backend/` — Flask API и SQLite-интеграция.
- `data/movierec.sqlite3` — база данных с пользователями, фильмами, метаданными, оценками и рекомендациями.
- `data/movies.json` — компактная выборка MovieLens ml-32m с тегами, описаниями, постерами и item-item сходством.
- `index.html`, `styles.css`, `app.js` — frontend MovieRec, подключенный к API.
- `extension/` — браузерное расширение Manifest V3, которое ходит в backend API.
- `scripts/build_data.py` — пересборка компактного датасета из `ml-32m.zip`.
- `scripts/evaluate_model.py` — оффлайн-оценка RMSE, Precision@5, Recall@5, F1@5.
- `scripts/enrich_tmdb.py` — обогащение фильмов через TMDb API.


## API

- `POST /api/register` — регистрация пользователя.
- `POST /api/login` — вход.
- `POST /api/logout` — выход.
- `GET /api/session` — текущий пользователь и его оценки.
- `GET /api/movies?q=matrix` — поиск фильмов.
- `GET /api/movies/<movie_id>` — детали фильма и похожие фильмы.
- `POST /api/ratings` — сохранить оценку.
- `DELETE /api/ratings/<movie_id>` — удалить оценку.
- `GET /api/recommendations?alpha=0.7&limit=10` — гибридные рекомендации.
- `GET /api/search/semantic?q=фильм про сны и ограбление` — поиск по описанию.
- `POST /api/enrich/tmdb/<movie_id>` — обогащение одного фильма через TMDb.
- `GET /api/evaluation` — последний отчет оффлайн-тестирования.


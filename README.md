# MovieRec

Рабочий прототип гибридной рекомендательной системы фильмов по материалам курсовой работы.

Данные MovieLens используются из набора GroupLens. Постеры, русские описания, актеры и режиссеры подтягиваются через TMDb API; при использовании данных/изображений TMDb в интерфейсе сохранена атрибуция TMDb.

## Что внутри

- `backend/` — Flask API и SQLite-интеграция.
- `data/movies.json` — выборка MovieLens ml-32m, расширенная фильмами из TMDb.
- `index.html`, `styles.css`, `app.js` — frontend MovieRec.
- `extension/` — браузерное расширение Manifest V3.
- `scripts/build_data.py` — пересборка MovieLens-выборки.
- `scripts/enrich_tmdb.py` — обогащение фильмов через TMDb.
- `scripts/expand_tmdb.py` — добавление новых фильмов из TMDb.
- `scripts/evaluate_model.py` — оффлайн-метрики RMSE, Precision@5, Recall@5, F1@5.

## Запуск

```powershell
cd "C:\Users\azzma\Documents\New project"
& ".\start_server.ps1"
```

После запуска откройте `http://localhost:8000`.

## API

- `POST /api/register` — регистрация пользователя.
- `POST /api/login` — вход.
- `GET /api/session` — текущий пользователь и оценки.
- `GET /api/movies` — каталог и фильтры.
- `GET /api/movies/<movie_id>` — детали фильма и похожие фильмы.
- `POST /api/ratings` — сохранить оценку.
- `GET /api/recommendations` — гибридные рекомендации.
- `GET /api/search/semantic` — поиск по описанию.
- `GET /api/evaluation` — отчет оффлайн-тестирования.

## TMDb

Создайте `.env` по образцу `.env.example` и добавьте `TMDB_API_KEY`.

Обогатить существующие фильмы:

```powershell
& "C:\Users\azzma\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\enrich_tmdb.py --limit 220 --language ru-RU
```

Расширить выборку новыми фильмами из TMDb:

```powershell
& "C:\Users\azzma\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\expand_tmdb.py --endpoint /movie/top_rated --pages 12 --max-new 80 --min-votes 1000 --language ru-RU
```

Новые TMDb-only фильмы участвуют в каталоге, нейропоиске и content-based рекомендациях. Коллаборативная часть MovieLens для них появится только если фильм есть в MovieLens.

## Embeddings

OpenAI:

```powershell
$env:EMBEDDING_PROVIDER="openai"
$env:OPENAI_API_KEY="ваш_ключ"
Invoke-RestMethod -Method Post "http://localhost:8000/api/embeddings/rebuild?provider=openai&limit=120"
```

Локальная модель без OpenAI API:

```powershell
& "C:\Users\azzma\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pip install sentence-transformers
$env:EMBEDDING_PROVIDER="local"
Invoke-RestMethod -Method Post "http://localhost:8000/api/embeddings/rebuild?provider=local&limit=120"
```

Без построенных embeddings сайт использует TF-IDF fallback.

## Расширение

1. Откройте `edge://extensions` или `chrome://extensions`.
2. Включите режим разработчика.
3. Выберите `Load unpacked` / `Загрузить распакованное`.
4. Укажите папку `C:\Users\azzma\Documents\New project\extension`.

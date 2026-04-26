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

## Запуск backend

```powershell
cd "C:\Users\azzma\Documents\New project"
& "C:\Users\azzma\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m backend.app
```

Или короче:

```powershell
& "C:\Users\azzma\Documents\New project\start_server.ps1"
```

После запуска откройте:

```text
http://localhost:8000
```

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

## Пересборка данных

```powershell
& "C:\Users\azzma\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\build_data.py --zip "C:\Users\azzma\Downloads\ml-32m.zip" --out data\movies.json --limit 220
```

## Оффлайн-тестирование

```powershell
& "C:\Users\azzma\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\evaluate_model.py --zip "C:\Users\azzma\Downloads\ml-32m.zip" --max-users 500 --out reports\evaluation.json
```

## TMDb

Для обогащения фильмов задайте переменную окружения:

```powershell
$env:TMDB_API_KEY="ваш_ключ"
& "C:\Users\azzma\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\enrich_tmdb.py --limit 50 --language ru-RU
```

Можно также создать файл `.env` по образцу `.env.example`: backend сам прочитает `TMDB_API_KEY`, `OPENAI_API_KEY` и `OPENAI_EMBEDDING_MODEL`.

## Embeddings

Для настоящего нейропоиска есть два режима.

### OpenAI

Задайте `EMBEDDING_PROVIDER=openai` и `OPENAI_API_KEY`, запустите backend и один раз перестройте эмбеддинги:

```powershell
$env:OPENAI_API_KEY="ваш_ключ"
Invoke-RestMethod -Method Post "http://localhost:8000/api/embeddings/rebuild?provider=openai&limit=120"
```

### Локальная модель

Можно обойтись без OpenAI API и использовать `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Для этого установите опциональную зависимость:

```powershell
& "C:\Users\azzma\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pip install sentence-transformers
```

Затем задайте:

```powershell
$env:EMBEDDING_PROVIDER="local"
$env:LOCAL_EMBEDDING_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
Invoke-RestMethod -Method Post "http://localhost:8000/api/embeddings/rebuild?provider=local&limit=120"
```

После этого `GET /api/search/semantic` будет работать в режиме `openai_embeddings` или `local_embeddings`; без построенных эмбеддингов сайт использует TF-IDF fallback.

## Установка расширения

1. Откройте `edge://extensions` или `chrome://extensions`.
2. Включите режим разработчика.
3. Выберите `Load unpacked` / `Загрузить распакованное`.
4. Укажите папку `C:\Users\azzma\Documents\New project\extension`.

Расширение ожидает, что backend запущен на `http://localhost:8000`.

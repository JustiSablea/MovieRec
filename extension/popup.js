let API_BASE = "http://127.0.0.1:8000";

const state = {
  selectedMovie: null,
  detectedMovie: null,
  pageContext: null,
  movies: [],
  session: null,
};

const els = {};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  cacheElements();
  wireEvents();
  await resolveApiBase();
  await loadSession();
  await detectActivePageMovie();
  await renderRecommendations();
}

function cacheElements() {
  els.search = document.querySelector("#movieSearch");
  els.rating = document.querySelector("#ratingValue");
  els.addMovie = document.querySelector("#addMovie");
  els.suggestions = document.querySelector("#suggestions");
  els.detectedMovie = document.querySelector("#detectedMovie");
  els.pageStatus = document.querySelector("#pageStatus");
  els.profileList = document.querySelector("#profileList");
  els.recommendations = document.querySelector("#recommendations");
  els.clearProfile = document.querySelector("#clearProfile");
  els.openSite = document.querySelector("#openSite");
  els.modelLabel = document.querySelector("#modelLabel");
}

function wireEvents() {
  els.search.addEventListener("input", debounce(renderSuggestions, 150));
  els.addMovie.addEventListener("click", addSelectedMovie);
  els.clearProfile.addEventListener("click", async () => {
    if (!state.session?.ratings?.length) return;
    for (const rating of state.session.ratings) {
      await api(`/api/ratings/${rating.movie_id}`, { method: "DELETE" });
    }
    await loadSession();
    await renderRecommendations();
  });
  els.openSite.addEventListener("click", () => {
    if (typeof chrome !== "undefined" && chrome.tabs) chrome.tabs.create({ url: `${API_BASE}/#recommendations` });
    else window.open(`${API_BASE}/#recommendations`, "_blank");
  });
  els.detectedMovie.addEventListener("click", handleDetectedAction);
}

async function resolveApiBase() {
  for (const base of ["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:8001"]) {
    try {
      const response = await fetch(`${base}/api/version`, { credentials: "include" });
      if (response.ok) {
        API_BASE = base;
        return;
      }
    } catch {
      // Try next local server.
    }
  }
}

async function loadSession() {
  try {
    state.session = await api("/api/session");
    renderProfile();
  } catch {
    state.session = null;
    els.profileList.innerHTML = '<div class="empty">Запустите сайт MovieRec</div>';
  }
}

async function detectActivePageMovie() {
  const context = await getActivePageContext();
  state.pageContext = context;
  if (!context?.candidates?.length) {
    renderDetectedMovie(null, "Фильм на странице не найден");
    return;
  }
  for (const candidate of context.candidates.slice(0, 5)) {
    const payload = await api(`/api/movies?q=${encodeURIComponent(candidate)}&limit=5`).catch(() => ({ movies: [] }));
    const exact = findBestPageMatch(candidate, payload.movies || []);
    if (exact) {
      state.detectedMovie = exact;
      renderDetectedMovie(exact, context.host || "страница");
      return;
    }
  }
  state.detectedMovie = null;
  renderDetectedMovie(null, "Точного совпадения в базе нет");
}

async function getActivePageContext() {
  if (typeof chrome === "undefined" || !chrome.tabs) return null;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return null;
  try {
    return await chrome.tabs.sendMessage(tab.id, { type: "MOVIEREC_PAGE_CONTEXT" });
  } catch {
    return {
      title: tab.title || "",
      url: tab.url || "",
      host: new URL(tab.url || "http://local").host,
      candidates: cleanTitleCandidates(tab.title || ""),
    };
  }
}

function renderDetectedMovie(movie, status) {
  els.pageStatus.textContent = status || "";
  if (!movie) {
    els.detectedMovie.className = "detected-card is-empty";
    const candidate = state.pageContext?.candidates?.[0];
    els.detectedMovie.innerHTML = candidate
      ? `
        <div>Похоже, это “${escapeHtml(candidate)}”, но точного совпадения в локальной базе MovieRec нет.</div>
        <button class="primary request-missing" type="button" data-detected-action="request">Отправить заявку</button>
      `
      : "Откройте страницу фильма на IMDb, TMDb, Кинопоиске, YouTube или выделите название на странице.";
    return;
  }
  els.detectedMovie.className = "detected-card";
  els.detectedMovie.innerHTML = `
    <div class="detected-title">
      <strong>${escapeHtml(formatTitle(movie))}</strong>
      <small>${Number(movie.averageRating || 0).toFixed(1)}</small>
    </div>
    <div class="detected-meta">${escapeHtml(formatGenres(movie.genres))}</div>
    <div class="detected-actions">
      <button class="primary" type="button" data-detected-action="rate">Оценить ${escapeHtml(els.rating.value)}</button>
      <button type="button" data-detected-action="similar">Похожие</button>
      <button type="button" data-detected-action="open">Карточка</button>
    </div>
  `;
}

async function handleDetectedAction(event) {
  const button = event.target.closest("[data-detected-action]");
  if (!button) return;
  const action = button.dataset.detectedAction;
  if (action === "request") {
    await requestMissingMovie();
    return;
  }
  if (!state.detectedMovie) return;
  if (action === "open") {
    openTab(`${API_BASE}/#movie/${state.detectedMovie.id}`);
    return;
  }
  if (action === "similar") {
    openTab(`${API_BASE}/#movie/${state.detectedMovie.id}`);
    return;
  }
  if (action === "rate") {
    if (!state.session?.user) {
      openTab(`${API_BASE}/#home`);
      return;
    }
    await api("/api/ratings", {
      method: "POST",
      body: JSON.stringify({ movieId: state.detectedMovie.id, rating: Number(els.rating.value) }),
    });
    await loadSession();
    await renderRecommendations();
    renderDetectedMovie(state.detectedMovie, "оценка сохранена");
  }
}

async function requestMissingMovie() {
  const candidate = state.pageContext?.candidates?.[0];
  if (!candidate) return;
  const title = candidate.replace(/\(\d{4}(?:\s*[–-]\s*[^)]*)?\)/g, "").trim().slice(0, 120);
  const year = extractYear([candidate, state.pageContext?.title].filter(Boolean).join(" "));
  const note = `Заявка из расширения. Страница: ${state.pageContext?.url || "не указана"}`;
  try {
    await api("/api/movie-requests", {
      method: "POST",
      body: JSON.stringify({ title, year, note }),
    });
    els.pageStatus.textContent = "Заявка отправлена";
    els.detectedMovie.className = "detected-card is-empty";
    els.detectedMovie.innerHTML = "Заявка ушла администратору. Ее статус можно посмотреть в личном кабинете MovieRec.";
  } catch (error) {
    els.pageStatus.textContent = "Не удалось отправить";
    els.detectedMovie.className = "detected-card is-empty";
    els.detectedMovie.innerHTML = `${escapeHtml(error.message || "Ошибка отправки заявки")}. Проверьте, что сайт запущен и вы вошли в аккаунт.`;
  }
}

function renderProfile() {
  if (!state.session?.user) {
    els.profileList.innerHTML = '<div class="empty">Войдите на сайте</div>';
    return;
  }
  const ratings = state.session.ratings || [];
  els.profileList.innerHTML = ratings.length
    ? ratings
        .map(
          (entry) => `
            <div class="profile-pill">
              <strong>${escapeHtml(entry.title)}${entry.year ? ` (${entry.year})` : ""}</strong>
              <span>${Number(entry.rating).toFixed(1)}</span>
            </div>
          `,
        )
        .join("")
    : '<div class="empty">Добавьте фильм</div>';
}

async function renderRecommendations() {
  const payload = await api("/api/recommendations?alpha=0.7&limit=4");
  const recs = payload.recommendations || [];
  els.modelLabel.textContent = state.session?.user ? "API · CF 70%" : "Cold start";
  els.recommendations.innerHTML = recs
    .map(
      (movie) => `
        <button class="movie-row" type="button" data-id="${movie.id}">
          <span>
            <strong>${escapeHtml(formatTitle(movie))}</strong>
            <span>${escapeHtml(movie.reason || movie.genres.slice(0, 2).join(", "))}</span>
          </span>
          <small>${movie.averageRating.toFixed(1)}</small>
        </button>
      `,
    )
    .join("");
  [...els.recommendations.querySelectorAll("[data-id]")].forEach((button) => {
    button.addEventListener("click", () => {
      openTab(`${API_BASE}/#movie/${button.dataset.id}`);
    });
  });
}

async function renderSuggestions() {
  const query = els.search.value.trim();
  if (!query) {
    els.suggestions.classList.remove("is-open");
    els.suggestions.innerHTML = "";
    return;
  }
  const payload = await api(`/api/movies?q=${encodeURIComponent(query)}&limit=5`);
  state.movies = payload.movies || [];
  if (!state.movies.length) {
    els.suggestions.classList.remove("is-open");
    els.suggestions.innerHTML = "";
    return;
  }
  els.suggestions.innerHTML = state.movies
    .map(
      (movie) => `
        <button class="suggestion" type="button" data-id="${movie.id}">
          <span>
            <strong>${escapeHtml(formatTitle(movie))}</strong>
            <span>${escapeHtml(movie.genres.slice(0, 2).join(", "))}</span>
          </span>
          <span>${movie.averageRating.toFixed(1)}</span>
        </button>
      `,
    )
    .join("");
  els.suggestions.classList.add("is-open");
  [...els.suggestions.querySelectorAll("[data-id]")].forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedMovie = state.movies.find((movie) => movie.id === Number(button.dataset.id));
      els.search.value = formatTitle(state.selectedMovie);
      els.suggestions.classList.remove("is-open");
    });
  });
}

async function addSelectedMovie() {
  const movie = state.selectedMovie || state.movies[0];
  if (!movie) return;
  if (!state.session?.user) {
    openTab(`${API_BASE}/#home`);
    return;
  }
  await api("/api/ratings", {
    method: "POST",
    body: JSON.stringify({ movieId: movie.id, rating: Number(els.rating.value) }),
  });
  state.selectedMovie = null;
  els.search.value = "";
  await loadSession();
  await renderRecommendations();
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || payload.message || "API error");
  return payload;
}

function formatTitle(movie) {
  return `${movie.title}${movie.year ? ` (${movie.year})` : ""}`;
}

function formatGenres(genres = []) {
  return genres.slice(0, 2).join(", ");
}

function openTab(url) {
  if (typeof chrome !== "undefined" && chrome.tabs) chrome.tabs.create({ url });
  else window.open(url, "_blank");
}

function findBestPageMatch(candidate, movies) {
  const normalized = normalize(candidate);
  if (!normalized) return null;
  return (
    movies.find((movie) => normalize(movie.title) === normalized) ||
    movies.find((movie) => {
      const title = normalize(movie.title);
      if (!title || title.length < 4) return false;
      return normalized.startsWith(`${title} `) || normalized.includes(` ${title} `) || normalized.endsWith(` ${title}`);
    }) ||
    null
  );
}

function cleanTitleCandidates(title) {
  const values = Array.isArray(title) ? title : [title];
  return [
    ...new Set(
      values
        .flatMap((value) => {
          const raw = String(value || "").trim();
          const cleaned = raw
            .replace(/\s*[-|—]\s*(IMDb|Кинопоиск|TMDb|YouTube|Google|Wikipedia|Википедия).*$/i, "")
            .replace(/\s+(фильм|сериал|аниме|мультфильм)\b.*$/i, "")
            .replace(/\(\d{4}(?:\s*[–-]\s*[^)]*)?\)/g, "")
            .replace(/\b\d{4}\b.*$/g, "")
            .trim();
          return [cleaned, raw];
        })
        .filter((value) => value.length >= 2 && value.length <= 120),
    ),
  ];
}

function normalize(value) {
  return String(value).toLowerCase().replace(/ё/g, "е").replace(/[^a-zа-я0-9]+/g, " ").trim();
}

function extractYear(value) {
  const match = String(value || "").match(/\b(19\d{2}|20\d{2})\b/);
  return match ? Number(match[1]) : "";
}

function debounce(callback, delay) {
  let timer = 0;
  return () => {
    clearTimeout(timer);
    timer = setTimeout(callback, delay);
  };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

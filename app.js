const API = {
  session: "/api/session",
  register: "/api/register",
  login: "/api/login",
  logout: "/api/logout",
  movies: "/api/movies",
  ratings: "/api/ratings",
  recommendations: "/api/recommendations",
  semantic: "/api/search/semantic",
  genres: "/api/genres",
  movieRequests: "/api/movie-requests",
};

const ALPHA_KEY = "movierec.alpha";

const state = {
  user: null,
  profile: [],
  scores: new Map(),
  alpha: Math.min(Number(localStorage.getItem(ALPHA_KEY)) || 0.65, 0.75),
  selectedPreferenceMovie: null,
  activeMovie: null,
  authMode: "login",
};

const els = {};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  cacheElements();
  wireEvents();
  els.alphaSlider.value = state.alpha;
  els.alphaValue.textContent = state.alpha.toFixed(2);
  await loadSession();
  await renderAll();
  await hydrateRoute();
}

function cacheElements() {
  els.navLinks = [...document.querySelectorAll("[data-route]")];
  els.screens = [...document.querySelectorAll("[data-screen]")];
  els.searchInput = document.querySelector("#movieSearch");
  els.searchResults = document.querySelector("#searchResults");
  els.preferenceForm = document.querySelector("#preferenceForm");
  els.preferenceSearch = document.querySelector("#preferenceSearch");
  els.preferenceSuggestions = document.querySelector("#preferenceSuggestions");
  els.ratingSelect = document.querySelector("#ratingSelect");
  els.alphaSlider = document.querySelector("#alphaSlider");
  els.alphaValue = document.querySelector("#alphaValue");
  els.buildRecommendations = document.querySelector("#buildRecommendations");
  els.resetProfile = document.querySelector("#resetProfile");
  els.starterMovies = document.querySelector("#starterMovies");
  els.ratedList = document.querySelector("#ratedList");
  els.ratedCount = document.querySelector("#ratedCount");
  els.recommendationsGrid = document.querySelector("#recommendationsGrid");
  els.modelStatus = document.querySelector("#modelStatus");
  els.tuneProfile = document.querySelector("#tuneProfile");
  els.catalogQuery = document.querySelector("#catalogQuery");
  els.catalogGenre = document.querySelector("#catalogGenre");
  els.catalogYearFrom = document.querySelector("#catalogYearFrom");
  els.catalogYearTo = document.querySelector("#catalogYearTo");
  els.catalogMinRating = document.querySelector("#catalogMinRating");
  els.catalogSort = document.querySelector("#catalogSort");
  els.catalogHasPoster = document.querySelector("#catalogHasPoster");
  els.catalogGrid = document.querySelector("#catalogGrid");
  els.semanticInput = document.querySelector("#semanticInput");
  els.semanticSearchButton = document.querySelector("#semanticSearchButton");
  els.semanticResults = document.querySelector("#semanticResults");
  els.movieRequestForm = document.querySelector("#movieRequestForm");
  els.requestTitle = document.querySelector("#requestTitle");
  els.requestYear = document.querySelector("#requestYear");
  els.requestNote = document.querySelector("#requestNote");
  els.movieModal = document.querySelector("#movieModal");
  els.modalPoster = document.querySelector("#modalPoster");
  els.modalRating = document.querySelector("#modalRating");
  els.modalTitle = document.querySelector("#modalTitle");
  els.modalMeta = document.querySelector("#modalMeta");
  els.modalDescription = document.querySelector("#modalDescription");
  els.cfBar = document.querySelector("#cfBar");
  els.contentBar = document.querySelector("#contentBar");
  els.modalAddMovie = document.querySelector("#modalAddMovie");
  els.modalImdb = document.querySelector("#modalImdb");
  els.closeMovieModal = document.querySelector("#closeMovieModal");
  els.authModal = document.querySelector("#authModal");
  els.authTitle = document.querySelector("#authTitle");
  els.authSubtitle = document.querySelector("#authSubtitle");
  els.authForm = document.querySelector("#authForm");
  els.authName = document.querySelector("#authName");
  els.authPassword = document.querySelector("#authPassword");
  els.saveAuth = document.querySelector("#saveAuth");
  els.switchAuthMode = document.querySelector("#switchAuthMode");
  els.closeAuthModal = document.querySelector("#closeAuthModal");
  els.loginButton = document.querySelector("#loginButton");
  els.registerButton = document.querySelector("#registerButton");
  els.toast = document.querySelector("#toast");
  els.detailsScreen = document.querySelector("#detailsScreen");
  els.detailPoster = document.querySelector("#detailPoster");
  els.detailRating = document.querySelector("#detailRating");
  els.detailTitle = document.querySelector("#detailsTitle");
  els.detailMeta = document.querySelector("#detailMeta");
  els.detailDescription = document.querySelector("#detailDescription");
  els.detailRatingSelect = document.querySelector("#detailRatingSelect");
  els.detailSaveRating = document.querySelector("#detailSaveRating");
  els.similarMovies = document.querySelector("#similarMovies");
  els.backToRecommendations = document.querySelector("#backToRecommendations");
  els.openExplain = document.querySelector("#openExplain");
  els.backToDetails = document.querySelector("#backToDetails");
  els.explainSummary = document.querySelector("#explainSummary");
  els.explainFormula = document.querySelector("#explainFormula");
  els.explainNeighbors = document.querySelector("#explainNeighbors");
  els.metricsGrid = document.querySelector("#metricsGrid");
  els.metricsNote = document.querySelector("#metricsNote");
}

function wireEvents() {
  els.navLinks.forEach((link) => {
    link.addEventListener("click", () => showScreen(link.dataset.route));
  });

  els.searchInput.addEventListener("input", debounce(async () => {
    const movies = await searchMovies(els.searchInput.value);
    renderMovieOptions(movies, els.searchResults, async (movie) => {
      await openMoviePage(movie.id);
      els.searchInput.value = "";
      closeSearchPanels();
    });
  }, 120));

  els.preferenceSearch.addEventListener("input", debounce(async () => {
    state.selectedPreferenceMovie = null;
    const movies = await searchMovies(els.preferenceSearch.value);
    renderMovieOptions(movies, els.preferenceSuggestions, (movie) => {
      state.selectedPreferenceMovie = movie;
      els.preferenceSearch.value = formatMovieTitle(movie);
      els.preferenceSuggestions.classList.remove("is-open");
    });
  }, 120));

  els.preferenceForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const movie = state.selectedPreferenceMovie || (await searchMovies(els.preferenceSearch.value, 1))[0];
    if (!movie) {
      showToast("Фильм не найден в базе");
      return;
    }
    await addToProfile(movie.id, Number(els.ratingSelect.value));
    els.preferenceSearch.value = "";
    state.selectedPreferenceMovie = null;
    els.preferenceSuggestions.classList.remove("is-open");
  });

  els.alphaSlider.addEventListener("input", async () => {
    state.alpha = Number(els.alphaSlider.value);
    localStorage.setItem(ALPHA_KEY, String(state.alpha));
    els.alphaValue.textContent = state.alpha.toFixed(2);
    await renderRecommendations();
  });

  els.buildRecommendations.addEventListener("click", async () => {
    await renderRecommendations();
    showScreen("recommendations");
  });
  els.tuneProfile.addEventListener("click", () => showScreen("home"));
  [els.catalogQuery, els.catalogGenre, els.catalogYearFrom, els.catalogYearTo, els.catalogMinRating, els.catalogSort, els.catalogHasPoster].forEach((control) => {
    control.addEventListener("input", debounce(renderCatalog, 180));
    control.addEventListener("change", renderCatalog);
  });
  els.catalogGrid.addEventListener("click", async (event) => {
    const card = event.target.closest("[data-movie-id]");
    if (card) await openMoviePage(Number(card.dataset.movieId));
  });
  els.semanticSearchButton.addEventListener("click", renderSemanticSearch);
  els.semanticInput.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") await renderSemanticSearch();
  });
  els.semanticResults.addEventListener("click", async (event) => {
    const card = event.target.closest("[data-movie-id]");
    if (card) await openMoviePage(Number(card.dataset.movieId));
  });
  els.movieRequestForm.addEventListener("submit", handleMovieRequest);
  els.resetProfile.addEventListener("click", async () => {
    if (!state.profile.length) return;
    for (const entry of [...state.profile]) {
      await api(`${API.ratings}/${entry.movie_id}`, { method: "DELETE" });
    }
    state.profile = [];
    await renderAll();
    showToast("Профиль очищен");
  });

  els.starterMovies.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-starter-id]");
    if (!button) return;
    await addToProfile(Number(button.dataset.starterId), Number(button.dataset.rating || 5));
  });

  els.recommendationsGrid.addEventListener("click", async (event) => {
    const card = event.target.closest("[data-movie-id]");
    if (card) await openMoviePage(Number(card.dataset.movieId));
  });
  els.recommendationsGrid.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest("[data-movie-id]");
    if (!card) return;
    event.preventDefault();
    await openMoviePage(Number(card.dataset.movieId));
  });

  els.similarMovies.addEventListener("click", async (event) => {
    const card = event.target.closest("[data-movie-id]");
    if (card) await openMoviePage(Number(card.dataset.movieId));
  });
  els.backToRecommendations.addEventListener("click", () => showScreen("recommendations"));
  els.detailSaveRating.addEventListener("click", async () => {
    if (state.activeMovie) await addToProfile(state.activeMovie.id, Number(els.detailRatingSelect.value));
  });
  els.openExplain.addEventListener("click", async () => {
    if (state.activeMovie) await openExplainPage(state.activeMovie.id);
  });
  els.backToDetails.addEventListener("click", async () => {
    if (state.activeMovie) await openMoviePage(state.activeMovie.id);
  });

  els.ratedList.addEventListener("click", async (event) => {
    const removeButton = event.target.closest("[data-remove-id]");
    if (removeButton) await removeFromProfile(Number(removeButton.dataset.removeId));
  });

  els.closeMovieModal.addEventListener("click", closeMovieModal);
  els.movieModal.addEventListener("click", (event) => {
    if (event.target === els.movieModal) closeMovieModal();
  });
  els.modalAddMovie.addEventListener("click", async () => {
    if (state.activeMovie) await addToProfile(state.activeMovie.id, 5);
  });

  els.loginButton.addEventListener("click", async () => {
    if (state.user) {
      await api(API.logout, { method: "POST" });
      state.user = null;
      state.profile = [];
      await renderAll();
      showToast("Вы вышли из аккаунта");
      return;
    }
    openAuth("login");
  });
  els.registerButton.addEventListener("click", () => {
    if (state.user) {
      showToast(`Вы вошли как ${state.user.username}`);
      return;
    }
    openAuth("register");
  });
  els.authForm.addEventListener("submit", handleAuthSubmit);
  els.switchAuthMode.addEventListener("click", () => {
    openAuth(state.authMode === "login" ? "register" : "login");
  });
  els.closeAuthModal.addEventListener("click", closeAuth);
  els.authModal.addEventListener("click", (event) => {
    if (event.target === els.authModal) closeAuth();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMovieModal();
      closeAuth();
      closeSearchPanels();
    }
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-box") && !event.target.closest(".preference-panel")) {
      closeSearchPanels();
    }
  });

  window.addEventListener("hashchange", () => {
    void hydrateRoute();
  });
}

async function loadSession() {
  const payload = await api(API.session);
  state.user = payload.user;
  state.profile = payload.ratings || [];
}

async function renderAll() {
  renderAuthState();
  await renderGenres();
  await renderCatalog();
  await renderStarterMovies();
  renderProfile();
  await renderRecommendations();
  await renderMetrics();
}

function renderAuthState() {
  if (state.user) {
    els.loginButton.textContent = "Выйти";
    els.registerButton.querySelector("span").textContent = state.user.username;
    return;
  }
  els.loginButton.textContent = "Войти";
  els.registerButton.querySelector("span").textContent = "Регистрация";
}

async function renderStarterMovies() {
  const ids = [2571, 79132, 2959, 318, 356, 58559];
  const movies = await Promise.all(ids.map((id) => getMovie(id).catch(() => null)));
  els.starterMovies.innerHTML = movies
    .filter(Boolean)
    .map(
      (movie) =>
        `<button class="starter-chip" type="button" data-starter-id="${movie.id}" data-rating="5">${escapeHtml(
          movie.title,
        )}</button>`,
    )
    .join("");
}

function renderProfile() {
  els.ratedCount.textContent = String(state.profile.length);
  if (!state.user) {
    els.ratedList.innerHTML = '<div class="empty-state">Войдите или зарегистрируйтесь, чтобы сохранить оценки в базе</div>';
    return;
  }
  if (!state.profile.length) {
    els.ratedList.innerHTML = '<div class="empty-state">Профиль пока пуст</div>';
    return;
  }

  els.ratedList.innerHTML = state.profile
    .map(
      (entry) => `
        <div class="rated-item">
          <strong>${escapeHtml(formatRatingTitle(entry))}</strong>
          <span>${Number(entry.rating).toFixed(1)}</span>
          <button type="button" data-remove-id="${entry.movie_id}" aria-label="Удалить ${escapeHtml(entry.title)}">
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" />
            </svg>
          </button>
        </div>
      `,
    )
    .join("");
}

async function renderRecommendations() {
  const payload = await api(`${API.recommendations}?alpha=${state.alpha}&limit=${state.profile.length ? 12 : 6}`);
  const recommendations = payload.recommendations || [];
  state.scores.clear();
  recommendations.forEach((movie) => state.scores.set(movie.id, movie));
  els.recommendationsGrid.innerHTML = recommendations.map(renderMovieCard).join("");
  els.modelStatus.textContent = `Гибридная модель: CF до ${Math.round(state.alpha * 100)}% · Content от ${Math.round(
    (1 - state.alpha) * 100,
  )}%`;
}

function renderMovieCard(movie) {
  const genres = movie.genres.slice(0, 2).join(", ");
  return `
    <article class="movie-card" data-movie-id="${movie.id}" tabindex="0" style="${posterVars(movie)}">
      <div class="card-poster">
        <span class="rating-badge">${movie.averageRating.toFixed(1)}</span>
        ${posterMarkup(movie)}
      </div>
      <h2>${escapeHtml(formatMovieTitle(movie))}</h2>
      <p>Жанры: ${escapeHtml(genres || "не указаны")}</p>
      <p>${escapeHtml(movie.reason || "Рекомендуется гибридной моделью")}</p>
      <p>${escapeHtml(movie.method || "Оценен пользователями MovieLens")}</p>
      <button class="details-button" type="button">Подробнее</button>
    </article>
  `;
}

function renderMovieOptions(movies, container, onPick) {
  if (!movies.length) {
    container.classList.remove("is-open");
    container.innerHTML = "";
    return;
  }

  container.innerHTML = movies
    .map(
      (movie) => `
        <button class="search-option" type="button" data-option-id="${movie.id}" style="${posterVars(movie)}">
          ${posterThumb(movie)}
          <span>
            <span class="option-title">${escapeHtml(formatMovieTitle(movie))}</span>
            <span class="option-meta">${escapeHtml(movie.genres.slice(0, 2).join(", "))}</span>
          </span>
          <span class="option-score">${movie.averageRating.toFixed(1)}</span>
        </button>
      `,
    )
    .join("");
  container.classList.add("is-open");
  [...container.querySelectorAll("[data-option-id]")].forEach((button) => {
    button.addEventListener("click", () => {
      const movie = movies.find((candidate) => candidate.id === Number(button.dataset.optionId));
      if (movie) onPick(movie);
    });
  });
}

async function searchMovies(query, limit = 7) {
  if (!query.trim()) return [];
  const payload = await api(`${API.movies}?q=${encodeURIComponent(query)}&limit=${limit}`);
  return payload.movies || [];
}

async function renderGenres() {
  const payload = await api(API.genres);
  els.catalogGenre.innerHTML = '<option value="">Все жанры</option>' + (payload.genres || [])
    .map((genre) => `<option value="${escapeHtml(genre)}">${escapeHtml(genre)}</option>`)
    .join("");
}

async function renderCatalog() {
  const query = els.catalogQuery.value.trim();
  const params = new URLSearchParams({
    limit: "18",
    sort: els.catalogSort.value,
  });
  if (query) params.set("q", query);
  if (els.catalogGenre.value) params.set("genre", els.catalogGenre.value);
  if (els.catalogYearFrom.value) params.set("yearFrom", els.catalogYearFrom.value);
  if (els.catalogYearTo.value) params.set("yearTo", els.catalogYearTo.value);
  if (els.catalogMinRating.value) params.set("minRating", els.catalogMinRating.value);
  if (els.catalogHasPoster.checked) params.set("hasPoster", "1");
  const payload = await api(`${API.movies}?${params}`);
  els.catalogGrid.innerHTML = (payload.movies || []).map(renderMovieCard).join("") || '<div class="empty-state">Фильмы не найдены</div>';
}

async function getMovie(movieId) {
  const payload = await api(`${API.movies}/${movieId}`);
  return payload.movie;
}

async function addToProfile(movieId, rating) {
  if (!state.user) {
    openAuth("register");
    showToast("Сначала создайте аккаунт, чтобы оценка сохранилась в базе");
    return;
  }
  const payload = await api(API.ratings, {
    method: "POST",
    body: JSON.stringify({ movieId, rating }),
  });
  state.profile = payload.ratings || [];
  renderProfile();
  await renderRecommendations();
  showToast("Оценка сохранена в SQLite");
}

async function removeFromProfile(movieId) {
  const payload = await api(`${API.ratings}/${movieId}`, { method: "DELETE" });
  state.profile = payload.ratings || [];
  renderProfile();
  await renderRecommendations();
}

async function openMovie(movieId) {
  const movie = await getMovie(movieId);
  const score = state.scores.get(movieId) || {};
  state.activeMovie = movie;
  els.modalPoster.style.cssText = posterVars(movie);
  els.modalPoster.innerHTML = posterMarkup(movie);
  els.modalRating.textContent = movie.averageRating.toFixed(1);
  els.modalTitle.textContent = formatMovieTitle(movie);
  const names = [movie.director ? `Режиссер: ${movie.director}` : "", movie.actors?.length ? `Актеры: ${movie.actors.slice(0, 3).join(", ")}` : ""]
    .filter(Boolean)
    .join(" · ");
  els.modalMeta.textContent = `Жанры: ${movie.genres.join(", ")} · ${movie.ratingCount.toLocaleString("ru-RU")} оценок${names ? ` · ${names}` : ""}`;
  els.modalDescription.textContent = movie.description;
  els.cfBar.style.width = `${Math.round(Math.min(1, score.cfSignal ?? score.cfScore ?? 0) * 100)}%`;
  els.contentBar.style.width = `${Math.round(Math.min(1, score.contentScore || 0) * 100)}%`;
  els.modalImdb.href = movie.imdbId ? `https://www.imdb.com/title/tt${movie.imdbId}/` : "#";
  els.movieModal.hidden = false;
}

async function openMoviePage(movieId) {
  const movie = await getMovie(movieId);
  state.activeMovie = movie;
  els.detailPoster.style.cssText = posterVars(movie);
  els.detailPoster.innerHTML = posterMarkup(movie);
  els.detailRating.textContent = movie.averageRating.toFixed(1);
  els.detailTitle.textContent = formatMovieTitle(movie);
  const people = [movie.director ? `Режиссер: ${movie.director}` : "", movie.actors?.length ? `Актеры: ${movie.actors.slice(0, 5).join(", ")}` : ""]
    .filter(Boolean)
    .join(" · ");
  els.detailMeta.textContent = `Жанры: ${movie.genres.join(", ")} · ${movie.ratingCount.toLocaleString("ru-RU")} оценок${people ? ` · ${people}` : ""}`;
  els.detailDescription.textContent = movie.description;
  if (movie.userRating) els.detailRatingSelect.value = String(movie.userRating);
  els.similarMovies.innerHTML = (movie.similarMovies || [])
    .map(
      (similar) => `
        <button class="compact-card" type="button" data-movie-id="${similar.id}">
          <strong>${escapeHtml(formatMovieTitle(similar))}</strong>
          <span>Сходство MovieLens: ${Math.round((similar.similarity || 0) * 100)}%</span>
          <span>${escapeHtml(similar.genres.slice(0, 2).join(", "))}</span>
        </button>
      `,
    )
    .join("");
  history.replaceState(null, "", `#movie/${movie.id}`);
  showScreen("details", false);
}

async function openExplainPage(movieId) {
  const payload = await api(`/api/recommendations/explain/${movieId}?alpha=${state.alpha}`);
  const movie = payload.movie;
  els.explainSummary.innerHTML = `
    <div><span>Фильм</span><strong>${escapeHtml(movie.title)}</strong></div>
    <div><span>Итоговый score</span><strong>${Number(movie.score || 0).toFixed(3)}</strong></div>
    <div><span>CF</span><strong>${Math.round((movie.cfSignal ?? movie.cfScore ?? 0) * 100)}%</strong></div>
    <div><span>Content</span><strong>${Math.round((movie.contentScore || 0) * 100)}%</strong></div>
  `;
  els.explainFormula.textContent = payload.formula;
  els.explainNeighbors.innerHTML = (payload.neighbors || [])
    .map(
      (item) => `
        <div class="neighbor-item">
          <div>
            <strong>${escapeHtml(item.title)}${item.year ? ` (${item.year})` : ""}</strong>
            <small>Ваша оценка: ${Number(item.userRating).toFixed(1)}</small>
          </div>
          <div>
            <small>CF ${Math.round(item.cfScore * 100)}%</small><br />
            <small>Content ${Math.round(item.contentScore * 100)}%</small>
          </div>
        </div>
      `,
    )
    .join("");
  history.replaceState(null, "", `#explain/${movieId}`);
  showScreen("explain", false);
}

async function renderMetrics() {
  try {
    const report = await api("/api/evaluation");
    if (report.status === "missing") {
      els.metricsGrid.innerHTML = "";
      els.metricsNote.textContent = report.message;
      return;
    }
    if (report.models) {
      const titles = { cf: "Collaborative", content: "Content-based", hybrid: "Hybrid" };
      els.metricsGrid.innerHTML = Object.entries(report.models)
        .map(
          ([name, metrics]) => `
            <article class="metrics-card">
              <span>${titles[name] || name}</span>
              <strong>RMSE ${metrics.rmse}</strong>
              <small>P@5 ${metrics.precisionAt5} · R@5 ${metrics.recallAt5} · F1 ${metrics.f1At5}</small>
            </article>
          `,
        )
        .join("");
    } else {
      const metrics = [
        ["RMSE", report.rmse],
        ["Precision@5", report.precisionAt5],
        ["Recall@5", report.recallAt5],
        ["F1@5", report.f1At5],
      ];
      els.metricsGrid.innerHTML = metrics
        .map(([label, value]) => `<article class="metrics-card"><span>${label}</span><strong>${value}</strong></article>`)
        .join("");
    }
    els.metricsNote.textContent = `${report.note || ""} Пользователей: ${report.testUsers || 0}, alpha: ${report.alpha ?? "—"}.`;
  } catch {
    els.metricsNote.textContent = "Метрики пока недоступны.";
  }
}

async function renderSemanticSearch() {
  const query = els.semanticInput.value.trim();
  if (!query) {
    els.semanticResults.innerHTML = "";
    return;
  }
  const payload = await api(`${API.semantic}?q=${encodeURIComponent(query)}`);
  const movies = (payload.movies || []).slice(0, 6);
  const modeLabels = {
    openai_embeddings: "OpenAI embeddings",
    local_embeddings: "Local sentence-transformers",
    tfidf_fallback: "TF-IDF fallback",
  };
  const mode = modeLabels[payload.mode] || "Embeddings";
  els.semanticResults.innerHTML = movies.length
    ? movies
        .map(
          (movie) => `
            <button class="compact-card" type="button" data-movie-id="${movie.id}">
              <strong>${escapeHtml(formatMovieTitle(movie))}</strong>
              <span>${escapeHtml(movie.genres.slice(0, 2).join(", "))}</span>
              <span>${mode}${movie.semanticScore ? ` · ${Number(movie.semanticScore).toFixed(3)}` : ""}</span>
            </button>
          `,
        )
        .join("")
    : '<div class="empty-state">По этому описанию пока ничего не найдено</div>';
}

async function handleMovieRequest(event) {
  event.preventDefault();
  const payload = await api(API.movieRequests, {
    method: "POST",
    body: JSON.stringify({
      title: els.requestTitle.value,
      year: els.requestYear.value,
      note: els.requestNote.value,
    }),
  });
  showToast(payload.message || "Заявка сохранена");
  els.movieRequestForm.reset();
}

function openAuth(mode) {
  state.authMode = mode;
  const isRegister = mode === "register";
  els.authTitle.textContent = isRegister ? "Регистрация" : "Вход в MovieRec";
  els.authSubtitle.textContent = isRegister
    ? "Создайте аккаунт: оценки будут храниться в SQLite и использоваться серверной моделью."
    : "Войдите, чтобы продолжить работу со своим профилем оценок.";
  els.saveAuth.textContent = isRegister ? "Зарегистрироваться" : "Войти";
  els.switchAuthMode.textContent = isRegister ? "У меня уже есть аккаунт" : "Создать новый аккаунт";
  els.authName.value = "";
  els.authPassword.value = "";
  els.authModal.hidden = false;
  setTimeout(() => els.authName.focus(), 0);
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const username = els.authName.value.trim();
  const password = els.authPassword.value;
  const url = state.authMode === "register" ? API.register : API.login;
  const payload = await api(url, {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  state.user = payload.user;
  state.profile = payload.ratings || [];
  closeAuth();
  await renderAll();
  showToast(state.authMode === "register" ? "Аккаунт создан" : "Вход выполнен");
}

async function hydrateRoute() {
  const hashRoute = location.hash.replace("#", "");
  if (hashRoute.startsWith("movie/")) {
    const movieId = Number(hashRoute.split("/")[1]);
    if (movieId) {
      await openMoviePage(movieId);
      return;
    }
  }
  if (hashRoute.startsWith("explain/")) {
    const movieId = Number(hashRoute.split("/")[1]);
    if (movieId) {
      await openExplainPage(movieId);
      return;
    }
  }
  const route = ["home", "recommendations", "catalog", "semantic", "about", "contacts", "report"].includes(hashRoute)
    ? hashRoute
    : "recommendations";
  showScreen(route, false);
}

function showScreen(route, pushHash = true) {
  els.screens.forEach((screen) => {
    screen.classList.toggle("is-active", screen.dataset.screen === route);
  });
  const activeRoute = ["details", "explain"].includes(route) ? "recommendations" : route;
  els.navLinks.forEach((link) => {
    link.classList.toggle("is-active", link.dataset.route === activeRoute);
  });
  if (pushHash) history.replaceState(null, "", `#${route}`);
}

function closeMovieModal() {
  els.movieModal.hidden = true;
}

function closeAuth() {
  els.authModal.hidden = true;
}

function closeSearchPanels() {
  els.searchResults.classList.remove("is-open");
  els.preferenceSuggestions.classList.remove("is-open");
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    credentials: "same-origin",
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "object" ? payload.error || payload.message : payload;
    showToast(message || "Ошибка API");
    throw new Error(message || `HTTP ${response.status}`);
  }
  return payload;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("is-visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.remove("is-visible"), 2200);
}

function formatMovieTitle(movie) {
  return `${movie.title}${movie.year ? ` (${movie.year})` : ""}`;
}

function formatRatingTitle(entry) {
  return `${entry.title}${entry.year ? ` (${entry.year})` : ""}`;
}

function posterVars(movie) {
  const [a, b] = movie.palette || ["#a855f7", "#111827"];
  return `--poster-a: ${a}; --poster-b: ${b};`;
}

function posterMarkup(movie) {
  const words = movie.title.split(/\s+/).slice(0, 3).join(" ");
  const fallback = `<span class="poster-fallback">${escapeHtml(words)}</span>`;
  if (!movie.poster) return fallback;
  return `${fallback}<img src="${movie.poster}" alt="Постер ${escapeHtml(movie.title)}" loading="lazy" onerror="this.remove()" />`;
}

function posterThumb(movie) {
  if (movie.poster) {
    return `<img src="${movie.poster}" alt="" loading="lazy" onerror="this.outerHTML='<span class=&quot;mini-poster&quot;>${escapeHtml(
      movie.title.slice(0, 1),
    )}</span>'" />`;
  }
  return `<span class="mini-poster">${escapeHtml(movie.title.slice(0, 1))}</span>`;
}

function debounce(callback, wait) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => callback(...args), wait);
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

const API_BASE = "http://localhost:8000";
const SITE_URL = `${API_BASE}/#recommendations`;

const state = {
  selectedMovie: null,
  movies: [],
  session: null,
};

const els = {};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  cacheElements();
  wireEvents();
  await loadSession();
  await renderRecommendations();
}

function cacheElements() {
  els.search = document.querySelector("#movieSearch");
  els.rating = document.querySelector("#ratingValue");
  els.addMovie = document.querySelector("#addMovie");
  els.suggestions = document.querySelector("#suggestions");
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
    if (typeof chrome !== "undefined" && chrome.tabs) chrome.tabs.create({ url: SITE_URL });
    else window.open(SITE_URL, "_blank");
  });
}

async function loadSession() {
  state.session = await api("/api/session");
  renderProfile();
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
      const url = `${API_BASE}/#movie/${button.dataset.id}`;
      if (typeof chrome !== "undefined" && chrome.tabs) chrome.tabs.create({ url });
      else window.open(url, "_blank");
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
    els.openSite.click();
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

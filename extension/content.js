(() => {
  const ROOT_ID = "movierec-extension-root";
  const API_BASE = "http://localhost:8000";
  let panelOpen = false;

  if (document.getElementById(ROOT_ID)) return;

  const root = document.createElement("div");
  root.id = ROOT_ID;
  root.innerHTML = `
    <style>
      #${ROOT_ID}{position:fixed;z-index:2147483647;right:18px;bottom:18px;font-family:Inter,system-ui,sans-serif;color:#f5f5f7}
      #${ROOT_ID} *{box-sizing:border-box}
      #movierec-fab{display:inline-flex;min-width:112px;min-height:42px;align-items:center;justify-content:center;border:0;border-radius:999px;background:linear-gradient(92deg,#d33ed5,#f00f24);color:white;cursor:pointer;font:800 13px Inter,system-ui,sans-serif;box-shadow:0 14px 34px rgba(0,0,0,.35)}
      #movierec-panel{position:absolute;right:0;bottom:52px;display:none;width:min(340px,calc(100vw - 34px));overflow:hidden;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:#171719;box-shadow:0 22px 52px rgba(0,0,0,.42)}
      #movierec-panel.is-open{display:block}
      .mrec-head{padding:15px 15px 12px;border-bottom:1px solid rgba(255,255,255,.08)}
      .mrec-head strong{display:block;font-size:15px}.mrec-head span{display:block;margin-top:3px;color:#9b9ba6;font-size:12px}
      .mrec-list{display:grid;gap:8px;padding:12px}.mrec-item{display:grid;width:100%;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;padding:10px 11px;border:0;border-radius:11px;background:#222228;text-align:left;cursor:pointer}
      .mrec-item strong{display:block;overflow:hidden;color:#fff;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.mrec-item span{color:#9c9ca7;font-size:11px}.mrec-item small{display:inline-grid;min-width:34px;min-height:27px;place-items:center;border-radius:999px;background:rgba(211,62,213,.16);color:#f7d9ff;font-weight:900}
      .mrec-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:0 12px 12px}.mrec-actions button{min-height:34px;border:0;border-radius:9px;cursor:pointer;color:white;font:800 12px Inter,system-ui,sans-serif}.mrec-primary{background:linear-gradient(92deg,#d33ed5,#f00f24)}.mrec-ghost{background:rgba(255,255,255,.08)}
    </style>
    <div id="movierec-panel" role="dialog" aria-label="MovieRec">
      <div class="mrec-head"><strong>MovieRec</strong><span id="mrec-context">Подборка по странице</span></div>
      <div id="mrec-list" class="mrec-list"></div>
      <div class="mrec-actions"><button class="mrec-primary" id="mrec-open-site" type="button">Сайт</button><button class="mrec-ghost" id="mrec-refresh" type="button">Обновить</button></div>
    </div>
    <button id="movierec-fab" type="button" aria-expanded="false">MovieRec</button>
  `;

  document.documentElement.appendChild(root);

  const fab = root.querySelector("#movierec-fab");
  const panel = root.querySelector("#movierec-panel");
  const list = root.querySelector("#mrec-list");
  const context = root.querySelector("#mrec-context");

  fab.addEventListener("click", () => {
    panelOpen = !panelOpen;
    panel.classList.toggle("is-open", panelOpen);
    fab.setAttribute("aria-expanded", String(panelOpen));
    if (panelOpen) renderPanel();
  });

  root.querySelector("#mrec-open-site").addEventListener("click", () => {
    window.open(`${API_BASE}/#recommendations`, "_blank", "noopener,noreferrer");
  });
  root.querySelector("#mrec-refresh").addEventListener("click", renderPanel);
  list.addEventListener("click", (event) => {
    const item = event.target.closest("[data-mrec-id]");
    if (item) window.open(`${API_BASE}/#movie/${item.dataset.mrecId}`, "_blank", "noopener,noreferrer");
  });

  async function renderPanel() {
    const sourceText = `${document.title} ${window.getSelection()?.toString() || ""} ${
      document.querySelector('meta[name="description"]')?.content || ""
    }`;
    const matched = await findMatchedMovie(sourceText);
    const recs = matched
      ? (await fetchJson(`/api/movies/${matched.id}`)).movie.similarMovies
      : (await fetchJson("/api/recommendations?limit=4")).recommendations;
    context.textContent = matched ? `Похоже на ${formatTitle(matched)}` : "Стартовая подборка MovieRec";
    list.innerHTML = recs
      .filter(Boolean)
      .slice(0, 4)
      .map(
        (movie) => `
          <button class="mrec-item" type="button" data-mrec-id="${movie.id}">
            <span><strong>${escapeHtml(formatTitle(movie))}</strong><span>${escapeHtml(movie.genres.slice(0, 2).join(", "))}</span></span>
            <small>${Number(movie.averageRating).toFixed(1)}</small>
          </button>
        `,
      )
      .join("");
  }

  async function findMatchedMovie(text) {
    const payload = await fetchJson(`/api/movies?q=${encodeURIComponent(text.slice(0, 140))}&limit=5`);
    const normalized = normalize(text);
    return (payload.movies || []).find((movie) => normalized.includes(normalize(movie.title))) || null;
  }

  async function fetchJson(path) {
    const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
    return response.json();
  }

  function formatTitle(movie) {
    return `${movie.title}${movie.year ? ` (${movie.year})` : ""}`;
  }

  function normalize(value) {
    return String(value).toLowerCase().trim().replace(/ё/g, "е");
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();

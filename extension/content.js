(() => {
  const ROOT_ID = "movierec-extension-root";
  let apiBase = "http://127.0.0.1:8000";
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
      .mrec-missing{display:grid;gap:9px;padding:12px;border:1px dashed rgba(211,62,213,.35);border-radius:12px;background:rgba(211,62,213,.07);color:#b8b8c3;font-size:12px;font-weight:800;line-height:1.35}.mrec-missing button{min-height:34px;border:0;border-radius:9px;background:linear-gradient(92deg,#d33ed5,#f00f24);color:white;cursor:pointer;font:900 12px Inter,system-ui,sans-serif}
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

  if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message?.type !== "MOVIEREC_PAGE_CONTEXT") return false;
      sendResponse(extractPageContext());
      return true;
    });
  }

  fab.addEventListener("click", () => {
    panelOpen = !panelOpen;
    panel.classList.toggle("is-open", panelOpen);
    fab.setAttribute("aria-expanded", String(panelOpen));
    if (panelOpen) renderPanel();
  });

  root.querySelector("#mrec-open-site").addEventListener("click", () => {
    window.open(`${apiBase}/#recommendations`, "_blank", "noopener,noreferrer");
  });
  root.querySelector("#mrec-refresh").addEventListener("click", renderPanel);
  list.addEventListener("click", (event) => {
    const item = event.target.closest("[data-mrec-id]");
    if (item) window.open(`${apiBase}/#movie/${item.dataset.mrecId}`, "_blank", "noopener,noreferrer");
    const requestButton = event.target.closest("[data-mrec-request]");
    if (requestButton) requestMissingMovie();
  });

  async function renderPanel() {
    await resolveApiBase();
    const pageContext = extractPageContext();
    const sourceText = [pageContext.selection, ...pageContext.candidates, pageContext.description].filter(Boolean).join(" ");
    const matched = await findMatchedMovie(sourceText);
    const recs = matched
      ? (await fetchJson(`/api/movies/${matched.id}`)).movie.similarMovies
      : (await fetchJson("/api/recommendations?limit=4")).recommendations;
    context.textContent = matched ? `Похоже на ${formatTitle(matched)}` : "Фильм не найден в базе";
    const requestCard = matched
      ? ""
      : `
        <div class="mrec-missing">
          <span>Похоже, это “${escapeHtml(pageContext.candidates[0] || document.title)}”, но такого фильма нет в базе MovieRec.</span>
          <button type="button" data-mrec-request="1">Отправить заявку</button>
        </div>
      `;
    list.innerHTML = requestCard + recs
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

  async function requestMissingMovie() {
    await resolveApiBase();
    const pageContext = extractPageContext();
    const candidate = pageContext.candidates[0] || document.title;
    const title = candidate.replace(/\(\d{4}(?:\s*[–-]\s*[^)]*)?\)/g, "").slice(0, 120).trim();
    if (!title) return;
    await fetchJson("/api/movie-requests", {
      method: "POST",
      body: JSON.stringify({
        title,
        year: extractYear([candidate, pageContext.title].join(" ")),
        note: `Заявка из расширения. Страница: ${pageContext.url}`,
      }),
    });
    context.textContent = "Заявка отправлена";
    list.innerHTML = '<div class="mrec-missing"><span>Заявка ушла администратору. Статус будет виден в личном кабинете MovieRec.</span></div>';
  }

  async function findMatchedMovie(text) {
    const payload = await fetchJson(`/api/movies?q=${encodeURIComponent(text.slice(0, 140))}&limit=5`);
    const normalized = normalize(text);
    return (payload.movies || []).find((movie) => normalized.includes(normalize(movie.title))) || null;
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(`${apiBase}${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    return response.json();
  }

  async function resolveApiBase() {
    for (const base of ["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:8001"]) {
      try {
        const response = await fetch(`${base}/api/version`, { credentials: "include" });
        if (response.ok) {
          apiBase = base;
          return;
        }
      } catch {
        // Try next local server.
      }
    }
  }

  function extractPageContext() {
    const selection = String(window.getSelection?.() || "").trim();
    const title = document.title || "";
    const description =
      document.querySelector('meta[property="og:description"]')?.content ||
      document.querySelector('meta[name="description"]')?.content ||
      "";
    const headings = [...document.querySelectorAll("h1")]
      .map((node) => node.textContent.trim())
      .filter(Boolean)
      .slice(0, 3);
    const ogTitle =
      document.querySelector('meta[property="og:title"]')?.content ||
      document.querySelector('meta[name="twitter:title"]')?.content ||
      "";
    const candidates = cleanTitleCandidates([selection, ogTitle, ...headings, title]);
    return {
      title,
      description,
      selection,
      url: location.href,
      host: location.host,
      candidates,
    };
  }

  function cleanTitleCandidates(values) {
    const ignored = /\b(imdb|tmdb|кинопоиск|youtube|google|wikipedia|википедия|official trailer|трейлер)\b/gi;
    return [
      ...new Set(
        values
          .map((value) =>
            String(value || "")
              .replace(ignored, "")
              .replace(/\s*[-|—]\s*$/g, "")
              .replace(/\(\d{4}\)/g, "")
              .trim(),
          )
          .filter((value) => value.length >= 2 && value.length <= 90),
      ),
    ];
  }

  function formatTitle(movie) {
    return `${movie.title}${movie.year ? ` (${movie.year})` : ""}`;
  }

  function normalize(value) {
    return String(value).toLowerCase().trim().replace(/ё/g, "е");
  }

  function extractYear(value) {
    const match = String(value || "").match(/\b(19\d{2}|20\d{2})\b/);
    return match ? Number(match[1]) : "";
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

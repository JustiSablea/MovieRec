(() => {
  if (typeof chrome === "undefined" || !chrome.runtime?.onMessage) return;

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "MOVIEREC_PAGE_CONTEXT") return false;
    sendResponse(extractPageContext());
    return true;
  });

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
              .replace(/\(\d{4}(?:\s*[–-]\s*[^)]*)?\)/g, "")
              .trim(),
          )
          .filter((value) => value.length >= 2 && value.length <= 120),
      ),
    ];
  }
})();

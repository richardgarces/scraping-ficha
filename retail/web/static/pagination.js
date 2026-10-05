(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.RetailPager = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function state(rawPage, rawTotalPages) {
    const totalPages = Math.max(1, Math.floor(Number(rawTotalPages) || 0));
    const page = Math.min(totalPages, Math.max(1, Math.floor(Number(rawPage) || 1)));
    return {
      page,
      totalPages,
      label: `Página ${page} de ${totalPages}`,
      showPrevious: totalPages > 1 && page > 1,
      showNext: totalPages > 1 && page < totalPages,
    };
  }

  function render(rawPage, rawTotalPages, options = {}) {
    const result = state(rawPage, rawTotalPages);
    if (typeof document === "undefined") return result;
    const previous = document.getElementById(options.previousId || "prev");
    const next = document.getElementById(options.nextId || "next");
    const label = document.getElementById(options.labelId || "page-label");
    if (previous) {
      previous.hidden = !result.showPrevious;
      previous.disabled = !result.showPrevious;
      previous.setAttribute("aria-label", "Ir a la página anterior");
    }
    if (next) {
      next.hidden = !result.showNext;
      next.disabled = !result.showNext;
      next.setAttribute("aria-label", "Ir a la página siguiente");
    }
    if (label) {
      label.textContent = result.label;
      label.setAttribute("aria-live", "polite");
    }
    return result;
  }

  return { state, render };
});

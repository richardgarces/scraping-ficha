// Admin: cambios de valor de precio (último mes) → export Cyber Day.
(() => {
  const FETCH_TIMEOUT_MS = 20000;
  let allItems = [];
  let selected = new Set();

  function el(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function showFlash(text, ok = true) {
    const node = el("flash");
    if (!node) return;
    node.hidden = false;
    node.className = ok ? "summary" : "err";
    node.textContent = text;
  }

  function money(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return "—";
    if (typeof window.formatPrice === "function") return window.formatPrice(n);
    return `$${Math.round(n).toLocaleString("es-CL")}`;
  }

  function fmtDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return date.toLocaleString("es-CL", {
      timeZone: "America/Santiago",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function sourceLabel(row) {
    const sources = Array.isArray(row.sources) && row.sources.length
      ? row.sources
      : [row.source].filter(Boolean);
    const map = { catalog: "Catálogo", cyber_day: "Cyber", following: "Seguidos" };
    return sources.map((s) => map[s] || s).join(" · ") || "—";
  }

  function filterText() {
    return String(el("filter-q")?.value || "").trim().toLowerCase();
  }

  function filteredItems() {
    const q = filterText();
    if (!q) return allItems.slice();
    return allItems.filter((row) => {
      const hay = [row.query, row.category, row.store, row.store_title, sourceLabel(row)]
        .map((v) => String(v || "").toLowerCase())
        .join(" ");
      return hay.includes(q);
    });
  }

  function rowId(row) {
    return String(row.id || row.query || "").trim();
  }

  function daysValue() {
    const n = Number(el("days")?.value || 30);
    if (!Number.isFinite(n)) return 30;
    return Math.max(1, Math.min(90, Math.round(n)));
  }

  async function apiJson(url, options = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: ctrl.signal });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401 || response.status === 403) {
        location.href = `/entrar?next=${encodeURIComponent("/cambios-precio")}`;
        throw new Error("Entra con la cuenta de administrador.");
      }
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(typeof detail === "string" ? detail : response.statusText);
      }
      return payload;
    } finally {
      clearTimeout(timer);
    }
  }

  function updateMeta(payload) {
    const meta = el("meta");
    if (!meta) return;
    const total = Number(payload.total || 0);
    const visible = filteredItems().length;
    const sel = selected.size;
    const stats = payload.stats || {};
    const from = payload.from_day || "";
    const to = payload.to_day || "";
    meta.textContent = [
      `${total.toLocaleString("es-CL")} con cambio de valor`,
      from && to ? `(${from} → ${to}, ${payload.timezone || "America/Santiago"})` : "",
      `· visibles ${visible.toLocaleString("es-CL")}`,
      `· seleccionados ${sel.toLocaleString("es-CL")}`,
      `· fuentes catálogo ${stats.catalog || 0}, cyber ${stats.cyber_day || 0}, seguidos ${stats.following || 0}`,
    ].filter(Boolean).join(" ");
  }

  function render() {
    const body = el("body");
    const rows = filteredItems();
    const payload = { total: allItems.length, stats: window.__priceChangeStats || {}, from_day: window.__priceChangeFrom, to_day: window.__priceChangeTo, timezone: "America/Santiago" };
    updateMeta(payload);
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="9" class="muted">${allItems.length ? "Ningún resultado con ese filtro." : "No hay cambios de valor en la ventana."}</td></tr>`;
      const checkAll = el("check-all");
      if (checkAll) checkAll.checked = false;
      return;
    }
    body.innerHTML = rows.map((row) => {
      const id = rowId(row);
      const checked = selected.has(id) ? " checked" : "";
      return `<tr>
        <td><input type="checkbox" class="row-check" data-id="${escapeHtml(id)}"${checked}></td>
        <td>${escapeHtml(row.n)}</td>
        <td>${escapeHtml(row.query)}</td>
        <td>${escapeHtml(row.category || "—")}</td>
        <td>${escapeHtml(row.store_title || row.store || "—")}</td>
        <td>${escapeHtml(money(row.previous_price))}</td>
        <td>${escapeHtml(money(row.price))}</td>
        <td>${fmtDate(row.last_change_at)}</td>
        <td>${escapeHtml(sourceLabel(row))}</td>
      </tr>`;
    }).join("");
    const checkAll = el("check-all");
    if (checkAll) {
      checkAll.checked = rows.length > 0 && rows.every((r) => selected.has(rowId(r)));
    }
  }

  async function load() {
    const days = daysValue();
    el("meta").textContent = "Cargando…";
    try {
      const payload = await apiJson(`/api/admin/price-changes?days=${encodeURIComponent(days)}`);
      allItems = Array.isArray(payload.items) ? payload.items : [];
      window.__priceChangeStats = payload.stats || {};
      window.__priceChangeFrom = payload.from_day;
      window.__priceChangeTo = payload.to_day;
      const valid = new Set(allItems.map(rowId));
      selected = new Set([...selected].filter((id) => valid.has(id)));
      render();
      showFlash(`${allItems.length.toLocaleString("es-CL")} productos con cambio de valor.`);
    } catch (err) {
      el("body").innerHTML = `<tr><td colspan="9" class="muted">${escapeHtml(err.message || err)}</td></tr>`;
      showFlash(err.message || String(err), false);
    }
  }

  function selectedIds() {
    return [...selected];
  }

  async function exportFormat(kind) {
    const ids = selectedIds();
    if (!ids.length) {
      showFlash("Seleccioná al menos un producto.", false);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(`/api/admin/price-changes/export.${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({ ids, days: daysValue() }),
        signal: ctrl.signal,
      });
      if (response.status === 401 || response.status === 403) {
        location.href = `/entrar?next=${encodeURIComponent("/cambios-precio")}`;
        return;
      }
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(typeof payload.detail === "string" ? payload.detail : response.statusText);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = kind === "csv" ? "cambios-precio-cyber.csv" : "cambios-precio-cyber.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showFlash(`Exportados ${ids.length.toLocaleString("es-CL")} ítems (${kind.toUpperCase()}). Importalos en Cyber → Importar lista.`);
    } catch (err) {
      showFlash(err.message || String(err), false);
    } finally {
      clearTimeout(timer);
    }
  }

  el("reload")?.addEventListener("click", () => load());
  el("days")?.addEventListener("change", () => load());
  el("filter-q")?.addEventListener("input", () => render());
  el("select-all")?.addEventListener("click", () => {
    allItems.forEach((row) => selected.add(rowId(row)));
    render();
  });
  el("select-filtered")?.addEventListener("click", () => {
    filteredItems().forEach((row) => selected.add(rowId(row)));
    render();
  });
  el("clear-selection")?.addEventListener("click", () => {
    selected.clear();
    render();
  });
  el("check-all")?.addEventListener("change", (event) => {
    const on = Boolean(event.target.checked);
    filteredItems().forEach((row) => {
      const id = rowId(row);
      if (on) selected.add(id);
      else selected.delete(id);
    });
    render();
  });
  el("body")?.addEventListener("change", (event) => {
    const input = event.target.closest(".row-check");
    if (!input) return;
    const id = input.getAttribute("data-id") || "";
    if (!id) return;
    if (input.checked) selected.add(id);
    else selected.delete(id);
    updateMeta({
      total: allItems.length,
      stats: window.__priceChangeStats || {},
      from_day: window.__priceChangeFrom,
      to_day: window.__priceChangeTo,
      timezone: "America/Santiago",
    });
    const rows = filteredItems();
    const checkAll = el("check-all");
    if (checkAll) checkAll.checked = rows.length > 0 && rows.every((r) => selected.has(rowId(r)));
  });
  el("export-csv")?.addEventListener("click", () => exportFormat("csv"));
  el("export-json")?.addEventListener("click", () => exportFormat("json"));

  load();
})();

// Panel admin Cyber Day (/cyber-day). Solo admin; la API también exige admin.
// IIFE: evita choque con window.flash (elemento #flash) que abortaba el script
// tras definir json() y dejaba la UI en «Cargando…» para siempre.
(() => {
  const FETCH_TIMEOUT_MS = 8000;
  const SEED_FALLBACK_URL = "/static/cyber_junio2026.json?v=1";
  const DEFAULT_LIST = {
    slug: "cyber_junio2026",
    list_id: "cyber_junio2026",
    name: "Cyber Junio 2026",
    title: "Cyber Junio 2026",
    products_count: 100,
  };
  let usingSeedFallback = false;

  async function apiJson(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401 || response.status === 403) {
        const next = encodeURIComponent(`${location.pathname}${location.search}`);
        location.href = `/entrar?next=${next}`;
        throw new Error("Entra con la cuenta de administrador.");
      }
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(typeof detail === "string" ? detail : response.statusText || `HTTP ${response.status}`);
      }
      return payload;
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error("La API tardó demasiado (timeout). Probá recargar.");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function el(id) {
    return document.getElementById(id);
  }

  function showFlash(text, ok = true) {
    const node = el("flash");
    if (!node) return;
    node.hidden = false;
    node.className = ok ? "summary" : "err";
    node.textContent = text;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  const STATUS_LABEL = {
    idle: "En espera",
    running: "En curso",
    paused: "Pausado",
    stopping: "Deteniendo",
    stopped: "Detenida",
    partial: "Parcial hoy",
    done: "Listo hoy",
    failed: "Falló hoy",
  };

  let cyberTimer = null;
  let currentListId = "";
  let loadReady = false;

  function formatSeconds(value) {
    const total = Math.max(0, Number(value) || 0);
    const m = Math.floor(total / 60);
    const s = total % 60;
    if (m <= 0) return `${s}s`;
    return `${m}m ${String(s).padStart(2, "0")}s`;
  }

  function formatPrice(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return "—";
    return `$${Math.round(n).toLocaleString("es-CL")}`;
  }

  function listQuery(path) {
    if (!currentListId) return path;
    const sep = path.includes("?") ? "&" : "?";
    return `${path}${sep}list=${encodeURIComponent(currentListId)}`;
  }

  function enableActionButtons() {
    ["cyber-start", "cyber-stop", "cyber-continue", "cyber-restart"].forEach((id) => {
      const btn = el(id);
      if (btn) btn.disabled = false;
    });
  }

  async function loadSeedFallback(message) {
    usingSeedFallback = true;
    loadReady = true;
    fillListSelect([DEFAULT_LIST], DEFAULT_LIST.slug);
    currentListId = DEFAULT_LIST.slug;
    const meta = el("cyber-meta");
    if (meta) {
      meta.textContent = `Error API: ${message}. Mostrando seed local (solo lectura).`;
    }
    const wrap = el("cyber-products-wrap");
    if (wrap) wrap.hidden = false;
    try {
      const response = await fetch(SEED_FALLBACK_URL, { cache: "no-store" });
      const data = await response.json();
      const items = data.items || data.products || [];
      const body = el("cyber-products-body");
      if (body) {
        body.innerHTML = items.map((row) => `
      <tr>
        <td>${escapeHtml(row.n ?? "—")}</td>
        <td>${escapeHtml(row.query || row.name || "—")}</td>
        <td>${escapeHtml(row.category || "—")}</td>
        <td>—</td>
        <td>—</td>
        <td class="muted">seed local</td>
      </tr>`).join("") || `<tr><td colspan="6" class="err">Sin seed local.</td></tr>`;
      }
      if (meta) {
        meta.textContent = `Error API: ${message}. Seed local: ${items.length} queries (solo lectura; reintentá Iniciar o recargá).`;
      }
    } catch (seedError) {
      const body = el("cyber-products-body");
      if (body) {
        body.innerHTML = `<tr><td colspan="6" class="err">Error al cargar: ${escapeHtml(message)} · seed: ${escapeHtml(seedError.message)}</td></tr>`;
      }
    }
    enableActionButtons();
  }

  function showLoadError(message) {
    loadSeedFallback(message).catch(() => {});
  }

  function fillListSelect(lists, activeId) {
    const select = el("cyber-list-select");
    if (!select) return;
    const rows = Array.isArray(lists) ? lists : [];
    if (!rows.length) {
      select.innerHTML = `<option value="${DEFAULT_LIST.slug}">${escapeHtml(DEFAULT_LIST.name)} (seed)</option>`;
      currentListId = DEFAULT_LIST.slug;
      return;
    }
    const active = activeId || currentListId || rows[0].slug || rows[0].list_id;
    select.innerHTML = rows.map((row) => {
      const slug = row.slug || row.list_id;
      const name = row.name || row.title || slug;
      const count = row.products_count != null ? ` (${row.products_count})` : "";
      const status = row.run?.status ? ` · ${STATUS_LABEL[row.run.status] || row.run.status}` : "";
      return `<option value="${escapeHtml(slug)}"${slug === active ? " selected" : ""}>${escapeHtml(name)}${escapeHtml(count)}${escapeHtml(status)}</option>`;
    }).join("");
    currentListId = select.value || active || "";
  }

  function renderCyber(payload) {
    loadReady = true;
    const run = payload?.run || {};
    const status = run.status || "idle";
    const total = Number(run.total) || Number(payload?.products_count) || 0;
    const processed = Number(run.processed) || 0;
    const percent = Number(run.percent) || 0;
    const lap = Number(run.lap) || 0;
    if (payload?.list_id) currentListId = payload.list_id;
    fillListSelect(payload?.lists, currentListId);

    const listMeta = payload?.list || {};
    const nameEl = el("cyber-name");
    const slugEl = el("cyber-slug");
    if (slugEl) slugEl.textContent = currentListId || "—";
    if (nameEl) nameEl.textContent = listMeta.name || listMeta.title || currentListId || "Cyber Day";
    const liveTitle = el("cyber-live-title");
    if (liveTitle) liveTitle.textContent = listMeta.name || listMeta.title || currentListId || "Cyber Day";

    const exportCsv = el("cyber-export-csv");
    const exportJson = el("cyber-export-json");
    if (exportCsv) exportCsv.href = listQuery("/api/admin/cyber-day/export.csv");
    if (exportJson) exportJson.href = listQuery("/api/admin/cyber-day/export.json");

    const meta = el("cyber-meta");
    if (meta) {
      const note = run.source_note || "";
      const change = run.last_change
        ? ` · Último cambio: ${run.last_change.name || ""} ${run.last_change.previous_price}→${run.last_change.price}`
        : "";
      const rows = payload?.products || payload?.products_preview || [];
      const withPrice = rows.filter((r) => r.last_price != null && Number(r.last_price) > 0).length;
      meta.textContent = [
        total ? `${total} queries en lista` : "Lista vacía — importá CSV/JSON o creá con seed",
        withPrice ? `${withPrice} con precio` : null,
        run.worker_healthy ? "worker OK" : "worker sin heartbeat",
        run.notified_count ? `${run.notified_count} avisos` : null,
        note,
        change,
      ].filter(Boolean).join(" · ");
    }
    const live = el("cyber-live");
    if (live) live.hidden = false;
    const badge = el("cyber-live-status");
    if (badge) {
      badge.className = `badge status-${STATUS_LABEL[status] ? status : "idle"}`;
      badge.textContent = STATUS_LABEL[status] || status;
    }
    const label = el("cyber-live-label");
    if (label) {
      const elapsed = run.lap_elapsed_seconds != null ? formatSeconds(run.lap_elapsed_seconds) : "—";
      const eta = run.lap_eta_seconds != null ? ` · ETA ${formatSeconds(run.lap_eta_seconds)}` : "";
      label.textContent = total
        ? `Vuelta ${lap || "—"} · ${percent}% (${processed}/${total}) · tiempo ${elapsed}${eta}`
        : "Importá la lista o creá una con seed para poder iniciar.";
    }
    const bar = el("cyber-live-bar");
    if (bar) bar.style.width = `${Math.min(100, percent)}%`;
    const barWrap = bar?.parentElement;
    if (barWrap) barWrap.setAttribute("aria-valuenow", String(Math.round(percent)));
    const counts = el("cyber-live-counts");
    if (counts) {
      counts.textContent = run.last_error
        ? `Error: ${run.last_error}`
        : run.last_lap_elapsed_seconds != null
          ? `Última vuelta: ${formatSeconds(run.last_lap_elapsed_seconds)}`
          : "";
    }
    const start = el("cyber-start");
    const stop = el("cyber-stop");
    const cont = el("cyber-continue");
    const restart = el("cyber-restart");
    if (start) start.disabled = !total || status === "running";
    if (stop) stop.disabled = !["running", "paused"].includes(status);
    if (cont) {
      cont.disabled = !total || status === "running" || (status === "idle" && processed <= 0);
      if (["stopped", "paused"].includes(status)) cont.disabled = !total;
    }
    if (restart) restart.disabled = !total || status === "running";

    const wrap = el("cyber-products-wrap");
    const body = el("cyber-products-body");
    const rows = payload?.products || payload?.products_preview || [];
    if (wrap && body) {
      wrap.hidden = false;
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="6" class="muted">Sin filas en la lista. Importá CSV/JSON o creá la lista con seed.</td></tr>`;
      } else {
        body.innerHTML = rows.map((row) => `
      <tr>
        <td>${escapeHtml(row.n ?? (row.order != null ? row.order + 1 : "—"))}</td>
        <td>${escapeHtml(row.query || row.name || "—")}</td>
        <td>${escapeHtml(row.category || "—")}</td>
        <td>${escapeHtml(row.last_match_count != null ? row.last_match_count : 0)}</td>
        <td>${formatPrice(row.last_price)}</td>
        <td class="muted">${escapeHtml(row.last_error || "")}</td>
      </tr>`).join("");
      }
    }
    const refreshHint = el("cyber-refresh");
    if (refreshHint) {
      refreshHint.textContent = status === "running" ? "Actualizando cada 3 s…" : "";
    }
  }

  async function refreshCyber() {
    try {
      const payload = await apiJson(listQuery("/api/admin/cyber-day"));
      usingSeedFallback = false;
      renderCyber(payload);
      if (cyberTimer) {
        clearTimeout(cyberTimer);
        cyberTimer = null;
      }
      if (payload?.run?.status === "running") {
        cyberTimer = setTimeout(() => {
          refreshCyber().catch((error) => {
            showLoadError(error.message);
            showFlash(error.message, false);
          });
        }, 3000);
      }
    } catch (error) {
      showLoadError(error.message);
      showFlash(error.message, false);
      throw error;
    }
  }

  async function cyberAction(path, button, busyLabel) {
    if (!button) return;
    if (!loadReady) {
      showFlash("Todavía cargando el estado…", false);
      return;
    }
    if (usingSeedFallback) {
      showFlash("Estás en modo seed local (solo lectura). Recargá cuando la API responda.", false);
      return;
    }
    const prev = button.textContent;
    button.disabled = true;
    button.textContent = busyLabel;
    try {
      const result = await apiJson(listQuery(path), { method: "POST" });
      showFlash(result.run?.status === "running" ? "Cyber Day en curso." : "Cyber Day actualizado.");
      renderCyber(result);
      await refreshCyber();
    } catch (error) {
      showFlash(error.message, false);
      await refreshCyber().catch(() => {});
    } finally {
      button.textContent = prev;
    }
  }

  el("cyber-list-select")?.addEventListener("change", async (event) => {
    currentListId = event.target.value || "";
    try {
      await refreshCyber();
    } catch (error) {
      showFlash(error.message, false);
    }
  });

  el("cyber-new-list-toggle")?.addEventListener("click", () => {
    const form = el("cyber-new-list-form");
    if (form) form.hidden = !form.hidden;
  });
  el("cyber-new-cancel")?.addEventListener("click", () => {
    const form = el("cyber-new-list-form");
    if (form) form.hidden = true;
  });

  el("cyber-new-list-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = el("cyber-new-create");
    const name = el("cyber-new-name")?.value?.trim() || "";
    const slug = el("cyber-new-slug")?.value?.trim() || "";
    const source = el("cyber-new-source")?.value || "seed";
    if (!name && !slug) {
      showFlash("Indicá un nombre o slug.", false);
      return;
    }
    if (button) {
      button.disabled = true;
      button.textContent = "Creando…";
    }
    try {
      const body = {
        name: name || slug,
        slug: slug || undefined,
        use_seed: source === "seed",
        copy_from: source === "copy" ? currentListId : undefined,
      };
      if (source === "empty") {
        body.use_seed = false;
      }
      const result = await apiJson("/api/admin/cyber-day/lists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      showFlash(`Lista creada: ${result.list?.slug || result.list_id || "ok"}`);
      const form = el("cyber-new-list-form");
      if (form) form.hidden = true;
      if (el("cyber-new-name")) el("cyber-new-name").value = "";
      if (el("cyber-new-slug")) el("cyber-new-slug").value = "";
      currentListId = result.list_id || result.list?.slug || currentListId;
      renderCyber(result);
    } catch (error) {
      showFlash(error.message, false);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "Crear lista";
      }
    }
  });

  el("cyber-start")?.addEventListener("click", () => {
    cyberAction("/api/admin/cyber-day/start", el("cyber-start"), "Iniciando…")
      .catch((error) => showFlash(error.message, false));
  });
  el("cyber-stop")?.addEventListener("click", () => {
    cyberAction("/api/admin/cyber-day/stop", el("cyber-stop"), "Parando…")
      .catch((error) => showFlash(error.message, false));
  });
  el("cyber-continue")?.addEventListener("click", () => {
    cyberAction("/api/admin/cyber-day/continue", el("cyber-continue"), "Continuando…")
      .catch((error) => showFlash(error.message, false));
  });
  el("cyber-restart")?.addEventListener("click", () => {
    cyberAction("/api/admin/cyber-day/restart", el("cyber-restart"), "Reiniciando…")
      .catch((error) => showFlash(error.message, false));
  });
  el("cyber-import-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = el("cyber-file");
    const button = el("cyber-import");
    const file = input?.files?.[0];
    if (!file || !button) return;
    button.disabled = true;
    button.textContent = "Importando…";
    try {
      const body = new FormData();
      body.append("file", file);
      if (currentListId) body.append("list_id", currentListId);
      const response = await fetch(listQuery("/api/admin/cyber-day/import"), { method: "POST", body });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401 || response.status === 403) {
        location.href = `/entrar?next=${encodeURIComponent("/cyber-day")}`;
        return;
      }
      if (!response.ok) {
        throw new Error(typeof payload.detail === "string" ? payload.detail : response.statusText);
      }
      showFlash(`Lista importada: ${payload.imported || 0} queries.`);
      input.value = "";
      await refreshCyber();
    } catch (error) {
      showFlash(error.message, false);
    } finally {
      button.disabled = false;
      button.textContent = "Importar lista";
    }
  });

  // Nunca dejar «Cargando listas» si el arranque falla en silencio.
  enableActionButtons();
  refreshCyber().catch((error) => showFlash(error.message, false));
})();

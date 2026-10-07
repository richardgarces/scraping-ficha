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
  let currentListName = "";
  let currentListsCount = 0;
  let currentRunStatus = "idle";
  let loadReady = false;
  let editingQueryN = null;
  let savingQueryN = null;

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

  /**
   * Celda TIENDA MEJOR PRECIO:
   * Con racha de bajas ≥2 y tienda previa distinta: `Actual (previa)`.
   * Si no hay previa o es la misma: solo la actual.
   */
  function bestStoreCellText(row) {
    const current = String(row?.best_store_title || row?.best_store || "").trim();
    if (!current) return "—";
    const prev = String(row?.prev_best_store_title || row?.prev_best_store || "").trim();
    const streak = Number(row?.delta_streak) || 0;
    const dir = String(row?.last_delta_direction || row?.price_direction || "");
    const downStreak = streak >= 2 && (dir === "down" || dir === "down_again");
    if (prev && downStreak && prev.toLowerCase() !== current.toLowerCase()) {
      return `${current} (${prev})`;
    }
    return current;
  }

  /**
   * Celda MEJOR PRECIO:
   * verde=bajó, azul=volvió a bajar, rojo=subió, naranjo=volvió a subir,
   * blanco=sin cambio/primer precio. Flecha ↑/↓ = última acción.
   * Racha consecutiva misma dirección: número pequeño (≥2) junto a flecha.
   */
  function priceCellHtml(row) {
    const text = formatPrice(row?.last_price);
    const streak = Number(row?.delta_streak) || 0;
    let dir = row?.price_direction || "";
    if (!dir && row?.prev_best_price != null && row?.last_price != null) {
      const last = Number(row.last_price);
      const prev = Number(row.prev_best_price);
      if (Number.isFinite(last) && Number.isFinite(prev) && last !== prev) {
        const base = last < prev ? "down" : "up";
        dir = streak >= 2 ? `${base}_again` : base;
      }
    }
    const arrow = (dir === "down" || dir === "down_again")
      ? "↓"
      : (dir === "up" || dir === "up_again")
        ? "↑"
        : "";
    const arrowHtml = arrow
      ? `<span class="price-arrow" aria-hidden="true">${arrow}</span>`
      : "";
    // Primera en esa dirección (streak 1): sin número. Consecutivas: 2, 3, …
    const streakHtml = (arrow && streak >= 2)
      ? `<sup class="price-streak" aria-label="racha ${streak}">${streak}</sup>`
      : "";
    const vs = formatPrice(row?.prev_best_price);
    const streakHint = streak >= 2 ? ` · racha ${streak}` : "";
    const meta = {
      down: { cls: "down", title: `Bajó vs ${vs}` },
      down_again: { cls: "down-again", title: `Volvió a bajar vs ${vs}${streakHint}` },
      up: { cls: "up", title: `Subió vs ${vs}` },
      up_again: { cls: "up-again", title: `Volvió a subir vs ${vs}${streakHint}` },
    }[dir];
    if (!meta) return `<td>${text}</td>`;
    return `<td class="${meta.cls}" title="${meta.title}">${text}${arrowHtml}${streakHtml}</td>`;
  }

  function listQuery(path) {
    if (!currentListId) return path;
    const sep = path.includes("?") ? "&" : "?";
    return `${path}${sep}list=${encodeURIComponent(currentListId)}`;
  }

  function setButtonEnabled(btn, enabled) {
    if (!btn) return;
    btn.disabled = !enabled;
    btn.classList.toggle("is-disabled", !enabled);
    btn.setAttribute("aria-disabled", enabled ? "false" : "true");
  }

  /** Sincroniza Iniciar/Parar/Continuar/Reiniciar/Eliminar con el status del run. */
  function applyActionButtons(status, total, listsCount) {
    const running = status === "running";
    const paused = status === "paused";
    const hasList = Number(total) > 0;
    const listCount = Number(listsCount) || 0;
    setButtonEnabled(el("cyber-start"), hasList && !running);
    setButtonEnabled(el("cyber-stop"), running || paused);
    setButtonEnabled(el("cyber-continue"), hasList && paused);
    // Reiniciar con confirm: habilitado si hay lista (también en curso).
    setButtonEnabled(el("cyber-restart"), hasList);
    // Eliminar: requiere Parar primero; no borrar la única lista.
    setButtonEnabled(
      el("cyber-delete-list"),
      !usingSeedFallback && Boolean(currentListId) && !running && !paused && listCount > 1,
    );
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
        <td>—</td>
        <td>—</td>
        <td>—</td>
        <td>—</td>
        <td>—</td>
        <td class="muted">seed local</td>
      </tr>`).join("") || `<tr><td colspan="11" class="err">Sin seed local.</td></tr>`;
      }
      if (meta) {
        meta.textContent = `Error API: ${message}. Seed local: ${items.length} queries (solo lectura; reintentá Iniciar o recargá).`;
      }
    } catch (seedError) {
      const body = el("cyber-products-body");
      if (body) {
        body.innerHTML = `<tr><td colspan="11" class="err">Error al cargar: ${escapeHtml(message)} · seed: ${escapeHtml(seedError.message)}</td></tr>`;
      }
    }
    // Seed local: no arrancar worker; botones de control deshabilitados.
    applyActionButtons("idle", 0, 1);
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
    currentListsCount = Array.isArray(payload?.lists) ? payload.lists.length : 0;
    currentRunStatus = status;

    const listMeta = payload?.list || {};
    currentListName = listMeta.name || listMeta.title || currentListId || "";
    const nameEl = el("cyber-name");
    const slugEl = el("cyber-slug");
    if (slugEl) slugEl.textContent = currentListId || "—";
    // Título de sección fijo; el nombre de lista vive en select + card de progreso.
    if (nameEl) nameEl.textContent = "Cyber";
    const liveTitle = el("cyber-live-title");
    if (liveTitle) liveTitle.textContent = currentListName || "Cyber";

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
    applyActionButtons(status, total, currentListsCount);

    const wrap = el("cyber-products-wrap");
    const body = el("cyber-products-body");
    const rows = payload?.products || payload?.products_preview || [];
    const editingActive = Boolean(
      editingQueryN != null
      || savingQueryN != null
      || document.activeElement?.classList?.contains("cyber-query-input"),
    );
    if (wrap && body && !editingActive) {
      wrap.hidden = false;
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="11" class="muted">Sin filas en la lista. Importá CSV/JSON o creá la lista con seed.</td></tr>`;
      } else {
        body.innerHTML = rows.map((row) => {
          const n = row.n ?? (row.order != null ? row.order + 1 : "");
          const query = row.query || row.name || "";
          const offerUrl = String(row.best_offer_url || "").trim();
          const offerCell = offerUrl
            ? `<a href="${escapeHtml(offerUrl)}" target="_blank" rel="noopener">Ver oferta</a>`
            : "—";
          return `
      <tr data-n="${escapeHtml(n)}">
        <td>${escapeHtml(n || "—")}</td>
        <td>
          <input
            type="text"
            class="cyber-query-input"
            data-n="${escapeHtml(n)}"
            data-original="${escapeHtml(query)}"
            value="${escapeHtml(query)}"
            aria-label="Query ${escapeHtml(n)}"
            ${usingSeedFallback ? "disabled" : ""}
          >
        </td>
        <td>${escapeHtml(row.category || "—")}</td>
        ${priceCellHtml(row)}
        <td>${escapeHtml(bestStoreCellText(row))}</td>
        <td>${escapeHtml(row.stores_scraped != null ? row.stores_scraped : 0)}</td>
        <td>${formatPrice(row.max_price_normal)}</td>
        <td>${formatPrice(row.min_price_normal)}</td>
        <td>${formatPrice(row.max_offer_price)}</td>
        <td>${offerCell}</td>
        <td class="muted">${escapeHtml(row.last_error || "")}</td>
      </tr>`;
        }).join("");
      }
    } else if (wrap) {
      wrap.hidden = false;
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
    if (!button || button.disabled || button.classList.contains("is-disabled")) return;
    if (!loadReady) {
      showFlash("Todavía cargando el estado…", false);
      return;
    }
    if (usingSeedFallback) {
      showFlash("Estás en modo seed local (solo lectura). Recargá cuando la API responda.", false);
      return;
    }
    const prev = button.textContent;
    setButtonEnabled(button, false);
    button.textContent = busyLabel;
    try {
      const result = await apiJson(listQuery(path), { method: "POST" });
      showFlash(result.run?.status === "running" ? "Cyber en curso." : "Cyber actualizado.");
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

  async function saveQueryInput(input) {
    if (!input || usingSeedFallback || input.disabled) return;
    const n = Number(input.dataset.n);
    const next = String(input.value || "").trim();
    const original = String(input.dataset.original || "").trim();
    if (!Number.isFinite(n) || n < 1) return;
    if (!next) {
      showFlash("La query no puede estar vacía.", false);
      input.value = original;
      return;
    }
    if (next === original) {
      editingQueryN = null;
      return;
    }
    savingQueryN = n;
    editingQueryN = n;
    input.classList.add("is-saving");
    input.disabled = true;
    try {
      const result = await apiJson(listQuery(`/api/admin/cyber-day/items/${n}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: next }),
      });
      showFlash(result.message || "Query actualizada.");
      editingQueryN = null;
      savingQueryN = null;
      renderCyber(result);
    } catch (error) {
      showFlash(error.message, false);
      input.value = original;
    } finally {
      savingQueryN = null;
      editingQueryN = null;
      input.classList.remove("is-saving");
      input.disabled = false;
      input.dataset.original = String(input.value || "").trim();
    }
  }

  const productsBody = el("cyber-products-body");
  productsBody?.addEventListener("focusin", (event) => {
    const input = event.target?.closest?.(".cyber-query-input");
    if (!input) return;
    editingQueryN = Number(input.dataset.n) || null;
  });
  productsBody?.addEventListener("focusout", (event) => {
    const input = event.target?.closest?.(".cyber-query-input");
    if (!input) return;
    // Dejá que el blur termine antes de decidir; evita carrera con Enter.
    setTimeout(() => {
      if (document.activeElement === input) return;
      saveQueryInput(input).catch((error) => showFlash(error.message, false));
    }, 0);
  });
  productsBody?.addEventListener("keydown", (event) => {
    const input = event.target?.closest?.(".cyber-query-input");
    if (!input) return;
    if (event.key === "Enter") {
      event.preventDefault();
      input.blur();
    } else if (event.key === "Escape") {
      event.preventDefault();
      input.value = input.dataset.original || "";
      editingQueryN = null;
      input.blur();
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
    if (!window.confirm("¿Reiniciar Cyber desde la query 1? Se pierde el progreso de la vuelta actual.")) {
      return;
    }
    cyberAction("/api/admin/cyber-day/restart", el("cyber-restart"), "Reiniciando…")
      .catch((error) => showFlash(error.message, false));
  });

  el("cyber-delete-list")?.addEventListener("click", async () => {
    const button = el("cyber-delete-list");
    if (!button || button.disabled || button.classList.contains("is-disabled")) return;
    if (!loadReady || usingSeedFallback) {
      showFlash(usingSeedFallback
        ? "Estás en modo seed local (solo lectura). Recargá cuando la API responda."
        : "Todavía cargando el estado…", false);
      return;
    }
    if (currentRunStatus === "running" || currentRunStatus === "paused") {
      showFlash("Pará la lista antes de eliminarla.", false);
      return;
    }
    if (currentListsCount <= 1) {
      showFlash("No podés eliminar la única lista. Creá otra antes.", false);
      return;
    }
    const label = currentListName || currentListId;
    if (!window.confirm(
      `¿Eliminar la lista «${label}» (${currentListId})?\nSe borran queries y progreso. No se puede deshacer.`,
    )) {
      return;
    }
    const prev = button.textContent;
    setButtonEnabled(button, false);
    button.textContent = "Eliminando…";
    try {
      const result = await apiJson(listQuery("/api/admin/cyber-day/lists"), { method: "DELETE" });
      showFlash(result.message || `Lista «${result.deleted || currentListId}» eliminada.`);
      currentListId = result.list_id || "";
      renderCyber(result);
      await refreshCyber();
    } catch (error) {
      showFlash(error.message, false);
      await refreshCyber().catch(() => {});
    } finally {
      button.textContent = prev;
    }
  });

  el("cyber-import-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = el("cyber-file");
    const button = el("cyber-import");
    const file = input?.files?.[0];
    if (!file || !button) return;
    if (usingSeedFallback) {
      showFlash("Estás en modo seed local (solo lectura). Recargá cuando la API responda.", false);
      return;
    }
    const label = currentListName || currentListId || "lista activa";
    const runningNote = (currentRunStatus === "running" || currentRunStatus === "paused")
      ? " La lista está en curso: se detendrá y se reiniciará el progreso."
      : "";
    if (!window.confirm(
      `¿Reemplazar las queries de «${label}» con «${file.name}»?${runningNote}\nSe conserva el slug/nombre; las filas actuales se sobrescriben.`,
    )) {
      return;
    }
    button.disabled = true;
    button.textContent = "Importando…";
    try {
      // Enviar cuerpo raw (JSON/CSV), no FormData: evita depender de python-multipart
      // en el contenedor (FormData → 500 «multipart must be installed»).
      const text = await file.text();
      const lower = (file.name || "").toLowerCase();
      const isJson = lower.endsWith(".json") || text.trimStart().startsWith("[") || text.trimStart().startsWith("{");
      const headers = {
        "Content-Type": isJson ? "application/json; charset=utf-8" : "text/csv; charset=utf-8",
      };
      const response = await fetch(listQuery("/api/admin/cyber-day/import"), {
        method: "POST",
        headers,
        body: text,
      });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401 || response.status === 403) {
        location.href = `/entrar?next=${encodeURIComponent("/cyber-day")}`;
        return;
      }
      if (!response.ok) {
        throw new Error(typeof payload.detail === "string" ? payload.detail : response.statusText || `HTTP ${response.status}`);
      }
      showFlash(payload.message || `Lista actualizada: ${payload.imported || 0} queries.`);
      input.value = "";
      if (payload.list_id || payload.run) {
        renderCyber(payload);
      }
      await refreshCyber();
    } catch (error) {
      showFlash(error.message, false);
    } finally {
      button.disabled = false;
      button.textContent = "Importar / actualizar";
    }
  });

  // Hasta el primer refresh: controles deshabilitados (evita Iniciar con status desconocido).
  applyActionButtons("idle", 0, 0);
  refreshCyber().catch((error) => showFlash(error.message, false));
})();

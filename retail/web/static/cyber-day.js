// Panel admin Cyber Day (/cyber-day). Solo admin; la API también exige admin.

async function json(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`);
    location.href = `/entrar?next=${next}`;
    throw new Error("Entra con la cuenta de administrador.");
  }
  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(typeof detail === "string" ? detail : response.statusText);
  }
  return payload;
}

function $(id) {
  return document.getElementById(id);
}

function flash(text, ok = true) {
  const el = $("flash");
  if (!el) return;
  el.hidden = false;
  el.className = ok ? "summary" : "err";
  el.textContent = text;
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

function renderCyber(payload) {
  const run = payload?.run || {};
  const status = run.status || "idle";
  const total = Number(run.total) || Number(payload?.products_count) || 0;
  const processed = Number(run.processed) || 0;
  const percent = Number(run.percent) || 0;
  const lap = Number(run.lap) || 0;
  const meta = $("cyber-meta");
  if (meta) {
    const note = run.source_note || "";
    const change = run.last_change
      ? ` · Último cambio: ${run.last_change.name || ""} ${run.last_change.previous_price}→${run.last_change.price}`
      : "";
    const rows = payload?.products || payload?.products_preview || [];
    const withPrice = rows.filter((r) => r.last_price != null && Number(r.last_price) > 0).length;
    meta.textContent = [
      total ? `${total} queries en lista` : "Lista vacía — importá CSV/JSON",
      withPrice ? `${withPrice} con precio` : null,
      run.worker_healthy ? "worker OK" : "worker sin heartbeat",
      run.notified_count ? `${run.notified_count} avisos` : null,
      note,
      change,
    ].filter(Boolean).join(" · ");
  }
  const live = $("cyber-live");
  if (live) live.hidden = false;
  const badge = $("cyber-live-status");
  if (badge) {
    badge.className = `badge status-${STATUS_LABEL[status] ? status : "idle"}`;
    badge.textContent = STATUS_LABEL[status] || status;
  }
  const label = $("cyber-live-label");
  if (label) {
    const elapsed = run.lap_elapsed_seconds != null ? formatSeconds(run.lap_elapsed_seconds) : "—";
    const eta = run.lap_eta_seconds != null ? ` · ETA ${formatSeconds(run.lap_eta_seconds)}` : "";
    label.textContent = total
      ? `Vuelta ${lap || "—"} · ${percent}% (${processed}/${total}) · tiempo ${elapsed}${eta}`
      : "Importá la lista para poder iniciar.";
  }
  const bar = $("cyber-live-bar");
  if (bar) bar.style.width = `${Math.min(100, percent)}%`;
  const barWrap = bar?.parentElement;
  if (barWrap) barWrap.setAttribute("aria-valuenow", String(Math.round(percent)));
  const counts = $("cyber-live-counts");
  if (counts) {
    counts.textContent = run.last_error
      ? `Error: ${run.last_error}`
      : run.last_lap_elapsed_seconds != null
        ? `Última vuelta: ${formatSeconds(run.last_lap_elapsed_seconds)}`
        : "";
  }
  const start = $("cyber-start");
  const stop = $("cyber-stop");
  const cont = $("cyber-continue");
  const restart = $("cyber-restart");
  if (start) start.disabled = !total || status === "running";
  if (stop) stop.disabled = !["running", "paused"].includes(status);
  if (cont) {
    cont.disabled = !total || status === "running" || (status === "idle" && processed <= 0);
    if (["stopped", "paused"].includes(status)) cont.disabled = !total;
  }
  if (restart) restart.disabled = !total || status === "running";

  const wrap = $("cyber-products-wrap");
  const body = $("cyber-products-body");
  const rows = payload?.products || payload?.products_preview || [];
  if (wrap && body) {
    wrap.hidden = false;
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="6" class="muted">Sin filas en la lista. Importá CSV/JSON o revisá el seed.</td></tr>`;
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
  const refreshHint = $("cyber-refresh");
  if (refreshHint) {
    refreshHint.textContent = status === "running" ? "Actualizando cada 3 s…" : "";
  }
}

async function refreshCyber() {
  try {
    const payload = await json("/api/admin/cyber-day");
    renderCyber(payload);
    if (cyberTimer) {
      clearTimeout(cyberTimer);
      cyberTimer = null;
    }
    if (payload?.run?.status === "running") {
      cyberTimer = setTimeout(() => {
        refreshCyber().catch((error) => {
          const meta = $("cyber-meta");
          if (meta && meta.textContent === "Cargando…") {
            meta.textContent = `Error al actualizar: ${error.message}`;
          }
          flash(error.message, false);
        });
      }, 3000);
    }
  } catch (error) {
    const meta = $("cyber-meta");
    if (meta) meta.textContent = `No se pudo cargar el estado: ${error.message}`;
    const wrap = $("cyber-products-wrap");
    if (wrap) wrap.hidden = false;
    flash(error.message, false);
    throw error;
  }
}

async function cyberAction(path, button, busyLabel) {
  if (!button || button.disabled) return;
  const prev = button.textContent;
  button.disabled = true;
  button.textContent = busyLabel;
  try {
    const result = await json(path, { method: "POST" });
    flash(result.run?.status === "running" ? "Cyber Day en curso." : "Cyber Day actualizado.");
    renderCyber(result);
    await refreshCyber();
  } catch (error) {
    flash(error.message, false);
  } finally {
    button.textContent = prev;
  }
}

$("cyber-start")?.addEventListener("click", () => {
  cyberAction("/api/admin/cyber-day/start", $("cyber-start"), "Iniciando…")
    .catch((error) => flash(error.message, false));
});
$("cyber-stop")?.addEventListener("click", () => {
  cyberAction("/api/admin/cyber-day/stop", $("cyber-stop"), "Parando…")
    .catch((error) => flash(error.message, false));
});
$("cyber-continue")?.addEventListener("click", () => {
  cyberAction("/api/admin/cyber-day/continue", $("cyber-continue"), "Continuando…")
    .catch((error) => flash(error.message, false));
});
$("cyber-restart")?.addEventListener("click", () => {
  cyberAction("/api/admin/cyber-day/restart", $("cyber-restart"), "Reiniciando…")
    .catch((error) => flash(error.message, false));
});
$("cyber-import-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("cyber-file");
  const button = $("cyber-import");
  const file = input?.files?.[0];
  if (!file || !button) return;
  button.disabled = true;
  button.textContent = "Importando…";
  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/admin/cyber-day/import", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      location.href = `/entrar?next=${encodeURIComponent("/cyber-day")}`;
      return;
    }
    if (!response.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : response.statusText);
    }
    flash(`Lista importada: ${payload.imported || 0} queries.`);
    input.value = "";
    await refreshCyber();
  } catch (error) {
    flash(error.message, false);
  } finally {
    button.disabled = false;
    button.textContent = "Importar lista";
  }
});

refreshCyber().catch((error) => flash(error.message, false));

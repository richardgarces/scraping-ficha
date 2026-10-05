// Estado de crons/lotes por grupo (admin). Auto-refresh si hay alguno running.

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

function flash(text, ok = true) {
  const el = $("flash");
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

function groupIncomplete(group) {
  if (group.can_continue) return true;
  const processed = Number(group.last_run?.processed) || 0;
  const items = Number(group.last_run?.items) || 0;
  if (items > 0 && processed > 0 && processed < items) return true;
  if (group.last_run?.budget_exhausted && processed > 0 && (items <= 0 || processed < items)) return true;
  return false;
}

function normalizedGroupStatus(status) {
  return STATUS_LABEL[status] ? status : "idle";
}

function groupHasStores(group) {
  return Number(group.store_count) > 0;
}

function statusBadge(status) {
  const key = normalizedGroupStatus(status);
  return `<span class="badge status-${key}">${STATUS_LABEL[key]}</span>`;
}

const startingGroups = new Set();
const stoppingGroups = new Set();
const startingStores = new Set();
const stoppingStores = new Set();
let stoppingBasic = false;
let startingBasic = false;

function groupStatusCell(group) {
  return statusBadge(group.status);
}

function groupActionsCell(group, paused) {
  const status = normalizedGroupStatus(group.status);
  const actions = [];
  if (["running", "paused"].includes(status)) {
    const stopping = stoppingGroups.has(group.id) || group.progress?.phase === "stopping";
    const title = `Detener ${group.title || group.id}. Las demás corridas siguen.`;
    actions.push(`<button type="button" class="secondary cron-stop" data-stop-group="${escapeHtml(group.id)}"
      title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"${stopping ? " disabled" : ""}>
      ${stopping ? "Deteniendo…" : "Detener"}
    </button>`);
  }
  if (status === "idle" && groupHasStores(group)) {
    const starting = startingGroups.has(group.id);
    const title = paused
      ? "Reanuda las corridas antes de iniciar un grupo."
      : `Iniciar ${group.title || group.id} ahora`;
    actions.push(`<button type="button" class="secondary" data-start-group="${escapeHtml(group.id)}"
      title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}"${paused || starting ? " disabled" : ""}>
      ${starting ? "Iniciando…" : "Iniciar ahora"}
    </button>`);
  }
  // Falló / detenida / parcial hoy (presupuesto o X<Y): Continuar + Reiniciar.
  // «Listo hoy» completo (X>=Y) no ofrece Continuar.
  if (["failed", "stopped", "partial"].includes(status) && groupHasStores(group)) {
    const starting = startingGroups.has(group.id);
    const processed = Number(group.last_run?.processed) || 0;
    const canContinue = status === "partial" ? groupIncomplete(group) : processed > 0;
    if (canContinue) {
      const continueTitle = paused
        ? "Reanuda las corridas antes de continuar un grupo."
        : `Continuar ${group.title || group.id} desde el producto ${processed}`;
      actions.push(`<button type="button" class="secondary cron-continue" data-start-group="${escapeHtml(group.id)}" data-start-mode="continue"
        title="${escapeHtml(continueTitle)}" aria-label="${escapeHtml(continueTitle)}"${paused || starting ? " disabled" : ""}>
        ${starting ? "Iniciando…" : "Continuar"}
      </button>`);
    }
    const restartTitle = paused
      ? "Reanuda las corridas antes de reiniciar un grupo."
      : `Reiniciar ${group.title || group.id} desde el comienzo`;
    actions.push(`<button type="button" class="secondary cron-restart" data-start-group="${escapeHtml(group.id)}" data-start-mode="restart"
      title="${escapeHtml(restartTitle)}" aria-label="${escapeHtml(restartTitle)}"${paused || starting ? " disabled" : ""}>
      ${starting ? "Iniciando…" : "Reiniciar"}
    </button>`);
  }
  // Compat: API antigua que aún manda done con progreso incompleto.
  if (status === "done" && groupHasStores(group) && groupIncomplete(group)) {
    const starting = startingGroups.has(group.id);
    const processed = Number(group.last_run?.processed) || 0;
    const continueTitle = paused
      ? "Reanuda las corridas antes de continuar un grupo."
      : `Continuar ${group.title || group.id} desde el producto ${processed}`;
    actions.push(`<button type="button" class="secondary cron-continue" data-start-group="${escapeHtml(group.id)}" data-start-mode="continue"
      title="${escapeHtml(continueTitle)}" aria-label="${escapeHtml(continueTitle)}"${paused || starting ? " disabled" : ""}>
      ${starting ? "Iniciando…" : "Continuar"}
    </button>`);
  }
  if (!actions.length) return "—";
  return `<div class="cron-group-action">${actions.join("")}</div>`;
}

async function startGroup(button) {
  const group = button.dataset.startGroup;
  const mode = button.dataset.startMode || "";
  if (!group || button.disabled || startingGroups.has(group)) return;
  startingGroups.add(group);
  button.disabled = true;
  const busyLabel = mode === "continue" ? "Continuando…" : mode === "restart" ? "Reiniciando…" : "Iniciando…";
  const idleLabel = mode === "continue" ? "Continuar" : mode === "restart" ? "Reiniciar" : "Iniciar ahora";
  button.textContent = busyLabel;
  try {
    const options = { method: "POST" };
    if (mode) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify({ mode });
    }
    const result = await json(`/api/admin/cron-batches/${encodeURIComponent(group)}/start`, options);
    flash(result.message || "Corrida iniciada.");
    watchUntil = Date.now() + 60000;
  } catch (error) {
    flash(error.message, false);
  } finally {
    startingGroups.delete(group);
    button.disabled = false;
    button.textContent = idleLabel;
  }
  await refresh().catch((error) => flash(error.message, false));
}

async function stopGroup(button) {
  const group = button.dataset.stopGroup;
  if (!group || button.disabled || stoppingGroups.has(group)) return;
  stoppingGroups.add(group);
  button.disabled = true;
  button.textContent = "Deteniendo…";
  try {
    const result = await json(`/api/admin/cron-batches/${encodeURIComponent(group)}/stop`, { method: "POST" });
    flash(result.message || "Deteniendo la corrida.");
    watchUntil = Date.now() + 60000;
  } catch (error) {
    flash(error.message, false);
    stoppingGroups.delete(group);
  }
  await refresh().catch((error) => flash(error.message, false));
}

function storeStatusCell(job) {
  const badge = statusBadge(job.status);
  const actions = [];
  const title = job.title || (typeof publicStoreLabel === "function" ? publicStoreLabel(job.id) : job.id);
  if (["running", "paused"].includes(job.status)) {
    const stopping = stoppingStores.has(job.id) || job.progress?.phase === "stopping";
    const stopTitle = `Detener scraping de ${title}`;
    actions.push(`<button type="button" class="secondary cron-stop" data-stop-store="${escapeHtml(job.id)}"
      title="${escapeHtml(stopTitle)}" aria-label="${escapeHtml(stopTitle)}"${stopping ? " disabled" : ""}>
      ${stopping ? "Deteniendo…" : "Detener"}
    </button>`);
  }
  if (["failed", "stopped", "partial"].includes(job.status)) {
    const starting = startingStores.has(job.id);
    const processed = Number(job.last_run?.processed) || 0;
    const canContinue = job.status === "partial" ? groupIncomplete(job) : processed > 0;
    if (canContinue) {
      const continueTitle = `Continuar scraping de ${title} desde la consulta ${processed}`;
      actions.push(`<button type="button" class="secondary cron-continue" data-start-store="${escapeHtml(job.id)}" data-start-mode="continue"
        title="${escapeHtml(continueTitle)}" aria-label="${escapeHtml(continueTitle)}"${starting ? " disabled" : ""}>
        ${starting ? "Iniciando…" : "Continuar"}
      </button>`);
    }
    const restartTitle = `Reiniciar scraping de ${title} desde el comienzo`;
    actions.push(`<button type="button" class="secondary cron-restart" data-start-store="${escapeHtml(job.id)}" data-start-mode="restart"
      title="${escapeHtml(restartTitle)}" aria-label="${escapeHtml(restartTitle)}"${starting ? " disabled" : ""}>
      ${starting ? "Iniciando…" : "Reiniciar"}
    </button>`);
  }
  if (job.status === "done") {
    const starting = startingStores.has(job.id);
    if (groupIncomplete(job)) {
      const processed = Number(job.last_run?.processed) || 0;
      const continueTitle = `Continuar scraping de ${title} desde la consulta ${processed}`;
      actions.push(`<button type="button" class="secondary cron-continue" data-start-store="${escapeHtml(job.id)}" data-start-mode="continue"
        title="${escapeHtml(continueTitle)}" aria-label="${escapeHtml(continueTitle)}"${starting ? " disabled" : ""}>
        ${starting ? "Iniciando…" : "Continuar"}
      </button>`);
    }
    const restartTitle = `Reiniciar scraping de ${title} desde el comienzo`;
    actions.push(`<button type="button" class="secondary cron-restart" data-start-store="${escapeHtml(job.id)}" data-start-mode="restart"
      title="${escapeHtml(restartTitle)}" aria-label="${escapeHtml(restartTitle)}"${starting ? " disabled" : ""}>
      ${starting ? "Iniciando…" : "Reiniciar"}
    </button>`);
  }
  if (job.status === "idle") {
    const starting = startingStores.has(job.id);
    const startTitle = `Iniciar scraping de ${title}`;
    actions.push(`<button type="button" class="secondary" data-start-store="${escapeHtml(job.id)}"
      title="${escapeHtml(startTitle)}" aria-label="${escapeHtml(startTitle)}"${starting ? " disabled" : ""}>
      ${starting ? "Iniciando…" : "Correr scraping"}
    </button>`);
  }
  if (!actions.length) return badge;
  return `<div class="cron-group-action">${badge}${actions.join("")}</div>`;
}

async function startStore(button) {
  const tienda = button.dataset.startStore || $("store-select")?.value || "";
  const mode = button.dataset.startMode || "";
  if (!tienda || button.disabled || startingStores.has(tienda)) return;
  startingStores.add(tienda);
  button.dataset.busy = "1";
  button.disabled = true;
  const busyLabel = mode === "continue" ? "Continuando…" : mode === "restart" ? "Reiniciando…" : "Iniciando…";
  button.textContent = busyLabel;
  try {
    const body = { tienda };
    if (mode) body.mode = mode;
    const result = await json("/api/admin/store-scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    flash(result.message || "Scraping iniciado.");
    watchUntil = Date.now() + 60000;
  } catch (error) {
    flash(error.message, false);
  } finally {
    startingStores.delete(tienda);
    delete button.dataset.busy;
    syncRunButton();
  }
  await refresh().catch((error) => flash(error.message, false));
}

async function stopStore(button) {
  const tienda = button.dataset.stopStore;
  if (!tienda || button.disabled || stoppingStores.has(tienda)) return;
  stoppingStores.add(tienda);
  button.disabled = true;
  button.textContent = "Deteniendo…";
  try {
    const result = await json(`/api/admin/store-scrape/${encodeURIComponent(tienda)}/stop`, { method: "POST" });
    flash(result.message || "Deteniendo el scraping.");
    watchUntil = Date.now() + 60000;
  } catch (error) {
    flash(error.message, false);
    stoppingStores.delete(tienda);
  }
  await refresh().catch((error) => flash(error.message, false));
}

function formatWhen(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return escapeHtml(iso);
    return d.toLocaleString("es-CL", { timeZone: "America/Santiago" });
  } catch {
    return escapeHtml(iso);
  }
}

function progressCell(group) {
  const progress = group.progress;
  if (!["running", "paused"].includes(group.status) || !progress) {
    if (group.status === "failed" && group.last_run) {
      const processed = group.last_run.processed || 0;
      const items = group.last_run.items || 0;
      const progressText = items ? `${processed}/${items} productos` : "";
      const error = group.last_run.last_error
        ? `<span class="err-inline">${escapeHtml(group.last_run.last_error)}</span>`
        : "";
      if (progressText && error) return `${progressText}<div>${error}</div>`;
      return error || progressText || "—";
    }
    if (group.status === "stopped" && group.last_run) {
      const processed = group.last_run.processed || 0;
      const items = group.last_run.items || 0;
      return items ? `Detenida en ${processed}/${items} productos` : "Detenida";
    }
    if ((group.status === "done" || group.status === "partial") && group.last_run) {
      const p = group.last_run.processed || 0;
      const t = group.last_run.items || 0;
      const rate = Number(group.last_run.queries_per_minute) || 0;
      const incomplete = groupIncomplete(group) || group.status === "partial";
      const turn = incomplete
        ? (group.last_run.budget_exhausted ? " · turno por presupuesto" : " · incompleto")
        : "";
      return t ? `${p}/${t} productos${rate ? ` · ${rate.toLocaleString("es-CL")} consultas/min` : ""}${turn}` : "—";
    }
    return "—";
  }
  const processed = progress.processed || 0;
  const items = progress.items || 0;
  const pct = progress.percent != null ? progress.percent : items ? Math.round((100 * processed) / items) : 0;
  const phaseLabel = progress.phase_label || (items ? "En curso" : "Arrancando");
  const query = progress.current_query
    ? `<div class="cron-query muted">${escapeHtml(phaseLabel)}: ${escapeHtml(progress.current_query)}</div>`
    : `<div class="cron-query muted">${escapeHtml(phaseLabel)}</div>`;
  const storeCount = progress.stores_total;
  const stores = storeCount
    ? `<span class="muted"> · ${storeCount} ${storeCount === 1 ? "tienda" : "tiendas"}</span>`
    : "";
  const label = items ? `${processed}/${items} productos` : "Preparando catálogo…";
  return `
    <div class="cron-progress-wrap">
      <div class="cron-progress-label">${label}${stores}</div>
      <div class="search-bar cron-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}">
        <span style="width:${pct}%"></span>
      </div>
      ${query}
    </div>`;
}

const RULE_LABELS = {
  price_drop_percent: "Bajó de precio (%)",
  price_drop_amount: "Bajó de precio ($)",
  cross_store_gap: "Mejor precio entre tiendas",
  below_median: "Bajo su precio habitual",
  watch_target: "Precio objetivo",
  watch_change: "Cambio de precio",
};

function ruleLabel(rule) {
  return String(rule || "")
    .split("+")
    .map((item) => RULE_LABELS[item] || item)
    .filter((item, index, list) => item && list.indexOf(item) === index)
    .join(" · ");
}

function channelLabel(channel) {
  if (channel === "email") return "Correo";
  if (channel === "telegram") return "Telegram";
  if (channel === "oferta real" || channel === "oferta_real") return "Oferta real";
  return channel || "";
}

function alertKind(item) {
  const rule = item.rule_label || ruleLabel(item.rule);
  const channel = channelLabel(item.channel);
  return [rule, channel].filter(Boolean).join(" · ") || "—";
}

function alertsLabel(count) {
  const n = Number(count) || 0;
  return n === 1 ? "1 alerta" : `${n} alertas`;
}

function lastRunCell(group) {
  const run = group.last_run;
  if (!run) return "—";
  const bits = [formatWhen(run.started_at || run.finished_at)];
  if (run.alert_count) {
    const label = alertsLabel(run.alert_count);
    if (run.id) {
      const open = openAlerts && openAlerts.runId === run.id;
      const who = group.title || group.id || "";
      bits.push(
        `<button type="button" class="drop-count cron-alerts" data-run="${escapeHtml(run.id)}" data-count="${Number(run.alert_count)}" data-who="${escapeHtml(who)}" aria-expanded="${open ? "true" : "false"}" title="Ver las alertas de esta corrida">${escapeHtml(label)}</button>`
      );
    } else {
      bits.push(escapeHtml(label));
    }
  }
  if (run.duration_seconds) {
    const minutes = Math.max(1, Math.round(Number(run.duration_seconds) / 60));
    bits.push(`${minutes} min`);
  }
  if ((run.suspended_stores || []).length) {
    bits.push(`${run.suspended_stores.length} tiendas suspendidas por error`);
  }
  return bits.join(" · ");
}

let openAlerts = null;

function closeAlerts() {
  openAlerts = null;
  document.querySelectorAll("tr.cron-alerts-row").forEach((row) => row.remove());
  document.querySelectorAll("button.cron-alerts[aria-expanded='true']").forEach((button) => {
    button.setAttribute("aria-expanded", "false");
  });
}

function priceMove(item) {
  const now = `<span class="price">${money(item.price)}</span>`;
  if (item.previous_price) {
    return `<span class="price was">${money(item.previous_price)}</span> → ${now}`;
  }
  if (item.median) {
    return `<span class="muted">habitual ${money(item.median)}</span> → ${now}`;
  }
  if (item.second_price) {
    const rival = item.second_store_title || item.second_store || "otra tienda";
    return `${now} <span class="muted">vs ${money(item.second_price)} en ${escapeHtml(rival)}</span>`;
  }
  return now;
}

function alertRow(item) {
  const name = item.name || item.query || "Sin nombre";
  const href = item.product_id
    ? `/producto?store=${encodeURIComponent(item.store || "")}&id=${encodeURIComponent(item.product_id)}`
    : "";
  const title = href
    ? `<a href="${escapeHtml(href)}">${escapeHtml(name)}</a>`
    : escapeHtml(name);
  const offer = item.url
    ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Oferta</a>`
    : "";
  const ficha = href ? `<a href="${escapeHtml(href)}">Ficha</a>` : "";
  const reason = item.message ? `<div class="muted">${escapeHtml(item.message)}</div>` : "";
  const store = storeLogo(item.display_store || item.store, item.store_title || item.store);
  return `
    <tr>
      <td>${title}${reason}</td>
      <td>${store}</td>
      <td>${priceMove(item)}</td>
      <td>${escapeHtml(alertKind(item))}</td>
      <td class="drops-links">${ficha}${offer}</td>
    </tr>`;
}

function alertsPanelHtml() {
  if (!openAlerts) return "";
  const who = openAlerts.who ? ` de ${escapeHtml(openAlerts.who)}` : "";
  const counted = alertsLabel(openAlerts.count);
  if (openAlerts.loading) {
    return `
      <div class="drops-panel">
        <div class="drops-head">
          <strong>${escapeHtml(counted)}${who}</strong>
          <button type="button" class="secondary" data-close-alerts>Cerrar</button>
        </div>
        <p class="muted">Cargando alertas…</p>
      </div>`;
  }
  if (openAlerts.error) {
    return `
      <div class="drops-panel">
        <div class="drops-head">
          <strong>${escapeHtml(counted)}${who}</strong>
          <button type="button" class="secondary" data-close-alerts>Cerrar</button>
        </div>
        <p class="err">${escapeHtml(openAlerts.error)}</p>
      </div>`;
  }
  const payload = openAlerts.payload || { items: [], total: 0, alert_count: openAlerts.count };
  const items = payload.items || [];
  const stored = payload.alert_count ?? openAlerts.count;
  const found = payload.total ?? items.length;
  let note = "Ofertas detectadas en esa corrida y guardadas con su id. El número de la tabla es ese contador, no envíos de correo, Telegram ni ofertas reales.";
  if (Number(found) !== Number(stored)) {
    note = `La corrida cuenta ${alertsLabel(stored)}. Hay ${found} ${found === 1 ? "guardada" : "guardadas"} con ese id.`;
  } else if (payload.truncated) {
    note = `Se muestran ${items.length} de ${found}.`;
  }
  const body = items.length
    ? items.map(alertRow).join("")
    : `<tr><td colspan="5" class="muted">No hay alertas guardadas para esta corrida.</td></tr>`;
  return `
    <div class="drops-panel">
      <div class="drops-head">
        <strong>${escapeHtml(counted)}${who}</strong>
        <button type="button" class="secondary" data-close-alerts>Cerrar</button>
      </div>
      <p class="muted">${escapeHtml(note)}</p>
      <div class="table-wrap">
        <table class="drops-table">
          <thead>
            <tr>
              <th>Producto</th>
              <th>Tienda</th>
              <th>Precio</th>
              <th>Tipo</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </div>`;
}

function mountAlerts(button) {
  document.querySelectorAll("tr.cron-alerts-row").forEach((row) => row.remove());
  const host = button.closest("tr");
  if (!host || !openAlerts) return;
  button.setAttribute("aria-expanded", "true");
  const cols = host.closest("table")?.querySelectorAll("thead th").length || 5;
  const detail = document.createElement("tr");
  detail.className = "store-drops cron-alerts-row";
  detail.innerHTML = `<td colspan="${cols}">${alertsPanelHtml()}</td>`;
  host.after(detail);
}

function restoreAlerts() {
  if (!openAlerts) return;
  const button = document.querySelector(`button.cron-alerts[data-run="${CSS.escape(openAlerts.runId)}"]`);
  if (!button) {
    openAlerts = null;
    return;
  }
  mountAlerts(button);
}

async function toggleAlerts(button) {
  const runId = button.dataset.run;
  if (!runId) return;
  const already = openAlerts && openAlerts.runId === runId;
  closeAlerts();
  if (already) return;
  openAlerts = {
    runId,
    who: button.dataset.who || "",
    count: Number(button.dataset.count) || 0,
    loading: true,
    payload: null,
    error: "",
  };
  mountAlerts(button);
  try {
    const payload = await json(`/api/admin/cron-batches/${encodeURIComponent(runId)}/alerts`);
    if (!openAlerts || openAlerts.runId !== runId) return;
    openAlerts.loading = false;
    openAlerts.payload = payload;
    if (payload.alert_count != null) openAlerts.count = payload.alert_count;
  } catch (error) {
    if (!openAlerts || openAlerts.runId !== runId) return;
    openAlerts.loading = false;
    openAlerts.error = error.message || "No se pudieron cargar las alertas.";
  }
  const current = document.querySelector(`button.cron-alerts[data-run="${CSS.escape(runId)}"]`);
  if (current && openAlerts && openAlerts.runId === runId) mountAlerts(current);
}

let lastStoreJobs = [];
let lastCronPayload = null;
let storeIdsKey = "";

function fillStores(payload) {
  const stores = payload.stores || [];
  const key = stores.map((item) => item.id).join(",");
  const select = $("store-select");
  if (!select || key === storeIdsKey) return;
  storeIdsKey = key;
  const current = select.value;
  const options = [`<option value="">Elegir tienda…</option>`].concat(
    stores.map(
      (store) =>
        `<option value="${escapeHtml(store.id)}">${escapeHtml(store.title)} · ${escapeHtml(store.group_title || store.group || "")}</option>`
    )
  );
  select.innerHTML = options.join("");
  if (current && stores.some((store) => store.id === current)) select.value = current;
}

function renderStoreLive(jobs) {
  const panel = $("store-scrape-live");
  if (!panel) return;
  const select = $("store-select");
  const selected = select?.value || "";
  const live = (jobs || []).filter((job) => ["running", "paused"].includes(job.status));
  const job = (selected && live.find((item) => item.id === selected)) || live[0] || null;
  if (!job) {
    panel.hidden = true;
    const actions = $("store-live-actions");
    if (actions) actions.innerHTML = "";
    return;
  }
  const progress = job.progress || {};
  const processed = progress.processed ?? job.last_run?.processed ?? 0;
  const items = progress.items ?? job.last_run?.items ?? 0;
  const pct = progress.percent != null
    ? progress.percent
    : items
      ? Math.round((100 * processed) / items)
      : 0;
  const phaseLabel = progress.phase_label || (items ? "En curso" : "Arrancando");
  panel.hidden = false;
  const title = $("store-live-title");
  const status = $("store-live-status");
  const label = $("store-live-label");
  const bar = $("store-live-bar");
  const query = $("store-live-query");
  const counts = $("store-live-counts");
  if (title) title.textContent = job.title || (typeof publicStoreLabel === "function" ? publicStoreLabel(job.id) : job.id);
  if (status) {
    status.textContent = job.status === "paused" ? "Pausado" : "En curso";
    status.className = job.status === "paused" ? "badge off" : "badge";
  }
  if (label) {
    label.textContent = items
      ? `${processed.toLocaleString("es-CL")} / ${items.toLocaleString("es-CL")} consultas · ${pct}%`
      : `${phaseLabel}…`;
  }
  if (bar) {
    bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    const wrap = bar.parentElement;
    if (wrap) wrap.setAttribute("aria-valuenow", String(pct));
  }
  if (query) {
    query.textContent = progress.current_query
      ? `${phaseLabel}: ${progress.current_query}`
      : phaseLabel;
  }
  if (counts) counts.textContent = countLine(progress) || "";
  const actions = $("store-live-actions");
  if (actions) {
    if (["running", "paused"].includes(job.status)) {
      const stopping = stoppingStores.has(job.id) || progress.phase === "stopping";
      const stopTitle = `Detener scraping de ${job.title || (typeof publicStoreLabel === "function" ? publicStoreLabel(job.id) : job.id)}`;
      actions.innerHTML = `<button type="button" class="secondary cron-stop" data-stop-store="${escapeHtml(job.id)}"
        title="${escapeHtml(stopTitle)}" aria-label="${escapeHtml(stopTitle)}"${stopping ? " disabled" : ""}>
        ${stopping ? "Deteniendo…" : "Detener"}
      </button>`;
    } else {
      actions.innerHTML = "";
    }
  }
}

function storeJobsForDisplay(payload) {
  const jobs = [...(payload.store_jobs || [])];
  const select = $("store-select");
  const selected = select?.value || "";
  if (!selected || jobs.some((job) => job.id === selected)) return jobs;
  const stores = payload.stores || lastCronPayload?.stores || [];
  const store = stores.find((item) => item.id === selected);
  if (!store) return jobs;
  return jobs.concat([
    {
      id: store.id,
      public_id: store.public_id || store.id,
      title: store.title,
      groups: store.group ? [store.group] : [],
      status: "idle",
      progress: null,
      last_run: null,
    },
  ]);
}

function renderStoreJobs(payload) {
  lastStoreJobs = payload.store_jobs || [];
  const displayJobs = storeJobsForDisplay(payload);
  const wrap = $("store-jobs-wrap");
  const meta = $("store-scrape-meta");
  const select = $("store-select");
  const selected = select?.value || "";
  const live = lastStoreJobs.filter((job) => ["running", "paused"].includes(job.status));
  const visible = displayJobs.filter((job) => {
    if (["running", "paused", "failed", "stopped", "partial", "done"].includes(job.status)) return true;
    return selected && job.id === selected;
  });
  renderStoreLive(lastStoreJobs);
  if (meta) {
    if (live.length) {
      meta.textContent = live
        .map((job) => {
          const processed = job.progress?.processed ?? job.last_run?.processed ?? 0;
          const items = job.progress?.items ?? job.last_run?.items ?? 0;
          const query = job.progress?.current_query;
          const label = job.title || (typeof publicStoreLabel === "function" ? publicStoreLabel(job.id) : job.id);
          const base = items
            ? `${label}: ${processed}/${items} productos`
            : `${label}: arrancando…`;
          return query ? `${base} · ${query}` : base;
        })
        .join(" · ");
    } else if (selected) {
      const job = displayJobs.find((item) => item.id === selected);
      const label = job ? (job.title || (typeof publicStoreLabel === "function" ? publicStoreLabel(job.id) : job.id)) : "";
      meta.textContent = job?.last_run
        ? `Última corrida de ${label}: ${formatWhen(job.last_run.finished_at || job.last_run.started_at)}`
        : "";
    } else {
      meta.textContent = "";
    }
  }
  if (!wrap) return;
  if (!visible.length) {
    wrap.hidden = true;
    wrap.querySelector("tbody").innerHTML = "";
    syncRunButton();
    return;
  }
  wrap.hidden = false;
  wrap.querySelector("tbody").innerHTML = visible
    .map((job) => {
      const like = { status: job.status, progress: job.progress, last_run: job.last_run };
      const groups = (job.groups || []).join(", ");
      const counts = countLine(job.progress || job.last_run);
      const highlight = selected && job.id === selected ? " cron-store-selected" : "";
      const publicId = job.public_id || (typeof publicStoreId === "function" ? publicStoreId(job.id) : job.id);
      return `
    <tr class="${highlight.trim()}" data-status="${escapeHtml(job.status)}" data-tienda="${escapeHtml(job.id)}">
      <td>
        <strong>${escapeHtml(job.title || publicId)}</strong>
        <div class="muted">${escapeHtml(publicId)}${groups ? ` · ${escapeHtml(groups)}` : ""}</div>
      </td>
      <td>${storeStatusCell(job)}</td>
      <td>
        ${progressCell(like)}
        ${counts ? `<div class="cron-basic-counts muted">${escapeHtml(counts)}</div>` : ""}
      </td>
      <td>${lastRunCell(like)}</td>
    </tr>`;
    })
    .join("");
  syncRunButton();
}

function countLine(run) {
  if (!run) return "";
  const nuevos = run.new ?? run.saved_upserted ?? 0;
  const actualizados = run.updated ?? run.saved_modified ?? 0;
  const omitidos = run.skipped || 0;
  const bits = [`${nuevos} nuevos`, `${actualizados} actualizados`];
  if (omitidos) bits.push(`${omitidos} sin categoría`);
  return bits.join(" · ");
}

function basicStatusCell(job) {
  const badge = statusBadge(job.status);
  const actions = [];
  if (["running", "paused"].includes(job.status)) {
    const stopping = stoppingBasic || job.progress?.phase === "stopping";
    const stopTitle = "Detener scraping básico";
    actions.push(`<button type="button" class="secondary cron-stop" data-stop-basic="1"
      title="${escapeHtml(stopTitle)}" aria-label="${escapeHtml(stopTitle)}"${stopping ? " disabled" : ""}>
      ${stopping ? "Deteniendo…" : "Detener"}
    </button>`);
  }
  if (["failed", "stopped", "partial"].includes(job.status)) {
    const starting = startingBasic;
    const processed = Number(job.last_run?.processed) || 0;
    const canContinue = job.status === "partial" ? groupIncomplete(job) : processed > 0;
    if (canContinue) {
      const continueTitle = `Continuar scraping básico desde el producto ${processed}`;
      actions.push(`<button type="button" class="secondary cron-continue" data-basic-mode="continue"
        title="${escapeHtml(continueTitle)}" aria-label="${escapeHtml(continueTitle)}"${starting ? " disabled" : ""}>
        ${starting ? "Iniciando…" : "Continuar"}
      </button>`);
    }
    const restartTitle = "Reiniciar scraping básico desde el comienzo";
    actions.push(`<button type="button" class="secondary cron-restart" data-basic-mode="restart"
      title="${escapeHtml(restartTitle)}" aria-label="${escapeHtml(restartTitle)}"${starting ? " disabled" : ""}>
      ${starting ? "Iniciando…" : "Reiniciar"}
    </button>`);
  }
  if (job.status === "done") {
    const starting = startingBasic;
    if (groupIncomplete(job)) {
      const processed = Number(job.last_run?.processed) || 0;
      const continueTitle = `Continuar scraping básico desde el producto ${processed}`;
      actions.push(`<button type="button" class="secondary cron-continue" data-basic-mode="continue"
        title="${escapeHtml(continueTitle)}" aria-label="${escapeHtml(continueTitle)}"${starting ? " disabled" : ""}>
        ${starting ? "Iniciando…" : "Continuar"}
      </button>`);
    }
    const restartTitle = "Reiniciar scraping básico desde el comienzo";
    actions.push(`<button type="button" class="secondary cron-restart" data-basic-mode="restart"
      title="${escapeHtml(restartTitle)}" aria-label="${escapeHtml(restartTitle)}"${starting ? " disabled" : ""}>
      ${starting ? "Iniciando…" : "Reiniciar"}
    </button>`);
  }
  if (!actions.length) return badge;
  return `<div class="cron-group-action">${badge}${actions.join("")}</div>`;
}

function renderBasic(payload) {
  const job = payload.basic_scrape || { status: "idle", title: "Scraping básico" };
  const button = $("basic-scrape-run");
  const wrap = $("basic-scrape-wrap");
  const meta = $("basic-scrape-meta");
  const formActions = $("basic-scrape-actions");
  const running = ["running", "paused"].includes(job.status);
  const failed = ["failed", "stopped"].includes(job.status);
  const canContinue =
    (failed && (Number(job.last_run?.processed) || 0) > 0) ||
    (["partial", "done"].includes(job.status) && groupIncomplete(job));
  if (!["running", "paused"].includes(job.status)) stoppingBasic = false;
  if (button && button.dataset.busy !== "1") {
    button.disabled = running || startingBasic;
    if (running) button.textContent = "En curso";
    else if (canContinue) {
      button.textContent = "Continuar";
      button.dataset.startMode = "continue";
    } else if (failed || job.status === "done" || job.status === "partial") {
      button.textContent = "Reiniciar";
      button.dataset.startMode = "restart";
    } else {
      button.textContent = "Scraping básico";
      button.dataset.startMode = "";
    }
  }
  if (formActions) {
    if (running) {
      const stopping = stoppingBasic || job.progress?.phase === "stopping";
      const stopTitle = "Detener scraping básico";
      formActions.innerHTML = `<button type="button" class="secondary cron-stop" data-stop-basic="1"
        title="${escapeHtml(stopTitle)}" aria-label="${escapeHtml(stopTitle)}"${stopping ? " disabled" : ""}>
        ${stopping ? "Deteniendo…" : "Detener"}
      </button>`;
    } else {
      formActions.innerHTML = "";
    }
  }
  if (meta) {
    meta.textContent = running
      ? "Recorriendo productos guardados…"
      : job.last_run
        ? `Última corrida ${formatWhen(job.last_run.finished_at || job.last_run.started_at)}`
        : "Sin corridas todavía.";
  }
  if (!wrap) return;
  if (!job.last_run && !job.progress) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  const like = { status: job.status, progress: job.progress, last_run: job.last_run };
  const counts = countLine(job.progress || job.last_run);
  wrap.querySelector("tbody").innerHTML = `
    <tr data-status="${escapeHtml(job.status)}">
      <td>
        <strong>${escapeHtml(job.title || "Scraping básico")}</strong>
        <div class="muted">${escapeHtml(job.id || "scraping_basico")}</div>
      </td>
      <td>${basicStatusCell(job)}</td>
      <td>
        ${progressCell(like)}
        ${counts ? `<div class="cron-basic-counts muted">${escapeHtml(counts)}</div>` : ""}
      </td>
      <td>${lastRunCell(like)}</td>
    </tr>`;
}

async function startBasicScrape(mode) {
  const button = $("basic-scrape-run");
  if (startingBasic) return;
  startingBasic = true;
  if (button) {
    button.dataset.busy = "1";
    button.disabled = true;
    button.textContent = mode === "continue" ? "Continuando…" : mode === "restart" ? "Reiniciando…" : "Iniciando…";
  }
  try {
    const body = {};
    if (mode) body.mode = mode;
    const result = await json("/api/admin/basic-scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    flash(result.message || "Scraping básico iniciado.");
    watchUntil = Date.now() + 60000;
  } catch (error) {
    flash(error.message, false);
  } finally {
    startingBasic = false;
    if (button) delete button.dataset.busy;
  }
  await refresh().catch((error) => flash(error.message, false));
}

async function stopBasicScrape(button) {
  if (button?.disabled || stoppingBasic) return;
  stoppingBasic = true;
  if (button) {
    button.disabled = true;
    button.textContent = "Deteniendo…";
  }
  try {
    const result = await json("/api/admin/basic-scrape/stop", { method: "POST" });
    flash(result.message || "Deteniendo scraping básico.");
    watchUntil = Date.now() + 60000;
  } catch (error) {
    flash(error.message, false);
    stoppingBasic = false;
  }
  await refresh().catch((error) => flash(error.message, false));
}

function syncRunButton() {
  const select = $("store-select");
  const button = $("store-run");
  const formActions = $("store-scrape-actions");
  if (!select || !button || button.dataset.busy === "1") return;
  const tienda = select.value || "";
  const job = lastStoreJobs.find((item) => item.id === tienda);
  const status = job?.status || "idle";
  const running = ["running", "paused"].includes(status);
  const failed = ["failed", "stopped"].includes(status);
  const processed = Number(job?.last_run?.processed) || 0;
  const canContinue =
    (failed && processed > 0) ||
    (["partial", "done"].includes(status) && job && groupIncomplete(job));
  const starting = Boolean(tienda && startingStores.has(tienda));
  const title = job?.title || tienda;

  button.dataset.startStore = tienda;
  if (!tienda) {
    button.disabled = true;
    button.textContent = "Correr scraping";
    button.dataset.startMode = "";
  } else if (running || starting) {
    button.disabled = true;
    button.textContent = running ? "En curso" : "Iniciando…";
    button.dataset.startMode = "";
  } else if (canContinue) {
    button.disabled = false;
    button.textContent = "Continuar";
    button.dataset.startMode = "continue";
  } else if (failed || status === "done" || status === "partial") {
    button.disabled = false;
    button.textContent = "Reiniciar";
    button.dataset.startMode = "restart";
  } else {
    button.disabled = false;
    button.textContent = "Correr scraping";
    button.dataset.startMode = "";
  }

  if (formActions) {
    const bits = [];
    if (running && tienda) {
      const stopping = stoppingStores.has(tienda) || job?.progress?.phase === "stopping";
      const stopTitle = `Detener scraping de ${title}`;
      bits.push(`<button type="button" class="secondary cron-stop" data-stop-store="${escapeHtml(tienda)}"
        title="${escapeHtml(stopTitle)}" aria-label="${escapeHtml(stopTitle)}"${stopping ? " disabled" : ""}>
        ${stopping ? "Deteniendo…" : "Detener"}
      </button>`);
    } else if (canContinue && tienda) {
      const restartTitle = `Reiniciar scraping de ${title} desde el comienzo`;
      bits.push(`<button type="button" class="secondary cron-restart" data-start-store="${escapeHtml(tienda)}" data-start-mode="restart"
        title="${escapeHtml(restartTitle)}" aria-label="${escapeHtml(restartTitle)}"${starting ? " disabled" : ""}>
        ${starting ? "Iniciando…" : "Reiniciar"}
      </button>`);
    }
    formActions.innerHTML = bits.join("");
  }
}

function render(payload) {
  lastCronPayload = payload;
  for (const group of payload.groups || []) {
    if (!["running", "paused"].includes(group.status)) stoppingGroups.delete(group.id);
  }
  for (const job of payload.store_jobs || []) {
    if (!["running", "paused"].includes(job.status)) stoppingStores.delete(job.id);
  }
  const sched = payload.schedule || {};
  const enabled = sched.enabled ? "activa" : "desactivada";
  $("cron-meta").textContent =
    `Hoy ${payload.today || ""} (${payload.timezone || "America/Santiago"}). ` +
    `Corrida diaria ${enabled}` +
    (sched.stagger_minutes != null ? ` · escalonado ${sched.stagger_minutes} min` : "") +
    (sched.batch_budget_minutes ? ` · turnos de ${sched.batch_budget_minutes} min` : "") +
    (sched.hint ? ` · ${sched.hint}` : "");
  const toggle = $("cron-toggle");
  if (toggle) {
    toggle.disabled = false;
    toggle.dataset.action = sched.paused ? "resume" : "pause";
    toggle.className = sched.paused ? "" : "secondary";
    toggle.textContent = sched.paused ? "Reanudar corridas" : "Pausar corridas";
    toggle.setAttribute("aria-pressed", sched.paused ? "true" : "false");
  }

  const groups = payload.groups || [];
  if (!groups.length) {
    $("cron-body").innerHTML = `<tr><td colspan="6" class="muted">No hay grupos de tiendas.</td></tr>`;
    return;
  }
  $("cron-body").innerHTML = groups
    .map(
      (group) => `
    <tr data-status="${escapeHtml(normalizedGroupStatus(group.status))}">
      <td>
        <strong>${escapeHtml(group.title || group.id)}</strong>
        <div class="muted">${escapeHtml(group.id)} · ${group.store_count || 0} tiendas</div>
      </td>
      <td>${escapeHtml(group.schedule?.label || "—")}</td>
      <td>${groupStatusCell(group)}</td>
      <td>${groupActionsCell(group, sched.paused)}</td>
      <td>${progressCell(group)}</td>
      <td>${lastRunCell(group)}</td>
    </tr>`
    )
    .join("");
}

let timer = null;
let watchUntil = 0;

async function refresh() {
  const payload = await json("/api/admin/cron-batches");
  fillStores(payload);
  renderBasic(payload);
  renderStoreJobs(payload);
  render(payload);
  restoreAlerts();
  syncRunButton();
  const watching = Date.now() < watchUntil;
  $("cron-refresh").textContent = payload.any_running || watching
    ? "Actualizando cada 3 s…"
    : "Actualiza al recargar o cuando un lote arranque.";
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  if (payload.any_running || watching) {
    timer = setTimeout(() => {
      refresh().catch((error) => flash(error.message, false));
    }, 3000);
  }
}

$("store-select")?.addEventListener("change", () => {
  syncRunButton();
  if (lastCronPayload) renderStoreJobs(lastCronPayload);
});

$("cron-toggle")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const action = button.dataset.action || "pause";
  button.disabled = true;
  button.textContent = action === "pause" ? "Pausando…" : "Reanudando…";
  try {
    const result = await json("/api/admin/cron-control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    flash(result.message || (action === "pause" ? "Corridas pausadas." : "Corridas reanudadas."));
    watchUntil = Date.now() + 15000;
    await refresh();
  } catch (error) {
    flash(error.message, false);
    button.disabled = false;
  }
});

$("basic-scrape-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("basic-scrape-run");
  const mode = button?.dataset.startMode || "";
  await startBasicScrape(mode || undefined);
});

document.addEventListener("click", (event) => {
  const stopBasic = event.target.closest("button[data-stop-basic]");
  if (stopBasic) {
    stopBasicScrape(stopBasic).catch((error) => flash(error.message, false));
    return;
  }
  const basic = event.target.closest("button[data-basic-mode]");
  if (basic) {
    startBasicScrape(basic.dataset.basicMode).catch((error) => flash(error.message, false));
    return;
  }
  const stopStoreBtn = event.target.closest("button[data-stop-store]");
  if (stopStoreBtn) {
    stopStore(stopStoreBtn).catch((error) => flash(error.message, false));
    return;
  }
  const startStoreBtn = event.target.closest("button[data-start-store]");
  if (startStoreBtn) {
    startStore(startStoreBtn).catch((error) => flash(error.message, false));
    return;
  }
  const stop = event.target.closest("button[data-stop-group]");
  if (stop) {
    stopGroup(stop).catch((error) => flash(error.message, false));
    return;
  }
  const start = event.target.closest("button[data-start-group]");
  if (start) {
    startGroup(start).catch((error) => flash(error.message, false));
    return;
  }
  const close = event.target.closest("[data-close-alerts]");
  if (close) {
    closeAlerts();
    return;
  }
  const button = event.target.closest("button.cron-alerts[data-run]");
  if (!button) return;
  toggleAlerts(button).catch((error) => flash(error.message, false));
});

$("store-scrape-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("store-run");
  const tienda = $("store-select")?.value;
  if (!button || !tienda) return;
  button.dataset.startStore = tienda;
  await startStore(button);
});

refresh().catch((error) => flash(error.message, false));

// $, money, attr, thumbMarkup, priceAlertButtonHtml y hydratePriceAlertButtons vienen de prices.js

let page = 1;
let totalPages = 1;
let loadToken = 0;
let availableDays = [];
let availableDaySet = new Set();
let calendarCursor = null; // Date at first of visible month (UTC)
let dayPickerOpen = false;
let chileToday = "";
const pageSearchForm = document.querySelector(".desktop-quick-search");
const pageSearchInput = pageSearchForm?.querySelector('input[name="q"]');
const MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
$("super-filter").checked = new URLSearchParams(location.search).get("super") === "1";

function flash(text, ok = false) {
  $("flash").hidden = false;
  $("flash").className = ok ? "summary" : "err";
  $("flash").textContent = text;
}

function parseDay(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || "").trim());
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDayKey(date) {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDayLabel(value) {
  if (!value || value === chileToday) return "Hoy";
  const date = parseDay(value);
  if (!date) return value;
  return `${date.getUTCDate()} ${MONTHS_ES[date.getUTCMonth()].slice(0, 3)} ${date.getUTCFullYear()}`;
}

function monthStart(date) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1));
}

function shiftMonth(date, delta) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + delta, 1));
}

function syncDayLabel() {
  const label = $("day-picker-label");
  if (label) label.textContent = formatDayLabel($("day").value || chileToday);
}

function syncDayUrl() {
  const url = new URL(location.href);
  const selected = $("day").value;
  if (!selected || selected === chileToday) url.searchParams.delete("day");
  else url.searchParams.set("day", selected);
  const next = `${url.pathname}${url.search}${url.hash}`;
  if (`${location.pathname}${location.search}${location.hash}` !== next) {
    history.replaceState(null, "", next);
  }
}

function setAvailableDays(days, selected, today) {
  chileToday = String(today || chileToday || "").trim();
  availableDays = [...new Set((days || []).map((item) => String(item || "").trim()).filter(Boolean))]
    .sort()
    .reverse();
  if (chileToday && !availableDays.includes(chileToday)) {
    availableDays = [chileToday, ...availableDays];
  }
  availableDaySet = new Set(availableDays);
  const wanted = String(selected || "").trim();
  const current = availableDaySet.has(wanted) ? wanted : chileToday;
  const anchor = parseDay(current || availableDays[0]) || new Date();
  calendarCursor = monthStart(anchor);
  // Vacío en el control = hoy (no cuenta como filtro activo).
  $("day").value = current && current !== chileToday ? current : "";
  syncDayLabel();
  syncDayUrl();
  renderDayCalendar();
}

function renderDayCalendar() {
  const grid = $("day-picker-grid");
  const monthLabel = $("day-month-label");
  if (!grid || !monthLabel || !calendarCursor) return;
  monthLabel.textContent = `${MONTHS_ES[calendarCursor.getUTCMonth()]} ${calendarCursor.getUTCFullYear()}`;
  const selected = $("day").value || chileToday;
  const year = calendarCursor.getUTCFullYear();
  const month = calendarCursor.getUTCMonth();
  const first = new Date(Date.UTC(year, month, 1));
  const startOffset = (first.getUTCDay() + 6) % 7;
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const cells = [];
  for (let i = 0; i < startOffset; i += 1) {
    cells.push(`<span class="day-picker-cell empty" aria-hidden="true"></span>`);
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const key = formatDayKey(new Date(Date.UTC(year, month, day)));
    const enabled = availableDaySet.has(key);
    const isSelected = selected === key;
    const classes = ["day-picker-cell"];
    if (!enabled) classes.push("disabled");
    if (isSelected) classes.push("selected");
    if (enabled && key === chileToday) classes.push("latest");
    cells.push(
      enabled
        ? `<button type="button" class="${classes.join(" ")}" data-day="${attr(key)}" aria-pressed="${isSelected ? "true" : "false"}">${day}</button>`
        : `<span class="${classes.join(" ")}" aria-disabled="true">${day}</span>`
    );
  }
  grid.innerHTML = cells.join("");
  const earliest = availableDays.length ? parseDay(availableDays[availableDays.length - 1]) : null;
  const latest = availableDays.length ? parseDay(availableDays[0]) : null;
  const prev = $("day-prev-month");
  const next = $("day-next-month");
  if (prev) prev.disabled = Boolean(earliest && calendarCursor <= monthStart(earliest));
  if (next) next.disabled = Boolean(latest && calendarCursor >= monthStart(latest));
}

function openDayPicker(open = true) {
  const picker = $("day-picker");
  const toggle = $("day-picker-toggle");
  if (!picker || !toggle) return;
  dayPickerOpen = open;
  picker.hidden = !open;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) renderDayCalendar();
}

function closeDayPicker() {
  openDayPicker(false);
}

function setDayValue(value, { reload: shouldReload = false } = {}) {
  const next = String(value || "").trim();
  const resolved = !next || next === chileToday
    ? ""
    : (availableDaySet.has(next) ? next : "");
  $("day").value = resolved;
  syncDayLabel();
  syncDayUrl();
  if (resolved) {
    const parsed = parseDay(resolved);
    if (parsed) calendarCursor = monthStart(parsed);
  } else if (chileToday) {
    const parsed = parseDay(chileToday);
    if (parsed) calendarCursor = monthStart(parsed);
  }
  renderDayCalendar();
  updateFilterBadge("real-filters", "real-filter-count");
  if (shouldReload) {
    page = 1;
    load();
  }
}

function setDealsBusy(on) {
  const deals = $("deals");
  const filters = $("real-filters");
  if (filters) filters.setAttribute("aria-busy", on ? "true" : "false");
  if (deals) {
    deals.setAttribute("aria-busy", on ? "true" : "false");
    if (on) {
      deals.innerHTML =
        `<div class="panel muted compare-loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span> Cargando ofertas…</div>`;
    }
  }
  if (on) $("summary").textContent = "Cargando ofertas…";
  $("prev").disabled = on || page <= 1;
  $("next").disabled = on || page >= totalPages;
  document.querySelectorAll("#real-filters [data-filter-control]").forEach((el) => {
    el.disabled = Boolean(on);
  });
  $("day-picker-toggle")?.toggleAttribute("disabled", Boolean(on));
}

function kindLabel(kind) {
  if (kind === "comparacion") return "Comparación entre tiendas";
  if (kind === "historial") return "Bajó respecto a otra fecha";
  if (kind === "iguales") return "Mismo precio en tiendas";
  return kind;
}

function fillSelect(id, values, current, anyLabel) {
  $(id).innerHTML =
    `<option value="">${anyLabel}</option>` +
    values
      .map((value) => `<option value="${attr(value)}" ${value === current ? "selected" : ""}>${attr(value)}</option>`)
      .join("");
}

function gapMark(item) {
  if ((item.gap || 0) > 0) {
    return `<span class="badge off">−${Math.round(item.gap_percent || 0)}%</span>`;
  }
  return `<span class="badge">mismo precio</span>`;
}

function timesfmSignal(item) {
  const signal = item.timesfm_signal;
  if (!signal) return "";
  return `<div class="timesfm-offer-signal timesfm-${attr(signal.status)}">
    <strong>TimesFM experimental · ${attr(signal.label)}</strong>
    <span>${attr(signal.explanation)}</span>
    <small>Esperado: ${money(signal.range_low)}–${money(signal.range_high)} · estimación, no garantía</small>
  </div>`;
}

function storeLine(row) {
  const title = row.store_title || row.store;
  const off = row.discount >= 10 ? discountBadge(row.discount, 10) : "";
  const labels = [
    row.best_price ? '<span class="badge off">Mejor precio</span>' : "",
    row.strongest_verified ? '<span class="badge">Mayor baja comprobada</span>' : "",
    row.strongest_published ? '<span class="badge ghost">Mayor descuento publicado</span>' : "",
    row.payment_restricted ? '<span class="badge ghost">Solo tarjeta</span>' : "",
  ].filter(Boolean).join(" ");
  const ficha = row.product_id
    ? `/producto?store=${encodeURIComponent(row.store)}&id=${encodeURIComponent(row.product_id)}`
    : "";
  const verified = row.verified_discount > 0 ? `<small>${Math.round(row.verified_discount)}% vs historial</small>` : "";
  const cardNote = row.price_card && row.price_card !== row.price
    ? `<small>Con tarjeta ${attr(row.payment_card_name || "")}: ${money(row.price_card)}</small>`
    : "";
  const inner = `<span class="compare-store-brand">${storeLogo(row.display_store || row.store, title)}</span><span class="compare-store-value"><span class="price">${money(row.price)}</span>${off}${verified}${cardNote}${labels}</span>`;
  if (ficha) {
    return `<li class="${row.win ? "win" : ""}"><a href="${attr(ficha)}">${inner}</a></li>`;
  }
  return `<li class="${row.win ? "win" : ""}">${inner}</li>`;
}

function dealCard(item) {
  const image = thumbMarkup(
    "deal-img",
    item.product_id
      ? `/api/thumb?store=${encodeURIComponent(item.store)}&id=${encodeURIComponent(item.product_id)}`
      : ""
  );
  const ficha = item.product_id
    ? `/producto?store=${encodeURIComponent(item.store)}&id=${encodeURIComponent(item.product_id)}`
    : "";
  const title = ficha
    ? `<a class="deal-name" href="${attr(ficha)}">${attr(item.name)}</a>`
    : `<span class="deal-name">${attr(item.name)}</span>`;
  const kinds = (item.kinds || [])
    .map((kind) => `<span class="badge">${attr(kindLabel(kind))}</span>`)
    .join("");
  const history = item.was_full_price_on
    ? `<p class="muted">Sin descuento el ${attr(item.was_full_price_on)}</p>`
    : "";
  const stores = (item.stores || []).map(storeLine).join("");
  const confidence = Math.round(Number(item.entity_confidence || 0) * 100);
  const identity = confidence >= 90
    ? `<span class="badge">Coincidencia alta ${confidence}%</span>`
    : `<span class="badge ghost">Coincidencia ${confidence}%: revisa modelo y variante</span>`;
  const bestStore = item.best_price_store_title || item.best_price_store || "otra tienda";
  const market = item.market_best
    ? '<span class="badge off">Es el menor precio actual</span>'
    : `<span class="badge ghost">No es el menor precio · ${attr(bestStore)} tiene ${money(item.best_price)}</span>`;
  const discountSummary = `Comercial: ${Math.round(item.commercial_discount || item.published_discount || 0)}% · ahorro real: ${Math.round(item.real_savings_percent || item.verified_discount || 0)}%`;
  const fresh = typeof updatedStamp === "function"
    ? updatedStamp(item.updated_at)
    : typeof updatedAgo === "function"
      ? updatedAgo(item.updated_at)
      : "";
  const suspicion = (item.suspicion_labels || []).length
    ? `<p class="muted">${attr((item.suspicion_labels || []).join(" · "))}</p>`
    : "";
  return `
    <article class="panel deal">
      ${image}
      <div class="deal-body">
        ${title}
        <p class="muted">${attr(item.brand || item.category || "")}${fresh ? ` · ${attr(fresh)}` : ""}</p>
        <div class="deal-kinds">${kinds}${market}${identity}</div>
        <div class="deal-prices">
          <div>
            <span class="deal-label">Todo medio</span>
            <span class="price">${money(item.price)}</span>
            ${item.price_card && item.price_card !== item.price
              ? `<small class="muted">Con tarjeta ${attr(item.payment_card_name || "")}: ${money(item.price_card)} (no comparable)</small>`
              : ""}
          </div>
          <div>
            <span class="deal-label">Otra tienda</span>
            <span class="deal-saving">${money(item.rival_price)}${gapMark(item)}</span>
          </div>
        </div>
        <p class="muted">${attr(discountSummary)} · puntaje ${Number(item.offer_score || 0).toLocaleString("es-CL")}/100</p>
        <p class="deal-reason">${attr(item.reason || "")}</p>
        ${suspicion}
        ${timesfmSignal(item)}
        ${history}
        <ul class="compare-stores">${stores}</ul>
        <div class="card-footer">
          ${item.url ? `<a class="muted" href="${attr(item.url)}" target="_blank" rel="noreferrer">ir a la tienda</a>` : "<span></span>"}
          ${typeof priceAlertButtonHtml === "function" ? priceAlertButtonHtml({ store: item.store, productId: item.product_id, name: item.name }) : ""}
        </div>
      </div>
    </article>`;
}

function render(data) {
  const rows = data.items || [];
  const total = data.total || 0;
  totalPages = Math.max(1, Math.ceil(total / (data.size || 40)));
  const comparacion = $("comparacion").checked;
  const historial = $("historial").checked;
  const iguales = $("iguales").checked;
  const superOnly = $("super-filter").checked;
  const timesfmSummary = $("timesfm-summary");
  if (timesfmSummary) {
    const admin = Boolean(window.retailUser && window.retailUser.role === "admin");
    if (admin) {
      const timesfm = data.timesfm_signal_status || {};
      timesfmSummary.textContent = timesfm.enabled
        ? `TimesFM complementa el análisis actual en ${timesfm.visible_signals || 0} ofertas de esta página; no cambia la clasificación.`
        : `TimesFM aún no se muestra en ofertas: ${timesfm.reason || "falta validar su precisión"} El análisis actual sigue funcionando sin cambios.`;
    } else {
      timesfmSummary.textContent = "";
    }
  }
  const dayNote = data.day && data.day !== chileToday
    ? ` del ${formatDayLabel(data.day)}`
    : " de hoy";
  if (!comparacion && !historial && !iguales && !superOnly) {
    $("summary").textContent = "Activa al menos un tipo de oferta.";
  } else if (total) {
    const minGap = Number($("min-gap").value) || 0;
    const gapNote = minGap ? ` Mínimo ${minGap}% más barato que la otra tienda.` : "";
    const kind = superOnly ? ` super ofertas (más de ${data.min_super || 50}% de descuento real)` : " ofertas reales";
    $("summary").textContent = `Mostrando ${rows.length} de ${total.toLocaleString("es-CL")}${kind}${dayNote}.${gapNote}`;
  } else {
    $("summary").textContent = `No hay productos${dayNote} que cumplan esas comparaciones con los precios guardados.`;
  }
  $("deals").innerHTML = rows.length
    ? rows.map(dealCard).join("")
    : `<p class="panel muted">Sin ofertas reales para estos filtros.</p>`;
  saveProductTrail(rows);
  if (typeof hydratePriceAlertButtons === "function") {
    hydratePriceAlertButtons($("deals")).catch(() => {});
  }
  const pager = RetailPager.render(data.page || 1, totalPages);
  page = pager.page;
}

function params() {
  const query = new URLSearchParams({
    page: String(page),
    size: $("size").value || "40",
    comparacion: $("comparacion").checked ? "true" : "false",
    historial: $("historial").checked ? "true" : "false",
    iguales: $("iguales").checked ? "true" : "false",
    super: $("super-filter").checked ? "true" : "false",
  });
  if (pageSearchInput?.value.trim()) query.set("q", pageSearchInput.value.trim());
  if ($("category").value) query.set("category", $("category").value);
  if ($("store").value) query.set("store", $("store").value);
  if (Number($("min-gap").value) > 0) query.set("min_gap", $("min-gap").value);
  const day = $("day").value || chileToday || new URLSearchParams(location.search).get("day") || "";
  if (day) query.set("day", day);
  return query;
}

async function load() {
  const token = ++loadToken;
  if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(true);
  setDealsBusy(true);
  try {
  if (typeof ensureUser === "function") await ensureUser();
  if (token !== loadToken) return;
  const response = await fetch(`/api/reales?${params()}`);
  const data = await response.json().catch(() => ({}));
  if (token !== loadToken) return;
  if (!response.ok) {
    flash(typeof data.detail === "string" ? data.detail : response.statusText);
    $("deals").innerHTML = `<p class="panel muted">No se pudieron cargar las ofertas.</p>`;
    $("summary").textContent = "";
    return;
  }
  $("flash").hidden = true;
  setAvailableDays(data.days || [], data.day, data.today || data.day);
  fillSelect("store", data.stores || [], $("store").value, "todas");
  fillSelect("category", data.categories || [], $("category").value, "todas");
  render(data);
  updateFilterBadge("real-filters", "real-filter-count");
  } catch (error) {
    if (token !== loadToken) return;
    flash(error.message || "Error al cargar ofertas");
    $("deals").innerHTML = `<p class="panel muted">No se pudieron cargar las ofertas.</p>`;
    $("summary").textContent = "";
  } finally {
    if (token === loadToken) {
      setDealsBusy(false);
      if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(false);
    }
  }
}

function reload() {
  page = 1;
  load();
}

function applyStartFilters() {
  const url = new URLSearchParams(location.search);
  const day = String(url.get("day") || "").trim();
  if (day) $("day").value = day;
  if (pageSearchInput && url.get("q")) pageSearchInput.value = url.get("q");
}

["comparacion", "historial", "iguales", "super-filter", "category", "store", "min-gap", "size"].forEach((id) => {
  $(id).addEventListener("change", reload);
});

$("day-picker-toggle")?.addEventListener("click", (event) => {
  event.preventDefault();
  openDayPicker(!dayPickerOpen);
});
$("day-prev-month")?.addEventListener("click", () => {
  if (!calendarCursor) return;
  calendarCursor = shiftMonth(calendarCursor, -1);
  renderDayCalendar();
});
$("day-next-month")?.addEventListener("click", () => {
  if (!calendarCursor) return;
  calendarCursor = shiftMonth(calendarCursor, 1);
  renderDayCalendar();
});
$("day-today")?.addEventListener("click", () => {
  closeDayPicker();
  setDayValue("", { reload: true });
});
$("day-picker-grid")?.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-day]");
  if (!button) return;
  closeDayPicker();
  setDayValue(button.dataset.day, { reload: true });
});
document.addEventListener("click", (event) => {
  if (!dayPickerOpen) return;
  const field = event.target.closest(".day-picker-field");
  if (field) return;
  closeDayPicker();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && dayPickerOpen) closeDayPicker();
});

pageSearchForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  reload();
});
pageSearchInput?.addEventListener("search", reload);

$("prev").addEventListener("click", () => {
  if (page > 1) {
    page -= 1;
    load();
  }
});
$("next").addEventListener("click", () => {
  if (page < totalPages) {
    page += 1;
    load();
  }
});

applyStartFilters();
load();

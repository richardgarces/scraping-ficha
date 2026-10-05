// $, money, attr, discountOf, discountBadge y priceLadder vienen de prices.js

const RULES = {
  price_drop_percent: "Bajó de precio (%)",
  price_drop_amount: "Bajó de precio ($)",
  cross_store_gap: "Mejor precio vs. competencia",
  below_median: "Bajo su precio habitual",
  watch_target: "Llegó a tu precio objetivo",
  watch_change: "Cambió el precio",
};

let page = 1;
let totalPages = 1;
let availableDays = [];
let availableDaySet = new Set();
let calendarCursor = null; // Date at first of visible month
let dayPickerOpen = false;
const pageSearchForm = document.querySelector(".desktop-quick-search");
const pageSearchInput = pageSearchForm?.querySelector('input[name="q"]');
const MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

function flash(text, ok = false) {
  $("flash").hidden = false;
  $("flash").className = ok ? "summary" : "err";
  $("flash").textContent = text;
}

function ruleLabel(rule) {
  return (rule || "")
    .split("+")
    .map((item) => RULES[item] || item)
    .filter((item, index, list) => list.indexOf(item) === index)
    .join(" · ");
}

function fillSelect(select, values, current, anyLabel, labels) {
  select.innerHTML =
    `<option value="">${anyLabel}</option>` +
    values
      .map((value) => {
        const text = (labels && labels[value]) || value;
        return `<option value="${attr(value)}" ${value === current ? "selected" : ""}>${attr(text)}</option>`;
      })
      .join("");
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
  if (!value) return "Más reciente";
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
  if (label) label.textContent = formatDayLabel($("day").value);
}

function setDayValue(value, { reload: shouldReload = false } = {}) {
  const next = availableDaySet.has(value) ? value : "";
  $("day").value = next;
  syncDayLabel();
  if (next) {
    const parsed = parseDay(next);
    if (parsed) calendarCursor = monthStart(parsed);
  } else if (availableDays[0]) {
    const parsed = parseDay(availableDays[0]);
    if (parsed) calendarCursor = monthStart(parsed);
  }
  renderDayCalendar();
  if (shouldReload) {
    page = 1;
    load(false).catch((error) => flash(error.message));
  } else {
    updateFilterBadge("today-filters", "today-filter-count");
  }
}

function setAvailableDays(days, selected) {
  availableDays = [...new Set((days || []).map((item) => String(item || "").trim()).filter(Boolean))]
    .sort()
    .reverse();
  availableDaySet = new Set(availableDays);
  const current = availableDaySet.has(selected) ? selected : ($("day").value && availableDaySet.has($("day").value) ? $("day").value : "");
  const anchor = parseDay(current || availableDays[0]) || new Date();
  calendarCursor = monthStart(anchor);
  $("day").value = current;
  syncDayLabel();
  renderDayCalendar();
}

function renderDayCalendar() {
  const grid = $("day-picker-grid");
  const monthLabel = $("day-month-label");
  if (!grid || !monthLabel || !calendarCursor) return;
  monthLabel.textContent = `${MONTHS_ES[calendarCursor.getUTCMonth()]} ${calendarCursor.getUTCFullYear()}`;
  const selected = $("day").value;
  const year = calendarCursor.getUTCFullYear();
  const month = calendarCursor.getUTCMonth();
  const first = new Date(Date.UTC(year, month, 1));
  // Monday-first: Sunday=0 -> 6
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
    if (enabled && !selected && availableDays[0] === key) classes.push("latest");
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

function renderDeals(data) {
  const rows = data.deals || [];
  const total = data.total || 0;
  const needle = pageSearchInput?.value.trim() || "";
  totalPages = Math.max(1, Math.ceil(total / (data.size || 80)));
  if (total) {
    const shown = `Mostrando ${rows.length} de ${total.toLocaleString("es-CL")}`;
    $("summary").textContent = needle
      ? `${shown} ofertas nuevas para “${needle}” · Ahorro ${money(data.total_saving)}`
      : `${shown} ofertas nuevas · Ahorro total detectado ${money(data.total_saving)}`;
  } else {
    $("summary").textContent = needle
      ? `Ninguna oferta nueva de este día coincide con “${needle}”.`
      : "No hay ofertas nuevas para ese día. Las que ya salieron antes no se repiten.";
  }
  $("deals").innerHTML = rows.length
    ? rows.map(dealCard).join("")
    : `<p class="panel muted">Sin ofertas.</p>`;
  saveProductTrail(rows);
  const pager = RetailPager.render(data.page || 1, totalPages);
  page = pager.page;
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
    : item.url
      ? `<a class="deal-name" href="${attr(item.url)}" target="_blank" rel="noreferrer">${attr(item.name)}</a>`
      : `<span class="deal-name">${attr(item.name)}</span>`;
  const cta = ficha
    ? `<a class="deal-cta" href="${attr(ficha)}">Ver ficha</a>`
    : item.url
      ? `<a class="deal-cta" href="${attr(item.url)}" target="_blank" rel="noreferrer">Ver oferta</a>`
      : "";
  const analysis = item.analysis_discount_pct
    ? `<p class="muted">${Number(item.analysis_discount_pct).toLocaleString("es-CL")}% bajo su precio habitual (${money(item.analysis_reference_price)}); esta referencia histórica no es el precio normal publicado.</p>`
    : "";
  const fresh = typeof updatedAgo === "function" ? updatedAgo(item.updated_at || item.created_at) : "";
  return `
    <article class="panel deal">
      ${image}
      <div class="deal-body">
        ${title}
        <p class="muted">${attr(item.category || "")}${fresh ? ` · ${attr(fresh)}` : ""}</p>
        <div class="deal-meta">
          ${storeLogo(item.display_store || item.store, item.store_title || item.store)}
          ${cta}
        </div>
        <div class="deal-prices">
          <div>
            <span class="deal-label">Precio</span>
            <span class="price">${money(item.price)}</span>
          </div>
          <div>
            <span class="deal-label">Ahorro</span>
            <span class="deal-saving">${item.saving ? money(item.saving) : "—"}${item.discount ? discountBadge(item.discount, 1) : ""}</span>
          </div>
        </div>
        <p class="deal-reason"><span>Motivo</span> ${attr(ruleLabel(item.rule))}</p>
        ${analysis}
      </div>
    </article>`;
}

function renderRuns(runs) {
  $("runs").innerHTML = (runs || []).length
    ? runs
        .map(
          (run) => `
          <tr>
            <td class="muted">${(run.started_at || "").replace("T", " ").slice(0, 16)}</td>
            <td>${run.status || ""}</td>
            <td>${run.processed || 0} / ${run.items || 0}</td>
            <td class="muted">+${run.saved_upserted || 0} ~${run.saved_modified || 0}</td>
            <td class="${run.failed ? "err" : "muted"}">${run.failed || 0}</td>
            <td class="muted">${run.without_price || 0}</td>
            <td>${run.alert_count || 0}</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="7" class="muted">Todavía no se ha corrido el batch.</td></tr>`;
}

function params() {
  const query = new URLSearchParams({ page: String(page), size: $("size").value || "80" });
  if (pageSearchInput?.value.trim()) query.set("q", pageSearchInput.value.trim());
  if ($("day").value) query.set("day", $("day").value);
  if ($("category").value) query.set("category", $("category").value);
  if ($("store").value) query.set("store", $("store").value);
  if ($("rule").value) query.set("rule", $("rule").value);
  if (Number($("min-price").value) > 0) query.set("min_price", $("min-price").value);
  if (Number($("max-price").value) > 0) query.set("max_price", $("max-price").value);
  if (Number($("min-saving").value) > 0) query.set("min_saving", $("min-saving").value);
  if (Number($("min-discount").value) > 0) query.set("min_discount", $("min-discount").value);
  if ($("sort").value) query.set("sort", $("sort").value);
  return query;
}

async function load(keepFilters = false) {
  if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(true);
  try {
  const response = await fetch(`/api/deals?${params()}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    flash(typeof data.detail === "string" ? data.detail : response.statusText);
    return;
  }
  $("flash").hidden = true;
  setAvailableDays(data.days || [], data.day);
  if (!keepFilters) {
    const facets = data.facets || {};
    fillSelect($("category"), facets.categories || [], $("category").value, "todas");
    fillSelect($("store"), facets.stores || [], $("store").value, "todas", data.store_labels || {});
    fillSelect($("rule"), facets.rules || [], $("rule").value, "todos", RULES);
  }
  renderDeals(data);
  renderRuns(data.runs);
  updateFilterBadge("today-filters", "today-filter-count");
  } finally {
    if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(false);
  }
}

function reload() {
  page = 1;
  load(true).catch((error) => flash(error.message));
}

["category", "store", "rule", "min-price", "max-price", "min-saving", "min-discount", "sort", "size"].forEach((id) => {
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
$("day-latest")?.addEventListener("click", () => {
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
    load(true).catch((error) => flash(error.message));
  }
});
$("next").addEventListener("click", () => {
  if (page < totalPages) {
    page += 1;
    load(true).catch((error) => flash(error.message));
  }
});

load().catch((error) => flash(error.message));

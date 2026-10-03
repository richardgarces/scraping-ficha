// $, money, attr, discountOf, cardLabel y priceLadder vienen de prices.js

function flash(text) {
  $("flash").hidden = false;
  $("flash").className = "err";
  $("flash").textContent = text;
}

function mountBackToResults() {
  const link = $("back-results");
  const siblings = $("product-siblings");
  const prev = $("prev-product");
  const next = $("next-product");
  const position = $("product-position");
  const trail = typeof readProductTrail === "function" ? readProductTrail() : null;
  const params = new URLSearchParams(location.search);
  const store = params.get("store") || "";
  const id = params.get("id") || "";
  const listPaths = new Set(["/", "/catalogo", "/hoy", "/reales", "/super", "/ofertas"]);

  let backHref = trail?.source || "";
  let useHistoryBack = false;
  if (!backHref && document.referrer) {
    try {
      const previous = new URL(document.referrer);
      if (previous.origin === location.origin && listPaths.has(previous.pathname)) {
        backHref = `${previous.pathname}${previous.search}${previous.hash}`;
        useHistoryBack = true;
      }
    } catch (_error) {
      backHref = "";
    }
  }
  if (link && backHref) {
    link.href = backHref;
    link.hidden = false;
    if (useHistoryBack) {
      link.addEventListener("click", (event) => {
        if (history.length <= 1) return;
        event.preventDefault();
        history.back();
      });
    }
  }

  if (!siblings || !prev || !next || !trail?.items?.length) {
    if (siblings) siblings.hidden = true;
    return;
  }
  const index = trail.items.findIndex((item) => item.store === store && String(item.id) === String(id));
  if (index < 0) {
    siblings.hidden = true;
    return;
  }
  siblings.hidden = false;
  if (position) position.textContent = `${index + 1} / ${trail.items.length}`;

  if (index > 0) {
    const item = trail.items[index - 1];
    prev.href = productUrl({ store: item.store, product_id: item.id });
    prev.hidden = false;
    prev.setAttribute("aria-label", item.name ? `Anterior: ${item.name}` : "Producto anterior");
  } else {
    prev.hidden = true;
  }
  if (index < trail.items.length - 1) {
    const item = trail.items[index + 1];
    next.href = productUrl({ store: item.store, product_id: item.id });
    next.hidden = false;
    next.setAttribute("aria-label", item.name ? `Siguiente: ${item.name}` : "Producto siguiente");
  } else {
    next.hidden = true;
  }
}

function thumbUrl(item) {
  return `/api/thumb?store=${encodeURIComponent(item.store || "")}&id=${encodeURIComponent(item.product_id || "")}`;
}

function productUrl(item) {
  return `/producto?store=${encodeURIComponent(item.store || "")}&id=${encodeURIComponent(item.product_id || "")}`;
}

function compareUrl(item) {
  return `/comparar?store=${encodeURIComponent(item.store || "")}&id=${encodeURIComponent(item.product_id || "")}`;
}

async function mountCompareAccess() {
  const link = $("compare-link");
  if (!link) return;
  link.hidden = true;
  const user = typeof ensureUser === "function" ? await ensureUser() : window.retailUser;
  link.hidden = !user;
}

function offerUrl(item) {
  if (item?.url) return item.url;
  const id = item?.product_id;
  if (!id) return "";
  if (item.store === "lider") return `https://www.lider.cl/ip/${encodeURIComponent(id)}`;
  if (item.store === "falabella") return `https://www.falabella.com/falabella-cl/product/${encodeURIComponent(id)}`;
  if (item.store === "sodimac") return `https://www.sodimac.cl/sodimac-cl/articulo/${encodeURIComponent(id)}`;
  if (item.store === "tottus") return `https://www.tottus.cl/tottus-cl/product/${encodeURIComponent(id)}`;
  return "";
}

function storeOutLink(item, label) {
  const href = offerUrl(item);
  if (!href) return "";
  return `<a class="store-out" href="${attr(href)}" target="_blank" rel="noreferrer">${label}</a>`;
}

function storeNameLink(item) {
  const label = storeLogo(item.display_store || item.store, item.store_title || item.store);
  if (!item.url) return label;
  return `<a class="store-offer" href="${attr(item.url)}" target="_blank" rel="noreferrer">${label}</a>`;
}

function payments(item) {
  const rows = [
    ["Normal", item.price_normal],
    ["Todo medio", item.price_all_payment ?? item.price_internet],
    [`Con tarjeta ${item.payment_card_name || cardLabel(item.store)}`, item.price_card ?? item.price_cmr],
  ].filter(([, value]) => value != null);
  if (rows.length < 2) return "";
  const discount = discountOf(item);
  const tiers = rows
    .map(([label, value]) => {
      const current = value === item.price ? " current" : "";
      return `<li class="${current.trim()}"><span>${label}</span><b>${money(value)}</b></li>`;
    })
    .join("");
  return `
    <ul class="tiers">${tiers}</ul>
    ${discount >= 1 ? `<p class="muted">${discount}% bajo el precio normal</p>` : ""}`;
}

const CONDITION_LABELS = {
  new: "Nuevo", refurbished: "Reacondicionado", open_box: "Caja abierta",
  display: "Exhibición", used: "Usado", unknown: "Condición no informada",
};

function commercialDetails(item) {
  const condition = CONDITION_LABELS[item.condition || "unknown"] || "Condición no informada";
  const shipping = item.shipping_cost === 0
    ? "Despacho gratis"
    : item.shipping_cost != null
      ? `Despacho visible: ${money(item.shipping_cost)}`
      : item.shipping_free_threshold
        ? `Despacho gratis sobre ${money(item.shipping_free_threshold)}`
        : "Despacho por confirmar";
  const total = item.shipping_cost != null && item.price != null
    ? ` · Total estimado: ${money(Number(item.price) + Number(item.shipping_cost))}`
    : "";
  const pickup = item.pickup_available ? " · Retiro en tienda disponible" : "";
  const stock = item.low_stock ? '<span class="badge fake">Pocas unidades</span>' : "";
  const financing = [
    item.installment_count ? `${item.installment_count} cuotas` : "",
    item.financial_cae != null ? `CAE ${Number(item.financial_cae).toLocaleString("es-CL")}%` : "",
    item.installment_total ? `costo total ${money(item.installment_total)}` : "",
  ].filter(Boolean).join(" · ");
  const financingWarning = item.installment_total && item.price && Number(item.installment_total) > Number(item.price)
    ? ' <span class="badge fake">El crédito aumenta el costo</span>'
    : "";
  return `<p class="muted">${attr(condition)} · ${shipping}${total}${pickup} ${stock}</p>
    ${financing ? `<p class="muted">Financiamiento: ${attr(financing)}${financingWarning}</p>` : ""}`;
}

const TIMING_LABELS = {
  comprar: "Conviene comprar",
  esperar: "Conviene esperar",
  indeciso: "Da lo mismo cuándo",
  sin_datos: "Todavía no se puede decir",
};

/** ¿Comprar hoy o esperar? Mientras no haya historial lo dice, no lo inventa. */
function timing(data) {
  if (!data) return "";
  const detalle = data.ready && data.typical_drop_percent
    ? `<span class="muted">${data.drops} ${data.drops === 1 ? "baja vista" : "bajas vistas"} en ${data.days_tracked} días</span>`
    : "";
  return `
    <div class="timing ${data.advice}">
      <strong>${TIMING_LABELS[data.advice] || ""}</strong>
      <span>${data.reason || ""}</span>
      ${detalle}
    </div>`;
}

function renderCard(data) {
  const item = data.product;
  const stats = item.stats || {};
  const quantity = stockQuantity(item.stock);
  const availability = availabilityLabel(item.availability, item.stock);
  const image = thumbMarkup(
    "thumb thumb-lg",
    item.has_thumb ? thumbUrl(item) : "",
    { store: item.store, id: item.product_id }
  );
  const score = Number(item.rating);
  const reviews = Number(item.reviews);
  const evaluation = Number.isFinite(score) && score > 0
    ? `<p class="customer-rating" aria-label="Evaluación de clientes: ${score.toFixed(1)} de 5">★ ${score.toFixed(1)} de 5${Number.isFinite(reviews) && reviews > 0 ? ` · ${reviews.toLocaleString("es-CL")} evaluaciones` : ""}</p>`
    : "";
  const cheaper = data.cheapest && data.cheapest.store !== item.store ? data.cheapest : null;
  const cheapest = cheaper
    ? `<p class="cheapest">${
        cheaper.url
          ? `<a class="store-offer" href="${attr(cheaper.url)}" target="_blank" rel="noreferrer">Más barato en ${storeLogo(cheaper.display_store || cheaper.store, cheaper.store_title || cheaper.store)} · ${money(cheaper.price)}</a>`
          : `Más barato en ${storeLogo(cheaper.display_store || cheaper.store, cheaper.store_title || cheaper.store)} · ${money(cheaper.price)}`
      }</p>`
    : "";
  $("card").innerHTML = `
    <div class="product-head">
      ${image}
      <div>
        <h2>${item.name}</h2>
        <p class="muted">${storeLogo(item.display_store || item.store, item.store_title || item.store)}${item.brand ? ` · ${item.brand}` : ""} · ${item.sku_id || item.product_id}</p>
        ${soldBy(item)}
        ${evaluation}
        <p class="price big">${money(item.price)}</p>
        ${(item.stock != null || item.availability) ? `<p class="availability">Disponibilidad: ${attr(availability)}${quantity != null ? ` · ${quantity.toLocaleString("es-CL")} unidades` : ""}</p>` : ''}
        ${commercialDetails(item)}
        ${payments(item)}
        <p class="verdict ${stats.level || "unknown"}">${stats.verdict || ""}</p>
        ${timing(item.timing)}
        ${cheapest}
        <div class="product-cta">${storeOutLink(item, "Ver oferta")} <a id="compare-link" class="btn" href="${attr(compareUrl(item))}" data-auth hidden>Comparar</a></div>
      </div>
    </div>`;
  mountPriceAlert(item);
  mountCompareAccess();
}

let fullOfferHistory = [];
let fullNormalHistory = [];
let windowDays = 90;
let chartMode = "separate";

try {
  chartMode = localStorage.getItem("retail-price-chart-mode") === "combined" ? "combined" : "separate";
} catch (_error) {
  chartMode = "separate";
}

// No reusar SANTIAGO: prices.js ya lo declara (coords) y un segundo const tumba este script.
const SANTIAGO_TZ = "America/Santiago";

/** Día calendario en Chile (YYYY-MM-DD), no el día UTC del timestamp. */
function santiagoDay(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: SANTIAGO_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function addCalendarDays(day, count) {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, date + count)).toISOString().slice(0, 10);
}

/**
 * Un punto por día hasta hoy, arrastrando el último precio.
 * Antes hacía falta más de una medición; una línea plana también se dibuja.
 */
function chartSeries(history, days, now = new Date()) {
  const today = santiagoDay(now);
  const parsed = (history || [])
    .map((item) => {
      const price = item?.price;
      const day = item?.scraped_at ? santiagoDay(item.scraped_at) : item?.day || null;
      if (price == null || !day) return null;
      return { price, day, at: item.scraped_at || "" };
    })
    .filter(Boolean)
    .sort((left, right) => left.day.localeCompare(right.day) || String(left.at).localeCompare(String(right.at)));
  if (!parsed.length || !today) return [];

  const lastByDay = new Map();
  for (const point of parsed) lastByDay.set(point.day, point.price);
  const first = parsed[0].day;
  const windowStart = days ? addCalendarDays(today, -(days - 1)) : first;
  let price = null;
  for (const point of parsed) {
    if (point.day < windowStart) price = point.price;
  }
  const start = first > windowStart ? first : windowStart;
  if (start > today) return [];

  const series = [];
  for (let day = start; day <= today; day = addCalendarDays(day, 1)) {
    if (lastByDay.has(day)) price = lastByDay.get(day);
    if (price == null) continue;
    series.push({ price, day, scraped_at: `${day}T16:00:00Z` });
  }
  return series;
}

function average(values) {
  return Math.round(values.reduce((total, value) => total + value, 0) / values.length);
}

const CHART_MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

/** Etiqueta corta en español a partir del día calendario de Chile (YYYY-MM-DD). */
function chartDateLabel(day, withYear) {
  const [year, month, date] = String(day).split("-");
  const name = CHART_MONTHS[Number(month) - 1] || month;
  const label = `${Number(date)} ${name}`;
  return withYear ? `${label} ${String(year).slice(2)}` : label;
}

/* --- Comparison modal and logic --- */
function compareTemplate() {
  return `
  <div id="compare-modal" class="modal" role="dialog" aria-modal="true" aria-labelledby="compare-title" hidden>
    <div class="modal-content">
      <button id="compare-close" class="modal-close" type="button" aria-label="Cerrar comparador">×</button>
      <h3 id="compare-title">Comparar productos</h3>
      <p class="muted compare-help">Mostramos productos parecidos al de esta ficha. También puedes buscar otro por nombre, marca o modelo.</p>
      <form id="compare-search-form" class="compare-search-form">
        <input id="compare-search" type="search" placeholder="Nombre, marca o modelo" aria-label="Buscar producto para comparar" autocomplete="off" />
        <button id="compare-search-btn" class="btn" type="submit">Buscar</button>
      </form>
      <p id="compare-status" class="muted" role="status"></p>
      <div id="compare-results" class="compare-results"></div>
      <h4>Seleccionados</h4>
      <ul id="compare-selected" class="compare-selected"></ul>
      <div id="compare-table" class="compare-table-wrap"></div>
    </div>
  </div>`;
}

function closeCompareModal() {
  const modal = $("compare-modal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
  compareTrigger?.focus();
}

function ensureCompareModal() {
  if ($("compare-modal")) return;
  const wrap = document.createElement("div");
  wrap.innerHTML = compareTemplate();
  document.body.appendChild(wrap.firstElementChild);
  $("compare-close").addEventListener("click", closeCompareModal);
  $("compare-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    doCompareSearch();
  });
  $("compare-modal").addEventListener("click", (event) => {
    if (event.target === $("compare-modal")) closeCompareModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeCompareModal();
  });
}

let compareSelected = []; // array of {store, product_id, name}
let compareSuggestions = [];
let compareTrigger = null;

function renderCompareSuggestions(items, title = "Productos similares") {
  const currentKey = `${currentProduct?.store || ""}:${currentProduct?.product_id || ""}`;
  const unique = new Map();
  for (const item of items || []) {
    const key = `${item.store || ""}:${item.product_id || ""}`;
    if (!item.product_id || key === currentKey || unique.has(key)) continue;
    unique.set(key, item);
  }
  compareSuggestions = [...unique.values()].slice(0, 12);
  const container = $("compare-results");
  $("compare-status").textContent = compareSuggestions.length
    ? `${title}: ${compareSuggestions.length}`
    : "No encontramos productos similares. Prueba con otro nombre o modelo.";
  container.innerHTML = compareSuggestions.map((item) => {
    const selected = compareSelected.some((row) => row.store === item.store && row.product_id === item.product_id);
    const image = thumbMarkup("thumb thumb-sm", item.has_thumb ? thumbUrl(item) : "", {
      store: item.store,
      id: item.product_id,
    });
    return `<div class="compare-hit">
      <div class="compare-hit-main">${image}<div><b>${attr(item.name || "Producto")}</b><span>${storeLogo(item.display_store || item.store, item.store_title || item.store)}${item.price != null ? ` · ${money(item.price)}` : ""}</span></div></div>
      <button type="button" class="btn small" data-store="${attr(item.store)}" data-id="${attr(item.product_id)}" data-name="${attr(item.name)}" ${selected ? "disabled" : ""}>${selected ? "Agregado" : "Agregar"}</button>
    </div>`;
  }).join("");
  for (const btn of container.querySelectorAll("button[data-id]:not([disabled])")) {
    btn.addEventListener("click", (event) => {
      const button = event.currentTarget;
      addCompareItem({ store: button.dataset.store, product_id: button.dataset.id, name: button.dataset.name });
    });
  }
}

async function loadSimilarProducts() {
  if (!currentProduct?.store || !currentProduct?.product_id) return;
  $("compare-status").textContent = "Buscando productos similares…";
  $("compare-results").innerHTML = `<div class="compare-loading"><span class="spinner" aria-hidden="true"></span> Buscando alternativas…</div>`;
  try {
    const params = new URLSearchParams({ store: currentProduct.store, id: currentProduct.product_id });
    const response = await fetch(`/api/product/ficha?${params}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(response.statusText);
    renderCompareSuggestions(data.related || []);
  } catch (_error) {
    renderCompareSuggestions([]);
  }
}

async function doCompareSearch() {
  const q = $("compare-search").value.trim();
  if (!q) return;
  $("compare-status").textContent = `Buscando “${q}”…`;
  $("compare-results").innerHTML = `<div class="compare-loading"><span class="spinner" aria-hidden="true"></span> Buscando…</div>`;
  try {
    const params = new URLSearchParams({ q, page: "1", size: "12", sort: "price" });
    const response = await fetch(`/api/catalog?${params}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(response.statusText);
    renderCompareSuggestions(data.items || [], "Resultados");
  } catch (_error) {
    $("compare-status").textContent = "No se pudo completar la búsqueda. Inténtalo nuevamente.";
    $("compare-results").innerHTML = "";
  }
}

function addCompareItem(item) {
  if (compareSelected.find(x => x.store === item.store && x.product_id === item.product_id)) return;
  if (compareSelected.length >= 4) return flash("Máximo 4 productos a la vez");
  compareSelected.push(item);
  renderSelected();
  renderCompareSuggestions(compareSuggestions);
  fetchAndRenderComparison();
}

function removeCompareItem(store, id) {
  compareSelected = compareSelected.filter(x => !(x.store === store && x.product_id === id));
  renderSelected();
  renderCompareSuggestions(compareSuggestions);
  fetchAndRenderComparison();
}

function renderSelected() {
  const ul = $("compare-selected");
  ul.innerHTML = compareSelected.map(it => `<li data-store="${attr(it.store)}" data-id="${attr(it.product_id)}">${attr(it.name)} <button class="btn small remove" data-store="${attr(it.store)}" data-id="${attr(it.product_id)}">x</button></li>`).join("");
  for (const btn of ul.querySelectorAll("button.remove")) {
    btn.addEventListener("click", (ev) => {
      removeCompareItem(ev.currentTarget.dataset.store, ev.currentTarget.dataset.id);
    });
  }
}

async function fetchAndRenderComparison() {
  const table = $("compare-table");
  if (!compareSelected.length) { table.innerHTML = ""; return; }
  // Fetch ficha for each selected
  const cards = [];
  for (const it of compareSelected) {
    try {
      const res = await fetch(`/api/product?store=${encodeURIComponent(it.store)}&id=${encodeURIComponent(it.product_id)}`);
      if (!res.ok) continue;
      const data = await res.json();
      // get ficha fields
      const ficha = await (await fetch(`/api/product/ficha?store=${encodeURIComponent(it.store)}&id=${encodeURIComponent(it.product_id)}`)).json().catch(()=>({}));
      cards.push({ product: data.product, ficha });
    } catch (e) {
      // ignore
    }
  }
  // Build union of spec keys
  const specs = new Set();
  cards.forEach(c => {
    const s = c.product.specifications || {}; if (typeof s === 'string') return; for (const k of Object.keys(s)) specs.add(k);
    const s2 = c.ficha?.specifications || {}; for (const k of Object.keys(s2)) specs.add(k);
  });
  const specKeys = Array.from(specs);
  const cols = cards.map(c => `<th>${attr(c.product.name || '')}<br>${storeLogo(c.product.display_store || c.product.store, c.product.store_title || c.product.store)}</th>`).join("");
  let html = `<table class="compare-table"><thead><tr><th>Característica</th>${cols}</tr></thead><tbody>`;
  for (const key of specKeys) {
    const cells = cards.map(c => {
      const s = c.product.specifications || {};
      const s2 = c.ficha?.specifications || {};
      const v = (s && s[key]) || (s2 && s2[key]) || '';
      return `<td>${attr(String(v || ''))}</td>`;
    }).join("");
    html += `<tr><td>${attr(key)}</td>${cells}</tr>`;
  }
  html += `</tbody></table>`;
  table.innerHTML = html;
}

// Hook the compare button once DOM updated
function mountCompareButton() {
  ensureCompareModal();
  const btn = $("compare-open");
  if (!btn || btn.dataset.compareMounted === "1") return;
  btn.dataset.compareMounted = "1";
  btn.addEventListener("click", async () => {
    compareTrigger = btn;
    compareSelected = currentProduct ? [{
      store: currentProduct.store,
      product_id: currentProduct.product_id,
      name: currentProduct.name,
    }] : [];
    renderSelected();
    $("compare-modal").hidden = false;
    document.body.classList.add("modal-open");
    $("compare-search").value = currentProduct?.name || "";
    $("compare-search").focus();
    fetchAndRenderComparison();
    await loadSimilarProducts();
  });
}


/** El eje siempre representa cada día; el contenedor permite desplazarse si no caben. */
function chartTickIndexes(count) {
  return Array.from({ length: count }, (_, index) => index);
}

function chartWidthForDays(count, baseWidth) {
  return Math.max(baseWidth, 56 + Math.max(count - 1, 0) * 72);
}

/** Padding horizontal del plot. Extra a la derecha para que «30 sep» no se corte al borde. */
function chartSidePads(basePad) {
  return { left: basePad, right: basePad + 24 };
}

function chartAxisAnchor(index, count) {
  if (index === 0) return "start";
  if (index === count - 1) return "end";
  return "middle";
}

function showLatestChartDay(container) {
  requestAnimationFrame(() => {
    container.scrollLeft = container.scrollWidth;
  });
}

function renderPriceChart(containerId, noteId, sourceHistory, label, sharedDomain = null) {
  const history = chartSeries(sourceHistory, windowDays);
  const prices = history.map((item) => item.price).filter((value) => value != null);
  // Vacío solo con un día calendario (o ninguno). El precio puede no haber cambiado.
  if (prices.length < 2) {
    $(containerId).innerHTML = "<p class='muted chart-empty'>Se necesita más de un día registrado para dibujar la curva.</p>";
    $(noteId).textContent = label === "Precio normal"
      ? "Empezamos a guardar este valor por separado; el gráfico aparecerá al acumular más días."
      : "Todavía hay pocos registros de precio.";
    return;
  }
  const width = chartWidthForDays(history.length, 720);
  const height = 200;
  const pad = 28;
  const { left: padLeft, right: padRight } = chartSidePads(pad);
  const dateY = height + 16;
  const viewHeight = height + 28;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const scaleMin = sharedDomain?.min ?? min;
  const scaleMax = sharedDomain?.max ?? max;
  const mean = average(prices);
  const toX = (index) => padLeft + (index / (prices.length - 1)) * (width - padLeft - padRight);
  const toY = (price) => (scaleMax === scaleMin ? height / 2 : height - pad - ((price - scaleMin) / (scaleMax - scaleMin)) * (height - pad * 2));
  const points = prices
    .map((price, index) => `${toX(index).toFixed(1)},${toY(price).toFixed(1)}`)
    .join(" ");
  const dots = prices.map((price, index) => `
      <circle class="chart-point" cx="${toX(index).toFixed(1)}" cy="${toY(price).toFixed(1)}" r="3.5">
        <title>${chartDateLabel(history[index].day, true)}: ${money(price)}</title>
      </circle>`).join("");
  const spanYears = history[0].day.slice(0, 4) !== history[history.length - 1].day.slice(0, 4);
  const dates = chartTickIndexes(history.length)
    .map((index) => {
      const anchor = chartAxisAnchor(index, history.length);
      return `<text x="${toX(index).toFixed(1)}" y="${dateY}" class="axis" text-anchor="${anchor}">${chartDateLabel(history[index].day, spanYears)}</text>`;
    })
    .join("");
  const from = chartDateLabel(history[0].day, spanYears);
  const to = chartDateLabel(history[history.length - 1].day, spanYears);
  const container = $(containerId);
  container.innerHTML = `
    <svg class="chart" style="--chart-min-width: ${width}px" viewBox="0 0 ${width} ${viewHeight}" role="img" aria-label="${attr(label)}, día a día, ${from} a ${to}">
      <line class="guide avg" x1="${padLeft}" x2="${width - padRight}" y1="${toY(mean).toFixed(1)}" y2="${toY(mean).toFixed(1)}"/>
      <line class="guide low" x1="${padLeft}" x2="${width - padRight}" y1="${toY(min).toFixed(1)}" y2="${toY(min).toFixed(1)}"/>
      <polyline fill="none" stroke="currentColor" stroke-width="2" points="${points}"/>
      ${dots}
      <text x="${padLeft}" y="16" class="axis">escala ${money(scaleMax)}</text>
      <text x="${padLeft}" y="${height - 6}" class="axis">escala ${money(scaleMin)}</text>
      <text x="${width - padRight}" y="${(toY(mean) - 6).toFixed(1)}" class="axis" text-anchor="end">promedio ${money(mean)}</text>
      ${dates}
    </svg>`;
  showLatestChartDay(container);
  $(noteId).textContent =
    `${prices.length} días · mínimo ${money(min)} · promedio ${money(mean)} · máximo ${money(max)}`;
}

function seriesSummary(label, history) {
  const prices = history.map((item) => item.price).filter((value) => value != null);
  if (!prices.length) return `${label}: sin datos`;
  return `${label}: mín. ${money(Math.min(...prices))} · prom. ${money(average(prices))} · máx. ${money(Math.max(...prices))}`;
}

function alignOfferNormalSeries(days, offer, normal) {
  const offerBy = Object.fromEntries(offer.map((item) => [item.day, item.price]));
  const normalBy = Object.fromEntries(normal.map((item) => [item.day, item.price]));
  let lastNormal = null;
  for (const item of fullNormalHistory) {
    if (item.price == null) continue;
    if (!days.length || item.day <= days[0]) lastNormal = item.price;
  }
  return days.map((day) => {
    if (normalBy[day] != null) lastNormal = normalBy[day];
    return {
      day,
      offer: offerBy[day] ?? null,
      normal: normalBy[day] ?? lastNormal,
    };
  });
}

function discountBandMarkup(aligned, toX, toY) {
  const bands = [];
  let current = [];
  const flush = () => {
    if (current.length) bands.push(current);
    current = [];
  };
  for (const point of aligned) {
    if (point.offer != null && point.normal != null && point.offer < point.normal) {
      current.push(point);
    } else {
      flush();
    }
  }
  flush();

  return bands.map((band) => {
    if (band.length === 1) {
      const point = band[0];
      const x = toX(point.day);
      const half = 9;
      const yNormal = toY(point.normal);
      const yOffer = toY(point.offer);
      return `<path class="chart-discount-band" d="M ${(x - half).toFixed(1)},${yNormal.toFixed(1)} L ${(x + half).toFixed(1)},${yNormal.toFixed(1)} L ${(x + half).toFixed(1)},${yOffer.toFixed(1)} L ${(x - half).toFixed(1)},${yOffer.toFixed(1)} Z"/>`;
    }
    const top = band.map((point) => `${toX(point.day).toFixed(1)},${toY(point.normal).toFixed(1)}`).join(" ");
    const bottom = [...band].reverse().map((point) => `${toX(point.day).toFixed(1)},${toY(point.offer).toFixed(1)}`).join(" ");
    return `<polygon class="chart-discount-band" points="${top} ${bottom}"/>`;
  }).join("");
}

function offerLineMarkup(aligned, toX, toY) {
  const points = aligned.filter((point) => point.offer != null);
  if (points.length < 2) return "";

  const isDiscounted = (point) => point.normal != null && point.offer < point.normal;
  const segments = [];
  let segment = [{ ...points[0], discounted: isDiscounted(points[0]) }];

  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    const discounted = isDiscounted(point);
    const previous = segment[segment.length - 1];
    if (discounted === previous.discounted) {
      segment.push({ ...point, discounted });
      continue;
    }
    segments.push(segment);
    segment = [{ ...previous, discounted }, { ...point, discounted }];
  }
  segments.push(segment);

  const lines = segments.map((part) => {
    const coords = part
      .map((point) => `${toX(point.day).toFixed(1)},${toY(point.offer).toFixed(1)}`)
      .join(" ");
    const className = part[0].discounted ? "offer discounted" : "offer";
    return `<polyline class="chart-series ${className}" fill="none" stroke-width="3.25" points="${coords}"/>`;
  }).join("");

  const dots = points.map((point) => {
    const discounted = isDiscounted(point);
    const className = discounted ? "offer discounted" : "offer";
    const tip = discounted
      ? `${chartDateLabel(point.day, true)}: oferta ${money(point.offer)} (normal ${money(point.normal)})`
      : `${chartDateLabel(point.day, true)}: ${money(point.offer)}`;
    return `
      <circle class="chart-series chart-point ${className}" cx="${toX(point.day).toFixed(1)}" cy="${toY(point.offer).toFixed(1)}" r="${discounted ? 5 : 4}">
        <title>${tip}</title>
      </circle>`;
  }).join("");

  return `${lines}${dots}`;
}

function renderCombinedPriceChart() {
  const offer = chartSeries(fullOfferHistory, windowDays);
  const normal = chartSeries(fullNormalHistory, windowDays);
  const drawable = [offer, normal].filter((series) => series.length >= 2);
  const allPrices = drawable.flatMap((series) => series.map((item) => item.price).filter((value) => value != null));
  if (!allPrices.length) {
    $("chart-combined").innerHTML = "<p class='muted chart-empty'>Se necesita más de un día registrado para unir los gráficos.</p>";
    $("chart-combined-note").textContent = "El gráfico aparecerá cuando exista historial suficiente.";
    return;
  }

  const days = [...new Set(drawable.flatMap((series) => series.map((item) => item.day)))].sort();
  const aligned = alignOfferNormalSeries(days, offer, normal);
  const width = chartWidthForDays(days.length, 1120);
  const height = 260;
  const pad = 36;
  const { left: padLeft, right: padRight } = chartSidePads(pad);
  const dateY = height + 18;
  const viewHeight = height + 32;
  const min = Math.min(...allPrices);
  const max = Math.max(...allPrices);
  const toX = (day) => {
    const index = days.indexOf(day);
    return padLeft + (index / Math.max(days.length - 1, 1)) * (width - padLeft - padRight);
  };
  const toY = (price) => max === min
    ? height / 2
    : height - pad - ((price - min) / (max - min)) * (height - pad * 2);
  const normalLine = () => {
    const refs = aligned.filter((point) => point.normal != null);
    if (!refs.length) return "";
    const points = refs.map((point) => `${toX(point.day).toFixed(1)},${toY(point.normal).toFixed(1)}`).join(" ");
    const line = refs.length >= 2
      ? `<polyline class="chart-series normal" fill="none" stroke-width="2.75" points="${points}"/>`
      : "";
    const seen = new Set(normal.map((item) => item.day));
    const dots = refs
      .filter((point) => seen.has(point.day))
      .map((point) => `
      <circle class="chart-series chart-point normal" cx="${toX(point.day).toFixed(1)}" cy="${toY(point.normal).toFixed(1)}" r="3.5">
        <title>${chartDateLabel(point.day, true)}: ${money(point.normal)}</title>
      </circle>`).join("");
    return `${line}${dots}`;
  };
  const discountDays = aligned.filter((point) => point.offer != null && point.normal != null && point.offer < point.normal).length;
  const spanYears = days[0].slice(0, 4) !== days[days.length - 1].slice(0, 4);
  const dates = chartTickIndexes(days.length).map((index) => {
    const anchor = chartAxisAnchor(index, days.length);
    return `<text x="${toX(days[index]).toFixed(1)}" y="${dateY}" class="axis" text-anchor="${anchor}">${chartDateLabel(days[index], spanYears)}</text>`;
  }).join("");
  const container = $("chart-combined");
  container.innerHTML = `
    <svg class="chart combined-chart" style="--chart-min-width: ${width}px" viewBox="0 0 ${width} ${viewHeight}" role="img" aria-label="Precio de oferta y precio normal, día a día">
      <line class="guide avg" x1="${padLeft}" x2="${width - padRight}" y1="${toY(max).toFixed(1)}" y2="${toY(max).toFixed(1)}"/>
      <line class="guide avg" x1="${padLeft}" x2="${width - padRight}" y1="${toY(min).toFixed(1)}" y2="${toY(min).toFixed(1)}"/>
      ${discountBandMarkup(aligned, toX, toY)}
      ${offerLineMarkup(aligned, toX, toY)}
      ${normalLine()}
      <text x="${padLeft}" y="18" class="axis">máximo ${money(max)}</text>
      <text x="${padLeft}" y="${height - 7}" class="axis">mínimo ${money(min)}</text>
      ${dates}
    </svg>`;
  showLatestChartDay(container);
  const summary = [
    seriesSummary("Oferta", offer),
    seriesSummary("Normal", normal),
  ];
  if (discountDays) summary.push(`Descuento: ${discountDays} día${discountDays === 1 ? "" : "s"}`);
  $("chart-combined-note").textContent = summary.join("  |  ");
}

function applyChartMode() {
  const combined = chartMode === "combined";
  $("chart-separated").hidden = combined;
  $("chart-combined-card").hidden = !combined;
  document.querySelectorAll("[data-chart-mode]").forEach((button) => {
    const active = button.dataset.chartMode === chartMode;
    button.classList.toggle("current", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function renderCharts() {
  const comparablePrices = [fullOfferHistory, fullNormalHistory]
    .flatMap((source) => chartSeries(source, windowDays))
    .map((item) => item.price)
    .filter((value) => value != null);
  const sharedDomain = comparablePrices.length
    ? { min: Math.min(...comparablePrices), max: Math.max(...comparablePrices) }
    : null;
  renderPriceChart("chart-offer", "chart-offer-note", fullOfferHistory, "Precio de oferta", sharedDomain);
  renderPriceChart("chart-normal", "chart-normal-note", fullNormalHistory, "Precio normal", sharedDomain);
  renderCombinedPriceChart();
  applyChartMode();
}

const FORECAST_TRENDS = {
  down: ["Probable baja", "El precio estimado es menor que el actual."],
  up: ["Probable alza", "El precio estimado es mayor que el actual."],
  stable: ["Probablemente estable", "No se estima un cambio importante."],
};

const FORECAST_CONFIDENCE = { low: "Baja", medium: "Media", high: "Alta" };

function forecastDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Fecha no disponible";
  return date.toLocaleString("es-CL", { dateStyle: "medium", timeStyle: "short", timeZone: SANTIAGO_TZ });
}

function patternMarkup(patterns) {
  if (!(patterns || []).length) return "";
  const rows = patterns.map((pattern) => `
    <li>
      <strong>${attr(pattern.label || "Patrón observado")}</strong>
      <span>${attr(pattern.explanation || "")}</span>
      <small>${Number(pattern.samples) || 0} mediciones · ${Math.abs(Number(pattern.difference_percent) || 0).toFixed(1)}% de diferencia observada${pattern.timesfm_consistent ? " · coincide con el pronóstico TimesFM" : ""}</small>
    </li>`).join("");
  return `<div class="forecast-patterns"><h3>Temporadas y patrones observados</h3><ul>${rows}</ul></div>`;
}

function renderForecast(summary, patterns = []) {
  const panel = $("forecast-panel");
  if (!panel) return;
  panel.open = false;
  if (!summary) {
    $("forecast-content").innerHTML = `
      <p class="muted">Todavía no hay un pronóstico para este producto. Se necesitan al menos 30 días de precios válidos.</p>
      ${patternMarkup(patterns)}`;
    return;
  }
  const trend = FORECAST_TRENDS[summary.trend] || FORECAST_TRENDS.stable;
  const rangeNote = summary.range_has_uncertainty
    ? "Rango de incertidumbre calculado por el modelo."
    : "Rango observado entre los valores centrales estimados; el modelo no entregó límites de incertidumbre.";
  $("forecast-content").innerHTML = `
    <div class="forecast-grid">
      <div class="forecast-stat"><span>Tendencia probable</span><strong class="forecast-${attr(summary.trend)}">${attr(trend[0])}</strong><small>${attr(trend[1])}</small></div>
      <div class="forecast-stat"><span>Rango esperado</span><strong>${money(summary.range_low)} – ${money(summary.range_high)}</strong><small>${attr(rangeNote)}</small></div>
      <div class="forecast-stat"><span>Nivel de confianza</span><strong>${attr(FORECAST_CONFIDENCE[summary.confidence] || "Baja")}</strong><small title="${attr(summary.confidence_reason)}">${attr(summary.confidence_reason)}</small></div>
      <div class="forecast-stat"><span>Generado</span><strong>${attr(forecastDate(summary.generated_at))}</strong><small>${summary.horizon_days} días estimados · ${summary.observation_count || 0} días analizados</small></div>
    </div>
    ${patternMarkup(patterns)}`;
}

async function loadForecast(store, id) {
  const panel = $("forecast-panel");
  if (!panel) return;
  // Colapsado siempre; la visibilidad la controla solo data-admin + applySession.
  panel.open = false;
  try {
    const user = await ensureUser();
    const admin = Boolean(user && user.role === "admin");
    if (!admin) {
      panel.hidden = true;
      return;
    }
    // No tocar panel.hidden: applySession ya reveló [data-admin] para admin.
    $("forecast-content").innerHTML = `<p class="muted">Buscando un pronóstico disponible…</p>`;
    const params = new URLSearchParams({ store });
    const response = await fetch(`/api/forecasts/${encodeURIComponent(id)}?${params}`);
    if (response.status === 404) {
      renderForecast(null, []);
      return;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : response.statusText);
    renderForecast(data.summary || null, data.patterns || []);
  } catch (_error) {
    if (panel.hidden) return;
    panel.open = false;
    $("forecast-content").innerHTML = `<p class="muted">El pronóstico no está disponible temporalmente.</p>`;
  }
}

$("windows").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-days]");
  if (!button) return;
  windowDays = Number(button.dataset.days);
  [...$("windows").querySelectorAll("button")].forEach((item) => item.classList.toggle("current", item === button));
  renderCharts();
});

document.querySelector(".chart-mode")?.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-chart-mode]");
  if (!button) return;
  chartMode = button.dataset.chartMode === "combined" ? "combined" : "separate";
  try {
    localStorage.setItem("retail-price-chart-mode", chartMode);
  } catch (_error) {
    // La preferencia solo deja de persistir si el navegador bloquea localStorage.
  }
  applyChartMode();
});

function otherRow(item) {
  const stats = item.stats || {};
  const ficha = `<a class="deal-cta" href="${attr(productUrl(item))}">Ver ficha</a>`;
  const offer = item.url
    ? `<a class="deal-cta offer" href="${attr(item.url)}" target="_blank" rel="noreferrer">Ver oferta</a>`
    : "";
  return `
    <tr class="${item.url ? "click-offer" : ""}" data-offer="${attr(`${item.store || ""}:${item.product_id || ""}`)}" data-price="${item.price ?? ""}" ${item.url ? `data-url="${attr(item.url)}"` : ""}>
      <td>${storeNameLink(item)}${soldBy(item)}</td>
      <td class="price">${money(item.price)}</td>
      <td class="muted">${stats.median ? money(stats.median) : "—"}</td>
      <td class="offer-actions">${ficha}${offer}</td>
    </tr>`;
}

function renderOthers(others) {
  if (!others.length) return;
  $("others-panel").hidden = false;
  $("others").innerHTML = others.map(otherRow).join("");
}

function findOtherRow(item) {
  const key = `${item.store || ""}:${item.product_id || ""}`;
  return [...$("others").querySelectorAll("tr[data-offer]")].find((row) => row.dataset.offer === key);
}

function upsertOtherRow(item) {
  const existing = findOtherRow(item);
  if (existing) {
    const prev = Number(existing.dataset.price);
    if (item.price != null && (Number.isNaN(prev) || item.price < prev)) {
      existing.dataset.price = String(item.price);
      const cell = existing.querySelector(".price");
      if (cell) cell.textContent = money(item.price);
    }
    return;
  }
  $("others-panel").hidden = false;
  $("others").insertAdjacentHTML("beforeend", otherRow(item));
  const rows = [...$("others").querySelectorAll("tr")];
  rows.sort((left, right) => (Number(left.dataset.price) || 1e15) - (Number(right.dataset.price) || 1e15));
  rows.forEach((row) => $("others").appendChild(row));
}

function noticeSeen(store, id, offer) {
  const key = `${store}:${id}:${offer.store}:${offer.price}`;
  let seen = [];
  try {
    seen = JSON.parse(sessionStorage.getItem("ficha-lower-notices") || "[]");
  } catch {
    seen = [];
  }
  if (!Array.isArray(seen) || seen.includes(key)) return true;
  seen.push(key);
  try {
    sessionStorage.setItem("ficha-lower-notices", JSON.stringify(seen.slice(-80)));
  } catch {
    /* modo privado: el aviso de esta vista igual se muestra */
  }
  return false;
}

function showLowerNotice(message) {
  const box = $("price-notice");
  if (!box || !message) return;
  box.hidden = false;
  box.textContent = message;
}

function markCheaper(item) {
  const head = $("card")?.querySelector(".product-head div");
  if (!head || item?.price == null) return;
  const html = item.url
    ? `<a class="store-offer" href="${attr(item.url)}" target="_blank" rel="noreferrer">Más barato en ${storeLogo(item.display_store || item.store, item.store_title || item.store)} · ${money(item.price)}</a>`
    : `Más barato en ${storeLogo(item.display_store || item.store, item.store_title || item.store)} · ${money(item.price)}`;
  let line = head.querySelector(".cheapest");
  if (!line) {
    line = document.createElement("p");
    line.className = "cheapest";
    const cta = head.querySelector(".product-cta");
    if (cta) cta.before(line);
    else head.appendChild(line);
  }
  line.innerHTML = html;
}

function startCrossStoreSweep(store, id, known) {
  if (!window.EventSource) return;
  const shown = new Set((known || []).filter((item) => item.price != null).map((item) => `${item.store}:${item.price}`));
  const status = $("sweep-status");
  if (status) {
    status.hidden = false;
    status.textContent = "Revisando el mismo producto en otras tiendas…";
  }
  const source = new EventSource(`/api/product/sweep?store=${encodeURIComponent(store)}&id=${encodeURIComponent(id)}`);
  source.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    if (data.type === "offer" && data.offer) {
      upsertOtherRow(data.offer);
      const key = `${data.offer.store}:${data.offer.price}`;
      if (data.notice && data.message && !shown.has(key) && !noticeSeen(store, id, data.offer)) {
        shown.add(key);
        showLowerNotice(data.message);
        markCheaper(data.offer);
      }
    }
    if (data.type === "done" || data.type === "error") {
      if (status) status.hidden = true;
      source.close();
    }
  };
  source.onerror = () => {
    if (status) status.hidden = true;
    source.close();
  };
}

const SPEC_PREVIEW = 6;
let fichaCopy = {};

function normalizeSpecifications(raw) {
  if (!raw) return {};
  if (typeof raw === "string") {
    const text = raw.trim();
    if (text.startsWith("[") || text.startsWith("{")) {
      try {
        return normalizeSpecifications(JSON.parse(text));
      } catch (_error) {
        // Continúa con el formato "Nombre: valor | Nombre: valor".
      }
    }
    const rows = {};
    text.split("|").forEach((part) => {
      const separator = part.indexOf(":");
      if (separator < 1) return;
      const label = part.slice(0, separator).trim();
      const value = part.slice(separator + 1).trim();
      if (label && value) rows[label] = value;
    });
    return rows;
  }
  if (Array.isArray(raw)) {
    return raw.reduce((rows, item) => ({ ...rows, ...normalizeSpecifications(item) }), {});
  }
  if (typeof raw !== "object") return {};
  const directLabel = raw.name || raw.label || raw.id;
  if (directLabel && raw.value != null) {
    const value = typeof raw.value === "object" ? Object.values(raw.value).filter(Boolean).join(", ") : String(raw.value).trim();
    const unit = raw.unit ? ` ${String(raw.unit).trim()}` : "";
    return value ? { [directLabel]: `${value}${unit}`.trim() } : {};
  }
  const rows = {};
  Object.entries(raw).forEach(([label, value]) => {
    const nested = normalizeSpecifications(value);
    if (["specs", "specifications", "attributes", "características", "caracteristicas"].includes(label.toLowerCase()) && Object.keys(nested).length) {
      Object.assign(rows, nested);
      return;
    }
    let display = value;
    if (Array.isArray(value)) display = value.map((item) => typeof item === "object" ? (item.value || item.label || item.name || "") : item).filter(Boolean).join(", ");
    else if (value && typeof value === "object") display = value.value || value.label || value.name || "";
    if (display != null && String(display).trim()) rows[label] = String(display).trim();
  });
  return rows;
}

function specRows(item) {
  const rows = Object.entries(normalizeSpecifications(item.specifications)).filter(([, value]) => value);
  const labels = new Set(rows.map(([label]) => label.toLowerCase()));
  if (item.brand && !labels.has("marca")) rows.push(["Marca", item.brand]);
  if (item.seller && !labels.has("vendido por")) rows.push(["Vendido por", item.seller]);
  return rows;
}

function renderFichaCopy(item) {
  fichaCopy = {
    ...fichaCopy,
    ...item,
    specifications: {
      ...normalizeSpecifications(fichaCopy.specifications),
      ...normalizeSpecifications(item.specifications),
    },
  };
  if (item.description) fichaCopy.description = item.description;
  const rows = specRows(fichaCopy);
  const description = (fichaCopy.description || "").trim();
  const panel = $("specs-panel");
  if (!rows.length && !description) {
    if (panel) panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const open = $("specs")?.dataset.open === "1";
  $("specs").innerHTML = rows.length
    ? `<dl class="spec-grid">${rows
        .map(([label, value], index) => {
          const hidden = !open && index >= SPEC_PREVIEW ? " hidden" : "";
          return `<div class="spec-row${hidden}"${hidden ? " hidden" : ""}><dt>${attr(label)}</dt><dd>${attr(value)}</dd></div>`;
        })
        .join("")}</dl>`
    : "";
  const specsToggle = $("specs-toggle");
  if (specsToggle) {
    specsToggle.hidden = rows.length <= SPEC_PREVIEW;
    specsToggle.textContent = open ? "Ver menos características" : "Ver más características";
  }
  const block = $("desc-block");
  if (block) block.hidden = !description;
  if (description) {
    $("desc-title").textContent = fichaCopy.name || "";
    $("desc").textContent = description;
    const long = description.length > 280;
    const collapsed = $("desc").dataset.open !== "1";
    $("desc").classList.toggle("collapsed", long && collapsed);
    const descToggle = $("desc-toggle");
    if (descToggle) {
      descToggle.hidden = !long;
      descToggle.textContent = collapsed ? "Ver más" : "Ver menos";
    }
  }
}

function relatedCard(item) {
  const image = thumbMarkup("thumb", item.has_thumb ? thumbUrl(item) : "", { store: item.store, id: item.product_id });
  const brand = item.brand ? `<p class="related-brand">${attr(item.brand)}</p>` : "";
  return `
    <a class="related-card" href="${productUrl(item)}">
      <span class="related-media">${image}${discountBadge(item)}</span>
      ${brand}
      <strong>${attr(item.name)}</strong>
      <span class="price">${money(item.price)}</span>
      <span class="related-store">${storeLogo(item.display_store || item.store, item.store_title || item.store)}</span>
    </a>`;
}

function renderRelated(items) {
  const panel = $("related-panel");
  if (!panel) return;
  const rows = (items || []).filter((item) => item && item.product_id).slice(0, 12);
  if (!rows.length) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("related").innerHTML = rows.map(relatedCard).join("");
}

let reviewProduct = null;
let reviewRows = [];
let reviewCommentCount = 0;
let reviewsExpanded = false;

function reviewStars(value) {
  const rating = Math.max(0, Math.min(5, Number(value) || 0));
  return `<span class="review-stars" aria-label="${rating} de 5 estrellas">${[1, 2, 3, 4, 5]
    .map((star) => `<span class="${star <= Math.round(rating) ? "filled" : ""}">★</span>`)
    .join("")}</span>`;
}

function reviewDate(value) {
  const date = new Date(value || "");
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("es-CL", { day: "numeric", month: "short", year: "numeric" }).format(date);
}

function setReviewRating(value) {
  const rating = Math.max(0, Math.min(5, Number(value) || 0));
  $("review-rating").value = String(rating);
  document.querySelectorAll("[data-review-rating]").forEach((button) => {
    const selected = Number(button.dataset.reviewRating) <= rating;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-checked", Number(button.dataset.reviewRating) === rating ? "true" : "false");
  });
  $("review-rating-label").textContent = rating ? `${rating} de 5 estrellas` : "Elige de 1 a 5 estrellas";
}

function renderReviewSummary(data) {
  const count = Number(data.count) || 0;
  const average = Number(data.average) || 0;
  $("reviews-summary").innerHTML = count
    ? `<strong>${average.toFixed(1)}</strong>${reviewStars(average)}<span>${count.toLocaleString("es-CL")} ${count === 1 ? "evaluación" : "evaluaciones"}</span>`
    : `<strong>—</strong><span>Sé la primera persona en evaluar</span>`;
}

function renderReviewComposer(data, user) {
  const form = $("review-form");
  const login = $("review-login");
  form.hidden = !user;
  login.hidden = Boolean(user);
  if (!user) {
    login.querySelector("a").href = typeof loginHref === "function" ? loginHref("") : "/entrar";
    return;
  }
  const mine = data.mine || null;
  setReviewRating(mine?.rating || 0);
  $("review-comment").value = mine?.comment || "";
  $("review-counter").textContent = `${$("review-comment").value.length}/600`;
  $("review-submit").textContent = mine ? "Actualizar opinión" : "Publicar opinión";
}

function reviewCard(review) {
  const comment = attr(review.comment || "").replace(/\n/g, "<br>");
  const author = attr(review.author || "Usuario");
  const initial = attr((review.author || "U").trim().charAt(0).toUpperCase() || "U");
  return `<article class="review-card${review.mine ? " mine" : ""}">
    <div class="review-avatar" aria-hidden="true">${initial}</div>
    <div>
      <div class="review-card-head"><strong>${author}</strong>${reviewStars(review.rating)}<time>${attr(reviewDate(review.updated_at || review.created_at))}</time></div>
      <p>${comment}</p>
    </div>
  </article>`;
}

function renderReviewList() {
  $("reviews-list").innerHTML = reviewRows.length
    ? reviewRows.map(reviewCard).join("")
    : `<p class="muted review-empty">Todavía no hay comentarios. Puedes dejar solo una calificación o contar brevemente tu experiencia.</p>`;
  const toggle = $("reviews-toggle");
  if (!reviewsExpanded) {
    toggle.hidden = reviewCommentCount <= 3;
    toggle.textContent = `Ver todos (${reviewCommentCount.toLocaleString("es-CL")})`;
    toggle.dataset.reviewAction = "all";
  } else if (reviewRows.length < reviewCommentCount) {
    toggle.hidden = false;
    toggle.textContent = "Ver más comentarios";
    toggle.dataset.reviewAction = "more";
  } else {
    toggle.hidden = reviewCommentCount <= 3;
    toggle.textContent = "Ver los últimos";
    toggle.dataset.reviewAction = "recent";
  }
}

async function loadProductReviews({ append = false } = {}) {
  if (!reviewProduct) return;
  const limit = reviewsExpanded ? 20 : 3;
  const skip = append ? reviewRows.length : 0;
  const params = new URLSearchParams({
    store: reviewProduct.store,
    id: reviewProduct.product_id,
    limit: String(limit),
    skip: String(skip),
  });
  const [response, user] = await Promise.all([
    fetch(`/api/product-reviews?${params}`),
    typeof ensureUser === "function" ? ensureUser() : Promise.resolve(window.retailUser || null),
  ]);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) return;
  reviewRows = append ? [...reviewRows, ...(data.reviews || [])] : (data.reviews || []);
  reviewCommentCount = Number(data.comment_count) || 0;
  renderReviewSummary(data);
  renderReviewComposer(data, user);
  renderReviewList();
  $("reviews-panel").hidden = false;
}

document.querySelector(".review-stars-input")?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-review-rating]");
  if (button) setReviewRating(button.dataset.reviewRating);
});

$("review-comment")?.addEventListener("input", () => {
  $("review-counter").textContent = `${$("review-comment").value.length}/600`;
});

$("review-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!reviewProduct) return;
  const rating = Number($("review-rating").value) || 0;
  if (!rating) {
    $("review-status").className = "err";
    $("review-status").textContent = "Elige una calificación antes de publicar.";
    return;
  }
  const submit = $("review-submit");
  submit.disabled = true;
  $("review-status").className = "muted";
  $("review-status").textContent = "Guardando…";
  try {
    const response = await fetch("/api/product-reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        store: reviewProduct.store,
        product_id: reviewProduct.product_id,
        rating,
        comment: $("review-comment").value,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) {
      location.href = typeof loginHref === "function" ? loginHref("") : "/entrar";
      return;
    }
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "No pudimos guardar tu opinión.");
    $("review-status").className = "review-success";
    $("review-status").textContent = "¡Gracias! Tu opinión quedó publicada.";
    reviewRows = [];
    reviewsExpanded = false;
    await loadProductReviews();
  } catch (error) {
    $("review-status").className = "err";
    $("review-status").textContent = error.message || "No pudimos guardar tu opinión.";
  } finally {
    submit.disabled = false;
  }
});

$("reviews-toggle")?.addEventListener("click", async (event) => {
  const action = event.currentTarget.dataset.reviewAction;
  if (action === "more") {
    await loadProductReviews({ append: true });
    return;
  }
  reviewsExpanded = action === "all";
  reviewRows = [];
  await loadProductReviews();
});

function loadFichaExtra(store, id) {
  fetch(`/api/product/ficha?store=${encodeURIComponent(store)}&id=${encodeURIComponent(id)}`)
    .then((response) => (response.ok ? response.json() : null))
    .then((extra) => {
      if (!extra) return;
      renderFichaCopy({
        description: extra.description,
        specifications: extra.specifications,
      });
      renderRelated(extra.related || []);
      if (extra.image_available) patchThumb(store, id);
    })
    .catch(() => {});
}

$("specs-toggle")?.addEventListener("click", () => {
  const box = $("specs");
  if (!box) return;
  box.dataset.open = box.dataset.open === "1" ? "0" : "1";
  renderFichaCopy(fichaCopy);
});

$("desc-toggle")?.addEventListener("click", () => {
  const box = $("desc");
  if (!box) return;
  box.dataset.open = box.dataset.open === "1" ? "0" : "1";
  renderFichaCopy(fichaCopy);
});

function priceAlertBox() {
  const cta = document.querySelector("#card .product-cta");
  const host = cta || document.querySelector("#card .product-head div") || $("card");
  if (!host) return null;
  let box = host.querySelector(".price-alert");
  if (!box) {
    box = document.createElement("div");
    box.className = "price-alert";
    host.appendChild(box);
  }
  return box;
}

function paintPriceAlert(box, item, state) {
  const user = state && state.user;
  if (!user) {
    const href = typeof loginHref === "function" ? loginHref("") : "/entrar";
    box.innerHTML = `<p class="muted price-alert-note">Entra para activar una alerta si cambia el precio. <a href="${attr(href)}">Entrar</a></p>`;
    return;
  }
  const active = Boolean(state.active);
  const email = state.email || user.email || "";
  const shown = email ? attr(email) : "";
  const note = active
    ? `Te avisamos a ${shown || "tu correo"} si el precio cambia.`
    : `Te avisamos a tu correo${shown ? ` (${shown})` : ""} si el precio sube o baja.`;
  box.innerHTML = `
    <button type="button" class="secondary${active ? " current" : ""}" data-price-alert="${active ? "off" : "on"}" data-store="${attr(item.store)}" data-id="${attr(item.product_id)}">${active ? "Alerta activa" : "Activar alerta"}</button>
    <p class="muted price-alert-note">${note}</p>`;
}

async function mountPriceAlert(item) {
  if (!item?.store || !item?.product_id) return;
  const box = priceAlertBox();
  if (!box) return;
  const user = typeof ensureUser === "function" ? await ensureUser() : window.retailUser;
  if (!user) {
    paintPriceAlert(box, item, null);
    return;
  }
  const params = new URLSearchParams({ store: item.store, id: item.product_id });
  const response = await fetch(`/api/price-alert?${params}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.logged_in) {
    paintPriceAlert(box, item, null);
    return;
  }
  paintPriceAlert(box, item, { user, active: data.active, email: data.email || user.email });
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-price-alert]");
  if (!button || button.disabled) return;
  const store = button.dataset.store;
  const id = button.dataset.id;
  if (!store || !id) return;
  button.disabled = true;
  const turnOff = button.dataset.priceAlert === "off";
  const params = new URLSearchParams({ store, id });
  try {
    const response = turnOff
      ? await fetch(`/api/price-alert?${params}`, { method: "DELETE" })
      : await fetch("/api/price-alert", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ store, product_id: id }),
        });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      flash(typeof data.detail === "string" ? data.detail : "No se pudo guardar la alerta.");
      button.disabled = false;
      return;
    }
    await mountPriceAlert({ store, product_id: id });
  } catch (error) {
    flash(error.message || "No se pudo guardar la alerta.");
    button.disabled = false;
  }
});

$("others").addEventListener("click", (event) => {
  if (event.target.closest("a")) return;
  const row = event.target.closest("tr[data-url]");
  if (row?.dataset.url) window.open(row.dataset.url, "_blank", "noopener,noreferrer");
});

async function load() {
  const params = new URLSearchParams(location.search);
  const store = params.get("store");
  const id = params.get("id");
  if (!store || !id) {
    flash("Falta la tienda o el código del producto.");
    return;
  }
  const response = await fetch(`/api/product?store=${encodeURIComponent(store)}&id=${encodeURIComponent(id)}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    flash(typeof data.detail === "string" ? data.detail : response.statusText);
    return;
  }
  renderCard(data);
  reviewProduct = { store, product_id: id };
  loadProductReviews().catch(() => {});
  renderFichaCopy(data.product || {});
  fullOfferHistory = data.product.history_offer || data.product.history || [];
  fullNormalHistory = data.product.history_normal || [];
  if (fullOfferHistory.length || fullNormalHistory.length) {
    $("chart-panel").hidden = false;
    renderCharts();
  }
  renderOthers(data.others || []);
  loadForecast(store, id);
  startCrossStoreSweep(store, id, data.others || []);
  loadFichaExtra(store, id);
}

function _ensurePricesScript() {
  if (typeof money !== "undefined" && typeof $ !== "undefined") return Promise.resolve();
  return new Promise((resolve, reject) => {
    try {
      const existing = [...document.getElementsByTagName('script')].find(s => String(s.src || '').includes('/static/prices.js'));
      if (existing) {
        if (typeof money !== 'undefined' && typeof $ !== 'undefined') return resolve();
        existing.addEventListener('load', () => resolve());
        existing.addEventListener('error', () => reject(new Error('No se pudo cargar prices.js')));
        return;
      }
      const s = document.createElement('script');
      s.src = '/static/prices.js?v=21';
      s.async = false;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('No se pudo cargar prices.js'));
      document.head.appendChild(s);
    } catch (e) {
      reject(e);
    }
  });
}

_ensurePricesScript()
  .then(() => {
    mountBackToResults();
    return load();
  })
  .catch((error) => flash(error && error.message ? error.message : 'Error cargando utilidades de la página'));

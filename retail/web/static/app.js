// $, money, attr, discountOf, discountBadge y priceLadder vienen de prices.js

let currentRows = [];
let currentDiscarded = [];
let lastResult = null;
let resultFocus = "matches";
let currentSource = null;
let currentSearchId = "";
let currentQuery = "";
const VIEW_KEY = "retail-search-view";
const PAGE_SIZE_KEY = "retail-page-size";
const PAGE_SIZES = [12, 24, 48, 96, 480];
const DEFAULT_PAGE_SIZE = 12;
const LEGACY_PAGE_SIZES = { 10: 12, 20: 24, 50: 48, 100: 96, 500: 480 };
let currentPage = 1;
let lastPagerTotal = 0;

// Thresholds configurables para ofertas
const OFFER_MIN_PERCENT = 10; // porcentaje mínimo para considerar oferta
const PERCENT_VS_MEDIAN_THRESHOLD = -5; // percent_vs_median <= this

const thumbUrl = (row) =>
  `/api/thumb?store=${encodeURIComponent(row.store || "")}&id=${encodeURIComponent(row.product_id || "")}`;

const productUrl = (row) =>
  `/producto?store=${encodeURIComponent(row.store || "")}&id=${encodeURIComponent(row.product_id || "")}`;

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || response.statusText);
  }
  return response.json();
}

function categoryIconKind(value) {
  const key = String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  if (/calzado|zapato/.test(key)) return "calzado";
  if (/deporte|aire libre/.test(key)) return "sports";
  if (/accesorios moda|moda/.test(key)) return "fashion";
  if (/electrodomest/.test(key)) return "appliance";
  if (/tecnolog/.test(key)) return "tech";
  if (/audio|musica/.test(key)) return "audio";
  if (/belleza|higiene|salud|farmacia/.test(key)) return "beauty";
  if (/alimento|bebida|gastronom/.test(key)) return "food";
  if (/supermercado/.test(key)) return "market";
  if (/ferreter|herramient|maquina|construccion/.test(key)) return "tools";
  if (/cocina|bano/.test(key)) return "kitchen";
  if (/juguete/.test(key)) return "toys";
  if (/automotriz|autos?/.test(key)) return "auto";
  if (/jardin|terraza/.test(key)) return "garden";
  if (/decohogar|hogar/.test(key)) return "home";
  if (/bebes?|infantil/.test(key)) return "baby";
  if (/libreria|libros?/.test(key)) return "books";
  if (/mascota/.test(key)) return "pets";
  return "other";
}

function renderCategoryShortcuts(categories) {
  const rail = $("category-rail");
  const section = $("catalog-categories");
  if (!rail || !section || !Array.isArray(categories) || !categories.length) return;
  rail.innerHTML = categories.map((item) => {
    const title = item.label || item.value || "Otros";
    const value = item.value || title;
    const count = Number(item.count) || 0;
    return `
      <a class="category-shortcut ${categoryIconKind(title)}" href="/catalogo?category=${encodeURIComponent(value)}" role="listitem" aria-label="Ver todos los productos de ${attr(title)}">
        <span class="category-icon" aria-hidden="true"></span>
        <span>${attr(title)}</span>
        <small data-category-count data-admin hidden>${count.toLocaleString("es-CL")}</small>
      </a>`;
  }).join("");
  section.removeAttribute("aria-busy");
  section.hidden = Boolean(currentQuery);
  if (typeof ensureUser === "function") {
    ensureUser().then((user) => {
      const isAdmin = Boolean(user && user.role === "admin");
      rail.querySelectorAll("[data-category-count]").forEach((element) => {
        element.hidden = !isAdmin;
      });
    });
  }
}

/** True after /api/stores has populated #stores (even if the admin filters UI is hidden). */
let storesReady = false;
/** Query waiting for fillStores when the user searches before checkboxes exist. */
let pendingSearchQuery = null;

function selectedStores() {
  return [...document.querySelectorAll("#stores input[type=checkbox]:checked")].map((item) => item.value);
}

function allStoresSelected() {
  const boxes = storeChecks();
  return boxes.length > 0 && boxes.every((item) => item.checked);
}

function updateExploreFilterBadge() {
  const active = [
    sourceValue() !== "db",
    Number($("max").value) !== 20,
    $("price-band").checked,
    $("fresh").checked,
    storeChecks().length > 0 && !allStoresSelected(),
  ].filter(Boolean).length;
  const badge = $("explore-filter-count");
  if (!badge) return;
  badge.textContent = active
    ? `${active} ${active === 1 ? "filtro activo" : "filtros activos"}`
    : "Sin filtros";
}

function productIndexLabel(info) {
  if (!info || !info.applied) return "";
  const groups = (info.group_titles || []).join(", ");
  const n = Number(info.store_count) || 0;
  const tiendas = n === 1 ? "1 tienda" : `${n} tiendas`;
    const extra = info.background ? ". Revisando más tiendas en segundo plano" : "";
    return `Buscando ${info.name} en ${groups} (${tiendas})${extra}`;
}

function sourceValue() {
  if (quickSearchEnabled()) return "db";
  return document.querySelector("input[name=source]:checked")?.value || "both";
}

function quickSearchEnabled() {
  return Boolean(document.querySelector('.desktop-quick-search input[name="quick"]')?.checked);
}

function hideCategoryShortcuts() {
  const section = $("catalog-categories");
  if (section) section.hidden = true;
}

function searchIsAdmin() {
  return Boolean(window.retailUser && window.retailUser.role === "admin");
}

function storeChecks() {
  return [...document.querySelectorAll("#stores input[type=checkbox]")];
}

function groupedStores(stores) {
  const groups = [];
  const byId = new Map();
  for (const store of stores) {
    const id = store.group || "otros";
    if (!byId.has(id)) {
      const group = {
        id,
        title: store.group_title || "Otros",
        order: Number(store.group_order ?? 99),
        stores: [],
      };
      byId.set(id, group);
      groups.push(group);
    }
    byId.get(id).stores.push(store);
  }
  groups.sort((left, right) => left.order - right.order || left.title.localeCompare(right.title, "es"));
  return groups;
}

function syncGroupToggles() {
  document.querySelectorAll("#store-groups input[data-group]").forEach((toggle) => {
    const boxes = storeChecks().filter((item) => item.dataset.group === toggle.dataset.group);
    const on = boxes.filter((item) => item.checked).length;
    toggle.checked = boxes.length > 0 && on === boxes.length;
    toggle.indeterminate = on > 0 && on < boxes.length;
  });
}

function setStoresChecked(checked, group) {
  storeChecks()
    .filter((item) => !group || item.dataset.group === group)
    .forEach((item) => {
      item.checked = checked;
    });
  syncGroupToggles();
  updateExploreFilterBadge();
}

function fillStores(stores) {
  const groups = groupedStores(stores);
  $("store-groups").innerHTML = groups
    .map(
      (group) => `
      <label class="check store-group-toggle">
        <input type="checkbox" data-group="${attr(group.id)}" checked>
        ${attr(group.title)}
      </label>`
    )
    .join("");
  $("stores").innerHTML = groups
    .map(
      (group) => `
      <section class="store-section" data-group="${attr(group.id)}">
        <h3>${attr(group.title)}</h3>
        <div class="store-grid">
          ${group.stores
            .map(
              (store) => `
          <label>
            <input type="checkbox" value="${attr(store.id)}" data-group="${attr(group.id)}" checked>
            ${storeLogo(store.id, store.title)}
          </label>`
            )
            .join("")}
        </div>
      </section>`
    )
    .join("");
  syncGroupToggles();
  updateExploreFilterBadge();
  storesReady = true;
  const queued = pendingSearchQuery;
  pendingSearchQuery = null;
  if (queued) runSearch(queued);
}

function fillHistory(items) {
  if (!items.length) {
    $("history").innerHTML = "<li>Aún no hay búsquedas guardadas.</li>";
    return;
  }
  $("history").innerHTML = items
    .map(
      (item) => `
      <li>
        <button type="button" data-query="${item.query}">
          <strong>${item.query}</strong><br>
          <small>${item.offer_count || 0} ofertas · ${item.comparable_count || 0} comparables</small>
        </button>
      </li>`
    )
    .join("");
}

function isRealOffer(row) {
  const stats = row.price_stats || {};
  if (row.precio_normal || row.fake_discount || stats.fake_discount) return false;
  const price = Number(row.price);
  if (!Number.isFinite(price) || price <= 0) return false;

  // Un mínimo histórico por sí solo no prueba una oferta: un precio plano
  // también es "el mínimo". Exigimos una referencia mayor y ahorro medible.
  const publishedBefore = Number(row.price_normal ?? row.price_internet);
  if (publishedBefore > price && discountOf(row) >= OFFER_MIN_PERCENT) return true;

  const median = Number(stats.median);
  const percentVsMedian = Number(stats.percent_vs_median);
  if (
    median > price &&
    Number.isFinite(percentVsMedian) &&
    percentVsMedian <= PERCENT_VS_MEDIAN_THRESHOLD
  ) return true;

  const previous = Number(row.previous_price ?? stats.previous);
  const percentVsPrevious = previous > price ? ((previous - price) * 100) / previous : 0;
  return percentVsPrevious >= Math.abs(PERCENT_VS_MEDIAN_THRESHOLD);
}

function hasProductDiscount(row) {
  const price = Number(row.price);
  return Number.isFinite(price) && price > 0
    && !row.fake_discount && !(row.price_stats || {}).fake_discount
    && discountOf(row) > 0;
}

function matchesFilters(row, { text, minPrice, maxPrice, minDiscount, comparable, lowest, offers, discounted }) {
  if ((comparable || resultFocus === "comparable") && !row.comparable) return false;
  if (lowest && !row.is_lowest) return false;
  if (minPrice && (row.price ?? 0) < minPrice) return false;
  if (maxPrice && (row.price ?? Infinity) > maxPrice) return false;
  if (minDiscount && discountOf(row) < minDiscount) return false;
  if (offers && !isRealOffer(row)) return false;
  if (discounted && !hasProductDiscount(row)) return false;
  if (!text) return true;
  const blob = [row.name, row.brand, row.store_title, row.store, row.sku_id, row.product_id, row.compare_code]
    .join(" ")
    .toLowerCase();
  return blob.includes(text);
}

function activeFilters() {
  return {
    text: $("table-filter").value.trim().toLowerCase(),
    minPrice: Number($("min-price").value) || 0,
    maxPrice: Number($("max-price").value) || 0,
    minDiscount: Number($("min-discount").value) || 0,
    comparable: $("only-comparable").checked,
    lowest: $("only-lowest").checked,
    offers: $("only-offers").checked,
    discounted: $("only-discounts").checked,
  };
}

function updateResultFilterBadge() {
  const filters = activeFilters();
  const active = [
    Boolean(filters.text),
    filters.minPrice > 0, filters.maxPrice > 0, filters.minDiscount > 0,
    filters.comparable, filters.lowest, filters.offers, filters.discounted,
    $("sort-by").value !== "price",
  ].filter(Boolean).length;
  const badge = $("search-filter-count");
  badge.textContent = active
    ? `${active} ${active === 1 ? "filtro activo" : "filtros activos"}`
    : "Sin filtros";
  syncOnlyOffersChip();
}

function setResultFiltersVisible(visible) {
  const bar = $("result-filter-bar");
  if (bar) {
    bar.hidden = !visible;
    return;
  }
  $("toolbar").hidden = !visible;
}

function syncOnlyOffersChip() {
  const chip = $("only-offers-chip");
  const box = $("only-offers");
  if (!chip || !box) return;
  chip.setAttribute("aria-pressed", box.checked ? "true" : "false");
}

/** Limpia filtros de resultados al iniciar una búsqueda nueva (no toca vista ni page-size). */
function resetResultFilters() {
  $("table-filter").value = "";
  $("min-price").value = "";
  $("max-price").value = "";
  $("min-discount").value = "0";
  $("only-comparable").checked = false;
  $("only-lowest").checked = false;
  $("only-offers").checked = false;
  $("only-discounts").checked = false;
  syncOnlyOffersChip();
  currentPage = 1;
}

function visibleRows() {
  const filters = activeFilters();
  return currentRows.filter((row) => matchesFilters(row, filters));
}

function sortGroups(groups) {
  const mode = $("sort-by").value;
  const best = (group) => group.offers.find((item) => item.price === group.lowest_price) || group.offers[0] || {};
  const copy = [...groups];
  if (mode === "discount") {
    copy.sort((left, right) => discountOf(best(right)) - discountOf(best(left)));
  } else if (mode === "saving") {
    const gap = (group) => (best(group).price_stats || {}).percent_vs_median ?? 0;
    copy.sort((left, right) => gap(left) - gap(right));
  } else if (mode === "name") {
    copy.sort((left, right) => (left.name || "").localeCompare(right.name || "", "es"));
  } else {
    copy.sort((left, right) => (left.lowest_price ?? 1e12) - (right.lowest_price ?? 1e12));
  }
  return copy;
}

function groupKey(row) {
  return row.compare_code || (row.name || "").toLowerCase();
}

function groupedByProduct(rows) {
  const buckets = new Map();
  for (const row of rows) {
    const key = groupKey(row);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(row);
  }
  const groups = [...buckets.values()].map((offers) => {
    offers.sort((left, right) => (left.price ?? 1e12) - (right.price ?? 1e12) || (left.store || "").localeCompare(right.store || "", "es"));
    const priced = offers.filter((item) => item.price != null);
    const lowest = priced.length ? Math.min(...priced.map((item) => item.price)) : null;
    const cheapest = offers.filter((item) => item.price === lowest);
    return {
      name: offers[0].name,
      brand: offers.find((item) => item.brand)?.brand,
      thumb: offers.find((item) => item.has_thumb),
      code: offers[0].compare_code,
      url: offers.find((item) => item.url)?.url,
      lowest_price: lowest,
      lowest_stores: [...new Set(cheapest.map((item) => item.store_title || item.store))],
      stores: new Set(offers.map((item) => item.store)).size,
      comparable: offers[0].comparable || new Set(offers.map((item) => item.store)).size > 1,
      kind: offers[0].compare_kind,
      offers,
    };
  });
  groups.sort((left, right) => (left.lowest_price ?? 1e12) - (right.lowest_price ?? 1e12) || left.name.localeCompare(right.name, "es"));
  return groups;
}

function sparkline(points) {
  const prices = (points || []).map((item) => item.price).filter((value) => value != null);
  if (prices.length < 2) return "";
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const width = 72;
  const height = 18;
  const coords = prices
    .map((price, index) => {
      const x = (index / (prices.length - 1)) * width;
      const y = max === min ? height / 2 : height - ((price - min) / (max - min)) * height;
      return `${x},${y}`;
    })
    .join(" ");
  return `<svg class="spark" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" aria-hidden="true"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${coords}"/></svg>`;
}

function ratingLabel(row) {
  if (!row.rating) return "";
  const reviews = row.reviews ? ` (${row.reviews})` : "";
  return `<div class="muted">★ ${Number(row.rating).toFixed(1)}${reviews}</div>`;
}

function badges(row, isLowest) {
  const stats = row.price_stats || {};
  const items = [];
  if (isLowest) items.push('<span class="badge">menor</span>');
  if (stats.is_lowest_ever) items.push('<span class="badge best">mínimo histórico</span>');
  const off = discountBadge(row);
  if (off) items.push(off);
  if (stats.fake_discount) items.push('<span class="badge fake">descuento inflado</span>');
  return items.join(" ");
}

/** Tallas o anchos del mismo aviso: se muestra el más barato y el rango. */
function variantLabel(row) {
  const variants = row.variants;
  if (!variants || variants.count < 2) return "";
  const range = variants.max_price && variants.max_price !== variants.min_price
    ? ` hasta ${money(variants.max_price)}`
    : "";
  return `<div class="muted">${variants.count} variantes${range}</div>`;
}

function ageLabel(row) {
  const days = (row.price_stats || {}).changed_days_ago;
  if (days == null) return "";
  if (days === 0) return `<div class="muted">precio de hoy</div>`;
  return `<div class="muted">hace ${days} ${days === 1 ? "día" : "días"}</div>`;
}

function deltaLabel(row) {
  if (row.previous_price == null || row.price == null || row.price_delta == null) return "";
  if (row.price_delta === 0) return `<div class="muted">igual que la última vez</div>`;
  const cls = row.price_delta < 0 ? "down" : "up";
  const arrow = row.price_delta < 0 ? "bajó" : "subió";
  return `<div class="${cls}">${arrow} ${money(Math.abs(row.price_delta))}</div>`;
}

function formatDay(iso) {
  if (!iso) return "antes";
  const day = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(day.getTime())) return "antes";
  return day.toLocaleDateString("es-CL", { day: "numeric", month: "short" });
}

function cheaperHints(row) {
  const items = [];
  const other = row.cheaper_elsewhere;
  if (other && other.price) {
    const who = other.store_title || other.store;
    items.push(
      `<li class="elsewhere">Más barato en ${attr(who)}: ${money(other.price)} <span class="badge off">−${Math.round(other.gap_percent || 0)}%</span></li>`
    );
  }
  const past = row.cheaper_before;
  if (past && past.price) {
    items.push(
      `<li class="past">Estuvo a ${money(past.price)} el ${attr(formatDay(past.on))} <span class="badge off">−${Math.round(past.gap_percent || 0)}%</span></li>`
    );
  }
  return items.length ? `<ul class="deal-hints">${items.join("")}</ul>` : "";
}

function searchDetailLabel(items) {
  const progress = items || [];
  if (!progress.length) return "Tiendas";
  const ok = progress.filter((item) => item.state === "ok").length;
  const failed = progress.filter((item) => item.state === "error").length;
  const cached = progress.filter((item) => item.cached).length;
  const running = progress.filter((item) => item.state === "running").length;
  const parts = [];
  if (progress.length) parts.push(`${progress.length} tiendas`);
  if (running) parts.push(`${running} buscando`);
  if (ok) parts.push(`${ok} ok`);
  if (cached) parts.push(`${cached} de hoy`);
  if (failed) parts.push(`${failed} con error`);
  return parts.join(" · ");
}

function progressStats(items) {
  const progress = items || [];
  const done = progress.filter((item) => ["ok", "error", "skip"].includes(item.state)).length;
  return { total: progress.length, done };
}

let searchMessageTimer = null;
let searchMessageStep = 0;
let searchConversation = { quick: true, progress: [], offers: 0 };

function searchOfferLabel(count) {
  return count === 1 ? "1 oferta" : `${count} ofertas`;
}

function renderSearchConversation() {
  if (!document.documentElement.classList.contains("is-searching")) return;
  const text = $("search-loading-text");
  const detail = $("search-loading-detail");
  const { total, done } = progressStats(searchConversation.progress);
  const offers = searchConversation.offers;
  const quick = searchConversation.quick;
  const phases = quick
    ? [
        "Buscando en productos",
        "Revisando las coincidencias…",
        "Ordenando los mejores resultados…",
      ]
    : [
        "Buscando...",
        "Comparando los precios disponibles…",
        "Revisando si aparece una mejor opción…",
      ];

  if (text) {
    if (offers > 0) {
      const found = `¡Encontramos ${searchOfferLabel(offers)}!`;
      const messages = [
        found,
        `${found} Seguimos buscando…`,
        `${found} Estamos comparando precios…`,
      ];
      text.textContent = messages[searchMessageStep % messages.length];
    } else if (!quick && total > 0 && done > 0) {
      text.textContent = done >= total
        ? "Terminando la comparación…"
        : `Ya revisamos ${done} de ${total} tiendas…`;
    } else {
      text.textContent = phases[searchMessageStep % phases.length];
    }
  }
  if (detail) {
    if (quick) {
      detail.textContent = offers
        ? "Preparando las opciones que coinciden con tu búsqueda."
        : "Esta búsqueda revisa la información disponible al instante.";
    } else if (offers) {
      detail.textContent = done < total
        ? "Aún queda por revisar; podríamos encontrar un precio mejor."
        : "Estamos preparando los resultados para mostrártelos.";
    } else {
      detail.textContent = done
        ? "Todavía no encontramos coincidencias, pero seguimos buscando."
        : "Esto puede tomar un momento. Puedes detener la búsqueda cuando quieras.";
    }
  }
}

function startSearchConversation(quick) {
  if (searchMessageTimer) clearInterval(searchMessageTimer);
  searchMessageStep = 0;
  searchConversation = { quick, progress: [], offers: 0 };
  searchMessageTimer = setInterval(() => {
    searchMessageStep += 1;
    renderSearchConversation();
  }, 4200);
}

function stopSearchConversation() {
  if (searchMessageTimer) clearInterval(searchMessageTimer);
  searchMessageTimer = null;
}

function updateSearchBar(items) {
  const { total, done } = progressStats(items);
  const pct = total ? Math.round((done * 100) / total) : 0;
  const count = $("search-loading-count");
  const fill = $("search-bar-fill");
  const bar = $("search-bar");
  searchConversation.progress = items || [];
  searchConversation.offers = Math.max(
    searchConversation.offers,
    Number(lastResult?.offer_count || 0),
    currentRows.length,
  );
  if (count) count.textContent = searchConversation.quick
    ? searchConversation.offers
      ? `${searchOfferLabel(searchConversation.offers)} en la base`
      : "Revisando la base de productos"
    : total
      ? `${done} de ${total} revisadas`
      : "Preparando";
  if (fill) fill.style.width = `${pct}%`;
  if (bar) bar.setAttribute("aria-valuenow", String(pct));
  renderSearchConversation();
}

function renderSkeleton() {
  hidePager();
  $("results").innerHTML = `<div class="deal-grid search-skeleton" aria-hidden="true">${Array.from(
    { length: 8 },
    () => `
      <article class="panel skeleton-card">
        <span class="skeleton-photo"></span>
        <span class="skeleton-line"></span>
        <span class="skeleton-line short"></span>
      </article>`
  ).join("")}</div>`;
}

function setLiveStop(on) {
  const button = $("search-stop-live");
  if (button) button.hidden = !on;
  document.documentElement.classList.toggle("is-search-live", Boolean(on));
}

function hasActiveStores(result) {
  const progress = (result && result.progress) || [];
  return progress.some((item) => item.state === "running" || item.state === "pending");
}

function setSearching(on, { live = false } = {}) {
  document.documentElement.classList.toggle("is-searching", on);
  const button = document.querySelector("#search-form .search-hero button");
  if (button) {
    button.disabled = on;
    button.innerHTML = on
      ? `<span class="spinner" aria-hidden="true"></span>Buscando…`
      : "Buscar";
  }
  if (typeof setQuickSearchBusy === "function") {
    setQuickSearchBusy(on || live, live ? "Actualizando…" : "Buscando…");
  }
  const overlay = $("search-overlay");
  if (overlay) overlay.hidden = !on;
  document.querySelectorAll("body > :not(#search-overlay)").forEach((el) => {
    if (el.tagName === "SCRIPT") return;
    el.toggleAttribute("inert", on);
  });
  if (on) renderSearchConversation();
  else stopSearchConversation();
  const form = $("search-form");
  if (form) form.setAttribute("aria-busy", on || live ? "true" : "false");
  if (on) {
    $("search-detail").hidden = !searchIsAdmin();
    $("search-detail").open = searchIsAdmin();
    setLiveStop(false);
    return;
  }
  setLiveStop(live);
  if (!on && lastResult) renderSummary();
  if (live) {
    $("search-detail").hidden = !searchIsAdmin();
    $("search-detail").open = searchIsAdmin();
    return;
  }
  $("search-detail").open = false;
}

function renderProgress(items) {
  const progress = items || [];
  $("store-progress").innerHTML = progress
    .map((item) => {
      const extra = item.state === "ok"
        ? ` · ${item.count || 0}`
        : item.state === "error"
          ? " · error"
          : item.state === "running"
            ? ""
            : item.cached
              ? " · hoy"
              : "";
      return `<span class="chip ${item.state || "pending"}">${storeLogo(item.id, item.title || item.id)}${extra}</span>`;
    })
    .join("");
  $("search-detail").hidden = !searchIsAdmin() || !progress.length;
  $("search-detail-label").textContent = searchDetailLabel(progress);
  updateSearchBar(progress);
}

function offerRow(row, group, index) {
  const lowest = row.price === group.lowest_price && group.offers.length > 1;
  const stats = row.price_stats || {};
  const verdict = stats.verdict && stats.level && stats.level !== "unknown"
    ? `<div class="verdict ${stats.level}">${stats.verdict}</div>`
    : "";
  const ficha = row.product_id ? `<a href="${productUrl(row)}">Ver ficha</a>` : "";
  const origin = `<span class="badge ghost">${row.from_scrape ? "tienda" : "base"}</span>`;
  // show comparison hint when cheaper elsewhere
  const cheaper = row.cheaper_elsewhere;
  const cheaperHint = cheaper && cheaper.price
    ? `<div class="muted">Más barato en ${attr(cheaper.store || cheaper.store_title || '')}: ${money(cheaper.price)} (${Math.round(((cheaper.price - (row.price||0))/((cheaper.price)||1))*100)}%)</div>`
    : "";
  return `
    <div class="offer-row ${lowest ? "lowest" : ""}">
      <div class="offer-store">
        ${row.url ? `<a class="store-offer" href="${attr(row.url)}" target="_blank" rel="noreferrer">${storeCell(row)}</a>` : storeCell(row)}
        ${soldBy(row)}
        ${ratingLabel(row)}
        ${variantLabel(row)}
      </div>
      <div class="offer-price">
        <div class="price">${money(row.price)} ${badges(row, lowest && index === 0)}</div>
        ${priceLadder(row)}
        ${deltaLabel(row)}
        ${cheaperHints(row)}
        ${verdict}
      </div>
      <div>${sparkline(row.price_history)}${ageLabel(row)}</div>
      <div class="offer-side">${origin}${row.url ? `<a href="${attr(row.url)}" target="_blank" rel="noreferrer">Ver oferta</a>` : ""}${ficha}</div>
    </div>`;
}

function currentView() {
  return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid";
}

function normalizePageSize(raw) {
  const value = Number(raw);
  if (PAGE_SIZES.includes(value)) return value;
  if (LEGACY_PAGE_SIZES[value]) return LEGACY_PAGE_SIZES[value];
  return DEFAULT_PAGE_SIZE;
}

function pageSize() {
  const select = $("page-size");
  return normalizePageSize((select && select.value) || localStorage.getItem(PAGE_SIZE_KEY) || DEFAULT_PAGE_SIZE);
}

function initPageSize() {
  const select = $("page-size");
  if (!select) return;
  const size = normalizePageSize(localStorage.getItem(PAGE_SIZE_KEY) || DEFAULT_PAGE_SIZE);
  select.value = String(size);
  localStorage.setItem(PAGE_SIZE_KEY, String(size));
}

function hidePager() {
  const nav = $("pager");
  lastPagerTotal = 0;
  if (!nav) return;
  nav.hidden = true;
  nav.innerHTML = "";
}

function slicePage(items) {
  const size = pageSize();
  const total = items.length;
  const pages = Math.max(1, Math.ceil(total / size) || 1);
  if (currentPage > pages) currentPage = pages;
  if (currentPage < 1) currentPage = 1;
  const start = (currentPage - 1) * size;
  return { items: items.slice(start, start + size), total, pages, size, start };
}

function pagerPages(current, pages) {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  const set = new Set([1, pages, current - 1, current, current + 1]);
  const list = [...set].filter((page) => page >= 1 && page <= pages).sort((left, right) => left - right);
  const out = [];
  for (const page of list) {
    if (out.length && page - out[out.length - 1] > 1) out.push("…");
    out.push(page);
  }
  return out;
}

function renderPager(total) {
  const nav = $("pager");
  if (!nav) return;
  lastPagerTotal = total;
  const size = pageSize();
  if (!total || total <= size) {
    hidePager();
    return;
  }
  const pages = Math.ceil(total / size);
  const start = (currentPage - 1) * size + 1;
  const end = Math.min(total, currentPage * size);
  const numbers = pagerPages(currentPage, pages)
    .map((page) =>
      page === "…"
        ? `<span class="pager-range">…</span>`
        : `<button type="button" class="${page === currentPage ? "current" : "secondary"}" data-page="${page}" aria-current="${page === currentPage ? "page" : "false"}">${page}</button>`
    )
    .join("");
  nav.hidden = false;
  nav.innerHTML = `
    <span class="pager-range">${start}–${end} de ${total}</span>
    <button type="button" class="secondary" data-page="prev" ${currentPage <= 1 ? "disabled" : ""}>Anterior</button>
    ${numbers}
    <button type="button" class="secondary" data-page="next" ${currentPage >= pages ? "disabled" : ""}>Siguiente</button>`;
}

function setView(view) {
  localStorage.setItem(VIEW_KEY, view);
  $("view-list").classList.toggle("current", view === "list");
  $("view-grid").classList.toggle("current", view === "grid");
  if (currentRows.length || currentDiscarded.length) renderTable();
}

function offerSaving(row) {
  const stats = row.price_stats || {};
  if (row.precio_normal || row.fake_discount || stats.fake_discount) return null;
  const price = Number(row.price);
  if (!Number.isFinite(price) || price <= 0) return null;
  const before = Number(row.price_normal ?? row.price_internet);
  if (before > price) return before - price;
  const median = Number(stats.median);
  if (median > price && Number(stats.percent_vs_median) <= PERCENT_VS_MEDIAN_THRESHOLD) return median - price;
  const previous = Number(row.previous_price ?? stats.previous);
  if (previous > price && ((previous - price) * 100) / previous >= Math.abs(PERCENT_VS_MEDIAN_THRESHOLD)) {
    return previous - price;
  }
  return null;
}

function sortRows(rows) {
  const mode = $("sort-by").value;
  const copy = [...rows];
  if (mode === "discount") {
    copy.sort((left, right) => discountOf(right) - discountOf(left));
  } else if (mode === "saving") {
    const gap = (row) => (row.price_stats || {}).percent_vs_median ?? 0;
    copy.sort((left, right) => gap(left) - gap(right));
  } else if (mode === "name") {
    copy.sort((left, right) => (left.name || "").localeCompare(right.name || "", "es"));
  } else {
    copy.sort((left, right) => (left.price ?? 1e12) - (right.price ?? 1e12) || (left.name || "").localeCompare(right.name || "", "es"));
  }
  return copy;
}

function searchDealCard(row) {
  const stats = row.price_stats || {};
  const saving = offerSaving(row);
  const ficha = row.product_id ? productUrl(row) : "";
  const image = thumbMarkup("deal-img", row.has_thumb && row.product_id ? thumbUrl(row) : "", {
    store: row.store,
    id: row.product_id,
  });
  const linkedImage = ficha
    ? `<a class="product-image-link" href="${attr(ficha)}" aria-label="Ver ficha de ${attr(row.name)}">${image}</a>`
    : image;
  const title = ficha
    ? `<a class="deal-name" href="${attr(ficha)}">${attr(row.name)}</a>`
    : row.url
      ? `<a class="deal-name" href="${attr(row.url)}" target="_blank" rel="noreferrer">${attr(row.name)}</a>`
      : `<span class="deal-name">${attr(row.name)}</span>`;
  const cta = ficha
    ? `<a class="deal-cta" href="${attr(ficha)}">Ver ficha</a>`
    : "";
  const offer = row.url
    ? `<a class="deal-cta" href="${attr(row.url)}" target="_blank" rel="noreferrer">Ver oferta</a>`
    : "";
  const hints = cheaperHints(row);
  let reason = "";
  if (!hints) {
    if (stats.level && stats.level !== "unknown" && stats.verdict) reason = stats.verdict;
    else if (row.is_lowest && row.comparable) reason = "Menor precio entre tiendas";
    else if (stats.is_lowest_ever) reason = "Es el precio más bajo que le hemos visto.";
  }
  return `
    <article class="panel deal">
      ${linkedImage}
      <div class="deal-body">
        ${title}
        <p class="muted">${attr(row.brand || row.category || "")}</p>
        <div class="deal-meta">
          ${storeLogo(row.display_store || row.store, row.store_title || row.store)}
          <div class="deal-ctas">${cta}${offer}</div>
        </div>
        <div class="deal-prices">
          <div>
            <span class="deal-label">Precio</span>
            <span class="price">${money(row.price)}</span>
          </div>
          <div>
            <span class="deal-label">Ahorro</span>
            <span class="deal-saving">${saving ? money(saving) : "—"}${discountBadge(row)}</span>
          </div>
        </div>
        ${hints}
        ${reason ? `<p class="deal-reason"><span>Motivo</span> ${attr(reason)}</p>` : ""}
        <button type="button" class="watch-btn" data-code="${attr(row.compare_code)}" data-name="${attr(row.name)}" data-price="${row.price ?? ""}" data-store="${attr(row.store)}" data-id="${attr(row.product_id)}">Seguir</button>
      </div>
    </article>`;
}

function resultCard(group) {
  const first = group.offers[0] || {};
  const title = first.product_id
    ? `<a href="${productUrl(first)}">${attr(group.name)}</a>`
    : group.url
      ? `<a href="${attr(group.url)}" target="_blank" rel="noreferrer">${attr(group.name)}</a>`
      : attr(group.name);
  const stores = `${group.stores} ${group.stores === 1 ? "tienda" : "tiendas"}`;
  const best = group.lowest_price != null
    ? `menor en ${group.lowest_stores.join(", ")}`
    : "sin precio";
  const thumbRow = group.thumb || first;
  const image = thumbMarkup("result-img", group.thumb ? thumbUrl(group.thumb) : "", {
    store: thumbRow.store,
    id: thumbRow.product_id,
  });
  const ficha = group.offers.find((item) => item.product_id);
  const imageProduct = thumbRow.product_id ? thumbRow : ficha;
  const linkedImage = imageProduct
    ? `<a class="product-image-link" href="${attr(productUrl(imageProduct))}" aria-label="Ver ficha de ${attr(group.name)}">${image}</a>`
    : image;
  return `
    <article class="result-card">
      <div class="result-hero">
        ${linkedImage}
        <div class="result-info">
          <h3>${title}</h3>
          <p class="result-meta">${group.brand ? `${attr(group.brand)} · ` : ""}${stores}</p>
          <p class="result-price">${money(group.lowest_price)}<span>${best}</span></p>
        </div>
        <div class="result-actions">
          <button type="button" class="watch-btn" data-code="${attr(group.code)}" data-name="${attr(group.name)}" data-price="${group.lowest_price ?? ""}" data-store="${attr((ficha || first).store)}" data-id="${attr((ficha || first).product_id)}">Seguir</button>
          ${ficha ? `<a class="ghost" href="${productUrl(ficha)}">Ficha</a>` : ""}
        </div>
      </div>
      <div class="offer-list">
        ${group.offers.map((row, index) => offerRow(row, group, index)).join("")}
      </div>
    </article>`;
}

function renderTable() {
  if (resultFocus === "discarded") {
    renderDiscarded();
    return;
  }
  if (!currentRows.length) {
    setResultFiltersVisible(true);
    updateResultFilterBadge();
    hidePager();
    $("results").innerHTML = "<p class='panel empty-results'>No hay productos que coincidan con la búsqueda.</p>";
    return;
  }
  setResultFiltersVisible(true);
  updateResultFilterBadge();
  if (currentView() === "grid") {
    const paged = slicePage(sortRows(visibleRows()));
    saveProductTrail(paged.items);
    $("results").innerHTML = paged.items.length
      ? `<div class="deal-grid">${paged.items.map(searchDealCard).join("")}</div>`
      : "<p class='panel empty-results'>Ningún resultado con esos filtros.</p>";
    renderPager(paged.total);
    focusFirstResult();
    return;
  }
  const paged = slicePage(sortGroups(groupedByProduct(visibleRows())));
  saveProductTrail(paged.items.map((group) => {
    const first = (group.offers || []).find((item) => item.product_id) || (group.offers || [])[0] || {};
    return { store: first.store, product_id: first.product_id, name: group.name };
  }));
  $("results").innerHTML = paged.items.length
    ? `<div class="result-list">${paged.items.map(resultCard).join("")}</div>`
    : "<p class='panel empty-results'>Ningún resultado con esos filtros.</p>";
  renderPager(paged.total);
  focusFirstResult();
}

async function followProduct(button) {
  const user = await ensureUser();
  if (!user) {
    location.href = loginHref("inscribir");
    return;
  }
  button.disabled = true;
  button.textContent = "Activando…";
  const exactProduct = button.dataset.store && button.dataset.id;
  const response = await fetch(exactProduct ? "/api/price-alert" : "/api/watches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(exactProduct
      ? {
          store: button.dataset.store,
          product_id: button.dataset.id,
          name: button.dataset.name,
        }
      : {
          query: currentQuery,
          compare_code: button.dataset.code,
          name: button.dataset.name,
          current_price: button.dataset.price || null,
          watch_changes: true,
        }),
  });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) {
    location.href = loginHref("inscribir");
    return;
  }
  if (!response.ok) {
    const detail = payload.detail;
    button.textContent = typeof detail === "string" ? detail : "No se pudo seguir";
    button.disabled = false;
    return;
  }
  button.textContent = "Siguiendo cambios ✓";
}

function cacheLabel(cache) {
  if (!cache) return "";
  if (cache.hit === "result") return "caché de hoy";
  if (cache.hit === "exact") return "caché de hoy";
  if (cache.hit === "similar") return "caché similar";
  return "caché parcial";
}

function liveSearchLabel(payload) {
  if (!document.documentElement.classList.contains("is-search-live") || payload.cancelled) return "";
  const text = payload.live_label || ((payload.offer_count || 0) >= 10 ? "Mostrando 10+ · sigue buscando…" : "");
  return text ? `<span class="stat">${attr(text)}</span>` : "";
}

function statButton(focus, count, label) {
  const pressed = resultFocus === focus;
  return `<button type="button" class="stat${pressed ? " accent" : ""}" data-result-focus="${focus}" data-admin-result hidden aria-pressed="${pressed ? "true" : "false"}"><b>${count || 0}</b> ${label}</button>`;
}

function revealAdminResultStats() {
  if (typeof ensureUser !== "function") return;
  ensureUser().then((user) => {
    const admin = Boolean(user && user.role === "admin");
    document.querySelectorAll("[data-admin-result]").forEach((element) => {
      element.hidden = !admin;
    });
  }).catch(() => {});
}

function renderSummary() {
  const payload = lastResult || {};
  $("summary").dataset.technicalSummary = "";
  $("summary").hidden = false;
  $("summary").className = "summary stats";
  const routed = productIndexLabel(payload.product_index);
  $("summary").innerHTML = `
    ${payload.requested_query && payload.requested_query !== payload.query ? `<span class="stat">Resultados para «${attr(payload.query)}»</span>` : ""}
    ${routed ? `<span class="stat accent route">${routed}</span>` : ""}
    ${statButton("matches", payload.offer_count, "coinciden")}
    ${statButton("comparable", payload.comparable_count, "en varias tiendas")}
    ${statButton("discarded", payload.discarded_count, "descartados")}
    ${payload.saved ? `<span class="stat">guardado</span>` : ""}
    ${payload.cancelled && payload.stopped_label ? `<span class="stat">${attr(payload.stopped_label)}</span>` : ""}
    ${liveSearchLabel(payload)}
    ${payload.cache ? `<span class="stat accent">${cacheLabel(payload.cache)}</span>` : ""}`;
  revealAdminResultStats();
}

function applyResultFocus(next) {
  if (!next) return;
  resultFocus = resultFocus === next && next !== "matches" ? "matches" : next;
  currentPage = 1;
  if (lastResult) renderSummary();
  renderTable();
}

function discardedWhy(row) {
  if (row.reason) return row.reason;
  const missing = (row.missing || []).filter(Boolean);
  if (missing.length) return `no menciona ${missing.join(", ")}`;
  return "";
}

function discardedItem(row) {
  const name = row.url
    ? `<a href="${attr(row.url)}" target="_blank" rel="noreferrer">${attr(row.name || "Sin nombre")}</a>`
    : attr(row.name || "Sin nombre");
  const why = discardedWhy(row);
  return `
    <article class="discarded-item">
      <div class="discarded-main">
        <strong>${name}</strong>
        ${storeLogo(row.display_store || row.store, row.store_title || row.store)}
      </div>
      <div class="price">${money(row.price)}</div>
      ${row.brand ? `<p class="muted">${attr(row.brand)}</p>` : ""}
      ${why ? `<p class="deal-reason"><span>Por qué</span> ${attr(why)}</p>` : ""}
    </article>`;
}

function visibleDiscarded() {
  const text = $("table-filter").value.trim().toLowerCase();
  const discounted = $("only-discounts").checked;
  const minPrice = Number($("min-price").value) || 0;
  const maxPrice = Number($("max-price").value) || 0;
  return currentDiscarded.filter((row) => {
    if (discounted && !hasProductDiscount(row)) return false;
    if (minPrice && (row.price ?? 0) < minPrice) return false;
    if (maxPrice && (row.price ?? Infinity) > maxPrice) return false;
    if (!text) return true;
    const blob = [row.name, row.brand, row.store_title, row.store, row.reason, ...(row.missing || [])]
      .join(" ")
      .toLowerCase();
    return blob.includes(text);
  });
}

function renderDiscarded() {
  const count = (lastResult && lastResult.discarded_count) || 0;
  setResultFiltersVisible(true);
  updateResultFilterBadge();
  if (!currentDiscarded.length) {
    const detail = count
      ? "Este resultado no incluye el detalle de lo descartado. Vuelve a buscar para verlo."
      : "No se descartó ningún producto en esta búsqueda.";
    $("results").innerHTML = `<p class="panel empty-results">${detail}</p>`;
    hidePager();
    return;
  }
  const paged = slicePage(sortRows(visibleDiscarded()));
  const list = paged.items.length
    ? `<div class="discarded-list">${paged.items.map(discardedItem).join("")}</div>`
    : "<p class='panel empty-results'>Ningún descartado con esos filtros.</p>";
  $("results").innerHTML = `
    <div class="discarded-head">
      <p class="muted">Mostrando ${paged.items.length} de ${currentDiscarded.length} productos que la búsqueda dejó fuera.</p>
      <button type="button" class="secondary" data-result-focus="matches">Volver a coinciden</button>
    </div>
    ${list}`;
  renderPager(paged.total);
  focusFirstResult();
}

function focusFirstResult() {
  const first = document.querySelector('#results .deal-grid .panel, #results .result-list > * , #results .discarded-list > *');
  if (!first) return;
  first.setAttribute('tabindex', '-1');
  try {
    first.focus({ preventScroll: true });
  } catch (e) {
    // focus may fail in some contexts; ignore
  }
  try {
    first.scrollIntoView({ block: 'start' });
  } catch (e) {}
  setTimeout(() => first.removeAttribute('tabindex'), 1000);
}

function renderResults(payload) {
  lastResult = payload;
  currentRows = payload.rows || [];
  currentDiscarded = Array.isArray(payload.discarded) ? payload.discarded : [];
  resultFocus = "matches";
  renderProgress(payload.progress || []);
  renderSummary();
  renderTable();
}

function renderExpandedSearchOffer() {
  setResultFiltersVisible(false);
  hidePager();
  $("results").innerHTML = `
    <section class="panel quick-search-empty" role="status" aria-live="polite">
      <span class="quick-search-empty-icon" aria-hidden="true">⌕</span>
      <h2>¿Ampliamos la búsqueda?</h2>
      <p>No encontramos coincidencias guardadas. Podemos consultar las tiendas disponibles para intentar encontrar este producto.</p>
      <div class="quick-search-empty-actions">
        <button type="button" data-expand-quick-search>Buscar en tiendas</button>
        <button type="button" class="secondary" data-dismiss-quick-search>Ahora no</button>
      </div>
    </section>`;
}

async function refreshMeta() {
  const [health, stores, history, catalog] = await Promise.all([
    json("/api/health"),
    json("/api/stores"),
    json("/api/history"),
    json("/api/catalog?size=1&only_offers=false"),
  ]);
  const mongo = health.mongo ? `MongoDB ${health.products} productos` : "MongoDB no disponible";
  const qdrant = health.qdrant ? "Qdrant conectado" : "Qdrant no disponible";
  const redis = health.redis ? "Redis hoy" : "Redis no disponible";
  console.info(`health ${mongo} · ${qdrant} · ${redis} · ${health.stores} tiendas`);
  fillStores(stores);
  fillHistory(history);
  renderCategoryShortcuts(catalog.facets?.categories || []);
}

function withStopped(result) {
  const progress = result.progress || [];
  const done = progress.filter((item) => ["ok", "error", "skip"].includes(item.state)).length;
  const total = progress.length;
  return {
    ...result,
    cancelled: true,
    stores_done: done,
    stores_total: total,
    stopped_label: total ? `Búsqueda detenida · ${done} de ${total} tiendas` : "Búsqueda detenida",
  };
}

function applyThumbs(items) {
  for (const item of items || []) {
    const store = item.store || "";
    const id = item.product_id || "";
    if (!store || !id) continue;
    for (const row of currentRows) {
      if (row.store === store && row.product_id === id) row.has_thumb = true;
    }
    if (lastResult && Array.isArray(lastResult.rows)) {
      for (const row of lastResult.rows) {
        if (row.store === store && row.product_id === id) row.has_thumb = true;
      }
    }
    if (typeof patchThumb === "function") patchThumb(store, id);
  }
}

function abortActiveSearch({ reveal = false } = {}) {
  const source = currentSource;
  const result = lastResult;
  const searchId = currentSearchId;
  const wasActive = Boolean(source)
    || document.documentElement.classList.contains("is-searching")
    || document.documentElement.classList.contains("is-search-live");
  currentSource = null;
  currentSearchId = "";
  if (searchId) {
    fetch(`/api/search/cancel?id=${encodeURIComponent(searchId)}`, { method: "POST" }).catch(() => {});
  }
  if (source) source.close();
  setSearching(false);
  if (!wasActive) return;
  if (!reveal) return;
  if (result) {
    renderResults(withStopped(result));
    return;
  }
  $("summary").hidden = false;
  $("summary").className = "summary stats";
  $("summary").innerHTML = "<span class='stat'>Búsqueda detenida</span>";
  $("results").innerHTML = "<p class='panel empty-results'>Búsqueda detenida. No alcanzaron a llegar ofertas.</p>";
}

function runSearch(query) {
  abortActiveSearch({ reveal: false });
  const headerInput = document.querySelector('.desktop-quick-search input[name="q"]');
  if (headerInput) headerInput.value = query;
  currentQuery = query;
  hideCategoryShortcuts();
  currentDiscarded = [];
  lastResult = null;
  resultFocus = "matches";
  delete $("summary").dataset.technicalSummary;
  resetResultFilters();
  const stores = selectedStores();
  const quick = quickSearchEnabled();
  const requestedSource = sourceValue();
  let expandedSearchOffered = false;
  const offerExpandedSearch = () => {
    if (!quick || expandedSearchOffered || currentRows.length) return;
    expandedSearchOffered = true;
    renderExpandedSearchOffer();
  };
  if (!stores.length) {
    // First paint / header submit often races refreshMeta(): #stores is still empty.
    // Queue the query and resume from fillStores instead of a false "elige tienda" error.
    if (!storesReady) {
      pendingSearchQuery = query;
      setSearching(false);
      $("summary").hidden = false;
      $("summary").className = "summary";
      $("summary").textContent = "Cargando tiendas…";
      return;
    }
    setSearching(false);
    $("summary").hidden = false;
    $("summary").innerHTML = "<p class='err'>Elige al menos una tienda.</p>";
    return;
  }
  pendingSearchQuery = null;
  currentSearchId = (crypto.randomUUID && crypto.randomUUID()) || `s${Date.now()}`;
  $("summary").hidden = false;
  $("summary").className = "summary";
  $("summary").textContent = "Buscando…";
  setResultFiltersVisible(false);
  startSearchConversation(quick);
  setSearching(true);
  renderSkeleton();
  renderProgress(stores.map((id) => ({ id, title: id, state: "pending" })));
  const params = new URLSearchParams({
    q: query,
    source: quick ? "db" : requestedSource,
    quick: quick ? "true" : "false",
    max: $("max").value,
    price_band: $("price-band").checked ? "true" : "false",
    // Se reutilizan búsquedas del día salvo que se elija Forzar tiendas.
    fresh: $("fresh").checked ? "true" : "false",
    search_id: currentSearchId,
  });
  if (!allStoresSelected()) {
    params.set("stores", stores.join(","));
  }
  const source = new EventSource(`/api/search/stream?${params}`);
  currentSource = source;
  source.onmessage = (event) => {
    if (currentSource !== source) return;
    const payload = JSON.parse(event.data);
    if (payload.type === "error") {
      setSearching(false);
      $("summary").innerHTML = `<p class="err">${payload.detail}</p>`;
      source.close();
      if (currentSource === source) currentSource = null;
      return;
    }
    if (payload.type === "start") {
      renderProgress(payload.progress || []);
      const routed = productIndexLabel(payload.product_index);
      if (routed) {
        $("summary").textContent = `${routed}…`;
      }
      return;
    }
    if (payload.result) {
      renderResults(payload.result);
    }
    if (payload.type === "thumbs") {
      applyThumbs(payload.thumbs || []);
      return;
    }
    if (payload.type === "ready") {
      // `ready` solo significa que ya hay resultados parciales visibles. Las
      // tiendas restantes siguen trabajando, por lo que el spinner continúa.
      return;
    }
    if (payload.type === "done") {
      // Algunas búsquedas emiten `done` antes de terminar tiendas opcionales.
      // Solo cerrar el spinner cuando el progreso realmente esté completo.
      if (hasActiveStores(payload.result)) return;
      setSearching(false);
      offerExpandedSearch();
      json("/api/history").then(fillHistory).catch(() => {});
      return;
    }
    if (payload.type === "end") {
      setSearching(false);
      source.close();
      if (currentSource === source) {
        currentSource = null;
        currentSearchId = "";
      }
      offerExpandedSearch();
      json("/api/history").then(fillHistory).catch(() => {});
    }
  };
  source.onerror = () => {
    if (currentSource !== source) return;
    source.close();
    currentSource = null;
    currentSearchId = "";
    setSearching(false);
    if (!currentRows.length) {
      $("summary").innerHTML = "<p class='err'>Se cortó la consulta. Vuelve a buscar.</p>";
    }
  };
}

$("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runSearch($("query").value.trim());
});

const headerSearch = document.querySelector(".desktop-quick-search");
if (headerSearch) {
  headerSearch.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = new FormData(headerSearch).get("q")?.toString().trim() || "";
    if (!query) return;
    $("query").value = query;
    runSearch(query);
  });
}

$("search-stop").addEventListener("click", (event) => {
  event.preventDefault();
  abortActiveSearch({ reveal: true });
});

const liveStop = $("search-stop-live");
if (liveStop) {
  liveStop.addEventListener("click", (event) => {
    event.preventDefault();
    abortActiveSearch({ reveal: true });
  });
}

$("summary").addEventListener("click", (event) => {
  const button = event.target.closest("[data-result-focus]");
  if (!button) return;
  applyResultFocus(button.dataset.resultFocus);
});

$("results").addEventListener("click", (event) => {
  const expandQuickSearch = event.target.closest("[data-expand-quick-search]");
  if (expandQuickSearch) {
    const checkbox = document.querySelector('.desktop-quick-search input[name="quick"]');
    const both = document.querySelector('input[name="source"][value="both"]');
    if (checkbox) checkbox.checked = false;
    if (both) both.checked = true;
    runSearch(currentQuery);
    return;
  }
  const dismissQuickSearch = event.target.closest("[data-dismiss-quick-search]");
  if (dismissQuickSearch) {
    $("results").innerHTML = "<p class='panel empty-results'>No hay productos guardados que coincidan con la búsqueda.</p>";
    return;
  }
  const focusBtn = event.target.closest("[data-result-focus]");
  if (focusBtn) {
    applyResultFocus(focusBtn.dataset.resultFocus);
    return;
  }
  const button = event.target.closest(".watch-btn");
  if (!button) return;
  followProduct(button).catch((error) => {
    button.textContent = error.message;
  });
});

$("history").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-query]");
  if (!button) return;
  $("query").value = button.dataset.query;
  runSearch(button.dataset.query);
});

["table-filter", "only-comparable", "only-lowest", "only-offers", "only-discounts", "min-price", "max-price", "min-discount", "sort-by"].forEach((id) => {
  $(id).addEventListener("input", () => {
    if (id === "only-offers") syncOnlyOffersChip();
    currentPage = 1;
    renderTable();
  });
  $(id).addEventListener("change", () => {
    if (id === "only-offers") syncOnlyOffersChip();
    currentPage = 1;
    renderTable();
  });
});

$("only-offers-chip")?.addEventListener("click", () => {
  const box = $("only-offers");
  if (!box) return;
  box.checked = !box.checked;
  syncOnlyOffersChip();
  currentPage = 1;
  renderTable();
});

$("page-size").addEventListener("change", () => {
  const size = pageSize();
  localStorage.setItem(PAGE_SIZE_KEY, String(size));
  currentPage = 1;
  renderTable();
});

$("pager").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-page]");
  if (!button || button.disabled) return;
  const action = button.dataset.page;
  const pages = Math.max(1, Math.ceil((lastPagerTotal || 0) / pageSize()));
  if (action === "prev") currentPage = Math.max(1, currentPage - 1);
  else if (action === "next") currentPage = Math.min(pages, currentPage + 1);
  else currentPage = Number(action) || 1;
  renderTable();
});

$("view-list").addEventListener("click", () => setView("list"));
$("view-grid").addEventListener("click", () => setView("grid"));
initPageSize();
setView(currentView());

$("all-stores").addEventListener("click", () => setStoresChecked(true));
$("no-stores").addEventListener("click", () => setStoresChecked(false));
$("store-groups").addEventListener("change", (event) => {
  const toggle = event.target.closest("input[data-group]");
  if (!toggle) return;
  setStoresChecked(toggle.checked, toggle.dataset.group);
});
$("stores").addEventListener("change", () => {
  syncGroupToggles();
  updateExploreFilterBadge();
});

document.querySelectorAll('input[name="source"], #max, #price-band, #fresh').forEach((control) => {
  control.addEventListener("change", updateExploreFilterBadge);
  control.addEventListener("input", updateExploreFilterBadge);
});

refreshMeta()
  .then(() => {
    const start = new URLSearchParams(location.search);
    const query = start.get("q")?.trim() || "";
    if (!query) return;
    // fillStores may have already flushed the same queued header submit.
    if (currentQuery === query && storeChecks().length) return;
    const checkbox = document.querySelector('.desktop-quick-search input[name="quick"]');
    if (checkbox) checkbox.checked = start.get("quick") !== "0";
    const headerInput = document.querySelector('.desktop-quick-search input[name="q"]');
    if (headerInput) headerInput.value = query;
    $("query").value = query;
    runSearch(query);
  })
  .catch((error) => {
    console.error(error.message);
    storesReady = true;
    if (pendingSearchQuery) {
      pendingSearchQuery = null;
      setSearching(false);
      $("summary").hidden = false;
      $("summary").innerHTML = "<p class='err'>No se pudieron cargar las tiendas. Vuelve a intentar.</p>";
    }
  });

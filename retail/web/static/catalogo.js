// $, money, attr, discountOf, discountBadge y priceLadder vienen de prices.js

let page = 1;
let totalPages = 1;
const catalogSearchForm = document.querySelector(".desktop-quick-search");
const catalogSearchInput = catalogSearchForm?.querySelector('input[name="q"]');

function flash(text) {
  $("flash").hidden = false;
  $("flash").className = "err";
  $("flash").textContent = text;
}

function fillSelect(select, values, anyLabel, { keepMissing = true } = {}) {
  const current = select.value;
  const rows = [...values];
  if (keepMissing && current && !rows.some((item) => item.value === current)) {
    rows.unshift({ value: current, count: 0 });
  }
  const selected = rows.some((item) => item.value === current) ? current : "";
  select.innerHTML =
    `<option value="">${anyLabel}</option>` +
    rows
      .map((item) => `<option value="${attr(item.value)}" ${item.value === selected ? "selected" : ""}>${attr(item.label || item.value)} (${item.count})</option>`)
      .join("");
  select.value = selected;
}

function card(item) {
  const fichaUrl = `/producto?store=${encodeURIComponent(item.store)}&id=${encodeURIComponent(item.product_id)}`;
  const image = thumbMarkup(
    "card-img",
    item.has_thumb
      ? `/api/thumb?store=${encodeURIComponent(item.store)}&id=${encodeURIComponent(item.product_id)}`
      : ""
  );
  const linkedImage = item.product_id
    ? `<a class="product-image-link" href="${fichaUrl}" aria-label="Ver ficha de ${attr(item.name)}">${image}</a>`
    : image;
  const rating = item.rating ? `<span class="muted">★ ${Number(item.rating).toFixed(1)}${item.reviews ? ` (${item.reviews})` : ""}</span>` : "";
  return `
    <article class="panel card">
      ${linkedImage}
      <h3><a href="${fichaUrl}">${attr(item.name)}</a></h3>
      <p class="muted">${storeLogo(item.display_store || item.store, item.store_title || item.store)}${item.brand ? ` · ${attr(item.brand)}` : ""}</p>
      ${soldBy(item)}
      <p class="price">${money(item.price)} ${discountBadge(item)}</p>
      ${priceLadder(item)}
      <p>${rating}</p>
      ${item.url ? `<a class="muted" href="${attr(item.url)}" target="_blank" rel="noreferrer">ir a la tienda</a>` : ""}
    </article>`;
}

function params() {
  const query = new URLSearchParams({ page: String(page), size: "40" });
  const text = catalogSearchInput?.value.trim() || "";
  if (text) query.set("q", text);
  const map = { category: "category", store: "store", brand: "brand", min_price: "min_price", max_price: "max_price", sort: "sort" };
  for (const [id, key] of Object.entries(map)) {
    const value = $(id).value;
    if (value) query.set(key, value);
  }
  if ($("only_offers").checked) query.set("only_offers", "true");
  return query;
}

function updateFilterSummary() {
  const active = [];
  if ($("category").value) active.push("categoría");
  if ($("store").value) active.push("tienda");
  if ($("brand").value) active.push("marca");
  if ($("min_price").value || $("max_price").value) active.push("precio");
  if ($("sort").value && $("sort").value !== "price") active.push("orden");
  if ($("only_offers").checked) active.push("solo ofertas");
  $("catalog-filter-count").textContent = active.length
    ? `${active.length} ${active.length === 1 ? "filtro activo" : "filtros activos"}`
    : "Sin filtros";
}

async function load() {
  if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(true);
  try {
  const response = await fetch(`/api/catalog?${params()}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    flash(typeof data.detail === "string" ? data.detail : response.statusText);
    return;
  }
  $("flash").hidden = true;
  fillSelect($("category"), data.facets.categories || [], "todas");
  fillSelect($("store"), data.facets.stores || [], "todas", { keepMissing: false });
  fillSelect($("brand"), data.facets.brands || [], "todas", { keepMissing: false });
  const items = data.items || [];
  totalPages = Math.max(1, Math.ceil((data.total || 0) / (data.size || 40)));
  $("summary").textContent = data.total
    ? `${data.total.toLocaleString("es-CL")} productos guardados`
    : "Todavía no hay productos guardados. Corre una búsqueda o el batch.";
  $("grid").innerHTML = items.length ? items.map(card).join("") : "<p class='panel muted'>Sin resultados con esos filtros.</p>";
  saveProductTrail(items);
  const pager = RetailPager.render(data.page, totalPages);
  page = pager.page;
  updateFilterSummary();
  } finally {
    if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(false);
  }
}

function reload() {
  page = 1;
  load().catch((error) => flash(error.message));
}

function applyStartFilters() {
  const url = new URLSearchParams(location.search);
  if (catalogSearchInput && url.get("q")) catalogSearchInput.value = url.get("q");
  for (const id of ["min_price", "max_price", "sort"]) {
    if (url.get(id)) $(id).value = url.get(id);
  }
  if (url.get("only_offers") === "true") $("only_offers").checked = true;
  if (url.get("only_offers") === "false") $("only_offers").checked = false;
  for (const id of ["category", "store", "brand"]) {
    const value = url.get(id);
    if (!value) continue;
    $(id).innerHTML = `<option value="${attr(value)}" selected>${attr(value)}</option>`;
  }
}

$("category").addEventListener("change", () => {
  $("store").value = "";
  $("brand").value = "";
  reload();
});
$("store").addEventListener("change", () => {
  $("brand").value = "";
  reload();
});
["brand", "min_price", "max_price", "sort", "only_offers"].forEach((id) => {
  $(id).addEventListener("change", reload);
});
catalogSearchForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  reload();
});
catalogSearchInput?.addEventListener("search", reload);

$("prev").addEventListener("click", () => {
  if (page > 1) {
    page -= 1;
    load().catch((error) => flash(error.message));
  }
});
$("next").addEventListener("click", () => {
  if (page < totalPages) {
    page += 1;
    load().catch((error) => flash(error.message));
  }
});

applyStartFilters();
load().catch((error) => flash(error.message));

// $, money, attr, thumbMarkup, storeLogo y discountOf vienen de prices.js

const MAX_COMPARE = 4;
let seedProduct = null;
let selected = [];
let suggestions = [];

function keyOf(item) {
  return `${item?.store || ""}:${item?.product_id || ""}`;
}

function productUrl(item) {
  return `/producto?store=${encodeURIComponent(item.store || "")}&id=${encodeURIComponent(item.product_id || "")}`;
}

function thumbUrl(item) {
  return `/api/thumb?store=${encodeURIComponent(item.store || "")}&id=${encodeURIComponent(item.product_id || "")}`;
}

function flash(message) {
  const box = $("flash");
  box.hidden = !message;
  box.className = "summary err";
  box.textContent = message || "";
}

function setStatus(message) {
  $("compare-status").textContent = message || "";
}

async function fetchProduct(store, id) {
  const params = new URLSearchParams({ store, id });
  const response = await fetch(`/api/product?${params}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.product) throw new Error(data.detail || "No se encontró el producto.");
  return data.product;
}

async function fetchFicha(item, comparableOnly = false) {
  const params = new URLSearchParams({ store: item.store, id: item.product_id });
  if (comparableOnly) params.set("comparable_only", "true");
  const response = await fetch(`/api/product/ficha?${params}`);
  if (!response.ok) return {};
  return response.json().catch(() => ({}));
}

function updateUrl() {
  const url = new URL(location.href);
  url.searchParams.delete("item");
  for (const item of selected) url.searchParams.append("item", keyOf(item));
  history.replaceState(null, "", url);
}

function renderSuggestions(items, label = "Productos similares") {
  const selectedKeys = new Set(selected.map(keyOf));
  const unique = new Map();
  for (const item of items || []) {
    const key = keyOf(item);
    if (!item.product_id || Number(item.comparison_fields || 0) < 1 || unique.has(key)) continue;
    unique.set(key, item);
  }
  suggestions = [...unique.values()].slice(0, 12);
  setStatus(suggestions.length ? `${label}: ${suggestions.length}` : "No encontramos alternativas. Prueba otra búsqueda.");
  $("compare-results").innerHTML = suggestions.map((item) => {
    const alreadySelected = selectedKeys.has(keyOf(item));
    const image = thumbMarkup("thumb thumb-sm", item.has_thumb ? thumbUrl(item) : "", { store: item.store, id: item.product_id });
    return `<article class="compare-hit">
      <div class="compare-hit-main">${image}<div><b>${attr(item.name || "Producto")}</b><span>${storeLogo(item.display_store || item.store, item.store_title || item.store)}${item.price != null ? ` · ${money(item.price)}` : ""} · ${Number(item.comparison_fields)} características</span></div></div>
      <button type="button" class="btn small" data-add-store="${attr(item.store)}" data-add-id="${attr(item.product_id)}" ${alreadySelected ? "disabled" : ""}>${alreadySelected ? "Agregado" : "Agregar"}</button>
    </article>`;
  }).join("");
}

function renderSelected() {
  $("selected-count").textContent = `${selected.length} de ${MAX_COMPARE}`;
  $("compare-selected").innerHTML = selected.map((item) => `
    <article class="compare-selected-card">
      ${thumbMarkup("thumb thumb-sm", item.has_thumb ? thumbUrl(item) : "", { store: item.store, id: item.product_id })}
      <div><strong>${attr(item.name)}</strong><span>${storeLogo(item.display_store || item.store, item.store_title || item.store)} · ${money(item.price)}</span></div>
      <button type="button" class="secondary" data-remove-store="${attr(item.store)}" data-remove-id="${attr(item.product_id)}" aria-label="Quitar ${attr(item.name)}">×</button>
    </article>`).join("");
  updateUrl();
}

function mergedSpecs(product, ficha) {
  const specs = {};
  for (const source of [product.specifications, ficha.specifications]) {
    if (!source || typeof source !== "object" || Array.isArray(source)) continue;
    for (const [key, value] of Object.entries(source)) {
      if (key && value != null && value !== "") specs[key] = String(value);
    }
  }
  return specs;
}

function savingLabel(product) {
  const normal = product.price_normal;
  const price = product.price;
  if (!normal || price == null || normal <= price) return "—";
  const amount = normal - price;
  const percent = Math.round(amount * 100 / normal);
  return `${money(amount)} (${percent}%)`;
}

function conditionLabel(value) {
  return ({ new: "Nuevo", refurbished: "Reacondicionado", open_box: "Caja abierta", display: "Exhibición", used: "Usado" })[value] || "No informada";
}

async function renderComparison() {
  const host = $("compare-table");
  if (!selected.length) {
    host.innerHTML = `<p class="muted compare-empty">Agrega productos para comenzar la comparación.</p>`;
    return;
  }
  host.innerHTML = `<div class="compare-loading"><span class="spinner" aria-hidden="true"></span> Preparando comparación…</div>`;
  const cards = await Promise.all(selected.map(async (item) => {
    try {
      const product = item._complete ? item : await fetchProduct(item.store, item.product_id);
      const ficha = await fetchFicha(product);
      return { product: { ...product, _complete: true }, ficha, specs: mergedSpecs(product, ficha) };
    } catch (_error) {
      return { product: item, ficha: {}, specs: {} };
    }
  }));
  selected = cards.map((card) => card.product);
  renderSelected();

  const priced = cards.map((card) => card.product.price).filter((value) => value != null);
  const lowest = priced.length ? Math.min(...priced) : null;
  const allShippingKnown = cards.length > 0 && cards.every(({ product }) => product.price != null && product.shipping_cost != null);
  const totalValues = cards.map(({ product }) => product.price != null && product.shipping_cost != null
    ? Number(product.price) + Number(product.shipping_cost)
    : null);
  const lowestTotal = allShippingKnown ? Math.min(...totalValues) : null;
  const specKeys = [...new Set(cards.flatMap((card) => Object.keys(card.specs)))];
  const headers = cards.map(({ product }) => `
    <th>
      <a class="compare-product-head" href="${attr(productUrl(product))}">
        ${thumbMarkup("thumb", product.has_thumb ? thumbUrl(product) : "", { store: product.store, id: product.product_id })}
        <span>${attr(product.name)}<small>${storeLogo(product.display_store || product.store, product.store_title || product.store)}</small></span>
      </a>
    </th>`).join("");
  const row = (label, values, className = "") => `<tr class="${className}"><th scope="row">${label}</th>${values.map((value) => `<td>${value ?? "—"}</td>`).join("")}</tr>`;
  const priceValues = cards.map(({ product }) => `<strong class="compare-price${lowest != null && product.price === lowest ? " best-price" : ""}">${money(product.price)}</strong>`);
  const rows = [
    row("Precio actual", priceValues, "compare-price-row"),
    row("Condición", cards.map(({ product }) => attr(conditionLabel(product.condition)))),
    row("Precio con tarjeta", cards.map(({ product }) => (product.price_card ?? product.price_cmr) ? `${money(product.price_card ?? product.price_cmr)} · ${attr(product.payment_card_name || "Tarjeta de la tienda")}` : "—")),
    row("Financiamiento", cards.map(({ product }) => [
      product.installment_count ? `${product.installment_count} cuotas` : "",
      product.financial_cae != null ? `CAE ${Number(product.financial_cae).toLocaleString("es-CL")}%` : "",
      product.installment_total ? `total ${money(product.installment_total)}` : "",
    ].filter(Boolean).join(" · ") || "—")),
    row("Despacho visible", cards.map(({ product }) => product.shipping_cost === 0 ? "Gratis" : product.shipping_cost != null ? money(product.shipping_cost) : product.shipping_free_threshold ? `Gratis sobre ${money(product.shipping_free_threshold)}` : "Por confirmar")),
    row("Total con despacho", totalValues.map((value) => value == null ? "—" : `<strong class="compare-price${value === lowestTotal ? " best-price" : ""}">${money(value)}</strong>`)),
    row("Precio normal", cards.map(({ product }) => product.price_normal ? money(product.price_normal) : "—")),
    row("Ahorro", cards.map(({ product }) => savingLabel(product))),
    row("Tienda", cards.map(({ product }) => storeLogo(product.display_store || product.store, product.store_title || product.store))),
    row("Disponibilidad", cards.map(({ product }) => attr(availabilityLabel(product.availability, product.stock)))),
    row("Marca", cards.map(({ product }) => attr(product.brand || "—"))),
    ...specKeys.map((key) => row(attr(key), cards.map((card) => attr(card.specs[key] || "—")))),
  ];
  host.innerHTML = `<table class="compare-table compare-page-table"><thead><tr><th>Dato</th>${headers}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

async function addProduct(item) {
  if (selected.some((row) => keyOf(row) === keyOf(item))) return;
  if (selected.length >= MAX_COMPARE) {
    flash(`Puedes comparar un máximo de ${MAX_COMPARE} productos.`);
    return;
  }
  flash("");
  selected.push(item);
  renderSelected();
  renderSuggestions(suggestions);
  await renderComparison();
}

async function removeProduct(store, id) {
  selected = selected.filter((item) => !(item.store === store && item.product_id === id));
  renderSelected();
  await renderComparison();
}

async function loadSimilar() {
  if (!seedProduct) return;
  setStatus("Buscando productos similares…");
  $("compare-results").innerHTML = `<div class="compare-loading"><span class="spinner" aria-hidden="true"></span> Buscando alternativas…</div>`;
  const ficha = await fetchFicha(seedProduct, true);
  renderSuggestions(ficha.related || []);
}

async function searchCatalog() {
  const query = $("compare-search").value.trim();
  if (!query) return loadSimilar();
  setStatus(`Buscando “${query}”…`);
  const params = new URLSearchParams({ q: query, page: "1", size: "12", sort: "price", only_comparable: "true" });
  try {
    const response = await fetch(`/api/catalog?${params}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(response.statusText);
    renderSuggestions(data.items || [], "Resultados");
  } catch (_error) {
    setStatus("No se pudo completar la búsqueda. Inténtalo nuevamente.");
    $("compare-results").innerHTML = "";
  }
}

function parseKey(value) {
  const separator = String(value || "").indexOf(":");
  if (separator < 1) return null;
  return { store: value.slice(0, separator), product_id: value.slice(separator + 1) };
}

async function load() {
  const params = new URLSearchParams(location.search);
  const initial = params.getAll("item").map(parseKey).filter(Boolean);
  if (!initial.length && params.get("store") && params.get("id")) initial.push({ store: params.get("store"), product_id: params.get("id") });
  if (!initial.length) throw new Error("Falta el producto inicial para comparar.");
  const products = await Promise.all(initial.slice(0, MAX_COMPARE).map((item) => fetchProduct(item.store, item.product_id)));
  seedProduct = products[0];
  selected = products;
  $("back-product").href = productUrl(seedProduct);
  $("compare-search").value = seedProduct.name || "";
  renderSelected();
  await Promise.all([renderComparison(), loadSimilar()]);
}

$("compare-search-form").addEventListener("submit", (event) => { event.preventDefault(); searchCatalog(); });
$("compare-results").addEventListener("click", (event) => {
  const button = event.target.closest("[data-add-id]");
  if (!button) return;
  const item = suggestions.find((row) => row.store === button.dataset.addStore && row.product_id === button.dataset.addId);
  if (item) addProduct(item);
});
$("compare-selected").addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-id]");
  if (button) removeProduct(button.dataset.removeStore, button.dataset.removeId);
});

load().catch((error) => flash(error.message || "No se pudo abrir el comparador."));

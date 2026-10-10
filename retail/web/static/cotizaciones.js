let activeQuote = null;
let dirtyQuote = false;
let documentImport = null;
let importMode = "shopping_list";
let storeGroups = [];
/** Polling mientras hay celdas «buscando en tienda…». */
let matrixPollTimer = null;
const MATRIX_POLL_MS = 8000;
const MATRIX_POLL_MAX = 24;
const DOCLING_POLL_MS = 6000;
const DOCLING_POLL_MAX = 40;
const CATALOG_STALE_HOURS = 48;
let matrixPollLeft = 0;
let doclingPollTimer = null;
let doclingPollLeft = 0;
/** Estado local del carrito (lista de compra). */
let cart = {
  id: null,
  version: null,
  title: "supermercado",
  store_group: "supermercados",
  store_groups: ["supermercados"],
  store_ids: [],
  items: [],
};

function quoteMessage(text, error = false) {
  $("quote-status").textContent = text;
  $("quote-status").className = error ? "err" : "summary";
}

async function quoteRequest(url, method = "GET", body) {
  const response = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "Revisa los campos de la lista y vuelve a intentarlo.";
    throw new Error(detail);
  }
  return data;
}

const STATUS_LABELS = { draft: "Borrador", review: "Revisión", compared: "Comparada", exported: "Exportada" };

function setImportMode(mode) {
  importMode = mode === "quote" ? "quote" : "shopping_list";
  document.querySelectorAll(".quote-mode-tab").forEach(tab => {
    const active = tab.dataset.mode === importMode;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  $("mode-shopping").hidden = importMode !== "shopping_list";
  $("mode-quote").hidden = importMode !== "quote";
  $("quote-docling-panel").hidden = importMode !== "quote";
}

document.querySelectorAll(".quote-mode-tab").forEach(tab => {
  tab.addEventListener("click", () => setImportMode(tab.dataset.mode));
});

function groupStoreCount(group) {
  if (Array.isArray(group?.stores) && group.stores.length) return group.stores.length;
  return (group?.store_ids || []).length;
}

function selectedStoreGroups() {
  const chosen = [...(cart.store_groups || [])].filter(Boolean);
  if (chosen.length) return chosen;
  if (cart.store_group) return [cart.store_group];
  return [];
}

function ensureDefaultStoreSelection() {
  if (selectedStoreGroups().length) {
    cart.store_groups = selectedStoreGroups();
    cart.store_group = cart.store_groups[0];
    cart.store_ids = [];
    return;
  }
  const superGroup = storeGroups.find((g) => g.id === "supermercados") || storeGroups[0];
  cart.store_groups = superGroup ? [superGroup.id] : [];
  cart.store_group = cart.store_groups[0] || "";
  cart.store_ids = [];
}

function primaryStoreGroup() {
  const groups = selectedStoreGroups();
  return groups[0] || cart.store_group || storeGroups[0]?.id || "supermercados";
}

function resolvedStoreCountForGroups(groupIds) {
  const seen = new Set();
  for (const id of groupIds) {
    const group = storeGroups.find((g) => g.id === id);
    if (!group) continue;
    for (const storeId of (group.store_ids || [])) seen.add(storeId);
    for (const store of (group.stores || [])) {
      if (store?.id) seen.add(store.id);
    }
  }
  return seen.size;
}

function updateStorePickerSummary() {
  const summary = $("cart-store-summary");
  if (!summary) return;
  const groups = selectedStoreGroups();
  const storeCount = resolvedStoreCountForGroups(groups);
  if (!groups.length) {
    summary.textContent = "Ninguna categoría seleccionada";
    return;
  }
  summary.textContent = `${groups.length} categorí${groups.length === 1 ? "a" : "as"} · ${storeCount} tienda${storeCount === 1 ? "" : "s"} al cotizar`;
}

function setAllCategoriesChecked(checked) {
  cart.store_groups = checked ? storeGroups.map((g) => g.id) : [];
  cart.store_group = cart.store_groups[0] || "";
  cart.store_ids = [];
  renderStorePicker();
}

function catalogThumbUrl(item) {
  if (!item?.has_thumb || !item.store || !item.product_id) return "";
  return `/api/thumb?store=${encodeURIComponent(item.store)}&id=${encodeURIComponent(item.product_id)}`;
}

function renderStorePicker() {
  const cats = $("cart-store-categories");
  if (!cats) return;
  const selected = new Set(selectedStoreGroups());
  cats.replaceChildren();
  for (const group of storeGroups) {
    const label = document.createElement("label");
    label.className = "cart-category-card" + (selected.has(group.id) ? " is-selected" : "");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = group.id;
    input.dataset.group = group.id;
    input.checked = selected.has(group.id);
    input.addEventListener("change", () => {
      const next = new Set(selectedStoreGroups());
      if (input.checked) next.add(group.id);
      else next.delete(group.id);
      cart.store_groups = [...next];
      cart.store_group = cart.store_groups[0] || "";
      cart.store_ids = [];
      renderStorePicker();
    });
    const count = groupStoreCount(group);
    const emptyN = Number(group.empty_catalog_stores) || (group.stores || []).filter((s) => s.catalog_empty).length;
    const emptyHint = emptyN
      ? ` · <span class="cart-catalog-empty">${emptyN} sin catálogo</span>`
      : "";
    const storeHints = (group.stores || [])
      .filter((s) => s.catalog_empty)
      .map((s) => s.title || s.id)
      .slice(0, 4)
      .join(", ");
    label.innerHTML = `<span class="cart-category-card-title">${attr(group.title || group.id)}</span>
      <span class="cart-category-card-meta">${count} tienda${count === 1 ? "" : "s"}${emptyHint}</span>
      ${storeHints ? `<span class="cart-category-card-meta muted">Vacío: ${attr(storeHints)}</span>` : ""}`;
    label.prepend(input);
    cats.append(label);
  }
  const select = $("shopping-group");
  if (select) {
    select.replaceChildren();
    for (const group of storeGroups) {
      const opt = document.createElement("option");
      opt.value = group.id;
      opt.textContent = group.title || group.id;
      select.append(opt);
    }
    if (cart.store_group) select.value = cart.store_group;
  }
  updateStorePickerSummary();
}

function syncCartFromForm() {
  cart.title = ($("shopping-title")?.value || "").trim() || "Lista de compra";
  cart.store_groups = selectedStoreGroups();
  cart.store_group = primaryStoreGroup();
  cart.store_ids = [];
  const rows = $("cart-items")?.querySelectorAll("tr[data-cart-index]") || [];
  rows.forEach(row => {
    const index = Number(row.dataset.cartIndex);
    if (!cart.items[index]) return;
    const qtyInput = row.querySelector("[data-cart-qty]");
    const nameInput = row.querySelector("[data-cart-name]");
    if (qtyInput) {
      const qty = Number(qtyInput.value);
      cart.items[index].quantity = Number.isFinite(qty) && qty > 0 ? qty : 1;
    }
    if (nameInput) {
      const name = nameInput.value.trim();
      if (name.length >= 3) cart.items[index].name = name;
    }
  });
}

function renderCart() {
  const body = $("cart-items");
  const empty = $("cart-empty");
  const count = $("cart-count");
  if (!body) return;
  if ($("shopping-title") && document.activeElement !== $("shopping-title")) {
    $("shopping-title").value = cart.title || "";
  }
  body.replaceChildren();
  cart.items.forEach((item, index) => {
    const tr = document.createElement("tr");
    tr.dataset.cartIndex = String(index);
    const thumb = typeof thumbMarkup === "function"
      ? thumbMarkup("cart-thumb cart-thumb-lg", catalogThumbUrl(item), { store: item.store, id: item.product_id })
      : "";
    tr.innerHTML = `<td class="cart-product-cell">${thumb}<div class="cart-product-meta"><input data-cart-name maxlength="300" value="${attr(item.name)}">${item.brand ? `<small>${attr(item.brand)}</small>` : ""}</div></td>
      <td><input data-cart-qty type="number" min="1" max="10000" step="1" value="${item.quantity ?? 1}"></td>
      <td><button type="button" class="secondary" data-cart-remove="${index}">Quitar</button></td>`;
    body.append(tr);
  });
  if (count) count.textContent = String(cart.items.length);
  if (empty) empty.hidden = cart.items.length > 0;
}

function resetCart() {
  cart = {
    id: null,
    version: null,
    title: "supermercado",
    store_group: "supermercados",
    store_groups: ["supermercados"],
    store_ids: [],
    items: [],
  };
  activeQuote = null;
  $("quote-detail").hidden = true;
  $("shopping-matrix-wrap").hidden = true;
  $("shopping-matrix-wrap").replaceChildren();
  ensureDefaultStoreSelection();
  renderStorePicker();
  renderCart();
  quoteMessage("Nueva lista lista para armar el carrito.");
}

function loadCartFromQuote(quote) {
  cart = {
    id: quote.id,
    version: quote.version,
    title: quote.title || "Lista de compra",
    store_group: quote.store_group || "supermercados",
    store_groups: [...(quote.store_groups || (quote.store_group ? [quote.store_group] : ["supermercados"]))],
    store_ids: [],
    items: (quote.items || []).map(line => ({
      name: line.name,
      quantity: line.quantity ?? 1,
      unit: line.unit || "unidad",
      brand: line.brand || "",
      gtin: line.gtin || "",
      store: line.store || "",
      product_id: line.product_id || "",
      has_thumb: Boolean(line.has_thumb),
    })),
  };
  ensureDefaultStoreSelection();
  renderStorePicker();
  renderCart();
}

function cartPayload() {
  syncCartFromForm();
  const payload = {
    title: cart.title,
    store_group: cart.store_group,
    store_groups: cart.store_groups,
    store_ids: [],
    items: cart.items.map(item => ({
      name: item.name,
      quantity: item.quantity ?? 1,
      unit: item.unit || "unidad",
      brand: item.brand || "",
      gtin: item.gtin || "",
    })),
  };
  if (cart.id) {
    payload.quote_id = cart.id;
    payload.version = cart.version;
  }
  return payload;
}

async function saveCart() {
  const previous = cart.items.map((item) => ({ ...item }));
  const data = await quoteRequest("/api/quotes/shopping-cart", "POST", cartPayload());
  const quote = data.quote;
  cart.id = quote.id;
  cart.version = quote.version;
  cart.store_ids = [];
  cart.store_group = quote.store_group || cart.store_group;
  cart.store_groups = [...(quote.store_groups || (quote.store_group ? [quote.store_group] : cart.store_groups))];
  cart.items = (quote.items || []).map((line, index) => {
    const prior = previous[index]
      || previous.find((row) => row.name === line.name && (row.brand || "") === (line.brand || ""));
    return {
      name: line.name,
      quantity: line.quantity ?? 1,
      unit: line.unit || "unidad",
      brand: line.brand || "",
      gtin: line.gtin || "",
      store: prior?.store || "",
      product_id: prior?.product_id || "",
      has_thumb: Boolean(prior?.has_thumb),
    };
  });
  renderCart();
  renderStorePicker();
  return quote;
}

async function loadStoreGroups() {
  const data = await quoteRequest("/api/quotes/store-groups");
  storeGroups = data.groups || [];
  ensureDefaultStoreSelection();
  renderStorePicker();
}

async function listQuotes() {
  const data = await quoteRequest("/api/quotes");
  $("quote-list").replaceChildren();
  for (const quote of data.quotes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quote-list-item";
    const status = STATUS_LABELS[quote.status] || quote.status || "Borrador";
    const modeLabel = quote.mode === "shopping_list" ? "Lista" : "Cotización";
    button.innerHTML = `<span>${attr(quote.title)}</span><small>${attr(modeLabel)}${quote.store_group ? ` · ${attr(quote.store_group)}` : ""}</small><small class="quote-status-pill" data-status="${attr(quote.status || "draft")}">${attr(status)}</small>`;
    button.addEventListener("click", () => openQuote(quote.id).catch(showQuoteError));
    $("quote-list").append(button);
  }
  if (!data.quotes.length) $("quote-list").textContent = "Todavía no tienes listas ni cotizaciones.";
}

function showQuoteError(error) { quoteMessage(error.message, true); }

function isShopping(quote) {
  return (quote || activeQuote)?.mode === "shopping_list";
}

function formatObserved(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" });
}

function countSearchingCells(data) {
  let n = Number(data?.searching_cells);
  if (Number.isFinite(n) && n >= 0) return n;
  n = 0;
  for (const row of data?.report?.rows || []) {
    for (const cell of Object.values(row.cells || {})) {
      if (cell && !cell.matched && cell.empty_reason === "searching") n += 1;
    }
  }
  return n;
}

function stopMatrixPoll() {
  if (matrixPollTimer) {
    clearInterval(matrixPollTimer);
    matrixPollTimer = null;
  }
  matrixPollLeft = 0;
}

function startMatrixPoll(quoteId) {
  stopMatrixPoll();
  if (!quoteId) return;
  matrixPollLeft = MATRIX_POLL_MAX;
  matrixPollTimer = setInterval(async () => {
    if (matrixPollLeft <= 0) {
      stopMatrixPoll();
      quoteMessage(
        "Scrape aún en curso o sin resultado. Pulsá «Regenerar matriz desde catálogo» para volver a consultar.",
        true,
      );
      return;
    }
    matrixPollLeft -= 1;
    if (!activeQuote || activeQuote.id !== quoteId) {
      stopMatrixPoll();
      return;
    }
    try {
      const result = await quoteRequest(
        `/api/quotes/${encodeURIComponent(quoteId)}/rebuild-matrix`,
        "POST",
      );
      renderQuote(result);
      const left = countSearchingCells(result);
      if (left > 0) {
        quoteMessage(`Buscando en tienda… ${left} celda(s) pendientes (scrape en segundo plano).`);
      } else {
        stopMatrixPoll();
        quoteMessage("Matriz actualizada: scrape on-miss terminó.");
      }
    } catch (_error) {
      /* siguiente tick */
    }
  }, MATRIX_POLL_MS);
}

function stopDoclingPoll() {
  if (doclingPollTimer) {
    clearInterval(doclingPollTimer);
    doclingPollTimer = null;
  }
  doclingPollLeft = 0;
}

function startDoclingPoll(jobId) {
  stopDoclingPoll();
  if (!jobId) return;
  doclingPollLeft = DOCLING_POLL_MAX;
  doclingPollTimer = setInterval(async () => {
    if (doclingPollLeft <= 0 || doclingJobId !== jobId) {
      stopDoclingPoll();
      return;
    }
    doclingPollLeft -= 1;
    try {
      const job = await quoteRequest(`/api/quotes/convert-jobs/${encodeURIComponent(jobId)}`);
      showDoclingStatus(job);
      if (["done", "failed", "needs_docling"].includes(job.status)) {
        stopDoclingPoll();
        if (job.status === "done") {
          quoteMessage("Conversión lista. Podés cargar el JSON resultante.");
        }
      }
    } catch (_error) {
      /* siguiente tick */
    }
  }, DOCLING_POLL_MS);
}

function catalogPriceAgeHours(iso) {
  if (!iso) return null;
  const stamp = new Date(iso).getTime();
  if (Number.isNaN(stamp)) return null;
  return (Date.now() - stamp) / 3600000;
}

function renderMatrix(data) {
  const stores = data.report.stores || data.report.summary.stores || [];
  const wrap = $("shopping-matrix-wrap");
  const head = ["Producto", "Cant.", ...stores, "Mejor"];
  let html = `<table class="shopping-matrix"><thead><tr>${head.map(h => `<th>${attr(h)}</th>`).join("")}</tr></thead><tbody>`;
  for (const row of data.report.rows) {
    const item = row.item;
    html += `<tr><td>${attr(item.name)}${item.brand ? `<small>${attr(item.brand)}</small>` : ""}</td><td>${item.quantity}${item.unit && item.unit !== "unidad" ? ` ${attr(item.unit)}` : ""}</td>`;
    for (const store of stores) {
      const cell = row.cells[store] || {};
      if (!cell.matched) {
        const reason = cell.empty_reason || "unknown";
        const searching = reason === "searching";
        const emptyClass = searching
          ? "matrix-empty matrix-searching"
          : (reason === "no_catalog" ? "matrix-empty matrix-no-catalog" : "matrix-empty matrix-no-match");
        const reasonBadge = searching
          ? "buscando…"
          : (reason === "no_catalog" ? "sin catálogo" : (reason === "no_match" ? "sin match" : reason));
        html += `<td class="${emptyClass}"><button type="button" class="matrix-cell-btn" data-matrix-index="${row.index}" data-matrix-store="${attr(store)}"><span class="matrix-empty-badge">${attr(reasonBadge)}</span><span class="matrix-meta">${attr(cell.label || "sin stock o sin match")}</span></button></td>`;
        continue;
      }
      const conf = cell.confidence != null ? `${Math.round(cell.confidence * 100)}%` : "";
      const observed = formatObserved(cell.observed_at);
      const age = cell.price_age_hours != null ? `${cell.price_age_hours} h` : "";
      const staleClass = cell.stale ? " matrix-stale" : "";
      html += `<td class="${staleClass.trim()}"><button type="button" class="matrix-cell-btn" data-matrix-index="${row.index}" data-matrix-store="${attr(store)}">
        <span class="matrix-price">${money(cell.price)}</span>
        <span class="matrix-meta">${attr(cell.name || "")}</span>
        <span class="matrix-meta">${attr(cell.match_reason || (conf ? `confianza ${conf}` : ""))}${cell.confirmed ? " · confirmada" : " · sugerida"}</span>
        ${observed ? `<span class="matrix-meta">precio ${attr(observed)}${age ? ` · ${attr(age)}` : ""}</span>` : ""}
        ${cell.stale ? `<span class="matrix-stale-badge">stale · fuera de ${attr(data.report.summary.price_max_age_hours || 48)} h</span>` : ""}
        ${cell.issues?.length ? `<span class="matrix-meta">${attr(cell.issues.join(" "))}</span>` : ""}
      </button>
      ${cell.url ? `<a href="${attr(cell.url)}" target="_blank" rel="noopener">Ficha</a>` : ""}
      </td>`;
    }
    html += `<td>${row.best_store ? `<span class="best-mark">${attr(row.best_store)}</span><span class="matrix-meta">${money(row.best_price)}</span>` : "—"}</td></tr>`;
  }
  html += "</tbody></table>";
  wrap.innerHTML = html;
  wrap.hidden = false;
}

function renderQuote(data) {
  activeQuote = data.quote;
  dirtyQuote = false;
  $("quote-detail").hidden = false;
  const shopping = isShopping(activeQuote);
  if (shopping) loadCartFromQuote(activeQuote);
  const status = data.report.summary.status || activeQuote.status || "draft";
  const modeTag = shopping ? "Lista de compra" : "Cotización";
  $("quote-heading").textContent = `${activeQuote.title} · ${modeTag} · ${STATUS_LABELS[status] || status}`;
  $("quote-valid-until").value = activeQuote.valid_until || "";
  $("quote-edit-tax").checked = activeQuote.tax_included === true;
  $("quote-source-reviewed").checked = activeQuote.source_reviewed === true;
  $("quote-tax-wrap").hidden = shopping;
  $("quote-reviewed-wrap").hidden = shopping;
  $("quote-lines-wrap").hidden = shopping;
  $("shopping-rebuild").hidden = !shopping;
  if ($("quote-refresh-prices")) $("quote-refresh-prices").hidden = false;
  $("quote-save-btn").textContent = shopping ? "Guardar nombres / cantidades" : "Guardar correcciones";

  if (shopping) {
    $("quote-lines").innerHTML = "";
    if (activeQuote.store_matches && Object.keys(activeQuote.store_matches).length) {
      renderMatrix(data);
    } else {
      $("shopping-matrix-wrap").hidden = true;
      $("shopping-matrix-wrap").replaceChildren();
    }
  } else {
    $("shopping-matrix-wrap").hidden = true;
    $("shopping-matrix-wrap").replaceChildren();
    $("quote-lines").innerHTML = activeQuote.items.map((line, index) => {
      const evidence = line.evidence;
      const trace = evidence ? `${evidence.source || activeQuote.source_name} · fila ${evidence.row}${evidence.page ? ` · página ${evidence.page}` : ""}` : "Datos ingresados manualmente";
      const chosen = data.report.rows[index]?.selected;
      const maxAge = data.report.summary.price_max_age_hours || CATALOG_STALE_HOURS;
      let chosenMeta = "Pendiente de confirmación";
      if (chosen) {
        const conf = chosen.confidence != null ? ` · ${Math.round(chosen.confidence * 100)}%` : "";
        const stale = chosen.stale ? ` · stale (>${maxAge} h)` : "";
        const reason = chosen.match_reason ? ` · ${chosen.match_reason}` : "";
        chosenMeta = `${chosen.store}: ${chosen.name}${conf}${stale}${reason}`;
      }
      return `<tr><td><input aria-label="Producto ${index + 1}" data-index="${index}" data-field="name" value="${attr(line.name)}" required minlength="3" maxlength="300"><small>${attr(trace)}</small><small>${attr(evidence?.text || "")}</small></td>
        <td><input aria-label="Cantidad ${index + 1}" data-index="${index}" data-field="quantity" type="number" min="1" max="10000" value="${line.quantity}" required></td>
        <td><input aria-label="Precio unitario ${index + 1}" data-index="${index}" data-field="unit_price" type="number" min="1" max="1000000000" value="${line.unit_price ?? ""}"></td>
        <td><select aria-label="Unidad ${index + 1}" data-index="${index}" data-field="unit">${["unidad", "pack", "kg", "litro", "metro"].map(unit => `<option ${unit === line.unit ? "selected" : ""}>${unit}</option>`).join("")}</select></td>
        <td><button type="button" data-candidates="${index}">Buscar coincidencias</button><small>${attr(chosenMeta)}</small></td></tr>`;
    }).join("");
  }

  $("quote-candidates").replaceChildren();
  const summary = data.report.summary;
  if (shopping) {
    const basket = (summary.basket || []).map(row => {
      const missing = row.missing_items ? ` · faltan ${row.missing_items}` : "";
      const stale = row.stale_items ? ` · ${row.stale_items} stale` : "";
      const total = row.subtotal != null ? money(row.subtotal) : "—";
      const catalog = row.catalog_subtotal != null && row.catalog_subtotal !== row.subtotal
        ? ` · catálogo ${money(row.catalog_subtotal)}`
        : "";
      const mark = summary.best_store === row.store ? " ← mejor canasta (fresca)" : "";
      return `<li><strong>${attr(row.store)}</strong>: ${total} (${row.usable_items ?? row.matched_items} usable / ${row.matched_items} match)${catalog}${missing}${stale}${mark}</li>`;
    }).join("");
    const hasMatrix = Boolean(activeQuote.store_matches && Object.keys(activeQuote.store_matches).length);
    const searching = summary.searching_cells || countSearchingCells(data);
    $("quote-report").innerHTML = hasMatrix
      ? `<h3>Matriz multi-tienda · ${attr(summary.status_label || STATUS_LABELS[summary.status] || "")}</h3>
      <p class="matrix-legend muted"><span class="legend-dot searching"></span> buscando · <span class="legend-dot no-catalog"></span> sin catálogo · <span class="legend-dot no-match"></span> sin match · <span class="legend-dot stale"></span> stale</p>
      <div class="quote-summary">
        <div><strong>${summary.matched_cells}/${summary.total_cells}</strong>celdas con match</div>
        <div><strong>${attr(summary.best_store || "—")}</strong>mejor tienda canasta</div>
        <div><strong>${money(summary.best_store_subtotal)}</strong>total canasta fresca</div>
        <div><strong>${summary.confirmed_cells || 0}</strong>celdas confirmadas</div>
        <div><strong>${summary.stale_cells || 0}</strong>precios stale (&gt;${summary.price_max_age_hours || 48} h)</div>
        <div><strong>${searching}</strong>celdas buscando</div>
      </div>
      <p>${attr(summary.note)}</p>
      <p class="shipping-note">${attr(summary.shipping_note || "Sin despacho: totales solo productos.")}</p>
      <div class="shopping-basket"><h4>Canasta por tienda (totales usable/frescos)</h4><ul>${basket}</ul></div>
      ${summary.best_store_missing?.length ? `<p class="err">En la mejor tienda faltan: ${attr(summary.best_store_missing.join(", "))}</p>` : ""}`
      : `<h3>Lista guardada · ${attr(STATUS_LABELS[status] || status)}</h3><p>Carrito con ${activeQuote.items?.length || 0} producto(s) y ${(activeQuote.resolved_stores || []).length} tienda(s). Pulsá <strong>Cotizar</strong> para armar la matriz desde Mongo.</p>`;
  } else {
    const reviewBanner = summary.source_review_pending
      ? `<p class="err">Revisión del documento pendiente: marcá el checkbox de revisión antes de considerar la comparación completa.</p>`
      : "";
    $("quote-report").innerHTML = `${reviewBanner}<h3>Comparación revisada · ${attr(summary.status_label || STATUS_LABELS[summary.status] || "")}</h3><div class="quote-summary"><div><strong>${summary.compared_items}/${summary.items}</strong>productos comparables</div><div><strong>${summary.confirmed_items ?? 0}</strong>coincidencias confirmadas</div><div><strong>${money(summary.reference_subtotal)}</strong>referencia comparable</div><div><strong>${money(summary.market_subtotal)}</strong>catálogo comparable</div><div><strong>${money(summary.potential_saving)}</strong>diferencia potencial</div></div><p>${attr(summary.note)}</p><p class="shipping-note">${attr(summary.shipping_note || "Sin despacho: totales solo productos.")}</p><ul>${data.report.rows.filter(row => row.issues?.length).map(row => `<li><strong>${attr(row.item.name)}:</strong> ${attr(row.issues.join(" "))}</li>`).join("")}</ul>`;
  }
  const exportLink = $("quote-export");
  exportLink.href = `/api/quotes/${encodeURIComponent(activeQuote.id)}/export.csv`;
  exportLink.textContent = shopping ? "Exportar matriz CSV" : "Exportar comparación CSV";
  exportLink.onclick = (event) => {
    const searching = summary.searching_cells || countSearchingCells(data);
    const stale = summary.stale_cells || 0;
    const incomplete = !summary.complete;
    const reviewPending = Boolean(summary.source_review_pending);
    const warnings = [];
    if (incomplete) warnings.push("la comparación/canasta no está completa");
    if (stale > 0) warnings.push(`${stale} precio(s) stale`);
    if (searching > 0) warnings.push(`${searching} celda(s) aún buscando`);
    if (reviewPending) warnings.push("falta revisar el documento de origen");
    if (warnings.length) {
      const ok = window.confirm(
        `Exportar con datos incompletos:\n• ${warnings.join("\n• ")}\n\n`
        + "El CSV se descarga igual, pero el estado no pasará a Exportada hasta que esté completo. ¿Continuar?",
      );
      if (!ok) {
        event.preventDefault();
        return;
      }
      quoteMessage("Exportación parcial: se descarga el CSV sin marcar Exportada.", true);
    } else {
      quoteMessage("Exportación solicitada. El estado pasará a Exportada.");
    }
    setTimeout(() => listQuotes().catch(showQuoteError), 500);
  };
  if (summary.extraction_warnings?.length) {
    const warning = document.createElement("p");
    warning.className = "err";
    warning.textContent = `${summary.source_review_pending ? "Revisión del documento pendiente. " : "Avisos de extracción revisados. "}${summary.extraction_warnings.join(" ")}`;
    $("quote-report").prepend(warning);
  }
}

async function openQuote(id) {
  const data = await quoteRequest(`/api/quotes/${encodeURIComponent(id)}`);
  if (data.quote?.mode === "shopping_list") setImportMode("shopping_list");
  else setImportMode("quote");
  renderQuote(data);
}

async function showCandidates(index, store) {
  if (dirtyQuote) { quoteMessage("Guarda las correcciones antes de buscar coincidencias.", true); return; }
  const params = store ? `?store=${encodeURIComponent(store)}` : "";
  const data = await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/candidates/${index}${params}`);
  const box = $("quote-candidates");
  const storeLabel = store ? ` en ${store}` : "";
  box.innerHTML = `<h3>Confirmar: ${attr(activeQuote.items[index].name)}${attr(storeLabel)}</h3><p>Revisa modelo, variante y condiciones antes de confirmar. Match mínimo 80%.</p>`;
  for (const candidate of data.candidates) {
    const card = document.createElement("div");
    card.className = "quote-candidate";
    const ficha = `/producto?${new URLSearchParams({ store: candidate.store, id: candidate.product_id })}`;
    const reason = candidate.match_reason || `coincidencia ${(candidate.confidence * 100).toFixed(0)}%`;
    const maxAge = CATALOG_STALE_HOURS;
    const stale = candidate.stale ? ` · stale (>${maxAge} h)` : "";
    const age = candidate.price_age_hours != null ? ` · ${candidate.price_age_hours} h` : "";
    card.innerHTML = `<strong>${attr(candidate.name)}</strong><p>${attr(candidate.store)} · ${money(candidate.price)} · ${attr(reason)}${attr(stale)}</p><p>${attr(candidate.observed_at ? new Date(candidate.observed_at).toLocaleString("es-CL") : "Fecha desconocida")}${attr(age)}</p><p>${attr((candidate.issues || []).join(" ") || "Precio y cantidad disponibles para comparar.")}</p><p>${attr(candidate.advice?.reason || "")}</p><a href="${attr(ficha)}" target="_blank" rel="noopener">Revisar ficha</a> `;
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.textContent = "Confirmar coincidencia";
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      try {
        const response = await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/selection`, "PUT", {
          index, store: candidate.store, product_id: candidate.product_id, version: activeQuote.version, confirm: true,
        });
        renderQuote(response);
        quoteMessage("Coincidencia confirmada.");
      } catch (error) { showQuoteError(error); confirm.disabled = false; }
    });
    card.append(confirm);
    box.append(card);
  }
  if (!data.candidates.length) {
    box.insertAdjacentHTML(
      "beforeend",
      "<p>No hay coincidencia segura en esa tienda. Probá un <strong>EAN</strong>, un nombre más corto (sin «x 6 un» / pack) o otra marca. Si el producto está en catálogo pero el precio es viejo, usá «Actualizar precios» y regenerá.</p>",
    );
  }
  box.scrollIntoView({ block: "start" });
}

function addToCart(item) {
  const name = String(item.name || "").trim();
  if (name.length < 3) {
    quoteMessage("El nombre del producto es demasiado corto.", true);
    return;
  }
  const existing = cart.items.find(row =>
    (item.store && item.product_id
      ? row.store === item.store && row.product_id === item.product_id
      : row.name.toLowerCase() === name.toLowerCase()
        && (row.brand || "").toLowerCase() === (item.brand || "").toLowerCase())
  );
  if (existing) {
    existing.quantity = (existing.quantity || 1) + (item.quantity || 1);
    if (!existing.has_thumb && item.has_thumb) {
      existing.has_thumb = true;
      existing.store = item.store || existing.store || "";
      existing.product_id = item.product_id || existing.product_id || "";
    }
  } else {
    cart.items.push({
      name,
      quantity: item.quantity || 1,
      unit: item.unit || "unidad",
      brand: item.brand || "",
      gtin: item.gtin || "",
      store: item.store || "",
      product_id: item.product_id || "",
      has_thumb: Boolean(item.has_thumb),
    });
  }
  renderCart();
  quoteMessage(`Agregado: ${name}`);
}

async function searchCatalog(query) {
  const params = new URLSearchParams({ q: query, size: "12", sort: "updated" });
  const response = await fetch(`/api/catalog?${params}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo buscar en el catálogo.");
  }
  return data.items || [];
}

function renderSearchResults(items) {
  const box = $("cart-search-results");
  if (!box) return;
  if (!items.length) {
    box.innerHTML = "<p class='muted'>Sin resultados en el catálogo. Probá otro nombre o importá CSV.</p>";
    return;
  }
  box.replaceChildren();
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "panel deal cart-search-card";
    const price = item.price != null ? money(item.price) : "—";
    const ageHours = catalogPriceAgeHours(item.updated_at);
    const observed = formatObserved(item.updated_at);
    const stale = ageHours != null && ageHours > CATALOG_STALE_HOURS;
    const freshness = observed
      ? `<span class="cart-search-fresh${stale ? " is-stale" : ""}">${stale ? `stale · >${CATALOG_STALE_HOURS} h` : "fresco"} · ${attr(observed)}</span>`
      : "";
    const thumb = typeof thumbMarkup === "function"
      ? thumbMarkup("deal-img cart-search-thumb", catalogThumbUrl(item), { store: item.store, id: item.product_id })
      : "";
    const storeBadge = typeof storeLogo === "function"
      ? storeLogo(item.display_store || item.store, item.store_title || item.store)
      : attr(item.store_title || item.store || "");
    const brand = item.brand ? `<p class="muted cart-search-brand">${attr(item.brand)}</p>` : "";
    card.innerHTML = `${thumb}<div class="deal-body">
      <span class="deal-name">${attr(item.name)}</span>
      ${brand}
      <div class="deal-meta">
        ${storeBadge}
        <span class="cart-search-price"><span class="deal-label">Precio</span>${price}</span>
      </div>
      ${freshness}
      <div class="cart-search-actions"></div>
    </div>`;
    const actions = card.querySelector(".cart-search-actions");
    const qty = document.createElement("input");
    qty.type = "number";
    qty.min = "1";
    qty.max = "10000";
    qty.value = "1";
    qty.className = "cart-search-qty";
    qty.setAttribute("aria-label", `Cantidad ${item.name}`);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cart-search-add";
    btn.textContent = "Agregar";
    btn.addEventListener("click", () => {
      addToCart({
        name: item.name,
        brand: item.brand || "",
        quantity: Number(qty.value) || 1,
        gtin: item.ean || item.gtin || "",
        store: item.store || "",
        product_id: item.product_id || "",
        has_thumb: Boolean(item.has_thumb),
      });
    });
    actions.append(qty, btn);
    box.append(card);
  }
}

$("cart-search")?.addEventListener("submit", async event => {
  event.preventDefault();
  const q = ($("cart-search-q")?.value || "").trim();
  if (q.length < 2) {
    quoteMessage("Escribí al menos 2 caracteres para buscar.", true);
    return;
  }
  const button = event.submitter;
  if (button) button.disabled = true;
  try {
    renderSearchResults(await searchCatalog(q));
    quoteMessage(`Resultados del catálogo para «${q}».`);
  } catch (error) {
    showQuoteError(error);
  } finally {
    if (button) button.disabled = false;
  }
});

$("cart-items")?.addEventListener("click", event => {
  const btn = event.target.closest("[data-cart-remove]");
  if (!btn) return;
  const index = Number(btn.dataset.cartRemove);
  syncCartFromForm();
  cart.items.splice(index, 1);
  renderCart();
});

$("cart-clear")?.addEventListener("click", () => {
  syncCartFromForm();
  cart.items = [];
  renderCart();
  quoteMessage("Carrito vaciado (la lista guardada no cambia hasta que guardes).");
});

$("cart-new")?.addEventListener("click", () => resetCart());

$("cart-stores-all")?.addEventListener("click", () => setAllCategoriesChecked(true));
$("cart-stores-none")?.addEventListener("click", () => setAllCategoriesChecked(false));

$("cart-save")?.addEventListener("click", async () => {
  const button = $("cart-save");
  button.disabled = true;
  try {
    syncCartFromForm();
    if (!selectedStoreGroups().length) throw new Error("Marcá al menos una categoría.");
    const quote = await saveCart();
    await listQuotes();
    quoteMessage(`Lista «${quote.title}» guardada (${quote.items.length} productos).`);
    $("quote-detail").hidden = false;
    $("quote-heading").textContent = `${quote.title} · Lista de compra · ${STATUS_LABELS[quote.status] || "Borrador"}`;
    $("quote-report").innerHTML = `<h3>Lista guardada</h3><p>Carrito con ${quote.items.length} producto(s). Pulsá <strong>Cotizar</strong> para comparar en Mongo.</p>`;
  } catch (error) {
    showQuoteError(error);
  } finally {
    button.disabled = false;
  }
});

$("cart-cotizar")?.addEventListener("click", async () => {
  const button = $("cart-cotizar");
  button.disabled = true;
  try {
    syncCartFromForm();
    if (!cart.items.length) throw new Error("Agrega al menos un producto al carrito.");
    if (!selectedStoreGroups().length) throw new Error("Marcá al menos una categoría.");
    const quote = await saveCart();
    const result = await quoteRequest(`/api/quotes/${encodeURIComponent(quote.id)}/cotizar`, "POST", {
      version: quote.version,
    });
    renderQuote(result);
    await listQuotes();
    const searching = countSearchingCells(result);
    if (searching > 0) {
      quoteMessage(`Cotización desde Mongo. ${searching} celda(s) buscando en tienda (scrape async); se actualizará sola.`);
      startMatrixPoll(result.quote?.id || quote.id);
    } else {
      stopMatrixPoll();
      quoteMessage("Cotización lista desde Mongo. Revisá celdas stale y confirmá matches.");
    }
    $("quote-detail").scrollIntoView({ block: "start" });
  } catch (error) {
    showQuoteError(error);
  } finally {
    button.disabled = false;
  }
});

$("quote-file")?.addEventListener("change", async () => {
  try {
    const file = $("quote-file").files[0];
    documentImport = null;
    if (!file) return;
    if (file.size > 512000) throw new Error("El archivo supera 512 KB.");
    const text = await file.text();
    if (file.name.toLowerCase().endsWith(".json")) {
      documentImport = JSON.parse(text);
      $("quote-csv").value = "";
      $("quote-title").value = documentImport.title || file.name;
      $("quote-supplier").value = documentImport.supplier || "";
      $("quote-tax").checked = documentImport.tax_included === true;
      quoteMessage("Documento convertido cargado. Importa para revisar sus filas.");
    } else {
      $("quote-csv").value = text;
      if (!$("quote-title").value) $("quote-title").value = file.name;
    }
  } catch (error) { showQuoteError(error); }
});

$("shopping-file")?.addEventListener("change", async () => {
  try {
    const file = $("shopping-file").files[0];
    if (!file) return;
    if (file.size > 512000) throw new Error("El archivo supera 512 KB.");
    $("shopping-csv").value = await file.text();
    if (!$("shopping-title").value) $("shopping-title").value = file.name;
  } catch (error) { showQuoteError(error); }
});

$("quote-csv")?.addEventListener("input", () => { documentImport = null; });

$("shopping-import")?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    syncCartFromForm();
    const groups = selectedStoreGroups();
    if (!groups.length) throw new Error("Marcá al menos una categoría antes de importar.");
    const created = await quoteRequest("/api/quotes/import-csv", "POST", {
      title: ($("shopping-title").value || "").trim() || "Lista CSV",
      mode: "shopping_list",
      store_group: primaryStoreGroup(),
      store_groups: groups,
      store_ids: [],
      source_name: $("shopping-file").files[0]?.name || "lista compra.csv",
      text: $("shopping-csv").value,
    });
    await openQuote(created.id);
    await listQuotes();
    quoteMessage("CSV importado y matriz armada desde el catálogo.");
    $("quote-detail").scrollIntoView({ block: "start" });
  } catch (error) { showQuoteError(error); }
  finally { button.disabled = false; }
});

$("quote-import")?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const base = {
      title: $("quote-title").value.trim(),
      supplier: $("quote-supplier").value.trim(),
      tax_included: $("quote-tax").checked ? true : null,
      mode: "quote",
    };
    const created = documentImport
      ? await quoteRequest("/api/quotes", "POST", { ...documentImport, ...base })
      : await quoteRequest("/api/quotes/import-csv", "POST", { ...base, source_name: $("quote-file").files[0]?.name || "lista manual.csv", text: $("quote-csv").value });
    await openQuote(created.id);
    await listQuotes();
    quoteMessage("Importada. Revisa las filas y confirma los productos del catálogo.");
    $("quote-detail").scrollIntoView({ block: "start" });
  } catch (error) { showQuoteError(error); }
  finally { button.disabled = false; }
});

$("quote-edit").addEventListener("input", () => { dirtyQuote = true; });
$("quote-edit").addEventListener("change", () => { dirtyQuote = true; });
$("quote-edit").addEventListener("submit", async event => {
  event.preventDefault();
  event.submitter.disabled = true;
  try {
    const { id, created_at, updated_at, selections, store_matches, resolved_stores, feedback, exported_at, status, ...payload } = activeQuote;
    payload.items = activeQuote.items.map(line => ({ ...line }));
    $("quote-lines").querySelectorAll("[data-field]").forEach(input => {
      const value = input.value.trim();
      payload.items[Number(input.dataset.index)][input.dataset.field] = ["quantity", "unit_price"].includes(input.dataset.field) ? (value ? Number(value) : null) : value;
    });
    if (isShopping(activeQuote)) {
      syncCartFromForm();
      payload.items = cart.items.map(item => ({
        name: item.name,
        quantity: item.quantity ?? 1,
        unit: item.unit || "unidad",
        brand: item.brand || "",
        gtin: item.gtin || "",
        unit_price: null,
        condition: "new",
      }));
      payload.store_ids = [];
      payload.store_group = cart.store_group;
      payload.store_groups = cart.store_groups;
    }
    payload.tax_included = isShopping(activeQuote) ? true : ($("quote-edit-tax").checked ? true : null);
    payload.valid_until = $("quote-valid-until").value || null;
    payload.source_reviewed = $("quote-source-reviewed").checked;
    payload.mode = activeQuote.mode || "quote";
    payload.store_group = payload.store_group || activeQuote.store_group || "";
    payload.store_groups = payload.store_groups || activeQuote.store_groups || [];
    payload.store_ids = payload.store_ids || [];
    renderQuote(await quoteRequest(`/api/quotes/${encodeURIComponent(id)}`, "PUT", payload));
    quoteMessage(isShopping(activeQuote) ? "Lista actualizada y matriz regenerada." : "Correcciones guardadas. Confirma nuevamente las coincidencias.");
  } catch (error) { showQuoteError(error); }
  finally { event.submitter.disabled = false; }
});

$("shopping-rebuild")?.addEventListener("click", async () => {
  if (!activeQuote || !isShopping(activeQuote)) return;
  try {
    const result = await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/rebuild-matrix`, "POST");
    renderQuote(result);
    const searching = countSearchingCells(result);
    if (searching > 0) {
      startMatrixPoll(activeQuote.id);
      quoteMessage(`Matriz regenerada. ${searching} celda(s) buscando en tienda…`);
    } else {
      quoteMessage("Matriz regenerada con el catálogo actual.");
    }
  } catch (error) { showQuoteError(error); }
});

$("quote-refresh-prices")?.addEventListener("click", async () => {
  if (!activeQuote) return;
  try {
    const result = await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/refresh-prices`, "POST");
    let message = result.message || "Prioridad de scrape actualizada.";
    if (isShopping(activeQuote)) {
      const rebuilt = await quoteRequest(
        `/api/quotes/${encodeURIComponent(activeQuote.id)}/rebuild-matrix`,
        "POST",
      );
      renderQuote(rebuilt);
      const searching = countSearchingCells(rebuilt);
      const stale = rebuilt.report?.summary?.stale_cells || 0;
      if (searching > 0 || stale > 0) startMatrixPoll(activeQuote.id);
      message = `${message} Matriz regenerada${stale ? ` · ${stale} stale` : ""}${searching ? ` · ${searching} buscando` : ""}.`;
    }
    quoteMessage(message);
  } catch (error) {
    showQuoteError(error);
  }
});

$("quote-lines").addEventListener("click", async event => {
  const button = event.target.closest("[data-candidates]");
  if (!button || !activeQuote) return;
  button.disabled = true;
  try { await showCandidates(Number(button.dataset.candidates)); }
  catch (error) { showQuoteError(error); }
  finally { button.disabled = false; }
});

$("shopping-matrix-wrap")?.addEventListener("click", async event => {
  const button = event.target.closest("[data-matrix-index]");
  if (!button || !activeQuote) return;
  try { await showCandidates(Number(button.dataset.matrixIndex), button.dataset.matrixStore); }
  catch (error) { showQuoteError(error); }
});

document.querySelectorAll("[data-feedback]").forEach(button => button.addEventListener("click", async () => {
  if (!activeQuote) return;
  try { await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/feedback`, "POST", { kind: button.dataset.feedback }); quoteMessage("Gracias. Tu evaluación quedó guardada para mejorar el comparador."); }
  catch (error) { showQuoteError(error); }
}));

ensureUser().then(async user => {
  if (!user || user.role !== "admin") {
    location.href = "/entrar?next=/cotizaciones";
    return;
  }
  setImportMode("shopping_list");
  await loadStoreGroups().catch(showQuoteError);
  renderCart();
  quoteRequest("/api/admin/purchasing-metrics").then(metrics => {
    $("quote-pilot-metrics").hidden = false;
    $("quote-pilot-metrics").textContent = `Piloto: ${metrics.imports} importaciones · ${metrics.matches} matches · ${metrics.exports} exportaciones · ${metrics.errors} errores · ahorro potencial exportado ${money(metrics.potential_saving_exported || 0)} · ${metrics.useful_quotes} útiles · ${metrics.needs_correction_quotes} necesitan corrección. ${metrics.note}`;
  }).catch(showQuoteError);
  return listQuotes().then(() => quoteMessage("Armá el carrito, elegí tiendas y pulsá Cotizar (solo Mongo)."));
}).catch(showQuoteError);

let doclingJobId = null;

function showDoclingStatus(job) {
  const labels = {
    queued: "En cola",
    processing: "Convirtiendo…",
    done: "Listo",
    failed: "Falló",
    needs_docling: "Requiere Docling (Soyo/scraping)",
    retry: "Reintento",
  };
  const help = $("quote-docling-help");
  const cmd = $("quote-docling-cmd");
  const needsHelp = job.status === "needs_docling" || job.status === "failed";
  if (help) help.hidden = !needsHelp;
  if (cmd && needsHelp) {
    const source = job.source_name || job.source_path || "documento.pdf";
    const title = JSON.stringify(job.title || "Cotización");
    cmd.textContent = [
      "python scripts/convert_quote_document.py \\",
      `  ${source} \\`,
      "  --output result.json \\",
      `  --title ${title}`,
      "",
      "# Luego: Cargar JSON resultante aquí, o importá CSV en la pestaña Cotización.",
    ].join("\n");
  }
  let detail = labels[job.status] || job.status;
  if (job.last_error) detail += ` · ${job.last_error}`;
  if (job.status === "failed") {
    detail += " · Revisá el archivo o usá CSV.";
  }
  $("quote-docling-status").textContent = detail;
  $("quote-docling-actions").hidden = false;
  $("quote-docling-import").disabled = job.status !== "done";
}

$("quote-docling")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("quote-pdf").files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  body.append("title", $("quote-title").value.trim() || file.name);
  body.append("supplier", $("quote-supplier").value.trim());
  if ($("quote-tax").checked) body.append("tax_included", "true");
  try {
    const response = await fetch("/api/quotes/convert-jobs", { method: "POST", body });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo encolar.");
    doclingJobId = data.id;
    showDoclingStatus(data);
    startDoclingPoll(doclingJobId);
    quoteMessage("Conversión encolada. Se actualiza sola; también podés refrescar o correr el worker Docling.");
  } catch (error) {
    showQuoteError(error);
  }
});

$("quote-docling-refresh")?.addEventListener("click", async () => {
  if (!doclingJobId) return;
  try {
    const job = await quoteRequest(`/api/quotes/convert-jobs/${encodeURIComponent(doclingJobId)}`);
    showDoclingStatus(job);
    if (!["done", "failed", "needs_docling"].includes(job.status)) {
      startDoclingPoll(doclingJobId);
    }
  } catch (error) {
    showQuoteError(error);
  }
});

$("quote-docling-import")?.addEventListener("click", async () => {
  if (!doclingJobId) return;
  try {
    const created = await quoteRequest(`/api/quotes/convert-jobs/${encodeURIComponent(doclingJobId)}/import`, "POST");
    await openQuote(created.id);
    await listQuotes();
    quoteMessage("JSON Docling cargado como cotización revisable.");
  } catch (error) {
    showQuoteError(error);
  }
});

let activeQuote = null;
let dirtyQuote = false;
let documentImport = null;
let importMode = "shopping_list";
let storeGroups = [];

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

async function loadStoreGroups() {
  const data = await quoteRequest("/api/quotes/store-groups");
  storeGroups = data.groups || [];
  const select = $("shopping-group");
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Elige una categoría";
  select.append(placeholder);
  for (const group of storeGroups) {
    const option = document.createElement("option");
    option.value = group.id;
    option.textContent = `${group.title} (${group.store_ids.join(", ")})`;
    if (group.id === "supermercados") option.selected = true;
    select.append(option);
  }
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

function renderMatrix(data) {
  const stores = data.report.stores || data.report.summary.stores || [];
  const wrap = $("shopping-matrix-wrap");
  const head = ["Producto", "Cant.", ...stores, "Mejor"];
  let html = `<table class="shopping-matrix"><thead><tr>${head.map(h => `<th>${attr(h)}</th>`).join("")}</tr></thead><tbody>`;
  for (const row of data.report.rows) {
    const item = row.item;
    html += `<tr><td>${attr(item.name)}${item.brand ? `<small>${attr(item.brand)}</small>` : ""}</td><td>${item.quantity}</td>`;
    for (const store of stores) {
      const cell = row.cells[store] || {};
      if (!cell.matched) {
        html += `<td class="matrix-empty"><button type="button" class="matrix-cell-btn" data-matrix-index="${row.index}" data-matrix-store="${attr(store)}">${attr(cell.label || "sin stock o sin match")}</button></td>`;
        continue;
      }
      const conf = cell.confidence != null ? `${Math.round(cell.confidence * 100)}%` : "";
      html += `<td><button type="button" class="matrix-cell-btn" data-matrix-index="${row.index}" data-matrix-store="${attr(store)}">
        <span class="matrix-price">${money(cell.price)}</span>
        <span class="matrix-meta">${attr(cell.name || "")}</span>
        <span class="matrix-meta">confianza ${attr(conf)}${cell.confirmed ? " · confirmada" : " · sugerida"}</span>
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
  $("quote-save-btn").textContent = shopping ? "Guardar nombres / cantidades" : "Guardar correcciones";

  if (shopping) {
    $("quote-lines").innerHTML = activeQuote.items.map((line, index) =>
      `<tr><td><input aria-label="Producto ${index + 1}" data-index="${index}" data-field="name" value="${attr(line.name)}" required minlength="3" maxlength="300"></td>
      <td><input aria-label="Cantidad ${index + 1}" data-index="${index}" data-field="quantity" type="number" min="1" max="10000" value="${line.quantity}" required></td>
      <td colspan="3"><small>Marca: ${attr(line.brand || "—")}</small></td></tr>`
    ).join("");
    renderMatrix(data);
  } else {
    $("shopping-matrix-wrap").hidden = true;
    $("shopping-matrix-wrap").replaceChildren();
    $("quote-lines").innerHTML = activeQuote.items.map((line, index) => {
      const evidence = line.evidence;
      const trace = evidence ? `${evidence.source || activeQuote.source_name} · fila ${evidence.row}${evidence.page ? ` · página ${evidence.page}` : ""}` : "Datos ingresados manualmente";
      const chosen = data.report.rows[index]?.selected;
      return `<tr><td><input aria-label="Producto ${index + 1}" data-index="${index}" data-field="name" value="${attr(line.name)}" required minlength="3" maxlength="300"><small>${attr(trace)}</small><small>${attr(evidence?.text || "")}</small></td>
        <td><input aria-label="Cantidad ${index + 1}" data-index="${index}" data-field="quantity" type="number" min="1" max="10000" value="${line.quantity}" required></td>
        <td><input aria-label="Precio unitario ${index + 1}" data-index="${index}" data-field="unit_price" type="number" min="1" max="1000000000" value="${line.unit_price ?? ""}"></td>
        <td><select aria-label="Unidad ${index + 1}" data-index="${index}" data-field="unit">${["unidad", "pack", "kg", "litro", "metro"].map(unit => `<option ${unit === line.unit ? "selected" : ""}>${unit}</option>`).join("")}</select></td>
        <td><button type="button" data-candidates="${index}">Buscar coincidencias</button><small>${chosen ? attr(`${chosen.store}: ${chosen.name}`) : "Pendiente de confirmación"}</small></td></tr>`;
    }).join("");
  }

  $("quote-candidates").replaceChildren();
  const summary = data.report.summary;
  if (shopping) {
    const basket = (summary.basket || []).map(row => {
      const missing = row.missing_items ? ` · faltan ${row.missing_items}` : "";
      const total = row.subtotal != null ? money(row.subtotal) : "—";
      const mark = summary.best_store === row.store ? " ← mejor canasta" : "";
      return `<li><strong>${attr(row.store)}</strong>: ${total} (${row.matched_items} ítems)${missing}${mark}</li>`;
    }).join("");
    $("quote-report").innerHTML = `<h3>Matriz multi-tienda · ${attr(summary.status_label || STATUS_LABELS[summary.status] || "")}</h3>
      <div class="quote-summary">
        <div><strong>${summary.matched_cells}/${summary.total_cells}</strong>celdas con match</div>
        <div><strong>${attr(summary.best_store || "—")}</strong>mejor tienda canasta</div>
        <div><strong>${money(summary.best_store_subtotal)}</strong>total canasta</div>
        <div><strong>${summary.confirmed_cells || 0}</strong>celdas confirmadas</div>
      </div>
      <p>${attr(summary.note)}</p>
      <div class="shopping-basket"><h4>Canasta por tienda</h4><ul>${basket}</ul></div>
      ${summary.best_store_missing?.length ? `<p class="err">En la mejor tienda faltan: ${attr(summary.best_store_missing.join(", "))}</p>` : ""}`;
  } else {
    $("quote-report").innerHTML = `<h3>Comparación revisada · ${attr(summary.status_label || STATUS_LABELS[summary.status] || "")}</h3><div class="quote-summary"><div><strong>${summary.compared_items}/${summary.items}</strong>productos comparables</div><div><strong>${summary.confirmed_items ?? 0}</strong>coincidencias confirmadas</div><div><strong>${money(summary.reference_subtotal)}</strong>referencia comparable</div><div><strong>${money(summary.market_subtotal)}</strong>catálogo comparable</div><div><strong>${money(summary.potential_saving)}</strong>diferencia potencial</div></div><p>${attr(summary.note)}</p><ul>${data.report.rows.filter(row => row.issues?.length).map(row => `<li><strong>${attr(row.item.name)}:</strong> ${attr(row.issues.join(" "))}</li>`).join("")}</ul>`;
  }
  $("quote-export").href = `/api/quotes/${encodeURIComponent(activeQuote.id)}/export.csv`;
  $("quote-export").textContent = shopping ? "Exportar matriz CSV" : "Exportar comparación CSV";
  $("quote-export").onclick = () => {
    quoteMessage("Exportación solicitada. El estado pasará a Exportada si la comparación está completa.");
    setTimeout(() => listQuotes().catch(showQuoteError), 500);
  };
  if (summary.extraction_warnings?.length) {
    const warning = document.createElement("p");
    warning.className = "err";
    warning.textContent = `${summary.source_review_pending ? "Revisión del documento pendiente. " : "Avisos de extracción revisados. "}${summary.extraction_warnings.join(" ")}`;
    $("quote-report").prepend(warning);
  }
}

async function openQuote(id) { renderQuote(await quoteRequest(`/api/quotes/${encodeURIComponent(id)}`)); }

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
    card.innerHTML = `<strong>${attr(candidate.name)}</strong><p>${attr(candidate.store)} · ${money(candidate.price)} · coincidencia ${(candidate.confidence * 100).toFixed(0)}%</p><p>${attr(candidate.observed_at ? new Date(candidate.observed_at).toLocaleString("es-CL") : "Fecha desconocida")}</p><p>${attr(candidate.issues.join(" ") || "Precio y cantidad disponibles para comparar.")}</p><p>${attr(candidate.advice.reason)}</p><a href="${attr(ficha)}" target="_blank" rel="noopener">Revisar ficha</a> `;
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
  if (!data.candidates.length) box.insertAdjacentHTML("beforeend", "<p>No encontramos una coincidencia suficientemente segura en esa tienda. Revisa el nombre.</p>");
  box.scrollIntoView({ block: "start" });
}

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
    const group = $("shopping-group").value;
    if (!group) throw new Error("Elige una categoría de tiendas.");
    const created = await quoteRequest("/api/quotes/import-csv", "POST", {
      title: $("shopping-title").value.trim(),
      mode: "shopping_list",
      store_group: group,
      source_name: $("shopping-file").files[0]?.name || "lista compra.csv",
      text: $("shopping-csv").value,
    });
    await openQuote(created.id);
    await listQuotes();
    quoteMessage("Lista importada. Matriz armada desde el catálogo; confirma celdas dudosas.");
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
    payload.tax_included = isShopping(activeQuote) ? true : ($("quote-edit-tax").checked ? true : null);
    payload.valid_until = $("quote-valid-until").value || null;
    payload.source_reviewed = $("quote-source-reviewed").checked;
    payload.mode = activeQuote.mode || "quote";
    payload.store_group = activeQuote.store_group || "";
    payload.store_ids = activeQuote.store_ids || [];
    renderQuote(await quoteRequest(`/api/quotes/${encodeURIComponent(id)}`, "PUT", payload));
    quoteMessage(isShopping(activeQuote) ? "Lista actualizada y matriz regenerada." : "Correcciones guardadas. Confirma nuevamente las coincidencias.");
  } catch (error) { showQuoteError(error); }
  finally { event.submitter.disabled = false; }
});

$("shopping-rebuild")?.addEventListener("click", async () => {
  if (!activeQuote || !isShopping(activeQuote)) return;
  try {
    renderQuote(await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/rebuild-matrix`, "POST"));
    quoteMessage("Matriz regenerada con el catálogo actual.");
  } catch (error) { showQuoteError(error); }
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
  quoteRequest("/api/admin/purchasing-metrics").then(metrics => {
    $("quote-pilot-metrics").hidden = false;
    $("quote-pilot-metrics").textContent = `Piloto: ${metrics.imports} importaciones · ${metrics.matches} matches · ${metrics.exports} exportaciones · ${metrics.errors} errores · ahorro potencial exportado ${money(metrics.potential_saving_exported || 0)} · ${metrics.useful_quotes} útiles · ${metrics.needs_correction_quotes} necesitan corrección. ${metrics.note}`;
  }).catch(showQuoteError);
  return listQuotes().then(() => quoteMessage("Elige Lista de compra o Cotización con precios de referencia."));
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
  $("quote-docling-status").textContent = `${labels[job.status] || job.status}${job.last_error ? ` · ${job.last_error}` : ""}`;
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
    quoteMessage("Conversión encolada. Actualiza el estado o corre el worker Docling en Soyo.");
  } catch (error) {
    showQuoteError(error);
  }
});

$("quote-docling-refresh")?.addEventListener("click", async () => {
  if (!doclingJobId) return;
  try {
    showDoclingStatus(await quoteRequest(`/api/quotes/convert-jobs/${encodeURIComponent(doclingJobId)}`));
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

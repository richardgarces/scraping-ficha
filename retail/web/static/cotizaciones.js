let activeQuote = null;
let dirtyQuote = false;
let documentImport = null;

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

async function listQuotes() {
  const data = await quoteRequest("/api/quotes");
  $("quote-list").replaceChildren();
  for (const quote of data.quotes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quote-list-item";
    const status = STATUS_LABELS[quote.status] || quote.status || "Borrador";
    button.innerHTML = `<span>${attr(quote.title)}</span><small class="quote-status-pill" data-status="${attr(quote.status || "draft")}">${attr(status)}</small>`;
    button.addEventListener("click", () => openQuote(quote.id).catch(showQuoteError));
    $("quote-list").append(button);
  }
  if (!data.quotes.length) $("quote-list").textContent = "Todavía no tienes cotizaciones.";
}

function showQuoteError(error) { quoteMessage(error.message, true); }

function renderQuote(data) {
  activeQuote = data.quote;
  dirtyQuote = false;
  $("quote-detail").hidden = false;
  const status = data.report.summary.status || activeQuote.status || "draft";
  $("quote-heading").textContent = `${activeQuote.title} · ${STATUS_LABELS[status] || status}`;
  $("quote-valid-until").value = activeQuote.valid_until || "";
  $("quote-edit-tax").checked = activeQuote.tax_included === true;
  $("quote-source-reviewed").checked = activeQuote.source_reviewed === true;
  $("quote-lines").innerHTML = activeQuote.items.map((line, index) => {
    const evidence = line.evidence;
    const trace = evidence ? `${evidence.source || activeQuote.source_name} · fila ${evidence.row}${evidence.page ? ` · página ${evidence.page}` : ""}` : "Datos ingresados manualmente";
    const chosen = data.report.rows[index].selected;
    return `<tr><td><input aria-label="Producto ${index + 1}" data-index="${index}" data-field="name" value="${attr(line.name)}" required minlength="3" maxlength="300"><small>${attr(trace)}</small><small>${attr(evidence?.text || "")}</small></td>
      <td><input aria-label="Cantidad ${index + 1}" data-index="${index}" data-field="quantity" type="number" min="1" max="10000" value="${line.quantity}" required></td>
      <td><input aria-label="Precio unitario ${index + 1}" data-index="${index}" data-field="unit_price" type="number" min="1" max="1000000000" value="${line.unit_price ?? ""}"></td>
      <td><select aria-label="Unidad ${index + 1}" data-index="${index}" data-field="unit">${["unidad", "pack", "kg", "litro", "metro"].map(unit => `<option ${unit === line.unit ? "selected" : ""}>${unit}</option>`).join("")}</select></td>
      <td><button type="button" data-candidates="${index}">Buscar coincidencias</button><small>${chosen ? attr(`${chosen.store}: ${chosen.name}`) : "Pendiente de confirmación"}</small></td></tr>`;
  }).join("");
  $("quote-candidates").replaceChildren();
  const summary = data.report.summary;
  $("quote-report").innerHTML = `<h3>Comparación revisada · ${attr(summary.status_label || STATUS_LABELS[summary.status] || "")}</h3><div class="quote-summary"><div><strong>${summary.compared_items}/${summary.items}</strong>productos comparables</div><div><strong>${summary.confirmed_items ?? 0}</strong>coincidencias confirmadas</div><div><strong>${money(summary.reference_subtotal)}</strong>referencia comparable</div><div><strong>${money(summary.market_subtotal)}</strong>catálogo comparable</div><div><strong>${money(summary.potential_saving)}</strong>diferencia potencial</div></div><p>${attr(summary.note)}</p><ul>${data.report.rows.filter(row => row.issues.length).map(row => `<li><strong>${attr(row.item.name)}:</strong> ${attr(row.issues.join(" "))}</li>`).join("")}</ul>`;
  $("quote-export").href = `/api/quotes/${encodeURIComponent(activeQuote.id)}/export.csv`;
  $("quote-export").onclick = () => {
    quoteMessage("Exportación solicitada. El estado pasará a Exportada si la comparación está completa.");
    setTimeout(() => listQuotes().catch(showQuoteError), 500);
  };
  if (summary.extraction_warnings.length) {
    const warning = document.createElement("p");
    warning.className = "err";
    warning.textContent = `${summary.source_review_pending ? "Revisión del documento pendiente. " : "Avisos de extracción revisados. "}${summary.extraction_warnings.join(" ")}`;
    $("quote-report").prepend(warning);
  }
}

async function openQuote(id) { renderQuote(await quoteRequest(`/api/quotes/${encodeURIComponent(id)}`)); }

$("quote-file").addEventListener("change", async () => {
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

$("quote-csv").addEventListener("input", () => { documentImport = null; });
$("quote-import").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const base = { title: $("quote-title").value.trim(), supplier: $("quote-supplier").value.trim(), tax_included: $("quote-tax").checked ? true : null };
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
    const { id, created_at, updated_at, selections, feedback, ...payload } = activeQuote;
    payload.items = activeQuote.items.map(line => ({ ...line }));
    $("quote-lines").querySelectorAll("[data-field]").forEach(input => {
      const value = input.value.trim();
      payload.items[Number(input.dataset.index)][input.dataset.field] = ["quantity", "unit_price"].includes(input.dataset.field) ? (value ? Number(value) : null) : value;
    });
    payload.tax_included = $("quote-edit-tax").checked ? true : null;
    payload.valid_until = $("quote-valid-until").value || null;
    payload.source_reviewed = $("quote-source-reviewed").checked;
    renderQuote(await quoteRequest(`/api/quotes/${encodeURIComponent(id)}`, "PUT", payload));
    quoteMessage("Correcciones guardadas. Confirma nuevamente las coincidencias.");
  } catch (error) { showQuoteError(error); }
  finally { event.submitter.disabled = false; }
});

$("quote-lines").addEventListener("click", async event => {
  const button = event.target.closest("[data-candidates]");
  if (!button || !activeQuote) return;
  if (dirtyQuote) { quoteMessage("Guarda las correcciones antes de buscar coincidencias.", true); return; }
  button.disabled = true;
  try {
    const index = Number(button.dataset.candidates);
    const data = await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/candidates/${index}`);
    const box = $("quote-candidates");
    box.innerHTML = `<h3>Confirmar: ${attr(activeQuote.items[index].name)}</h3><p>Revisa modelo, variante y condiciones antes de confirmar.</p>`;
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
          const response = await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/selection`, "PUT", { index, store: candidate.store, product_id: candidate.product_id, version: activeQuote.version });
          renderQuote(response);
          quoteMessage("Coincidencia confirmada. La comparación muestra cualquier condición pendiente.");
        } catch (error) { showQuoteError(error); confirm.disabled = false; }
      });
      card.append(confirm);
      box.append(card);
    }
    if (!data.candidates.length) box.insertAdjacentHTML("beforeend", "<p>No encontramos una coincidencia suficientemente segura. Revisa el nombre y sus especificaciones.</p>");
    box.scrollIntoView({ block: "start" });
  } catch (error) { showQuoteError(error); }
  finally { button.disabled = false; }
});

document.querySelectorAll("[data-feedback]").forEach(button => button.addEventListener("click", async () => {
  if (!activeQuote) return;
  try { await quoteRequest(`/api/quotes/${encodeURIComponent(activeQuote.id)}/feedback`, "POST", { kind: button.dataset.feedback }); quoteMessage("Gracias. Tu evaluación quedó guardada para mejorar el comparador."); }
  catch (error) { showQuoteError(error); }
}));

ensureUser().then(user => {
  if (!user || user.role !== "admin") {
    location.href = "/entrar?next=/cotizaciones";
    return;
  }
  quoteRequest("/api/admin/purchasing-metrics").then(metrics => {
    $("quote-pilot-metrics").hidden = false;
    $("quote-pilot-metrics").textContent = `Piloto: ${metrics.imports} importaciones · ${metrics.matches} matches · ${metrics.exports} exportaciones · ${metrics.errors} errores · ahorro potencial exportado ${money(metrics.potential_saving_exported || 0)} · ${metrics.useful_quotes} útiles · ${metrics.needs_correction_quotes} necesitan corrección. ${metrics.note}`;
  }).catch(showQuoteError);
  return listQuotes().then(() => quoteMessage("Importa una lista o abre una cotización guardada."));
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

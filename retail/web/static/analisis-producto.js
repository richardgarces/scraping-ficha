(() => {
  const form = document.getElementById("analysis-form");
  const query = document.getElementById("analysis-query");
  const submit = document.getElementById("analysis-submit");
  const status = document.getElementById("analysis-status");
  const error = document.getElementById("analysis-error");
  const summary = document.getElementById("analysis-summary");
  const results = document.getElementById("analysis-results");
  const entityActions = document.getElementById("entity-actions");
  let currentUser = null;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function money(value) {
    if (value == null) return "No informado";
    return new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(value);
  }

  function stamp(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("es-CL", { timeZone: "America/Santiago" });
  }

  function safeUrl(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_reason) {
      return "";
    }
  }

  function offerRow(offer) {
    const isAdmin = currentUser?.role === "admin";
    const name = escapeHtml(offer.name || "Producto");
    const url = safeUrl(offer.url);
    const product = url
      ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${name}</a>`
      : name;
    const source = offer.checked_live ? "Consulta en vivo" : "Último dato guardado";
    const quantityClass = offer.quantity_kind === "exact" && offer.quantity === 0 ? "fake" : "ghost";
    const condition = ({ new: "Nuevo", refurbished: "Reacondicionado", open_box: "Caja abierta", display: "Exhibición", used: "Usado" })[offer.condition] || "No informada";
    const payment = offer.price_card ? `${money(offer.price_card)} con ${escapeHtml(offer.payment_card_name || "tarjeta de la tienda")}` : "—";
    const shipping = offer.shipping_cost === 0 ? "Gratis" : offer.shipping_cost != null ? money(offer.shipping_cost) : "Por confirmar";
    const confidence = offer.entity_confidence == null ? "Sin evaluar" : `${Math.round(Number(offer.entity_confidence) * 100)}%`;
    const selection = isAdmin
      ? `<input class="entity-product" type="checkbox" data-store="${escapeHtml(offer.store)}" data-id="${escapeHtml(offer.product_id)}" aria-label="Seleccionar ${name}">`
      : "";
    const adminCells = isAdmin ? `
      <td>${shipping}</td>
      <td><span class="badge ${quantityClass}">${escapeHtml(offer.quantity_label)}</span></td>
      <td>${escapeHtml(availabilityLabel(offer.availability, offer.quantity))}</td>
      <td class="muted">${source}</td>
      <td>${escapeHtml(confidence)}<br><span class="muted">${escapeHtml(offer.entity_match_method || "automático")}</span></td>` : "";
    return `<tr>
      ${isAdmin ? `<td>${selection}</td>` : ""}
      <td><strong>${escapeHtml(offer.store_title)}</strong></td>
      <td>${product}<br><span class="muted">${escapeHtml(offer.sku_id || offer.product_id || "")}</span></td>
      <td class="price">${money(offer.price)}</td>
      <td>${escapeHtml(condition)}</td>
      <td>${payment}</td>
      ${adminCells}
    </tr>`;
  }

  function render(data) {
    const groups = Array.isArray(data.groups) ? data.groups : [];
    summary.hidden = false;
    const adminQuantity = currentUser?.role === "admin"
      ? `<article class="stat-card"><span>Cantidad exacta</span><strong>${Number(data.exact_quantity_count || 0).toLocaleString("es-CL")}</strong></article>`
      : "";
    const adminHeaders = currentUser?.role === "admin"
      ? "<th>Despacho</th><th>Cantidad</th><th>Estado</th><th>Origen</th><th>Coincidencia</th>"
      : "";
    summary.innerHTML = `<h2>Resultado</h2>
      <div class="stat-cards">
        <article class="stat-card"><span>Tiendas encontradas</span><strong>${Number(data.store_count || 0).toLocaleString("es-CL")}</strong></article>
        <article class="stat-card"><span>Publicaciones</span><strong>${Number(data.offer_count || 0).toLocaleString("es-CL")}</strong></article>
        ${adminQuantity}
      </div>
      <p class="muted">Generado ${escapeHtml(stamp(data.generated_at))}. Cada bloque representa un producto comparable; variantes distintas se mantienen separadas.</p>`;
    if (!groups.length) {
      results.innerHTML = '<section class="panel"><p class="muted">No se encontraron publicaciones comparables para este producto.</p></section>';
      return;
    }
    results.innerHTML = groups.map((group) => `<section class="panel analysis-group">
      <div class="cron-head"><div><h2>${escapeHtml(group.name)}</h2><p class="muted">${group.store_count} tienda${group.store_count === 1 ? "" : "s"}</p></div></div>
      <div class="table-wrap"><table class="results">
        <thead><tr>${currentUser?.role === "admin" ? "<th></th>" : ""}<th>Tienda</th><th>Producto</th><th>Todo medio</th><th>Condición</th><th>Precio tarjeta</th>${adminHeaders}</tr></thead>
        <tbody>${group.offers.map(offerRow).join("")}</tbody>
      </table></div>
    </section>`).join("");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    currentUser = await ensureUser();
    entityActions.hidden = currentUser?.role !== "admin";
    const live = currentUser?.role === "admin" && document.getElementById("analysis-live").checked;
    error.hidden = true;
    summary.hidden = true;
    results.innerHTML = "";
    submit.disabled = true;
    submit.textContent = "Analizando…";
    status.textContent = live
      ? "Consultando. Esto puede tardar algunos segundos…"
      : "Buscando en los datos guardados…";
    try {
      const response = await fetch("/api/product-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.value, live }),
      });
      const data = await response.json().catch(() => ({}));
      if (response.status === 401 || response.status === 403) {
        location.href = `/entrar?next=${encodeURIComponent(location.pathname)}`;
        return;
      }
      if (!response.ok) throw new Error(data.detail || "No se pudo realizar el análisis.");
      render(data);
      status.textContent = `Análisis terminado: ${data.store_count || 0} tiendas encontradas.`;
    } catch (reason) {
      error.hidden = false;
      error.textContent = reason.message || "No se pudo realizar el análisis.";
      status.textContent = "";
    } finally {
      submit.disabled = false;
      submit.textContent = "Analizar ahora";
    }
  });

  async function changeEntities(action) {
    const products = [...document.querySelectorAll(".entity-product:checked")].map((input) => ({
      store: input.dataset.store,
      product_id: input.dataset.id,
    }));
    if ((action === "merge" && products.length < 2) || !products.length) {
      error.hidden = false;
      error.textContent = action === "merge" ? "Selecciona al menos dos publicaciones." : "Selecciona al menos una publicación.";
      return;
    }
    const response = await fetch("/api/admin/entity-overrides", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, products }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      error.hidden = false;
      error.textContent = data.detail || "No se pudo guardar la corrección.";
      return;
    }
    error.hidden = true;
    status.textContent = action === "merge"
      ? "Productos unidos. Vuelve a analizar para ver la comparación actualizada."
      : action === "split"
        ? "Productos separados. Vuelve a analizar para actualizar los grupos."
        : "Los productos volverán a usar la detección automática.";
  }

  document.getElementById("entity-merge").addEventListener("click", () => changeEntities("merge"));
  document.getElementById("entity-split").addEventListener("click", () => changeEntities("split"));
  document.getElementById("entity-reset").addEventListener("click", () => changeEntities("reset"));
})();

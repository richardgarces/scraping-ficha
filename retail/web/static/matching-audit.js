(() => {
  const $ = (id) => document.getElementById(id);
  const LABELS = [
    ["exact", "Exacta"],
    ["variant", "Variante"],
    ["not_equivalent", "No equivalente"],
    ["uncertain", "Incierta"],
  ];
  const labelNames = Object.fromEntries(LABELS);
  let runId = "";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString("es-CL", { timeZone: "America/Santiago" });
  }

  function formatPercent(value) {
    return value == null ? "No verificado" : `${(Number(value) * 100).toFixed(1)}%`;
  }

  function formatKappa(value) {
    return value == null ? "No calculable" : Number(value).toFixed(3);
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      const next = encodeURIComponent(`${location.pathname}${location.search}`);
      location.href = `/entrar?next=${next}`;
      throw new Error("Entra con la cuenta de administrador.");
    }
    if (!response.ok) {
      throw new Error(payload.detail || response.statusText || "No se pudo completar la solicitud.");
    }
    return payload;
  }

  function flash(message, error = false) {
    const status = $("audit-status");
    status.textContent = message;
    status.className = error ? "err" : "summary";
  }

  function renderMetrics(data) {
    const { run, metrics } = data;
    $("audit-metrics").innerHTML = `
      <p>Estado: <strong>${escapeHtml(run.status)}</strong> · ${Number(run.sampled_search_count || 0)} búsquedas · ${Number(run.comparison_count || 0)} comparaciones · creada ${formatDate(run.created_at)}</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Métrica</th><th>Valor</th><th>Base</th></tr></thead>
        <tbody>
          <tr><td>Matching exacto</td><td>${formatPercent(metrics.precision_exact)}</td><td>${metrics.exact_count}/${metrics.precision_denominator} etiquetas finales concluyentes</td></tr>
          <tr><td>Kappa de Cohen</td><td>${formatKappa(metrics.cohen_kappa)}</td><td>${metrics.kappa_denominator} dobles revisiones; ${metrics.kappa_reviewer_pair_count} pares de revisores</td></tr>
          <tr><td>Resueltas</td><td>${metrics.resolved_count}</td><td>${metrics.comparison_count} comparaciones</td></tr>
          <tr><td>Inciertas</td><td>${metrics.uncertain_count}</td><td>Excluidas de la precisión exacta</td></tr>
          <tr><td>Desacuerdos pendientes</td><td>${metrics.disagreement_count}</td><td>Requieren tercera persona</td></tr>
        </tbody>
      </table></div>`;
  }

  function renderOffer(item) {
    const offer = item.offer || {};
    const safeUrl = /^https?:\/\//i.test(offer.url || "") ? offer.url : "";
    const price = offer.price_all_payment ?? "No verificado";
    const cardPrice = offer.price_card ?? "No verificado";
    return `
      <p><strong>Producto:</strong> ${escapeHtml(offer.name || "Sin nombre")} · ${escapeHtml(item.store)}</p>
      <p><strong>Precio sin tarjeta:</strong> ${escapeHtml(price)} · <strong>Con tarjeta:</strong> ${escapeHtml(cardPrice)}</p>
      <p><strong>Condiciones:</strong> ${escapeHtml(offer.payment_conditions || "No verificadas")} · <strong>Despacho:</strong> ${escapeHtml(offer.shipping_cost ?? "No verificado")}</p>
      <p><strong>Última actualización guardada:</strong> ${formatDate(offer.updated_at)} · <strong>Frecuencia:</strong> ${Number(item.frequency_count_30d || 0)} (${escapeHtml(item.frequency_bucket || "—")})</p>
      ${safeUrl ? `<p><a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">Abrir ficha de tienda</a></p>` : ""}`;
  }

  function renderQueue(items) {
    const root = $("audit-queue");
    if (!items.length) {
      root.innerHTML = '<p class="muted">No quedan comparaciones para tu revisión en esta corrida.</p>';
      return;
    }
    root.innerHTML = items.map((item) => `
      <article class="panel" data-item="${escapeHtml(item.id)}">
        <p><strong>Búsqueda:</strong> ${escapeHtml(item.query)}</p>
        <p><strong>Categoría/tienda:</strong> ${escapeHtml(item.category)} · ${escapeHtml(item.store)} · posición ${Number(item.position || 0)}</p>
        ${renderOffer(item)}
        <label>Nota opcional <textarea data-note maxlength="500" rows="2"></textarea></label>
        <div class="analysis-search">
          ${LABELS.map(([value, text]) => `<button type="button" data-label="${value}">${text}</button>`).join("")}
        </div>
      </article>`).join("");
  }

  function renderArbitration(items) {
    const root = $("audit-arbitration");
    if (!items.length) {
      root.innerHTML = '<p class="muted">No hay desacuerdos pendientes.</p>';
      return;
    }
    root.innerHTML = items.map((item) => `
      <article class="panel" data-item="${escapeHtml(item.id)}">
        <p><strong>Búsqueda:</strong> ${escapeHtml(item.query)}</p>
        <p><strong>Categoría/tienda:</strong> ${escapeHtml(item.category)} · ${escapeHtml(item.store)}</p>
        ${renderOffer(item)}
        <h3>Revisiones</h3>
        <ul>${(item.reviews || []).map((review) => `
          <li>${escapeHtml(review.reviewer_id)}: <strong>${escapeHtml(review.label_name)}</strong> — ${escapeHtml(review.note || "Sin nota")}</li>
        `).join("")}</ul>
        <label>Nota de arbitraje <textarea data-note maxlength="500" rows="2"></textarea></label>
        <div class="analysis-search">
          ${LABELS.map(([value, text]) => `<button type="button" data-arbitrate="${value}">${text}</button>`).join("")}
        </div>
      </article>`).join("");
  }

  async function loadRun() {
    if (!runId) return;
    const [summary, queue, arbitration] = await Promise.all([
      api(`/api/admin/matching-audit/runs/${encodeURIComponent(runId)}/metrics`),
      api(`/api/admin/matching-audit/runs/${encodeURIComponent(runId)}/review-queue?limit=25`),
      api(`/api/admin/matching-audit/runs/${encodeURIComponent(runId)}/arbitration?limit=50`),
    ]);
    renderMetrics(summary);
    renderQueue(queue.items || []);
    renderArbitration(arbitration.items || []);
    $("audit-export").href = `/api/admin/matching-audit/runs/${encodeURIComponent(runId)}/export.csv`;
    $("audit-export").hidden = false;
  }

  async function loadRuns(preferredId = "") {
    const { runs } = await api("/api/admin/matching-audit/runs");
    const selector = $("audit-run");
    selector.innerHTML = runs.map((run) => `
      <option value="${escapeHtml(run.id)}">${formatDate(run.created_at)} · ${escapeHtml(run.status)} · ${Number(run.comparison_count || 0)} comparaciones</option>
    `).join("");
    runId = preferredId || runs[0]?.id || "";
    selector.value = runId;
    if (runId) await loadRun();
    else {
      $("audit-metrics").innerHTML = "";
      $("audit-queue").innerHTML = '<p class="muted">Crea una muestra para comenzar.</p>';
      $("audit-arbitration").innerHTML = "";
      $("audit-export").hidden = true;
    }
  }

  $("audit-run").addEventListener("change", async (event) => {
    runId = event.target.value;
    try { await loadRun(); } catch (error) { flash(error.message, true); }
  });

  $("audit-create").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    flash("Creando y estratificando una muestra…");
    try {
      const result = await api("/api/admin/matching-audit/runs", { method: "POST", body: "{}" });
      await loadRuns(result.run_id);
      flash("Muestra creada.");
    } catch (error) {
      flash(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  $("audit-queue").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-label]");
    if (!button) return;
    const card = button.closest("[data-item]");
    button.disabled = true;
    try {
      await api(`/api/admin/matching-audit/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(card.dataset.item)}/reviews`, {
        method: "POST",
        body: JSON.stringify({ label: button.dataset.label, note: card.querySelector("[data-note]").value }),
      });
      flash(`Revisión guardada: ${labelNames[button.dataset.label]}.`);
      await loadRun();
    } catch (error) {
      flash(error.message, true);
      button.disabled = false;
    }
  });

  $("audit-arbitration").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-arbitrate]");
    if (!button) return;
    const card = button.closest("[data-item]");
    button.disabled = true;
    try {
      await api(`/api/admin/matching-audit/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(card.dataset.item)}/arbitration`, {
        method: "POST",
        body: JSON.stringify({ label: button.dataset.arbitrate, note: card.querySelector("[data-note]").value }),
      });
      flash(`Desacuerdo arbitrado: ${labelNames[button.dataset.arbitrate]}.`);
      await loadRun();
    } catch (error) {
      flash(error.message, true);
      button.disabled = false;
    }
  });

  loadRuns().catch((error) => flash(error.message, true));
})();

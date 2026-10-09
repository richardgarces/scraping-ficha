(() => {
  let page = 1;
  let totalPages = 1;

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function money(value) {
    if (value == null || value === "") return "—";
    return Number(value).toLocaleString("es-CL", {
      style: "currency",
      currency: "CLP",
      maximumFractionDigits: 0,
    });
  }

  function fmtDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
    return date.toLocaleString("es-CL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function flash(text, ok = true) {
    const el = $("flash");
    el.hidden = false;
    el.className = ok ? "summary" : "err";
    el.textContent = text;
  }

  async function json(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 || response.status === 403) {
      const next = encodeURIComponent(`${location.pathname}${location.search}`);
      location.href = `/entrar?next=${next}`;
      throw new Error("Entra con la cuenta de administrador.");
    }
    if (!response.ok) {
      const detail = payload.detail;
      throw new Error(typeof detail === "string" ? detail : response.statusText);
    }
    return payload;
  }

  const STATUS = {
    pending: { label: "Pendiente", className: "outcome-pending" },
    hit: { label: "Cumplió", className: "outcome-hit" },
    miss: { label: "No cumplió", className: "outcome-miss" },
    expired: { label: "Vencido", className: "outcome-miss" },
  };

  function statusCell(row) {
    const meta = STATUS[row.status] || STATUS.pending;
    const reason = row.hit_reason
      ? `<span class="muted outcome-reason">${escapeHtml(row.hit_reason)}</span>`
      : "";
    return `<span class="outcome-badge ${meta.className}">${meta.label}</span>${reason}`;
  }

  function etaCell(row) {
    if (row.status === "hit") {
      const days = row.days_to_hit != null ? row.days_to_hit : "—";
      return `<strong>${escapeHtml(days)}</strong> <span class="muted">días a cumplir</span>`;
    }
    if (row.status === "miss" || row.status === "expired") {
      return `<span class="muted">Horizonte cerrado (${escapeHtml(row.horizon || "—")} d)</span>`;
    }
    const eta = row.eta_days != null ? row.eta_days : "—";
    const elapsed = row.days_elapsed != null ? row.days_elapsed : 0;
    return `<strong>${escapeHtml(eta)}</strong> <span class="muted">días est. · ${escapeHtml(elapsed)}/​${escapeHtml(row.horizon || "—")}</span>`;
  }

  function productCell(row) {
    const name = row.name || row.product_id || row.forecast_key || "Producto";
    const store = row.store || "";
    const href = row.store && row.product_id
      ? `/producto?store=${encodeURIComponent(row.store)}&id=${encodeURIComponent(row.product_id)}`
      : "";
    const title = href
      ? `<a href="${href}">${escapeHtml(name)}</a>`
      : escapeHtml(name);
    return `${title}<div class="muted">${escapeHtml(store)}${store && row.product_id ? " · " : ""}${escapeHtml(row.product_id || "")}</div>`;
  }

  function rangeCell(row) {
    if (row.range_low == null && row.range_high == null) return "—";
    const trend = row.trend ? ` · ${row.trend}` : "";
    return `${money(row.range_low)} – ${money(row.range_high)}<div class="muted">${escapeHtml(money(row.expected_price))}${escapeHtml(trend)}</div>`;
  }

  function renderStats(stats) {
    const box = $("outcome-stats");
    const by = stats.by_status || {};
    const hitRate = stats.hit_rate == null ? "—" : `${stats.hit_rate}%`;
    const medianHit = stats.median_days_to_hit == null ? "—" : stats.median_days_to_hit;
    const pendingEta = stats.pending_eta_median == null ? "—" : stats.pending_eta_median;
    box.innerHTML = `
      <div class="outcome-stat"><span class="muted">Total</span><strong>${escapeHtml(stats.total || 0)}</strong></div>
      <div class="outcome-stat"><span class="muted">Cumplió</span><strong class="outcome-hit">${escapeHtml(by.hit || 0)}</strong></div>
      <div class="outcome-stat"><span class="muted">No cumplió</span><strong class="outcome-miss">${escapeHtml(by.miss || 0)}</strong></div>
      <div class="outcome-stat"><span class="muted">Pendiente</span><strong class="outcome-pending">${escapeHtml(by.pending || 0)}</strong></div>
      <div class="outcome-stat"><span class="muted">Hit rate</span><strong>${escapeHtml(hitRate)}</strong></div>
      <div class="outcome-stat"><span class="muted">Mediana días a cumplir</span><strong>${escapeHtml(medianHit)}</strong></div>
      <div class="outcome-stat"><span class="muted">ETA mediana pendiente</span><strong>${escapeHtml(pendingEta)}</strong></div>
    `;

    const models = stats.by_model || [];
    const wrap = $("outcome-model-stats");
    const body = $("outcome-model-body");
    if (!models.length) {
      wrap.hidden = true;
      body.innerHTML = "";
      return;
    }
    wrap.hidden = false;
    body.innerHTML = models.map((row) => `
      <tr>
        <td>${escapeHtml(row.model)}</td>
        <td>${escapeHtml(row.total)}</td>
        <td>${escapeHtml(row.hit)}</td>
        <td>${escapeHtml(row.miss)}</td>
        <td>${escapeHtml(row.pending)}</td>
        <td>${row.hit_rate == null ? "—" : `${escapeHtml(row.hit_rate)}%`}</td>
        <td>${row.median_days_to_hit == null ? "—" : escapeHtml(row.median_days_to_hit)}</td>
      </tr>
    `).join("");
  }

  function filterParams() {
    const params = new URLSearchParams({
      page: String(page),
      size: "40",
    });
    const q = $("filter-q").value.trim();
    const status = $("filter-status").value;
    const model = $("filter-model").value;
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    if (model) params.set("model", model);
    return params;
  }

  async function loadStats() {
    const stats = await json("/api/admin/forecast-outcomes/stats");
    renderStats(stats);
  }

  async function loadList() {
    const data = await json(`/api/admin/forecast-outcomes?${filterParams()}`);
    const items = data.items || [];
    totalPages = Math.max(1, Math.ceil((data.total || 0) / (data.size || 40)));
    $("outcomes-meta").textContent = data.total
      ? `${Number(data.total).toLocaleString("es-CL")} pronósticos`
      : "Todavía no hay snapshots de pronósticos. Generá forecasts o pulsá Actualizar evaluación.";
    $("outcomes-body").innerHTML = items.length
      ? items.map((row) => `
          <tr>
            <td>${productCell(row)}</td>
            <td><code>${escapeHtml(row.model || "—")}</code></td>
            <td>${escapeHtml(fmtDate(row.generated_at))}</td>
            <td>${escapeHtml(row.horizon || "—")} d</td>
            <td>${statusCell(row)}</td>
            <td>${etaCell(row)}</td>
            <td>${rangeCell(row)}</td>
          </tr>
        `).join("")
      : `<tr><td colspan="7" class="muted">Sin resultados con esos filtros.</td></tr>`;
    if (typeof RetailPager !== "undefined") {
      const pager = RetailPager.render(data.page, totalPages);
      page = pager.page;
    }
  }

  async function reload() {
    await Promise.all([loadStats(), loadList()]);
  }

  $("outcome-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    page = 1;
    loadList().catch((error) => flash(error.message, false));
  });

  $("filter-reset").addEventListener("click", () => {
    $("filter-q").value = "";
    $("filter-status").value = "";
    $("filter-model").value = "";
    page = 1;
    loadList().catch((error) => flash(error.message, false));
  });

  $("prev").addEventListener("click", () => {
    if (page > 1) {
      page -= 1;
      loadList().catch((error) => flash(error.message, false));
    }
  });

  $("next").addEventListener("click", () => {
    if (page < totalPages) {
      page += 1;
      loadList().catch((error) => flash(error.message, false));
    }
  });

  $("refresh-outcomes").addEventListener("click", async () => {
    const button = $("refresh-outcomes");
    button.disabled = true;
    try {
      const result = await json("/api/admin/forecast-outcomes/refresh", { method: "POST" });
      const backfill = result.backfill || {};
      const evaluate = result.evaluate || {};
      flash(
        `Evaluación: +${backfill.inserted || 0} snapshots, revisados ${evaluate.checked || 0} `
        + `(cumplió ${evaluate.hit || 0}, no ${evaluate.miss || 0}, pendiente ${evaluate.pending || 0}).`,
      );
      await reload();
    } catch (error) {
      flash(error.message, false);
    } finally {
      button.disabled = false;
    }
  });

  reload().catch((error) => flash(error.message, false));
})();

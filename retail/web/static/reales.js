// $, money, attr y thumbMarkup vienen de prices.js

let page = 1;
let totalPages = 1;
let loadToken = 0;
const pageSearchForm = document.querySelector(".desktop-quick-search");
const pageSearchInput = pageSearchForm?.querySelector('input[name="q"]');
$("super-filter").checked = new URLSearchParams(location.search).get("super") === "1";

function flash(text, ok = false) {
  $("flash").hidden = false;
  $("flash").className = ok ? "summary" : "err";
  $("flash").textContent = text;
}

function setDealsBusy(on) {
  const deals = $("deals");
  const filters = $("real-filters");
  if (filters) filters.setAttribute("aria-busy", on ? "true" : "false");
  if (deals) {
    deals.setAttribute("aria-busy", on ? "true" : "false");
    if (on) {
      deals.innerHTML =
        `<div class="panel muted compare-loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span> Cargando ofertas…</div>`;
    }
  }
  if (on) $("summary").textContent = "Cargando ofertas…";
  $("prev").disabled = on || page <= 1;
  $("next").disabled = on || page >= totalPages;
  document.querySelectorAll("#real-filters [data-filter-control]").forEach((el) => {
    el.disabled = Boolean(on);
  });
}

function kindLabel(kind) {
  if (kind === "comparacion") return "Comparación entre tiendas";
  if (kind === "historial") return "Bajó respecto a otra fecha";
  if (kind === "iguales") return "Mismo precio en tiendas";
  return kind;
}

function fillSelect(id, values, current, anyLabel) {
  $(id).innerHTML =
    `<option value="">${anyLabel}</option>` +
    values
      .map((value) => `<option value="${attr(value)}" ${value === current ? "selected" : ""}>${attr(value)}</option>`)
      .join("");
}

function gapMark(item) {
  if ((item.gap || 0) > 0) {
    return `<span class="badge off">−${Math.round(item.gap_percent || 0)}%</span>`;
  }
  return `<span class="badge">mismo precio</span>`;
}

function timesfmSignal(item) {
  const signal = item.timesfm_signal;
  if (!signal) return "";
  return `<div class="timesfm-offer-signal timesfm-${attr(signal.status)}">
    <strong>TimesFM experimental · ${attr(signal.label)}</strong>
    <span>${attr(signal.explanation)}</span>
    <small>Esperado: ${money(signal.range_low)}–${money(signal.range_high)} · estimación, no garantía</small>
  </div>`;
}

function storeLine(row) {
  const title = row.store_title || row.store;
  const off = row.discount >= 10 ? discountBadge(row.discount, 10) : "";
  const labels = [
    row.best_price ? '<span class="badge off">Mejor precio</span>' : "",
    row.strongest_verified ? '<span class="badge">Mayor baja comprobada</span>' : "",
    row.strongest_published ? '<span class="badge ghost">Mayor descuento publicado</span>' : "",
  ].filter(Boolean).join(" ");
  const ficha = row.product_id
    ? `/producto?store=${encodeURIComponent(row.store)}&id=${encodeURIComponent(row.product_id)}`
    : "";
  const verified = row.verified_discount > 0 ? `<small>${Math.round(row.verified_discount)}% vs historial</small>` : "";
  const inner = `<span class="compare-store-brand">${storeLogo(row.display_store || row.store, title)}</span><span class="compare-store-value"><span class="price">${money(row.price)}</span>${off}${verified}${labels}</span>`;
  if (ficha) {
    return `<li class="${row.win ? "win" : ""}"><a href="${attr(ficha)}">${inner}</a></li>`;
  }
  return `<li class="${row.win ? "win" : ""}">${inner}</li>`;
}

function dealCard(item) {
  const image = thumbMarkup(
    "deal-img",
    item.product_id
      ? `/api/thumb?store=${encodeURIComponent(item.store)}&id=${encodeURIComponent(item.product_id)}`
      : ""
  );
  const ficha = item.product_id
    ? `/producto?store=${encodeURIComponent(item.store)}&id=${encodeURIComponent(item.product_id)}`
    : "";
  const title = ficha
    ? `<a class="deal-name" href="${attr(ficha)}">${attr(item.name)}</a>`
    : `<span class="deal-name">${attr(item.name)}</span>`;
  const kinds = (item.kinds || [])
    .map((kind) => `<span class="badge">${attr(kindLabel(kind))}</span>`)
    .join("");
  const history = item.was_full_price_on
    ? `<p class="muted">Sin descuento el ${attr(item.was_full_price_on)}</p>`
    : "";
  const stores = (item.stores || []).map(storeLine).join("");
  const confidence = Math.round(Number(item.entity_confidence || 0) * 100);
  const identity = confidence >= 90
    ? `<span class="badge">Coincidencia alta ${confidence}%</span>`
    : `<span class="badge ghost">Coincidencia ${confidence}%: revisa modelo y variante</span>`;
  const market = item.market_best
    ? '<span class="badge off">Es el menor precio actual</span>'
    : `<span class="badge ghost">No es el menor precio · ${attr(item.best_price_store || "otra tienda")} tiene ${money(item.best_price)}</span>`;
  const discountSummary = `Comercial: ${Math.round(item.commercial_discount || item.published_discount || 0)}% · ahorro real: ${Math.round(item.real_savings_percent || item.verified_discount || 0)}%`;
  const fresh = typeof updatedAgo === "function" ? updatedAgo(item.updated_at) : "";
  const suspicion = (item.suspicion_labels || []).length
    ? `<p class="muted">${attr((item.suspicion_labels || []).join(" · "))}</p>`
    : "";
  return `
    <article class="panel deal">
      ${image}
      <div class="deal-body">
        ${title}
        <p class="muted">${attr(item.brand || item.category || "")}${fresh ? ` · ${attr(fresh)}` : ""}</p>
        <div class="deal-kinds">${kinds}${market}${identity}</div>
        <div class="deal-prices">
          <div>
            <span class="deal-label">Oferta</span>
            <span class="price">${money(item.price)}</span>
          </div>
          <div>
            <span class="deal-label">Otra tienda</span>
            <span class="deal-saving">${money(item.rival_price)}${gapMark(item)}</span>
          </div>
        </div>
        <p class="muted">${attr(discountSummary)} · puntaje ${Number(item.offer_score || 0).toLocaleString("es-CL")}/100</p>
        <p class="deal-reason">${attr(item.reason || "")}</p>
        ${suspicion}
        ${timesfmSignal(item)}
        ${history}
        <ul class="compare-stores">${stores}</ul>
      </div>
    </article>`;
}

function render(data) {
  const rows = data.items || [];
  const total = data.total || 0;
  totalPages = Math.max(1, Math.ceil(total / (data.size || 40)));
  const comparacion = $("comparacion").checked;
  const historial = $("historial").checked;
  const iguales = $("iguales").checked;
  const superOnly = $("super-filter").checked;
  const timesfmSummary = $("timesfm-summary");
  if (timesfmSummary) {
    const admin = Boolean(window.retailUser && window.retailUser.role === "admin");
    if (admin) {
      const timesfm = data.timesfm_signal_status || {};
      timesfmSummary.textContent = timesfm.enabled
        ? `TimesFM complementa el análisis actual en ${timesfm.visible_signals || 0} ofertas de esta página; no cambia la clasificación.`
        : `TimesFM aún no se muestra en ofertas: ${timesfm.reason || "falta validar su precisión"} El análisis actual sigue funcionando sin cambios.`;
    } else {
      timesfmSummary.textContent = "";
    }
  }
  if (!comparacion && !historial && !iguales && !superOnly) {
    $("summary").textContent = "Activa al menos un tipo de oferta.";
  } else if (total) {
    const minGap = Number($("min-gap").value) || 0;
    const gapNote = minGap ? ` Mínimo ${minGap}% más barato que la otra tienda.` : "";
    const kind = superOnly ? ` super ofertas (más de ${data.min_super || 50}% de descuento real)` : " ofertas reales";
    $("summary").textContent = `Mostrando ${rows.length} de ${total.toLocaleString("es-CL")}${kind}.${gapNote}`;
  } else {
    $("summary").textContent = "No hay productos que cumplan esas comparaciones con los precios guardados.";
  }
  $("deals").innerHTML = rows.length
    ? rows.map(dealCard).join("")
    : `<p class="panel muted">Sin ofertas reales para estos filtros.</p>`;
  saveProductTrail(rows);
  const pager = RetailPager.render(data.page || 1, totalPages);
  page = pager.page;
}

function params() {
  const query = new URLSearchParams({
    page: String(page),
    size: $("size").value || "40",
    comparacion: $("comparacion").checked ? "true" : "false",
    historial: $("historial").checked ? "true" : "false",
    iguales: $("iguales").checked ? "true" : "false",
    super: $("super-filter").checked ? "true" : "false",
  });
  if (pageSearchInput?.value.trim()) query.set("q", pageSearchInput.value.trim());
  if ($("category").value) query.set("category", $("category").value);
  if ($("store").value) query.set("store", $("store").value);
  if (Number($("min-gap").value) > 0) query.set("min_gap", $("min-gap").value);
  return query;
}

async function load() {
  const token = ++loadToken;
  if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(true);
  setDealsBusy(true);
  try {
  if (typeof ensureUser === "function") await ensureUser();
  if (token !== loadToken) return;
  const response = await fetch(`/api/reales?${params()}`);
  const data = await response.json().catch(() => ({}));
  if (token !== loadToken) return;
  if (response.status === 401) {
    location.href = "/entrar?next=/reales";
    return;
  }
  if (!response.ok) {
    flash(typeof data.detail === "string" ? data.detail : response.statusText);
    $("deals").innerHTML = `<p class="panel muted">No se pudieron cargar las ofertas.</p>`;
    $("summary").textContent = "";
    return;
  }
  $("flash").hidden = true;
  fillSelect("store", data.stores || [], $("store").value, "todas");
  fillSelect("category", data.categories || [], $("category").value, "todas");
  render(data);
  updateFilterBadge("real-filters", "real-filter-count");
  } catch (error) {
    if (token !== loadToken) return;
    flash(error.message || "Error al cargar ofertas");
    $("deals").innerHTML = `<p class="panel muted">No se pudieron cargar las ofertas.</p>`;
    $("summary").textContent = "";
  } finally {
    if (token === loadToken) {
      setDealsBusy(false);
      if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(false);
    }
  }
}

function reload() {
  page = 1;
  load();
}

["comparacion", "historial", "iguales", "super-filter", "category", "store", "min-gap", "size"].forEach((id) => {
  $(id).addEventListener("change", reload);
});

pageSearchForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  reload();
});
pageSearchInput?.addEventListener("search", reload);

$("prev").addEventListener("click", () => {
  if (page > 1) {
    page -= 1;
    load();
  }
});
$("next").addEventListener("click", () => {
  if (page < totalPages) {
    page += 1;
    load();
  }
});

load();

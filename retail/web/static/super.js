// $, money, attr, discountBadge y thumbMarkup vienen de prices.js

let page = 1;
let totalPages = 1;
const pageSearchForm = document.querySelector(".desktop-quick-search");
const pageSearchInput = pageSearchForm?.querySelector('input[name="q"]');

function flash(text, ok = false) {
  $("flash").hidden = false;
  $("flash").className = ok ? "summary" : "err";
  $("flash").textContent = text;
}

function kindLabel(kind) {
  if (kind === "comparacion") return "Comparación entre tiendas";
  if (kind === "historial") return "Bajó respecto a otra fecha";
  return kind;
}

function fillSelect(id, values, current, anyLabel) {
  $(id).innerHTML =
    `<option value="">${anyLabel}</option>` +
    values
      .map((value) => `<option value="${attr(value)}" ${value === current ? "selected" : ""}>${attr(value)}</option>`)
      .join("");
}

function superPercent(item) {
  return Math.max(Number(item.gap_percent) || 0, Number(item.discount) || 0);
}

function gapMark(item) {
  const pct = Number(item.gap_percent) || 0;
  if ((item.gap || 0) > 0 && pct > 0) {
    return discountBadge(pct, 1);
  }
  return "";
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
  const ficha = row.product_id
    ? `/producto?store=${encodeURIComponent(row.store)}&id=${encodeURIComponent(row.product_id)}`
    : "";
  const labels = [
    row.best_price ? '<span class="badge off">Mejor precio</span>' : "",
    row.strongest_verified ? '<span class="badge">Mayor baja comprobada</span>' : "",
    row.strongest_published ? '<span class="badge ghost">Mayor descuento publicado</span>' : "",
  ].filter(Boolean).join(" ");
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
  const headline = discountBadge(superPercent(item), 1);
  const confidence = Math.round(Number(item.entity_confidence || 0) * 100);
  const market = item.market_best
    ? '<span class="badge off">Es el menor precio actual</span>'
    : `<span class="badge ghost">No es el menor precio · ${attr(item.best_price_store || "otra tienda")} tiene ${money(item.best_price)}</span>`;
  return `
    <article class="panel deal">
      ${image}
      <div class="deal-body">
        ${title}
        <p class="muted">${attr(item.brand || item.category || "")}</p>
        <div class="deal-kinds">${kinds}${headline}${market}<span class="badge">Coincidencia ${confidence}%</span></div>
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
        <p class="muted">Publicado: ${Math.round(item.published_discount || 0)}% · comprobado: ${Math.round(item.verified_discount || 0)}% · puntaje ${Number(item.offer_score || 0).toLocaleString("es-CL")}/100</p>
        <p class="deal-reason">${attr(item.reason || "")}</p>
        ${timesfmSignal(item)}
        ${history}
        <ul class="compare-stores">${stores}</ul>
      </div>
    </article>`;
}

function render(data) {
  const rows = data.items || [];
  const total = data.total || 0;
  const floor = data.min_super || 50;
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
  totalPages = Math.max(1, Math.ceil(total / (data.size || 40)));
  if (total) {
    $("summary").textContent =
      `Mostrando ${rows.length} de ${total.toLocaleString("es-CL")} super ofertas (más de ${floor}% de ahorro real).`;
  } else {
    $("summary").textContent =
      "No hay productos con más de 50% de ahorro real frente al historial u otras tiendas.";
  }
  $("deals").innerHTML = rows.length
    ? rows.map(dealCard).join("")
    : `<p class="panel muted">Sin super ofertas para estos filtros.</p>`;
  saveProductTrail(rows);
  $("page-label").textContent = `Página ${data.page || 1} de ${totalPages}`;
  $("prev").disabled = (data.page || 1) <= 1;
  $("next").disabled = (data.page || 1) >= totalPages;
}

function params() {
  const query = new URLSearchParams({
    page: String(page),
    size: $("size").value || "40",
  });
  if (pageSearchInput?.value.trim()) query.set("q", pageSearchInput.value.trim());
  if ($("category").value) query.set("category", $("category").value);
  if ($("store").value) query.set("store", $("store").value);
  return query;
}

async function load() {
  if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(true);
  try {
  if (typeof ensureUser === "function") await ensureUser();
  const response = await fetch(`/api/super?${params()}`);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    location.href = "/entrar?next=/super";
    return;
  }
  if (!response.ok) {
    flash(typeof data.detail === "string" ? data.detail : response.statusText);
    return;
  }
  $("flash").hidden = true;
  fillSelect("store", data.stores || [], $("store").value, "todas");
  fillSelect("category", data.categories || [], $("category").value, "todas");
  render(data);
  updateFilterBadge("super-filters", "super-filter-count");
  } finally {
    if (typeof setQuickSearchBusy === "function") setQuickSearchBusy(false);
  }
}

function reload() {
  page = 1;
  load().catch((error) => flash(error.message));
}

["category", "store", "size"].forEach((id) => {
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
    load().catch((error) => flash(error.message));
  }
});
$("next").addEventListener("click", () => {
  if (page < totalPages) {
    page += 1;
    load().catch((error) => flash(error.message));
  }
});

load().catch((error) => flash(error.message));

// $, money, attr, discountOf, discountBadge y priceLadder vienen de prices.js

const RULES = {
  price_drop_percent: "Bajó de precio (%)",
  price_drop_amount: "Bajó de precio ($)",
  cross_store_gap: "Mejor precio vs. competencia",
  below_median: "Bajo su precio habitual",
  watch_target: "Llegó a tu precio objetivo",
  watch_change: "Cambió el precio",
};

let page = 1;
let totalPages = 1;
const pageSearchForm = document.querySelector(".desktop-quick-search");
const pageSearchInput = pageSearchForm?.querySelector('input[name="q"]');

function flash(text, ok = false) {
  $("flash").hidden = false;
  $("flash").className = ok ? "summary" : "err";
  $("flash").textContent = text;
}

function ruleLabel(rule) {
  return (rule || "")
    .split("+")
    .map((item) => RULES[item] || item)
    .filter((item, index, list) => list.indexOf(item) === index)
    .join(" · ");
}

function fillSelect(select, values, current, anyLabel, labels) {
  select.innerHTML =
    `<option value="">${anyLabel}</option>` +
    values
      .map((value) => {
        const text = (labels && labels[value]) || value;
        return `<option value="${attr(value)}" ${value === current ? "selected" : ""}>${attr(text)}</option>`;
      })
      .join("");
}

function renderDeals(data) {
  const rows = data.deals || [];
  const total = data.total || 0;
  const needle = pageSearchInput?.value.trim() || "";
  totalPages = Math.max(1, Math.ceil(total / (data.size || 80)));
  if (total) {
    const shown = `Mostrando ${rows.length} de ${total.toLocaleString("es-CL")}`;
    $("summary").textContent = needle
      ? `${shown} ofertas para “${needle}” · Ahorro ${money(data.total_saving)}`
      : `${shown} ofertas · Ahorro total detectado ${money(data.total_saving)}`;
  } else {
    $("summary").textContent = needle
      ? `Ninguna oferta de este día coincide con “${needle}”.`
      : "No hay ofertas guardadas para ese día. Corre el batch desde Configurar.";
  }
  $("deals").innerHTML = rows.length
    ? rows.map(dealCard).join("")
    : `<p class="panel muted">Sin ofertas.</p>`;
  $("page-label").textContent = `Página ${data.page || 1} de ${totalPages}`;
  $("prev").disabled = (data.page || 1) <= 1;
  $("next").disabled = (data.page || 1) >= totalPages;
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
    : item.url
      ? `<a class="deal-name" href="${attr(item.url)}" target="_blank" rel="noreferrer">${attr(item.name)}</a>`
      : `<span class="deal-name">${attr(item.name)}</span>`;
  const cta = ficha
    ? `<a class="deal-cta" href="${attr(ficha)}">Ver ficha</a>`
    : item.url
      ? `<a class="deal-cta" href="${attr(item.url)}" target="_blank" rel="noreferrer">Ver oferta</a>`
      : "";
  return `
    <article class="panel deal">
      ${image}
      <div class="deal-body">
        ${title}
        <p class="muted">${attr(item.category || "")}</p>
        <div class="deal-meta">
          ${storeLogo(item.display_store || item.store, item.store_title || item.store)}
          ${cta}
        </div>
        <div class="deal-prices">
          <div>
            <span class="deal-label">Precio</span>
            <span class="price">${money(item.price)}</span>
          </div>
          <div>
            <span class="deal-label">Ahorro</span>
            <span class="deal-saving">${item.saving ? money(item.saving) : "—"}${item.discount ? discountBadge(item.discount, 1) : ""}</span>
          </div>
        </div>
        <p class="deal-reason"><span>Motivo</span> ${attr(ruleLabel(item.rule))}</p>
      </div>
    </article>`;
}

function renderRuns(runs) {
  $("runs").innerHTML = (runs || []).length
    ? runs
        .map(
          (run) => `
          <tr>
            <td class="muted">${(run.started_at || "").replace("T", " ").slice(0, 16)}</td>
            <td>${run.status || ""}</td>
            <td>${run.processed || 0} / ${run.items || 0}</td>
            <td class="muted">+${run.saved_upserted || 0} ~${run.saved_modified || 0}</td>
            <td class="${run.failed ? "err" : "muted"}">${run.failed || 0}</td>
            <td class="muted">${run.without_price || 0}</td>
            <td>${run.alert_count || 0}</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="7" class="muted">Todavía no se ha corrido el batch.</td></tr>`;
}

function params() {
  const query = new URLSearchParams({ page: String(page), size: $("size").value || "80" });
  if (pageSearchInput?.value.trim()) query.set("q", pageSearchInput.value.trim());
  if ($("day").value) query.set("day", $("day").value);
  if ($("category").value) query.set("category", $("category").value);
  if ($("store").value) query.set("store", $("store").value);
  if ($("rule").value) query.set("rule", $("rule").value);
  if (Number($("min-price").value) > 0) query.set("min_price", $("min-price").value);
  if (Number($("max-price").value) > 0) query.set("max_price", $("max-price").value);
  if (Number($("min-saving").value) > 0) query.set("min_saving", $("min-saving").value);
  if (Number($("min-discount").value) > 0) query.set("min_discount", $("min-discount").value);
  if ($("sort").value) query.set("sort", $("sort").value);
  return query;
}

async function load(keepFilters = false) {
  const response = await fetch(`/api/deals?${params()}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    flash(typeof data.detail === "string" ? data.detail : response.statusText);
    return;
  }
  $("flash").hidden = true;
  fillSelect($("day"), data.days || [], data.day, "más reciente");
  if (!keepFilters) {
    const facets = data.facets || {};
    fillSelect($("category"), facets.categories || [], $("category").value, "todas");
    fillSelect($("store"), facets.stores || [], $("store").value, "todas", data.store_labels || {});
    fillSelect($("rule"), facets.rules || [], $("rule").value, "todos", RULES);
  }
  renderDeals(data);
  renderRuns(data.runs);
  updateFilterBadge("today-filters", "today-filter-count");
}

function reload() {
  page = 1;
  load(true).catch((error) => flash(error.message));
}

["category", "store", "rule", "min-price", "max-price", "min-saving", "min-discount", "sort", "size"].forEach((id) => {
  $(id).addEventListener("change", reload);
});
$("day").addEventListener("change", () => {
  page = 1;
  load(false).catch((error) => flash(error.message));
});

pageSearchForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  reload();
});
pageSearchInput?.addEventListener("search", reload);

$("prev").addEventListener("click", () => {
  if (page > 1) {
    page -= 1;
    load(true).catch((error) => flash(error.message));
  }
});
$("next").addEventListener("click", () => {
  if (page < totalPages) {
    page += 1;
    load(true).catch((error) => flash(error.message));
  }
});

load().catch((error) => flash(error.message));

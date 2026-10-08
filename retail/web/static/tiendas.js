/* Ranking de tiendas según cuántas de sus bajas de precio son de verdad.
   El número de «Bajas de precio» abre justo esas bajas, no el catálogo. */

let reportStores = [];
let reportMeta = {};
const dropsCache = new Map();

function flash(message, isError = false) {
  const box = $("flash");
  box.hidden = false;
  box.className = isError ? "err" : "summary";
  box.textContent = message;
}

function bar(percent) {
  const width = Math.min(100, Math.max(2, percent));
  return `<span class="bar"><span style="width:${width}%"></span></span>`;
}

function formatWhen(iso) {
  if (!iso) return "";
  const day = new Date(iso);
  if (Number.isNaN(day.getTime())) return "";
  return day.toLocaleDateString("es-CL", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "America/Santiago",
  });
}

function formatWhenTime(iso) {
  if (!iso) return "";
  const day = new Date(iso);
  if (Number.isNaN(day.getTime())) return "";
  return day.toLocaleString("es-CL", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Santiago",
  });
}

function fichaHref(item) {
  if (!item.product_id) return "";
  return `/producto?store=${encodeURIComponent(item.store || "")}&id=${encodeURIComponent(item.product_id)}`;
}

function dropsButton(row) {
  const n = row.drops || 0;
  if (!n) return "0";
  const label = n === 1 ? "Ver la baja de precio" : `Ver las ${n} bajas de precio`;
  return `<button type="button" class="drop-count" data-drops="${attr(row.store)}" aria-expanded="false" title="${attr(label)}">${n}</button>`;
}

function closeDrops() {
  dropsView = null;
  document.querySelectorAll("tr.store-drops").forEach((row) => row.remove());
  document.querySelectorAll(".drop-count[aria-expanded='true']").forEach((button) => {
    button.setAttribute("aria-expanded", "false");
  });
}

// ((anterior − actual) / anterior) × 100. Null si el anterior falta o es 0.
function savingsPercent(item) {
  const before = Number(item.previous_price);
  const after = Number(item.price);
  if (!Number.isFinite(before) || before <= 0 || !Number.isFinite(after)) return null;
  return ((before - after) / before) * 100;
}

function savingsHtml(pct) {
  if (pct == null) return `<span class="muted">—</span>`;
  const shown = Math.round(Math.abs(pct));
  return `<span class="badge off ${discountTone(shown)}" title="${attr(`Ahorro ${shown}%`)}">−${shown}%</span>`;
}

const DROP_COLUMNS = [
  { key: "name", label: "Producto" },
  { key: "previous", label: "Precio anterior" },
  { key: "price", label: "Precio actual" },
  { key: "percent", label: "%" },
  { key: "date", label: "Fecha" },
];

function sortValue(item, key) {
  if (key === "name") {
    const name = (item.name || "").trim();
    return name || null;
  }
  if (key === "previous" || key === "price") {
    const raw = key === "previous" ? item.previous_price : item.price;
    if (raw == null || raw === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  if (key === "percent") return savingsPercent(item);
  return item.dropped_at || null;
}

function sortDrops(items, key, dir) {
  const factor = dir === "asc" ? 1 : -1;
  return items.slice().sort((a, b) => {
    const av = sortValue(a, key);
    const bv = sortValue(b, key);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string" || typeof bv === "string") {
      return String(av).localeCompare(String(bv), "es", { sensitivity: "base" }) * factor;
    }
    if (av < bv) return -1 * factor;
    if (av > bv) return 1 * factor;
    return 0;
  });
}

function dropHeaders(key, dir) {
  const heads = DROP_COLUMNS.map((col) => {
    const active = col.key === key;
    const aria = active ? (dir === "asc" ? "ascending" : "descending") : "none";
    const meaning = col.key === "percent" ? "Ahorro respecto al precio anterior" : col.label;
    const hint = active
      ? `${meaning}. ${dir === "desc" ? "Mayor a menor" : "Menor a mayor"}. Clic para invertir.`
      : `Ordenar por ${meaning}`;
    const mark = active ? `<span class="sort-mark" aria-hidden="true">${dir === "asc" ? "↑" : "↓"}</span>` : "";
    return `<th scope="col" aria-sort="${aria}"><button type="button" class="sort" data-sort="${col.key}" title="${attr(hint)}">${attr(col.label)}${mark}</button></th>`;
  }).join("");
  return `${heads}<th scope="col"></th>`;
}

let dropsView = null;

function dropList(store, items, key, dir, inflatedCount) {
  const n = items.length;
  const title = n === 1 ? "1 baja de precio" : `${n} bajas de precio`;
  const inflated = inflatedCount != null
    ? inflatedCount
    : items.filter((item) => item.inflated).length;
  const inflatedNote = n
    ? ` · ${inflated} inflada${inflated === 1 ? "" : "s"} (${n ? Math.round((inflated * 100) / n) : 0}% de esta lista)`
    : "";
  const body = n
    ? items.map((item) => {
        const when = formatWhen(item.dropped_at);
        const href = fichaHref(item);
        const name = item.name || "Sin nombre";
        const titleHtml = href ? `<a href="${attr(href)}">${attr(name)}</a>` : attr(name);
        const ficha = href ? `<a href="${attr(href)}">Ficha</a>` : "";
        const oferta = item.url
          ? `<a href="${attr(item.url)}" target="_blank" rel="noreferrer">Oferta</a>`
          : "";
        const inflatedBadge = item.inflated ? ` <span class="badge fake">inflada</span>` : "";
        const pct = savingsPercent(item);
        const hot = pct != null && Math.abs(pct) > 40 ? "savings-high" : "";
        return `
          <tr class="${hot}">
            <td>${titleHtml}${inflatedBadge}</td>
            <td class="price was">${money(item.previous_price)}</td>
            <td class="price down">${money(item.price)}</td>
            <td class="pct">${savingsHtml(pct)}</td>
            <td class="muted">${when ? attr(when) : "—"}</td>
            <td class="drops-links">${ficha}${oferta}</td>
          </tr>`;
      }).join("")
    : `<tr><td colspan="6" class="muted">No hay bajas guardadas para esta tienda.</td></tr>`;
  return `
    <div class="drops-panel">
      <div class="drops-head">
        <strong>${title} en ${attr(publicStoreLabel(store))}${attr(inflatedNote)}</strong>
        <button type="button" class="secondary" data-close-drops>Cerrar</button>
      </div>
      <p class="muted">Solo las bajas que cuenta ese número. No es el catálogo vigilado. Las filas en rojo ahorran más del 40%.</p>
      <div class="table-wrap">
        <table class="drops-table">
          <thead>
            <tr>${dropHeaders(key, dir)}</tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </div>`;
}

function paintDrops(focusHeader) {
  if (!dropsView) return;
  const { store, items, key, dir, detail, inflated } = dropsView;
  detail.innerHTML = `<td colspan="5">${dropList(store, sortDrops(items, key, dir), key, dir, inflated)}</td>`;
  if (focusHeader) detail.querySelector(`button.sort[data-sort="${CSS.escape(key)}"]`)?.focus();
}

async function openDrops(button) {
  const store = button.dataset.drops;
  const row = button.closest("tr");
  const already = button.getAttribute("aria-expanded") === "true";
  closeDrops();
  if (already || !row) return;

  const detail = document.createElement("tr");
  detail.className = "store-drops";
  detail.innerHTML = `<td colspan="5"><p class="muted">Cargando las bajas de ${attr(publicStoreLabel(store))}…</p></td>`;
  row.after(detail);
  button.setAttribute("aria-expanded", "true");

  let data = dropsCache.get(store);
  if (!data) {
    const response = await fetch(`/api/stores-drops?store=${encodeURIComponent(store)}`);
    if (response.status === 401 || response.status === 403) {
      location.href = "/entrar?next=/tiendas";
      return;
    }
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      detail.innerHTML = `<td colspan="5"><p class="err">${attr(typeof err.detail === "string" ? err.detail : "No se pudieron cargar las bajas.")}</p></td>`;
      return;
    }
    data = await response.json();
    dropsCache.set(store, data);
  }
  if (!detail.isConnected) return;
  dropsView = {
    store,
    items: data.items || [],
    inflated: data.inflated,
    key: "percent",
    dir: "desc",
    detail,
  };
  paintDrops();
}

function botCheckBadge(row) {
  if (!row || !row.bot_check) return "";
  const when = formatWhen(row.bot_check_last_seen_at);
  const hint = when
    ? `Comprobación antibot vista el ${when}. Esa captura no se adjunta.`
    : "Comprobación antibot. Esa captura no se adjunta.";
  return ` <span class="badge" title="${attr(hint)}">comprobación antibot</span>`;
}

function coverageBadge(row) {
  if (row.coverage === "sin_muestra") {
    return ` <span class="badge ghost" title="No hay productos de esta tienda en el scan de historial">Sin muestra en el scan</span>`;
  }
  if (row.coverage === "sin_bajas") {
    return ` <span class="badge ghost" title="Hay productos vigilados pero no se contaron bajas">Sin bajas detectadas</span>`;
  }
  return "";
}

function staleBadge(row) {
  if (!row.stale) return "";
  const hours = reportMeta.stale_hours || 48;
  const age = row.price_age_hours != null ? `${row.price_age_hours} h` : "";
  return ` <span class="badge fake" title="Último scrape en la muestra fuera de ${hours} h${age ? ` (${age})` : ""}">datos viejos</span>`;
}

function inflatedCell(row) {
  const percent = row.fake_percent;
  if (percent == null) {
    if (row.coverage === "sin_muestra") {
      return `<span class="muted">sin muestra</span>`;
    }
    return `<span class="muted">sin bajas</span>`;
  }
  const count = `${row.fake_drops || 0}/${row.drops || 0}`;
  return `${bar(percent)} <span title="Bajas infladas / bajas contadas">${percent}% <small class="muted">(${count})</small></span>`;
}

function lastSeenCell(row) {
  if (!row.last_seen) {
    return `<span class="muted">—</span>`;
  }
  const label = formatWhenTime(row.last_seen);
  const age = row.price_age_hours != null ? ` · ${row.price_age_hours} h` : "";
  return `<span class="${row.stale ? "err" : "muted"}" title="${attr(row.last_seen)}">${attr(label)}${attr(age)}</span>`;
}

function renderBotChecks(checks) {
  const box = $("bot-checks");
  const list = checks || [];
  if (!list.length) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  const text = list
    .map((item) => {
      const name = publicStoreLabel(item.store, item.store_title);
      const when = formatWhen(item.last_seen_at);
      return when ? `${name} (${when})` : name;
    })
    .join(", ");
  box.hidden = false;
  box.textContent =
    `Comprobación antibot: ${text}. Esas capturas no se adjuntan; el aviso usa la foto del producto.`;
}

function filteredStores() {
  const hideSin = $("hide-sin-muestra")?.checked;
  const soloBajas = $("solo-con-bajas")?.checked;
  const soloBot = $("solo-antibot")?.checked;
  const sortKey = $("store-sort")?.value || "fake_percent";
  let rows = reportStores.slice();
  if (hideSin) rows = rows.filter((row) => row.coverage !== "sin_muestra");
  if (soloBajas) rows = rows.filter((row) => (row.drops || 0) > 0);
  if (soloBot) rows = rows.filter((row) => row.bot_check);
  rows.sort((a, b) => {
    if (sortKey === "name") {
      return String(a.store_title || a.store || "").localeCompare(
        String(b.store_title || b.store || ""),
        "es",
        { sensitivity: "base" },
      );
    }
    if (sortKey === "drops") return (b.drops || 0) - (a.drops || 0);
    if (sortKey === "products") return (b.products || 0) - (a.products || 0);
    const ap = a.fake_percent;
    const bp = b.fake_percent;
    if (ap == null && bp == null) return 0;
    if (ap == null) return 1;
    if (bp == null) return -1;
    return bp - ap;
  });
  return rows;
}

function renderRows() {
  const stores = filteredStores();
  closeDrops();
  if (!stores.length) {
    $("rows").innerHTML = `<tr><td colspan="5" class="muted">Ninguna tienda cumple esos filtros.</td></tr>`;
    return;
  }
  $("rows").innerHTML = stores
    .map((row) => {
      const muted = row.coverage === "sin_muestra" ? " class=\"store-row-muted\"" : "";
      return `
        <tr${muted}>
          <td>
            <a class="store-link" href="/catalogo?store=${encodeURIComponent(row.store)}" title="Ver productos de ${attr(publicStoreLabel(row.store, row.store_title))}">
              ${storeLogo(row.display_store || row.store, row.store_title)}
            </a>${botCheckBadge(row)}${coverageBadge(row)}${staleBadge(row)}
          </td>
          <td>${dropsButton(row)}</td>
          <td>${inflatedCell(row)}</td>
          <td class="muted">${row.products}</td>
          <td>${lastSeenCell(row)}</td>
        </tr>`;
    })
    .join("");
}

function renderMeta() {
  const box = $("report-meta");
  if (!box) return;
  const ranked = reportMeta.ranked_stores ?? "—";
  const registry = reportMeta.registry_stores ?? "—";
  const limit = reportMeta.scan_limit ?? "—";
  const scanned = reportMeta.scanned_products ?? "—";
  box.hidden = false;
  box.textContent =
    `Cobertura: ${ranked} tiendas con muestra / ${registry} en registry · scan ${scanned} productos (tope ${limit}).`;
}

$("rows").addEventListener("click", (event) => {
  const sortButton = event.target.closest("button.sort[data-sort]");
  if (sortButton && dropsView) {
    const key = sortButton.dataset.sort;
    if (dropsView.key === key) dropsView.dir = dropsView.dir === "asc" ? "desc" : "asc";
    else {
      dropsView.key = key;
      dropsView.dir = key === "name" ? "asc" : "desc";
    }
    paintDrops(true);
    return;
  }
  const close = event.target.closest("[data-close-drops]");
  if (close) {
    closeDrops();
    return;
  }
  const button = event.target.closest("[data-drops]");
  if (!button) return;
  openDrops(button).catch((error) => flash(error.message, true));
});

$("tiendas-filters")?.addEventListener("change", () => {
  renderRows();
});

async function load() {
  const response = await fetch("/api/stores-report");
  if (response.status === 401 || response.status === 403) {
    location.href = "/entrar?next=/tiendas";
    return;
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    flash(typeof data.detail === "string" ? data.detail : response.statusText, true);
    return;
  }
  const data = await response.json();
  reportStores = data.stores || [];
  reportMeta = data;
  const sinMuestra = reportStores.filter((row) => row.coverage === "sin_muestra").length;
  if (!data.ready) {
    flash(
      `Llevamos ${data.days_tracked} ${data.days_tracked === 1 ? "día" : "días"} de historial. ` +
      `Desde los ${data.min_days} días esta comparación empieza a decir algo.` +
      (sinMuestra ? ` Además, ${sinMuestra} tiendas del registry no tienen muestra en este scan.` : ""),
    );
  } else if (sinMuestra) {
    flash(
      `${sinMuestra} tienda${sinMuestra === 1 ? "" : "s"} del registry sin muestra en el scan ` +
      `(tope ${data.scan_limit || "—"} productos). Usá el filtro «Ocultar sin muestra».`,
    );
  }
  renderMeta();
  renderRows();
  renderBotChecks(data.bot_checks);
}

load().catch((error) => flash(error.message, true));

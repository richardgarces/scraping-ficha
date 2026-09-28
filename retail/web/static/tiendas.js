/* Ranking de tiendas según cuántas de sus bajas de precio son de verdad.
   El número de «Bajas de precio» abre justo esas bajas, no el catálogo. */

function flash(message) {
  const box = $("flash");
  box.hidden = false;
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

function dropList(store, items, key, dir) {
  const n = items.length;
  const title = n === 1 ? "1 baja de precio" : `${n} bajas de precio`;
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
        const inflated = item.inflated ? ` <span class="badge fake">inflada</span>` : "";
        const pct = savingsPercent(item);
        const hot = pct != null && Math.abs(pct) > 40 ? "savings-high" : "";
        return `
          <tr class="${hot}">
            <td>${titleHtml}${inflated}</td>
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
        <strong>${title} en ${attr(store)}</strong>
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
  const { store, items, key, dir, detail } = dropsView;
  detail.innerHTML = `<td colspan="4">${dropList(store, sortDrops(items, key, dir), key, dir)}</td>`;
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
  detail.innerHTML = `<td colspan="4"><p class="muted">Cargando las bajas de ${attr(store)}…</p></td>`;
  row.after(detail);
  button.setAttribute("aria-expanded", "true");

  const response = await fetch(`/api/stores-drops?store=${encodeURIComponent(store)}`);
  if (response.status === 401) {
    location.href = "/entrar?next=/tiendas";
    return;
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    detail.innerHTML = `<td colspan="4"><p class="err">${attr(typeof data.detail === "string" ? data.detail : "No se pudieron cargar las bajas.")}</p></td>`;
    return;
  }
  const data = await response.json();
  if (!detail.isConnected) return;
  dropsView = { store, items: data.items || [], key: "percent", dir: "desc", detail };
  paintDrops();
}

function renderRows(stores) {
  if (!stores.length) {
    $("rows").innerHTML = `<tr><td colspan="4" class="muted">Todavía no hay historial guardado.</td></tr>`;
    return;
  }
  $("rows").innerHTML = stores
    .map((row) => {
      const percent = row.fake_percent;
      const cell = percent == null
        ? `<span class="muted">no le hemos visto bajas</span>`
        : `${bar(percent)} ${percent}%`;
      return `
        <tr>
          <td>
            <a class="store-link" href="/catalogo?store=${encodeURIComponent(row.store)}" title="Ver productos de ${attr(row.store_title || row.store)}">
              ${storeLogo(row.display_store || row.store, row.store_title || row.store)}
            </a>
          </td>
          <td>${dropsButton(row)}</td>
          <td>${cell}</td>
          <td class="muted">${row.products}</td>
        </tr>`;
    })
    .join("");
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
  openDrops(button).catch((error) => flash(error.message));
});

async function load() {
  const response = await fetch("/api/stores-report");
  if (response.status === 401) {
    location.href = "/entrar?next=/tiendas";
    return;
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    flash(typeof data.detail === "string" ? data.detail : response.statusText);
    return;
  }
  const data = await response.json();
  if (!data.ready) {
    // Con pocos días encima el ranking mide el azar, no a la tienda.
    flash(
      `Llevamos ${data.days_tracked} ${data.days_tracked === 1 ? "día" : "días"} de historial. ` +
      `Desde los ${data.min_days} días esta comparación empieza a decir algo.`
    );
  }
  renderRows(data.stores || []);
}

load().catch((error) => flash(error.message));

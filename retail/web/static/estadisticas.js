// Peticiones de la app (admin). Se refresca solo cada 30 s.

// Esta página también carga prices.js, que define utilidades globales como `$`.
// Mantener todo este archivo aislado evita colisiones que detengan su ejecución.
(() => {

const REFRESH_MS = 30000;
const GROUPS = {
  buscar: "Buscar",
  catalogo: "Catálogo",
  ofertas: "Ofertas",
  producto: "Producto",
  tiendas: "Tiendas",
  siguiendo: "Siguiendo",
  cuenta: "Cuenta",
  admin: "Admin",
  otro: "Otras",
};

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

function fmt(value) {
  return Number(value || 0).toLocaleString("es-CL");
}

async function json(url) {
  const response = await fetch(url);
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

function flash(text, ok = true) {
  const el = $("flash");
  el.hidden = false;
  el.className = ok ? "summary" : "err";
  el.textContent = text;
}

function dayLabel(iso) {
  const parts = String(iso || "").split("-");
  if (parts.length !== 3) return iso;
  return `${parts[2]}/${parts[1]}`;
}

function barColumn(label, primary, secondary, title, max) {
  const height = (value) => {
    if (!max || !value) return "0%";
    return `${Math.max(2, Math.round((value / max) * 100))}%`;
  };
  const avg = secondary == null
    ? ""
    : `<span class="hit-bar avg" style="height:${height(secondary)}" title="Promedio ${fmt(secondary)}"></span>`;
  return `
    <div class="hit-col" title="${escapeHtml(title)}">
      <span class="hit-n">${fmt(primary)}</span>
      <span class="hit-pair">
        <span class="hit-bar" style="height:${height(primary)}"></span>
        ${avg}
      </span>
      <span class="hit-label">${escapeHtml(label)}</span>
    </div>`;
}

function renderSeries(target, rows, valueOf, noun) {
  const el = $(target);
  if (!el) return;
  const max = Math.max(1, ...rows.map((row) => valueOf(row) || 0));
  el.innerHTML = `<div class="hit-bars">${rows
    .map((row) => {
      const value = valueOf(row) || 0;
      const title = `${dayLabel(row.day)}: ${fmt(value)} ${noun}`;
      const label = dayLabel(row.day).slice(0, 2);
      return barColumn(label, value, null, title, max);
    })
    .join("")}</div>`;
}

function renderDays(rows) {
  renderSeries("chart-days", rows, (row) => row.count, "peticiones");
}

function renderVisitors(rows) {
  renderSeries("chart-visitors", rows, (row) => row.visitors, "visitantes");
}

function renderSearches(rows) {
  renderSeries("chart-searches", rows, (row) => row.count, "búsquedas");
}

function renderHours(rows) {
  const max = Math.max(
    1,
    ...rows.map((row) => Math.max(row.today || 0, row.average || 0)),
  );
  $("chart-hours").innerHTML = `<div class="hit-bars hours">${rows
    .map((row) => {
      const hour = String(row.hour).padStart(2, "0");
      const title = `${hour}:00 · hoy ${fmt(row.today)} · promedio ${fmt(row.average)}`;
      return barColumn(hour, row.today || 0, row.average || 0, title, max);
    })
    .join("")}</div>`;
}

function renderGroups(rows) {
  const max = Math.max(1, ...rows.map((row) => row.count || 0));
  if (!rows.length) {
    $("chart-groups").innerHTML = `<p class="muted">Todavía no hay peticiones en esta ventana.</p>`;
    return;
  }
  $("chart-groups").innerHTML = `<div class="hit-bars groups">${rows
    .map((row) => {
      const label = GROUPS[row.group] || row.group;
      return barColumn(label, row.count || 0, null, `${label}: ${fmt(row.count)}`, max);
    })
    .join("")}</div>`;
}

function renderOrigins(rows) {
  const body = $("origins-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">Todavía no hay orígenes en esta ventana.</td></tr>`;
    return;
  }
  const max = Math.max(...rows.map((row) => row.count || 0), 1);
  body.innerHTML = rows
    .map((row) => {
      const width = Math.round(((row.count || 0) / max) * 100);
      const country = row.country ? escapeHtml(row.country) : "—";
      return `
        <tr>
          <td>${escapeHtml(row.ip)}</td>
          <td>${country}</td>
          <td class="num">${fmt(row.count)}</td>
          <td><span class="origin-bar" style="width:${width}%"></span></td>
        </tr>`;
    })
    .join("");
}

function stampLabel(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("es-CL", {
    timeZone: "America/Santiago",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderQueries(rows) {
  const body = $("queries-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">Todavía no hay búsquedas de la web en esta ventana.</td></tr>`;
    return;
  }
  const max = Math.max(...rows.map((row) => row.count || 0), 1);
  body.innerHTML = rows
    .map((row) => {
      const width = Math.round(((row.count || 0) / max) * 100);
      const query = String(row.query || "").trim() || "—";
      return `
        <tr>
          <td class="query-cell" title="${escapeHtml(query)}">${escapeHtml(query)}</td>
          <td class="num">${fmt(row.count)}</td>
          <td>${escapeHtml(stampLabel(row.last_at))}</td>
          <td><span class="origin-bar" style="width:${width}%"></span></td>
        </tr>`;
    })
    .join("");
}

function ttlLabel(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  if (!total) return "—";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours && minutes) return `${hours} h ${minutes} min`;
  if (hours) return `${hours} h`;
  if (minutes) return `${minutes} min`;
  return `${total} s`;
}

function renderSearchFreq(freq) {
  const data = freq || {};
  const items = data.items || [];
  $("search-freq-count").textContent = fmt(data.count ?? items.length);
  $("search-freq-cached").textContent = fmt(data.cached_count ?? 0);
  $("search-freq-day").textContent = data.day ? dayLabel(data.day) : "—";
  const note = data.redis === false
    ? " Redis no está disponible."
    : "";
  $("search-freq-meta").textContent =
    `Top ${data.top_n || 10} del día Chile. Hit exacto o primera palabra + filtro de tokens. ${data.store_policy || "Top global + filtro tienda."}${note}`;
  const body = $("search-freq-body");
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">${
      data.redis === false
        ? "No se pudo leer el ranking en Redis."
        : "Todavía no hay búsquedas frecuentes hoy."
    }</td></tr>`;
    return;
  }
  body.innerHTML = items
    .map((row, index) => {
      const query = String(row.query || "").trim() || "—";
      return `
        <tr>
          <td class="num">${index + 1}</td>
          <td class="query-cell" title="${escapeHtml(query)}">${escapeHtml(query)}</td>
          <td class="num">${fmt(row.count)}</td>
          <td>${row.cached ? "Sí" : "No"}</td>
        </tr>`;
    })
    .join("");
}

function renderSearchCache(cache) {
  const data = cache || {};
  const items = data.items || [];
  $("search-cache-count").textContent = fmt(data.count ?? items.length);
  $("search-cache-day").textContent = data.day ? dayLabel(data.day) : "—";
  const note = data.redis === false
    ? " Redis no está disponible, así que la lista sale vacía."
    : "";
  $("search-cache-meta").textContent =
    `Consultas guardadas hoy en Redis para no volver a scrapear. Caducan a medianoche (Santiago).${note}`;
  const body = $("search-cache-body");
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">${
      data.redis === false
        ? "No se pudo leer la caché de Redis."
        : "Todavía no hay búsquedas cacheadas hoy."
    }</td></tr>`;
    return;
  }
  body.innerHTML = items
    .map((row) => {
      const query = String(row.query || "").trim() || "—";
      const titles = (row.store_titles || row.stores || []).map((item) => String(item || "").trim()).filter(Boolean);
      const stores = titles.length ? titles.join(", ") : "—";
      const result = row.result_cached ? "Sí" : "No";
      return `
        <tr>
          <td class="query-cell" title="${escapeHtml(query)}">${escapeHtml(query)}</td>
          <td title="${escapeHtml(stores)}">${escapeHtml(stores)}</td>
          <td>${escapeHtml(result)}</td>
          <td>${escapeHtml(ttlLabel(row.ttl))}</td>
        </tr>`;
    })
    .join("");
}

function renderScrapes(scrapes) {
  const data = scrapes || {};
  const totals = data.totals || {};
  const scraped = totals.scraped || {};
  const price = totals.price_updated || {};
  const discount = totals.discount_updated || {};
  $("scrapes-today").textContent = fmt(scraped.today);
  $("scrapes-week").textContent = fmt(scraped.days_7);
  $("scrapes-month").textContent = fmt(scraped.days_30);
  $("scrapes-price-today").textContent = fmt(price.today);
  $("scrapes-price-week").textContent = fmt(price.days_7);
  $("scrapes-price-month").textContent = fmt(price.days_30);
  $("scrapes-discount-today").textContent = fmt(discount.today);
  $("scrapes-discount-week").textContent = fmt(discount.days_7);
  $("scrapes-discount-month").textContent = fmt(discount.days_30);
  const note = data.mongo === false ? " No se pudo leer el registro de scrapes." : "";
  $("scrapes-meta").textContent =
    `Productos que el scraper consultó y guardó. El precio y el descuento solo cuentan cuando cambian frente al valor anterior. Este contador partió con esta versión.${note}`;
  const rows = [...(data.by_day || [])].reverse();
  const body = $("scrapes-body");
  if (!rows.length || rows.every((row) => !(row.scraped || row.price_updated || row.discount_updated))) {
    body.innerHTML = `<tr><td colspan="4" class="muted">Todavía no hay scrapes registrados en esta ventana.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((row) => `
      <tr>
        <td>${escapeHtml(dayLabel(row.day))}</td>
        <td class="num">${fmt(row.scraped)}</td>
        <td class="num">${fmt(row.price_updated)}</td>
        <td class="num">${fmt(row.discount_updated)}</td>
      </tr>`)
    .join("");
}

function renderClicks(clicks) {
  const data = clicks || {};
  const totals = data.totals || {};
  $("clicks-today").textContent = fmt(totals.today);
  $("clicks-week").textContent = fmt(totals.days_7);
  $("clicks-month").textContent = fmt(totals.days_30);
  const note = data.mongo === false ? " No se pudo leer el registro de clics." : "";
  $("clicks-meta").textContent =
    `Clics en el menú, en la fecha y en enlaces que salen a la tienda. No cuenta la carga de la página ni el cron.${note}`;
  const rows = data.items || [];
  const body = $("clicks-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">Todavía no hay clics en esta ventana.</td></tr>`;
  } else {
    const max = Math.max(...rows.map((row) => row.days_30 || 0), 1);
    body.innerHTML = rows
      .map((row) => {
        const width = Math.round(((row.days_30 || 0) / max) * 100);
        return `
          <tr>
            <td>${escapeHtml(row.label || row.kind)}</td>
            <td class="num">${fmt(row.today)}</td>
            <td class="num">${fmt(row.days_7)}</td>
            <td class="num">${fmt(row.days_30)}</td>
            <td><span class="origin-bar" style="width:${width}%"></span></td>
          </tr>`;
      })
      .join("");
  }
  renderSeries("chart-clicks", data.by_day || [], (row) => row.count, "clics");
}

function render(payload) {
  const totals = payload.totals || {};
  const visitors = payload.visitors || {};
  const pages = payload.page_visits || {};
  const searches = payload.searches || {};
  const searchTotals = searches.totals || {};
  $("visitors-today").textContent = fmt(visitors.today);
  $("visitors-week").textContent = fmt(visitors.days_7);
  $("visitors-month").textContent = fmt(visitors.days_30);
  $("pages-today").textContent = fmt(pages.today);
  $("pages-week").textContent = fmt(pages.days_7);
  $("pages-month").textContent = fmt(pages.days_30);
  $("searches-today").textContent = fmt(searchTotals.today);
  $("searches-week").textContent = fmt(searchTotals.days_7);
  $("searches-month").textContent = fmt(searchTotals.days_30);
  $("total-today").textContent = fmt(totals.today);
  $("total-week").textContent = fmt(totals.days_7);
  $("total-month").textContent = fmt(totals.days_30);
  const stamp = payload.generated_at ? `Actualizado ${payload.generated_at.replace("T", " ").slice(0, 16)}` : "";
  const zone = payload.timezone ? ` · ${payload.timezone}` : "";
  const mongo = payload.mongo === false ? " Mongo no está disponible, así que los números salen en cero." : "";
  $("stats-meta").textContent =
    `Páginas y APIs de búsqueda o catálogo. No cuenta estáticos, salud ni el refresco de esta página. Se actualiza cada 30 s.${zone}${mongo}`;
  const searchMongo = searches.mongo === false
    ? " No se pudo leer el registro de búsquedas."
    : "";
  $("searches-meta").textContent =
    `Consultas de la caja de búsqueda. No cuenta el cron ni los barridos automáticos.${searchMongo}`;
  $("stats-refresh").textContent = stamp;
  renderClicks(payload.clicks || {});
  renderScrapes(payload.scrapes || {});
  renderSearchFreq(payload.search_freq || {});
  renderSearchCache(payload.search_cache || {});
  renderVisitors(payload.by_day || []);
  renderSearches(searches.by_day || []);
  renderQueries(searches.top || []);
  renderDays(payload.by_day || []);
  renderHours(payload.by_hour || []);
  renderOrigins(payload.origins || []);
  renderGroups(payload.groups || []);
  $("flash").hidden = true;
}

async function refresh() {
  const payload = await json("/api/admin/stats");
  render(payload);
}

let timer = 0;
function schedule() {
  window.clearTimeout(timer);
  timer = window.setTimeout(async () => {
    if (!document.hidden) {
      try {
        await refresh();
      } catch (error) {
        if (!String(error.message || "").includes("administrador")) flash(error.message, false);
      }
    }
    schedule();
  }, REFRESH_MS);
}

refresh()
  .catch((error) => {
    if (!String(error.message || "").includes("administrador")) flash(error.message, false);
  })
  .finally(schedule);

})();

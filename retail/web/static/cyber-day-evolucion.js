// Informe diario de evolución Cyber (/cyber-day/evolucion?list=&n=&day=).
// Reutiliza el patrón visual de la ficha (Oferta / Normal / Ahorro) con eje horario.
(() => {
  const SANTIAGO_TZ = "America/Santiago";
  const FETCH_TIMEOUT_MS = 10000;

  function $(id) {
    return document.getElementById(id);
  }

  function showFlash(text, ok = true) {
    const node = $("flash");
    if (!node) return;
    node.hidden = false;
    node.className = ok ? "summary" : "err";
    node.textContent = text;
  }

  function attr(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function money(value) {
    if (typeof window.money === "function") return window.money(value);
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return `$${Math.round(n).toLocaleString("es-CL")}`;
  }

  function timeLabel(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleTimeString("es-CL", {
      timeZone: SANTIAGO_TZ,
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function dayLabel(day) {
    if (!day) return "";
    const [y, m, d] = String(day).split("-").map(Number);
    if (!y || !m || !d) return String(day);
    const date = new Date(Date.UTC(y, m - 1, d, 16));
    return date.toLocaleDateString("es-CL", {
      timeZone: SANTIAGO_TZ,
      weekday: "short",
      day: "numeric",
      month: "short",
    });
  }

  function storeLabel(point) {
    if (typeof publicStoreLabel === "function") {
      return String(publicStoreLabel(point.store, point.store_title || point.store) || "").trim();
    }
    const raw = String(point.store_title || point.store || "").trim();
    return raw.replace(/\s+Chile\s*$/i, "").trim() || raw;
  }

  async function apiJson(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, { signal: controller.signal });
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401 || response.status === 403) {
        const next = encodeURIComponent(`${location.pathname}${location.search}`);
        location.href = `/entrar?next=${next}`;
        throw new Error("Entra con la cuenta de administrador.");
      }
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(typeof detail === "string" ? detail : response.statusText || `HTTP ${response.status}`);
      }
      return payload;
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error("La API tardó demasiado (timeout).");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function summaryCards(stats) {
    if (!stats) return "";
    const changeLabel = stats.change_label
      || (stats.change === 0
        ? "Sin cambio"
        : `${stats.change > 0 ? "+" : "−"}${money(Math.abs(stats.change))}`);
    return [
      ["Actual", money(stats.current)],
      ["Mínimo", money(stats.min)],
      ["Máximo", money(stats.max)],
      ["Promedio", money(stats.average)],
      ["Cambio", changeLabel],
    ].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
  }

  function hasMeaningfulNormal(observations) {
    if (window.PriceHistory?.hasMeaningfulNormal) {
      return PriceHistory.hasMeaningfulNormal(observations);
    }
    return (observations || []).some(
      (point) => point.offer != null
        && point.normal != null
        && Number(point.offer) !== Number(point.normal),
    );
  }

  function chartPointLabel(point, meaningfulNormal) {
    const parts = [timeLabel(point.at)];
    parts.push(`${meaningfulNormal ? "Oferta" : "Precio"}: ${money(point.offer)}`);
    if (meaningfulNormal && point.normal != null) {
      parts.push(`Normal: ${money(point.normal)}`);
      if (point.offer < point.normal) {
        const saving = point.normal - point.offer;
        parts.push(`Ahorro: ${money(saving)} (${Math.round((saving * 100) / point.normal)}%)`);
      } else {
        parts.push("Sin descuento");
      }
    }
    const store = storeLabel(point);
    if (store) parts.push(`Tienda: ${store}`);
    return parts.join(" · ");
  }

  function mountChartPointInteractions(container, observations, meaningfulNormal) {
    const tooltip = $("chart-tooltip");
    for (const target of container.querySelectorAll("[data-chart-point]")) {
      const show = () => {
        const point = observations[Number(target.dataset.chartPoint)];
        if (point && tooltip) tooltip.textContent = chartPointLabel(point, meaningfulNormal);
      };
      target.addEventListener("click", show);
      target.addEventListener("focus", show);
      target.addEventListener("mouseenter", show);
    }
  }

  function limitedTickIndexes(count, maximum = 6) {
    if (count <= maximum) return [...Array(count).keys()];
    return [...new Set(
      Array.from({ length: maximum }, (_, index) => Math.round((index * (count - 1)) / (maximum - 1))),
    )];
  }

  function chartAxisAnchor(index, count) {
    if (index <= 0) return "start";
    if (index >= count - 1) return "end";
    return "middle";
  }

  function renderChart(payload) {
    const observations = (payload.observations || []).map((row) => ({
      ...row,
      offer: row.offer ?? row.price,
      normal: row.normal ?? row.price_normal,
    }));
    const container = $("chart-combined");
    const summary = $("chart-summary");
    const note = $("chart-combined-note");
    const legend = $("chart-legend");
    if (!observations.length) {
      container.innerHTML = "<p class='muted chart-empty'>Aún no hay observaciones de precio para este día.</p>";
      summary.innerHTML = "";
      legend.innerHTML = "";
      note.textContent = "Cuando el worker registre un mejor precio, aparecerá aquí.";
      return;
    }

    const offerRows = observations.filter((point) => point.offer != null);
    const paired = observations.filter((point) => point.offer != null && point.normal != null);
    const meaningfulNormal = hasMeaningfulNormal(paired);
    const offerStats = payload.stats || (window.PriceHistory?.stats
      ? PriceHistory.stats(offerRows.map((point) => point.offer))
      : null);
    summary.innerHTML = summaryCards(offerStats);
    legend.innerHTML = meaningfulNormal
      ? '<span><i class="offer"></i>Oferta</span><span><i class="normal"></i>Normal (línea discontinua)</span><span><i class="discount"></i>Ahorro observado</span>'
      : '<span><i class="offer"></i>Precio observado</span>';

    const allPrices = offerRows.flatMap((point) => (
      meaningfulNormal && point.normal != null ? [point.offer, point.normal] : [point.offer]
    ));
    const width = 760;
    const height = 300;
    const plot = { left: 82, right: 18, top: 26, bottom: 54 };
    const rawMin = Math.min(...allPrices);
    const rawMax = Math.max(...allPrices);
    const spread = Math.max(rawMax - rawMin, Math.round(rawMax * 0.08), 1);
    const domainMin = Math.max(0, rawMin - spread * 0.12);
    const domainMax = rawMax + spread * 0.12;
    const toX = (index) => plot.left + (index * (width - plot.left - plot.right)) / Math.max(observations.length - 1, 1);
    const toY = (price) => plot.top + ((domainMax - price) * (height - plot.top - plot.bottom)) / (domainMax - domainMin);
    const offerPath = offerRows.map((point) => {
      const index = observations.indexOf(point);
      return `${toX(index).toFixed(1)},${toY(point.offer).toFixed(1)}`;
    }).join(" ");
    const normalRows = meaningfulNormal ? observations.filter((point) => point.normal != null) : [];
    const normalPath = normalRows.map((point) => {
      const index = observations.indexOf(point);
      return `${toX(index).toFixed(1)},${toY(point.normal).toFixed(1)}`;
    }).join(" ");
    const guides = [domainMin, (domainMin + domainMax) / 2, domainMax].map((value) => {
      const y = toY(value);
      return `<line class="chart-grid" x1="${plot.left}" x2="${width - plot.right}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/>
      <text class="axis price-axis" x="${plot.left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end">${money(Math.round(value))}</text>`;
    }).join("");
    const dates = limitedTickIndexes(observations.length).map((index) => {
      const anchor = chartAxisAnchor(index, observations.length);
      return `<text class="axis" x="${toX(index).toFixed(1)}" y="${height - 18}" text-anchor="${anchor}">${attr(timeLabel(observations[index].at))}</text>`;
    }).join("");
    const bands = observations.map((point, index) => {
      if (!meaningfulNormal || point.offer == null || point.normal == null || point.offer >= point.normal) return "";
      const x = toX(index);
      const top = toY(point.normal);
      const bottom = toY(point.offer);
      return `<rect class="chart-discount-band" x="${(x - 8).toFixed(1)}" y="${top.toFixed(1)}" width="16" height="${Math.max(bottom - top, 2).toFixed(1)}" rx="5"/>`;
    }).join("");
    const points = observations.map((point, index) => {
      if (point.offer == null) return "";
      const label = chartPointLabel(point, meaningfulNormal);
      const saving = meaningfulNormal && point.normal != null && point.offer < point.normal;
      return `<g class="chart-hit" data-chart-point="${index}" tabindex="0" role="button" aria-label="${attr(label)}">
      <circle class="chart-touch-target" cx="${toX(index).toFixed(1)}" cy="${toY(point.offer).toFixed(1)}" r="18"/>
      <circle class="chart-series chart-point offer${saving ? " discounted" : ""}" cx="${toX(index).toFixed(1)}" cy="${toY(point.offer).toFixed(1)}" r="4.5"><title>${attr(label)}</title></circle>
    </g>`;
    }).join("");
    const currentIndex = observations.length - 1;
    const minimumIndex = observations.findIndex((point) => point.offer === offerStats.min);
    const sameMarker = currentIndex === minimumIndex;
    const markers = `
    <circle class="chart-marker minimum" cx="${toX(minimumIndex).toFixed(1)}" cy="${toY(observations[minimumIndex].offer).toFixed(1)}" r="8">
      <title>Mínimo del día: ${money(offerStats.min)}</title>
    </circle>
    ${sameMarker ? "" : `<circle class="chart-marker current" cx="${toX(currentIndex).toFixed(1)}" cy="${toY(observations[currentIndex].offer).toFixed(1)}" r="8"><title>Precio actual: ${money(offerStats.current)}</title></circle>`}`;
    container.innerHTML = `
    <svg class="chart combined-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Historial Cyber del día con ${offerStats.count} observaciones. Actual ${money(offerStats.current)}; mínimo ${money(offerStats.min)}; máximo ${money(offerStats.max)}.">
      ${guides}${bands}
      ${normalRows.length > 1 ? `<polyline class="chart-series normal" fill="none" points="${normalPath}"/>` : ""}
      ${offerRows.length > 1 ? `<polyline class="chart-series offer" fill="none" stroke-width="3" points="${offerPath}"/>` : ""}
      ${markers}${points}${dates}
    </svg>`;
    const discounts = paired.filter((point) => point.offer < point.normal);
    note.textContent = meaningfulNormal
      ? `${offerStats.count} observaciones en el día · ${discounts.length} con ahorro frente al precio normal.`
      : `${offerStats.count} observaciones en el día · Oferta y normal fueron iguales cuando ambas se informaron; no hubo descuento publicado.`;
    mountChartPointInteractions(container, observations, meaningfulNormal);
  }

  async function load() {
    const params = new URLSearchParams(location.search);
    const n = params.get("n");
    const list = params.get("list") || "";
    const day = params.get("day") || "";
    const back = $("back-cyber");
    if (back) {
      back.href = list ? `/cyber-day?list=${encodeURIComponent(list)}` : "/cyber-day";
    }
    if (!n) {
      showFlash("Falta el parámetro n (número de query).", false);
      $("cyber-evo-meta").textContent = "Indicá ?n=… en la URL.";
      return;
    }
    const qs = new URLSearchParams({ n: String(n) });
    if (list) qs.set("list", list);
    if (day) qs.set("day", day);
    // n va en path; list/day en query.
    qs.delete("n");
    const query = qs.toString();
    const url = `/api/admin/cyber-day/items/${encodeURIComponent(n)}/evolution${query ? `?${query}` : ""}`;
    try {
      const payload = await apiJson(url);
      const title = payload.query
        ? `#${payload.n} · ${payload.query}`
        : `Query #${payload.n}`;
      document.title = `${title} · Evolución Cyber`;
      const h1 = $("page-title");
      if (h1) h1.textContent = title;
      const meta = $("cyber-evo-meta");
      if (meta) {
        meta.textContent = [
          payload.list_id ? `Lista ${payload.list_id}` : null,
          payload.day ? dayLabel(payload.day) : null,
          payload.timezone || SANTIAGO_TZ,
          payload.category || null,
          `${(payload.observations || []).length} observaciones`,
        ].filter(Boolean).join(" · ");
      }
      renderChart(payload);
    } catch (error) {
      showFlash(error.message || String(error), false);
      $("cyber-evo-meta").textContent = "No se pudo cargar el informe.";
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();

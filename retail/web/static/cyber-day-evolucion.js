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
    if (!point) return "";
    if (typeof publicStoreLabel === "function") {
      return String(publicStoreLabel(point.store, point.store_title || point.store) || "").trim();
    }
    const raw = String(point.store_title || point.store || "").trim();
    return raw.replace(/\s+Chile\s*$/i, "").trim() || raw;
  }

  function storeMeta(point) {
    return storeLabel(point) || "Sin tienda";
  }

  function cardMeta(point) {
    if (!point) return "";
    const time = timeLabel(point.at);
    const store = storeMeta(point);
    return `<small>${attr(time)} · ${attr(store)}</small>`;
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

  function extremeFromStats(stats, key) {
    if (!stats) return null;
    if (key === "menor_valor") {
      return {
        value: stats.min,
        at: stats.min_at,
        store: stats.min_store,
        store_title: stats.min_store_title,
      };
    }
    if (key === "mayor_valor") {
      return {
        value: stats.max,
        at: stats.max_at,
        store: stats.max_store,
        store_title: stats.max_store_title,
      };
    }
    if (key === "actual") {
      return {
        value: stats.current,
        at: stats.current_at,
        store: stats.current_store,
        store_title: stats.current_store_title,
      };
    }
    return null;
  }

  function summaryCards(stats, extremes) {
    if (!stats) return "";
    const changeLabel = stats.change_label
      || (stats.change === 0
        ? "Sin cambio"
        : `${stats.change > 0 ? "+" : "−"}${money(Math.abs(stats.change))}`);
    const menor = extremes?.menor_valor || extremeFromStats(stats, "menor_valor");
    const mayor = extremes?.mayor_valor || extremeFromStats(stats, "mayor_valor");
    const actual = extremes?.actual || extremeFromStats(stats, "actual");
    const mayorDesc = extremes?.mayor_descuento || null;
    const menorDesc = extremes?.menor_descuento || null;
    const cards = [
      {
        label: "Actual",
        value: money(stats.current),
        meta: cardMeta(actual),
      },
      {
        label: "Menor valor",
        value: money(menor?.value ?? stats.min),
        meta: cardMeta(menor),
      },
      {
        label: "Mayor valor",
        value: money(mayor?.value ?? stats.max),
        meta: cardMeta(mayor),
      },
      {
        label: "Mayor descuento",
        value: mayorDesc
          ? (mayorDesc.value_label || `${money(mayorDesc.value)} (${mayorDesc.saving_pct ?? "—"}%)`)
          : "—",
        meta: mayorDesc ? cardMeta(mayorDesc) : "<small>Sin ahorro vs normal</small>",
      },
      {
        label: "Menor descuento",
        value: menorDesc
          ? (menorDesc.value_label || `${money(menorDesc.value)} (${menorDesc.saving_pct ?? "—"}%)`)
          : "—",
        meta: menorDesc ? cardMeta(menorDesc) : "<small>Sin ahorro vs normal</small>",
      },
      {
        label: "Promedio",
        value: money(stats.average),
        meta: "",
      },
      {
        label: "Cambio",
        value: changeLabel,
        meta: "",
      },
    ];
    return cards.map(({ label, value, meta }) => (
      `<div><span>${label}</span><strong>${value}</strong>${meta || ""}</div>`
    )).join("");
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
        const saving = point.saving ?? (point.normal - point.offer);
        const pct = point.saving_pct ?? Math.round((saving * 100) / point.normal);
        parts.push(`Ahorro: ${money(saving)} (${pct}%)`);
      } else {
        parts.push("Sin descuento");
      }
    }
    parts.push(`Tienda: ${storeMeta(point)}`);
    return parts.join(" · ");
  }

  function renderObservationsList(observations, meaningfulNormal) {
    const list = $("chart-observations");
    if (!list) return;
    if (!observations.length) {
      list.innerHTML = "";
      list.hidden = true;
      return;
    }
    list.hidden = false;
    list.innerHTML = observations.map((point) => {
      const label = chartPointLabel(point, meaningfulNormal);
      return `<li><span class="obs-line">${attr(label)}</span></li>`;
    }).join("");
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

  const FORECAST_TRENDS = {
    down: ["Probable baja", "El precio estimado es menor que el actual."],
    up: ["Probable alza", "El precio estimado es mayor que el actual."],
    stable: ["Probablemente estable", "No se estima un cambio importante."],
  };

  const FORECAST_CONFIDENCE = { low: "Baja", medium: "Media", high: "Alta" };

  const FORECAST_BUY = {
    comprar: { className: "forecast-buy-yes", fallback: "Conviene comprar" },
    esperar: { className: "forecast-buy-wait", fallback: "Mejor esperar" },
    observar: { className: "forecast-buy-watch", fallback: "Sin señal clara" },
  };

  function forecastDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Fecha no disponible";
    return date.toLocaleString("es-CL", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: SANTIAGO_TZ,
    });
  }

  function buyAdviceMarkup(summary) {
    const advice = summary && summary.buy_advice;
    if (!advice || !advice.advice) return "";
    const meta = FORECAST_BUY[advice.advice] || FORECAST_BUY.observar;
    const label = advice.label || meta.fallback;
    const reason = advice.reason || "";
    return `
      <div class="forecast-buy ${attr(meta.className)}" role="status">
        <span>¿Conviene comprar en Cyber?</span>
        <strong>${attr(label)}</strong>
        <small>${attr(reason)}</small>
      </div>`;
  }

  function renderForecast(payload) {
    const box = $("cyber-evo-forecast-content");
    if (!box) return;
    const forecast = payload && payload.forecast;
    const summary = forecast && forecast.summary;
    if (!summary) {
      const empty = (forecast && forecast.empty_reason)
        || "Todavía no hay suficientes precios del día para un pronóstico experimental.";
      box.innerHTML = `<p class="muted">${attr(empty)}</p>`;
      return;
    }
    const trend = FORECAST_TRENDS[summary.trend] || FORECAST_TRENDS.stable;
    const isCyber = summary.mode === "cyber_event" || summary.model === "cyber_event_trend";
    const rangeNote = summary.range_has_uncertainty
      ? "Rango de incertidumbre calculado por el modelo."
      : "Banda entre los valores proyectados para el resto de la ventana Cyber.";
    const horizonNote = isCyber
      ? `${summary.horizon_days} día${summary.horizon_days === 1 ? "" : "s"} restantes de ventana Cyber · ${summary.observation_count || 0} observaciones`
      : `${summary.horizon_days} días estimados · ${summary.observation_count || 0} días analizados`;
    box.innerHTML = `
      ${buyAdviceMarkup(summary)}
      <div class="forecast-grid">
        <div class="forecast-stat"><span>Tendencia probable</span><strong class="forecast-${attr(summary.trend)}">${attr(trend[0])}</strong><small>${attr(trend[1])}</small></div>
        <div class="forecast-stat"><span>Rango esperado</span><strong>${money(summary.range_low)} – ${money(summary.range_high)}</strong><small>${attr(rangeNote)}</small></div>
        <div class="forecast-stat"><span>Nivel de confianza</span><strong>${attr(FORECAST_CONFIDENCE[summary.confidence] || "Baja")}</strong><small title="${attr(summary.confidence_reason || "")}">${attr(summary.confidence_reason || "")}</small></div>
        <div class="forecast-stat"><span>Generado</span><strong>${attr(forecastDate(summary.generated_at))}</strong><small>${attr(horizonNote)}</small></div>
      </div>`;
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
      renderObservationsList([], false);
      return;
    }

    const offerRows = observations.filter((point) => point.offer != null);
    const paired = observations.filter((point) => point.offer != null && point.normal != null);
    const meaningfulNormal = hasMeaningfulNormal(paired);
    const offerStats = payload.stats || (window.PriceHistory?.stats
      ? PriceHistory.stats(offerRows.map((point) => point.offer))
      : null);
    summary.innerHTML = summaryCards(offerStats, payload.extremes || null);
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
      <title>Menor valor del día: ${money(offerStats.min)} · ${attr(storeMeta(observations[minimumIndex]))}</title>
    </circle>
    ${sameMarker ? "" : `<circle class="chart-marker current" cx="${toX(currentIndex).toFixed(1)}" cy="${toY(observations[currentIndex].offer).toFixed(1)}" r="8"><title>Precio actual: ${money(offerStats.current)} · ${attr(storeMeta(observations[currentIndex]))}</title></circle>`}`;
    container.innerHTML = `
    <svg class="chart combined-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Historial Cyber del día con ${offerStats.count} observaciones. Actual ${money(offerStats.current)}; menor ${money(offerStats.min)}; mayor ${money(offerStats.max)}.">
      ${guides}${bands}
      ${normalRows.length > 1 ? `<polyline class="chart-series normal" fill="none" points="${normalPath}"/>` : ""}
      ${offerRows.length > 1 ? `<polyline class="chart-series offer" fill="none" stroke-width="3" points="${offerPath}"/>` : ""}
      ${markers}${points}${dates}
    </svg>`;
    const discounts = paired.filter((point) => point.offer < point.normal);
    note.textContent = meaningfulNormal
      ? `${offerStats.count} observaciones en el día · ${discounts.length} con ahorro frente al precio normal.`
      : `${offerStats.count} observaciones en el día · Oferta y normal fueron iguales cuando ambas se informaron; no hubo descuento publicado.`;
    renderObservationsList(observations, meaningfulNormal);
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
      renderForecast(payload);
    } catch (error) {
      showFlash(error.message || String(error), false);
      $("cyber-evo-meta").textContent = "No se pudo cargar el informe.";
      const forecastBox = $("cyber-evo-forecast-content");
      if (forecastBox) {
        forecastBox.innerHTML = `<p class="muted">No se pudo cargar el pronóstico experimental.</p>`;
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();

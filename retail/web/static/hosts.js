// Panel admin Recursos de hosts (/hosts). Solo admin; la API exige admin.
(function () {
  const el = (id) => document.getElementById(id);
  /** Último payload de hosts indexado por id (para el modal de características). */
  let lastHostsById = {};

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function apiJson(url) {
    const response = await fetch(url, { credentials: "same-origin" });
    if (response.status === 401 || response.status === 403) {
      location.href = `/entrar?next=${encodeURIComponent("/hosts")}`;
      throw new Error("auth");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function formatBytes(value, { si = false } = {}) {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) return "—";
    const base = si ? 1000 : 1024;
    const units = si
      ? ["B", "KB", "MB", "GB", "TB"]
      : ["B", "KiB", "MiB", "GiB", "TiB"];
    let v = n;
    let i = 0;
    while (v >= base && i < units.length - 1) {
      v /= base;
      i += 1;
    }
    const digits = i === 0 ? 0 : (v >= 10 ? 0 : 1);
    return `${v.toFixed(digits)} ${units[i]}`;
  }

  function formatUptime(seconds) {
    const n = Number(seconds);
    if (!Number.isFinite(n) || n < 0) return null;
    const days = Math.floor(n / 86400);
    const hours = Math.floor((n % 86400) / 3600);
    const mins = Math.floor((n % 3600) / 60);
    if (days >= 2) return `${days}d ${hours}h`;
    if (days >= 1) return `${days}d ${hours}h`;
    if (hours >= 1) return `${hours}h ${mins}m`;
    return `${mins}m`;
  }

  function gaugeSvg(percent, label, { display = null, titleSuffix = "%", empty = false } = {}) {
    const p = empty ? 0 : Math.max(0, Math.min(100, Number(percent) || 0));
    const r = 34;
    const c = 2 * Math.PI * r;
    const dash = (p / 100) * c;
    const tone = empty ? "empty" : (p >= 85 ? "hot" : (p >= 65 ? "warm" : "ok"));
    const center = display != null ? display : `${Math.round(p)}%`;
    const titleVal = display != null ? display : `${Math.round(p)}${titleSuffix}`;
    return `<div class="cyber-gauge cyber-gauge-${tone}" title="${escapeHtml(label)} ${escapeHtml(titleVal)}">
      <svg viewBox="0 0 80 80" width="80" height="80" aria-hidden="true">
        <circle class="cyber-gauge-track" cx="40" cy="40" r="${r}" />
        <circle class="cyber-gauge-fill" cx="40" cy="40" r="${r}"
          stroke-dasharray="${dash.toFixed(1)} ${c.toFixed(1)}"
          transform="rotate(-90 40 40)" />
        <text x="40" y="44" text-anchor="middle" class="cyber-gauge-pct">${escapeHtml(center)}</text>
      </svg>
      <span class="cyber-gauge-label">${escapeHtml(label)}</span>
    </div>`;
  }

  /** Mapea °C → % del anillo (0–100°C) y tono (warn 70 / hot 85). */
  function tempGaugePercent(celsius, thresholds) {
    const c = Number(celsius);
    if (!Number.isFinite(c)) return 0;
    const warn = Number(thresholds?.temp_warn);
    const hot = Number(thresholds?.temp_hot);
    const warnN = Number.isFinite(warn) ? warn : 70;
    const hotN = Number.isFinite(hot) ? hot : 85;
    // Escala no lineal: debajo de warn ocupa hasta 65%, warn→hot 65–85%, hot→100.
    if (c <= 0) return 0;
    if (c < warnN) return Math.min(64, (c / warnN) * 65);
    if (c < hotN) {
      const span = Math.max(1, hotN - warnN);
      return 65 + ((c - warnN) / span) * 20;
    }
    const over = Math.min(1, (c - hotN) / Math.max(15, 100 - hotN));
    return Math.min(100, 85 + over * 15);
  }

  function metricBlock(kind, data, thresholds) {
    const cpu = data || {};
    if (kind === "cpu") {
      const loads = [cpu.load1, cpu.load5, cpu.load15]
        .filter((v) => v != null)
        .join(" / ");
      const detail = [
        cpu.percent != null ? `usado ${cpu.percent}%` : null,
        cpu.cores != null ? `${cpu.cores} núcleos` : null,
        loads ? `load ${loads}` : null,
      ].filter(Boolean).join(" · ");
      return `<div class="cyber-host-metric">${gaugeSvg(cpu.percent, "CPU")}<p class="muted">${escapeHtml(detail || "sin datos")}</p></div>`;
    }
    if (kind === "ram") {
      const detail = [
        cpu.free_bytes != null ? `libre ${formatBytes(cpu.free_bytes)}` : null,
        cpu.used_bytes != null ? `usado ${formatBytes(cpu.used_bytes)}` : null,
        cpu.total_bytes != null ? `total ${formatBytes(cpu.total_bytes)}` : null,
      ].filter(Boolean).join(" · ");
      return `<div class="cyber-host-metric">${gaugeSvg(cpu.percent, "RAM")}<p class="muted">${escapeHtml(detail || "sin datos")}</p></div>`;
    }
    if (kind === "temp") {
      const c = cpu.celsius;
      if (c == null || !Number.isFinite(Number(c))) {
        return `<div class="cyber-host-metric cyber-host-metric-temp">${gaugeSvg(0, "Temp", { display: "—", empty: true })}`
          + `<p class="muted">sin sensor</p></div>`;
      }
      const rounded = Math.round(Number(c));
      const fill = tempGaugePercent(c, thresholds);
      const detail = [
        `${Number(c).toFixed(1)}°C`,
        cpu.source ? String(cpu.source) : null,
      ].filter(Boolean).join(" · ");
      return `<div class="cyber-host-metric cyber-host-metric-temp">${gaugeSvg(fill, "Temp", { display: `${rounded}°` })}`
        + `<p class="muted">${escapeHtml(detail)}</p></div>`;
    }
    const freeLine = cpu.free_bytes != null
      ? `<p class="hosts-disk-free">${escapeHtml(formatBytes(cpu.free_bytes))} libres</p>`
      : "";
    const detail = [
      cpu.used_bytes != null ? `usado ${formatBytes(cpu.used_bytes)}` : null,
      cpu.total_bytes != null ? `total ${formatBytes(cpu.total_bytes)}` : null,
      cpu.path ? `(${cpu.path})` : null,
    ].filter(Boolean).join(" · ");
    return `<div class="cyber-host-metric">${gaugeSvg(cpu.percent, "Disco")}${freeLine}<p class="muted">${escapeHtml(detail || "sin datos")}</p></div>`;
  }

  function dockerLine(docker) {
    if (!docker || typeof docker !== "object") return "";
    const parts = [];
    if (docker.images_bytes != null) {
      parts.push(`imágenes ${formatBytes(docker.images_bytes, { si: true })}`);
    }
    if (docker.images_reclaimable_bytes != null) {
      parts.push(`reclaimable ${formatBytes(docker.images_reclaimable_bytes, { si: true })}`);
    }
    if (docker.volumes_bytes != null) {
      parts.push(`vols ${formatBytes(docker.volumes_bytes, { si: true })}`);
    }
    if (!parts.length) return "";
    return `<p class="muted hosts-docker-line">Docker: ${escapeHtml(parts.join(" · "))}</p>`;
  }

  const HOST_CHART_COLORS = {
    bmax: "#258fdf",
    soyo: "#3ecf8e",
    orange_pi: "#e6a23c",
  };

  function historySeries(history, key) {
    const rows = Array.isArray(history) ? history : [];
    return rows
      .map((row) => {
        const n = Number(row?.[key]);
        return Number.isFinite(n) ? n : null;
      })
      .filter((v) => v != null);
  }

  function historyTimeRangeLabel(history) {
    const rows = Array.isArray(history) ? history : [];
    const times = rows
      .map((row) => Date.parse(String(row?.t || "")))
      .filter((t) => Number.isFinite(t));
    if (times.length < 2) return null;
    const spanMs = times[times.length - 1] - times[0];
    if (spanMs < 0) return null;
    const mins = Math.round(spanMs / 60000);
    if (mins < 90) return `últ. ${mins || 1} min`;
    const hours = Math.round(mins / 60);
    if (hours < 36) return `últ. ${hours} h`;
    return `últ. ${Math.round(hours / 24)} d`;
  }

  /** Sparkline SVG (serie numérica). */
  function sparklineSvg(values, {
    width = 160,
    height = 36,
    stroke = "currentColor",
    fill = "none",
    guide = null,
    ariaLabel = "",
  } = {}) {
    const nums = (Array.isArray(values) ? values : [])
      .map((v) => Number(v))
      .filter((v) => Number.isFinite(v));
    if (nums.length < 2) {
      return `<div class="hosts-spark hosts-spark-empty" title="Historial insuficiente">`
        + `<span class="muted">sin historial</span></div>`;
    }
    const padX = 2;
    const padY = 3;
    const min = Math.min(...nums);
    const max = Math.max(...nums);
    const span = Math.max(0.5, max - min);
    const innerW = width - padX * 2;
    const innerH = height - padY * 2;
    const points = nums.map((v, i) => {
      const x = padX + (nums.length === 1 ? innerW / 2 : (i / (nums.length - 1)) * innerW);
      const y = padY + (1 - (v - min) / span) * innerH;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    let guideLine = "";
    if (guide != null && Number.isFinite(Number(guide)) && Number(guide) >= min && Number(guide) <= max) {
      const gy = padY + (1 - (Number(guide) - min) / span) * innerH;
      guideLine = `<line class="hosts-spark-guide" x1="${padX}" y1="${gy.toFixed(1)}" x2="${(width - padX).toFixed(1)}" y2="${gy.toFixed(1)}" />`;
    }
    const last = nums[nums.length - 1];
    const lastX = points.split(" ").pop().split(",")[0];
    const lastY = points.split(" ").pop().split(",")[1];
    return `<svg class="hosts-spark-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}"`
      + ` role="img" aria-label="${escapeHtml(ariaLabel || "historial")}">`
      + guideLine
      + `<polyline class="hosts-spark-line" fill="${escapeHtml(fill)}" stroke="${escapeHtml(stroke)}"`
      + ` stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" points="${points}" />`
      + `<circle class="hosts-spark-dot" cx="${lastX}" cy="${lastY}" r="2.25" fill="${escapeHtml(stroke)}" />`
      + `<title>${escapeHtml(`${min.toFixed(0)}–${max.toFixed(0)} · ahora ${last.toFixed(1)}`)}</title>`
      + `</svg>`;
  }

  function hostSparklines(host, thresholds) {
    const history = Array.isArray(host?.history) ? host.history : [];
    const temps = historySeries(history, "temp");
    const cpus = historySeries(history, "cpu");
    if (temps.length < 2 && cpus.length < 2) return "";
    const range = historyTimeRangeLabel(history);
    const color = HOST_CHART_COLORS[host.id] || "var(--accent)";
    const warn = Number(thresholds?.temp_warn);
    const tempGuide = Number.isFinite(warn) ? warn : 70;
    const bits = [];
    if (temps.length >= 2) {
      bits.push(
        `<div class="hosts-spark-block">`
        + `<span class="hosts-spark-label">Temp</span>`
        + sparklineSvg(temps, {
          stroke: color,
          guide: tempGuide,
          ariaLabel: `Temperatura ${host.label || host.id}`,
        })
        + `</div>`
      );
    }
    if (cpus.length >= 2) {
      bits.push(
        `<div class="hosts-spark-block">`
        + `<span class="hosts-spark-label">CPU</span>`
        + sparklineSvg(cpus, {
          stroke: color,
          ariaLabel: `CPU ${host.label || host.id}`,
        })
        + `</div>`
      );
    }
    return `<div class="hosts-sparklines">`
      + bits.join("")
      + (range ? `<p class="muted hosts-spark-range">${escapeHtml(range)} · ${history.length} pts</p>` : "")
      + `</div>`;
  }

  /** Gráfico combinado (varios hosts) para una métrica. */
  function multiHostChart(hosts, key, {
    title,
    unit = "",
    yMin = null,
    yMax = null,
    guide = null,
    height = 120,
    width = 560,
  } = {}) {
    const series = [];
    for (const host of hosts) {
      const history = Array.isArray(host?.history) ? host.history : [];
      const points = history
        .map((row) => {
          const t = Date.parse(String(row?.t || ""));
          const v = Number(row?.[key]);
          if (!Number.isFinite(t) || !Number.isFinite(v)) return null;
          return { t, v };
        })
        .filter(Boolean);
      if (points.length >= 2) {
        series.push({
          id: host.id,
          label: host.label || host.id,
          color: HOST_CHART_COLORS[host.id] || "var(--accent)",
          points,
        });
      }
    }
    if (!series.length) return "";

    let tMin = Infinity;
    let tMax = -Infinity;
    let vMin = yMin != null ? yMin : Infinity;
    let vMax = yMax != null ? yMax : -Infinity;
    for (const s of series) {
      for (const p of s.points) {
        tMin = Math.min(tMin, p.t);
        tMax = Math.max(tMax, p.t);
        if (yMin == null) vMin = Math.min(vMin, p.v);
        if (yMax == null) vMax = Math.max(vMax, p.v);
      }
    }
    if (!(tMax > tMin)) return "";
    if (yMin == null && yMax == null) {
      const pad = Math.max(0.5, (vMax - vMin) * 0.12);
      vMin -= pad;
      vMax += pad;
    }
    if (!(vMax > vMin)) {
      vMin -= 1;
      vMax += 1;
    }

    const padL = 34;
    const padR = 10;
    const padT = 10;
    const padB = 22;
    const innerW = width - padL - padR;
    const innerH = height - padT - padB;
    const toX = (t) => padL + ((t - tMin) / (tMax - tMin)) * innerW;
    const toY = (v) => padT + (1 - (v - vMin) / (vMax - vMin)) * innerH;

    const gridYs = [vMin, (vMin + vMax) / 2, vMax];
    const grid = gridYs.map((v) => {
      const y = toY(v);
      return `<line class="hosts-chart-grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${(width - padR).toFixed(1)}" y2="${y.toFixed(1)}" />`
        + `<text class="hosts-chart-axis" x="${padL - 4}" y="${(y + 3).toFixed(1)}" text-anchor="end">${escapeHtml(`${Math.round(v)}${unit}`)}</text>`;
    }).join("");

    let guideEl = "";
    if (guide != null && Number.isFinite(Number(guide)) && Number(guide) >= vMin && Number(guide) <= vMax) {
      const gy = toY(Number(guide));
      guideEl = `<line class="hosts-chart-warn" x1="${padL}" y1="${gy.toFixed(1)}" x2="${(width - padR).toFixed(1)}" y2="${gy.toFixed(1)}" />`
        + `<text class="hosts-chart-axis hosts-chart-warn-label" x="${(width - padR).toFixed(1)}" y="${(gy - 3).toFixed(1)}" text-anchor="end">warn ${escapeHtml(String(Math.round(Number(guide))))}${escapeHtml(unit)}</text>`;
    }

    const paths = series.map((s) => {
      const d = s.points.map((p, i) => {
        const cmd = i === 0 ? "M" : "L";
        return `${cmd}${toX(p.t).toFixed(1)},${toY(p.v).toFixed(1)}`;
      }).join(" ");
      const last = s.points[s.points.length - 1];
      return `<path class="hosts-chart-series" d="${d}" fill="none" stroke="${escapeHtml(s.color)}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />`
        + `<circle cx="${toX(last.t).toFixed(1)}" cy="${toY(last.v).toFixed(1)}" r="3" fill="${escapeHtml(s.color)}" />`;
    }).join("");

    const legend = series.map((s) => {
      const last = s.points[s.points.length - 1].v;
      return `<span class="hosts-chart-legend-item">`
        + `<i style="background:${escapeHtml(s.color)}"></i>`
        + `${escapeHtml(s.label)} ${escapeHtml(last.toFixed(1))}${escapeHtml(unit)}`
        + `</span>`;
    }).join("");

    const spanMin = Math.max(1, Math.round((tMax - tMin) / 60000));
    const spanLabel = spanMin < 90 ? `${spanMin} min` : `${Math.round(spanMin / 60)} h`;

    return `<div class="hosts-chart-card">`
      + `<div class="hosts-chart-head"><strong>${escapeHtml(title)}</strong>`
      + `<span class="muted">${escapeHtml(spanLabel)}</span></div>`
      + `<div class="hosts-chart-legend">${legend}</div>`
      + `<svg class="hosts-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)}">`
      + grid + guideEl + paths
      + `</svg></div>`;
  }

  function renderTrends(payload) {
    const box = el("hosts-trends");
    if (!box) return;
    const hosts = Array.isArray(payload?.hosts) ? payload.hosts : [];
    const thresholds = payload?.thresholds || {};
    const tempChart = multiHostChart(hosts, "temp", {
      title: "Temperatura",
      unit: "°",
      guide: thresholds.temp_warn ?? 70,
      yMin: null,
      yMax: null,
    });
    const cpuChart = multiHostChart(hosts, "cpu", {
      title: "CPU",
      unit: "%",
      yMin: 0,
      yMax: 100,
    });
    if (!tempChart && !cpuChart) {
      const hasLiveTemp = hosts.some((h) => {
        const c = Number(h?.temperature?.celsius);
        return Number.isFinite(c);
      });
      const hasPartialHist = hosts.some((h) => Array.isArray(h?.history) && h.history.length >= 1);
      if (hasLiveTemp || hasPartialHist) {
        box.hidden = false;
        box.innerHTML = `<div class="hosts-trends-head">`
          + `<h3>Tendencias</h3>`
          + `<p class="muted">Acumulando historial (≥2 muestras) para graficar temperatura y CPU. El anillo Temp de cada tarjeta ya muestra el valor actual.</p>`
          + `</div>`;
        return;
      }
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = `<div class="hosts-trends-head">`
      + `<h3>Tendencias</h3>`
      + `<p class="muted">Historial publicado por cada host (retención acotada).</p>`
      + `</div>`
      + `<div class="hosts-trends-grid">${tempChart}${cpuChart}</div>`;
  }

  /** Comandos seguros sugeridos según código de alerta (copiar → pegar en el host). */
  const ALERT_COMMANDS = {
    docker_reclaim: [
      { label: "Ver uso Docker", cmd: "docker system df" },
      { label: "Imágenes dangling", cmd: "docker image prune -f" },
      { label: "Build cache", cmd: "docker builder prune -f" },
      { label: "Contenedores parados", cmd: "docker container prune -f" },
      {
        label: "Prune suave (sin -a ni volúmenes)",
        cmd: "docker system prune -f",
      },
    ],
    disk_hot: [
      { label: "Espacio en disco", cmd: "df -h" },
      { label: "Top /var", cmd: "sudo du -xh /var --max-depth=1 2>/dev/null | sort -h | tail -n 20" },
      { label: "Ver uso Docker", cmd: "docker system df" },
      { label: "Journal (liberar logs)", cmd: "sudo journalctl --vacuum-size=200M" },
    ],
    disk_warn: [
      { label: "Espacio en disco", cmd: "df -h" },
      { label: "Top /var", cmd: "sudo du -xh /var --max-depth=1 2>/dev/null | sort -h | tail -n 20" },
      { label: "Ver uso Docker", cmd: "docker system df" },
    ],
    ram_warn: [
      { label: "Memoria", cmd: "free -h" },
      { label: "Procesos por RAM", cmd: "ps aux --sort=-%mem | head -n 20" },
    ],
    temp_warn: [
      {
        label: "Temp thermal",
        cmd: "paste <(cat /sys/class/thermal/thermal_zone*/type) <(cat /sys/class/thermal/thermal_zone*/temp) 2>/dev/null || sensors 2>/dev/null || echo 'sin sensores'",
      },
      { label: "Load / top", cmd: "uptime; ps aux --sort=-%cpu | head -n 15" },
    ],
    temp_hot: [
      {
        label: "Temp thermal",
        cmd: "paste <(cat /sys/class/thermal/thermal_zone*/type) <(cat /sys/class/thermal/thermal_zone*/temp) 2>/dev/null || sensors 2>/dev/null || echo 'sin sensores'",
      },
      { label: "Load / top", cmd: "uptime; ps aux --sort=-%cpu | head -n 15" },
    ],
    stale: [
      { label: "Cron host-stats", cmd: "crontab -l | grep -n host-stats || true" },
      { label: "Último log report", cmd: "tail -n 40 ~/desarrollo/python/scraping-ficha/logs/host-stats-cron.log 2>/dev/null || tail -n 40 logs/host-stats-cron.log 2>/dev/null || echo 'sin log local'" },
    ],
    no_data: [
      { label: "Cron host-stats", cmd: "crontab -l | grep -n host-stats || true" },
      { label: "Probar report", cmd: "bash scripts/host-stats-report.sh" },
    ],
  };

  function wrapSsh(ssh, cmd) {
    if (!ssh || !cmd) return cmd || "";
    const escaped = String(cmd).replace(/'/g, `'\\''`);
    return `${ssh} '${escaped}'`;
  }

  function commandSuggestions(code) {
    const rows = ALERT_COMMANDS[code] || [];
    if (!rows.length) return "";
    // Docker reclaim: abierto por defecto (caso más frecuente en el banner).
    const openAttr = code === "docker_reclaim" ? " open" : "";
    return `<details class="hosts-cmd-details"${openAttr}>
      <summary>Comandos sugeridos</summary>
      <ul class="hosts-cmd-list">${rows.map((row) => (
        `<li class="hosts-cmd-row">`
        + `<span class="hosts-cmd-label">${escapeHtml(row.label)}</span>`
        + `<code class="hosts-cmd-code">${escapeHtml(row.cmd)}</code>`
        + `<button type="button" class="secondary hosts-cmd-copy" data-copy="${escapeHtml(row.cmd)}" title="Copiar comando">Copiar</button>`
        + `</li>`
      )).join("")}</ul>
      <p class="muted hosts-cmd-note">Seguros para diagnóstico / limpieza leve. Revisá antes de pegar en el host (SSH).</p>
    </details>`;
  }

  /** Checklist de mantenimiento (copiar acción o SSH+cmd). */
  const HOST_MAINTENANCE = [
    {
      group: "Actualizaciones",
      items: [
        {
          id: "apt_check",
          label: "Ver updates",
          title: "Listar paquetes actualizables",
          cmd: "sudo apt update && apt list --upgradable",
        },
        {
          id: "apt_upgrade",
          label: "Upgrade",
          title: "Actualizar paquetes (sin -y: confirmás en la terminal)",
          cmd: "sudo apt update && sudo apt upgrade",
        },
        {
          id: "reboot_needed",
          label: "¿Reinicio?",
          title: "Comprobar si hace falta reiniciar tras upgrades",
          cmd: "test -f /var/run/reboot-required && echo 'REINICIO PENDIENTE' || echo 'OK: sin reinicio pendiente'",
        },
        {
          id: "unattended",
          label: "Auto-upgrades",
          title: "Estado de unattended-upgrades",
          cmd: "systemctl is-active unattended-upgrades 2>/dev/null; systemctl is-enabled unattended-upgrades 2>/dev/null; cat /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null || echo 'sin 20auto-upgrades'",
        },
      ],
    },
    {
      group: "Firewall / red",
      items: [
        {
          id: "ufw_status",
          label: "Firewall",
          title: "Estado UFW",
          cmd: "sudo ufw status verbose",
        },
        {
          id: "ufw_numbered",
          label: "Reglas UFW",
          title: "Reglas numeradas (para delete/insert)",
          cmd: "sudo ufw status numbered",
        },
        {
          id: "ss_listen",
          label: "Puertos",
          title: "Puertos en escucha",
          cmd: "ss -tulpn",
        },
        {
          id: "fail2ban",
          label: "fail2ban",
          title: "Estado fail2ban",
          cmd: "sudo fail2ban-client status 2>/dev/null || echo 'fail2ban no instalado o sin permiso'",
        },
      ],
    },
    {
      group: "Sistema",
      items: [
        {
          id: "timedate",
          label: "Hora/NTP",
          title: "Sincronización de reloj",
          cmd: "timedatectl status",
        },
        {
          id: "journal",
          label: "Journal",
          title: "Uso de disco del journal",
          cmd: "sudo journalctl --disk-usage",
        },
        {
          id: "journal_vacuum",
          label: "Limpiar logs",
          title: "Recortar journal a 200M",
          cmd: "sudo journalctl --vacuum-size=200M",
        },
        {
          id: "df",
          label: "Disco",
          title: "Espacio en discos",
          cmd: "df -hT",
        },
      ],
    },
    {
      group: "Docker",
      items: [
        {
          id: "docker_df",
          label: "Docker df",
          title: "Uso y reclaimable de Docker",
          cmd: "docker system df",
        },
        {
          id: "docker_prune",
          label: "Prune suave",
          title: "Limpiar dangling (sin -a ni volúmenes)",
          cmd: "docker system prune -f",
        },
        {
          id: "docker_ps",
          label: "Contenedores",
          title: "Contenedores en ejecución",
          cmd: "docker ps",
        },
      ],
    },
  ];

  function maintenancePanel(host) {
    const ssh = host?.ssh || "";
    const groups = HOST_MAINTENANCE.map((group) => {
      const buttons = group.items.map((item) => {
        const remote = wrapSsh(ssh, item.cmd);
        return `<button type="button" class="secondary hosts-maint-btn"`
          + ` data-copy="${escapeHtml(remote)}"`
          + ` data-copy-local="${escapeHtml(item.cmd)}"`
          + ` title="${escapeHtml(item.title)}${ssh ? " · copia SSH+comando" : ""}">`
          + `${escapeHtml(item.label)}</button>`;
      }).join("");
      return `<div class="hosts-maint-group">`
        + `<span class="hosts-maint-group-label">${escapeHtml(group.group)}</span>`
        + `<div class="hosts-maint-actions">${buttons}</div>`
        + `</div>`;
    }).join("");
    return `<details class="hosts-maint">
      <summary>Mantenimiento</summary>
      <div class="hosts-maint-body">${groups}</div>
      <p class="muted hosts-cmd-note">Cada botón copia la acción${ssh ? " envuelta en SSH" : ""} para pegar en tu terminal. No se ejecuta en el servidor desde la web.</p>
    </details>`;
  }

  function alertBadges(alerts) {
    const rows = Array.isArray(alerts) ? alerts : [];
    if (!rows.length) return "";
    return `<ul class="hosts-alert-list">${rows.map((a) => (
      `<li class="hosts-alert hosts-alert-${escapeHtml(a.level || "info")}">`
      + `<div>${escapeHtml(a.message || a.code || "alerta")}</div>`
      + commandSuggestions(a.code)
      + `</li>`
    )).join("")}</ul>`;
  }

  function renderAlertsBanner(alerts) {
    const box = el("hosts-alerts");
    if (!box) return;
    const rows = Array.isArray(alerts) ? alerts : [];
    if (!rows.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = `<strong>Alertas</strong><ul>${rows.map((a) => (
      `<li class="hosts-alert hosts-alert-${escapeHtml(a.level || "info")}">`
      + `<div>`
      + `<span class="hosts-alert-host">${escapeHtml(a.label || a.host_id || "")}</span>`
      + ` ${escapeHtml(a.message || "")}</div>`
      + commandSuggestions(a.code)
      + `</li>`
    )).join("")}</ul>`;
  }

  function cardTone(host) {
    const alerts = Array.isArray(host.alerts) ? host.alerts : [];
    if (alerts.some((a) => a.level === "hot")) return "hot";
    if (alerts.some((a) => a.level === "warn") || host.stale || !host.online) return "warn";
    if (alerts.some((a) => a.level === "info")) return "info";
    return "ok";
  }

  const FACT_ROWS = [
    ["machine_model", "Modelo"],
    ["hostname", "Hostname"],
    ["cpu_model", "CPU"],
    ["cpu_cores", "Núcleos"],
    ["cpu_arch", "Arquitectura"],
    ["mem_total_bytes", "Memoria total"],
    ["disk_total_bytes", "Disco total"],
    ["os_pretty_name", "Sistema"],
    ["kernel", "Kernel"],
    ["uptime_seconds", "Uptime"],
  ];

  function formatFactCell(key, value) {
    if (value == null || value === "") return "—";
    if (key === "mem_total_bytes" || key === "disk_total_bytes") {
      return formatBytes(value);
    }
    if (key === "uptime_seconds") {
      const up = formatUptime(value);
      if (!up) return "—";
      const secs = Number(value);
      const extra = Number.isFinite(secs) ? ` (${Math.round(secs)}s)` : "";
      return `${up}${extra}`;
    }
    if (key === "cpu_cores") {
      const n = Number(value);
      return Number.isFinite(n) ? String(n) : "—";
    }
    return String(value);
  }

  function closeHostDetail() {
    const modal = el("hosts-detail-modal");
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove("modal-open");
  }

  function openHostDetail(hostId) {
    const host = lastHostsById[hostId];
    const modal = el("hosts-detail-modal");
    const body = el("hosts-detail-body");
    if (!host || !modal || !body) return;

    const facts = host.facts && typeof host.facts === "object" ? host.facts : {};
    // Hostname/uptime del reporte si facts no los trae aún.
    const merged = {
      ...facts,
      hostname: facts.hostname || host.hostname || null,
      uptime_seconds: facts.uptime_seconds != null ? facts.uptime_seconds : host.uptime_seconds,
      mem_total_bytes: facts.mem_total_bytes != null
        ? facts.mem_total_bytes
        : (host.ram && host.ram.total_bytes != null ? host.ram.total_bytes : null),
      disk_total_bytes: facts.disk_total_bytes != null
        ? facts.disk_total_bytes
        : (host.disk && host.disk.total_bytes != null ? host.disk.total_bytes : null),
      cpu_cores: facts.cpu_cores != null
        ? facts.cpu_cores
        : (host.cpu && host.cpu.cores != null ? host.cpu.cores : null),
    };
    const hasAny = FACT_ROWS.some(([key]) => {
      const v = merged[key];
      return v != null && v !== "";
    });
    const photo = host.image
      ? `<div class="hosts-photo" aria-hidden="true">`
        + `<img src="${escapeHtml(host.image)}" alt="" width="120" height="120" loading="lazy" decoding="async">`
        + `</div>`
      : `<div class="hosts-photo hosts-photo-empty" aria-hidden="true"></div>`;
    const sub = [host.ip, host.hostname].filter(Boolean).join(" · ");
    const rowsHtml = FACT_ROWS.map(([key, label]) => (
      `<tr><th scope="row">${escapeHtml(label)}</th>`
      + `<td>${escapeHtml(formatFactCell(key, merged[key]))}</td></tr>`
    )).join("");
    body.innerHTML = `<div class="hosts-detail-head">`
      + photo
      + `<div>`
      + `<h2 id="hosts-detail-title">${escapeHtml(host.label || host.id || "Host")}</h2>`
      + `<p class="muted">${escapeHtml(sub || "—")}</p>`
      + (host.role ? `<p class="hosts-detail-role">${escapeHtml(host.role)}</p>` : "")
      + `</div></div>`
      + (hasAny
        ? `<table class="hosts-facts-table"><tbody>${rowsHtml}</tbody></table>`
        : `<p class="muted hosts-facts-empty">Aún no hay características publicadas para este host. Se rellenan con cada reporte de host-stats.</p>`);
    modal.hidden = false;
    document.body.classList.add("modal-open");
    el("hosts-detail-close")?.focus();
  }

  function renderHosts(payload) {
    const grid = el("hosts-grid");
    const meta = el("hosts-meta");
    if (!grid) return;
    const rows = Array.isArray(payload?.hosts) ? payload.hosts : [];
    lastHostsById = {};
    for (const host of rows) {
      if (host?.id) lastHostsById[host.id] = host;
    }
    renderAlertsBanner(payload?.alerts);
    renderTrends(payload);
    if (!rows.length) {
      grid.innerHTML = `<p class="muted">Sin hosts configurados.</p>`;
      if (meta) meta.textContent = "";
      return;
    }
    const sorted = [...rows].sort((a, b) => {
      const rank = { hot: 3, warn: 2, info: 1, ok: 0 };
      return (rank[cardTone(b)] || 0) - (rank[cardTone(a)] || 0);
    });
    grid.innerHTML = sorted.map((host) => {
      const stale = Boolean(host.stale) || !host.online;
      const status = stale ? "stale" : "online";
      const statusLabel = host.online ? "en línea" : (host.reported_at ? "stale" : "sin datos");
      const tone = cardTone(host);
      const sub = [host.ip, host.hostname].filter(Boolean).join(" · ");
      const thresholds = payload?.thresholds || {};
      // Orden: CPU · RAM · Temp · Disco — Temp junto a RAM (mismo estilo de anillo).
      const gauges = host.cpu || host.ram || host.disk || host.temperature
        ? [
            metricBlock("cpu", host.cpu, thresholds),
            metricBlock("ram", host.ram, thresholds),
            metricBlock("temp", host.temperature, thresholds),
            metricBlock("disk", host.disk, thresholds),
          ].join("")
        : `<p class="muted">Aún no hay métricas publicadas para este host.</p>`;
      const uptime = formatUptime(host.uptime_seconds);
      const noteParts = [
        host.reported_at
          ? `Actualizado ${host.reported_at}${host.age_seconds != null ? ` · hace ${Math.round(host.age_seconds)}s` : ""}`
          : "Sin heartbeat",
        uptime ? `uptime ${uptime}` : null,
      ].filter(Boolean);
      const ssh = host.ssh
        ? `<button type="button" class="secondary hosts-ssh" data-ssh="${escapeHtml(host.ssh)}" title="Copiar SSH">${escapeHtml(host.ssh)}</button>`
        : "";
      const label = host.label || host.id || "Host";
      const photo = host.image
        ? `<div class="hosts-photo" aria-hidden="true">`
          + `<img src="${escapeHtml(host.image)}" alt="" width="160" height="160" loading="lazy" decoding="async">`
          + `</div>`
        : `<div class="hosts-photo hosts-photo-empty" aria-hidden="true"></div>`;
      return `<article class="cyber-host-panel hosts-card hosts-card-${status} hosts-card-tone-${tone}" data-host-id="${escapeHtml(host.id || "")}" tabindex="0" role="button" aria-label="Ver características de ${escapeHtml(label)}">
        <div class="hosts-card-top">
          ${photo}
          <div class="hosts-card-id">
            <div class="cyber-host-head">
              <strong>${escapeHtml(label)}</strong>
              <span class="muted">${escapeHtml(sub || "—")}</span>
              <span class="hosts-status hosts-status-${status}">${escapeHtml(statusLabel)}</span>
            </div>
            ${host.role ? `<p class="hosts-role">${escapeHtml(host.role)}</p>` : ""}
          </div>
        </div>
        ${alertBadges(host.alerts)}
        <div class="cyber-host-gauges">${gauges}</div>
        ${hostSparklines(host, thresholds)}
        ${dockerLine(host.docker)}
        ${ssh}
        ${maintenancePanel(host)}
        <p class="muted cyber-host-note">${escapeHtml(noteParts.join(" · "))}</p>
      </article>`;
    }).join("");
    if (meta) {
      const maxAge = payload?.max_age_seconds;
      const th = payload?.thresholds || {};
      const hist = payload?.history || {};
      const bits = [
        maxAge != null ? `Umbral stale: ${maxAge}s` : null,
        th.disk_warn != null ? `disco warn/hot ${th.disk_warn}/${th.disk_hot}%` : null,
        th.ram_warn != null ? `RAM warn ${th.ram_warn}%` : null,
        th.temp_warn != null ? `temp warn/hot ${th.temp_warn}/${th.temp_hot}°C` : null,
        hist.max_points != null ? `historial ≤${hist.max_points} pts` : null,
        "refresco cada 15s",
      ].filter(Boolean);
      meta.textContent = bits.join(" · ");
    }
  }

  function showFlash(message, isError) {
    const flash = el("flash");
    if (!flash) return;
    flash.hidden = !message;
    flash.textContent = message || "";
    flash.classList.toggle("error", Boolean(isError));
  }

  async function refresh() {
    try {
      const payload = await apiJson("/api/admin/hosts");
      renderHosts(payload);
      showFlash("");
    } catch (err) {
      if (String(err.message) === "auth") return;
      showFlash(err.message || "No se pudo cargar hosts", true);
    }
  }

  el("hosts-refresh")?.addEventListener("click", () => {
    refresh();
  });

  async function copyText(cmd, failMsg) {
    if (!cmd) return;
    try {
      await navigator.clipboard.writeText(cmd);
      const preview = cmd.length > 72 ? `${cmd.slice(0, 72)}…` : cmd;
      showFlash(`Copiado: ${preview}`, false);
      setTimeout(() => showFlash(""), 2500);
    } catch {
      showFlash(failMsg || "No se pudo copiar", true);
    }
  }

  el("hosts-grid")?.addEventListener("click", (event) => {
    const ssh = event.target.closest("[data-ssh]");
    if (ssh) {
      event.stopPropagation();
      copyText(ssh.getAttribute("data-ssh") || "", "No se pudo copiar el comando SSH");
      return;
    }
    const maint = event.target.closest(".hosts-maint-btn[data-copy]");
    if (maint) {
      event.stopPropagation();
      // Alt/Option: solo el comando local (sin SSH).
      const useLocal = event.altKey;
      const cmd = useLocal
        ? (maint.getAttribute("data-copy-local") || maint.getAttribute("data-copy") || "")
        : (maint.getAttribute("data-copy") || "");
      copyText(cmd, "No se pudo copiar la acción");
      return;
    }
    const copyBtn = event.target.closest("[data-copy]");
    if (copyBtn) {
      event.stopPropagation();
      copyText(copyBtn.getAttribute("data-copy") || "", "No se pudo copiar el comando");
      return;
    }
    // No abrir detalle al interactuar con botones / details / enlaces.
    if (event.target.closest("button, a, summary, details, input, select, textarea, label")) {
      return;
    }
    const card = event.target.closest(".hosts-card[data-host-id]");
    if (!card) return;
    openHostDetail(card.getAttribute("data-host-id") || "");
  });

  el("hosts-grid")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    if (event.target.closest("button, a, summary, details, input, select, textarea")) return;
    const card = event.target.closest(".hosts-card[data-host-id]");
    if (!card || event.target !== card) return;
    event.preventDefault();
    openHostDetail(card.getAttribute("data-host-id") || "");
  });

  el("hosts-alerts")?.addEventListener("click", (event) => {
    const copyBtn = event.target.closest("[data-copy]");
    if (!copyBtn) return;
    event.stopPropagation();
    copyText(copyBtn.getAttribute("data-copy") || "", "No se pudo copiar el comando");
  });

  el("hosts-detail-close")?.addEventListener("click", () => {
    closeHostDetail();
  });
  el("hosts-detail-modal")?.addEventListener("click", (event) => {
    if (event.target === el("hosts-detail-modal")) closeHostDetail();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const modal = el("hosts-detail-modal");
    if (modal && !modal.hidden) closeHostDetail();
  });

  refresh();
  setInterval(refresh, 15000);
})();

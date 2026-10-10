// Panel admin Recursos de hosts (/hosts). Solo admin; la API exige admin.
(function () {
  const el = (id) => document.getElementById(id);

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

  function gaugeSvg(percent, label) {
    const p = Math.max(0, Math.min(100, Number(percent) || 0));
    const r = 34;
    const c = 2 * Math.PI * r;
    const dash = (p / 100) * c;
    const tone = p >= 85 ? "hot" : (p >= 65 ? "warm" : "ok");
    return `<div class="cyber-gauge cyber-gauge-${tone}" title="${escapeHtml(label)} ${p}%">
      <svg viewBox="0 0 80 80" width="80" height="80" aria-hidden="true">
        <circle class="cyber-gauge-track" cx="40" cy="40" r="${r}" />
        <circle class="cyber-gauge-fill" cx="40" cy="40" r="${r}"
          stroke-dasharray="${dash.toFixed(1)} ${c.toFixed(1)}"
          transform="rotate(-90 40 40)" />
        <text x="40" y="44" text-anchor="middle" class="cyber-gauge-pct">${Math.round(p)}%</text>
      </svg>
      <span class="cyber-gauge-label">${escapeHtml(label)}</span>
    </div>`;
  }

  function metricBlock(kind, data) {
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

  function renderHosts(payload) {
    const grid = el("hosts-grid");
    const meta = el("hosts-meta");
    if (!grid) return;
    const rows = Array.isArray(payload?.hosts) ? payload.hosts : [];
    renderAlertsBanner(payload?.alerts);
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
      const gauges = host.cpu || host.ram || host.disk
        ? [
            metricBlock("cpu", host.cpu),
            metricBlock("ram", host.ram),
            metricBlock("disk", host.disk),
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
      return `<article class="cyber-host-panel hosts-card hosts-card-${status} hosts-card-tone-${tone}" data-host-id="${escapeHtml(host.id || "")}">
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
        ${dockerLine(host.docker)}
        ${ssh}
        ${maintenancePanel(host)}
        <p class="muted cyber-host-note">${escapeHtml(noteParts.join(" · "))}</p>
      </article>`;
    }).join("");
    if (meta) {
      const maxAge = payload?.max_age_seconds;
      const th = payload?.thresholds || {};
      const bits = [
        maxAge != null ? `Umbral stale: ${maxAge}s` : null,
        th.disk_warn != null ? `disco warn/hot ${th.disk_warn}/${th.disk_hot}%` : null,
        th.ram_warn != null ? `RAM warn ${th.ram_warn}%` : null,
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
      copyText(ssh.getAttribute("data-ssh") || "", "No se pudo copiar el comando SSH");
      return;
    }
    const maint = event.target.closest(".hosts-maint-btn[data-copy]");
    if (maint) {
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
      copyText(copyBtn.getAttribute("data-copy") || "", "No se pudo copiar el comando");
    }
  });

  el("hosts-alerts")?.addEventListener("click", (event) => {
    const copyBtn = event.target.closest("[data-copy]");
    if (!copyBtn) return;
    copyText(copyBtn.getAttribute("data-copy") || "", "No se pudo copiar el comando");
  });

  refresh();
  setInterval(refresh, 15000);
})();

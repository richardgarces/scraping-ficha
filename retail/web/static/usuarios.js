// Cuentas registradas (admin). Roles, membresía y mes de regalo.

const ROLES = {
  admin: "Administrador",
  paid: "De pago",
  user: "Usuario",
};

const STATUSES = {
  approved: "Aprobada",
  pending: "Pendiente",
  rejected: "Rechazada",
  invited: "Invitada",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  return date.toLocaleString("es-CL", {
    timeZone: "America/Santiago",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function json(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`);
    location.href = `/entrar?next=${next}`;
    throw new Error("Entra con la cuenta de administrador.");
  }
  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(typeof detail === "string" ? detail : (detail && detail.message) || response.statusText);
  }
  return payload;
}

function flash(text, ok = true) {
  const el = $("flash");
  el.hidden = false;
  el.className = ok ? "summary" : "err";
  el.textContent = text;
}

function roleLabel(role) {
  return ROLES[role] || "Usuario";
}

function statusLabel(status) {
  return STATUSES[status] || status || "—";
}

function badge(text, kind) {
  return `<span class="badge ${kind}">${escapeHtml(text)}</span>`;
}

function membershipCell(user) {
  const role = user.role || "user";
  if (role === "admin") {
    return badge("Admin (sin cupo)", "best");
  }
  const active = Boolean(user.membership_active ?? user.membership?.active);
  const expires = user.membership_expires_at || user.membership?.expires_at;
  const source = user.membership_source || user.membership?.source || "";
  if (!active) {
    return `<span class="muted">Sin membresía</span>`;
  }
  const src = source === "gift" || source === "promo" ? "regalo" : source === "admin" ? "admin" : "mensual";
  return `${badge("Activa", "best")} <span class="muted">${escapeHtml(src)} · hasta ${fmtDate(expires)}</span>`;
}

function roleSelect(user) {
  const role = user.role || "user";
  const options = ["user", "paid", "admin"]
    .map((value) => `<option value="${value}"${value === role ? " selected" : ""}>${escapeHtml(roleLabel(value))}</option>`)
    .join("");
  return `<select class="role-select" data-role-user="${escapeHtml(user.id)}" aria-label="Rol de ${escapeHtml(user.email || "")}">${options}</select>`;
}

function render(users) {
  const body = $("users-body");
  const rows = Array.isArray(users) ? users : [];
  $("users-meta").textContent = rows.length
    ? `${rows.length.toLocaleString("es-CL")} cuenta${rows.length === 1 ? "" : "s"}. Hora de Santiago.`
    : "Todavía no hay cuentas.";
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="9" class="muted">Todavía no hay usuarios registrados.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((user) => {
    const name = String(user.name || "").trim();
    const telegram = user.has_telegram ? badge("Sí", "best") : badge("No", "ghost");
    const statusKind = user.status === "rejected" ? "fake" : user.status === "pending" ? "off" : "ghost";
    const alerts = Number(user.price_alerts || 0).toLocaleString("es-CL");
    const limit = user.alert_limit ?? user.membership?.alert_limit;
    const alertLabel = limit != null ? `${alerts} / ${Number(limit).toLocaleString("es-CL")}` : alerts;
    return `
      <tr data-user-id="${escapeHtml(user.id)}">
        <td>${escapeHtml(user.email || "—")}</td>
        <td>${name ? escapeHtml(name) : '<span class="muted">—</span>'}</td>
        <td>${fmtDate(user.created_at)}</td>
        <td>${roleSelect(user)}</td>
        <td>${badge(statusLabel(user.status), statusKind)}</td>
        <td>${membershipCell(user)}</td>
        <td>${telegram}</td>
        <td class="price">${escapeHtml(alertLabel)}</td>
        <td class="user-actions">
          <button type="button" class="secondary" data-gift-user="${escapeHtml(user.id)}" ${user.role === "admin" ? "disabled title=\"El admin no necesita membresía\"" : ""}>1 mes regalo</button>
        </td>
      </tr>`;
  }).join("");
}

async function load() {
  $("users-meta").textContent = "Cargando…";
  try {
    const payload = await json("/api/admin/users");
    render(payload.users);
    $("flash").hidden = true;
  } catch (error) {
    if (String(error.message || "").includes("administrador")) return;
    $("users-body").innerHTML = '<tr><td colspan="9" class="muted">No se pudo cargar la lista.</td></tr>';
    $("users-meta").textContent = "Sin datos.";
    flash(error.message || "No se pudo cargar la lista.", false);
  }
}

$("reload").addEventListener("click", () => {
  load();
});

$("users-body").addEventListener("change", async (event) => {
  const select = event.target.closest("[data-role-user]");
  if (!select) return;
  const userId = select.dataset.roleUser;
  const role = select.value;
  select.disabled = true;
  try {
    const payload = await json(`/api/admin/users/${encodeURIComponent(userId)}/role`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    flash(`Rol actualizado: ${roleLabel(payload.user?.role || role)}.`, true);
    await load();
  } catch (error) {
    flash(error.message || "No se pudo cambiar el rol.", false);
    await load();
  } finally {
    select.disabled = false;
  }
});

$("users-body").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-gift-user]");
  if (!button || button.disabled) return;
  const userId = button.dataset.giftUser;
  button.disabled = true;
  try {
    const payload = await json(`/api/admin/users/${encodeURIComponent(userId)}/membership/gift`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ months: 1 }),
    });
    flash(payload.message || "Se otorgó 1 mes de regalo.", true);
    await load();
  } catch (error) {
    flash(error.message || "No se pudo otorgar el mes de regalo.", false);
    button.disabled = false;
  }
});

load();

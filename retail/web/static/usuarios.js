// Cuentas registradas (admin). No pinta hashes, tokens ni chats de Telegram.

const ROLES = {
  admin: "Administrador",
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

function roleLabel(role) {
  return ROLES[role] || "Usuario";
}

function statusLabel(status) {
  return STATUSES[status] || status || "—";
}

function badge(text, kind) {
  return `<span class="badge ${kind}">${escapeHtml(text)}</span>`;
}

function render(users) {
  const body = $("users-body");
  const rows = Array.isArray(users) ? users : [];
  $("users-meta").textContent = rows.length
    ? `${rows.length.toLocaleString("es-CL")} cuenta${rows.length === 1 ? "" : "s"}. Hora de Santiago.`
    : "Todavía no hay cuentas.";
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="muted">Todavía no hay usuarios registrados.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((user) => {
    const name = String(user.name || "").trim();
    const telegram = user.has_telegram ? badge("Sí", "best") : badge("No", "ghost");
    const role = user.role === "admin" ? badge(roleLabel(user.role), "best") : badge(roleLabel(user.role), "ghost");
    const statusKind = user.status === "rejected" ? "fake" : user.status === "pending" ? "off" : "ghost";
    const alerts = Number(user.price_alerts || 0).toLocaleString("es-CL");
    return `
      <tr>
        <td>${escapeHtml(user.email || "—")}</td>
        <td>${name ? escapeHtml(name) : '<span class="muted">—</span>'}</td>
        <td>${fmtDate(user.created_at)}</td>
        <td>${role}</td>
        <td>${badge(statusLabel(user.status), statusKind)}</td>
        <td>${telegram}</td>
        <td class="price">${alerts}</td>
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
    $("users-body").innerHTML = '<tr><td colspan="7" class="muted">No se pudo cargar la lista.</td></tr>';
    $("users-meta").textContent = "Sin datos.";
    flash(error.message || "No se pudo cargar la lista.", false);
  }
}

$("reload").addEventListener("click", () => {
  load();
});

load();

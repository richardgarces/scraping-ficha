function offerLoginHint() {
  const raw = new URLSearchParams(location.search).get("next") || "";
  if (raw.startsWith("/super")) return "Inicia sesión para ver super ofertas.";
  if (raw.startsWith("/reales")) return "Inicia sesión para ver ofertas reales.";
  if (raw.startsWith("/tiendas")) return "Solo administradores pueden ver el ranking de tiendas.";
  return "";
}

function nextPath(user) {
  const raw = new URLSearchParams(location.search).get("next");
  const fallback = user && user.role === "admin" ? "/ofertas" : "/siguiendo";
  if (!raw) return fallback;
  let dest = fallback;
  if (raw.startsWith("/") && !raw.startsWith("//") && !raw.includes("://") && !raw.includes("\\")) {
    dest = raw;
  }
  if (
    dest.startsWith("/ofertas")
    || dest.startsWith("/cron")
    || dest.startsWith("/cyber")
    || dest.startsWith("/estadisticas")
    || dest.startsWith("/usuarios")
    || dest.startsWith("/cotizaciones")
    || dest.startsWith("/tiendas")
  ) {
    if (!user || user.role !== "admin") {
      return "/siguiendo";
    }
  }
  return dest;
}

function showFlash(message) {
  const flash = $("flash");
  flash.hidden = false;
  flash.textContent = message;
}

function clearFlash() {
  const flash = $("flash");
  flash.hidden = true;
  flash.textContent = "";
}

function setMode(mode) {
  const inscribir = mode === "inscribir";
  const recover = mode === "recuperar";
  const reset = mode === "restablecer";
  $("login-form").hidden = inscribir || recover || reset;
  $("register-form").hidden = !inscribir;
  $("forgot-form").hidden = !recover;
  $("reset-form").hidden = !reset;
  $("tab-entrar").classList.toggle("current", !inscribir);
  $("tab-inscribir").classList.toggle("current", inscribir);
  $("auth-title").textContent = inscribir ? "Inscribirse" : recover ? "Recuperar clave" : reset ? "Crear nueva clave" : "Entrar";
  const hint = offerLoginHint();
  $("auth-copy").textContent = recover
    ? "Te enviaremos un enlace seguro a tu correo."
    : reset
      ? "El enlace funciona una sola vez."
      : inscribir
    ? "Crea una cuenta para guardar productos y seguir sus precios."
    : (hint || "Con tu cuenta puedes seguir productos y ver sus precios.");
  document.title = recover ? "Recuperar clave" : reset ? "Cambiar clave" : inscribir ? "Inscribirse" : "Entrar";
  document.querySelectorAll("[data-login-mode]").forEach((el) => {
    el.classList.toggle("current", inscribir ? el.dataset.loginMode === "inscribir" : el.dataset.loginMode === "entrar");
  });
}

$("tab-entrar").addEventListener("click", () => setMode("entrar"));
$("tab-inscribir").addEventListener("click", () => setMode("inscribir"));
$("forgot-link").addEventListener("click", () => setMode("recuperar"));
$("forgot-back").addEventListener("click", () => setMode("entrar"));
clearFlash();
const initialMode = new URLSearchParams(location.search).get("modo");
setMode(["inscribir", "recuperar", "restablecer"].includes(initialMode) ? initialMode : "entrar");

document.querySelectorAll(".pwd-toggle").forEach((button) => {
  const input = document.getElementById(button.getAttribute("aria-controls"));
  if (!input) return;
  button.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "Ocultar" : "Ver";
    button.setAttribute("aria-label", show ? "Ocultar clave" : "Ver clave");
    button.setAttribute("aria-pressed", show ? "true" : "false");
  });
});

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("flash").hidden = true;
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: $("email").value.trim(),
        password: $("password").value,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : "No se pudo entrar.");
    }
    location.href = nextPath(payload.user || {});
  } catch (error) {
    showFlash(error.message);
  }
});

$("forgot-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearFlash();
  try {
    const response = await fetch("/api/auth/password/forgot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("forgot-email").value.trim() }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "No se pudo procesar la solicitud.");
    showFlash(payload.message || "Revisa tu correo para continuar.");
    $("forgot-form").reset();
  } catch (error) {
    showFlash(error.message);
  }
});

$("reset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearFlash();
  const password = $("reset-password").value;
  if (password !== $("reset-password2").value) {
    showFlash("Las claves no coinciden.");
    return;
  }
  try {
    const response = await fetch("/api/auth/password/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: new URLSearchParams(location.search).get("token") || "", password }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "No se pudo cambiar la clave.");
    location.href = nextPath(payload.user || {});
  } catch (error) {
    showFlash(error.message);
  }
});

$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("flash").hidden = true;
  const password = $("reg-password").value;
  if (password !== $("reg-password2").value) {
    showFlash("Las claves no coinciden.");
    return;
  }
  const submit = $("register-submit");
  const originalLabel = submit.textContent;
  submit.disabled = true;
  submit.setAttribute("aria-busy", "true");
  submit.innerHTML = '<span class="spinner" aria-hidden="true"></span>Creando…';
  try {
    const response = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("reg-name").value.trim(),
        email: $("reg-email").value.trim(),
        password,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : "No se pudo inscribir.");
    }
    if (!payload.user || payload.user.status !== "approved") {
      showFlash(payload.message || "Revisa tu correo para confirmar la cuenta.");
      $("register-form").reset();
      return;
    }
    location.href = nextPath(payload.user);
  } catch (error) {
    showFlash(error.message);
  } finally {
    submit.disabled = false;
    submit.removeAttribute("aria-busy");
    submit.textContent = originalLabel;
  }
});

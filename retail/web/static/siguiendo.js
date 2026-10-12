// $, money, attr, discountOf, priceLadder, ensureUser y loginHref vienen de prices.js

function flash(text, ok = true, near) {
  const box = $("flash");
  if (box) {
    box.hidden = false;
    box.className = ok ? "summary notice-banner" : "err notice-banner";
    box.setAttribute("role", "status");
    box.textContent = text;
  }
  const anchor = near instanceof Element ? near : null;
  if (!anchor) {
    box?.scrollIntoView({ block: "nearest" });
    return;
  }
  if (anchor.id === "telegram-status") {
    anchor.hidden = false;
    anchor.textContent = text;
    anchor.className = `span telegram-connection ${ok ? "summary" : "err"}`;
    anchor.scrollIntoView({ block: "nearest" });
    return;
  }
  const host = anchor.closest("form, section") || anchor.parentElement;
  let status = host.querySelector("[data-action-status]");
  if (!status) {
    status = document.createElement("p");
    status.dataset.actionStatus = "1";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
  }
  const button = anchor.matches("button") ? anchor : host.querySelector('button[type="submit"]');
  if (button) button.insertAdjacentElement("afterend", status);
  else host.append(status);
  status.hidden = false;
  status.className = `action-status ${ok ? "summary" : "err"}`;
  status.textContent = text;
  status.scrollIntoView({ block: "nearest" });
}

async function saving(form, action) {
  const button = form.querySelector('button[type="submit"]');
  if (button?.disabled) return undefined;
  const label = button?.textContent || "Guardar";
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.innerHTML = '<span class="spinner" aria-hidden="true"></span>Guardando…';
  }
  try {
    return await action();
  } finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = label;
    }
  }
}

async function json(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) {
    location.href = loginHref("inscribir");
    throw new Error("Entra con tu cuenta para seguir productos.");
  }
  if (!response.ok) {
    const detail = payload.detail;
    const message = typeof detail === "string"
      ? detail
      : (detail && detail.message) || response.statusText;
    throw new Error(message);
  }
  return payload;
}

function storeLabel(store) {
  const key = String(store || "").trim().toLowerCase();
  if (!key) return "—";
  if (typeof window.storeTitle === "function") {
    try {
      return window.storeTitle(key) || key;
    } catch (_error) {
      /* fall through */
    }
  }
  return key;
}

function productHref(item) {
  const store = String(item.store || "").trim();
  const id = String(item.product_id || "").trim();
  if (!store || !id) return "";
  return `/producto?store=${encodeURIComponent(store)}&id=${encodeURIComponent(id)}`;
}

function alertThresholdLabel(item) {
  const target = Number(item.target_price);
  if (target > 0 && item.any_change === false) {
    return typeof money === "function" ? `≤ ${money(target)}` : `≤ ${target}`;
  }
  return "cualquier cambio";
}

function render(items) {
  $("watches").innerHTML = items.length
    ? items
        .map((item) => {
          const href = productHref(item);
          const name = item.name || item.product_id || "Producto";
          const title = href
            ? `<a href="${attr(href)}">${name}</a>`
            : name;
          return `
          <tr>
            <td>${title}</td>
            <td class="muted">${storeLabel(item.store)}</td>
            <td>${attr(alertThresholdLabel(item))}</td>
            <td><button type="button" class="secondary remove" data-store="${attr(item.store)}" data-id="${attr(item.product_id)}">Quitar alerta</button></td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="4" class="muted">No tienes alertas activas. En la ficha de un producto usa «Activar alerta».</td></tr>`;
}

async function load() {
  render(await json("/api/price-alerts"));
}

function checked(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((item) => item.value);
}

function setChecked(name, values) {
  document.querySelectorAll(`input[name="${name}"]`).forEach((item) => {
    item.checked = (values || []).includes(item.value);
  });
}

function renderTelegramStatus(connected, telegram = "") {
  const status = $("telegram-status");
  const guide = $("telegram-guide");
  if (guide) guide.hidden = connected;
  status.textContent = connected
    ? `Telegram conectado${telegram ? ` como ${telegram}` : ""}. Las alertas llegarán a este chat.`
    : "Telegram aún no está conectado.";
  status.className = connected ? "summary span telegram-connection" : "muted span telegram-connection";
}

let pushRegistration = null;
let pushSubscription = null;
let pushPublicKey = "";
const PUSH_SW_URL = "/push-sw-v3.js";

function pushKeyBytes(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const raw = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

function renderPushStatus() {
  const status = $("push-status");
  const button = $("push-toggle");
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    status.textContent = "Este navegador no admite notificaciones push.";
    button.hidden = true;
    return;
  }
  button.hidden = false;
  if (Notification.permission === "denied") {
    status.textContent = "Las notificaciones están bloqueadas en la configuración del navegador.";
    button.textContent = "Notificaciones bloqueadas";
    button.disabled = true;
    return;
  }
  button.disabled = false;
  status.textContent = pushSubscription
    ? "Este dispositivo recibirá tus alertas incluso cuando la página esté cerrada."
    : "Actívalas para recibir alertas aunque la página esté cerrada.";
  button.textContent = pushSubscription ? "Desactivar en este dispositivo" : "Activar en este dispositivo";
}

async function loadPushState() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    renderPushStatus();
    return;
  }
  const config = await json("/api/account/push");
  pushPublicKey = config.public_key || "";
  pushRegistration = await navigator.serviceWorker.register(PUSH_SW_URL, { scope: "/" });
  pushSubscription = await pushRegistration.pushManager.getSubscription();
  renderPushStatus();
}

async function togglePush() {
  if (pushSubscription) {
    await json("/api/account/push", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: pushSubscription.endpoint }),
    });
    await pushSubscription.unsubscribe();
    pushSubscription = null;
    const pushChannel = document.querySelector('input[name="notice-channel"][value="push"]');
    if (pushChannel) pushChannel.checked = false;
    renderPushStatus();
    flash("Las notificaciones push se desactivaron en este dispositivo.", true, $("push-toggle"));
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    renderPushStatus();
    throw new Error("El navegador no autorizó las notificaciones.");
  }
  if (!pushRegistration) pushRegistration = await navigator.serviceWorker.register(PUSH_SW_URL, { scope: "/" });
  pushSubscription = await pushRegistration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: pushKeyBytes(pushPublicKey),
  });
  await json("/api/account/push", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pushSubscription.toJSON()),
  });
  const pushChannel = document.querySelector('input[name="notice-channel"][value="push"]');
  if (pushChannel) pushChannel.checked = true;
  renderPushStatus();
  flash("Este dispositivo ya recibirá tus alertas push.", true, $("push-toggle"));
}

function renderEmailCategories(categories, selected) {
  const chosen = new Set(selected || []);
  $("email-categories").innerHTML = (categories || []).map((category) => `
    <label>
      <input type="checkbox" name="email-category" value="${attr(category.id)}" ${chosen.has(category.id) ? "checked" : ""}>
      ${attr(category.title)}
    </label>
  `).join("");
  refreshEmailCategorySummary();
}

function refreshEmailCategorySummary() {
  const boxes = [...document.querySelectorAll('input[name="email-category"]')];
  const selected = boxes.filter((item) => item.checked).length;
  $("email-category-count").textContent = selected
    ? `${selected} ${selected === 1 ? "categoría seleccionada" : "categorías seleccionadas"}`
    : "Todas las categorías";
}

function hasAdvancedAccountPrefs(user) {
  const tier = user?.membership?.tier || (user?.role === "admin" ? "admin" : "user");
  return tier === "paid" || tier === "admin";
}

function applyAdvancedPrefsVisibility(user) {
  const advanced = hasAdvancedAccountPrefs(user);
  const filters = $("advanced-notification-prefs");
  const upgrade = $("advanced-prefs-upgrade");
  const stores = $("store-preferences-panel");
  const storesUpgrade = $("store-preferences-upgrade");
  if (filters) filters.hidden = !advanced;
  if (upgrade) upgrade.hidden = advanced;
  if (stores) stores.hidden = !advanced;
  if (storesUpgrade) storesUpgrade.hidden = advanced;
}

async function loadNotifications() {
  const data = await json("/api/account/notifications");
  const preferences = data.preferences || {};
  setChecked("notice-channel", preferences.channels);
  setChecked("notice-kind", preferences.kinds);
  $("notice-email").value = data.email || "";
  $("notice-telegram").value = data.telegram || "";
  renderTelegramStatus(Boolean(data.telegram_connected), data.telegram || "");
  if (hasAdvancedAccountPrefs(window.retailUser)) {
    $("min-discount-self").value = preferences.min_discount_self ?? 0;
    $("min-discount-stores").value = preferences.min_discount_other_stores ?? 0;
    $("email-min-real-discount").value = preferences.email_min_real_discount ?? 0;
    renderEmailCategories(data.notification_categories, preferences.email_categories);
  }
  const predictive = data.predictive || {};
  const anticipated = predictive.anticipated || {};
  const baseStatus = predictive.enabled
    ? `Alertas predictivas habilitadas: ${predictive.evaluated_series || 0} series validadas.`
    : `Puedes dejar la opción activada, pero no enviaremos alertas hasta comprobar su precisión. ${predictive.reason || "Validación pendiente."}`;
  const anticipatedStatus = anticipated.enabled
    ? " Los avisos anticipados de baja también superaron la validación reforzada."
    : ` Los avisos anticipados permanecen bloqueados: ${anticipated.reason || "requieren mayor precisión."}`;
  $("predictive-status").textContent = baseStatus + anticipatedStatus;
}

let storePreferenceData = { stores: [], favorites: [], excluded: [] };

function renderStorePreferences(filter = "") {
  const term = filter.trim().toLocaleLowerCase("es");
  const favorites = new Set(storePreferenceData.favorites || []);
  const excluded = new Set(storePreferenceData.excluded || []);
  const visible = (storePreferenceData.stores || []).filter((store) =>
    !term || `${store.title} ${store.group_title}`.toLocaleLowerCase("es").includes(term)
  );
  const groups = new Map();
  visible.forEach((store) => {
    if (!groups.has(store.group_title)) groups.set(store.group_title, []);
    groups.get(store.group_title).push(store);
  });
  $("store-preference-list").innerHTML = [...groups.entries()].map(([group, stores]) => `
    <details class="store-preference-group">
      <summary><span>${attr(group)}</span><small>${stores.length} ${stores.length === 1 ? "tienda" : "tiendas"}</small></summary>
      <div class="group-state-control" data-store-group="${attr(group)}" aria-label="Aplicar preferencia a toda la categoría">
        <span>Aplicar a toda la categoría</span>
        <button type="button" class="secondary" data-group-state="normal">Normal</button>
        <button type="button" class="secondary" data-group-state="favorite">★ Preferida</button>
        <button type="button" class="secondary" data-group-state="excluded">⊘ Excluir</button>
      </div>
      <div class="store-preference-grid">
        ${stores.map((store) => {
          const state = excluded.has(store.id) ? "excluded" : favorites.has(store.id) ? "favorite" : "normal";
          const radioName = `store-state-${store.id}`;
          return `
          <article class="store-preference-row" data-store-row="${attr(store.id)}" data-state="${state}">
            <div class="store-preference-name"><span class="store-avatar" aria-hidden="true">${attr(store.title.slice(0, 1).toUpperCase())}</span><strong>${attr(store.title)}</strong></div>
            <div class="store-state-control" role="radiogroup" aria-label="Preferencia para ${attr(store.title)}">
              <label><input type="radio" name="${attr(radioName)}" data-store-state="${attr(store.id)}" value="normal" ${state === "normal" ? "checked" : ""}><span>Normal</span></label>
              <label><input type="radio" name="${attr(radioName)}" data-store-state="${attr(store.id)}" value="favorite" ${state === "favorite" ? "checked" : ""}><span>★ Preferida</span></label>
              <label><input type="radio" name="${attr(radioName)}" data-store-state="${attr(store.id)}" value="excluded" ${state === "excluded" ? "checked" : ""}><span>⊘ Excluir</span></label>
            </div>
          </article>`;
        }).join("")}
      </div>
    </details>`).join("") || '<p class="muted empty-preferences">No hay tiendas que coincidan con ese nombre.</p>';
  refreshStorePreferenceSummary();
}

function refreshStorePreferenceSummary() {
  const favorites = (storePreferenceData.favorites || []).length;
  const excluded = (storePreferenceData.excluded || []).length;
  $("favorite-store-count").textContent = favorites;
  $("excluded-store-count").textContent = excluded;
  $("store-preference-summary").textContent = favorites || excluded
    ? `${favorites} ${favorites === 1 ? "preferida" : "preferidas"} · ${excluded} ${excluded === 1 ? "excluida" : "excluidas"}`
    : "Todas las tiendas se tratarán de forma normal.";
}

async function loadStorePreferences() {
  storePreferenceData = await json("/api/account/store-preferences");
  renderStorePreferences($("store-preference-filter").value);
}

$("store-preference-filter")?.addEventListener("input", (event) => renderStorePreferences(event.target.value));

$("store-preference-list")?.addEventListener("change", (event) => {
  const input = event.target.closest("input[data-store-state]");
  if (!input) return;
  const favorites = new Set(storePreferenceData.favorites || []);
  const excluded = new Set(storePreferenceData.excluded || []);
  const storeId = input.dataset.storeState;
  favorites.delete(storeId);
  excluded.delete(storeId);
  if (input.value === "favorite") favorites.add(storeId);
  if (input.value === "excluded") excluded.add(storeId);
  storePreferenceData.favorites = [...favorites];
  storePreferenceData.excluded = [...excluded];
  const row = input.closest(".store-preference-row");
  if (row) row.dataset.state = input.value;
  refreshStorePreferenceSummary();
});

$("store-preference-list")?.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-group-state]");
  if (!button) return;
  const control = button.closest("[data-store-group]");
  const group = control?.dataset.storeGroup;
  const state = button.dataset.groupState;
  if (!group || !["normal", "favorite", "excluded"].includes(state)) return;
  const favorites = new Set(storePreferenceData.favorites || []);
  const excluded = new Set(storePreferenceData.excluded || []);
  (storePreferenceData.stores || []).filter((store) => store.group_title === group).forEach((store) => {
    favorites.delete(store.id);
    excluded.delete(store.id);
    if (state === "favorite") favorites.add(store.id);
    if (state === "excluded") excluded.add(store.id);
  });
  storePreferenceData.favorites = [...favorites];
  storePreferenceData.excluded = [...excluded];
  renderStorePreferences($("store-preference-filter").value);
});

$("store-preferences-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!hasAdvancedAccountPrefs(window.retailUser)) {
    flash("Las tiendas preferidas y excluidas forman parte de la membresía.", false, form);
    return;
  }
  try {
    const data = await saving(form, () => json("/api/account/store-preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        favorites: storePreferenceData.favorites || [],
        excluded: storePreferenceData.excluded || [],
      }),
    }));
    if (data === undefined) return;
    storePreferenceData = data;
    renderStorePreferences($("store-preference-filter").value);
    flash("Tus tiendas preferidas y excluidas quedaron guardadas.", true, form);
  } catch (error) {
    flash(error.message, false, form);
  }
});

$("password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const newPassword = $("new-password").value;
  if (newPassword !== $("new-password2").value) {
    flash("Las claves nuevas no coinciden.", false, form);
    return;
  }
  try {
    const saved = await saving(form, () => json("/api/account/password", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: $("current-password").value, new_password: newPassword }),
    }));
    if (saved === undefined) return;
    form.reset();
    flash("Tu clave quedó actualizada.", true, form);
  } catch (error) {
    flash(error.message, false, form);
  }
});

$("notification-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const preferences = {
      channels: checked("notice-channel"),
      kinds: checked("notice-kind"),
    };
    if (hasAdvancedAccountPrefs(window.retailUser)) {
      preferences.min_discount_self = $("min-discount-self").value;
      preferences.min_discount_other_stores = $("min-discount-stores").value;
      preferences.email_categories = checked("email-category");
      preferences.email_min_real_discount = $("email-min-real-discount").value;
    }
    const data = await saving(form, () => json("/api/account/notifications", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        telegram: $("notice-telegram").value.trim(),
        preferences,
      }),
    }));
    if (data === undefined) return;
    renderTelegramStatus(Boolean(data.telegram_connected), data.telegram || "");
    flash("Tus preferencias de notificación quedaron guardadas.", true, form);
  } catch (error) {
    flash(error.message, false, form);
  }
});

$("telegram-connect").addEventListener("click", async () => {
  // Abrimos la ventana durante el click para que el navegador no bloquee el enlace.
  const telegramWindow = window.open("about:blank", "_blank");
  try {
    const data = await json("/api/account/telegram/link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ telegram: $("notice-telegram").value.trim() }),
    });
    if (telegramWindow) telegramWindow.location = data.url;
    else location.href = data.url;
    renderTelegramStatus(false, $("notice-telegram").value.trim());
    flash(`Se abrió ${data.bot_username}. Presiona Iniciar y vuelve aquí para presionar Verificar conexión.`, true, $("telegram-status"));
  } catch (error) {
    if (telegramWindow) telegramWindow.close();
    flash(error.message || "No se pudo abrir Telegram.", false, $("telegram-status"));
  }
});

$("push-toggle").addEventListener("click", () => {
  togglePush().catch((error) => flash(error.message, false, $("push-toggle")));
});

$("telegram-verify").addEventListener("click", async () => {
  const button = $("telegram-verify");
  if (button.disabled) return;
  const label = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Verificando…";
  const status = $("telegram-status");
  status.hidden = false;
  status.textContent = "Verificando la conexión con Telegram…";
  status.className = "span telegram-connection is-checking";
  status.scrollIntoView({ block: "nearest" });
  try {
    const data = await json("/api/account/telegram/verify", { method: "POST" });
    const telegram = data.telegram || "";
    $("notice-telegram").value = telegram || $("notice-telegram").value;
    const who = telegram ? ` como ${telegram}` : "";
    const guide = $("telegram-guide");
    if (guide) guide.hidden = true;
    flash(`Telegram conectado${who}. Las alertas llegarán a este chat.`, true, status);
  } catch (error) {
    const guide = $("telegram-guide");
    if (guide) guide.hidden = false;
    flash(error.message || "No se pudo verificar la conexión.", false, status);
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = label;
  }
});

$("email-categories")?.addEventListener("change", refreshEmailCategorySummary);

$("email-categories-all")?.addEventListener("click", () => {
  document.querySelectorAll('input[name="email-category"]').forEach((item) => { item.checked = true; });
  refreshEmailCategorySummary();
});

$("email-categories-none")?.addEventListener("click", () => {
  document.querySelectorAll('input[name="email-category"]').forEach((item) => { item.checked = false; });
  refreshEmailCategorySummary();
});

$("watches").addEventListener("click", async (event) => {
  const button = event.target.closest(".remove");
  if (!button) return;
  const store = button.dataset.store || "";
  const productId = button.dataset.id || "";
  if (!store || !productId) return;
  try {
    const params = new URLSearchParams({ store, id: productId });
    await json(`/api/price-alert?${params}`, { method: "DELETE" });
    await Promise.all([load(), loadMembership()]);
    flash("Alerta quitada.", true, button);
  } catch (error) {
    flash(error.message, false, button);
  }
});

function fmtMembershipDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("es-CL", {
    timeZone: "America/Santiago",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

async function loadMembership() {
  const panel = $("membership-panel");
  if (!panel) return;
  try {
    const data = await json("/api/account/membership");
    const membership = data.membership || {};
    const quota = data.quota || {};
    const role = data.user?.role || "user";
    const summary = $("membership-summary");
    const quotaEl = $("membership-quota");
    if (role === "admin") {
      summary.textContent = "Cuenta administrador.";
      quotaEl.textContent = `Alertas activas: ${quota.count ?? 0}.`;
      $("promo-form").hidden = true;
      return;
    }
    $("promo-form").hidden = false;
    if (membership.active) {
      const until = fmtMembershipDate(membership.expires_at);
      const source = membership.source === "gift" || membership.source === "promo"
        ? " (regalo)"
        : membership.source === "admin"
          ? " (otorgada por admin)"
          : "";
      summary.textContent = `Membresía mensual activa${source}${until ? ` hasta ${until}` : ""}.`;
    } else {
      summary.textContent = "Cuenta gratuita. Activa la membresía o canjea un mes de regalo para seguir más productos.";
    }
    quotaEl.textContent = `Alertas: ${quota.count ?? 0} de ${quota.limit ?? 3}.`;
  } catch (error) {
    $("membership-summary").textContent = error.message || "No se pudo cargar la membresía.";
  }
}

$("promo-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const data = await saving(form, () => json("/api/account/membership/promo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: $("promo-code").value.trim() }),
    }));
    if (data === undefined) return;
    $("promo-code").value = "";
    flash(data.message || "Membresía de regalo activada.", true, form);
    if (data.user) window.retailUser = { ...(window.retailUser || {}), ...data.user };
    await loadMembership();
    applyAdvancedPrefsVisibility(window.retailUser);
    if (hasAdvancedAccountPrefs(window.retailUser)) {
      await Promise.all([loadNotifications(), loadStorePreferences()]);
    }
  } catch (error) {
    flash(error.message || "No se pudo canjear el código.", false, form);
  }
});

async function ready() {
  const user = await ensureUser();
  window.retailUser = user || null;
  $("guest-box").hidden = Boolean(user);
  $("membership-panel").hidden = !user;
  $("watch-panel").hidden = !user;
  $("watch-list").hidden = !user;
  $("notification-panel").hidden = !user;
  $("password-panel").hidden = !user;
  if (!user) {
    if ($("store-preferences-panel")) $("store-preferences-panel").hidden = true;
    if ($("store-preferences-upgrade")) $("store-preferences-upgrade").hidden = true;
    if ($("advanced-notification-prefs")) $("advanced-notification-prefs").hidden = true;
    if ($("advanced-prefs-upgrade")) $("advanced-prefs-upgrade").hidden = true;
    render([]);
    return;
  }
  applyAdvancedPrefsVisibility(user);
  const loaders = [load(), loadNotifications(), loadPushState(), loadMembership()];
  if (hasAdvancedAccountPrefs(user)) loaders.push(loadStorePreferences());
  await Promise.all(loaders);
  applyAdvancedPrefsVisibility(user);
  if (location.hash === "#membresia") {
    $("membership-panel")?.scrollIntoView({ block: "start" });
  }
}

ready().catch((error) => flash(error.message, false));

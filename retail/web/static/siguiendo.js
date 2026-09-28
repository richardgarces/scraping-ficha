// $, money, attr, discountOf, priceLadder, ensureUser y loginHref vienen de prices.js

function flash(text, ok = true) {
  $("flash").hidden = false;
  $("flash").className = ok ? "summary" : "err";
  $("flash").textContent = text;
}

async function json(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) {
    location.href = loginHref("inscribir");
    throw new Error("Entra con tu cuenta para seguir productos.");
  }
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : response.statusText);
  }
  return payload;
}

function target(item) {
  if (item.target_price) return `bajo ${money(item.target_price)}`;
  if (item.drop_percent) return `baja ${item.drop_percent}%`;
  return "cualquier cambio";
}

function render(items) {
  $("watches").innerHTML = items.length
    ? items
        .map(
          (item) => `
          <tr>
            <td>${item.name || item.query}</td>
            <td class="muted">${item.query}</td>
            <td>${target(item)}</td>
            <td class="muted">${item.last_notified_price ? money(item.last_notified_price) : "sin avisos"}</td>
            <td><button type="button" class="secondary remove" data-id="${attr(item.id)}">Dejar de seguir</button></td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="5" class="muted">Todavía no sigues ningún producto. Búscalo y usa el botón "Seguir".</td></tr>`;
}

async function load() {
  render(await json("/api/watches"));
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
  status.textContent = connected
    ? `Telegram conectado${telegram ? ` como ${telegram}` : ""}. Las alertas llegarán a este chat.`
    : "Telegram aún no está conectado. Abre el bot, presiona Iniciar y luego verifica la conexión.";
  status.className = connected ? "summary span" : "muted span";
}

let pushRegistration = null;
let pushSubscription = null;
let pushPublicKey = "";

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
  pushRegistration = await navigator.serviceWorker.register("/push-sw-v1.js", { scope: "/" });
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
    flash("Las notificaciones push se desactivaron en este dispositivo.");
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    renderPushStatus();
    throw new Error("El navegador no autorizó las notificaciones.");
  }
  if (!pushRegistration) pushRegistration = await navigator.serviceWorker.register("/push-sw-v1.js", { scope: "/" });
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
  flash("Este dispositivo ya recibirá tus alertas push.");
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

async function loadNotifications() {
  const data = await json("/api/account/notifications");
  const preferences = data.preferences || {};
  setChecked("notice-channel", preferences.channels);
  setChecked("notice-kind", preferences.kinds);
  $("notice-email").value = data.email || "";
  $("notice-telegram").value = data.telegram || "";
  renderTelegramStatus(Boolean(data.telegram_connected), data.telegram || "");
  $("min-discount-self").value = preferences.min_discount_self ?? 0;
  $("min-discount-stores").value = preferences.min_discount_other_stores ?? 0;
  $("email-min-real-discount").value = preferences.email_min_real_discount ?? 0;
  renderEmailCategories(data.notification_categories, preferences.email_categories);
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

$("store-preference-filter").addEventListener("input", (event) => renderStorePreferences(event.target.value));

$("store-preference-list").addEventListener("change", (event) => {
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

$("store-preference-list").addEventListener("click", (event) => {
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

$("store-preferences-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await json("/api/account/store-preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        favorites: storePreferenceData.favorites || [],
        excluded: storePreferenceData.excluded || [],
      }),
    });
    storePreferenceData = data;
    renderStorePreferences($("store-preference-filter").value);
    flash("Tus tiendas preferidas y excluidas quedaron guardadas.");
  } catch (error) {
    flash(error.message, false);
  }
});

$("password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const newPassword = $("new-password").value;
  if (newPassword !== $("new-password2").value) {
    flash("Las claves nuevas no coinciden.", false);
    return;
  }
  try {
    await json("/api/account/password", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: $("current-password").value, new_password: newPassword }),
    });
    $("password-form").reset();
    flash("Tu clave quedó actualizada.");
  } catch (error) {
    flash(error.message, false);
  }
});

$("notification-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await json("/api/account/notifications", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        telegram: $("notice-telegram").value.trim(),
        preferences: {
          channels: checked("notice-channel"),
          kinds: checked("notice-kind"),
          min_discount_self: $("min-discount-self").value,
          min_discount_other_stores: $("min-discount-stores").value,
          email_categories: checked("email-category"),
          email_min_real_discount: $("email-min-real-discount").value,
        },
      }),
    });
    renderTelegramStatus(Boolean(data.telegram_connected), data.telegram || "");
    flash("Tus preferencias de notificación quedaron guardadas.");
  } catch (error) {
    flash(error.message, false);
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
    flash(`Se abrió ${data.bot_username}. Presiona Iniciar y vuelve aquí para verificar.`);
  } catch (error) {
    if (telegramWindow) telegramWindow.close();
    flash(error.message, false);
  }
});

$("push-toggle").addEventListener("click", () => {
  togglePush().catch((error) => flash(error.message, false));
});

$("telegram-verify").addEventListener("click", async () => {
  try {
    const data = await json("/api/account/telegram/verify", { method: "POST" });
    $("notice-telegram").value = data.telegram || $("notice-telegram").value;
    renderTelegramStatus(true, data.telegram || "");
    flash("Telegram quedó conectado. Ya puedes recibir alertas en ese chat.");
  } catch (error) {
    renderTelegramStatus(false, $("notice-telegram").value.trim());
    flash(error.message, false);
  }
});

$("email-categories").addEventListener("change", refreshEmailCategorySummary);

$("email-categories-all").addEventListener("click", () => {
  document.querySelectorAll('input[name="email-category"]').forEach((item) => { item.checked = true; });
  refreshEmailCategorySummary();
});

$("email-categories-none").addEventListener("click", () => {
  document.querySelectorAll('input[name="email-category"]').forEach((item) => { item.checked = false; });
  refreshEmailCategorySummary();
});

$("watches").addEventListener("click", async (event) => {
  const button = event.target.closest(".remove");
  if (!button) return;
  try {
    await json(`/api/watches/${button.dataset.id}`, { method: "DELETE" });
    await load();
  } catch (error) {
    flash(error.message, false);
  }
});

async function ready() {
  const user = await ensureUser();
  $("guest-box").hidden = Boolean(user);
  $("watch-panel").hidden = !user;
  $("watch-list").hidden = !user;
  $("notification-panel").hidden = !user;
  $("store-preferences-panel").hidden = !user;
  $("password-panel").hidden = !user;
  if (!user) {
    render([]);
    return;
  }
  await Promise.all([load(), loadNotifications(), loadStorePreferences(), loadPushState()]);
}

ready().catch((error) => flash(error.message, false));

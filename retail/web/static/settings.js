// $, money y attr vienen de prices.js

const CATALOG_DISPLAY_LIMIT = 100;
const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
let catalogProducts = [];
const removedCatalogIndexes = new Set();

function fmt(value) {
  const number = Number(value);
  return Number.isFinite(number) ? integerFormat.format(number) : "0";
}

async function saving(form, action) {
  const button = form.querySelector('button[type="submit"]');
  if (button?.disabled) return;
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
  $("flash").hidden = false;
  $("flash").className = ok ? "summary" : "err";
  $("flash").textContent = text;
}

function checkedValues(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((item) => item.value);
}

function setChecks(name, values) {
  document.querySelectorAll(`input[name="${name}"]`).forEach((item) => {
    item.checked = values.includes(item.value);
  });
}

function fillRules(rules) {
  setChecks("rule", rules.enabled || []);
  $("price_drop_percent").value = rules.price_drop_percent ?? 10;
  $("price_drop_amount").value = rules.price_drop_amount ?? 20000;
  $("cross_store_gap_percent").value = rules.cross_store_gap_percent ?? 8;
  $("below_median_percent").value = rules.below_median_percent ?? 12;
  $("ignore_fake_discounts").checked = rules.ignore_fake_discounts !== false;
  $("min_price").value = rules.min_price ?? 0;
  $("max_price").value = rules.max_price ?? "";
}

function fillChannels(rules, channels) {
  setChecks("channel", rules.channels || []);
  $("telegram_bot_token").value = channels.telegram_bot_token || "";
  $("telegram_chat_id").value = channels.telegram_chat_id || "";
  $("smtp_host").value = channels.smtp_host || "";
  $("smtp_port").value = channels.smtp_port || 587;
  $("smtp_user").value = channels.smtp_user || "";
  $("smtp_password").value = channels.smtp_password || "";
  $("smtp_from").value = channels.smtp_from || "";
  $("alert_email_to").value = channels.alert_email_to || "";
}

function fillSchedule(schedule) {
  $("cron_enabled").checked = Boolean(schedule.enabled);
  $("cron_hour").value = schedule.hour ?? 8;
  $("cron_minute").value = schedule.minute ?? 0;
  $("cron_source").value = schedule.source || "both";
  $("cron_pause").value = schedule.pause ?? 3;
  const line = schedule.line || "";
  if (schedule.backend === "host") {
    $("cron-line").textContent = schedule.enabled
      ? `Horario ${line}. Los valores se guardan en MongoDB; en BMAX el cron del host se instala con prod-menu opción 8 o en cada deploy.`
      : `Corrida diaria desactivada. ${line}`;
    return;
  }
  $("cron-line").textContent = schedule.installed
    ? `Cron instalado: ${line}`
    : `Línea prevista: ${line}`;
}

function escapeAttr(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;");
}

function catalogRow(item, index = null) {
  const source = Number.isInteger(index) ? ` data-catalog-index="${index}"` : "";
  return `
    <tr${source}>
      <td><input type="checkbox" class="cat-enabled" ${item.enabled !== false ? "checked" : ""}></td>
      <td><input class="cat-id" value="${escapeAttr(item.id)}"></td>
      <td><input class="cat-query" value="${escapeAttr(item.query)}"></td>
      <td><input class="cat-category" value="${escapeAttr(item.category)}"></td>
      <td><input class="cat-brand" value="${escapeAttr(item.brand)}"></td>
      <td><button type="button" class="secondary remove-row">Quitar</button></td>
    </tr>`;
}

function renderCatalogProducts() {
  const visible = catalogProducts.slice(0, CATALOG_DISPLAY_LIMIT);
  $("catalog-body").innerHTML = visible.map((item, index) => catalogRow(item, index)).join("");
  const total = catalogProducts.length;
  const shown = Math.min(total, CATALOG_DISPLAY_LIMIT);
  $("catalog-limit-note").textContent = total > CATALOG_DISPLAY_LIMIT
    ? `Mostrando los primeros ${shown} de ${fmt(total)} productos. Los demás se conservan al guardar.`
    : `Mostrando ${shown} productos.`;
}

function catalogGroups(stores) {
  const groups = [];
  const byId = new Map();
  for (const store of stores) {
    const id = store.group || "otros";
    if (!byId.has(id)) {
      const group = {
        id,
        title: store.group_title || "Otros",
        order: Number(store.group_order ?? 99),
        stores: [],
      };
      byId.set(id, group);
      groups.push(group);
    }
    byId.get(id).stores.push(store);
  }
  groups.sort((left, right) => left.order - right.order || left.title.localeCompare(right.title, "es"));
  return groups;
}

function catalogStoreChecks(group) {
  return [...document.querySelectorAll("#catalog-stores input[name=cat-store]")].filter(
    (item) => !group || item.dataset.group === group
  );
}

function syncCatalogGroupAll() {
  const select = $("catalog-store-group");
  const toggle = $("catalog-store-group-all");
  if (!select || !toggle) return;
  const group = select.value;
  const boxes = catalogStoreChecks(group);
  const on = boxes.filter((item) => item.checked).length;
  toggle.checked = boxes.length > 0 && on === boxes.length;
  toggle.indeterminate = on > 0 && on < boxes.length;
  const title = group
    ? select.selectedOptions[0]?.textContent || "esta categoría"
    : "todas las categorías";
  const text = $("catalog-store-all-text");
  if (text) text.textContent = `Marcar ${title}`;
}

function applyCatalogGroupFilter() {
  const group = $("catalog-store-group")?.value || "";
  document.querySelectorAll("#catalog-stores [data-store-group]").forEach((section) => {
    section.hidden = Boolean(group) && section.dataset.storeGroup !== group;
  });
  syncCatalogGroupAll();
}

function fillCatalog(catalog, stores) {
  catalogProducts = (catalog.products || []).map((item) => ({ ...item }));
  removedCatalogIndexes.clear();
  const selected = new Set(catalog.default_stores || []);
  const groups = catalogGroups(stores);
  const select = $("catalog-store-group");
  if (select) {
    const current = select.value;
    select.innerHTML = `<option value="">Todas</option>${groups
      .map((group) => `<option value="${escapeAttr(group.id)}">${escapeAttr(group.title)}</option>`)
      .join("")}`;
    if ([...select.options].some((option) => option.value === current)) select.value = current;
  }
  $("catalog-stores").innerHTML = groups
    .map(
      (group) => `
      <section class="store-section" data-store-group="${escapeAttr(group.id)}">
        <h3>${escapeAttr(group.title)}</h3>
        <div class="store-grid">
          ${group.stores
            .map(
              (store) => `
          <label>
            <input type="checkbox" name="cat-store" value="${escapeAttr(store.id)}" data-group="${escapeAttr(group.id)}" ${selected.has(store.id) ? "checked" : ""}>
            ${escapeAttr(store.title)}
          </label>`
            )
            .join("")}
        </div>
      </section>`
    )
    .join("");
  applyCatalogGroupFilter();
  renderCatalogProducts();
}

function collectCatalog() {
  const products = catalogProducts.map((item) => ({ ...item }));
  const added = [];
  [...$("catalog-body").querySelectorAll("tr")].forEach((row) => {
    const item = {
      enabled: row.querySelector(".cat-enabled").checked,
      id: row.querySelector(".cat-id").value.trim(),
      query: row.querySelector(".cat-query").value.trim(),
      category: row.querySelector(".cat-category").value.trim(),
      brand: row.querySelector(".cat-brand").value.trim() || null,
    };
    const index = Number(row.dataset.catalogIndex);
    if (row.dataset.catalogIndex != null && Number.isInteger(index)) products[index] = item;
    else added.push(item);
  });
  return {
    title: "Productos más buscados en Chile",
    default_stores: [...document.querySelectorAll("input[name=cat-store]:checked")].map((item) => item.value),
    products: products.filter((_item, index) => !removedCatalogIndexes.has(index)).concat(added),
  };
}

function fillAlerts(items) {
  if (!items.length) {
    $("alerts").innerHTML = "<li>Aún no hay alertas.</li>";
    return;
  }
  $("alerts").innerHTML = items
    .map(
      (item) => `
      <li>
        <strong>${item.query || item.catalog_id}</strong> · ${item.store ? storeLogo(item.display_store || item.store, item.store_title || item.store) : ""} · $${item.price || 0}<br>
        <small>${item.message || item.rule}</small>
      </li>`
    )
    .join("");
}

async function refresh() {
  const [settings, stores, alerts, status] = await Promise.all([
    json("/api/settings"),
    json("/api/stores"),
    json("/api/alerts"),
    json("/api/batch/status"),
  ]);
  fillRules(settings.rules);
  fillChannels(settings.rules, settings.channels);
  fillSchedule(settings.schedule);
  fillCatalog(settings.catalog, stores);
  fillAlerts(alerts);
  renderBatch(status);
}

function renderBatch(status) {
  if (status.running) {
    $("batch-status").textContent = "Batch en curso…";
    return;
  }
  if (status.error) {
    $("batch-status").textContent = `Error: ${status.error}`;
    return;
  }
  const last = status.last;
  if (!last) {
    $("batch-status").textContent = "Sin corridas en esta sesión.";
    return;
  }
  $("batch-status").textContent = `${last.items} productos · ${last.alert_count || 0} alertas`;
}

async function saveRules() {
  return json("/api/settings/rules", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enabled: checkedValues("rule"),
      channels: checkedValues("channel"),
      price_drop_percent: $("price_drop_percent").value,
      price_drop_amount: $("price_drop_amount").value,
      cross_store_gap_percent: $("cross_store_gap_percent").value,
      below_median_percent: $("below_median_percent").value,
      ignore_fake_discounts: $("ignore_fake_discounts").checked,
      min_price: $("min_price").value,
      max_price: $("max_price").value || null,
    }),
  });
}

$("rules-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const saved = await saving(event.currentTarget, saveRules);
    fillRules(saved);
    flash("Reglas guardadas.");
  } catch (error) {
    flash(error.message, false);
  }
});

$("channels-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const saved = await saving(event.currentTarget, async () => {
      const rules = await saveRules();
      const channels = await json("/api/settings/channels", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          telegram_bot_token: $("telegram_bot_token").value,
          telegram_chat_id: $("telegram_chat_id").value,
          smtp_host: $("smtp_host").value,
          smtp_port: $("smtp_port").value,
          smtp_user: $("smtp_user").value,
          smtp_password: $("smtp_password").value,
          smtp_from: $("smtp_from").value,
          alert_email_to: $("alert_email_to").value,
        }),
      });
      return { rules, channels };
    });
    fillChannels(saved.rules, saved.channels);
    flash("Canales guardados.");
  } catch (error) {
    flash(error.message, false);
  }
});

$("schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
  const schedule = await saving(event.currentTarget, () => json("/api/settings/schedule", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enabled: $("cron_enabled").checked,
      hour: $("cron_hour").value,
      minute: $("cron_minute").value,
      source: $("cron_source").value,
      pause: $("cron_pause").value,
    }),
  }));
  fillSchedule(schedule);
  if (schedule.cron_error) {
    flash(`Horario guardado, pero el cron no se instaló: ${schedule.cron_error}`, false);
  } else if (schedule.hint) {
    flash(`Valores guardados en la base de datos. ${schedule.hint}`);
  } else {
    flash(schedule.enabled ? "Cron instalado." : "Cron desactivado.");
  }
  } catch (error) {
    flash(error.message, false);
  }
});

$("save-catalog").addEventListener("click", async () => {
  try {
  const saved = await json("/api/settings/catalog", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectCatalog()),
  });
  catalogProducts = (saved.products || []).map((item) => ({ ...item }));
  removedCatalogIndexes.clear();
  renderCatalogProducts();
  flash("Catálogo.");
  } catch (error) {
    flash(error.message, false);
  }
});

$("add-product").addEventListener("click", () => {
  $("catalog-body").insertAdjacentHTML("afterbegin", catalogRow({ enabled: true, id: "", query: "", category: "otros", brand: "" }));
});

$("catalog-body").addEventListener("click", (event) => {
  if (event.target.classList.contains("remove-row")) {
    const row = event.target.closest("tr");
    if (row.dataset.catalogIndex != null) removedCatalogIndexes.add(Number(row.dataset.catalogIndex));
    row.remove();
  }
});

async function runBatch(dryRun) {
  const status = await json("/api/batch/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dry_run: dryRun, limit: dryRun ? null : 2 }),
  });
  flash(status.message);
  pollBatch();
}

function pollBatch() {
  json("/api/batch/status").then((status) => {
    renderBatch(status);
    if (status.running) setTimeout(pollBatch, 2000);
    else json("/api/alerts").then(fillAlerts);
  });
}

$("catalog-store-group")?.addEventListener("change", applyCatalogGroupFilter);
$("catalog-store-group-all")?.addEventListener("change", (event) => {
  const group = $("catalog-store-group")?.value || "";
  catalogStoreChecks(group).forEach((item) => {
    item.checked = event.target.checked;
  });
  syncCatalogGroupAll();
});
$("catalog-stores")?.addEventListener("change", (event) => {
  if (event.target?.name === "cat-store") syncCatalogGroupAll();
});

const TEST_EMAIL_DEFAULT = "richardgarces@gmail.com";

async function sendNoticeTest(url, button, body) {
  if (button.disabled) return;
  button.disabled = true;
  try {
    const options = { method: "POST" };
    if (body) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const payload = await json(url, options);
    flash(payload.message || "Enviado.");
  } catch (error) {
    flash(error.message, false);
  } finally {
    button.disabled = false;
  }
}

$("test-telegram")?.addEventListener("click", () => {
  sendNoticeTest("/api/admin/test-telegram", $("test-telegram"));
});
$("test-email")?.addEventListener("click", () => {
  const typed = ($("test_email_to")?.value || "").trim();
  sendNoticeTest("/api/admin/test-email", $("test-email"), { to: typed || TEST_EMAIL_DEFAULT });
});

$("run-dry").addEventListener("click", () => runBatch(true).catch((error) => flash(error.message, false)));
$("run-batch").addEventListener("click", () => runBatch(false).catch((error) => flash(error.message, false)));

refresh().catch((error) => flash(error.message, false));

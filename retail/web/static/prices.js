/* Desglose de precios tal como lo publica la tienda: normal, internet y con tarjeta.
   Se carga antes que el script de cada página. */

const $ = (id) => document.getElementById(id);

// Tiendas es una vista administrativa: se oculta antes de resolver la sesión
// para que no aparezca brevemente en cuentas normales o visitantes.
document.querySelectorAll('nav a[href="/tiendas"]').forEach((el) => { el.hidden = true; });

const money = (value) =>
  value == null ? "s/precio" : new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 }).format(value);

const attr = (value) =>
  String(value ?? "").replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

/** Texto legible de disponibilidad aunque la tienda entregue un objeto anidado. */
function availabilityLabel(value, stock = null) {
  const quantity = stockQuantity(stock);
  const fallback = quantity == null ? "Sin información" : quantity > 0 ? "En stock" : "Sin stock";
  if (value == null || value === "") return fallback;
  if (typeof value === "boolean") return value ? "En stock" : "Sin stock";
  if (typeof value === "number") return value > 0 ? "En stock" : "Sin stock";
  if (typeof value === "string") {
    const text = value.trim();
    if (!text || text === "[object Object]") return fallback;
    const code = text.toLowerCase().replaceAll("_", " ").replaceAll("-", " ");
    if (["available", "in stock", "instock", "disponible"].includes(code)) return "En stock";
    if (["unavailable", "out of stock", "outofstock", "agotado", "no disponible"].includes(code)) return "Sin stock";
    return text;
  }
  if (Array.isArray(value)) {
    const labels = [...new Set(value.map((item) => availabilityLabel(item, null)).filter((item) => item !== "Sin información"))];
    return labels.join(" · ") || fallback;
  }
  if (typeof value === "object") {
    for (const key of ["message", "text", "label", "name", "description", "displayName", "statusText", "stockStatus", "status", "type", "availability", "value"]) {
      if (value[key] == null || value[key] === value) continue;
      const label = availabilityLabel(value[key], null);
      if (label !== "Sin información") return label;
    }
    for (const key of ["available", "isAvailable", "inStock", "isInStock"]) {
      if (typeof value[key] === "boolean") return value[key] ? "En stock" : "Sin stock";
    }
    const nestedQuantity = stockQuantity(value);
    if (nestedQuantity != null) return nestedQuantity > 0 ? "En stock" : "Sin stock";
  }
  return fallback;
}

function stockQuantity(value) {
  if (value == null || value === "" || typeof value === "boolean") return null;
  if (typeof value === "object") {
    for (const key of ["quantity", "availableQuantity", "stock", "count", "value"]) {
      if (value[key] != null && value[key] !== value) {
        const quantity = stockQuantity(value[key]);
        if (quantity != null) return quantity;
      }
    }
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

// La tarjeta que exige cada cadena para el precio más bajo.
const CARD_LABELS = {
  falabella: "CMR",
  sodimac: "CMR",
  tottus: "CMR",
  paris: "Cencosud",
  easy: "Cencosud",
  ripley: "Ripley",
  lider: "Líder",
  preunic: "Mi Preunic",
};

const cardLabel = (store) => CARD_LABELS[store] || "de la tienda";

/** Misma regla que sane_discount en el backend: vale el porcentaje de la tienda
 *  salvo que esté fuera de rango o muy lejos de la resta. Hace falta acá porque
 *  /api/catalog lee documentos de Mongo guardados antes del arreglo. */
function discountOf(row) {
  if (row.precio_normal) return 0;
  const before = row.price_normal ?? row.price_internet;
  const computed = before && row.price && before > row.price
    ? Math.round(((before - row.price) / before) * 100)
    : 0;
  const declared = Math.abs(Math.round(row.discount_percent || 0));
  if (!declared || declared >= 100) return computed;
  if (computed && Math.abs(declared - computed) > 20) return computed;
  return declared;
}

/** Color del badge −N%: >40 rojo, >30–40 naranja, ≤30 amarillo. */
function discountTone(pct) {
  const n = Math.abs(Math.round(Number(pct) || 0));
  if (n > 40) return "discount-high";
  if (n > 30) return "discount-mid";
  return "discount-low";
}

/** Markup del badge −N%. Vacío si precio_normal / fake_discount o % bajo el umbral. */
function discountBadge(rowOrPct, min = 5) {
  let pct;
  if (rowOrPct != null && typeof rowOrPct === "object") {
    if (rowOrPct.precio_normal || rowOrPct.fake_discount || (rowOrPct.price_stats || {}).fake_discount) {
      return "";
    }
    pct = discountOf(rowOrPct);
  } else {
    pct = Math.abs(Math.round(Number(rowOrPct) || 0));
  }
  if (pct < min) return "";
  return `<span class="badge off ${discountTone(pct)}">−${pct}%</span>`;
}

/** Precio pagable sin la tarjeta de la tienda: sirve para comparar parejo. */
function openPrice(row) {
  return row.price_internet ?? row.price_normal ?? row.price ?? null;
}

/** Si el precio mostrado solo se consigue con la tarjeta de la cadena. */
function needsCard(row) {
  const open = row.price_internet ?? row.price_normal;
  return Boolean(row.price_cmr && row.price === row.price_cmr && open && open > row.price_cmr);
}

/** Qué es el precio principal: "con tarjeta CMR", "precio internet" o "precio normal". */
function priceTag(row) {
  if (row.precio_normal) return "";
  if (needsCard(row)) return `con tarjeta ${cardLabel(row.store)}`;
  if (row.price_internet && row.price === row.price_internet && row.price_normal && row.price_normal > row.price) {
    return "precio internet";
  }
  return "";
}

/**
 * Escalera de precios de la tienda. Se omite cada peldaño que repite al anterior
 * para no mostrar tres veces la misma cifra.
 */
function priceLadder(row) {
  const lines = [];
  const tag = priceTag(row);
  if (tag) lines.push(`<span class="tier">${tag}</span>`);
  if (needsCard(row) && row.price_internet && row.price_internet !== row.price) {
    lines.push(`<span>Internet ${money(row.price_internet)}</span>`);
  }
  if (!row.precio_normal && row.price_normal && row.price_normal > (row.price ?? 0)) {
    lines.push(`<span>Normal <span class="strike">${money(row.price_normal)}</span></span>`);
  }
  return lines.length ? `<div class="ladder">${lines.join(" · ")}</div>` : "";
}

const STORE_LOGOS = {
  falabella: "falabella.png",
  sodimac: "sodimac.png",
  tottus: "tottus.png",
  paris: "paris.svg",
  easy: "easy.svg",
  construplaza: "construplaza.svg",
  prat: "prat.svg",
  weitzler: "weitzler.svg",
  audiomusica: "audiomusica.svg",
  casaroyal: "casaroyal.svg",
  promusic: "promusic.svg",
  dbs: "dbs.svg",
  sallybeauty: "sallybeauty.svg",
  bodyshop: "bodyshop.svg",
  preunic: "preunic.svg",
  ripley: "ripley.svg",
  lider: "lider.svg",
  unimarc: "unimarc.svg",
  alvi: "alvi.svg",
  cugat: "cugat.svg",
  pcfactory: "pcfactory.png",
  ikea: "ikea.svg",
  mercadolibre: "mercadolibre.svg",
  drsimi: "drsimi.webp",
  doite: "doite.png",
  antartica: "antartica.png",
  intime: "intime.png",
  sparta: "sparta.png",
  nike: "nike.png",
  weplay: "weplay.png",
  rosen: "rosen.jpg",
  amphora: "amphora.jpg",
  fashionspark: "fashionspark.png",
  lippi: "lippi.png",
  colloky: "colloky.png",
  tiendaflores: "tiendaflores.png",
  cannon: "cannon.png",
  ahumada: "ahumada.svg",
  cruzverde: "cruzverde.png",
  eliteperfumes: "eliteperfumes.svg",
  loccitane: "loccitane.svg",
  lush: "lush.svg",
  pichara: "pichara.svg",
  silkperfumes: "silkperfumes.svg",
  azaleia: "azaleia.svg",
  cardinale: "cardinale.svg",
  converse: "converse.svg",
  crocs: "crocs.svg",
  hushpuppies: "hushpuppies.svg",
  vans: "vans.svg",
  allnutrition: "allnutrition.svg",
  andesgear: "andesgear.svg",
  asics: "asics.svg",
  bikehouse: "bikehouse.svg",
  hakahonu: "hakahonu.svg",
  head: "head.svg",
  mammut: "mammut.svg",
  merrell: "merrell.svg",
  newbalance: "newbalance.svg",
  nutrapharm: "nutrapharm.svg",
  oxford: "oxford.svg",
  patagonia: "patagonia.svg",
  puma: "puma.svg",
  reebok: "reebok.svg",
  salomon: "salomon.svg",
  sportika: "sportika.svg",
  supletech: "supletech.svg",
  thenorthface: "thenorthface.svg",
  underarmour: "underarmour.svg",
  dellanatura: "dellanatura.svg",
  atika: "atika.svg",
  budnik: "budnik.svg",
  mk: "mk.svg",
  stretto: "stretto.svg",
  adagio: "adagio.svg",
  cafehaiti: "cafehaiti.svg",
  lavinoteca: "lavinoteca.svg",
  marleycoffee: "marleycoffee.svg",
  mundovino: "mundovino.svg",
  wineclub: "wineclub.svg",
  varsovienne: "varsovienne.svg",
  byp: "byp.svg",
  flex: "flex.svg",
  interdesign: "interdesign.svg",
  kitchencenter: "kitchencenter.svg",
  mashini: "mashini.svg",
  medular: "medular.svg",
  oster: "oster.svg",
  simplepuro: "simplepuro.svg",
  thomas: "thomas.svg",
  tramontina: "tramontina.svg",
  bebesit: "bebesit.svg",
  ficcus: "ficcus.svg",
  limonada: "limonada.svg",
  opaline: "opaline.svg",
  artenostro: "artenostro.svg",
  contrapunto: "contrapunto.svg",
  ferialibro: "ferialibro.svg",
  torre: "torre.svg",
  bananarepublic: "bananarepublic.svg",
  calvinklein: "calvinklein.svg",
  dockers: "dockers.svg",
  ellus: "ellus.svg",
  kipling: "kipling.svg",
  levis: "levis.svg",
  lounge: "lounge.svg",
  trial: "trial.svg",
  econopticas: "econopticas.svg",
  gmo: "gmo.svg",
  opv: "opv.svg",
  schilling: "schilling.svg",
  mosso: "mosso.svg",
  swarovski: "swarovski.svg",
  belkin: "belkin.svg",
  centrale: "centrale.svg",
  migo: "migo.svg",
  motorola: "motorola.svg",
  movistar: "movistar.svg",
  entel: "entel.svg",
  dcshoes: "dcshoes.svg",
  totaltools: "totaltools.svg",
  descorcha: "descorcha.svg",
  piwen: "piwen.svg",
  tika: "tika.svg",
  betterlife: "betterlife.svg",
  janome: "janome.svg",
  mundotransfer: "mundotransfer.svg",
  maui: "maui.svg",
  ripcurl: "ripcurl.svg",
  volcom: "volcom.svg",
  speedo: "speedo.svg",
  liquimoly: "liquimoly.svg",
  needle: "needle.svg",
  ansaldo: "ansaldo.svg",
  toyng: "toyng.svg",
  piedrabruja: "piedrabruja.svg",
  catalonia: "catalonia.svg",
  nacional: "nacional.svg",
  etienne: "etienne.svg",
  petrizzio: "petrizzio.svg",
  gap: "gap.svg",
  ferouch: "ferouch.svg",
  perryellis: "perryellis.svg",
  tommy: "tommy.svg",
  hugoboss: "hugoboss.svg",
  guess: "guess.svg",
  fdv: "fdv.svg",
  amesti: "amesti.svg",
  dartel: "dartel.svg",
  salcobrand: "salcobrand.svg",
};

function storeLogoSrc(store) {
  const id = String(store || "").toLowerCase();
  return `/static/logos/${STORE_LOGOS[id] || "_store.svg"}`;
}

/** Nombre de la tienda con su marca a la izquierda. */
function storeLogo(store, title) {
  const label = title || store || "";
  if (!store && !title) return "";
  return `<span class="store"><img class="store-logo" src="${storeLogoSrc(store)}" alt="" width="22" height="22">${attr(label)}</span>`;
}

/** Actualiza la insignia de un panel plegable sin conocer la API de cada página. */
function updateFilterBadge(panelId, badgeId, extraActive = 0) {
  const panel = document.getElementById(panelId);
  const badge = document.getElementById(badgeId);
  if (!panel || !badge) return;
  let active = Number(extraActive) || 0;
  panel.querySelectorAll("[data-filter-control]").forEach((control) => {
    if (control.type === "checkbox" || control.type === "radio") {
      if (control.checked) active += 1;
      return;
    }
    const value = String(control.value || "").trim();
    const defaultValue = String(control.dataset.filterDefault || "").trim();
    if (value && value !== "0" && value !== defaultValue) active += 1;
  });
  badge.textContent = active
    ? `${active} ${active === 1 ? "filtro activo" : "filtros activos"}`
    : "Sin filtros";
}

function thumbDataAttrs(meta) {
  if (!meta || !meta.store || !meta.id) return "";
  return ` data-thumb-store="${attr(meta.store)}" data-thumb-id="${attr(meta.id)}"`;
}

/** Si /api/thumb falla, el <img> roto se cambia por el placeholder (un img no puede mostrar ::after). */
function emptyThumb(img) {
  if (!img || !img.replaceWith) return;
  const placeholder = document.createElement("span");
  placeholder.className = `${img.className} thumb-empty`.replace(/\s+/g, " ").trim();
  placeholder.setAttribute("role", "img");
  placeholder.setAttribute("aria-label", "Imagen no disponible");
  if (img.dataset.thumbStore) placeholder.dataset.thumbStore = img.dataset.thumbStore;
  if (img.dataset.thumbId) placeholder.dataset.thumbId = img.dataset.thumbId;
  img.replaceWith(placeholder);
}

function thumbMarkup(className, url, meta) {
  const extra = thumbDataAttrs(meta);
  if (!url) {
    return `<span class="${className} thumb-empty" role="img" aria-label="Imagen no disponible"${extra}></span>`;
  }
  return `<img class="${className}" src="${attr(url)}" alt="" loading="lazy"${extra} onerror="emptyThumb(this)">`;
}

function patchThumb(store, id) {
  if (!store || !id) return;
  const url = `/api/thumb?store=${encodeURIComponent(store)}&id=${encodeURIComponent(id)}&t=${Date.now()}`;
  const esc = (value) => (window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/"/g, '\\"'));
  document.querySelectorAll(`[data-thumb-store="${esc(store)}"][data-thumb-id="${esc(id)}"]`).forEach((el) => {
    if (el.tagName === "IMG") {
      el.src = url;
      return;
    }
    const img = document.createElement("img");
    img.className = el.className.replace(/\bthumb-empty\b/g, "").trim();
    img.alt = "";
    img.loading = "lazy";
    img.src = url;
    img.dataset.thumbStore = store;
    img.dataset.thumbId = id;
    img.onerror = () => emptyThumb(img);
    el.replaceWith(img);
  });
}

/** Quién publica el aviso: seller del marketplace o la tienda misma. */
function soldBy(item) {
  const who = (item.seller || item.store_title || item.store || "").trim();
  if (!who) return "";
  return `<p class="sold-by">Vendido por: ${attr(who)}</p>`;
}

/** La fila principal más las cadenas hermanas que publican el mismo aviso. */
function storeCell(row) {
  const main = storeLogo(row.display_store || row.store, row.store_title || row.store);
  const extras = ((row.mirrors && row.mirrors.stores) || [])
    .map((id, index) => storeLogo(id, (row.mirrors.store_titles || [])[index] || id))
    .join("");
  return extras ? `<div class="store-stack">${main}${extras}</div>` : main;
}

const THEME_KEY = "retail-theme";
const THEME_COORDS_KEY = "retail-theme-coords";
const THEME_AUTO_MIGRATION = "retail-theme-auto";
if (!localStorage.getItem(THEME_AUTO_MIGRATION)) {
  localStorage.setItem(THEME_AUTO_MIGRATION, "1");
  localStorage.setItem(THEME_KEY, "auto");
}
/** WGS84 east-positive. Used when TZ is Chile and GPS is unavailable. */
const SANTIAGO = { lat: -33.45, lon: -70.67 };
const NIGHT_HOUR_START = 19;
const NIGHT_HOUR_END = 7;
let themeTimer = 0;

function themeMode() {
  const saved = localStorage.getItem(THEME_KEY);
  return saved === "day" || saved === "night" ? saved : "auto";
}

function visitorTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch (error) {
    return "";
  }
}

function coordsFromTimezone() {
  const tz = visitorTimeZone();
  if (tz === "America/Santiago" || tz === "America/Punta_Arenas") return SANTIAGO;
  if (tz === "Pacific/Easter") return { lat: -27.15, lon: -109.43 };
  return null;
}

/** Cached GPS first, then Chile TZ approx. Null → local hour bands. */
function themeCoords() {
  try {
    const saved = JSON.parse(localStorage.getItem(THEME_COORDS_KEY) || "null");
    if (saved && Number.isFinite(saved.lat) && Number.isFinite(saved.lon)) {
      return { lat: saved.lat, lon: saved.lon, source: "gps" };
    }
  } catch (error) {
    /* coords inválidas */
  }
  const fromTz = coordsFromTimezone();
  return fromTz ? { ...fromTz, source: "tz" } : null;
}

function themeFromHours(now = new Date()) {
  const hour = now.getHours();
  return hour >= NIGHT_HOUR_END && hour < NIGHT_HOUR_START ? "day" : "night";
}

function julianDay(date) {
  return date.getTime() / 86400000 + 2440587.5;
}

/**
 * NOAA-style sunrise/sunset. `lonEast` is WGS84 (east positive);
 * the algorithm needs west-positive longitude.
 */
function sunriseSunset(date, lat, lonEast) {
  const rad = Math.PI / 180;
  const lonWest = -lonEast;
  const n = Math.round(julianDay(date) - 2451545 - 0.0009 - lonWest / 360);
  const jstar = n + 0.0009 + lonWest / 360;
  const mean = (357.5291 + 0.98560028 * jstar) % 360;
  const center = 1.9148 * Math.sin(mean * rad) + 0.02 * Math.sin(2 * mean * rad);
  const lambda = (mean + center + 180 + 102.9372) % 360;
  const transit = 2451545 + jstar + 0.0053 * Math.sin(mean * rad) - 0.0069 * Math.sin(2 * lambda * rad);
  const sinDec = Math.sin(lambda * rad) * Math.sin(23.4397 * rad);
  const dec = Math.asin(sinDec);
  const cosOmega =
    (Math.sin(-0.83 * rad) - Math.sin(lat * rad) * sinDec) / (Math.cos(lat * rad) * Math.cos(dec));
  const toDate = (julian) => new Date((julian - 2440587.5) * 86400000);
  if (cosOmega <= -1) {
    const start = new Date(date);
    start.setHours(0, 0, 0, 0);
    return { rise: start, set: new Date(start.getTime() + 86400000 - 1) };
  }
  if (cosOmega >= 1) {
    const start = new Date(date);
    start.setHours(0, 0, 0, 0);
    return { rise: start, set: start };
  }
  const omega = Math.acos(Math.min(1, Math.max(-1, cosOmega)));
  return { rise: toDate(transit - omega / (2 * Math.PI)), set: toDate(transit + omega / (2 * Math.PI)) };
}

function themeFromSun(now = new Date()) {
  const coords = themeCoords();
  if (!coords) return themeFromHours(now);
  const { rise, set } = sunriseSunset(now, coords.lat, coords.lon);
  return now >= rise && now < set ? "day" : "night";
}

function resolvedTheme(mode = themeMode()) {
  return mode === "auto" ? themeFromSun() : mode;
}

function nextHourBoundary(now = new Date()) {
  const next = new Date(now);
  next.setMinutes(0, 0, 0);
  next.setHours(next.getHours() + 1);
  return next.getTime();
}

function nextSunChange(now = new Date()) {
  const coords = themeCoords();
  if (!coords) return nextHourBoundary(now);
  const today = sunriseSunset(now, coords.lat, coords.lon);
  if (now < today.rise) return today.rise.getTime();
  if (now < today.set) return today.set.getTime();
  const tomorrow = sunriseSunset(new Date(now.getTime() + 86400000), coords.lat, coords.lon);
  return tomorrow.rise.getTime();
}

function scheduleThemeTick() {
  window.clearTimeout(themeTimer);
  if (themeMode() !== "auto") return;
  const wait = Math.min(Math.max(5000, nextSunChange() - Date.now() + 1000), 15 * 60 * 1000);
  themeTimer = window.setTimeout(() => {
    applyTheme("auto", false);
    scheduleThemeTick();
  }, wait);
}

function rememberCoords(lat, lon) {
  localStorage.setItem(THEME_COORDS_KEY, JSON.stringify({ lat, lon }));
}

function locateForTheme() {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      rememberCoords(pos.coords.latitude, pos.coords.longitude);
      if (themeMode() === "auto") {
        applyTheme("auto", false);
        scheduleThemeTick();
      }
    },
    () => {
      if (themeMode() === "auto") {
        applyTheme("auto", false);
        scheduleThemeTick();
      }
    },
    { maximumAge: 86400000, timeout: 4000 }
  );
}

function applyTheme(mode, persist = true) {
  if (persist) localStorage.setItem(THEME_KEY, mode);
  document.documentElement.dataset.theme = resolvedTheme(mode);
  document.querySelectorAll("[data-theme-set]").forEach((button) => {
    button.classList.toggle("current", button.dataset.themeSet === mode);
  });
  if (mode === "auto") scheduleThemeTick();
  else window.clearTimeout(themeTimer);
}

applyTheme(themeMode(), false);
locateForTheme();
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible" || themeMode() !== "auto") return;
  applyTheme("auto", false);
  scheduleThemeTick();
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-theme-set]");
  if (!button) return;
  applyTheme(button.dataset.themeSet);
});

window.retailUser = undefined;
let sessionPromise;

function applySession(user) {
  window.retailUser = user || null;
  const loggedIn = Boolean(user);
  const admin = Boolean(user && user.role === "admin");
  document.documentElement.classList.toggle("is-authed", loggedIn);
  document.documentElement.classList.toggle("is-admin", admin);
  document.querySelectorAll("[data-admin]").forEach((el) => {
    el.hidden = !admin;
  });
  document.querySelectorAll('nav a[href="/tiendas"]').forEach((el) => {
    el.hidden = !admin;
  });
  document.querySelectorAll("[data-login]").forEach((el) => {
    el.hidden = loggedIn;
  });
  document.querySelectorAll("[data-logout]").forEach((el) => {
    el.hidden = !loggedIn;
  });
  document.querySelectorAll("[data-auth]").forEach((el) => {
    el.hidden = !loggedIn;
  });
  const label = (user && (user.name || user.email || "").trim()) || "Cuenta";
  document.querySelectorAll("[data-user-label]").forEach((el) => {
    el.textContent = label.split("@")[0];
  });
  refreshLoginLinks();
}

function refreshLoginLinks() {
  document.querySelectorAll("a[data-login-mode]").forEach((el) => {
    el.setAttribute("href", loginHref(el.dataset.loginMode === "inscribir" ? "inscribir" : ""));
  });
}

function loginHref(mode) {
  const next = `${location.pathname}${location.search}`;
  const params = new URLSearchParams();
  params.set("next", next.startsWith("/") ? next : "/");
  if (mode) params.set("modo", mode);
  return `/entrar?${params.toString()}`;
}

function loadSession() {
  if (!sessionPromise) {
    sessionPromise = fetch("/api/auth/me")
      .then((response) => (response.ok ? response.json() : { user: null }))
      .then((data) => {
        applySession(data && data.user);
        return window.retailUser;
      })
      .catch(() => {
        applySession(null);
        return window.retailUser;
      });
  }
  return sessionPromise;
}

function ensureUser() {
  return loadSession();
}

loadSession();
refreshLoginLinks();

document.addEventListener("click", (event) => {
  document.querySelectorAll(".nav-menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  document.querySelectorAll(".nav-menu[open]").forEach((menu) => menu.removeAttribute("open"));
});

document.addEventListener("click", async (event) => {
  const link = event.target.closest("[data-logout]");
  if (!link) return;
  event.preventDefault();
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } finally {
    location.href = "/";
  }
});

// Clics públicos. No corta la navegación: sendBeacon sale antes del cambio de página.
// La fecha clickeable es el selector #day (Ofertas de hoy, icono de calendario) y el
// encabezado «Fecha» de las bajas en Tiendas. Las fechas del gráfico son texto, no botones.
const CLICK_NAV = {
  "/catalogo": "catalogo",
  "/hoy": "hoy",
  "/reales": "reales",
  "/super": "reales",
  "/tiendas": "tiendas",
};
const CLICK_ADMIN_PAGES = new Set(["/cron", "/estadisticas", "/usuarios", "/ofertas"]);
let fechaClickAt = 0;

function trackClick(kind) {
  if (!kind || CLICK_ADMIN_PAGES.has(location.pathname)) return;
  if (kind === "fecha") {
    const now = Date.now();
    if (now - fechaClickAt < 700) return;
    fechaClickAt = now;
  }
  const body = new URLSearchParams({ kind });
  try {
    if (navigator.sendBeacon && navigator.sendBeacon("/api/clicks", body)) return;
  } catch (error) {
    /* el fetch de abajo cubre el fallo */
  }
  fetch("/api/clicks", { method: "POST", body, keepalive: true }).catch(() => {});
}

function clickPath(href) {
  try {
    return new URL(href, location.origin).pathname;
  } catch (error) {
    return "";
  }
}

function isExternalHref(href) {
  if (!href) return false;
  try {
    const url = new URL(href, location.origin);
    return (url.protocol === "http:" || url.protocol === "https:") && url.origin !== location.origin;
  } catch (error) {
    return false;
  }
}

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest("#day, label.filter-day, button.sort[data-sort='date']")) {
    trackClick("fecha");
    return;
  }
  const link = target.closest("a[href]");
  if (link && link.closest("nav.nav")) {
    const kind = CLICK_NAV[clickPath(link.getAttribute("href"))];
    if (kind) trackClick(kind);
    return;
  }
  if (link && isExternalHref(link.getAttribute("href"))) {
    trackClick("externo");
    return;
  }
  if (link) return;
  const row = target.closest("tr[data-url]");
  if (row && isExternalHref(row.getAttribute("data-url"))) trackClick("externo");
}, true);

document.addEventListener("change", (event) => {
  if (event.target && event.target.id === "day") trackClick("fecha");
}, true);

// En páginas secundarias el buscador suele filtrar datos guardados de esa
// pantalla. Si el usuario desmarca "Búsqueda rápida", lo llevamos al buscador
// principal para ejecutar la consulta real a tiendas y base.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches(".desktop-quick-search")) return;
  if (location.pathname === "/") return;
  const quick = form.querySelector('input[name="quick"]');
  if (!quick || quick.checked) return;
  const query = form.querySelector('input[name="q"]')?.value.trim() || "";
  if (!query) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  location.href = `/?q=${encodeURIComponent(query)}&quick=0`;
}, true);

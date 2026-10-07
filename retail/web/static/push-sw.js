self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

function notificationImage(value) {
  if (typeof value !== "string" || !value || value.length > 2000) return "";
  try {
    const url = new URL(value, self.location.origin);
    if (url.protocol !== "https:" || url.username || url.password) return "";
    const host = url.hostname.toLowerCase();
    const path = url.pathname.toLowerCase();
    if (host === "challenges.cloudflare.com" || host.endsWith(".challenges.cloudflare.com")) return "";
    if (path.includes("/cdn-cgi/challenge") || path.includes("cf-challenge")) return "";
    return url.href;
  } catch (_) {
    return "";
  }
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { body: event.data ? event.data.text() : "Nueva alerta de precio" };
  }
  const options = {
    body: data.body || "Hay una nueva alerta de precio.",
    icon: data.icon || "/static/brand/icon-192.png",
    badge: data.badge || "/static/brand/icon-192.png",
    tag: data.tag || "precio-alerta",
    renotify: false,
    data: { url: data.url || "/siguiendo" },
  };
  const image = notificationImage(data.image);
  if (image) options.image = image;
  event.waitUntil(self.registration.showNotification(data.title || "Precios", options));
});

function trustedPushTarget(value) {
  try {
    const candidate = new URL(value || "/siguiendo", self.location.origin);
    const host = candidate.hostname.toLowerCase();
    const trustedHost =
      host === "lnk.meincart.cl" ||
      host === "precios.meincart.cl" ||
      host.endsWith(".meincart.cl");
    if (candidate.origin === self.location.origin) return candidate;
    if (candidate.protocol === "https:" && trustedHost) return candidate;
  } catch (_) {}
  return new URL("/siguiendo", self.location.origin);
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = trustedPushTarget(event.notification.data?.url);
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const open = windows.find((client) => new URL(client.url).origin === self.location.origin);
    if (open) {
      return open.focus().then(() => {
        if (typeof open.navigate === "function") return open.navigate(target.href);
        return clients.openWindow(target.href);
      });
    }
    return clients.openWindow(target.href);
  }));
});

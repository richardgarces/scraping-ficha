self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { body: event.data ? event.data.text() : "Nueva alerta de precio" };
  }
  event.waitUntil(self.registration.showNotification(data.title || "Precios", {
    body: data.body || "Hay una nueva alerta de precio.",
    icon: data.icon || "/static/brand/icon-192.png",
    badge: data.badge || "/static/brand/icon-192.png",
    tag: data.tag || "precio-alerta",
    renotify: false,
    data: { url: data.url || "/siguiendo" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  let target = new URL("/siguiendo", self.location.origin);
  try {
    const candidate = new URL(event.notification.data?.url || "/siguiendo", self.location.origin);
    const trustedShortLink = candidate.protocol === "https:" && candidate.hostname === "lnk.meincart.cl";
    if (candidate.origin === self.location.origin || trustedShortLink) target = candidate;
  } catch (_) {}
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const open = windows.find((client) => new URL(client.url).origin === self.location.origin);
    if (open) return open.focus().then(() => open.navigate(target.href));
    return clients.openWindow(target.href);
  }));
});

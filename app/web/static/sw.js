/* Service worker — ilova qobig'ini keshlaydi.
   Muhim: API javoblari keshlanmaydi, aks holda eski ma'lumot ko'rinardi. */
const CACHE = "nm-savdo-v7";
const SHELL = [
  "/app",
  "/static/app.css",
  "/static/app.js",
  "/static/icon-192.png",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/media/")) return;

  // Avval tarmoq — yangi versiya darhol yetib boradi; internet yo'q bo'lsa keshdan
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match("/app")))
  );
});


/* ---------------- Push bildirishnomalar ---------------- */

self.addEventListener("push", (e) => {
  let data = { title: "Savdo tizimi", body: "", url: "/app", tag: "nm" };
  try {
    if (e.data) data = Object.assign(data, e.data.json());
  } catch (err) {
    if (e.data) data.body = e.data.text();
  }

  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      tag: data.tag,
      renotify: true,
      vibrate: [80, 40, 80],
      data: { url: data.url || "/app" },
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || "/app";
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        // Ilova allaqachon ochiq bo'lsa — o'sha oynani ko'targanimiz ma'qul
        if (client.url.includes("/app") && "focus" in client) {
          client.navigate(target).catch(() => {});
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});

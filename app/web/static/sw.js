/* Service worker — ilova qobig'ini keshlaydi.
   Muhim: API javoblari keshlanmaydi, aks holda eski ma'lumot ko'rinardi. */
const CACHE = "nm-savdo-v3";
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

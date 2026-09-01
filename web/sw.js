/* Minimal service worker: keep the shell and what you already read available
   offline. No background sync, no push, no tracking, nothing that phones home.

   Network first everywhere, cache as the fallback. Cache-first would be faster
   on a second load and would also serve a stale app.js after an update, which
   on a locally-hosted application is a bad trade. */
const CACHE = "mcpnews-v2";
const SHELL = [
  "/", "/index.html", "/styles.css", "/app.js", "/manifest.webmanifest",
  "/icon.svg", "/i18n/en.json",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;

  e.respondWith((async () => {
    try {
      const fresh = await fetch(request);
      /* Only the shell and the catalogues are worth keeping; API responses go
         stale in minutes and a stale feed is worse than no feed. */
      if (fresh.ok && !url.pathname.startsWith("/api/")) {
        const cache = await caches.open(CACHE);
        cache.put(request, fresh.clone());
      }
      return fresh;
    } catch (err) {
      const cached = await caches.match(request);
      if (cached) return cached;
      if (request.mode === "navigate") {
        const shell = await caches.match("/index.html");
        if (shell) return shell;
      }
      throw err;
    }
  })());
});

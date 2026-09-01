/* Minimal service worker: cache the shell so previously-loaded articles stay
   readable offline. No background sync, no push, no tracking. */
const CACHE = "mcpnews-v1";
const SHELL = ["/", "/index.html", "/styles.css", "/app.js", "/manifest.webmanifest"];

self.addEventListener("install", e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))));

self.addEventListener("activate", e =>
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))));

self.addEventListener("fetch", e => {
  const { request } = e;
  if (request.method !== "GET") return;
  /* API: network first, so the feed is fresh. Shell: cache first. */
  if (new URL(request.url).pathname.startsWith("/api/")) {
    e.respondWith(fetch(request).catch(() => caches.match(request)));
  } else {
    e.respondWith(caches.match(request).then(r => r || fetch(request)));
  }
});

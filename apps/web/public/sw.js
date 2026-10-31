// App-shell-only service worker: caches the page shell so the app opens fast and installs
// on a phone. It never caches /api/* (health data stays out of the browser's storage).
const CACHE = "cha-shell-v1";
const SHELL = ["/", "/scoreboard/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

function cacheable(url) {
  const u = new URL(url, self.location.origin);
  if (u.origin !== self.location.origin) return false;
  if (u.pathname.startsWith("/api/")) return false;
  return SHELL.includes(u.pathname) || u.pathname.startsWith("/_next/static/");
}
self.__cacheable = cacheable;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || !cacheable(req.url)) return; // network only: never stored
  event.respondWith(fetch(req).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
    return res;
  }).catch(() => caches.match(req).then((hit) => hit || Response.error())));
});

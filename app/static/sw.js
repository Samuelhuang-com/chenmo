// 辰墨軒 Service Worker
// 頁面：先走網路，斷線時改用快取，再不行就顯示離線頁。
// 靜態檔（CSS/JS/圖示）：先回快取、背景更新。
// API、WebSocket、登入流程一律不快取。
const VERSION = "__VERSION__";
const CACHE = `chenmo-${VERSION}`;
const PRECACHE = ["/offline", "/static/css/main.css"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("chenmo-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const NEVER = ["/api/", "/ws/", "/master/auth", "/me/login", "/me/logout", "/master/logout", "/sw.js"];

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (NEVER.some((p) => url.pathname.startsWith(p))) return;

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok && !url.pathname.startsWith("/master")) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(async () => (await caches.match(req)) || caches.match("/offline"))
    );
    return;
  }

  // CSS / JS：先走網路（確保拿到最新版），離線才用快取
  if (/\.(css|js)$/.test(url.pathname)) {
    event.respondWith(
      fetch(req)
        .then((res) => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); } return res; })
        .catch(async () => (await caches.match(req)) || Response.error())
    );
    return;
  }

  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(
      caches.open(CACHE).then(async (c) => {
        const cached = await c.match(req);
        const fresh = fetch(req).then((res) => { if (res.ok) c.put(req, res.clone()); return res; }).catch(() => cached);
        return cached || fresh;
      })
    );
  }
});

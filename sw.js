// HRP planner - offline service worker.
//
// Two caches, deliberately separate:
//   SHELL  the page itself + icons. Small, versioned, replaced on each deploy.
//   TILES  OpenTopoMap raster tiles. Large, long-lived, survives shell updates
//          so a redeploy never throws away a 22 MB download made on wifi.
//
// Tile caching here is ordinary HTTP caching, not scraping: OpenTopoMap serves
// the tiles with `Cache-Control: max-age=604800` and `Access-Control-Allow-Origin: *`,
// so responses are CORS-readable (not opaque) and carry no storage-quota padding.

const VERSION = 'v1';
const SHELL = 'hrp-shell-' + VERSION;
const TILES = 'hrp-tiles';           // intentionally unversioned
const TILE_HOST = /(^|\.)tile\.opentopomap\.org$/;
const TILE_MAX = 4000;               // hard ceiling, ~190 MB worst case

const SHELL_URLS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png',
  './apple-touch-icon.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(SHELL)
      .then(c => c.addAll(SHELL_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        // Drop old shells; never touch the tile cache.
        keys.filter(k => k.startsWith('hrp-shell-') && k !== SHELL)
            .map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // --- map tiles: cache first, then network ------------------------------
  if (TILE_HOST.test(url.hostname)) {
    e.respondWith(
      caches.open(TILES).then(cache =>
        cache.match(req).then(hit => {
          if (hit) return hit;
          return fetch(req).then(res => {
            if (res && res.status === 200) cache.put(req, res.clone());
            return res;
          }).catch(() => hit || Response.error());
        })
      )
    );
    return;
  }

  // --- the page and its icons: network first, fall back to cache ---------
  // Network-first so a redeploy is picked up as soon as there is signal,
  // while a dead connection still serves the last good copy.
  if (url.origin === self.location.origin) {
    e.respondWith(
      fetch(req)
        .then(res => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(SHELL).then(c => c.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req).then(hit => hit || caches.match('./index.html')))
    );
  }
});

// --- messages from the page --------------------------------------------
self.addEventListener('message', e => {
  const msg = e.data || {};
  const reply = m => e.source && e.source.postMessage(m);

  if (msg.type === 'TILE_STATS') {
    caches.open(TILES)
      .then(c => c.keys())
      .then(keys => reply({ type: 'TILE_STATS', count: keys.length }));
  }

  if (msg.type === 'TILE_CLEAR') {
    caches.delete(TILES).then(() => reply({ type: 'TILE_STATS', count: 0 }));
  }

  // Warm the tile cache for a list of URLs. Concurrency is capped at 4 to stay
  // a polite guest on a volunteer-run tile server.
  if (msg.type === 'TILE_PREFETCH') {
    const urls = msg.urls || [];
    let done = 0, failed = 0, added = 0;
    caches.open(TILES).then(cache => {
      const queue = urls.slice();
      const worker = () => {
        const u = queue.shift();
        if (!u) return Promise.resolve();
        return cache.match(u)
          .then(hit => {
            if (hit) return;                       // already have it, no request
            return fetch(u, { mode: 'cors' })
              .then(res => {
                if (res && res.status === 200) { added++; return cache.put(u, res); }
                failed++;
              })
              .catch(() => { failed++; });
          })
          .then(() => {
            done++;
            if (done % 10 === 0 || done === urls.length) {
              reply({ type: 'TILE_PROGRESS', done, total: urls.length, added, failed });
            }
            return worker();
          });
      };
      return Promise.all([worker(), worker(), worker(), worker()])
        .then(() => cache.keys())
        .then(keys => {
          // Enforce the ceiling oldest-first if a run pushed us over.
          if (keys.length > TILE_MAX) {
            return Promise.all(keys.slice(0, keys.length - TILE_MAX).map(k => cache.delete(k)))
              .then(() => cache.keys());
          }
          return keys;
        })
        .then(keys => reply({ type: 'TILE_DONE', done, total: urls.length, added, failed, count: keys.length }));
    });
  }
});

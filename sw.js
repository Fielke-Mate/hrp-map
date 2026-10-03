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

const VERSION = 'v3';
const SHELL = 'hrp-shell-' + VERSION;
const TILES = 'hrp-tiles';           // intentionally unversioned
const TILE_HOST = /(^|\.)tile\.opentopomap\.org$/;
const TILE_MAX = 4000;               // hard ceiling, ~190 MB worst case

const SHELL_URLS = [
  './',
  './index.html',
  './planner.html',
  './leaflet.js',
  './leaflet.css',
  './manifest.webmanifest',
  './planner.webmanifest',
  './icon-192.png',
  './icon-512.png',
  './apple-touch-icon.png',
  // The planner's data, all three routes, so it can still plan with no
  // signal. Fetched at runtime it would only be cached once the page was
  // already controlled - which the first visit never is.
  './data/shelters.json',
  './data/routes/hrp.json',
  './data/routes/gr10.json',
  './data/routes/gr11.json'
];

// Refuge and hotel wifi commonly answers EVERY request with its login page
// until you sign in - status 200, no error. Saved under our URLs, that page
// would replace the real files, and the planner would be broken the next time
// there was no signal at all. So a response is kept only if it is plainly the
// file that was asked for:
//   a page      must link one of our manifests (no login page does)
//   route/hut   data must actually be JSON
//   anything    else must at least not be an HTML page
// and never a redirect, an error status or an opaque response.
function trustworthy(req, res){
  if (!res || res.status !== 200 || res.redirected || res.type === 'opaque')
    return Promise.resolve(false);
  const type = (res.headers.get('content-type') || '').toLowerCase();
  const path = new URL(req.url).pathname;
  if (req.mode === 'navigate' || /\/$|\.html$/.test(path))
    return res.clone().text().then(t => /(planner|manifest)\.webmanifest"/.test(t));
  if (/\/data\/.*\.json$/.test(path)) return Promise.resolve(type.indexOf('json') >= 0);
  return Promise.resolve(type.indexOf('text/html') < 0);
}

self.addEventListener('install', e => {
  // Fetched one by one rather than addAll, because addAll accepts any 200 -
  // installing behind a wifi login page would fill the new shell with login
  // pages, and activation would then delete the good one. A failed check
  // abandons the install; the previous version and its cache stay in charge.
  // cache:'reload' bypasses the HTTP cache so a new version gets new files.
  e.waitUntil(
    caches.open(SHELL).then(cache => Promise.all(SHELL_URLS.map(u => {
      const req = new Request(u, { cache: 'reload' });
      return fetch(req).then(res => trustworthy(req, res).then(ok => {
        if (!ok) throw new Error('not trusting the response for ' + u);
        return cache.put(u, res);
      }));
    }))).then(() => self.skipWaiting())
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
          }).catch(() => Response.error());
        })
      )
    );
    return;
  }

  // --- the page and its icons: network first, fall back to cache ---------
  // Network-first so a redeploy is picked up as soon as there is signal,
  // while a dead connection still serves the last good copy.
  if (url.origin === self.location.origin) {
    // Hut and route data revalidate with the server on every load when there
    // is signal. A safety correction - a refuge closed for good - must reach a
    // phone that cached the old file, not wait out a heuristic HTTP cache
    // lifetime, which in testing kept a browser planning with stale huts.
    const isData = url.pathname.indexOf('/data/') >= 0;
    e.respondWith(
      fetch(req, isData ? { cache: 'no-cache' } : undefined)
        .then(res => trustworthy(req, res).then(ok => {
          if (ok) {
            const copy = res.clone();
            caches.open(SHELL).then(c => c.put(req, copy));
            return res;
          }
          // A server error, a redirect, or a wifi login page: the saved copy
          // is better than whatever this is, if there is one.
          return caches.match(req).then(hit => hit || res);
        }))
        // Only a page navigation may fall back to the HRP page. Answering a
        // failed data request with HTML made the planner's JSON parse throw.
        .catch(() => caches.match(req).then(hit => hit
          || (req.mode === 'navigate' ? caches.match('./index.html') : Response.error())))
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
            // Already stored: no request, but re-save it. A put moves the entry
            // to the newest end, so if this run pushes the cache over TILE_MAX
            // the eviction below removes OTHER areas - never part of the
            // section being saved now, which a plain skip would have left at
            // the old end, first in line to be deleted.
            if (hit) return cache.put(u, hit);
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

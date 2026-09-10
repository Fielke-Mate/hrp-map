# HRP map — hosting and offline use

Everything in this folder is static. No build step, no server-side anything.

## 1. Put it online

You need **https** — service workers and GPS are both refused on plain http
and on `content://` URLs (which is what Android hands Chrome when you open a
file from the Downloads list).

**Netlify Drop — no account needed**
1. Go to <https://app.netlify.com/drop>
2. Drag this whole `site` folder onto the page
3. You get an https URL straight away

Claim it with a free account if you want it to stick around, and rename it to
something memorable under Site settings → Change site name.

**GitHub Pages — if you'd rather it lived in a repo**
1. Create a new public repo on github.com
2. Upload the contents of this folder (Add file → Upload files)
3. Settings → Pages → Source: `main`, folder: `/root`
4. Live at `https://<user>.github.io/<repo>/` in about a minute

## 2. On the phone

1. Open the URL in Chrome (Android) or Safari (iOS)
2. **Add to Home Screen** — Share → Add to Home Screen on iOS, ⋮ → Add to
   Home screen on Android
3. Open it from that icon, tap **⇩ Offline maps** → **Download corridor**,
   while still on wifi

Standard detail is ~474 tiles / ~22 MB and covers 2 km either side of the
route at zoom 9–14. High detail adds zoom 15: ~1,500 tiles / ~71 MB.

**Add to Home Screen is not optional on iOS.** Safari clears the cache of
sites that are only bookmarked after about 7 days unused. Installed ones are
exempt.

## 3. What works with no signal

Cached by the page itself, so always available:

- the route, all 58 shelters, the day splits and the elevation profile
- leg distances between shelters
- **your GPS position** — the receiver needs no data connection

Only the topographic background needs the tile download. Without it you get
the route on a blank background, which is still perfectly readable.

## Files

| File | |
|---|---|
| `index.html` | The whole map. Leaflet is inlined, so no CDN. |
| `sw.js` | Service worker: caches the page, and tiles as you view them. |
| `manifest.webmanifest` | Makes it installable. |
| `icon-*.png` | Home screen icons, drawn from the route shape. |

## Updating it

Re-upload `index.html`. The service worker is network-first for the page, so
a phone with signal picks up the new version on next open. Bump `VERSION` in
`sw.js` if you change `sw.js` itself. The tile cache is deliberately kept in a
separate, unversioned cache so a redeploy never throws away a 22 MB download.

## Tiles

OpenTopoMap, CC-BY-SA. They serve tiles with `Cache-Control: max-age=604800`
and permit downloading "as long as our server is not overly strained by mass
downloads". The prefetch is capped at 4 concurrent requests and skips anything
already cached. It is a few hundred tiles for one walker, once — please don't
loop it.

**This is a planning aid, not a navigation system.** Carry a proper offline
topo app and a paper map.

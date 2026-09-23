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

## Building

`index.html` is generated, not hand-edited. The source and the whole toolchain
live in `src/`:

```
python src/build.py
```

That inlines Leaflet 1.9.4 (vendored in `src/`, so no CDN and the page works
with no signal), adds the PWA tags, sets `crossOrigin` on the tile layer, and
appends the offline block. It is deterministic - rebuilding without changing
`src/hrp_wallon_luchon.html` reproduces `index.html` byte for byte.

**`src/hrp_wallon_luchon.html` is the only source.** `index.html` is output.
Editing `index.html` directly gets overwritten by the next build.

After cloning, run this once so the pre-commit hook is active:

```
git config core.hooksPath .githooks
```

### What the build refuses to do

Each guard exists because the mistake behind it actually happened here.

| Guard | The mistake it prevents |
|---|---|
| a second copy of the source | An edit went into a top-level copy while the build read `src/`, producing a page silently missing the change |
| `--check` (pre-commit hook) | Committing an `index.html` that does not match its source |
| temporal-dead-zone lint | A module-level `const` read by a function that startup calls earlier in the file. It throws at load and aborts the rest of the script, but hoisted functions stay callable so the page looks alive. `node --check` cannot see it - it is a runtime error. This happened twice. |
| popup consistency | A popup's heading or elevation drifting from its `shelterIndex` entry. Renaming a hut moved the popup's key but left the old name in its `<h4>`, so the map kept announcing "Cabane de Mommour"; correcting entry elevations left two popups quoting superseded figures. Elevation tolerance 30 m. |
| `__hrpReady` sentinel | Tests asserting "the page works" when the script actually threw partway through |

The TDZ lint follows the call graph, since both real cases were indirect
(`updateDayCards` -> `calcDayStats` -> the const). Put the value inside the
function or make it a hoisted function; `tdz-ok` in a comment on the
declaration overrides it.

Run `python src/build.py --check` any time to confirm the committed page
matches its source.

## Exporting

**Export GPX** in the header writes GPX 1.1 with a single `<trk>` - Komoot,
Gaia and Garmin all import that reliably, whereas multiple `<trk>` elements get
split or partly ignored. It exports the plan as it currently stands, including
any overnight stops you have changed and the live Day 6 re-route.

- **Whole route** - 8,781 points, ~590 KB
- **Selected day** - pick a day card first; ~1,500 points, ~100 KB
- **Overnight stops as waypoints** (on by default), or every shelter currently
  shown on the map
- **Reduce points** - simplifies at 5 m for apps that cap track size. Costs
  about 2.2 km of the 144 km; the exact loss is reported after each download.

Per-day files are the easier import if a tool complains about size.

## Tiles

OpenTopoMap, CC-BY-SA. They serve tiles with `Cache-Control: max-age=604800`
and permit downloading "as long as our server is not overly strained by mass
downloads". The prefetch is capped at 4 concurrent requests and skips anything
already cached. It is a few hundred tiles for one walker, once — please don't
loop it.

## Route geometry

Every route array was measured against OpenStreetMap highway geometry - the
distance from each point to the nearest mapped way:

| array | points | median | max | > 25 m |
|---|---|---|---|---|
| TRACK | 7,912 | 0.2 m | 55 m | 1 |
| LUCHON_DESCENT | 1,480 | 0.2 m | 0.7 m | 0 |
| BUS965_ROUTE | 319 | 0.2 m | 0.6 m | 0 |
| BUS_ROUTE | 418 | 0.2 m | 0.6 m | 0 |

TRACK was not always like that. It used to be a decimated 1,408-point line that
cut switchback corners: median 3.3 m off the trail but up to 104 m, with 50
points beyond 25 m. Because the shortcuts skipped real zigzags it **understated
distance by 9.1%** - 121.11 km where the trail is 132.15 km. That is the
dangerous direction for an error, since distance drives the time estimates.

It was re-routed through its own waypoints with BRouter (hiking-beta), which
keeps every curated decision - the Parzan spur and the Marcadau descent stay cut
- while restoring the real trail between them. Verified afterwards that no point
strays more than 250 m from the original line, so nothing new was introduced.
Three short stretches kept their original geometry where BRouter's server-side
watchdog repeatedly timed out.

The headline total moved from 134 km to 144 km as a result. The route on the
ground did not change; the measurement of it got honest.

## Shelter data

All 55 shelters carry coordinates taken from OpenStreetMap, at full precision,
with the source feature id recorded in each entry (`OSM node/892738761`). None
are hand-placed.

They were not always. An audit found 28 of the original 58 entered by hand at
three decimal places (about +-55 m), and three of those sat on open hillside:

- **Gite La Munia (Heas)** - a duplicate of Auberge de la Munia, pinned 464 m away
- **Abri de Caillauas** - a duplicate of Refuge de Caillauas, the same OSM feature
- **Cabane de Sarnes / Crabioules** - no feature of that name within 3 km of the
  pin, and none anywhere nearby. Removed rather than shown in a guessed place.

Two were also misnamed: *Cabane de Mommour* is **Cabane du Cortail de Batoua**,
and *Gite du Maillet* is **Auberge du Maillet**.

Shelter positions are drawn on the map and drive the "distance to the next place
I could sleep" figures, so a wrong pin is a safety problem rather than a cosmetic
one. To re-check them against current OSM, re-run the audit before a trip - huts
are rebuilt, renamed and demolished.

Leg distances now include the walk off the route to reach each shelter, marked
with a leading `~` because the off-route portion is straight-line and therefore
a minimum. The climb figure covers the on-route part only.

**This is a planning aid, not a navigation system.** Carry a proper offline topo
app and a paper map, and do not rely on any hut being open, stocked or standing.

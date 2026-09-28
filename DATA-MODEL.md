# Data model — Pyrenees traverse planner

Draft for sign-off. Nothing is built against this yet.

Measurements quoted here come from the OSM survey on 2026-09-23 and from the
current HRP tool; they are not estimates.

---

## 1. What changes, and why

The current tool is one fixed itinerary: a single `TRACK` array where each
point carries the day it belongs to (`[lat, lon, ele, day]`), five hardcoded
overnight stops, and a hardcoded journey to the trailhead.

The target is a planner for the whole range: pick a route, say where you want
to start and finish, say how far you like to walk and what you will sleep in,
and get a staged itinerary you can adjust and export.

Three things force a new model:

1. **Three routes, not one.** GR10 (~929 km), GR11 (~871 km), HRP (~758 km).
2. **Days belong to the plan, not the map.** With a user-chosen start, end and
   daily range, the same geometry yields different days for different walkers.
   A day tag baked into the geometry cannot express that.
3. **The routes interconnect.** The HRP runs within 500 m of the GR10 for
   **20.6%** of its length across ~16 zones, and of the GR11 for **10%** across
   ~9 zones. GR10 and GR11 never meet each other at all. The HRP is the spine
   between them, so switching routes mid-trip is a normal thing to want.

---

## 2. The one idea everything rests on

**A route is a single continuous polyline. Every other thing is an interval or
a point measured in kilometres along it.**

A stage is `[startKm, endKm]`. A day is `[startKm, endKm]`. A section you pick
is an interval. A shelter is a km value plus how far off to one side it sits. A
junction is a km value on two routes at once.

That turns almost every question into one-dimensional arithmetic on a sorted
array, which is why the existing `routeIndex()` already makes leg distances and
"next place I can sleep" cheap. It generalises directly.

**A position is therefore `{route: "hrp", km: 97.7}`** — never a bare
coordinate. Latitude and longitude are derived from it for drawing.

---

## 3. Entities

### 3.1 Route

One file per route. Geometry stitched **by connectivity, not by relation member
order** — OSM does not guarantee member order, and assuming it produced phantom
gaps of up to 19 km in my first survey pass.

```jsonc
{
  "id": "hrp",
  "name": "Haute Randonnée Pyrénéenne",
  "ref": "HRP",
  "from": "Hendaye", "to": "Banyuls-sur-Mer",
  "lengthKm": 757.5,
  "source": {
    "osmRelations": [3326074, 3326179, "…41 stage relations"],
    "wikidata": "Q924990",
    "licence": "ODbL",
    "fetched": "2026-09-23",
    "simplifiedToM": 5
  },
  "geometry": [[42.85162, -0.13667, 1465], …],   // lat, lon, ele — no day tag
  "stages": [
    { "n": 19, "name": "Étape 19",
      "from": "Refuge de Viados", "to": "Refuge de la Soula",
      "startKm": 352.1, "endKm": 374.8, "osmRelation": 3341112 }
  ],
  "variants": [
    { "ref": "HRP 19.1", "name": "Variante 19.1",
      "rejoinsAtKm": [352.1, 374.8], "geometry": [ … ] }
  ]
}
```

Notes:

- `geometry` has **no day index**. That is the point.
- Cumulative distance is computed once on load, not stored — it is derivable
  and storing it invites drift.
- Stage `from`/`to` come straight from OSM and are already good: the HRP and
  GR11 tag every stage with named endpoints. **GR10 does not** — it has only 9
  coarse sections, so its stage list must be derived rather than inherited.
- Variants matter for the HRP (~46 of them) — they are the bad-weather and
  high-level alternatives a planner should offer.

### 3.2 Shelter

One shared file. A shelter is **not** owned by a route; it projects onto every
route it is near. Refugio de Viados is on both the HRP (Étapes 18/19) and the
GR11 (E21/E22) — verified in the OSM tags.

```jsonc
{
  "id": "osm:way/848321849",
  "name": "Refugio de Barrosa",
  "type": "C",
  "ll": [42.703992, 0.157441],
  "ele": 1745,
  "eleSource": "osm",                // osm | dem  — never typed in
  "capacity": 12,
  "staffed": null,
  "season": null,
  "notes": "Renovated, wood stove, good condition.",
  "on": [
    { "route": "hrp",  "km": 69.6,  "offM": 120 },
    { "route": "gr11", "km": 412.3, "offM": 240 }
  ],
  "verified": "2026-09-22"
}
```

`type` needs widening beyond the current R/C/A for the GR routes, which pass
through villages:

| code | meaning |
|---|---|
| `R` | staffed refuge — warden, meals |
| `C` | cabane / unattended hut with basic kit |
| `A` | abri — walls and roof only |
| `G` | gîte d'étape / albergue — staffed, in or near a village |
| `H` | hotel / guesthouse |
| `B` | campsite |

Nothing enters this file without a resolvable `id` and a `verified` date. Of
the original 58 HRP shelters, 28 had been typed in by hand and three pointed at
open hillside; that is not repeatable at range scale.

### 3.3 Junction

Where two routes coincide or cross. Generated offline, not authored.

```jsonc
{ "id": "j-hrp-gr11-viados",
  "ll": [42.6402, 0.3358],
  "on": [ { "route": "hrp", "km": 352.1 }, { "route": "gr11", "km": 412.3 } ],
  "separationM": 35 }
```

~25 measured zones. These are what make a multi-route plan possible.

### 3.4 Plan

The user's document. This is the only mutable thing, and the only thing worth
putting in a share link or localStorage.

```jsonc
{
  "v": 1,
  "legs": [                                   // route intervals, in walking order
    { "route": "hrp",  "fromKm": 300.0, "toKm": 352.1 },
    { "route": "gr11", "fromKm": 412.3, "toKm": 470.0 }
  ],
  "constraints": {
    "dayKm": [10, 20],
    "maxAscentM": 1600,
    "shelterTypes": ["R", "G"],
    "maxOffRouteKm": 1.5
  },
  "stops": [                                   // overnight stops, in order
    { "shelter": "osm:way/848321849", "night": 1, "locked": false }
  ],
  "startedFrom": "auto"                        // auto | manual
}
```

`stops` is the itinerary. `locked: true` means the auto-planner must keep that
stop and plan around it — that is how "computed for me, but I insist on night 3
at Viados" works.

---

## 4. Derived, never stored

| Derived | From |
|---|---|
| Days | consecutive entries in `stops`, plus the start and end |
| Day distance | `offRoute(a) + (km_b − km_a) + offRoute(b)` — door to door |
| Day ascent | elevation resampled at **25 m** then a 3 m threshold |
| Day time | Naismith: 4 km/h + 1 h per 600 m of ascent |
| Cumulative distance | computed on load from geometry |
| Shelter projections | computed at build time, stored in `on[]` |

Two conventions carried over because both were bugs once:

- **Distance is door to door.** Off-route detours to reach a hut are included.
  Omitting them understated the walk, which is the dangerous direction.
- **Ascent is resampled to a fixed 25 m interval first.** Counting every 3 m
  rise on raw points makes the number depend on how densely the track was
  sampled — the same hillside read 8,032 m at 496 points and 9,135 m at 7,912.

---

## 5. The auto-planner

**Input:** start, end, `dayKm: [min, max]`, shelter types, max off-route, and
optionally max ascent or a target number of days.

**Method.** Candidate stops are the shelters projecting onto the plan's legs
between start and end that match the filters. Sorted by km, they form a DAG:
an edge `a → b` exists when the day from `a` to `b` satisfies every constraint.
Each edge costs

```
cost = |dayKm − ideal|          ideal = midpoint of the requested range
     + ascentPenalty            above the configured ceiling
     + typePenalty              for a shelter outside the preferred types
     + offRoutePenalty          for a long detour
```

and the plan is the minimum-cost path from start to end, solved by dynamic
programming over stops in km order. A few hundred candidates at most, so it is
instant.

**Why not greedy.** Walking the target distance and taking the nearest hut each
time — the obvious approach — paints itself into corners: it will happily leave
a 26 km stretch with nothing in it for the final day. Shortest-path over the
whole range avoids that for the same effort.

**Infeasibility must be explained, never fudged.** If no valid path exists the
answer is a reason and an option, not a silent stretch:

> No accommodation between Refuge de Barroude and Refugio de Viados for 28.4 km,
> above your 20 km maximum. Raise the daily maximum to 29 km, include cabanes
> (adds 2 options), or plan a bivouac.

This is the feature that no GPX file gives you, and everything already built —
verified shelters, leg distances, Naismith timings — exists to feed it.

---

## 6. Files and loading

```
data/
  routes/gr10.json      geometry + stages     ~0.55 MB simplified
  routes/gr11.json                            ~0.40 MB
  routes/hrp.json                             ~0.43 MB
  shelters.json         all shelters, all projections
  junctions.json
```

159,244 raw points across the three routes, about **3.9 MB** of coordinates, or
**~1.4 MB** simplified at 5 m. Small enough to ship as static JSON, too big to
inline into one HTML file — so the app shell and the data separate, and a route
loads when it is first needed.

The service worker caches route JSON alongside the shell. Tile prefetch becomes
**per section**, not per range: the whole Pyrenees at z9–14 is ~435 MB, which is
not a thing to offer.

---

## 7. What happens to the current code

| Now | Becomes |
|---|---|
| `TRACK` with `[lat,lon,ele,day]` | `route.geometry` `[lat,lon,ele]`; day tag deleted |
| `TRACK_ORIG` restore dance | gone — geometry is immutable, plans are separate |
| `computeDaySplits()` | `derivePlan(plan)` — pure, no mutation of geometry |
| `selectedNights{1..5}` | `plan.stops[]`, any length |
| `shelterIndex` | `shelters[]` with `on[]` projections |
| `routeIndex()` | per-route, cached, same idea |
| `LUCHON_DESCENT`, bus routes, transport card | deleted |
| `activeDay` | `plan.selectedDay` |

Worth keeping as-is: the shelter/leg concepts, GPS-on-route, offline-first, GPX
export, the build guards, and the verification discipline.

GPX **import** stays, demoted: useful for overlaying your own track against the
official line for comparison, not as a data path.

---

## 8. Decisions I need you to confirm

1. **Route = one polyline, everything else an interval on it.** The whole model
   follows from this.
2. **Days derived from stops, never stored in geometry.**
3. **Shelter types widen to R/C/A/G/H/B** to cover village accommodation on the
   GR routes.
4. **A plan can span several routes** via junctions, rather than being locked to
   one.
5. **Data splits from code** into per-route JSON.
6. **Transport is dropped entirely** for now — start and end are just positions.

## 9. Open questions

- **GR10 stages.** Only 9 coarse sections, against 37 and 41. Derive day-sized
  stages from shelter spacing, or leave GR10 without a stage layer and rely
  purely on the auto-planner?
- **Overlap drawing.** A fifth of the HRP is coincident with the GR10. Draw both
  and accept doubled lines, or detect overlap and draw once?
- **Shelter coverage off the HRP corridor.** The current 55 are the HRP section
  only. The range-wide fetch will be several hundred, and the GR routes pass
  through villages where "accommodation" means hotels and gîtes — a different
  data quality problem from mountain huts.
- **Opening seasons.** Unstaffed huts are always open; staffed refuges are not,
  and OSM records this inconsistently. Do we model season at all in v1, or state
  plainly that we do not?

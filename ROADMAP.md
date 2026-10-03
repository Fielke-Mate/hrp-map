# Pyrenees traverse planner — roadmap

Goal: a public planning tool for the GR10, GR11 and HRP that a hiker can rely
on, including on a phone with no signal. Accommodation is safety critical: a
plan that sends someone to a hut that is gone, closed or locked can strand them.

Ordered by risk to a hiker first, then by usefulness.

| # | Item | Why | Status |
|---|------|-----|--------|
| 1 | **Accommodation safety pass** — never plan to a hut OSM records as demolished, ruined, abandoned, closed or private; show the reason on the map | 104 of 452 feasible plans in a sweep stopped at such a hut | **done** |
| 2 | **Access points** — stations, bus stations and airports, with distance to the trail; click one to start or finish there | Your idea: plan from where the train arrives | needs Q6–Q10 |
| 3 | **Offline for the planner** — page and all route and hut data saved on first visit; map tiles saved per section with a size estimate and a hard cap; data re-checked whenever there is signal; wifi login pages can no longer overwrite saved files | The planner did not work offline at all | **done** |
| 4 | **Phone layout** — on narrow screens everything stacks: map first at full width, then profile, then days; limits fold behind a Settings button; the key collapses | The map was 35 px wide on a 375 px phone | **done** |
| 5 | **Your location** — GPS dot, distance along the route to the next stop | The first feature this project had; the planner lost it | |
| 6 | **Shareable plan links** — route, section, limits, types and locked stops in the URL | Send a plan to a walking partner and reopen it unchanged | |
| 7 | **Multi-route itineraries** — switch routes at the measured junctions | Agreed earlier; the largest remaining feature | needs Q4 |
| 8 | **Cross-check huts against refuges.info** — 368 records carry its id; it records whether a hut is usable | The strongest second source for the safety question | needs Q5 |
| 9 | **Public-launch readiness** — disclaimer, attribution, a tile provider whose policy allows bulk offline download, a data refresh pipeline | Required before strangers rely on it | needs Q1 |

## Open questions

1. **Who is the next version for** — you and walking partners, or a public launch?
2. **The original HRP tool at the root URL** — keep as an archive, or make the planner the front page?
3. **Private or reported-closed huts** — default: never auto-planned, but lockable by a hiker who knows they are open. Ruined and demolished huts can be neither planned nor locked. Change this?
4. **Multi-route plans** — should the planner choose where to switch routes, or should you?
5. **refuges.info** — happy to use it as a verification source (external dependency, CC BY-SA)?

Access points (item 2) — recommendation in brackets:

6. **Which kinds?** (train stations and airports, plus proper bus stations in towns — not every roadside stop)
7. **How close to the trail?** (show both, labelled "on the trail" within 3 km and "onward transport needed" within ~20 km)
8. **Airports?** (gateway markers when zoomed out, plus nearest airports listed for the plan's start and finish)
9. **Click a station to set start/finish?** (yes — snap to the nearest trail point)
10. **Timetables?** (no — location plus a link to the operator; summer-only services cannot be read reliably from OSM)

## How hut status works

Structured OSM tags set a status automatically: `access=private|no` → private;
`demolished:*`, `disused:*`, `historic=ruins`, `abandoned=yes` … on the keys
that make it accommodation → gone; `opening_hours=off|closed` → closed.

Free-text notes and descriptions only *nominate* a hut for review. Keyword
matching on prose was wrong about half the time — "the refuge is open, simply
closed by an iron door"; "a ruined hut restored in 2019" — so each nomination
gets a human decision with a reason in `src/data/status_review.json`, and
`finalise_shelters.py` refuses to write the data while any is unreviewed.

## Known limits

- Behind a wifi login page a phone reports itself online, so the offline panel says
  "Online" while the planner is in fact running from saved data. It still works;
  only the label is wrong.
- Saved map tiles come from OpenTopoMap, a volunteer-run server. Per-section saving
  with a 4,000-tile cap is reasonable for personal use; a public launch needs a
  provider whose terms allow offline download (item 9).

## Done

- Phone layout: map 375 px wide and 120 px from the top on a phone (was 35 px wide, 386 px down)
- Offline planner, tested with the server dropping connections, answering with a
  wifi login page, returning 503, and a service-worker update installing behind a
  login page (`src/offline_test_server.py`)
- Hut status: ruined, closed and private huts never planned (this change)
- Every visible route's lines and accommodation shown (`a72b290`)
- Min/max distance and climb per day, click snapping, draggable pins, real reset (`47a2142`)
- Locked stops, with pinned nights (`a45acc7`)

# Pyrenees traverse planner — roadmap

Goal: a public planning tool for the GR10, GR11 and HRP that a hiker can rely
on, including on a phone with no signal. Accommodation is safety critical: a
plan that sends someone to a hut that is gone, closed or locked can strand them.

Ordered by risk to a hiker first, then by usefulness.

| # | Item | Why | Status |
|---|------|-----|--------|
| 1 | **Accommodation safety pass** — never plan to a hut OSM records as demolished, ruined, abandoned, closed or private; show the reason on the map | 104 of 452 feasible plans in a sweep stopped at such a hut | **done** |
| 1b | **Hut links** — call, email, booking flag, website, refuges.info and pyrenees-refuges pages, OSM source; every hut-database link checked by position, every website checked, dead ones explained not linked | Where you sleep is critical; if it does not exist you sleep outside | **done** |
| 1c | **Hut types against the hut databases** — 10 staffed refuges are classified too low (Bayssellance, Ayous, Oulettes de Gaube shown as bare shelters); 1 was too high (Refuge Da Silva, now fixed) | A "staffed refuges only" plan skips the best-known HRP refuges | needs your OK |
| 2 | **Access points** — 25 places to start, each with the realistic ways from Paris: a direct train to the trail, or a direct train to a gateway then a regional train and/or bus; built from the official SNCF, liO and Pyrénées-Atlantiques timetables; Start/Finish here buttons | Plan from where the train arrives | **done** — Spanish side still to add |
| 3 | **Offline for the planner** — page and all route and hut data saved on first visit; map tiles saved per section with a size estimate and a hard cap; data re-checked whenever there is signal; wifi login pages can no longer overwrite saved files | The planner did not work offline at all | **done** |
| 4 | **Phone layout** — on narrow screens everything stacks: map first at full width, then profile, then days; limits fold behind a Settings button; the key collapses | The map was 35 px wide on a 375 px phone | **done** |
| 5 | **Your location** — GPS dot, km along the route, tonight's stop with door-to-door distance, climb along the route and time; never points at a closed or ruined hut | The planner had lost it; GPS works with no signal | **done** |
| 6 | **Shareable plan links** — the address always holds the plan; "Share this plan" uses the phone's share sheet or copies the link; locks to huts since marked ruined are refused and explained | Send a plan to a walking partner and reopen it unchanged | **done** |
| 7 | **Multi-route itineraries** — switch routes at the measured junctions | Agreed earlier; the largest remaining feature | needs Q4 |
| 8 | **Cross-check huts against refuges.info** — 368 records carry its id; it records whether a hut is usable | The strongest second source for the safety question | needs Q5 |
| 9 | **Public-launch readiness** — disclaimer, attribution, a tile provider whose policy allows bulk offline download, a data refresh pipeline | Required before strangers rely on it | needs Q1 |

## Open questions

1. **Who is the next version for** — you and walking partners, or a public launch?
2. **The original HRP tool at the root URL** — keep as an archive, or make the planner the front page?
3. **Private or reported-closed huts** — default: never auto-planned, but lockable by a hiker who knows they are open. Ruined and demolished huts can be neither planned nor locked. Change this?
4. **Multi-route plans** — should the planner choose where to switch routes, or should you?
5. **refuges.info** — happy to use it as a verification source (external dependency, CC BY-SA)?

Access points — open follow-ups:

6. **Spanish side** — load Renfe and the Navarra / Aragón / Catalonia bus timetables so GR11 starts are covered (today only Hendaye, Latour-de-Carol and Bourg-Madame).
7. **Airports** — not shown yet; train access came first, as you asked.

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

- Access from Paris: 25 trailheads from the official timetables, including the original trip (TGV to Lourdes, bus 965, navette to Pont d'Espagne) and home from Luchon
- Hut links: 365 refuges.info + 390 pyrenees-refuges pages verified by position; 577 websites checked, 75 dead ones explained instead of linked
- Shareable plan links, round trip verified identical (works offline: state is in the #fragment)
- Your location on the route, with tonight's stop (works offline)
- Phone layout: map 375 px wide and 120 px from the top on a phone (was 35 px wide, 386 px down)
- Offline planner, tested with the server dropping connections, answering with a
  wifi login page, returning 503, and a service-worker update installing behind a
  login page (`src/offline_test_server.py`)
- Hut status: ruined, closed and private huts never planned (this change)
- Every visible route's lines and accommodation shown (`a72b290`)
- Min/max distance and climb per day, click snapping, draggable pins, real reset (`47a2142`)
- Locked stops, with pinned nights (`a45acc7`)

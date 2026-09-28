# Route data pipeline

Produces `data/routes/{gr10,gr11,hrp}.json` from OpenStreetMap.

Run in order. Each step caches to the scratchpad, so later steps can be
re-run without re-querying Overpass.

| script | does |
|---|---|
| `survey_routes.py` | finds candidate route relations, writes `route_rels.json` |
| `measure_routes.py` | fetches member geometry for the main-line stages |
| `recheck_gaps.py` | checks whether consecutive stages actually touch |
| `build_routes.py` | stitches ways into one polyline per route, sweeps simplification tolerance |
| `finalise_routes.py` | writes the reference files with stage km intervals |
| `junctions.py` | measures where the three routes meet |

## Two things that will bite you

**Relation member order is not walking order.** Chaining members in stored
order produced phantom gaps of up to 19 km. The stitcher matches shared
endpoint coordinates instead; a shared OSM node has identical coordinates at
full precision. After that, every consecutive stage pair touches on all three
routes.

**Nearest-fragment joining is not safe.** Greedily attaching leftover runs to
whatever is closest stitched GR11 fragments across 57.7 km and 34.4 km of
empty ground, inflating the route from 829 km to 925 km. Fragments further
than 500 m from the line are dropped and reported instead.

## Choices

- **Simplified at 1 m**, which costs under 0.10% of length on all three. 5 m
  looked tempting at a third of the points but lost 1.2% - about 12 km on
  GR10 - and understating distance is the dangerous direction.
- **Normalised west to east** (Atlantic to Mediterranean). GR10 and GR11 are
  stored east-to-west upstream, so their stage `from`/`to` are swapped to
  match the flipped line.
- Elevation is **not yet attached**. Ascent figures need it; see DATA-MODEL.md.

## Licence

OpenStreetMap, ODbL 1.0, © OpenStreetMap contributors. Recorded in each file's
`source` block along with the relation ids and fetch date.

"""Produce data/shelters.json: deduplicated, elevation-corrected, labelled.

Three corrections the verification pass showed are needed:

  457 pairs of records sit within 30 m of each other - the same hut mapped
  twice, typically a building way plus a node inside it, or two contributors
  who did not notice each other. Merged, keeping the richer record and
  recording both ids.

  16 OSM ele tags disagree with the DEM by more than 50 m, the worst by
  1,276 m (Cabane Beille d'en Bas tagged 612 m where the ground is 1,888 m).
  Where they diverge that far the tag is wrong, so the DEM wins and the
  disagreement is recorded rather than hidden.

  526 records have no name. A planner that says "sleep at (unnamed)" is not
  useful, so they get a descriptive label built from what is known.
"""
import json, math, os
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(HERE, '.shelters')
recs = json.load(open(os.path.join(CACHE, 'projected.json')))

TYPE_WORD = {'R': 'refuge', 'C': 'cabane', 'A': 'shelter', 'G': 'gîte',
             'B': 'campsite', 'H': 'guesthouse'}
RICHNESS = {'high': 3, 'medium': 2, 'low': 1}


def gc(a, b):
    dlat = (b[0]-a[0])*111.0
    dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
    return math.sqrt(dlat*dlat + dlon*dlon)


def score(r):
    """how much this record is worth keeping as the primary of a merged pair"""
    s = 0
    if r['name']:
        s += 100
    s += RICHNESS.get(r['confidence'], 0) * 10
    s += len(r['tags'])
    if r['eleSource'] == 'osm':
        s += 2
    if r['capacity']:
        s += 3
    return s


# ---- 1. merge near-duplicates -------------------------------------------
CELL = 0.005
grid = defaultdict(list)
for i, r in enumerate(recs):
    grid[(int(r['ll'][0]/CELL), int(r['ll'][1]/CELL))].append(i)

parent = list(range(len(recs)))


def find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def union(i, j):
    a, b = find(i), find(j)
    if a != b:
        parent[b] = a


for i, r in enumerate(recs):
    c = (int(r['ll'][0]/CELL), int(r['ll'][1]/CELL))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for j in grid.get((c[0]+dx, c[1]+dy), ()):
                if j > i and gc(r['ll'], recs[j]['ll']) < 0.03:
                    union(i, j)

groups = defaultdict(list)
for i in range(len(recs)):
    groups[find(i)].append(i)

merged = []
merge_count = 0
for _, idxs in groups.items():
    members = [recs[i] for i in idxs]
    if len(members) > 1:
        merge_count += len(members) - 1
    members.sort(key=score, reverse=True)
    primary = dict(members[0])
    if len(members) > 1:
        primary['mergedFrom'] = [m['id'] for m in members[1:]]
        # keep the best information from any of them
        for m in members[1:]:
            if not primary['name'] and m['name']:
                primary['name'] = m['name']
            if not primary['capacity'] and m['capacity']:
                primary['capacity'] = m['capacity']
            if not primary['operator'] and m['operator']:
                primary['operator'] = m['operator']
        # a merged group takes the most cautious type present
        order = ['A', 'C', 'B', 'G', 'R', 'H']
        types = [m['type'] for m in members]
        primary['type'] = sorted(types, key=lambda t: order.index(t))[0]
        # and the union of route projections, nearest per route
        byroute = {}
        for m in members:
            for o in m['on']:
                if o['route'] not in byroute or o['offM'] < byroute[o['route']]['offM']:
                    byroute[o['route']] = o
        primary['on'] = sorted(byroute.values(), key=lambda o: o['offM'])
    merged.append(primary)

print('merged %d duplicate records: %d -> %d' % (merge_count, len(recs), len(merged)))

# ---- 2. elevation ---------------------------------------------------------
fixed = 0
for r in merged:
    if r['eleSource'] == 'osm' and r['eleDem'] is not None:
        if abs(r['ele'] - r['eleDem']) > 50:
            r['eleWas'] = r['ele']
            r['ele'] = r['eleDem']
            r['eleSource'] = 'dem (osm tag disagreed by %+d m)' % (r['eleWas'] - r['eleDem'])
            fixed += 1
print('elevations taken from the DEM because the OSM tag was implausible: %d' % fixed)

# ---- 3. labels ------------------------------------------------------------
unnamed = 0
for r in merged:
    if not r['name']:
        unnamed += 1
        # No route reference in the label: a shelter can serve several routes,
        # and naming one of them means a stop on the HRP can read "GR10 km 10".
        # The planner shows km on the route actually being planned.
        r['name'] = None
        r['label'] = 'Unnamed %s%s' % (
            TYPE_WORD.get(r['type'], 'shelter'),
            (' · %d m' % r['ele']) if r['ele'] else '')
    else:
        r['label'] = r['name']
print('descriptive labels generated for unnamed records: %d' % unnamed)

# ---- 4. write -------------------------------------------------------------
for r in merged:
    r.pop('eleDem', None)
merged.sort(key=lambda r: (r['on'][0]['route'], r['on'][0]['km']))
doc = {
    'count': len(merged),
    'source': {'provider': 'OpenStreetMap', 'licence': 'ODbL 1.0',
               'attribution': '© OpenStreetMap contributors',
               'fetched': '2026-09-28',
               'elevation': 'AWS Terrain Tiles z12, used where the OSM ele tag '
                            'is absent or disagrees by more than 50 m',
               'maxOffRouteKm': 2.5},
    'types': {'R': 'staffed refuge', 'C': 'unattended hut', 'A': 'bare shelter',
              'G': 'gîte d\'étape / albergue', 'B': 'campsite',
              'H': 'hotel / guesthouse'},
    'shelters': merged
}
out = os.path.join(ROOT, 'data', 'shelters.json')
# ensure_ascii=False needs an explicitly UTF-8 handle; the default handle
# writes cp1252 on Windows and the file stops being valid UTF-8 JSON
json.dump(doc, open(out, 'w', encoding='utf-8'), separators=(',', ':'),
          ensure_ascii=False)
print('\nwrote %s  %.2f MB' % (out, os.path.getsize(out)/1048576))
print('by type      : %s' % dict(Counter(r['type'] for r in merged)))
print('by confidence: %s' % dict(Counter(r['confidence'] for r in merged)))
print('named        : %d of %d' % (sum(1 for r in merged if r['name']), len(merged)))

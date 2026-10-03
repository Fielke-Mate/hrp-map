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
import json, math, os, sys
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


# The tag keys that existed before status evidence was kept. Evidence keys
# (note, description, historic, lifecycle prefixes) were added to the record
# so a status can be re-examined; counting them here changed which duplicate
# won a merge, and so silently changed the id, name and position of huts that
# had nothing to do with the status work.
SCORED_TAGS = {'tourism', 'amenity', 'shelter_type', 'building', 'ele', 'capacity',
               'operator', 'access', 'fee', 'seasonal', 'opening_hours',
               'ref:refuges.info'}


def score(r):
    """how much this record is worth keeping as the primary of a merged pair"""
    s = 0
    if r['name']:
        s += 100
    s += RICHNESS.get(r['confidence'], 0) * 10
    s += sum(1 for k in r['tags'] if k in SCORED_TAGS)
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
STATUS_RANK = {'gone': 3, 'closed': 2, 'private': 1, 'ok': 0}
superseded = 0
for _, idxs in groups.items():
    members = [recs[i] for i in idxs]
    # A demolished hut next to a working one is usually its predecessor - the
    # old refuge knocked down and a new one built beside it. Letting the dead
    # record's status win the merge would refuse the hut that is actually
    # there, so it leaves the group and is remembered as what it was.
    live = [m for m in members if m.get('status') != 'gone']
    dead = [m for m in members if m.get('status') == 'gone']
    if live and dead:
        superseded += len(dead)
        members = live
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
        # closed or private on any record of the same building wins
        worst = max(members, key=lambda m: STATUS_RANK.get(m.get('status', 'ok'), 0))
        primary['status'] = worst.get('status', 'ok')
        primary['statusWhy'] = sorted({w for m in members for w in m.get('statusWhy', [])})
        primary['reviewNotes'] = sorted({w for m in members for w in m.get('reviewNotes', [])})
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
    if live and dead:
        primary['supersedes'] = [{'id': m['id'], 'name': m.get('name'),
                                  'why': m.get('statusWhy', [])} for m in dead]
    merged.append(primary)

print('merged %d duplicate records: %d -> %d' % (merge_count, len(recs), len(merged)))
print('demolished/ruined predecessors folded into a live neighbour: %d' % superseded)

# ---- 1b. human review of free-text warnings -------------------------------
# A nomination with no decision stops the build. Shipping it unreviewed would
# mean either trusting a keyword match (wrong half the time) or ignoring a
# note that says a refuge closed for good - both unacceptable for data that
# hikers will plan nights around.
review = json.load(open(os.path.join(HERE, 'status_review.json'), encoding='utf-8'))
decisions = review['decisions']
used, unreviewed = set(), []
for r in merged:
    ids = [r['id']] + list(r.get('mergedFrom', []))
    key = next((i for i in ids if i in decisions), None)
    if key:
        d = decisions[key]
        used.add(key)
        r['status'] = d['status']
        r['statusWhy'] = ['reviewed %s: %s' % (review['reviewed'], d['reason'])] + \
                         [w for w in r.get('statusWhy', []) if not w.startswith('reviewed')]
        if d.get('caveat'):
            r['caveat'] = d['caveat']
    elif r.get('reviewNotes'):
        unreviewed.append(r)
    r.pop('reviewNotes', None)
stale = sorted(set(decisions) - used)
if stale:
    print('WARNING: %d review decisions match no record (renamed or deleted in OSM?): %s'
          % (len(stale), ', '.join(stale)))
if unreviewed:
    print('\nREFUSING TO WRITE: %d huts carry a free-text warning nobody has reviewed.'
          % len(unreviewed))
    for r in unreviewed:
        print('  %-20s %s' % (r['id'], r.get('name') or '(unnamed)'))
    print('Read each description and add a decision to src/data/status_review.json.')
    sys.exit(1)
print('free-text warnings reviewed: %d decisions applied' % len(used))

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
print('by status    : %s' % dict(Counter(r.get('status', 'ok') for r in merged)))
print('named        : %d of %d' % (sum(1 for r in merged if r['name']), len(merged)))

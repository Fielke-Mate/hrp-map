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
import json, math, os, re, sys
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
        # A decision may also correct the TYPE, when independent hut databases
        # contradict the classification - kept with the old value and reason.
        if d.get('type') and d['type'] != r['type']:
            r['typeWas'] = r['type']
            r['type'] = d['type']
            r['basis'] = list(r.get('basis', [])) + ['reviewed %s: %s' % (review['reviewed'], d['reason'])]
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


# ---- 3b. links: where a hiker can check, call or book --------------------
# Where you sleep is the decision a plan rests on, so every hut carries the
# ways to check it before relying on it. OSM is always there as the source;
# the rest only if it exists - and the hut-database pages only once
# verify_links.py has confirmed they describe THIS hut (a wrong reference
# number would open another hut's page, which is worse than no link). A
# website whose domain has lapsed or whose page is gone is not linked; the
# hiker is told instead, since a lapsed domain can mean the place has closed.
#
# Pipeline order on fresh data: build -> finalise -> verify_links -> finalise.
RAW = json.load(open(os.path.join(CACHE, 'all_features.json')))
VF = os.path.join(HERE, '.links', 'verified.json')
VER = json.load(open(VF, encoding='utf-8')) if os.path.exists(VF) else {'links': {}, 'checked': None}
PHONE_KEYS = ('phone', 'contact:phone', 'mobile', 'contact:mobile', 'phone:mobile')
EMAIL_RE = re.compile(r'^[^@\s;]+@[^@\s;]+\.[a-z]{2,}$', re.I)


def raw_tags(r):
    t = {}
    for i in [r['id']] + list(r.get('mergedFrom', [])):
        for k, v in (RAW.get(i, {}).get('tags') or {}).items():
            t.setdefault(k, v)
    return t


unverified = 0
for r in merged:
    t, v = raw_tags(r), VER['links'].get(r['id'], {})
    L = {'osm': 'https://www.openstreetmap.org/' + r['id']}
    phones, seen = [], set()
    for k in PHONE_KEYS:
        for p in re.split(r'[;,]', str(t.get(k) or '')):
            p = ' '.join(p.split())
            digits = re.sub(r'[^\d+]', '', p)
            if len(digits.lstrip('+')) >= 8 and digits not in seen:
                seen.add(digits)
                phones.append(p)
    if phones:
        L['phone'] = phones
    em = str(t.get('email') or t.get('contact:email') or '').split(';')[0].strip()
    if EMAIL_RE.match(em):
        L['email'] = em
    if t.get('reservation') in ('required', 'recommended', 'yes', 'no'):
        L['reservation'] = t['reservation']
    if v.get('website') and not v.get('website_note'):
        L['website'] = v['website']
    for src_key, dst in (('website_note', 'websiteNote'), ('refuges_info', 'refugesInfo'),
                         ('refuges_info_note', 'refugesInfoNote'),
                         ('pyrenees_refuges', 'pyreneesRefuges'),
                         ('pyrenees_refuges_note', 'pyreneesRefugesNote')):
        if v.get(src_key):
            L[dst] = v[src_key]
    if ((t.get('ref:refuges.info') and 'refuges_info' not in v)
            or (t.get('ref:FR:pyrenees_refuges') and 'pyrenees_refuges' not in v)
            or ((t.get('website') or t.get('contact:website')) and 'website' not in v)):
        unverified += 1
    r['links'] = L
if unverified:
    print('WARNING: %d huts have references or websites not yet checked - run '
          'src/data/verify_links.py, then this script again' % unverified)

# ---- 4. write -------------------------------------------------------------
for r in merged:
    r.pop('eleDem', None)
merged.sort(key=lambda r: (r['on'][0]['route'], r['on'][0]['km']))
doc = {
    'count': len(merged),
    'source': {'provider': 'OpenStreetMap', 'licence': 'ODbL 1.0',
               'attribution': '© OpenStreetMap contributors',
               'fetched': '2026-09-28',
               # shown to the hiker beside the data, so they know how old the
               # hut statuses are when planning offline
               'reviewed': review['reviewed'],
               'linksChecked': VER.get('checked'),
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
direct = lambda r: any(k in r['links'] for k in ('phone', 'website', 'email'))
hutdb = lambda r: any(k in r['links'] for k in ('refugesInfo', 'pyreneesRefuges'))
print('links        : phone %d, website %d, email %d, hut database %d, OSM only %d'
      % (sum('phone' in r['links'] for r in merged), sum('website' in r['links'] for r in merged),
         sum('email' in r['links'] for r in merged), sum(hutdb(r) for r in merged),
         sum(not direct(r) and not hutdb(r) for r in merged)))
for typ in 'RGCAB':
    rs = [r for r in merged if r['type'] == typ]
    print('   %s %4d huts: %3d%% can be called, written to or looked up; %3d%% OSM only'
          % (typ, len(rs), 100 * sum(direct(r) or hutdb(r) for r in rs) / max(1, len(rs)),
             100 * sum(not direct(r) and not hutdb(r) for r in rs) / max(1, len(rs))))

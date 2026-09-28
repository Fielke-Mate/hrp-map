"""Verify the projected accommodation set, and measure coverage per route.

Coverage is the question that decides which types the planner may rely on: if
excluding gites leaves a 40 km stretch of GR10 with nowhere to sleep, that is
not a filter, it is a broken route.
"""
import json, math, os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(HERE, '.shelters')
recs = json.load(open(os.path.join(CACHE, 'projected.json')))
routes = {rid: json.load(open(os.path.join(ROOT, 'data', 'routes', rid + '.json')))['lengthKm']
          for rid in ('gr10', 'gr11', 'hrp')}


def gc(a, b):
    dlat = (b[0]-a[0])*111.0
    dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
    return math.sqrt(dlat*dlat + dlon*dlon)


print('=' * 76)
print('VERIFICATION')
issues = Counter()

# 1. identity
noid = [r for r in recs if not r['id'] or '/' not in r['id']]
print('1. every record has a resolvable OSM id      : %s' % ('PASS' if not noid else 'FAIL %d' % len(noid)))

# 2. unnamed
unnamed = [r for r in recs if not r['name']]
print('2. unnamed features                          : %d (%.0f%%)'
      % (len(unnamed), 100*len(unnamed)/len(recs)))
print('     by type: %s' % dict(Counter(r['type'] for r in unnamed)))

# 3. duplicates by proximity
CELL = 0.005
g = defaultdict(list)
for i, r in enumerate(recs):
    g[(int(r['ll'][0]/CELL), int(r['ll'][1]/CELL))].append(i)
dups = []
seen = set()
for i, r in enumerate(recs):
    c = (int(r['ll'][0]/CELL), int(r['ll'][1]/CELL))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for j in g.get((c[0]+dx, c[1]+dy), ()):
                if j <= i:
                    continue
                d = gc(r['ll'], recs[j]['ll'])
                if d < 0.03 and (i, j) not in seen:
                    seen.add((i, j))
                    dups.append((round(d*1000), r['name'], r['type'], recs[j]['name'], recs[j]['type']))
print('3. pairs within 30 m of each other           : %d' % len(dups))
for d, n1, t1, n2, t2 in sorted(dups, key=lambda x: x[0])[:8]:
    print('     %3d m  %-28s [%s]  <->  %-28s [%s]'
          % (d, str(n1)[:28], t1, str(n2)[:28], t2))

# 4. elevation: OSM tag vs DEM
both = [r for r in recs if r['eleSource'] == 'osm' and r['eleDem'] is not None]
bad = [r for r in both if abs(r['ele'] - r['eleDem']) > 50]
print('4. elevation, OSM tag vs DEM (%d comparable)  : %d differ by >50 m'
      % (len(both), len(bad)))
for r in sorted(bad, key=lambda r: -abs(r['ele']-r['eleDem']))[:6]:
    print('     %-34s osm %5d  dem %5d  (%+d)'
          % (str(r['name'])[:34], r['ele'], r['eleDem'], r['ele']-r['eleDem']))
noele = [r for r in recs if r['ele'] is None]
print('     records with no elevation at all: %d' % len(noele))

# 5. confidence
print('5. classification confidence                 : %s'
      % dict(Counter(r['confidence'] for r in recs)))
low = [r for r in recs if r['confidence'] == 'low']
print('     low-confidence by type: %s' % dict(Counter(r['type'] for r in low)))

# 6. multi-route
multi = [r for r in recs if len(r['on']) > 1]
print('6. serving more than one route               : %d' % len(multi))
for r in multi[:4]:
    print('     %-32s %s' % (str(r['name'])[:32],
          ', '.join('%s@%.1fkm(%dm off)' % (o['route'], o['km'], o['offM']) for o in r['on'])))

# ---- coverage -------------------------------------------------------------
print('\n' + '=' * 76)
print('COVERAGE - longest stretch with nowhere to sleep')
print('(off-route limit 2.5 km; a 20 km day needs gaps under 20 km)')
SETS = [('R only', {'R'}), ('R+C', {'R', 'C'}), ('R+C+A', {'R', 'C', 'A'}),
        ('R+C+A+G', {'R', 'C', 'A', 'G'}), ('R+C+A+G+B', {'R', 'C', 'A', 'G', 'B'}),
        ('everything incl. H', {'R', 'C', 'A', 'G', 'B', 'H'})]
print('\n%-20s %10s %10s %10s' % ('types allowed', 'GR10', 'GR11', 'HRP'))
for label, allow in SETS:
    row = []
    for rid, length in routes.items():
        kms = sorted(o['km'] for r in recs if r['type'] in allow
                     for o in r['on'] if o['route'] == rid)
        if not kms:
            row.append('none'); continue
        marks = [0.0] + kms + [length]
        worst = max(b - a for a, b in zip(marks, marks[1:]))
        row.append('%.1f km' % worst)
    print('%-20s %10s %10s %10s' % (label, row[0], row[1], row[2]))

print('\ncount of options per route')
print('%-20s %10s %10s %10s' % ('types allowed', 'GR10', 'GR11', 'HRP'))
for label, allow in SETS:
    row = []
    for rid in routes:
        row.append(sum(1 for r in recs if r['type'] in allow
                       for o in r['on'] if o['route'] == rid))
    print('%-20s %10d %10d %10d' % (label, row[0], row[1], row[2]))

# how many stretches would break a 20 km day, per set
print('\nstretches over 20 km (a hard day) with nothing in them')
print('%-20s %10s %10s %10s' % ('types allowed', 'GR10', 'GR11', 'HRP'))
for label, allow in SETS:
    row = []
    for rid, length in routes.items():
        kms = sorted(o['km'] for r in recs if r['type'] in allow
                     for o in r['on'] if o['route'] == rid)
        marks = [0.0] + kms + [length]
        row.append(sum(1 for a, b in zip(marks, marks[1:]) if b - a > 20))
    print('%-20s %10d %10d %10d' % (label, row[0], row[1], row[2]))

"""Fetch every accommodation feature near the three routes, with raw tags.

Hikers rely on these, so the rule is: nothing enters the dataset without a
resolvable OSM id, and every classification decision stays auditable by
keeping the source tags alongside it. An earlier hand-built list of 58 had 28
coordinates typed in by hand, three of which pointed at open hillside - that
is not repeatable at range scale.

Fetched in longitude slices to stay inside Overpass timeouts, and cached, so a
re-run costs nothing.
"""
import json, math, os, sys, time, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.shelters')
os.makedirs(CACHE, exist_ok=True)
ROUTES = os.path.join(os.path.dirname(os.path.dirname(HERE)), 'data', 'routes')

# every plausible place a walker could sleep; classification happens later and
# is kept separate from collection on purpose
TAGS = [
    'nwr["tourism"~"^(alpine_hut|wilderness_hut|chalet|hostel|guest_house|camp_site|hotel|motel|apartment)$"]',
    'nwr["amenity"="shelter"]',
    'nwr["building"~"^(cabin|hut)$"]',
    'nwr["shelter_type"]',
]

LAT0, LAT1 = 42.0, 43.7
SLICES = [(-2.3, -1.0), (-1.0, 0.0), (0.0, 0.7), (0.7, 1.5), (1.5, 2.3), (2.3, 3.5)]


def ovp(q):
    eps = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
    delay = 30
    for attempt in range(4):
        for ep in eps:
            try:
                req = urllib.request.Request(
                    ep, data=('data=' + urllib.parse.quote(q)).encode(),
                    headers={'Content-Type': 'application/x-www-form-urlencoded',
                             'User-Agent': 'HRP-Planner-build/1.0 (route planning, personal)'})
                return json.load(urllib.request.urlopen(req, timeout=300))
            except Exception as e:
                print('     %s: %s' % (ep.split('/')[2], str(e)[:60])); sys.stdout.flush()
                time.sleep(delay)
                delay = min(delay * 2, 240)
    return None


all_feats = {}
for lo0, lo1 in SLICES:
    path = os.path.join(CACHE, 'slice_%s_%s.json' % (lo0, lo1))
    if os.path.exists(path):
        els = json.load(open(path))
        print('slice %6.1f..%-5.1f cached  %d features' % (lo0, lo1, len(els)))
    else:
        bbox = '%f,%f,%f,%f' % (LAT0, lo0, LAT1, lo1)
        q = ('[out:json][timeout:300];(' +
             ''.join(t + '(' + bbox + ');' for t in TAGS) +
             ');out tags center;')
        print('slice %6.1f..%-5.1f fetching...' % (lo0, lo1)); sys.stdout.flush()
        d = ovp(q)
        if not d:
            print('  FAILED - rerun to resume'); sys.exit(1)
        els = d['elements']
        json.dump(els, open(path, 'w'))
        print('  %d features' % len(els))
        time.sleep(8)
    for e in els:
        all_feats['%s/%s' % (e['type'], e['id'])] = e

print('\nunique features across the range: %d' % len(all_feats))
json.dump(all_feats, open(os.path.join(CACHE, 'all_features.json'), 'w'))

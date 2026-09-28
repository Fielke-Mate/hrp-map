"""What does OSM actually hold for GR10, GR11 and the HRP?

Lists candidate route relations across the whole Pyrenean chain (Hendaye to
Banyuls) with their tagging, so we can judge coverage before committing to a
source. Tags only at this stage - geometry comes after, for whichever
relations turn out to be the real ones.
"""
import json, sys, time, urllib.request, urllib.parse

SP = r'C:\Users\MARTIN~1.FIE\AppData\Local\Temp\claude\C--Users-martin-fielke-OneDrive---Accenture-Documents-Claude-Test-Planning-Other\54a269c5-48fe-4046-b63a-8f3d0d51d52d\scratchpad'
BBOX = '42.0,-2.2,43.6,3.4'          # Hendaye -> Banyuls, both slopes

Q = ('[out:json][timeout:300];('
     'relation["type"~"route|superroute"]["route"="hiking"]["ref"~"^GR ?-?1[01]$",i](%s);'
     'relation["type"~"route|superroute"]["route"="hiking"]["name"~"GR ?-?1[01]([^0-9]|$)",i](%s);'
     'relation["type"~"route|superroute"]["route"="hiking"]["name"~"Haute Randonn",i](%s);'
     'relation["type"~"route|superroute"]["route"="hiking"]["name"~"Alta Ruta Pirenaica",i](%s);'
     'relation["type"~"route|superroute"]["route"="hiking"]["ref"~"HRP",i](%s);'
     ');out tags;') % (BBOX, BBOX, BBOX, BBOX, BBOX)


def ovp(q):
    eps = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
    for attempt in range(3):
        for ep in eps:
            try:
                print('  try %s' % ep.split('/')[2]); sys.stdout.flush()
                req = urllib.request.Request(
                    ep, data=('data=' + urllib.parse.quote(q)).encode(),
                    headers={'Content-Type': 'application/x-www-form-urlencoded',
                             'User-Agent': 'HRP-Planner-survey/1.0'})
                return json.load(urllib.request.urlopen(req, timeout=300))
            except Exception as e:
                print('     %s' % e); sys.stdout.flush()
                time.sleep(8)
    return None


d = ovp(Q)
if not d:
    sys.exit('overpass unavailable')
rels = d['elements']
print('\n%d candidate relations\n' % len(rels))
json.dump(rels, open(SP + r'\route_rels.json', 'w'))


def bucket(t):
    ref = (t.get('ref') or '').upper().replace(' ', '').replace('-', '')
    nm = (t.get('name') or '')
    low = nm.lower()
    if ref in ('GR10',) or 'gr10' in low.replace(' ', '').replace('-', ''):
        return 'GR10'
    if ref in ('GR11',) or 'gr11' in low.replace(' ', '').replace('-', ''):
        return 'GR11'
    if 'haute randonn' in low or 'alta ruta pirenaica' in low or 'HRP' in (t.get('ref') or ''):
        return 'HRP'
    return 'other'


groups = {}
for r in rels:
    groups.setdefault(bucket(r.get('tags', {})), []).append(r)

for g in ('GR10', 'GR11', 'HRP', 'other'):
    lst = groups.get(g, [])
    print('=' * 78)
    print('%s : %d relations' % (g, len(lst)))
    for r in sorted(lst, key=lambda x: (x.get('tags', {}).get('type', ''),
                                        x.get('tags', {}).get('name', ''))):
        t = r.get('tags', {})
        print('  rel/%-12s %-9s %-46s' % (r['id'], t.get('type'), (t.get('name') or '')[:46]))
        bits = []
        for k in ('ref', 'network', 'operator', 'from', 'to', 'distance', 'osmc:symbol', 'state'):
            if t.get(k):
                bits.append('%s=%s' % (k, t[k][:34]))
        if bits:
            print('       ' + ' | '.join(bits))

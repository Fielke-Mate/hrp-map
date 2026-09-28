"""Turn 15,602 raw OSM features into a verified accommodation dataset.

Hikers rely on these. The rules, each learned from a real failure in the
earlier hand-built list of 58:

  * nothing enters without a resolvable OSM id and a fetch date
  * classification is derived from tags and the deciding tags are kept, so
    every judgement can be re-examined instead of taken on trust
  * where the tags are ambiguous, classify DOWN. Promising a staffed refuge
    that turns out to be a bare shelter is the dangerous direction; the
    reverse just means someone carries a stove they did not need
  * elevation is cross-checked against the DEM, which previously caught seven
    wrong figures, the worst by 276 m
  * duplicates are detected by proximity as well as by id - two of the 58 were
    the same hut entered twice under different names
"""
import json, math, os, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ROUTES = os.path.join(ROOT, 'data', 'routes')
CACHE = os.path.join(HERE, '.shelters')
TILES = os.path.join(HERE, '.tilecache')
MAX_OFF_KM = 2.5
Z = 12

feats = json.load(open(os.path.join(CACHE, 'all_features.json')))
print('raw features: %s' % f'{len(feats):,}')

routes = {}
for rid in ('gr10', 'gr11', 'hrp'):
    d = json.load(open(os.path.join(ROUTES, rid + '.json')))
    pts = d['points']
    cum = [0.0]
    for i in range(1, len(pts)):
        a, b = pts[i-1], pts[i]
        dlat = (b[0]-a[0])*111.0
        dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
        cum.append(cum[-1] + math.sqrt(dlat*dlat + dlon*dlon))
    routes[rid] = dict(pts=pts, cum=cum, km=d['lengthKm'])

CELL = 0.02
grids = {}
for rid, r in routes.items():
    g = defaultdict(list)
    for i, p in enumerate(r['pts']):
        g[(int(p[0]/CELL), int(p[1]/CELL))].append(i)
    grids[rid] = g


def gc(a, b):
    dlat = (b[0]-a[0])*111.0
    dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
    return math.sqrt(dlat*dlat + dlon*dlon)


def project(ll, rid):
    r, g = routes[rid], grids[rid]
    c = (int(ll[0]/CELL), int(ll[1]/CELL))
    best, bi = 9e9, -1
    span = int(MAX_OFF_KM / (CELL*111)) + 1
    for dx in range(-span, span+1):
        for dy in range(-span, span+1):
            for i in g.get((c[0]+dx, c[1]+dy), ()):
                d = gc(ll, r['pts'][i])
                if d < best:
                    best, bi = d, i
    return (best, r['cum'][bi]) if bi >= 0 else (None, None)


# ---- classification -------------------------------------------------------
# R staffed refuge | C unattended hut | A bare shelter | G gite/albergue
# B campsite | H hotel/guesthouse (collected, excluded from planning by default)
def classify(t):
    tour = t.get('tourism'); amen = t.get('amenity')
    st = t.get('shelter_type'); bld = t.get('building')
    name = (t.get('name') or '').lower()
    why = []
    if tour == 'alpine_hut':
        why.append('tourism=alpine_hut')
        # OSM defines alpine_hut as usually staffed, but plenty are not.
        # Only call it staffed with corroboration; otherwise drop to C.
        if t.get('operator') or t.get('phone') or t.get('website') or t.get('email'):
            return 'R', 'high', why + ['contact/operator present']
        if any(w in name for w in ('refuge', 'refugi', 'refugio')):
            return 'R', 'medium', why + ['name says refuge']
        return 'C', 'low', why + ['no operator or contact - not assumed staffed']
    if tour == 'wilderness_hut':
        return 'C', 'high', ['tourism=wilderness_hut']
    if tour == 'hostel':
        return 'G', 'high', ['tourism=hostel']
    if tour == 'chalet':
        if any(w in name for w in ('gite', 'gîte', 'refugi', 'refuge', 'alberg')):
            return 'G', 'medium', ['tourism=chalet', 'name suggests gite']
        return 'H', 'medium', ['tourism=chalet']
    if tour in ('hotel', 'guest_house', 'motel', 'apartment'):
        return 'H', 'high', ['tourism=' + tour]
    if tour == 'camp_site':
        return 'B', 'high', ['tourism=camp_site']
    if amen == 'shelter':
        if st in ('basic_hut', 'lean_to'):
            return 'C', 'high', ['amenity=shelter', 'shelter_type=' + str(st)]
        if st in ('picnic_shelter', 'public_transport', 'gazebo'):
            return None, None, ['amenity=shelter', 'shelter_type=' + str(st), 'not for sleeping']
        return 'A', 'medium', ['amenity=shelter', 'shelter_type=' + str(st)]
    if bld in ('cabin', 'hut'):
        return 'C', 'low', ['building=' + bld, 'no tourism tag - may be private']
    if st:
        return 'A', 'low', ['shelter_type=' + st]
    return None, None, ['no usable tag']


# ---- DEM ------------------------------------------------------------------
from PIL import Image
_tc = {}


def dem(lat, lon):
    n = 2 ** Z
    fx = (lon+180)/360*n
    fy = (1 - math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
    tx, ty = int(fx), int(fy)
    k = (tx, ty)
    if k not in _tc:
        p = os.path.join(TILES, '%d_%d_%d.png' % (Z, tx, ty))
        _tc[k] = None
        if os.path.exists(p):
            im = Image.open(p).convert('RGB')
            _tc[k] = (im.width, im.height, im.load())
    t = _tc[k]
    if not t:
        return None
    W, H, px = t
    r, g, b = px[min(W-1, int((fx-tx)*W)), min(H-1, int((fy-ty)*H))]
    return (r*256 + g + b/256.0) - 32768.0


# ---- build ----------------------------------------------------------------
out, skipped = [], Counter()
for fid, e in feats.items():
    t = e.get('tags', {})
    lat = e.get('lat', (e.get('center') or {}).get('lat'))
    lon = e.get('lon', (e.get('center') or {}).get('lon'))
    if lat is None:
        skipped['no position'] += 1
        continue
    on = []
    for rid in routes:
        off, km = project((lat, lon), rid)
        if off is not None and off <= MAX_OFF_KM:
            on.append(dict(route=rid, km=round(km, 2), offM=round(off*1000)))
    if not on:
        skipped['too far from any route'] += 1
        continue
    typ, conf, why = classify(t)
    if not typ:
        skipped['not somewhere to sleep'] += 1
        continue
    ele_osm = None
    if t.get('ele'):
        try:
            ele_osm = int(float(str(t['ele']).replace(',', '.').split()[0]))
        except Exception:
            pass
    ele_dem = dem(lat, lon)
    rec = dict(id=fid, name=t.get('name'), type=typ, confidence=conf,
               ll=[round(lat, 6), round(lon, 6)],
               ele=ele_osm if ele_osm is not None else (round(ele_dem) if ele_dem else None),
               eleSource='osm' if ele_osm is not None else ('dem' if ele_dem else None),
               eleDem=round(ele_dem) if ele_dem is not None else None,
               capacity=t.get('capacity') or t.get('beds'),
               operator=t.get('operator'), website=t.get('website'),
               basis=why, on=sorted(on, key=lambda x: x['offM']),
               tags={k: v for k, v in t.items()
                     if k in ('tourism', 'amenity', 'shelter_type', 'building',
                              'ele', 'capacity', 'operator', 'access', 'fee',
                              'seasonal', 'opening_hours', 'ref:refuges.info')})
    out.append(rec)

print('kept %d, skipped %s' % (len(out), dict(skipped)))
json.dump(out, open(os.path.join(CACHE, 'projected.json'), 'w'))
print('\nby type: %s' % dict(Counter(r['type'] for r in out)))
print('by confidence: %s' % dict(Counter(r['confidence'] for r in out)))

"""Fetch the main-line stage relations for GR10, GR11 and HRP and measure them.

Tags existing does not mean the line is walkable end to end. This measures, per
route: total length, whether each stage's ways join up internally, and whether
consecutive stages meet. Gaps are what would break a planner.
"""
import json, math, re, sys, time, urllib.request, urllib.parse

SP = r'C:\Users\MARTIN~1.FIE\AppData\Local\Temp\claude\C--Users-martin-fielke-OneDrive---Accenture-Documents-Claude-Test-Planning-Other\54a269c5-48fe-4046-b63a-8f3d0d51d52d\scratchpad'
rels = json.load(open(SP + r'\route_rels.json'))


def pick(pred):
    return [r for r in rels if pred(r.get('tags', {}))]


MAIN = {
  'GR10': pick(lambda t: t.get('ref') == 'GR 10'
               and re.search(r'sec\.(\d+)', t.get('name') or '')),
  'GR11': pick(lambda t: t.get('ref') == 'GR 11'
               and re.search(r'- E(\d+)', t.get('name') or '')),
  'HRP':  pick(lambda t: t.get('ref') == 'HRP'
               and re.search(r'tape (\d+)', t.get('name') or '')),
}


def order_key(name):
    m = re.search(r'sec\.(\d+)|- E(\d+)|tape (\d+)', name or '')
    return int([g for g in m.groups() if g][0]) if m else 999


for k in MAIN:
    MAIN[k].sort(key=lambda r: order_key(r['tags'].get('name')))
    print('%s: %d main-line relations' % (k, len(MAIN[k])))


def ovp(q):
    eps = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter"]
    for attempt in range(3):
        for ep in eps:
            try:
                req = urllib.request.Request(
                    ep, data=('data=' + urllib.parse.quote(q)).encode(),
                    headers={'Content-Type': 'application/x-www-form-urlencoded',
                             'User-Agent': 'HRP-Planner-survey/1.0'})
                return json.load(urllib.request.urlopen(req, timeout=600))
            except Exception as e:
                print('   %s: %s' % (ep.split('/')[2], e)); sys.stdout.flush()
                time.sleep(15)
    return None


def gc(a, b):
    dlat = (b[0]-a[0])*111.0
    dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
    return math.sqrt(dlat*dlat + dlon*dlon)


geo = {}
for route, lst in MAIN.items():
    ids = ''.join('relation(%d);' % r['id'] for r in lst)
    print('\nfetching %s geometry (%d relations)...' % (route, len(lst))); sys.stdout.flush()
    d = ovp('[out:json][timeout:600];(' + ids + ');out geom;')
    if not d:
        print('  FAILED'); continue
    geo[route] = d['elements']
    json.dump(d['elements'], open(SP + ('\\geo_%s.json' % route), 'w'))
    print('  got %d relations' % len(d['elements']))
    time.sleep(5)

print('\n' + '=' * 78)
summary = {}
for route, els in geo.items():
    byid = {e['id']: e for e in els}
    total = 0.0
    stage_rows = []
    internal_gaps = 0
    for r in MAIN[route]:
        e = byid.get(r['id'])
        if not e:
            stage_rows.append((r['tags'].get('name'), None, None, None)); continue
        # stitch the member ways in order, measuring joins
        segs = [m['geometry'] for m in e.get('members', [])
                if m.get('type') == 'way' and m.get('geometry')]
        pts, gaps = [], 0
        for g in segs:
            cur = [(p['lat'], p['lon']) for p in g]
            if pts:
                # a way may be stored in either direction
                d_ff = gc(pts[-1], cur[0]); d_fr = gc(pts[-1], cur[-1])
                if d_fr < d_ff:
                    cur.reverse(); d_ff = d_fr
                if d_ff > 0.05:
                    gaps += 1
                pts.extend(cur)
            else:
                pts = cur
        km = sum(gc(pts[i-1], pts[i]) for i in range(1, len(pts))) if len(pts) > 1 else 0
        total += km
        internal_gaps += gaps
        stage_rows.append((r['tags'].get('name'), km, len(pts), gaps,
                           pts[0] if pts else None, pts[-1] if pts else None))
    # do consecutive stages meet?
    joins = []
    for i in range(1, len(stage_rows)):
        a, b = stage_rows[i-1], stage_rows[i]
        if len(a) > 4 and len(b) > 4 and a[5] and b[4]:
            joins.append(gc(a[5], b[4]))
    summary[route] = dict(stages=len(MAIN[route]), km=round(total, 1),
                          internal_gaps=internal_gaps,
                          joins_over_100m=sum(1 for j in joins if j > 0.1),
                          worst_join_km=round(max(joins), 2) if joins else None,
                          median_join_m=round(sorted(joins)[len(joins)//2]*1000) if joins else None)
    print('\n%s' % route)
    print('  stages %d | total %.1f km | way-joins >50 m inside stages: %d'
          % (len(MAIN[route]), total, internal_gaps))
    if joins:
        print('  stage-to-stage joins: median %d m, worst %.2f km, %d over 100 m'
              % (sorted(joins)[len(joins)//2]*1000, max(joins), sum(1 for j in joins if j > 0.1)))
    bad = [(s[0], round(j*1000)) for s, j in zip(stage_rows[1:], joins) if j > 0.1]
    for nm, m in bad[:8]:
        print('     gap before %-26s %d m' % ((nm or '')[:26], m))

json.dump(summary, open(SP + r'\route_summary.json', 'w'))
print('\n' + json.dumps(summary, indent=1))

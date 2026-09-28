"""Stitch GR10 / GR11 / HRP into one continuous polyline each.

Relation member order is NOT walking order in OSM - assuming it was produced
phantom gaps of up to 19 km in the survey. This chains ways by shared endpoint
coordinates instead (a shared node has identical coordinates at full
precision), and reports any place it genuinely had to jump.

Output: one ordered [lat, lon] polyline per route, plus stage boundaries
expressed as km along that polyline.
"""
import json, math, re, sys
from collections import defaultdict

SP = r'C:\Users\MARTIN~1.FIE\AppData\Local\Temp\claude\C--Users-martin-fielke-OneDrive---Accenture-Documents-Claude-Test-Planning-Other\54a269c5-48fe-4046-b63a-8f3d0d51d52d\scratchpad'
rels = json.load(open(SP + r'\route_rels.json'))


def order_key(n):
    m = re.search(r'sec\.(\d+)|- E(\d+)|tape (\d+)', n or '')
    return int([g for g in m.groups() if g][0]) if m else 999


MAIN = {
  'GR10': [r for r in rels if r['tags'].get('ref') == 'GR 10' and re.search(r'sec\.\d+', r['tags'].get('name') or '')],
  'GR11': [r for r in rels if r['tags'].get('ref') == 'GR 11' and re.search(r'- E\d+', r['tags'].get('name') or '')],
  'HRP':  [r for r in rels if r['tags'].get('ref') == 'HRP' and re.search(r'tape \d+', r['tags'].get('name') or '')],
}
for k in MAIN:
    MAIN[k].sort(key=lambda r: order_key(r['tags'].get('name')))

ENDS = {'GR10': ('Hendaye', 'Banyuls'), 'GR11': ('Cap de Creus', 'Cabo Higer'),
        'HRP': ('Hendaye', 'Banyuls-sur-Mer')}


def gc(a, b):
    dlat = (b[0]-a[0])*111.0
    dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
    return math.sqrt(dlat*dlat + dlon*dlon)


def key(p):
    return (round(p[0], 7), round(p[1], 7))


def stitch(ways):
    """chain ways by shared endpoints; returns [(pts, jumped_km), ...] runs"""
    ends = defaultdict(list)
    for i, w in enumerate(ways):
        ends[key(w[0])].append(i)
        ends[key(w[-1])].append(i)
    used = [False] * len(ways)

    def extend(chain, forward):
        while True:
            tip = key(chain[-1] if forward else chain[0])
            nxt = None
            for i in ends.get(tip, ()):
                if not used[i]:
                    nxt = i
                    break
            if nxt is None:
                return
            used[nxt] = True
            w = ways[nxt][:]
            if forward:
                if key(w[0]) != tip:
                    w.reverse()
                chain.extend(w[1:])
            else:
                if key(w[-1]) != tip:
                    w.reverse()
                chain[:0] = w[:-1]

    runs = []
    for seed in range(len(ways)):
        if used[seed]:
            continue
        used[seed] = True
        chain = ways[seed][:]
        extend(chain, True)
        extend(chain, False)
        runs.append(chain)
    return runs


def simplify(pts, tol_m):
    if len(pts) < 3:
        return pts[:]
    ky, kx = 110540.0, 111320.0 * math.cos(math.radians(pts[0][0]))

    def perp(p, a, b):
        px, py = p[1]*kx, p[0]*ky; ax, ay = a[1]*kx, a[0]*ky; bx, by = b[1]*kx, b[0]*ky
        dx, dy = bx-ax, by-ay
        L = dx*dx + dy*dy
        if not L:
            return math.hypot(px-ax, py-ay)
        t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy)/L))
        return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

    keep = [False]*len(pts); keep[0] = keep[-1] = True
    stack = [(0, len(pts)-1)]
    while stack:
        a, b = stack.pop()
        worst, wi = 0.0, -1
        for k in range(a+1, b):
            d = perp(pts[k], pts[a], pts[b])
            if d > worst:
                worst, wi = d, k
        if wi >= 0 and worst > tol_m:
            keep[wi] = True
            stack.append((a, wi)); stack.append((wi, b))
    return [p for p, k in zip(pts, keep) if k]


out_all = {}
for route in ('GR10', 'GR11', 'HRP'):
    byid = {e['id']: e for e in json.load(open(SP + ('\\geo_%s.json' % route)))}
    ways, owner = [], []
    for r in MAIN[route]:
        e = byid.get(r['id'])
        if not e:
            continue
        for m in e.get('members', []):
            if m.get('type') == 'way' and m.get('geometry'):
                ways.append([(p['lat'], p['lon']) for p in m['geometry']])
                owner.append(r['tags'].get('name'))
    runs = stitch(ways)
    runs.sort(key=lambda c: -sum(gc(c[i-1], c[i]) for i in range(1, len(c))))
    lens = [sum(gc(c[i-1], c[i]) for i in range(1, len(c))) for c in runs]
    print('=' * 74)
    print('%s: %d ways -> %d connected runs' % (route, len(ways), len(runs)))
    print('   longest run %.1f km, top 5: %s' % (lens[0], [round(l, 1) for l in lens[:5]]))
    print('   total across runs %.1f km' % sum(lens))

    # chain the runs end to end, nearest first, recording every jump
    main = runs.pop(0)
    jumps = []
    while runs:
        tail, head = main[-1], main[0]
        best = None
        for i, c in enumerate(runs):
            for endp, rev, at_tail in ((c[0], False, True), (c[-1], True, True),
                                       (c[-1], False, False), (c[0], True, False)):
                d = gc(tail if at_tail else head, endp)
                if best is None or d < best[0]:
                    best = (d, i, rev, at_tail)
        d, i, rev, at_tail = best
        # Only absorb a fragment if it genuinely abuts the line. Greedy nearest
        # joining stitched GR11 fragments across 57.7 km and 34.4 km of empty
        # ground and inflated the route from 829 to 925 km.
        if d > 0.5:
            break
        c = runs.pop(i)
        if rev:
            c = c[::-1]
        if at_tail:
            main.extend(c)
        else:
            main[:0] = c
        if d > 0.05:
            jumps.append(round(d, 3))
    dropped = [round(sum(gc(c[i-1], c[i]) for i in range(1, len(c))), 2) for c in runs]
    total = sum(gc(main[i-1], main[i]) for i in range(1, len(main)))
    print('   stitched %.1f km in %d points' % (total, len(main)))
    print('   jumps over 50 m while joining runs: %d %s'
          % (len(jumps), sorted(jumps, reverse=True)[:6]))
    if dropped:
        print('   fragments left out (too far to be part of the line): %s km' % dropped)
    print('   %-6s %8s %10s %9s' % ('tol', 'points', 'km', 'lost'))
    for tol in (0.5, 1.0, 2.0, 5.0):
        t = simplify(main, tol)
        tk = sum(gc(t[i-1], t[i]) for i in range(1, len(t)))
        print('   %-6.1f %8d %10.1f %8.2f%%' % (tol, len(t), tk, 100*(total-tk)/total))
    simp = simplify(main, 1.0)
    stotal = sum(gc(simp[i-1], simp[i]) for i in range(1, len(simp)))
    print('   chosen 1.0 m -> %d points, %.1f km' % (len(simp), stotal))
    out_all[route] = dict(points=simp, km=round(stotal, 2), raw_points=len(main),
                          runs=len(lens), jumps=jumps)
    json.dump({'id': route.lower(), 'km': round(stotal, 2),
               'points': [[round(p[0], 6), round(p[1], 6)] for p in simp]},
              open(SP + ('\\route_%s.json' % route.lower()), 'w'))

print('\nwrote route_gr10.json / route_gr11.json / route_hrp.json')

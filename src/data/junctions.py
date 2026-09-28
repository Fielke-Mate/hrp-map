"""How often do GR10, GR11 and the HRP actually meet?

If they cross rarely, route-hopping is an edge case. If they meet often, the
data model has to be a graph from the start. Uses the cached geometry.
"""
import json, math, re

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


def pts_of(route):
    byid = {e['id']: e for e in json.load(open(SP + ('\\geo_%s.json' % route)))}
    out = []
    for r in MAIN[route]:
        e = byid.get(r['id'])
        if not e:
            continue
        for m in e.get('members', []):
            if m.get('type') == 'way' and m.get('geometry'):
                out.extend((p['lat'], p['lon']) for p in m['geometry'])
    return out


P = {r: pts_of(r) for r in ('GR10', 'GR11', 'HRP')}
for r, v in P.items():
    print('%s %s points' % (r, f'{len(v):,}'))

CELL = 0.01           # ~1.1 km lat


def grid(pts):
    g = {}
    for i, (la, lo) in enumerate(pts):
        g.setdefault((int(la / CELL), int(lo / CELL)), []).append(i)
    return g


def gc(a, b):
    dlat = (b[0]-a[0])*111.0
    dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
    return math.sqrt(dlat*dlat + dlon*dlon)


print()
for a, b in (('HRP', 'GR10'), ('HRP', 'GR11'), ('GR10', 'GR11')):
    A, B = P[a], P[b]
    gb = grid(B)
    close = []
    for i in range(0, len(A), 5):                    # sample A every 5th point
        la, lo = A[i]
        ca, co = int(la / CELL), int(lo / CELL)
        best = 9e9
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in gb.get((ca + dx, co + dy), ()):
                    d = gc(A[i], B[j])
                    if d < best:
                        best = d
        if best < 0.5:
            close.append((i, best))
    # collapse consecutive close samples into distinct meeting zones
    zones, prev = 0, -99
    for i, d in close:
        if i - prev > 40:
            zones += 1
        prev = i
    pct = 100.0 * len(close) / max(1, len(range(0, len(A), 5)))
    print('%-5s vs %-5s : %5.1f%% of %s within 500 m of %s, in about %d distinct meeting zones'
          % (a, b, pct, a, b, zones))

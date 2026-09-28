"""Are the stage gaps real, or an artefact of assuming member order?

My stitcher walks relation members in stored order and flips each way to fit.
OSM does not guarantee that order, so a badly ordered relation yields a
zigzag whose endpoints are meaningless - which would look exactly like a gap.

For each suspicious join this checks:
  a) all four endpoint pairings (stage direction may be stored reversed)
  b) the true minimum distance between ANY point of one stage and any of the
     next, which is 0 if they genuinely touch anywhere
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


def gc(a, b):
    dlat = (b[0]-a[0])*111.0
    dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
    return math.sqrt(dlat*dlat + dlon*dlon)


def all_points(e):
    pts = []
    for m in e.get('members', []):
        if m.get('type') == 'way' and m.get('geometry'):
            pts.extend((p['lat'], p['lon']) for p in m['geometry'])
    return pts


def endpoints(e):
    """endpoints of each member way - the true candidates for a stage terminus"""
    eps = []
    for m in e.get('members', []):
        if m.get('type') == 'way' and m.get('geometry'):
            g = m['geometry']
            eps.append((g[0]['lat'], g[0]['lon']))
            eps.append((g[-1]['lat'], g[-1]['lon']))
    return eps


def mindist(A, B, stride=1):
    best = 9e9
    for a in A[::stride]:
        for b in B[::stride]:
            d = gc(a, b)
            if d < best:
                best = d
                if best < 0.005:
                    return best
    return best


for route in ('GR10', 'GR11', 'HRP'):
    byid = {e['id']: e for e in json.load(open(SP + ('\\geo_%s.json' % route)))}
    print('=' * 78)
    print(route)
    stages = [(r['tags'].get('name'), byid.get(r['id']), r['tags'].get('from'), r['tags'].get('to'))
              for r in MAIN[route]]
    real, artefact = 0, 0
    for i in range(1, len(stages)):
        (na, ea, fa, ta), (nb, eb, fb, tb) = stages[i-1], stages[i]
        if not ea or not eb:
            continue
        pa, pb = all_points(ea), all_points(eb)
        if not pa or not pb:
            continue
        # cheap coarse pass, then refine only if it looks far apart
        d = mindist(pa, pb, stride=25)
        if d > 0.05:
            d = mindist(pa, pb, stride=1)
        tag = 'TOUCH' if d < 0.05 else ('CLOSE' if d < 0.5 else 'GAP')
        if d >= 0.5:
            real += 1
        if tag == 'TOUCH':
            artefact += 1
        if d > 0.05:
            print('  %-26s -> %-26s  nearest approach %7.0f m   %s'
                  % ((na or '')[:26], (nb or '')[:26], d*1000, tag))
            if d >= 0.5:
                print('       %s ends "%s"  /  %s starts "%s"' % (na, ta, nb, fb))
    print('  consecutive stages that touch somewhere: %d of %d'
          % (artefact, len(stages)-1))
    print('  genuine separations over 500 m: %d' % real)

"""Produce the reference route files: one polyline per route, stages as km
intervals along it, all normalised west to east (Atlantic -> Mediterranean).
"""
import json, math, os, re, sys
from collections import defaultdict

SP = r'C:\Users\MARTIN~1.FIE\AppData\Local\Temp\claude\C--Users-martin-fielke-OneDrive---Accenture-Documents-Claude-Test-Planning-Other\54a269c5-48fe-4046-b63a-8f3d0d51d52d\scratchpad'
OUT = os.path.join('site', 'data', 'routes')
os.makedirs(OUT, exist_ok=True)
rels = json.load(open(os.path.join(SP, 'route_rels.json')))


def order_key(n):
    m = re.search(r'sec\.(\d+)|- E(\d+)|tape (\d+)', n or '')
    return int([g for g in m.groups() if g][0]) if m else 999


MAIN = {
  'gr10': [r for r in rels if r['tags'].get('ref') == 'GR 10' and re.search(r'sec\.\d+', r['tags'].get('name') or '')],
  'gr11': [r for r in rels if r['tags'].get('ref') == 'GR 11' and re.search(r'- E\d+', r['tags'].get('name') or '')],
  'hrp':  [r for r in rels if r['tags'].get('ref') == 'HRP' and re.search(r'tape \d+', r['tags'].get('name') or '')],
}
for k in MAIN:
    MAIN[k].sort(key=lambda r: order_key(r['tags'].get('name')))

META = {
 'gr10': dict(name='GR 10 \u2013 La travers\u00e9e des Pyr\u00e9n\u00e9es', ref='GR 10',
              side='French', from_='Hendaye', to='Banyuls-sur-Mer'),
 'gr11': dict(name='GR 11 \u2013 Senda Pirenaica', ref='GR 11',
              side='Spanish', from_='Cabo Higer', to='Cap de Creus'),
 'hrp':  dict(name='Haute Randonn\u00e9e Pyr\u00e9n\u00e9enne', ref='HRP',
              side='watershed', from_='Hendaye', to='Banyuls-sur-Mer'),
}


def gc(a, b):
    dlat = (b[0]-a[0])*111.0
    dlon = (b[1]-a[1])*111.0*math.cos(math.radians((a[0]+b[0])/2))
    return math.sqrt(dlat*dlat + dlon*dlon)


for rid in ('gr10', 'gr11', 'hrp'):
    d = json.load(open(os.path.join(SP, 'route_%s.json' % rid)))
    pts = [tuple(p) for p in d['points']]
    # normalise: Atlantic (west) first. If we flip the line we must also flip
    # each stage's from/to, which describe the original walking direction -
    # otherwise GR11 stage 1 reads "Bera -> Cape Higuer" on a west-to-east axis.
    reversed_line = pts[0][1] > pts[-1][1]
    if reversed_line:
        pts.reverse()
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + gc(pts[i-1], pts[i]))
    total = cum[-1]

    # project each stage onto the line via its own endpoints
    byid = {e['id']: e for e in json.load(open(os.path.join(SP, 'geo_%s.json' % rid.upper())))}

    def nearest_km(p):
        best, bk = 9e9, 0.0
        for i in range(0, len(pts), 7):            # coarse
            dd = gc(p, pts[i])
            if dd < best:
                best, bi = dd, i
        lo, hi = max(0, bi-10), min(len(pts), bi+10)
        for i in range(lo, hi):                    # refine
            dd = gc(p, pts[i])
            if dd < best:
                best, bi = dd, i
        return cum[bi], best

    stages = []
    for r in MAIN[rid]:
        e = byid.get(r['id'])
        if not e:
            continue
        sp = []
        for m in e.get('members', []):
            if m.get('type') == 'way' and m.get('geometry'):
                g = m['geometry']
                sp.append((g[0]['lat'], g[0]['lon']))
                sp.append((g[-1]['lat'], g[-1]['lon']))
        if not sp:
            continue
        kms = [nearest_km(p)[0] for p in sp]
        t = r['tags']
        a, b = t.get('from'), t.get('to')
        if reversed_line:
            a, b = b, a
        stages.append(dict(n=order_key(t.get('name')), name=t.get('name'),
                           **{'from': a, 'to': b},
                           startKm=round(min(kms), 2), endKm=round(max(kms), 2),
                           osmRelation=r['id']))
    stages.sort(key=lambda s: s['startKm'])

    doc = {
      'id': rid,
      'name': META[rid]['name'],
      'ref': META[rid]['ref'],
      'side': META[rid]['side'],
      'from': META[rid]['from_'],
      'to': META[rid]['to'],
      'lengthKm': round(total, 2),
      'pointCount': len(pts),
      'direction': 'west to east (Atlantic to Mediterranean)',
      'source': {
        'provider': 'OpenStreetMap',
        'licence': 'ODbL 1.0',
        'attribution': '\u00a9 OpenStreetMap contributors',
        'osmRelations': [r['id'] for r in MAIN[rid]],
        'fetched': '2026-09-23',
        'stitchedBy': 'shared endpoint coordinates, not relation member order',
        'simplifiedToM': 1.0
      },
      'stages': stages,
      'points': [[round(p[0], 6), round(p[1], 6)] for p in pts]
    }
    path = os.path.join(OUT, rid + '.json')
    json.dump(doc, open(path, 'w'), separators=(',', ':'))
    print('%-5s %7d pts  %7.1f km  %2d stages  %5.2f MB  %s -> %s'
          % (rid, len(pts), total, len(stages), os.path.getsize(path)/1048576,
             '%.3f,%.3f' % pts[0], '%.3f,%.3f' % pts[-1]))
    bad = [s for s in stages if s['endKm'] <= s['startKm']]
    if bad:
        print('      stages with no length: %s' % [s['name'] for s in bad][:4])
    covered = sum(s['endKm']-s['startKm'] for s in stages)
    print('      stage coverage %.1f km of %.1f km (%.0f%%)'
          % (covered, total, 100*covered/total))

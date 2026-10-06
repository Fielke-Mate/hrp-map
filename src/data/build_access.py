"""Access points: where a walker can realistically arrive from Paris, and how
they get from the station onto the GR10, GR11 or HRP.

The pattern is the one used for the original HRP trip: a train to Lourdes,
bus 965 from the station forecourt to Cauterets, and on up the valley. So an
access point is

    a station with a DIRECT train from Paris                (no change)
    plus how it reaches the trail:
        on the trail     the station itself is within 3 km of a route
        by train         a regional train from it calls at a station that is
        by bus           a bus from the station forecourt calls at a stop
                         within 1.5 km of a route

Nothing here is asserted. Every link is a trip in an official timetable:

    SNCF       TGV, Intercites (incl. night trains), TER and TER coaches
    liO        Occitanie regional buses (Hautes-Pyrenees to Pyrenees-Orientales)
    PA64       Pyrenees-Atlantiques regional buses (Basque Country and Bearn)

"Direct from Paris" means one trip in the SNCF timetable calls at both a
Paris terminus and the station. The SNCF feed only covers the timetable it
has published (currently to March 2027), so a summer-only train - the Hendaye
extension of the Paris night train, for instance - may be absent. Spanish
operators are not loaded yet, so GR11 access from the Spanish side is
under-represented; that is recorded in the output rather than hidden.

    python src/data/build_access.py      reads the feeds cached in .access/
"""
import collections, csv, datetime, io, json, math, os, re, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(HERE, '.access')
sys.stdout.reconfigure(encoding='utf-8')

ON_TRAIL_KM = 3.0          # station this close to a route: walk from the train
TRAILHEAD_KM = 1.5         # bus stop this close to a route is a trailhead
FORECOURT_KM = 0.4         # bus stop this close to the station: no cross-town transfer
BBOX = (42.0, 43.75, -2.1, 3.35)   # lat min/max, lon min/max: the Pyrenees and their gateways
# A seasonal bus for summer 2027 may simply not be published yet - the Gavarnie
# service appears only in September 2026, at the start of the feed. So the
# evidence is whichever summer the timetable actually covers, not next summer
# alone; treating "not published" as "does not run" dropped Gavarnie.
SUMMERS = [(datetime.date(y, 6, 15), datetime.date(y, 9, 15)) for y in (2026, 2027)]
SUMMER = SUMMERS[-1]
APPROACH_KM = 8.0           # report other routes this close, as the crow flies


def km(a, b):          # the planner's own formula, so km along the route agree
    dlat = (b[0] - a[0]) * 111.0
    dlon = (b[1] - a[1]) * 111.0 * math.cos((a[0] + b[0]) / 2 * math.pi / 180)
    return math.sqrt(dlat * dlat + dlon * dlon)


# ---- the routes, with a grid for fast "how far from the trail" ----------------
ROUTES = {}
GRID = collections.defaultdict(list)
CELL = 0.02
for rid in ('gr10', 'gr11', 'hrp'):
    pts = json.load(open(os.path.join(ROOT, 'data', 'routes', rid + '.json'), encoding='utf-8'))['points']
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + km(pts[i - 1], pts[i]))
    ROUTES[rid] = (pts, cum)
    for i in range(0, len(pts), 2):
        GRID[(int(pts[i][0] / CELL), int(pts[i][1] / CELL))].append((rid, i))


def near_routes(ll, max_km):
    """{route: (km along, km off)} for every route within max_km of ll."""
    out = {}
    r = int(max_km / (CELL * 78)) + 1
    cx, cy = int(ll[0] / CELL), int(ll[1] / CELL)
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            for rid, i in GRID.get((cx + dx, cy + dy), ()):
                d = km(ll, ROUTES[rid][0][i])
                if d <= max_km and (rid not in out or d < out[rid][1]):
                    out[rid] = (ROUTES[rid][1][i], d)
    return out


def inside(ll):
    return BBOX[0] <= ll[0] <= BBOX[1] and BBOX[2] <= ll[1] <= BBOX[3]


# ---- reading GTFS ----------------------------------------------------------------
def reader(z, name):
    return csv.DictReader(io.TextIOWrapper(z.open(name), encoding='utf-8-sig'))


def service_days(z):
    """service_id -> set of dates, from calendar.txt and calendar_dates.txt."""
    days = collections.defaultdict(set)
    names = z.namelist()
    if 'calendar.txt' in names:
        wk = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
        for c in reader(z, 'calendar.txt'):
            d = datetime.datetime.strptime(c['start_date'], '%Y%m%d').date()
            end = datetime.datetime.strptime(c['end_date'], '%Y%m%d').date()
            while d <= end:
                if c[wk[d.weekday()]] == '1':
                    days[c['service_id']].add(d)
                d += datetime.timedelta(days=1)
    if 'calendar_dates.txt' in names:
        for c in reader(z, 'calendar_dates.txt'):
            d = datetime.datetime.strptime(c['date'], '%Y%m%d').date()
            if c['exception_type'] == '1':
                days[c['service_id']].add(d)
            else:
                days[c['service_id']].discard(d)
    return days


def feed_window(days):
    alld = set().union(*days.values()) if days else set()
    return (min(alld), max(alld)) if alld else (None, None)


# ===================================================================== SNCF ======
z = zipfile.ZipFile(os.path.join(CACHE, 'sncf.zip'))
area, point_area, point_kind = {}, {}, {}
for s in reader(z, 'stops.txt'):
    ll = [float(s['stop_lat']), float(s['stop_lon'])]
    if s['location_type'] == '1':
        area[s['stop_id']] = {'name': s['stop_name'], 'll': ll,
                              'uic': s['stop_id'].split('OCE')[-1]}
    else:
        point_area[s['stop_id']] = s['parent_station'] or s['stop_id']
        m = re.match(r'StopPoint:OCE(.+)-\d+$', s['stop_id'])
        point_kind[s['stop_id']] = m.group(1) if m else '?'
paris = {a for a, v in area.items() if v['name'].startswith('Paris')
         and 48.8 < v['ll'][0] < 48.92 and 2.25 < v['ll'][1] < 2.42}
region = {a for a, v in area.items() if inside(v['ll'])}
print('SNCF: %d stations, %d Paris termini, %d in the Pyrenees box'
      % (len(area), len(paris), len(region)))

routes = {r['route_id']: r for r in reader(z, 'routes.txt')}
trips = {t['trip_id']: t for t in reader(z, 'trips.txt')}
sdays = service_days(z)
sncf_window = feed_window(sdays)

want = paris | region
calls = collections.defaultdict(list)          # trip -> [(seq, area, kind)]
for st in reader(z, 'stop_times.txt'):
    a = point_area.get(st['stop_id'])
    if a in want:
        calls[st['trip_id']].append((int(st['stop_sequence']), a, point_kind.get(st['stop_id'], '?')))
for t in calls.values():
    t.sort()

KIND = {'TGV INOUI': 'TGV INOUI', 'OUIGO': 'OUIGO', 'INTERCITES': 'Intercités',
        'INTERCITES de nuit': 'Intercités de nuit (night train)', 'Lyria': 'TGV Lyria'}
direct = collections.defaultdict(lambda: collections.defaultdict(
    lambda: {'paris': set(), 'trips': 0, 'days': set()}))
for tid, cs in calls.items():
    ps = [a for _, a, _ in cs if a in paris]
    if not ps:
        continue
    t = trips[tid]
    for _, a, kind in cs:
        if a in region:
            k = KIND.get(kind, kind)
            rec = direct[a][k]
            # "Paris Montparnasse Hall 1 - 2" is a platform hall, not a station name
            rec['paris'].update(re.sub(r'\s+Hall\b.*$', '', area[p]['name']) for p in ps)
            rec['trips'] += 1
            rec['days'] |= sdays.get(t['service_id'], set())
# A diverted night train calling once is not a way to plan a trip: Peyrehorade
# showed up as "direct from Paris" on the strength of a single day.
MIN_DIRECT_DAYS = 20
raw_direct = len(direct)
for a in list(direct):
    for k in list(direct[a]):
        if len(direct[a][k]['days']) < MIN_DIRECT_DAYS:
            del direct[a][k]
    if not direct[a]:
        del direct[a]
print('stations with a direct train to or from Paris: %d (%d before dropping services '
      'running on fewer than %d days)' % (len(direct), raw_direct, MIN_DIRECT_DAYS))

# stations of any kind within reach of the trail, for "by train" onward links
trail_station = {}
for a in region:
    n = near_routes(area[a]['ll'], ON_TRAIL_KM)
    if n:
        trail_station[a] = n

# regional trains: direct-Paris station A -> any station B on the same trip.
# B on the trail is an onward link in itself; any other B may be the start of
# a bus - Toulouse -> Boussens by train, then bus 452 to Aulus-les-Bains.
by_train = collections.defaultdict(lambda: collections.defaultdict(
    lambda: {'trips': 0, 'days': set(), 'line': set()}))
for tid, cs in calls.items():
    t = trips[tid]
    r = routes.get(t['route_id'], {})
    if r.get('route_type') != '2':
        continue
    stations = [a for _, a, _ in cs]
    for a in set(stations) & set(direct):
        if a in trail_station:
            continue                       # already on the trail, no onward leg needed
        for b in set(stations) & region:
            if b == a:
                continue
            rec = by_train[a][b]
            rec['trips'] += 1
            rec['days'] |= sdays.get(t['service_id'], set())
            # name it from the trip's own ends: SNCF labels some lines "INCONNU"
            rec['line'].add('TER ' + area[stations[0]]['name'] + ' - ' + area[stations[-1]]['name'])


# ===================================================================== buses =====
AGENCY_URL = {}
def load_bus(name, label, z, kinds=None):
    """Yield (line label, operator, service days, [(stop name, ll)]) per trip."""
    agencies = {a.get('agency_id', ''): a['agency_name'] for a in reader(z, 'agency.txt')}
    for a in reader(z, 'agency.txt'):
        if a.get('agency_url', '').startswith('http'):
            AGENCY_URL[a['agency_name']] = a['agency_url']
    rts = {r['route_id']: r for r in reader(z, 'routes.txt')}
    stops = {s['stop_id']: (s['stop_name'], [float(s['stop_lat']), float(s['stop_lon'])])
             for s in reader(z, 'stops.txt') if s.get('stop_lat')}
    trp = {t['trip_id']: t for t in reader(z, 'trips.txt')}
    if kinds:
        trp = {k: v for k, v in trp.items() if rts.get(v['route_id'], {}).get('route_type') in kinds}
    days = service_days(z)
    seq = collections.defaultdict(list)
    for st in reader(z, 'stop_times.txt'):
        if st['trip_id'] in trp:
            s = stops.get(st['stop_id'])
            if s and inside(s[1]):
                seq[st['trip_id']].append((int(st['stop_sequence']), s))
    for tid, ss in seq.items():
        ss.sort()
        t = trp[tid]
        r = rts.get(t['route_id'], {})
        line = ' '.join(x for x in ((r.get('route_short_name') or '').strip(),
                                    (r.get('route_long_name') or '').strip()) if x)
        yield (line or t.get('trip_headsign') or '?', agencies.get(r.get('agency_id', ''), label),
               days.get(t['service_id'], set()), [s for _, s in ss])
    print('%s: %d bus trips in the Pyrenees box, timetable %s to %s'
          % (label, len(seq), *feed_window(days)))


bus_sources = []
for fname, label in (('lio.zip', 'liO Occitanie'), ('pa64.zip', 'Pyrénées-Atlantiques')):
    zz = zipfile.ZipFile(os.path.join(CACHE, fname))
    bus_sources.append((label, list(load_bus(fname, label, zz)), feed_window(service_days(zz))))
bus_sources.append(('SNCF TER coach', list(load_bus('sncf.zip', 'SNCF TER coach', z, kinds={'3'})),
                    sncf_window))

# station -> bus trailheads, for every station in the box (a direct-Paris one,
# or one reached from it by regional train)
ST_GRID = collections.defaultdict(list)
for a in region:
    ST_GRID[(int(area[a]['ll'][0] / CELL), int(area[a]['ll'][1] / CELL))].append(a)


def stations_near(ll, max_km):
    cx, cy = int(ll[0] / CELL), int(ll[1] / CELL)
    return {a for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            for a in ST_GRID.get((cx + dx, cy + dy), ()) if km(ll, area[a]['ll']) <= max_km}


by_bus = collections.defaultdict(dict)
for label, trips_, window in bus_sources:
    for line, op, days, ss in trips_:
        starts = set()
        for _, ll in ss:
            starts |= stations_near(ll, FORECOURT_KM)
        for a in starts:
            if a in trail_station:
                continue
            sll = area[a]['ll']
            for name, ll in ss:
                if km(sll, ll) <= ON_TRAIL_KM:
                    continue                    # still in town, not a trailhead
                for rid, (rkm, off) in near_routes(ll, TRAILHEAD_KM).items():
                    # one trailhead per 5 km of route per line: a valley bus
                    # otherwise lists every hamlet the trail passes
                    key = (line, op, rid, round(rkm / 5.0))
                    cur = by_bus[a].get(key)
                    if cur is None or off < cur['off']:
                        by_bus[a][key] = cur = {'line': line, 'operator': op, 'source': label,
                                                'stop': name, 'll': ll, 'route': rid,
                                                'km': rkm, 'off': off, 'days': set(), 'trips': 0}
                    cur['days'] |= days
                    cur['trips'] += 1


# ===================================================================== output ====
# Organised by TRAILHEAD - where you start walking - not by station: every stop
# on the Paris-Hendaye line "has a train to Hendaye", which tells a walker
# nothing. Each trailhead lists the realistic ways to reach it from Paris.
MIN_SUMMER_BUS_DAYS = 10
WINDOWS = {label: w for label, _, w in bus_sources}
SNCF_SPAN = (sncf_window[1] - sncf_window[0]).days + 1
SUMMER_SPAN = (SUMMER[1] - SUMMER[0]).days + 1
CURATED = json.load(open(os.path.join(HERE, 'access_curated.json'), encoding='utf-8'))['links']


def when(days, window):
    span = (window[1] - window[0]).days + 1
    w = {'days': len(days), 'windowFrom': window[0].isoformat(), 'windowTo': window[1].isoformat(),
         'share': round(len(days) / span, 2), 'summerDays': None, 'summerYear': None,
         'summerCovered': None}
    best = None
    for lo, hi in SUMMERS:
        a, b = max(lo, window[0]), min(hi, window[1])
        if a > b:
            continue                        # this summer is outside the timetable
        covered = (b - a).days + 1
        n = sum(1 for d in days if a <= d <= b)
        # the summer with the MOST observed service is the evidence: a ratio
        # let 7 of 7 days at the very start of a feed beat 73 of 89 in the
        # next summer, and the 10-day floor then dropped Pau - Gourette
        if best is None or (n, covered) > (best[0], best[1]):
            best = (n, covered, lo.year)
    if best:
        w['summerDays'], w['summerCovered'], w['summerYear'] = best
    return w


def share(w):           # how often, for ranking: summer if we know it, else the year
    if w.get('summerDays') is not None:
        return w['summerDays'] / w['summerCovered']
    return w['share']


def paris_leg(a):
    svc = sorted(direct[a].items(), key=lambda kv: -len(kv[1]['days']))
    return {'mode': 'train', 'from': 'Paris', 'to': area[a]['name'],
            'll': [round(x, 6) for x in area[a]['ll']],
            'services': [{'service': k, 'parisStations': sorted(v['paris']),
                          'when': when(v['days'], sncf_window)} for k, v in svc]}


def paris_share(a):
    return max(len(v['days']) for v in direct[a].values()) / SNCF_SPAN


MIN_BUS_DAYS = 20          # where the timetable says nothing about summer


def summer_ok(w):
    if w['summerDays'] is None:
        return w['days'] >= MIN_BUS_DAYS
    return w['summerDays'] >= MIN_SUMMER_BUS_DAYS


def dominated(a, b):
    # changing at A to reach B is pointless when B has its own direct train
    # at least as often: the walker would simply take that one
    return b in direct and paris_share(b) >= 0.9 * paris_share(a)


cands = []          # (name, ll, {route: (km, off)}, option)
for a in direct:
    if a in trail_station:
        cands.append((area[a]['name'], area[a]['ll'], trail_station[a],
                      {'legs': [paris_leg(a)], 'direct': True, 'score': 1 + paris_share(a)}))
for a, bs in by_train.items():
    for b, v in bs.items():
        if b not in trail_station or dominated(a, b):
            continue
        w = when(v['days'], sncf_window)
        cands.append((area[b]['name'], area[b]['ll'], trail_station[b], {
            'legs': [paris_leg(a), {'mode': 'train', 'line': sorted(v['line'])[0], 'operator': 'SNCF TER',
                                    'source': 'SNCF', 'to': area[b]['name'], 'when': w}],
            'direct': False, 'score': min(paris_share(a), share(w))}))
bus_opts = []


def bus_leg(v):
    return {'mode': 'bus', 'line': v['line'][:80], 'operator': v['operator'], 'source': v['source'],
            'url': AGENCY_URL.get(v['operator']),
            'to': v['stop'], 'll': [round(x, 6) for x in v['ll']], 'when': when(v['days'], WINDOWS[v['source']])}





# direct train to A, regional train to B, bus from B's forecourt
for a, bs in by_train.items():
    for b, tv in bs.items():
        if dominated(a, b):
            continue
        tw = when(tv['days'], sncf_window)
        for v in by_bus.get(b, {}).values():
            bl = bus_leg(v)
            if not summer_ok(bl['when']):
                continue
            cands.append((v['stop'], v['ll'], near_routes(v['ll'], TRAILHEAD_KM), {
                'legs': [paris_leg(a), {'mode': 'train', 'line': sorted(tv['line'])[0], 'operator': 'SNCF TER',
                                        'source': 'SNCF', 'to': area[b]['name'], 'when': tw}, bl],
                'direct': False, 'score': min(paris_share(a), share(tw), share(bl['when'])) * 0.95}))

for a, d in by_bus.items():
    if a not in direct:
        continue
    for v in d.values():
        w = when(v['days'], WINDOWS[v['source']])
        if not summer_ok(w):
            continue        # a bus that does not run in summer is no use to a walker
        opt = {'legs': [paris_leg(a), bus_leg(v)],
               'direct': False, 'score': min(paris_share(a), share(w))}
        cands.append((v['stop'], v['ll'], near_routes(v['ll'], TRAILHEAD_KM), opt))
        bus_opts.append((v['ll'], opt))
# curated private shuttles, chained after a timetabled bus to their start
for c in CURATED:
    for ll, opt in bus_opts:
        if km(ll, c['from']['ll']) <= FORECOURT_KM:
            leg = {'mode': c['mode'], 'line': c['line'], 'operator': c['operator'],
                   'source': 'curated', 'to': c['to']['name'], 'll': c['to']['ll'],
                   'season': c['season'], 'provenance': c['source'], 'fallback': c.get('fallback')}
            cands.append((c['to']['name'], c['to']['ll'], near_routes(c['to']['ll'], TRAILHEAD_KM),
                          {'legs': opt['legs'] + [leg], 'direct': False, 'score': opt['score'] * 0.9}))

# merge candidates that are the same place (within 500 m)
heads = []
for name, ll, rts, opt in cands:
    if not rts:
        continue
    h = next((h for h in heads if km(h['ll'], ll) <= 0.5), None)
    if h is None:
        h = {'name': name, 'll': [round(x, 6) for x in ll], 'routes': {}, 'options': []}
        heads.append(h)
    elif opt['direct'] and not any(o['direct'] for o in h['options']):
        h['name'], h['ll'] = name, [round(x, 6) for x in ll]      # a station names the place
    for rid, (rkm, off) in rts.items():
        if rid not in h['routes'] or off < h['routes'][rid][1]:
            h['routes'][rid] = (rkm, off)
    h['options'].append(opt)

# Two trailheads within 3 km along the same route are one place to a walker
# (Hendaye and the halt beside it; Luz and Viella on the same bus). Keep the
# better one: a direct train first, then the closer to the trail - unless the
# two are within 300 m of it, when a stop the bus line is named after (968
# LOURDES - LUZ) wins over a roadside hamlet.
def best_score(h):
    return max(o['score'] for o in h['options'])


def preferred(a, b):
    da, db = any(o['direct'] for o in a['options']), any(o['direct'] for o in b['options'])
    if da != db:
        return a if da else b
    oa = min(v[1] for v in a['routes'].values())
    ob = min(v[1] for v in b['routes'].values())
    if abs(oa - ob) > 0.3:
        return a if oa < ob else b
    def named(h):
        # LUZ-SAINT-SAUVEUR is the town bus "968 LOURDES - LUZ" is named after
        town = h['name'].split(' - ')[0].upper()
        toks = {t for o in h['options'] for l in o['legs']
                for t in re.findall(r"[A-ZÀ-Ü'-]{3,}", (l.get('line') or '').upper())}
        return any(town.startswith(t) for t in toks)
    if named(a) != named(b):
        return a if named(a) else b
    return a if best_score(a) >= best_score(b) else b


merged_any = True
while merged_any:
    merged_any = False
    for i in range(len(heads)):
        for j in range(i + 1, len(heads)):
            a, b = heads[i], heads[j]
            shared = [r for r in a['routes'] if r in b['routes']
                      and abs(a['routes'][r][0] - b['routes'][r][0]) <= 3.0]
            if shared and km(a['ll'], b['ll']) <= 3.0:
                keep = preferred(a, b)
                drop = b if keep is a else a
                # the kept place keeps ITS OWN position on the trail: borrowing the
                # dropped stop's closer km put "Luz" at Viella's km, so "start
                # here" would drop the pin where the bus does not stop
                for rid, v in drop['routes'].items():
                    if rid not in keep['routes']:
                        keep['routes'][rid] = v
                keep['options'] += drop['options']
                heads.remove(drop)
                merged_any = True
                break
        if merged_any:
            break

out_heads = []
for h in heads:
    seen, opts = set(), []
    best_direct = max([o['score'] - 1 for o in h['options'] if o['direct']], default=0)
    # an option whose last stop IS this trailhead is listed before one that
    # reached a stop since merged into it, so the kept one reads consistently
    for o in sorted(h['options'], key=lambda o: (-o['score'], o['legs'][-1].get('to') != h['name'])):
        # one entry per way of getting here: the gateway and the lines taken,
        # not the exact stop - two stops of one village are the same journey
        key = tuple(l.get('line') or l.get('to') for l in o['legs'])
        if key in seen:
            continue
        seen.add(key)
        # a change of train is pointless where a direct train is at least as frequent
        if not o['direct'] and o['score'] <= best_direct + 1e-9:
            continue
        opts.append(o)
    # the same onward journey from several gateways (Perpignan, Narbonne and
    # Beziers all reach the Banyuls train): keep the gateway nearest to here
    by_tail = {}
    for o in opts:
        tail = tuple(l['to'] if l['mode'] == 'train' else l.get('line') for l in o['legs'][1:])
        d = km(o['legs'][0]['ll'], h['ll']) if o['legs'] else 0
        if tail not in by_tail or d < by_tail[tail][0]:
            by_tail[tail] = (d, o)
    keep = {id(o) for _, o in by_tail.values()}
    opts = [o for o in opts if o['direct'] or id(o) in keep]
    # and from any one gateway, only its shortest way here: Perpignan's own
    # bus 560 makes "train to Prades, then bus 560" redundant
    fewest = {}
    for o in opts:
        g = o['legs'][0]['to']
        fewest[g] = min(fewest.get(g, 99), len(o['legs']))
    opts = [o for o in opts if len(o['legs']) == fewest[o['legs'][0]['to']]]
    direct_opts = [o for o in opts if o['direct']]
    others = [o for o in opts if not o['direct']][:3]
    if not direct_opts and not others:
        continue
    # other routes within reach on foot - reported as the crow flies, because
    # the approach path is not mapped here and must not be presented as known
    approach = [{'route': r, 'crowKm': round(v[1], 1)}
                for r, v in sorted(near_routes(h['ll'], APPROACH_KM).items()) if r not in h['routes']]
    out_heads.append({'name': h['name'], 'll': h['ll'],
                      'routes': [{'route': r, 'km': round(v[0], 2), 'offM': round(v[1] * 1000)}
                                 for r, v in sorted(h['routes'].items())],
                      'approach': approach,
                      'options': [{k: v for k, v in o.items() if k != 'score'}
                                  for o in direct_opts + others]})
out_heads.sort(key=lambda h: h['ll'][1])

doc = {
    'about': 'Places to start walking on the GR10, GR11 and HRP that can be reached from Paris: '
             'by a direct train, or a direct train to a gateway and then a regional train or bus. '
             'Every timetabled leg is a trip in the official timetables listed under sources.',
    'rules': {'onTrailKm': ON_TRAIL_KM, 'trailheadKm': TRAILHEAD_KM, 'forecourtKm': FORECOURT_KM,
              'minDirectDays': MIN_DIRECT_DAYS, 'minSummerBusDays': MIN_SUMMER_BUS_DAYS,
              'summer': '15 June - 15 September, in whichever year the timetable covers',
              'approachKm': APPROACH_KM},
    'sources': [{'name': 'SNCF TGV, Intercités and TER', 'licence': 'ODbL',
                 'url': 'https://transport.data.gouv.fr/datasets/horaires-sncf',
                 'from': sncf_window[0].isoformat(), 'to': sncf_window[1].isoformat()},
                {'name': 'liO Occitanie regional buses', 'licence': 'ODbL',
                 'url': 'https://transport.data.gouv.fr/datasets/reseau-interurbain-lio-occitanie',
                 'from': WINDOWS['liO Occitanie'][0].isoformat(), 'to': WINDOWS['liO Occitanie'][1].isoformat()},
                {'name': 'Pyrénées-Atlantiques regional buses', 'licence': 'Licence Ouverte',
                 'url': 'https://transport.data.gouv.fr/datasets/reseau-interurbain-pyrenees-atlantiques-64',
                 'from': WINDOWS['Pyrénées-Atlantiques'][0].isoformat(),
                 'to': WINDOWS['Pyrénées-Atlantiques'][1].isoformat()}],
    'gaps': ['Spanish rail and bus operators are not loaded yet, so starts on the Spanish side '
             '(most of the GR11) are under-represented.',
             'The SNCF timetable is published only to %s, so summer-only trains - such as the '
             'summer extension of the Paris night train to Hendaye - can be missing.'
             % sncf_window[1].isoformat(),
             'Private shuttles are in no open timetable; the few included are curated and marked.'],
    'built': datetime.date.today().isoformat(),
    'trailheads': out_heads,
}
out = os.path.join(ROOT, 'data', 'access.json')
json.dump(doc, open(out, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('\nwrote %s  %.0f KB, %d trailheads' % (out, os.path.getsize(out) / 1024, len(out_heads)))


def leg_txt(l):
    if l['mode'] == 'train' and 'services' in l:
        s = l['services'][0]
        return '%s to %s (%d d)' % (s['service'], l['to'], s['when']['days'])
    w = l.get('when')
    return '%s %s to %s%s' % (l['mode'], l['line'][:34], l['to'][:24],
                              (' (%s of %s summer-%s d)' % (w['summerDays'], w['summerCovered'], w['summerYear']))
                              if w and w.get('summerDays') is not None
                              else (' (%d d)' % w['days'] if w else ' [curated]'))


for h in out_heads:
    print('\n%-30s %s%s' % (h['name'][:30], ', '.join('%s km %.0f (%d m)' % (r['route'].upper(), r['km'], r['offM'])
                                                for r in h['routes']),
                            ''.join('   [%s %.1f km away]' % (a['route'].upper(), a['crowKm']) for a in h['approach'])))
    for o in h['options']:
        print('    %s %s' % ('DIRECT ' if o['direct'] else '       ', '  ->  '.join(leg_txt(l) for l in o['legs'])))

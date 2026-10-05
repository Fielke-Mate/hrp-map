"""Verify every external page we are about to link a hut to.

A link is only useful if it opens the RIGHT hut. An OSM record carrying the
wrong reference number would send a hiker to another hut's page - with its
photos, its state reports, its phone number - which is worse than no link.

    refuges.info         one bounding-box API request returns every point with
                         its position; a ref is confirmed if that point lies
                         within 300 m of ours. Refs missing from it are fetched
                         one by one: a 404 means refuges.info deleted the page.
    pyrenees-refuges.com the sitemap maps every page number to its name. Where
                         the name disagrees with ours (often just French vs
                         Spanish/Basque/Catalan), the page itself is fetched -
                         politely, one at a time - and its position decides.
                         robots.txt disallows the bulk data file; it is not used.

Writes .links/verified.json: {osm id: {"refuges_info": url|null, ...}} with the
reason for every link withheld. finalise_shelters.py reads it.

    python src/data/verify_links.py          uses the cached downloads
    python src/data/verify_links.py --fetch  refreshes them first
"""
import json, math, os, re, socket, ssl, sys, time, unicodedata, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(HERE, '.links')
UA = 'Pyrenees traverse planner (link verification; fielke-mate.github.io/hrp-map)'
SAME_KM = 0.3
os.makedirs(CACHE, exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8')


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'replace'), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, '', url


def km(a, b):
    dlat = (b[0] - a[0]) * 111.0
    dlon = (b[1] - a[1]) * 111.0 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


def toks(x):
    x = unicodedata.normalize('NFD', (x or '').lower())
    x = ''.join(c for c in x if not unicodedata.combining(c))
    stop = {'refuge', 'refugi', 'refugio', 'cabane', 'cabana', 'caba', 'abri', 'orri',
            'de', 'du', 'des', 'la', 'le', 'les', 'del', 'dels', 'el', 'los', 'las', 'et',
            'y', 'd', 'l', 'pastorale', 'pastoral', 'gite', 'etape'}
    return {w for w in re.findall(r'[a-z0-9]+', x) if len(w) > 2 and w not in stop}


def cached(name, url, fetch):
    p = os.path.join(CACHE, name)
    if fetch or not os.path.exists(p):
        code, body, _ = get(url, 180)
        if code != 200:
            sys.exit('could not fetch %s: HTTP %s' % (url, code))
        open(p, 'w', encoding='utf-8').write(body)
    return open(p, encoding='utf-8').read()


FETCH = '--fetch' in sys.argv
S = json.load(open(os.path.join(ROOT, 'data', 'shelters.json'), encoding='utf-8'))['shelters']
feats = json.load(open(os.path.join(HERE, '.shelters', 'all_features.json')))


def tags(s):
    t = {}
    for i in [s['id']] + s.get('mergedFrom', []):
        for k, v in (feats.get(i, {}).get('tags') or {}).items():
            t.setdefault(k, v)
    return t


def ref_num(v):
    m = re.search(r'(\d+)', str(v or ''))
    return int(m.group(1)) if m else None


# ---- refuges.info -----------------------------------------------------------
ri = {f['id']: f for f in json.loads(cached(
    'refuges_info.json',
    'https://www.refuges.info/api/bbox?bbox=-2.2,42.0,3.5,43.6&type_points=all'
    '&nb_points=all&format=geojson&detail=simple', FETCH))['features']}

# ---- pyrenees-refuges.com ---------------------------------------------------
xml = cached('pyrenees_refuges_sitemap.xml', 'https://www.pyrenees-refuges.com/sitemap.xml', FETCH)
pr = {int(m[3]): {'url': m[0], 'slug': m[2]} for m in re.findall(
    r'<loc>(https://www\.pyrenees-refuges\.com/([a-z\-]+)/([a-z0-9\-]+)-(\d+))</loc>', xml)}
pr_pos_file = os.path.join(CACHE, 'pyrenees_refuges_positions.json')
pr_pos = json.load(open(pr_pos_file, encoding='utf-8')) if os.path.exists(pr_pos_file) else {}

out, tally = {}, {'ri_ok': 0, 'ri_withheld': 0, 'pr_ok': 0, 'pr_withheld': 0}
for s in S:
    t = tags(s)
    rec = {}
    n = ref_num(t.get('ref:refuges.info'))
    if n is not None:
        f = ri.get(n)
        if f is None:
            code, _, final = get('https://www.refuges.info/point/%d/' % n, 30)
            time.sleep(1)
            if code == 200:
                rec['refuges_info'] = final
                tally['ri_ok'] += 1
            else:
                rec['refuges_info'] = None
                rec['refuges_info_note'] = 'refuges.info has removed its page for this hut (HTTP %d)' % code
                tally['ri_withheld'] += 1
        else:
            pos = [f['geometry']['coordinates'][1], f['geometry']['coordinates'][0]]
            d = km(s['ll'], pos)
            if d <= SAME_KM:
                rec['refuges_info'] = f['properties']['lien']
                tally['ri_ok'] += 1
            else:
                rec['refuges_info'] = None
                rec['refuges_info_note'] = ('refuges.info number %d is %.1f km away - a different hut'
                                            % (n, d))
                tally['ri_withheld'] += 1
    n = ref_num(t.get('ref:FR:pyrenees_refuges'))
    if n is not None:
        p = pr.get(n)
        if p is None:
            rec['pyrenees_refuges'] = None
            rec['pyrenees_refuges_note'] = 'pyrenees-refuges.com no longer lists number %d' % n
            tally['pr_withheld'] += 1
        else:
            a, b = toks(s.get('name')), toks(p['slug'].replace('-', ' '))
            agree = bool(a & b)
            if not agree:
                # names differ: let the page's own position decide
                key = str(n)
                if key not in pr_pos or FETCH:
                    code, body, _ = get(p['url'], 30)
                    time.sleep(1.5)
                    m1 = re.search(r'"latitude"\s*:\s*(-?\d+\.\d+)', body)
                    m2 = re.search(r'"longitude"\s*:\s*(-?\d+\.\d+)', body)
                    pr_pos[key] = [float(m1.group(1)), float(m2.group(1))] if (code == 200 and m1 and m2) else None
                pos = pr_pos.get(key)
                d = km(s['ll'], pos) if pos else None
                agree = d is not None and d <= SAME_KM
                if not agree:
                    rec['pyrenees_refuges'] = None
                    rec['pyrenees_refuges_note'] = (
                        ('pyrenees-refuges.com page %d (%s) is %.1f km away - a different hut'
                         % (n, p['slug'], d)) if d is not None else
                        'pyrenees-refuges.com page %d could not be located' % n)
                    tally['pr_withheld'] += 1
            if agree:
                rec['pyrenees_refuges'] = p['url']
                tally['pr_ok'] += 1
    if rec:
        out[s['id']] = rec

json.dump(pr_pos, open(pr_pos_file, 'w', encoding='utf-8'))


# ---- websites ----------------------------------------------------------------
# A phone number cannot be checked from here, but a website that has ceased to
# exist is a strong hint the place has too. Classified conservatively: only a
# domain that no longer resolves, or a page the server itself reports missing
# (404/410), counts as dead. Bot blocking, server errors, timeouts and expired
# certificates are "could not check" - small refuge sites are often like that
# and still very much open.
def website_of(t):
    w = t.get('website') or t.get('contact:website') or t.get('url')
    if not w:
        return None
    w = str(w).split(';')[0].strip()
    if not re.match(r'^https?://', w, re.I):
        if re.match(r'^[\w.-]+\.[a-z]{2,}(/.*)?$', w, re.I):
            w = 'https://' + w
        else:
            return None
    return w


def probe(url):
    host = re.sub(r'^https?://', '', url, flags=re.I).split('/')[0].split(':')[0]
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror:
        # The local resolver is not evidence on its own: on the first run it
        # declared campingixeia.es non-existent while public DNS resolves it.
        # Only a public NXDOMAIN counts; SERVFAIL and the rest are ambiguous.
        try:
            d = json.load(urllib.request.urlopen(
                'https://dns.google/resolve?name=%s&type=A' % host, timeout=20))
            status = d.get('Status')
        except Exception:
            status = None
        if status == 3:
            return 'dead', 'the domain %s no longer exists' % host
        return 'unchecked', 'local DNS failed; public DNS status %s' % status
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (link check)'})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return 'ok', r.status
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return 'dead', 'the page reports it no longer exists (HTTP %d)' % e.code
        return 'unchecked', 'HTTP %d' % e.code
    except Exception as e:
        return 'unchecked', type(e).__name__


web_file = os.path.join(CACHE, 'websites.json')
web = json.load(open(web_file, encoding='utf-8')) if os.path.exists(web_file) else {}
want = sorted({website_of(tags(s)) for s in S} - {None})
todo = [u for u in want if FETCH or u not in web]
with ThreadPoolExecutor(8) as ex:
    for u, res in zip(todo, ex.map(probe, todo)):
        web[u] = {'state': res[0], 'detail': res[1], 'checked': time.strftime('%Y-%m-%d')}
json.dump(web, open(web_file, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
for s in S:
    u = website_of(tags(s))
    if not u:
        continue
    rec = out.setdefault(s['id'], {})
    rec['website'] = u
    w = web.get(u, {})
    if w.get('state') == 'dead':
        rec['website_note'] = 'Website checked %s: %s' % (w['checked'], w['detail'])
from collections import Counter
st = Counter(web[u]['state'] for u in want if u in web)
print('websites           %d checked: %s' % (len(want), dict(st)))
for u in want:
    if web.get(u, {}).get('state') == 'dead':
        print('   dead      %-50s %s' % (u[:50], web[u]['detail']))
json.dump({'checked': time.strftime('%Y-%m-%d'), 'links': out},
          open(os.path.join(CACHE, 'verified.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print('refuges.info       linked %d, withheld %d' % (tally['ri_ok'], tally['ri_withheld']))
print('pyrenees-refuges   linked %d, withheld %d' % (tally['pr_ok'], tally['pr_withheld']))
for i, r in out.items():
    for k in ('refuges_info_note', 'pyrenees_refuges_note'):
        if r.get(k):
            s = next(x for x in S if x['id'] == i)
            print('   withheld  %-38s %s' % (s['label'][:38], r[k]))

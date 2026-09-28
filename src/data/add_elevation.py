"""Attach elevation to the route reference files.

Source: AWS Terrain Tiles (registry.opendata.aws/terrain-tiles), terrarium
encoding, elevation = (R*256 + G + B/256) - 32768. Open data, no key, no rate
limit, and cacheable - which matters because 106k points is far past what the
free elevation APIs allow (opentopodata is 1000 calls/day at 100 points each).

z12 is 28 m/px at this latitude, matching the ~30 m source resolution. z13
returns identical values, so it would be four times the tiles for upsampled
data.

Sampling is bilinear rather than nearest-pixel: ascent is later accumulated
over the profile, and nearest-pixel stair-steps inflate it.

    python src/data/add_elevation.py --count     tiles needed, no download
    python src/data/add_elevation.py             fetch and attach
"""
import io, json, math, os, sys, threading, queue, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUTES = os.path.join(ROOT, 'data', 'routes')
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.tilecache')
Z = 12
COUNT_ONLY = '--count' in sys.argv


def tile_of(lat, lon, z=Z):
    n = 2 ** z
    return ((lon + 180) / 360 * n,
            (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


routes = {}
needed = set()
for rid in ('gr10', 'gr11', 'hrp'):
    d = json.load(open(os.path.join(ROUTES, rid + '.json')))
    routes[rid] = d
    for p in d['points']:
        la, lo = p[0], p[1]          # tolerate [lat,lon] or [lat,lon,ele] so
        fx, fy = tile_of(la, lo)     # the script can be re-run on its output
        # a point near a tile edge samples from the neighbour too
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                needed.add((int(fx) + dx, int(fy) + dy))
print('routes: %s' % ', '.join('%s %d pts' % (k, len(v['points'])) for k, v in routes.items()))
print('z%d tiles needed (incl. edge neighbours): %d' % (Z, len(needed)))
print('estimated download: %.0f MB' % (len(needed) * 0.13))
if COUNT_ONLY:
    sys.exit(0)

os.makedirs(CACHE, exist_ok=True)
from PIL import Image

lock = threading.Lock()
tiles = {}
fetched = [0]
failed = []


def worker(q):
    while True:
        try:
            xy = q.get_nowait()
        except queue.Empty:
            return
        x, y = xy
        path = os.path.join(CACHE, '%d_%d_%d.png' % (Z, x, y))
        try:
            if not os.path.exists(path):
                url = ('https://s3.amazonaws.com/elevation-tiles-prod/terrarium/'
                       '%d/%d/%d.png' % (Z, x, y))
                req = urllib.request.Request(url, headers={'User-Agent': 'HRP-Planner-build/1.0'})
                raw = urllib.request.urlopen(req, timeout=90).read()
                with open(path, 'wb') as f:
                    f.write(raw)
            with lock:
                fetched[0] += 1
                if fetched[0] % 50 == 0:
                    print('  %d/%d' % (fetched[0], len(needed))); sys.stdout.flush()
        except Exception as e:
            # a tile over open sea legitimately 404s; record and move on
            with lock:
                failed.append((x, y, str(e)[:40]))
        finally:
            q.task_done()


q = queue.Queue()
for xy in sorted(needed):
    q.put(xy)
threads = [threading.Thread(target=worker, args=(q,), daemon=True) for _ in range(8)]
[t.start() for t in threads]
[t.join() for t in threads]
print('tiles on disk: %d, unavailable: %d' % (fetched[0], len(failed)))


class TileStore:
    """lazily decode tiles to float arrays, keeping a bounded set in memory"""
    def __init__(self):
        self.cache = {}

    def get(self, x, y):
        k = (x, y)
        if k in self.cache:
            return self.cache[k]
        path = os.path.join(CACHE, '%d_%d_%d.png' % (Z, x, y))
        arr = None
        if os.path.exists(path):
            im = Image.open(path).convert('RGB')
            arr = (im.width, im.height, im.load())
        if len(self.cache) > 400:
            self.cache.clear()
        self.cache[k] = arr
        return arr

    def sample(self, lat, lon):
        fx, fy = tile_of(lat, lon)
        tx, ty = int(fx), int(fy)
        t = self.get(tx, ty)
        if not t:
            return None
        W, H, px = t
        # pixel coordinates within the tile, offset by half a pixel so that
        # bilinear weights are centred on pixel centres
        gx = (fx - tx) * W - 0.5
        gy = (fy - ty) * H - 0.5
        x0, y0 = math.floor(gx), math.floor(gy)
        wx, wy = gx - x0, gy - y0
        tot, wsum = 0.0, 0.0
        for dx in (0, 1):
            for dy in (0, 1):
                sx, sy = x0 + dx, y0 + dy
                ttx, tty, ssx, ssy = tx, ty, sx, sy
                if sx < 0:
                    ttx, ssx = tx - 1, sx + W
                elif sx >= W:
                    ttx, ssx = tx + 1, sx - W
                if sy < 0:
                    tty, ssy = ty - 1, sy + H
                elif sy >= H:
                    tty, ssy = ty + 1, sy - H
                tt = self.get(ttx, tty) if (ttx, tty) != (tx, ty) else t
                if not tt:
                    continue
                r, g, b = tt[2][ssx, ssy]
                e = (r * 256 + g + b / 256.0) - 32768.0
                w = (wx if dx else 1 - wx) * (wy if dy else 1 - wy)
                tot += e * w
                wsum += w
        return (tot / wsum) if wsum > 0 else None


store = TileStore()
for rid, d in routes.items():
    pts = d['points']
    out, misses = [], 0
    for p in pts:
        la, lo = p[0], p[1]
        e = store.sample(la, lo)
        if e is None:
            misses += 1
            e = out[-1][2] if out else 0
        out.append([la, lo, round(e)])
    eles = [p[2] for p in out]
    d['points'] = out
    d['source']['elevation'] = {
        'provider': 'AWS Terrain Tiles (terrarium)',
        'url': 'https://registry.opendata.aws/terrain-tiles/',
        'zoom': Z, 'sampling': 'bilinear',
        'note': 'derived from SRTM and national DEMs; +-10-16 m typical'
    }
    json.dump(d, open(os.path.join(ROUTES, rid + '.json'), 'w'), separators=(',', ':'))
    print('%-5s min %5d  max %5d  median %5d  no-data points %d  %.2f MB'
          % (rid, min(eles), max(eles), sorted(eles)[len(eles)//2], misses,
             os.path.getsize(os.path.join(ROUTES, rid + '.json')) / 1048576))
if failed:
    print('\ntiles that never arrived (sea or missing): %d' % len(failed))

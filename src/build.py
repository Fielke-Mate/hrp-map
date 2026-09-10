import re, io, os, sys
SP = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(SP,'hrp_wallon_luchon.html'), encoding='utf-8').read()
orig_len = len(src)

css = open(os.path.join(SP,'leaflet.css'), encoding='utf-8').read()
js  = open(os.path.join(SP,'leaflet.js'),  encoding='utf-8').read()
off = open(os.path.join(SP,'offline_block.js'), encoding='utf-8').read()

assert '</script' not in js, 'leaflet.js contains a script terminator'

# --- 1. inline leaflet css -------------------------------------------------
link = '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>'
assert src.count(link) == 1, 'css link not found exactly once'
# the only url() refs are for the default marker + layers control, neither of
# which this map uses; drop them so nothing 404s offline
css_clean = re.sub(r'url\((images/[^)]*)\)', 'none', css)
src = src.replace(link, '<style>/* leaflet 1.9.4 */\n' + css_clean + '</style>')

# --- 2. inline leaflet js --------------------------------------------------
scr = '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
assert src.count(scr) == 1, 'js script tag not found exactly once'
src = src.replace(scr, '<script>/* leaflet 1.9.4 */\n' + js + '\n</script>')

# --- 3. PWA head tags ------------------------------------------------------
head_extra = (
 '<link rel="manifest" href="./manifest.webmanifest"/>\n'
 '<meta name="theme-color" content="#0a1622"/>\n'
 '<meta name="mobile-web-app-capable" content="yes"/>\n'
 '<meta name="apple-mobile-web-app-capable" content="yes"/>\n'
 '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>\n'
 '<meta name="apple-mobile-web-app-title" content="HRP"/>\n'
 '<link rel="apple-touch-icon" href="./apple-touch-icon.png"/>\n'
 '<link rel="icon" href="./icon-192.png"/>\n'
)
m = re.search(r'</head>', src)
assert m, 'no </head>'
src = src[:m.start()] + head_extra + src[m.start():]

# --- 4. tiles must be CORS-enabled or the SW caches opaque, quota-padded
#        responses. OpenTopoMap sends Access-Control-Allow-Origin: *
tl_old = """L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{
  attribution:'OpenTopoMap (CC-BY-SA)',
  maxZoom:17,"""
tl_new = """L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{
  attribution:'Kartendaten: \u00a9 OpenStreetMap-Mitwirkende, SRTM | Kartendarstellung: \u00a9 OpenTopoMap (CC-BY-SA)',
  crossOrigin:true,          // needed so the service worker caches CORS (non-opaque) responses
  maxZoom:17,"""
assert src.count(tl_old) == 1, 'tile layer block not matched'
src = src.replace(tl_old, tl_new)

# --- 5. append the offline block just before the closing script tag --------
idx = src.rindex('</script>')
src = src[:idx] + off + src[idx:]


open(os.path.join(os.path.dirname(SP),'index.html'), 'w', encoding='utf-8').write(src)
print('source     %8.1f KB' % (orig_len/1024))
print('site/index %8.1f KB' % (len(src)/1024))
print('leaflet css/js inlined, PWA tags added, crossOrigin set, offline block appended')

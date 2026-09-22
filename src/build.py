"""Build site/index.html from src/hrp_wallon_luchon.html.

  python src/build.py            rebuild index.html
  python src/build.py --check    verify index.html is current; write nothing

Guards against the mistakes this project has actually made:

  * a second copy of the source outside src/, which let an edit go into one
    file while the build read the other and silently produced a stale page
  * committing an index.html that does not match its source (--check, wired
    into .githooks/pre-commit)
  * module-level `const`/`let` read by a function that startup calls earlier
    in the file - a temporal dead zone that throws at load, leaves hoisted
    functions callable so the page looks alive, and which `node --check`
    cannot see because it is a runtime error, not a syntax one
"""
import re, os, sys, glob

SP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SP)
CHECK = '--check' in sys.argv
SRC = os.path.join(SP, 'hrp_wallon_luchon.html')
OUT = os.path.join(ROOT, 'index.html')


def die(msg):
    print('BUILD FAILED: ' + msg)
    sys.exit(1)


# --- guard 1: exactly one source ------------------------------------------
strays = []
for d in (ROOT, os.path.dirname(ROOT)):
    for p in glob.glob(os.path.join(d, 'hrp_wallon_luchon.html*')):
        if os.path.abspath(p) != os.path.abspath(SRC):
            strays.append(p)
if strays:
    die('a second copy of the source exists, so edits can go to the wrong file:\n'
        + '\n'.join('   ' + os.path.relpath(p, ROOT) for p in strays)
        + '\n   The only source is src/hrp_wallon_luchon.html - delete the others.')

src = open(SRC, encoding='utf-8').read()
orig_len = len(src)
css = open(os.path.join(SP, 'leaflet.css'), encoding='utf-8').read()
js = open(os.path.join(SP, 'leaflet.js'), encoding='utf-8').read()
off = open(os.path.join(SP, 'offline_block.js'), encoding='utf-8').read()
if '</script' in js:
    die('leaflet.js contains a script terminator')


# --- guard 2: temporal-dead-zone lint -------------------------------------
def tdz_lint(text):
    """module-level const/let read by code that runs before the declaration.

    Follows the call graph, not just direct calls: the two real bugs here were
    both indirect - updateDayCards() -> calcDayStats() -> ELEV_SAMPLE_M, and
    snapshotShelterWindows() -> computeShelterWindow() -> SHELTER_WINDOW_PAD_KM.
    """
    m = re.findall(r'<script>(.*?)</script>', text, re.S)
    if not m:
        return []
    code = m[-1].split('\n')
    KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'function', 'catch',
                'typeof', 'new', 'do', 'else'}

    decls = {}                       # name -> line index
    for i, ln in enumerate(code):
        d = re.match(r'(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=', ln)
        if d and 'tdz-ok' not in ln:
            decls.setdefault(d.group(1), i)

    def body_end(start):
        depth = 0
        for j in range(start, len(code)):
            depth += code[j].count('{') - code[j].count('}')
            if depth <= 0 and j > start:
                return j
        return len(code) - 1

    funcs = {}                       # name -> (start, end)
    for i, ln in enumerate(code):
        f = re.match(r'function\s+([A-Za-z_$][\w$]*)\s*\(', ln)
        if f:
            funcs[f.group(1)] = (i, body_end(i))

    # who calls whom
    callees = {}
    for name, (fs, fe) in funcs.items():
        seen = set()
        for k in range(fs, fe + 1):
            for c in re.findall(r'\b([A-Za-z_$][\w$]*)\s*\(', code[k]):
                if c in funcs and c != name:
                    seen.add(c)
        callees[name] = seen

    def reachable(start):
        out, stack = set(), [start]
        while stack:
            f = stack.pop()
            for g in callees.get(f, ()):
                if g not in out:
                    out.add(g)
                    stack.append(g)
        out.add(start)
        return out

    # things that execute at load: bare `foo();` at column 0, and top-level IIFEs
    entries = []                     # (label, line, set-of-functions-reached)
    for i, ln in enumerate(code):
        # trailing comments are common on these lines, e.g.
        #   snapshotShelterWindows();   // freeze candidate lists
        # and an anchored `);\s*$` silently skips them
        c = re.match(r'([A-Za-z_$][\w$]*)\(.*\);\s*(?://.*)?$', ln)
        if c and c.group(1) not in KEYWORDS and c.group(1) in funcs:
            entries.append((c.group(1) + '()', i, reachable(c.group(1))))
        if re.match(r'\(function\s*\(', ln) or re.match(r'\(\s*\(\)\s*=>', ln):
            end = body_end(i)
            reached = set()
            for k in range(i, end + 1):
                for f in re.findall(r'\b([A-Za-z_$][\w$]*)\s*\(', code[k]):
                    if f in funcs:
                        reached |= reachable(f)
            entries.append(('top-level IIFE', i, reached))

    problems = []
    for name, dline in sorted(decls.items(), key=lambda kv: kv[1]):
        ref = re.compile(r'\b' + re.escape(name) + r'\b')
        for label, cline, reached in entries:
            if cline >= dline:
                continue
            for fname in reached:
                fs, fe = funcs[fname]
                if fs <= dline <= fe:
                    continue          # declared inside that function: fine
                if any(ref.search(code[k]) for k in range(fs, fe + 1)):
                    problems.append(
                        '%s (line %d) is read by %s(), reached from %s at line %d '
                        '- before the declaration runs'
                        % (name, dline + 1, fname, label, cline + 1))
                    break
            else:
                continue
            break
    return problems


issues = tdz_lint(src)
if issues:
    die('temporal dead zone - these throw at load and abort the rest of the script:\n'
        + '\n'.join('   ' + p for p in issues)
        + '\n   Move the value inside the function, or make it a hoisted '
          'function. Add `tdz-ok` in a comment on the line to override.')

# --- 1. inline leaflet css -------------------------------------------------
link = '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>'
if src.count(link) != 1:
    die('css link not found exactly once')
css_clean = re.sub(r'url\((images/[^)]*)\)', 'none', css)
src = src.replace(link, '<style>/* leaflet 1.9.4 */\n' + css_clean + '</style>')

# --- 2. inline leaflet js --------------------------------------------------
scr = '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
if src.count(scr) != 1:
    die('js script tag not found exactly once')
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
if not m:
    die('no </head>')
src = src[:m.start()] + head_extra + src[m.start():]

# --- 4. tiles must be CORS-enabled or the SW caches opaque, quota-padded
#        responses. OpenTopoMap sends Access-Control-Allow-Origin: *
tl_old = """L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{
  attribution:'OpenTopoMap (CC-BY-SA)',
  maxZoom:17,"""
tl_new = """L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{
  attribution:'Kartendaten: © OpenStreetMap-Mitwirkende, SRTM | Kartendarstellung: © OpenTopoMap (CC-BY-SA)',
  crossOrigin:true,          // needed so the service worker caches CORS (non-opaque) responses
  maxZoom:17,"""
if src.count(tl_old) != 1:
    die('tile layer block not matched')
src = src.replace(tl_old, tl_new)

# --- 5. append the offline block just before the closing script tag --------
idx = src.rindex('</script>')
src = src[:idx] + off + src[idx:]

# --- guard 3: the startup sentinel must survive ---------------------------
if '__hrpReady' not in src:
    die('the __hrpReady startup sentinel is missing - tests rely on it to tell '
        '"the script ran" from "the script threw but hoisted functions still exist"')

# --- write, or check ------------------------------------------------------
if CHECK:
    if not os.path.exists(OUT):
        die('index.html does not exist - run: python src/build.py')
    current = open(OUT, encoding='utf-8').read()
    if current != src:
        die('index.html is stale - it does not match src/hrp_wallon_luchon.html.\n'
            '   Run: python src/build.py   then commit both.')
    print('index.html is current (%.1f KB)' % (len(src) / 1024))
    sys.exit(0)

open(OUT, 'w', encoding='utf-8').write(src)
print('source     %8.1f KB' % (orig_len / 1024))
print('index.html %8.1f KB' % (len(src) / 1024))
print('leaflet inlined, PWA tags added, crossOrigin set, offline block appended')
print('guards passed: single source, no TDZ, sentinel present')

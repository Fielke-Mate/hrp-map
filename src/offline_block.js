
// ---------------------------------------------------------------------------
// Offline support.
//
// The page itself (route, shelters, legs, profile, GPS) is entirely
// self-contained, so once the service worker has cached this file it works with
// no signal at all - just on a blank background. The button below additionally
// pulls the OpenTopoMap tiles for a 2 km corridor along the route so the
// background is there too.
//
// Tile URLs must be generated exactly as Leaflet would request them, subdomain
// included, or the prefetched entries never match the runtime lookups.
// ---------------------------------------------------------------------------
(function(){
  if (!('serviceWorker' in navigator)) return;      // file:// or an old browser
  if (location.protocol !== 'http:' && location.protocol !== 'https:') return;

  const ZOOM_MIN = 9, BUF_KM = 2.0;
  let swReg = null, tileCount = 0, busy = false;

  const style = document.createElement('style');
  style.textContent =
    '#off-chip{background:#1a2d3f;border:1px solid #2a4060;border-radius:8px;padding:5px 10px;'
  + 'color:#7ad0f0;font-size:10.5px;font-weight:700;cursor:pointer;box-shadow:0 2px 8px #0009;'
  + 'user-select:none;text-align:center;margin-top:6px;}'
  + '#off-panel{background:#1a2d3f;border:1px solid #2a4060;border-radius:8px;padding:8px 10px;'
  + 'color:#d0e0f0;font-size:10.5px;line-height:1.6;max-width:230px;box-shadow:0 2px 8px #0009;'
  + 'margin-top:6px;display:none;}'
  + '#off-panel b{color:#7ad0f0;}'
  + '#off-panel select,#off-panel button{font:inherit;font-size:10px;background:#0f2030;'
  + 'color:#d0e0f0;border:1px solid #2a4060;border-radius:5px;padding:3px 6px;margin-top:5px;cursor:pointer;}'
  + '#off-panel button:disabled{opacity:.5;cursor:default;}'
  + '#off-bar{height:5px;background:#0f2030;border-radius:3px;margin-top:6px;overflow:hidden;display:none;}'
  + '#off-bar i{display:block;height:100%;width:0;background:#2e9bff;transition:width .2s;}'
  + '#off-note{color:#8aa4bc;font-size:9.5px;margin-top:6px;}';
  document.head.appendChild(style);

  const ctl = L.control({ position:'topright' });
  ctl.onAdd = function(){
    const wrap = L.DomUtil.create('div');
    wrap.innerHTML =
      '<div id="off-chip" title="Save the map for use with no signal">&#8681; Offline maps</div>'
    + '<div id="off-panel">'
    +   '<div id="off-status">Checking&hellip;</div>'
    +   '<div><select id="off-zoom">'
    +     '<option value="14" selected>Standard detail &middot; ~22 MB</option>'
    +     '<option value="15">High detail &middot; ~71 MB</option>'
    +   '</select></div>'
    +   '<div><button id="off-go">Download corridor</button> '
    +       '<button id="off-clear">Clear</button></div>'
    +   '<div id="off-bar"><i></i></div>'
    +   '<div id="off-note">Do this on wifi. Then <b>Add to Home Screen</b> &mdash; '
    +     'iOS clears the cache of sites that are only bookmarked.</div>'
    + '</div>';
    L.DomEvent.disableClickPropagation(wrap);
    return wrap;
  };
  ctl.addTo(map);

  const chip   = document.getElementById('off-chip');
  const panel  = document.getElementById('off-panel');
  const status = document.getElementById('off-status');
  const bar    = document.getElementById('off-bar');
  const barIn  = bar.firstChild;
  const goBtn  = document.getElementById('off-go');
  const clrBtn = document.getElementById('off-clear');

  chip.addEventListener('click', function(){
    const open = panel.style.display === 'block';
    panel.style.display = open ? 'none' : 'block';
    if (!open) refresh();
  });

  function setStatus(){
    const stored = tileCount > 0
      ? '<b>' + tileCount.toLocaleString() + '</b> tiles stored'
      : 'No tiles stored yet';
    status.innerHTML = (navigator.onLine ? 'Online' : '<b>Offline</b>') + ' &middot; ' + stored
      + '<br>Page itself: <b>' + (swReg ? 'available offline' : 'not cached yet') + '</b>';
  }

  function refresh(){
    setStatus();
    if (navigator.serviceWorker.controller){
      navigator.serviceWorker.controller.postMessage({ type:'TILE_STATS' });
    }
    if (navigator.storage && navigator.storage.estimate){
      navigator.storage.estimate().then(function(est){
        if (!est || !est.usage) return;
        const mb = (est.usage/1048576).toFixed(0);
        const quota = est.quota ? (est.quota/1048576).toFixed(0) : null;
        status.innerHTML += '<br>Using <b>' + mb + ' MB</b>'
                          + (quota ? ' of ~' + quota + ' MB allowed' : '');
      });
    }
  }

  // --- tile maths, mirroring Leaflet -------------------------------------
  function lon2x(lon, z){ return Math.floor((lon+180)/360 * Math.pow(2,z)); }
  function lat2y(lat, z){
    const r = lat*Math.PI/180;
    return Math.floor((1 - Math.log(Math.tan(r) + 1/Math.cos(r))/Math.PI)/2 * Math.pow(2,z));
  }
  function corridorTiles(zMax){
    const seen = new Set(), urls = [];
    // Everything the map can show, not just the walking track.
    let pts = TRACK.map(function(p){ return [p[0],p[1]]; });
    [ typeof BUS965_ROUTE !== 'undefined' ? BUS965_ROUTE : null,
      typeof BUS_ROUTE    !== 'undefined' ? BUS_ROUTE    : null ].forEach(function(r){
      if (r) pts = pts.concat(r.map(function(p){ return [p[0],p[1]]; }));
    });
    for (let z = ZOOM_MIN; z <= zMax; z++){
      for (let i = 0; i < pts.length; i++){
        const lat = pts[i][0], lon = pts[i][1];
        const dlat = BUF_KM/111.0;
        const dlon = BUF_KM/(111.0*Math.cos(lat*Math.PI/180));
        const x0 = lon2x(lon-dlon, z), x1 = lon2x(lon+dlon, z);
        const y0 = lat2y(lat+dlat, z), y1 = lat2y(lat-dlat, z);
        for (let x = x0; x <= x1; x++){
          for (let y = y0; y <= y1; y++){
            const key = z+'/'+x+'/'+y;
            if (seen.has(key)) continue;
            seen.add(key);
            // Leaflet: subdomains[abs(x+y) % 3]
            const s = 'abc'.charAt(Math.abs(x+y) % 3);
            urls.push('https://'+s+'.tile.opentopomap.org/'+z+'/'+x+'/'+y+'.png');
          }
        }
      }
    }
    return urls;
  }

  goBtn.addEventListener('click', function(){
    if (busy) return;
    if (!navigator.serviceWorker.controller){
      status.innerHTML = 'Service worker not ready yet &mdash; reload the page and try again.';
      return;
    }
    const zMax = parseInt(document.getElementById('off-zoom').value, 10);
    const urls = corridorTiles(zMax);
    busy = true; goBtn.disabled = true; clrBtn.disabled = true;
    bar.style.display = 'block'; barIn.style.width = '0';
    status.innerHTML = 'Downloading <b>0</b> / ' + urls.length.toLocaleString() + ' tiles&hellip;';
    navigator.serviceWorker.controller.postMessage({ type:'TILE_PREFETCH', urls: urls });
  });

  clrBtn.addEventListener('click', function(){
    if (busy || !navigator.serviceWorker.controller) return;
    navigator.serviceWorker.controller.postMessage({ type:'TILE_CLEAR' });
  });

  navigator.serviceWorker.addEventListener('message', function(e){
    const m = e.data || {};
    if (m.type === 'TILE_STATS'){ tileCount = m.count; setStatus(); }
    if (m.type === 'TILE_PROGRESS'){
      barIn.style.width = (100*m.done/m.total).toFixed(1) + '%';
      status.innerHTML = 'Downloading <b>' + m.done.toLocaleString() + '</b> / '
                       + m.total.toLocaleString() + ' tiles&hellip;';
    }
    if (m.type === 'TILE_DONE'){
      busy = false; goBtn.disabled = false; clrBtn.disabled = false;
      bar.style.display = 'none';
      tileCount = m.count;
      setStatus();
      status.innerHTML += '<br>Added <b>' + m.added.toLocaleString() + '</b>'
                        + (m.failed ? ', <b>' + m.failed + '</b> failed' : '') + '.';
    }
  });

  window.addEventListener('online',  setStatus);
  window.addEventListener('offline', setStatus);

  navigator.serviceWorker.register('./sw.js').then(function(reg){
    swReg = reg;
    return navigator.serviceWorker.ready;
  }).then(function(){
    refresh();
  }).catch(function(err){
    status.innerHTML = 'Offline support unavailable: ' + err.message;
  });
})();

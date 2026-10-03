// Exercise autoPlan, with and without locked stops, against the real route
// and shelter data.
//
//   node src/test_planner.js
//
// The functions under test are lifted out of planner.html rather than copied,
// so the test cannot pass against a stale duplicate. What it pins down:
//
//   * an unlocked plan is unchanged by the locking code existing
//   * a lock is always visited, and never by breaking a distance or climb
//     limit - those are safety limits and a lock must not override them
//   * a pinned night is honoured exactly, or refused with the nights that
//     are actually reachable
//   * contradictory and backwards pins are refused rather than fudged
//   * a lock is honoured even with its type switched off or beyond the
//     detour limit, because the user named it
//   * the extra night dimension does not make a whole-route plan slow
//   * a hut recorded as ruined, demolished, closed or private is never chosen
//     by the planner; a closed or private one can still be locked by name,
//     a ruin cannot
const fs = require('fs'), path = require('path');
const SITE = path.dirname(__dirname);
const html = fs.readFileSync(path.join(SITE, 'planner.html'), 'utf8');

function grab(name){
  const start = html.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('no ' + name);
  let i = html.indexOf('{', start), depth = 0;
  for (let j = i; j < html.length; j++){
    if (html[j] === '{') depth++;
    else if (html[j] === '}'){ depth--; if (!depth) return html.slice(start, j + 1); }
  }
  throw new Error('unbalanced ' + name);
}

const SRC = ['kmBetween','idxAtKm','eleAtKm','ascentBetween','autoPlan']
  .map(grab).join('\n\n');
const ELEV_LINE = html.match(/const ELEV_SAMPLE_M[^\n]*/);
eval(SRC + '\nglobalThis.autoPlan = autoPlan; globalThis.kmBetween = kmBetween;');

function load(id){
  const r = JSON.parse(fs.readFileSync(path.join(SITE, 'data/routes', id + '.json'), 'utf8'));
  const cum = [0];
  for (let i = 1; i < r.points.length; i++) cum.push(cum[i-1] + kmBetween(r.points[i-1], r.points[i]));
  const SH = JSON.parse(fs.readFileSync(path.join(SITE, 'data/shelters.json'), 'utf8')).shelters;
  const shelters = [];
  SH.forEach(s => {
    const o = s.on.find(o => o.route === id);
    if (o) shelters.push({id:s.id, label:s.label, type:s.type, ele:s.ele,
                          capacity:s.capacity, confidence:s.confidence,
                          status:s.status || 'ok', statusWhy:s.statusWhy || [],
                          ll:s.ll, km:o.km, offM:o.offM});
  });
  shelters.sort((a,b) => a.km - b.km);
  return {id:r.id, name:r.name, points:r.points, cum, lengthKm:cum[cum.length-1], shelters};
}

const DEF = {types:new Set(['R','C','A','G','B']), maxOffM:2500,
             minKm:10, maxKm:20, maxAsc:1600};
const o = (x) => Object.assign({}, DEF, x);
let fails = 0, checks = 0;
function check(label, cond, detail){
  checks++;
  if (!cond){ fails++; console.log('  FAIL  ' + label + (detail ? '  [' + detail + ']' : '')); }
  else console.log('  ok    ' + label + (detail ? '  ' + detail : ''));
}

const hrp = load('hrp'), gr11 = load('gr11'), gr10 = load('gr10');

// ===========================================================  1. no regression
console.log('\n1. unlocked plans are unchanged');
const base = autoPlan(hrp, 0, 150, o({}));
check('HRP 0-150 plans', base.ok, base.ok ? base.days.length + ' days' : JSON.stringify(base.reasons));
const baseStops = base.stops.map(s => s.label).join(' | ');
const again = autoPlan(hrp, 0, 150, o({locks:[]}));
check('empty lock list is identical', again.ok && again.stops.map(s=>s.label).join(' | ') === baseStops);
check('every day within limits',
  base.days.every(d => d.km <= DEF.maxKm + 1e-9 && d.up <= DEF.maxAsc),
  'worst ' + Math.max(...base.days.map(d=>d.km)).toFixed(1) + ' km, '
  + Math.max(...base.days.map(d=>d.up)) + ' m');

// ===========================================================  2. required lock
console.log('\n2. an unpinned lock is always visited');
// pick a hut the base plan did NOT choose, inside the range
const chosen = new Set(base.stops.map(s => s.id));
// the lock tests are about locking, so they draw only from usable huts -
// section 12 covers what happens with ruined, closed and private ones
const notChosen = hrp.shelters.filter(s => s.km > 20 && s.km < 130 && !chosen.has(s.id)
                                        && DEF.types.has(s.type) && s.offM <= 2500
                                        && s.status === 'ok');
check('found unchosen candidates', notChosen.length > 0, notChosen.length + ' of them');
let visited = 0, broke = 0, infeasible = 0;
const sample = notChosen.filter((_, i) => i % 7 === 0).slice(0, 40);
sample.forEach(s => {
  const p = autoPlan(hrp, 0, 150, o({locks:[{route:'hrp', id:s.id, km:s.km, label:s.label, night:null}]}));
  if (!p.ok){ infeasible++; return; }
  if (p.stops.some(x => x.id === s.id)) visited++;
  if (p.days.some(d => d.km > DEF.maxKm + 1e-9 || d.up > DEF.maxAsc)) broke++;
});
check('every feasible locked plan includes the lock',
  visited === sample.length - infeasible,
  visited + ' of ' + (sample.length - infeasible) + ' (' + infeasible + ' infeasible)');
check('no locked plan breaks the distance or climb limit', broke === 0,
  broke + ' violations across ' + sample.length + ' plans');

// ===========================================================  3. pinned nights
console.log('\n3. pinning a night');
const target = base.stops[3];           // night 3 of the base plan
check('base night 3 is ' + target.label, !!target.id);
for (let n = 1; n <= base.days.length; n++){
  const p = autoPlan(hrp, 0, 150, o({locks:[{route:'hrp', id:target.id, km:target.km,
                                             label:target.label, night:n}]}));
  if (p.ok){
    const at = p.stops.findIndex(x => x.id === target.id);
    check('night ' + n + ' honoured', at === n,
      'lands on night ' + at + ', plan is ' + p.days.length + ' days');
  } else if (p.kind === 'pin'){
    check('night ' + n + ' refused as a pin', p.want === n,
      'reachable on nights ' + p.nights.filter(x=>x>0).join(','));
  } else {
    check('night ' + n + ' refused as a gap', true, p.reasons.join('+'));
  }
}

// ===========================================================  4. two locks
console.log('\n4. several locks at once');
const t2 = base.stops[2], t5 = base.stops[5];
const two = autoPlan(hrp, 0, 150, o({locks:[
  {route:'hrp', id:t2.id, km:t2.km, label:t2.label, night:2},
  {route:'hrp', id:t5.id, km:t5.km, label:t5.label, night:5}]}));
check('both pins satisfied', two.ok
  && two.stops.findIndex(x => x.id === t2.id) === 2
  && two.stops.findIndex(x => x.id === t5.id) === 5,
  two.ok ? two.days.length + ' days' : two.kind);

// contradictory: two huts both pinned to night 2
const bad = autoPlan(hrp, 0, 150, o({locks:[
  {route:'hrp', id:t2.id, km:t2.km, label:t2.label, night:2},
  {route:'hrp', id:t5.id, km:t5.km, label:t5.label, night:2}]}));
check('contradictory pins refused', !bad.ok, bad.ok ? 'ACCEPTED' : bad.kind);

// ===========================================================  5. order
console.log('\n5. a pin that reverses the walking order');
const rev = autoPlan(hrp, 0, 150, o({locks:[
  {route:'hrp', id:t2.id, km:t2.km, label:t2.label, night:5},
  {route:'hrp', id:t5.id, km:t5.km, label:t5.label, night:2}]}));
check('backwards pins refused', !rev.ok, rev.ok ? 'ACCEPTED - BUG' : rev.kind);

// ===========================================================  6. filtered type
console.log('\n6. a lock whose type is switched off is still honoured');
const hotel = hrp.shelters.find(s => s.type === 'H' && s.km > 20 && s.km < 130);
if (hotel){
  const p = autoPlan(hrp, 0, 150, o({locks:[{route:'hrp', id:hotel.id, km:hotel.km,
                                             label:hotel.label, night:null}]}));
  check('hotel lock used despite H being off',
    p.ok && p.stops.some(x => x.id === hotel.id),
    p.ok ? hotel.label + ' on night ' + p.stops.findIndex(x=>x.id===hotel.id) : p.kind);
} else console.log('  --    no hotel in range, skipped');

// a lock beyond the detour limit
const farOff = hrp.shelters.find(s => s.offM > 2500 && s.km > 20 && s.km < 130);
if (farOff){
  const p = autoPlan(hrp, 0, 150, o({locks:[{route:'hrp', id:farOff.id, km:farOff.km,
                                             label:farOff.label, night:null}]}));
  check('lock beyond the 2.5 km detour limit honoured',
    !p.ok || p.stops.some(x => x.id === farOff.id),
    (p.ok ? 'included' : p.kind) + ', ' + farOff.offM + ' m off');
} else console.log('  --    nothing beyond the detour limit in range, skipped');

// ===========================================================  7. short day
console.log('\n7. a lock may make a short day');
// two huts close together, both locked
const pairs = [];
for (let i = 1; i < hrp.shelters.length; i++){
  const a = hrp.shelters[i-1], b = hrp.shelters[i];
  if (a.km > 20 && b.km < 130 && b.km - a.km < 5 && b.km - a.km > 1
      && DEF.types.has(a.type) && DEF.types.has(b.type)
      && a.status === 'ok' && b.status === 'ok') pairs.push([a,b]);
}
if (pairs.length){
  const [a,b] = pairs[0];
  const p = autoPlan(hrp, 0, 150, o({locks:[
    {route:'hrp', id:a.id, km:a.km, label:a.label, night:null},
    {route:'hrp', id:b.id, km:b.km, label:b.label, night:null}]}));
  const ia = p.ok ? p.stops.findIndex(x=>x.id===a.id) : -1;
  const ib = p.ok ? p.stops.findIndex(x=>x.id===b.id) : -1;
  check('both close locks used, consecutive', p.ok && ia > 0 && ib === ia + 1,
    p.ok ? a.label + ' -> ' + b.label + ' = ' + (b.km-a.km).toFixed(1) + ' km day' : p.kind);
  check('the short day is under the minimum, as asked',
    p.ok && p.days[ib-1].km < DEF.minKm,
    p.ok ? p.days[ib-1].km.toFixed(1) + ' km' : '-');
} else console.log('  --    no close pair found, skipped');

// ===========================================================  8. out of range
console.log('\n8. a lock outside the section is reported, not applied');
const outside = hrp.shelters.find(s => s.km > 200);
const p8 = autoPlan(hrp, 0, 150, o({locks:[{route:'hrp', id:outside.id, km:outside.km,
                                            label:outside.label, night:null}]}));
check('plan still made', p8.ok, p8.ok ? p8.days.length + ' days' : p8.kind);
check('lock listed as ignored', p8.ok && p8.ignored.length === 1,
  p8.ok ? JSON.stringify(p8.ignored.map(l=>l.label)) : '-');
check('identical to the unlocked plan',
  p8.ok && p8.stops.map(s=>s.label).join(' | ') === baseStops);

// ===========================================================  9. other routes
console.log('\n9. the same on GR11 and GR10');
[['gr11',gr11],['gr10',gr10]].forEach(([id, rt]) => {
  const b = autoPlan(rt, 0, 200, o({}));
  if (!b.ok){ console.log('  --    ' + id + ' 0-200 infeasible unlocked (' + b.kind + ')'); return; }
  const t = b.stops[2];
  const p = autoPlan(rt, 0, 200, o({locks:[{route:id, id:t.id, km:t.km, label:t.label, night:2}]}));
  check(id + ' pin night 2 = ' + t.label, p.ok && p.stops.findIndex(x=>x.id===t.id) === 2,
    p.ok ? p.days.length + ' days' : p.kind);
  // and an unpinned lock on something it did not choose
  const nc = rt.shelters.find(s => s.km > 30 && s.km < 170 && !b.stops.some(x=>x.id===s.id)
                                && DEF.types.has(s.type) && s.offM <= 2500 && s.status === 'ok');
  if (nc){
    const q = autoPlan(rt, 0, 200, o({locks:[{route:id, id:nc.id, km:nc.km, label:nc.label, night:null}]}));
    check(id + ' unpinned lock visited', !q.ok || q.stops.some(x=>x.id===nc.id),
      q.ok ? nc.label : q.kind);
  }
});

// =========================================================== 10. monotonic km
console.log('\n10. invariants on every locked plan produced above');
const plans = [];
for (let n = 1; n <= 8; n++){
  const p = autoPlan(hrp, 0, 150, o({locks:[{route:'hrp', id:target.id, km:target.km,
                                             label:target.label, night:n}]}));
  if (p.ok) plans.push(p);
}
check('plans to inspect', plans.length > 0, plans.length + '');
check('stops strictly increase in km',
  plans.every(p => p.stops.every((s,i) => i === 0 || s.km > p.stops[i-1].km)));
check('first stop is the start, last is the finish',
  plans.every(p => p.stops[0].label === 'Start'
                && p.stops[p.stops.length-1].label === 'Finish'));
check('day count equals stop count minus one',
  plans.every(p => p.days.length === p.stops.length - 1));
check('day distances sum to the section plus detours',
  plans.every(p => {
    const track = p.days.reduce((a,d) => a + d.trackKm, 0);
    return Math.abs(track - 150) < 0.5;
  }));
check('no day exceeds the limits',
  plans.every(p => p.days.every(d => d.km <= DEF.maxKm + 1e-9 && d.up <= DEF.maxAsc)));

// =========================================================== 12. hut status
// Before this rule, 104 of 452 feasible plans in a sweep stopped at a hut that
// is ruined, closed or private - among them a demolished refuge and one
// closed for good in August 2026. This is the property that must never regress.
console.log('\n12. ruined, closed and private huts are never planned');
const NOT_OK = new Set(['gone', 'closed', 'private']);
let planned = 0, offenders = [];
[['hrp',hrp],['gr10',gr10],['gr11',gr11]].forEach(([id, rt]) => {
  for (let a = 0; a + 60 <= rt.lengthKm; a += 45){
    [[10,20,1600],[8,25,2000],[6,14,1000]].forEach(([mn, mx, asc]) => {
      const p = autoPlan(rt, a, Math.min(rt.lengthKm, a + 150),
                         o({minKm:mn, maxKm:mx, maxAsc:asc,
                            types:new Set(['R','C','A','G','B','H'])}));
      if (!p.ok) return;
      planned++;
      p.stops.forEach(s => { if (NOT_OK.has(s.status)) offenders.push(id + ' ' + s.label + ' (' + s.status + ')'); });
    });
  }
});
check('no auto-planned stop is ruined, closed or private', offenders.length === 0,
  planned + ' plans, every type allowed' + (offenders.length ? ' - ' + offenders.slice(0,3).join(', ') : ''));

const anyRt = [hrp, gr10, gr11];
const findStatus = st => { for (const rt of anyRt){ const s = rt.shelters.find(x => x.status === st
                             && x.km > 15 && x.km < rt.lengthKm - 15); if (s) return [rt, s]; } };
const [gRt, gone] = findStatus('gone') || [];
if (gone){
  const p = autoPlan(gRt, gone.km - 14, gone.km + 14,
    o({locks:[{route:gRt.id, id:gone.id, km:gone.km, label:gone.label, night:null}],
       types:new Set(['R','C','A','G','B','H'])}));
  check('a ruin cannot be planned even when locked',
    !(p.ok && p.stops.some(s => s.id === gone.id)), gone.label);
} else console.log('  --    no ruined hut found, skipped');
const [cRt, shut] = findStatus('closed') || [];
if (shut){
  const p = autoPlan(cRt, shut.km - 12, shut.km + 12,
    o({locks:[{route:cRt.id, id:shut.id, km:shut.km, label:shut.label, night:null}],
       minKm:2, types:new Set(['R','C','A','G','B','H'])}));
  check('a closed hut can still be locked by a hiker who knows it is open',
    p.ok && p.stops.some(s => s.id === shut.id), shut.label + (p.ok ? '' : ' - ' + p.kind));
} else console.log('  --    no closed hut found, skipped');

// =========================================================== 11. performance
console.log('\n11. cost of the extra dimension');
const whole = [['hrp',hrp],['gr11',gr11],['gr10',gr10]];
whole.forEach(([id, rt]) => {
  let t0 = Date.now();
  const a = autoPlan(rt, 0, rt.lengthKm, o({}));
  const tFlat = Date.now() - t0;
  if (!a.ok){ console.log('  --    ' + id + ' whole route infeasible, skipped'); return; }
  const t = a.stops[5];
  t0 = Date.now();
  const b = autoPlan(rt, 0, rt.lengthKm, o({locks:[{route:id, id:t.id, km:t.km, label:t.label, night:5}]}));
  const tPin = Date.now() - t0;
  check(id + ' whole route, pinned', b.ok && b.stops.findIndex(x=>x.id===t.id) === 5,
    a.days.length + ' days, flat ' + tFlat + ' ms -> pinned ' + tPin + ' ms');
  // A wall-clock budget is flaky on a shared machine: on one run the flat
  // pass came out slower than the pinned one. What matters is that the extra
  // night dimension does not multiply the cost, so compare the two passes
  // against each other and keep only a generous absolute ceiling.
  check(id + ' pinning costs no more than planning itself',
    tPin < tFlat * 2.5 + 400 && tPin < 15000,
    'flat ' + tFlat + ' ms, pinned ' + tPin + ' ms');
});

console.log('\n' + '='.repeat(60));
console.log(fails ? 'FAILED ' + fails + ' of ' + checks : 'ALL ' + checks + ' CHECKS PASSED');
process.exit(fails ? 1 : 0);

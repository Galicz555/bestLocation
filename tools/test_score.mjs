// Self-check for the scoring math in app/score.js, run against the REAL app/config.js —
// no framework, no stubs, no browser. Both are classic scripts, so we evaluate them
// inside one Function body and hand back the bindings we want to assert on.
//
//   node tools/test_score.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const APP = join(dirname(fileURLToPath(import.meta.url)), '..', 'app');
const src = f => readFileSync(join(APP, f), 'utf8');
// lang.js reads localStorage and navigator.language at load: an empty store is a first visit,
// and the suite runs as a Hungarian browser unless a test passes another language.
const load = (language = 'hu-HU') => new Function('localStorage', 'navigator',
  src('lang.js') + '\n' + src('config.js') + '\n' + src('score.js') +
  '\nreturn {METRICS,FILTERS,UI,HU,percentiles,score,passes,valueResidual,summarize,kf,costOf,lowTx,LOW_TX,' +
  'setPct:v=>{pct=v},getPct:()=>pct,setLang:v=>{LANG=v},getLang:()=>LANG};')({getItem: () => null}, {language});

// Only these metrics are on, so an expected score can be computed by hand.
const only = (S, weights) => {
  for (const m of S.METRICS) m.w = weights[m.k] || 0;
};
const rows = n => Array.from({length: n}, (_, i) => ({ksh: String(i), garden_score: i}));
let checks = 0;
const ok = (label, fn) => { fn(); checks++; console.log('  ok  ' + label); };

// --- percentiles ------------------------------------------------------------
ok('rank percentile spans 0..1 and is order-preserving', () => {
  const S = load();
  const p = S.percentiles(rows(101))['garden_score'];
  assert.equal(p(0), 0, 'lowest value must sit at 0');
  assert.equal(p(100), 1, 'highest value must sit at 1');
  assert.ok(p(50) > p(49) && p(51) > p(50), 'must be monotonic');
});

ok('a reversed direction inverts the percentile', () => {
  const S = load();
  const m = S.METRICS.find(m => m.k === 'garden_score');
  const before = [0, 50, 100].map(S.percentiles(rows(101))['garden_score']);
  m.dir = -m.dir;
  const after = [0, 50, 100].map(S.percentiles(rows(101))['garden_score']);
  before.forEach((v, i) => assert.equal(after[i], 1 - v, 'flipping dir must flip the ranking'));
});

ok('a tied block takes its MIDrank, not the rank of its lowest member', () => {
  // The fixture is shaped like real data: school_beats_prediction has 428 of its 549 values
  // tied at the floor, and it is on by default. Lower-bound ranking scored that whole block
  // 0.0 — indistinguishable from being genuinely worst. Every other fixture here is
  // all-distinct, which is precisely why the suite could not see this.
  const S = load();
  const tied = Array.from({length: 60}, () => ({garden_score: 0}));
  const rest = Array.from({length: 40}, (_, i) => ({garden_score: 1 + i}));
  const p = S.percentiles([...tied, ...rest])['garden_score'];
  assert.ok(p(0) > 0.2 && p(0) < 0.4, `a 60% floor-tie must land mid-rank, got ${p(0)}`);
  assert.ok(p(1) > p(0), 'the value just above the tie must still outrank it');
});

ok('a tie is direction-symmetric: flipping dir mirrors it exactly', () => {
  // Under lower-bound ranking a tied block sat at the pessimistic end for dir:+1 and the
  // optimistic end for dir:-1, so reversing a direction was not a clean mirror.
  const S = load();
  const m = S.METRICS.find(m => m.k === 'garden_score');
  const data = [...Array.from({length: 30}, () => ({garden_score: 5})),
                ...Array.from({length: 10}, (_, i) => ({garden_score: 10 + i}))];
  const up = S.percentiles(data)['garden_score'](5);
  m.dir = -m.dir;
  const down = S.percentiles(data)['garden_score'](5);
  assert.ok(Math.abs((1 - up) - down) < 1e-12, `dir flip must mirror a tie: ${up} vs ${down}`);
});

ok('a column with no spread abstains from ranking rather than inventing one', () => {
  // One row in scope (a tight radius around a remote anchor), or a column where every
  // settlement shares a value, carries no rank information. Ranking it 0 or 1 by direction
  // would hand an arbitrary score to whoever is left.
  const S = load();
  assert.equal(S.percentiles([{garden_score: 42}])['garden_score'](42), 0.5,
    'a single row cannot be ranked against itself');
  assert.equal(S.percentiles(rows(1).concat(rows(1)))['garden_score'](0), 0.5,
    'an all-constant column must sit neutral, not at an end');
});

ok('a percentile closure reads m.dir LIVE, so a stale pct changes meaning', () => {
  // Not a bug — app.js rebuilds pct on every direction toggle — but it is load-bearing:
  // the closure captures the metric object, not a copy of dir. If a future change flips a
  // direction without rebuilding pct, every score silently inverts with no error. This
  // check exists so that change fails here instead of in the field.
  const S = load();
  const m = S.METRICS.find(m => m.k === 'garden_score');
  const p = S.percentiles(rows(101))['garden_score'];
  const top = p(100);
  m.dir = -m.dir;
  assert.equal(p(100), 1 - top, 'the already-built closure follows the live dir');
});

ok('missing, non-numeric and infinite values return null, never 0', () => {
  const S = load();
  const p = S.percentiles(rows(20))['garden_score'];
  for (const bad of [null, undefined, NaN, Infinity, 'nyolc', {}])
    assert.equal(p(bad), null, `${String(bad)} must abstain, not score`);
});

ok('percentiles survive an all-missing column', () => {
  const S = load();
  const p = S.percentiles([{garden_score: null}, {garden_score: null}])['garden_score'];
  assert.equal(p(5), null, 'no data at all must not throw or fabricate a rank');
});

// --- score ------------------------------------------------------------------
ok('score is a weighted MEAN, so it is invariant to the weight scale', () => {
  const S = load();
  const data = rows(50);
  data.forEach(r => { r.pop_trend_21y_pct = r.garden_score; });
  const at = w => {
    only(S, {garden_score: w, pop_trend_21y_pct: w});
    S.setPct(S.percentiles(data));
    return S.score(data[40]);
  };
  // This is what makes the 0-10 sliders safe: x1/x1 and x10/x10 must agree.
  assert.ok(Math.abs(at(1) - at(10)) < 1e-12, 'scaling every weight must not move the score');
});

ok('a missing metric abstains from the mean instead of scoring zero', () => {
  const S = load();
  const data = rows(50);
  data.forEach(r => { r.pop_trend_21y_pct = r.garden_score; });
  only(S, {garden_score: 1, pop_trend_21y_pct: 1});
  S.setPct(S.percentiles(data));
  const full = S.score(data[49]);                       // best on both metrics
  const half = S.score({...data[49], pop_trend_21y_pct: null});
  assert.equal(full, 1, 'top of both metrics should be a perfect 1');
  assert.equal(half, 1, 'losing a metric must not halve the score — it must abstain');
});

ok('every weight off scores 0 rather than dividing by zero', () => {
  const S = load();
  const data = rows(20);
  only(S, {});
  S.setPct(S.percentiles(data));
  assert.equal(S.score(data[10]), 0);
  assert.ok(Number.isFinite(S.score(data[10])), 'must never be NaN');
});

// --- passes -----------------------------------------------------------------
ok('the budget filter reads UI.size-derived cost and rejects unpriced rows', () => {
  const S = load();
  for (const f of S.FILTERS) f.on = f.k === 'budget';
  S.UI.budget = 100; S.UI.size = 100;
  assert.equal(S.passes({house_price_m2: 900}), true, '100 m² x 900 eFt = 90 M Ft fits');
  assert.equal(S.passes({house_price_m2: 1100}), false, '110 M Ft does not');
  assert.equal(S.passes({house_price_m2: null}), false, 'no price must not silently pass the budget');
});

// --- property type (UI.kind) --------------------------------------------------
// Budapest inner districts are the real shape: flats priced, houses not.
const district = {house_price_m2: null, house_tx: null, house_price_year: null,
  flat_price_m2: 1196, flat_tx: 1155, flat_price_year: 2024};
const village = {house_price_m2: 161, house_tx: 3, house_price_year: 2024};

ok('kind switch: price metric, cost and year all read the chosen family', () => {
  const S = load();
  const price = S.METRICS.find(m => m.k === 'house_price_m2');
  assert.equal(S.UI.kind, 'house', 'default must stay house — today\'s behaviour');
  assert.equal(price.get(district), null, 'a district has no house price');
  assert.equal(S.costOf(district), null);
  S.UI.kind = 'flat';
  assert.equal(price.get(district), 1196, 'the same metric reads flat_price_m2 in flat mode');
  assert.equal(S.costOf(district), 1196 * S.UI.size / 1000);
  assert.equal(S.kf(district, 'price_year'), 2024);
  assert.equal(price.get(village), undefined, 'and a house-only village abstains in flat mode');
  const f = S.FILTERS.find(f => f.k === 'priced');
  assert.equal(f.f(district), true, 'the recent-price filter follows the kind too');
});

ok('budget filter follows the kind', () => {
  const S = load();
  for (const f of S.FILTERS) f.on = f.k === 'budget';
  S.UI.budget = 200;
  assert.equal(S.passes(district), false, 'house mode: an unpriced district fails the budget');
  S.UI.kind = 'flat';
  assert.equal(S.passes(district), true, 'flat mode: 120 m² x 1196 eFt = 143.5 M Ft fits 200');
  S.UI.budget = 140;
  assert.equal(S.passes(district), false, 'and still honours the budget');
});

ok('low-sales marking: under LOW_TX is thin, at LOW_TX is not, no price is not marked', () => {
  const S = load();
  assert.equal(S.LOW_TX, 10);
  assert.equal(S.lowTx({house_price_m2: 500, house_tx: 9}), true);
  assert.equal(S.lowTx({house_price_m2: 500, house_tx: 10}), false, 'the threshold is inclusive');
  assert.equal(S.lowTx({house_price_m2: 500}), true, 'an unknown count is not a reliable price');
  assert.equal(S.lowTx({house_price_m2: null, house_tx: 2}), false, 'nothing shown, nothing to mark');
  assert.equal(S.lowTx(village), true);
  S.UI.kind = 'flat';
  assert.equal(S.lowTx(district), false, 'flat mode reads flat_tx');
  const rel = S.FILTERS.find(f => f.k === 'reliable');
  assert.equal(rel.on, false, 'the reliable-price filter is off by default');
  assert.equal(rel.f(district), true);
  assert.equal(rel.f({flat_price_m2: 800, flat_tx: 9}), false);
});

ok('a settlement passes when every filter is off', () => {
  const S = load();
  for (const f of S.FILTERS) f.on = false;
  assert.equal(S.passes({}), true, 'no active filter must exclude nothing');
});

// --- valueResidual ----------------------------------------------------------
ok('value fit abstains below 12 priced rows', () => {
  const S = load();
  const few = Array.from({length: 11}, (_, i) => ({house_price_m2: 300 + i, _s: 0.5}));
  assert.equal(S.valueResidual(few), null, 'too few points must return null, not a fit');
  assert.ok(few.every(r => r._v === null), 'and must leave every _v cleared');
});

ok('value ranks a cheap high-scorer above an expensive one', () => {
  const S = load();
  // score rises with price, plus one bargain that beats the line
  const data = Array.from({length: 30}, (_, i) => ({house_price_m2: 200 + i * 20, _s: 0.3 + i * 0.02}));
  const bargain = {house_price_m2: 220, _s: 0.85};
  const fit = S.valueResidual([...data, bargain]);
  assert.ok(fit && fit.n === 31, 'should fit all 31 priced rows');
  assert.ok(fit.b > 0, 'score should correlate with price in this fixture');
  assert.equal(bargain._v, 1, 'the cheap high-scorer must rank top on value');
  assert.ok(bargain._resid > 0, 'and sit above the fitted line');
});

ok('value fit reads the chosen kind\'s price', () => {
  const S = load(); S.UI.kind = 'flat';
  const data = Array.from({length: 20}, (_, i) => ({flat_price_m2: 400 + i * 10, _s: 0.4 + i * 0.01}));
  assert.equal(S.valueResidual(data)?.n, 20, 'flat mode must fit on flat_price_m2');
  S.UI.kind = 'house';
  assert.equal(S.valueResidual(data), null, 'house mode finds no priced rows in the same data');
});

ok('unpriced rows are cleared, not ranked', () => {
  const S = load();
  const data = Array.from({length: 20}, (_, i) => ({house_price_m2: 200 + i * 10, _s: 0.4 + i * 0.01}));
  const noPrice = {house_price_m2: null, _s: 0.9};
  S.valueResidual([...data, noPrice]);
  assert.equal(noPrice._v, null, 'a settlement with no price must not get a value rank');
  assert.equal(noPrice._resid, null);
});

// --- summarize --------------------------------------------------------------
// 101 rows where price rises and winter PM2.5 rises with i; only those two metrics are on.
// The probe row is the cheapest (a strength) and the smoggiest (a weakness) in scope.
const sumScope = S => {
  only(S, {house_price_m2: 2, pm25_winter: 1});
  S.setPct(S.percentiles(Array.from({length: 101},
    (_, i) => ({house_price_m2: 200 + i, pm25_winter: 10 + i / 10}))));
};
const probe = {pop_2022: 2345, pop_trend_21y_pct: 12.4, commute_best_min: 42,
  house_price_m2: 200, house_price_year: 2024, pm25_winter: 20, frost_risk: 70};

ok('summary: a well-covered row reads as facts, strengths, weaknesses and flags', () => {
  const S = load(); sumScope(S);
  const txt = S.summarize(probe, 'Budapest', 90), H = S.HU;
  assert.ok(txt.length > 80, `expected a real summary, got "${txt}"`);
  for (const bit of ['2345 lakos', '+12%', '42\u00a0perc', 'Budapest', '24\u00a0M\u00a0Ft', H.sum_frost])
    assert.ok(txt.includes(bit), `missing "${bit}" in: ${txt}`);
  assert.ok(!/undefined|null|NaN/.test(txt), `leaked a missing value: ${txt}`);
});

ok('summary: direction is respected — a cheap price is a strength, high PM2.5 a weakness', () => {
  const S = load(); sumScope(S);
  const H = S.HU, txt = S.summarize(probe, 'Budapest', 90);
  const at = s => txt.indexOf(s);
  assert.ok(at(H.sum_s1) >= 0 && at(H.sum_s1) < at(H.lo_house_price_m2), `cheap must be a strength: ${txt}`);
  assert.ok(at(H.sum_w1) > at(H.lo_house_price_m2) && at(H.hi_pm25_winter) > at(H.sum_w1),
    `smog must be a weakness: ${txt}`);
  // flip price: the same cheap row becomes a weakness, and is STILL described as cheap
  S.METRICS.find(m => m.k === 'house_price_m2').dir = 1;
  const flipped = S.summarize(probe, 'Budapest', 90);
  assert.ok(flipped.includes(H.sum_wN) && flipped.includes(H.lo_house_price_m2)
    && !flipped.includes(H.sum_s1), `a flipped direction must not relabel the value: ${flipped}`);
});

ok('summary: missing values abstain — no clause, no placeholder, no relative claim', () => {
  const S = load(); sumScope(S);
  const H = S.HU;
  const thin = S.summarize({pm25_winter: 20, house_price_m2: null, frost_risk: null}, 'Budapest', 90);
  assert.ok(!thin.includes('M Ft') && !thin.includes(H.lo_house_price_m2) && !thin.includes('lakos'),
    `a null price or population must say nothing: ${thin}`);
  assert.ok(thin.includes(H.hi_pm25_winter), `the one present metric still counts: ${thin}`);
  assert.equal(S.summarize({}, 'Budapest', 90), '', 'no data at all must yield no text');
  assert.ok(!S.summarize(probe, 'Budapest', null).includes(H.sum_rel(90).slice(0, 8)),
    'outside the scope there is nothing to rank against');
});

ok('summary: the GP warning follows the gp filter, not the raw count', () => {
  const S = load(); sumScope(S);
  const warn = s => S.summarize(s, 'Budapest', null).includes(S.HU.sum_gp);
  assert.ok(!warn({pop_2022: 32625, gp_vacant: 1}), 'a town the rate-based filter passes gets no warning');
  assert.ok(warn({pop_2022: 800, gp_vacant: 1}), 'a village over 1 per 10k is still flagged');
});

ok('summary: price clause names the kind and its sales count, and flags thin data', () => {
  const S = load(); sumScope(S);
  const H = S.HU, few = S.summarize({...probe, house_tx: 4}, 'Budapest', null);
  assert.ok(few.includes('ház') && few.includes('4 eladásból') && few.includes(H.low_tx), few);
  assert.ok(!S.summarize({...probe, house_tx: 40}, 'Budapest', null).includes(H.low_tx),
    'a well-sampled price is not flagged');
  S.UI.kind = 'flat';
  const flat = S.summarize({pop_2022: 60000, ...district}, 'Budapest', null);
  assert.ok(flat.includes('lakás') && flat.includes('144\u00a0M\u00a0Ft') && flat.includes('1155 eladásból'), flat);
  assert.ok(!S.summarize(probe, 'Budapest', null).includes('M\u00a0Ft'),
    'a house-only row says nothing about price in flat mode');
});

ok('summary: two workplaces name both commutes; one workplace reads as before', () => {
  const S = load(); sumScope(S);
  const two = S.summarize({...probe, commute_best_min: 55, commute1_min: 42, commute2_min: 55},
    'Budapest / Vác', null);
  assert.ok(two.includes('ingázás: 42 / 55\u00a0perc') && two.includes('Budapest / Vác'), two);
  assert.ok(!two.includes('központ'), `the single-anchor wording must not also appear: ${two}`);
  const one = S.summarize({...probe, commute1_min: 42}, 'Budapest', null);
  assert.ok(one.includes('42\u00a0perc ingázás (központ: Budapest)'), one);
});

ok('summary: the English fallback is complete', () => {
  const S = load(); sumScope(S); S.setLang('en');
  const txt = S.summarize(probe, 'Budapest', 90);
  assert.ok(txt.includes('its strength is cheaper housing') && txt.includes('more polluted winter air')
    && txt.includes('Watch out: frost pocket.'), txt);
  assert.ok(!/[őűáé]/.test(txt), `Hungarian leaked into English: ${txt}`);
});

ok('first visit follows the browser language: Hungarian only for a Hungarian browser', () => {
  assert.equal(load('hu-HU').getLang(), 'hu');
  assert.equal(load('hu').getLang(), 'hu');
  assert.equal(load('en-GB').getLang(), 'en');
  assert.equal(load('de-DE').getLang(), 'en');
  assert.equal(load('').getLang(), 'en');
});

console.log(`\n${checks} checks passed`);

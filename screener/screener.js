/* Rent screener, one state at a time or the whole country (?st=US): rent-study (RCS) conclusions vs HUD Small Area FMRs,
   and an estimate of market rent for every HUD rent line from the rent studies near it (including studies just across the
   state line). Each data file (data/<ST>.enc.js, data/US.enc.js) is encrypted; nothing renders until the password unlocks it. */
(function () {
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const ok = v => v != null && v !== '' && isFinite(v);
const money = v => !ok(v) ? '–' : (v < 0 ? '−$' : '$') + Math.abs(Math.round(v)).toLocaleString('en-US');
const pct = v => !ok(v) ? '–' : Math.round(v * 100) + '%';
const int = v => !ok(v) ? '–' : Math.round(v).toLocaleString('en-US');
const mi = v => !ok(v) ? '–' : v < 10 ? v.toFixed(1) : Math.round(v).toString();
const bedName = b => b === 0 ? 'Studio' : b + 'BR';
const sgn = v => !ok(v) ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '';
const ropCode = r => r ? r.split(':')[0] : '—';
const titleCase = s => s && s === s.toUpperCase() ? s.toLowerCase().replace(/(^|[\s-])\w/g, c => c.toUpperCase()) : s;
const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
// Same method as Python's statistics.quantiles (exclusive), used for the build-time numbers.
const quant = (a, q) => {
  const s = [...a].sort((x, y) => x - y), n = s.length;
  if (!n) return null; if (n === 1) return s[0];
  const h = Math.max(0, Math.min(n - 1, q * (n + 1) - 1)), lo = Math.floor(h);
  return s[lo] + (h - lo) * (s[Math.min(lo + 1, n - 1)] - s[lo]);
};
const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  del(k) { try { sessionStorage.removeItem(k); } catch (e) { /* private mode */ } },
};

/* ---------- state ---------- */
const STATES = window.RS_STATES || [];
const stName = Object.fromEntries(STATES);
let ST = (new URLSearchParams(location.search).get('st') || store.get('rsState') || 'US').toUpperCase();
if (!stName[ST]) ST = 'US';
const fillStates = sel => { sel.innerHTML = STATES.map(([c, n]) => `<option value="${c}">${esc(c === 'US' ? 'United States (all states)' : n)}</option>`).join(''); sel.value = ST; };
function setState(c) {
  ST = c; store.set('rsState', c);
  document.title = `${stName[c]} Rent Screener`;
  $('.gate h1').textContent = `${stName[c]} Rent Screener`;
  history.replaceState(null, '', location.pathname + '?st=' + c + location.hash);
}
fillStates($('#gateState')); fillStates($('#stateSel')); setState(ST);
$('#gateState').addEventListener('change', e => setState(e.target.value));
$('#stateSel').addEventListener('change', e => { store.set('rsState', e.target.value); location.href = location.pathname + '?st=' + e.target.value; });
const loadData = () => new Promise((res, rej) => {
  if (window.RS_ENC && window.RS_ENC[ST]) return res();
  const el = document.createElement('script'); el.src = `data/${ST}.enc.js?v=${window.RS_BUILD || 1}`; el.onload = res; el.onerror = rej; document.head.appendChild(el);
});

/* ---------- unlock ---------- */
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
async function decrypt(pw) {
  const E = window.RS_ENC[ST];
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt: b64(E.salt), iterations: E.iter },
    base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  const gz = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(E.iv) }, key, b64(E.ct));
  const text = await new Response(new Blob([gz]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  return JSON.parse(text);
}
const pwIn = $('#pw'), gateErr = $('#gateErr'), gateBtn = $('#gateBtn');
async function unlock(pw, quiet) {
  gateBtn.disabled = true;
  try { await loadData(); } catch (e) { gateBtn.disabled = false; gateErr.textContent = 'The data file did not load. Check the connection and reload the page.'; return; }
  if (!(window.RS_ENC && window.RS_ENC[ST])) { gateBtn.disabled = false; gateErr.textContent = 'The data file did not load. Reload the page.'; return; }
  if (!(window.crypto && crypto.subtle && window.DecompressionStream)) { gateErr.textContent = 'This browser cannot open the data. Use a current Chrome, Edge, Safari or Firefox over https.'; return; }
  gateBtn.disabled = true; gateErr.textContent = quiet ? '' : 'Unlocking…';
  let data;
  try { data = await decrypt(pw); } catch (e) {
    store.del('caPw'); gateBtn.disabled = false;
    gateErr.textContent = quiet ? '' : 'Wrong password.'; pwIn.select(); return;
  }
  store.set('caPw', pw);
  $('#gate').remove();
  start(data);
}
$('#gateForm').addEventListener('submit', e => { e.preventDefault(); unlock(pwIn.value); });
const savedPw = store.get('caPw');
if (savedPw) unlock(savedPw, true); else pwIn.focus();

/* ---------- app ---------- */
function start(D) {
  const NAT = ST === 'US';   // the national file: every state at once
  const M = D.meta, P = D.props, RCS = D.rcs, SAF = D.safmr, SN = NAT ? 'U.S.' : stName[ST];
  const RMAX = NAT ? 150 : 500;   // studies are searched this far; the national file has no state-line limit, so it stops at 150 miles
  const pById = new Map(P.map(p => [p.id, p]));
  // Properties in other states that have a study near this state's properties: location and name only.
  const spById = new Map((D.sprops || []).map(p => [p.id, Object.assign(p, { cons: [], lines: [], away: true, county: titleCase(p.county), city: titleCase(p.city),
    hay: [p.name, p.addr, p.city, p.state, p.zip, p.county].join(' ').toLowerCase() })]));
  const today = new Date().toISOString().slice(0, 10);
  const addMonths = n => { const d = new Date(); d.setMonth(d.getMonth() + n); return d.toISOString().slice(0, 10); };
  const yearAgo = addMonths(-12);
  // 2027 QCT / DDA membership (screener/zones.js, public): 1 = QCT, 2 = DDA
  const ZN = window.RS_ZONES || null, ZQ = new Set(ZN ? ZN.qct : []), ZD = new Set(ZN ? ZN.dda : []);
  const zoneOf = id => (ZQ.has(id) ? 1 : 0) | (ZD.has(id) ? 2 : 0);
  const zoneTxt = z => [z & 1 ? 'QCT' : '', z & 2 ? 'DDA' : ''].filter(Boolean).join(', ');
  const ZONEF = { qct: z => z & 1, dda: z => z & 2, either: z => z > 0, both: z => z === 3, neither: z => !z };
  const zoneOk = z => !S.zone || !ZN || !!ZONEF[S.zone](z);
  for (const p of P) {
    p.zone = zoneOf(p.id);
    p.state = NAT ? p.st : ST; p.county = titleCase(p.county); p.city = titleCase(p.city);
    p.hay = [p.name, p.addr, p.city, p.zip, p.county, p.owner, p.mgmt, p.id, ...(NAT ? [p.state, stName[p.state]] : [])].join(' ').toLowerCase();
  }
  // One entry per property and firm (that firm's latest study there), newest first; p.rcs = the property's latest from any firm.
  for (const r of RCS) {
    r.p = pById.get(r.id) || spById.get(r.id); (r.p.studies = r.p.studies || []).push(r); if (!r.p.rcs) r.p.rcs = r;
    r.ratio = median(r.asis.map(x => x.pct).filter(ok));                                   // vs SAFMR on the study date
    r.ratio27 = median(r.asis.map(x => ok(x.pct27) ? x.pct27 : x.pct).filter(ok));         // the same dollars vs today's SAFMR
    r.asis.forEach((x, i) => { x.renRow = r.ren.length === r.asis.length ? r.ren[i] : r.ren.find(y => y.unit === x.unit && y.sf === x.sf) || null; });
  }
  // Distance from every property to every study property (miles), nearest first; a property's own study is not "nearby".
  const R_EARTH = 3958.8, rad = Math.PI / 180;
  const dist = (a, b) => {
    const dp = (b.lat - a.lat) * rad, dl = (b.lon - a.lon) * rad;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dl / 2) ** 2;
    return 2 * R_EARTH * Math.asin(Math.sqrt(h));
  };
  // Studies sorted by latitude, so each property only measures the ones in its latitude band; with none within RMAX, the nearest one.
  const byLat = RCS.slice().sort((a, b) => a.p.lat - b.p.lat), lats = byLat.map(r => r.p.lat), band = RMAX / 69 + 0.05;
  const firstAt = v => { let lo = 0, hi = lats.length; while (lo < hi) { const m = (lo + hi) >> 1; if (lats[m] < v) lo = m + 1; else hi = m; } return lo; };
  // Any point (a property, a LIHTC project, a pin); self = the property at that point, whose own study is not "nearby".
  function nearList(pt, self) {
    const near = [];
    for (let i = firstAt(pt.lat - band); i < byLat.length && lats[i] <= pt.lat + band; i++) {
      const r = byLat[i]; if (r.p === self) continue;
      const d = dist(pt, r.p); if (d <= RMAX) near.push({ r, d });
    }
    if (!near.length) { let best = null; for (const r of RCS) if (r.p !== self) { const d = dist(pt, r.p); if (!best || d < best.d) best = { r, d }; } if (best) near.push(best); }
    return near.sort((a, b) => a.d - b.d);
  }
  for (const p of P) p.near = nearList(p, p);
  const zipProps = {};
  for (const p of P) (zipProps[p.zip] = zipProps[p.zip] || []).push(p);

  // Which studies can be used
  const CAL = {
    all: ['All studies', () => true],
    m12: ['Studies from the last 12 months', r => r.date >= addMonths(-12)],
    m24: ['Studies from the last 2 years', r => r.date >= addMonths(-24)],
    m36: ['Studies from the last 3 years', r => r.date >= addMonths(-36)],
    final: ['Final reports and grids (no prelims)', r => !r.prelim],
  };
  // The fallback % and the calibration tables use this state's own studies (all loaded studies if it has fewer than 5).
  const HOME = RCS.filter(r => !r.p.away);
  const POOL = HOME.filter(r => ok(r.ratio)).length >= 5 ? HOME : RCS, FB = NAT ? 'National' : POOL === HOME ? 'Statewide' : 'Regional';
  const firmN = {};
  for (const r of RCS) firmN[r.firm] = (firmN[r.firm] || 0) + 1;
  const FIRMS = Object.keys(firmN).sort((a, b) => firmN[b] - firmN[a] || a.localeCompare(b));
  const studyOk = r => S.firms.has(r.firm) && CAL[S.cal][1](r) && ok(r.ratio);
  function calib(setKey, firms) {
    const set = POOL.filter(r => CAL[setKey][1](r) && (!firms || firms.has(r.firm)) && ok(r.ratio));
    const ps = set.map(r => r.ratio), byBed = {}, byYear = {};
    for (const r of set) {
      const g = {};
      for (const x of r.asis) if (ok(x.pct)) (g[x.bed] = g[x.bed] || []).push(x.pct);
      for (const b in g) (byBed[b] = byBed[b] || []).push(median(g[b]));
      (byYear[r.date.slice(0, 4)] = byYear[r.date.slice(0, 4)] || []).push(r.ratio);
    }
    return { n: ps.length, med: median(ps), p25: quant(ps, 0.25), p75: quant(ps, 0.75), byBed, byYear };
  }

  const DOCS = ['HAP', 'PRAC', 'RAC', 'PAC', '—'];
  const docCount = {}, ropCount = {}, ropLabel = {};
  for (const p of P) for (const c of p.cons) {
    const d = c.doc || '—', r = ropCode(c.ropt);
    docCount[d] = (docCount[d] || 0) + 1; ropCount[r] = (ropCount[r] || 0) + 1; ropLabel[r] = c.ropt ? c.ropt.split(': ').slice(1).join(': ') : 'No renewal option on file';
  }
  const ROPTS = Object.keys(ropCount).sort((a, b) => (a === '—') - (b === '—') || a.localeCompare(b));
  const DEF = () => ({ q: '', stf: '', county: '', radius: 5, combine: 'idw', cal: 'all', bedMatch: true, useOwn: true, rcsMode: 'auto',
    fallback: 'none', ratio: Math.round(calib('all').med * 100), fee: 5, firms: new Set(FIRMS),
    docs: new Set(['HAP']), ropts: new Set(ROPTS), oldCons: false, exp: '', minUnits: '', minGap: '', minAnnual: '', rcsOnly: false, showNoEst: false, zone: '', areaOnly: true });
  const S = Object.assign(DEF(), { view: 'props', sel: null, selE: null, ctr: null, limit: 300,
    sort: { near: { i: 'd', d: 1 }, props: { i: 'annual', d: -1 }, lines: { i: 'annual', d: -1 }, rcs: { i: 'date', d: -1 }, safmr: { i: 'props', d: -1 } } });
  let CALNOW = calib('all'), TOK = 0;

  /* ---------- estimate ---------- */
  const modeFor = r => S.rcsMode === 'auto' ? (r.date >= yearAgo ? 'asis' : 'age') : S.rcsMode;
  const rowK = (x, mode) => mode === 'asis' ? (ok(x.pct27) ? x.pct27 : x.pct) : x.pct;
  const wavg = (rows, f) => { let s = 0, w = 0; for (const x of rows) { const u = x.units || 1; s += f(x) * u; w += u; } return w ? s / w : null; };
  // A study's market ratio for one bedroom count: its own unit types of that size when it has them, else its median.
  function studyK(r, bed, forceMatch) {
    const mode = modeFor(r);
    const rows = (S.bedMatch || forceMatch) ? r.asis.filter(x => x.bed === bed && ok(rowK(x, mode))) : [];
    if (rows.length) return { k: wavg(rows, x => rowK(x, mode)), match: true, mode };
    return { k: mode === 'asis' ? r.ratio27 : r.ratio, match: false, mode };
  }
  function refsFor(p) {
    if (p._tok === TOK) return p._refs;
    if (!p.near) p.near = nearList(p, p.self || p);
    let list = p.near.filter(o => o.d <= S.radius && studyOk(o.r));
    if (S.combine === 'nearest') list = list.slice(0, 1);
    p._tok = TOK; p._refs = list;
    return list;
  }
  function combine(list, bed) {
    const parts = list.map(o => ({ r: o.r, d: o.d, ...studyK(o.r, bed), w: 1 / Math.max(o.d, 0.25) }));
    let k;
    if (S.combine === 'median') { k = median(parts.map(x => x.k)); parts.forEach(x => { x.share = null; }); }
    else if (S.combine === 'nearest') { k = parts[0].k; parts[0].share = 1; }
    else {
      const W = parts.reduce((a, x) => a + x.w, 0);
      k = parts.reduce((a, x) => a + x.k * x.w, 0) / W;
      parts.forEach(x => { x.share = x.w / W; });
    }
    return { k, parts };
  }
  const ownStudy = p => S.useOwn && p.studies ? p.studies.find(studyOk) || null : null;   // latest usable study at the property
  // FY2027 SAFMR for a ZIP (5BR+ = 4BR + 15% per extra bedroom)
  const safAt = (zip, bed) => { const a = zip && SAF[zip]; if (!a) return null; return bed <= 4 ? a[1 + bed] : ok(a[5]) ? a[5] * (1 + 0.15 * (bed - 4)) : null; };
  // Market % of SAFMR for one bedroom count at any subject (a screener property or any other point): own study, else nearby studies, else the fallback
  function subjectK(s, bed) {
    const own = ownStudy(s);
    if (own) { const x = studyK(own, bed, true); return { k: x.k, basis: 'own', parts: [{ r: own, d: 0, ...x, share: 1 }] }; }
    const refs = refsFor(s);
    if (refs.length) { const c = combine(refs, bed); return { k: c.k, basis: 'near', parts: c.parts }; }
    if (S.fallback === 'state') return { k: S.ratio / 100, basis: 'state', parts: [] };
    return { k: null, basis: null, parts: [] };
  }
  function lineEst(p, ln) {
    const saf = ln.s27 ?? ln.fmr, safSrc = ln.s27 != null ? 'SAFMR' : ln.fmr != null ? 'area FMR' : null;
    const gross = ln.rent + ln.ua;
    let estGross = null, estRent = null, basis = null, k = null, parts = null;
    const own = ownStudy(p);
    if (own) {
      const mode = modeFor(own), rows = own.asis.filter(x => x.bed === ln.bed && ok(x.gross));
      if (mode === 'asis' && rows.length) { estRent = wavg(rows, x => x.rcs); basis = 'own'; parts = [{ r: own, d: 0, k: null, match: true, mode, share: 1 }]; }
      else if (saf) { const s = studyK(own, ln.bed, true); k = s.k; estGross = k * saf; basis = 'own'; parts = [{ r: own, d: 0, ...s, share: 1 }]; }
    }
    if (basis == null && saf) {
      const refs = refsFor(p);
      if (refs.length) { const c = combine(refs, ln.bed); k = c.k; parts = c.parts; estGross = k * saf; basis = 'near'; }
      else if (S.fallback === 'state') { k = S.ratio / 100; estGross = k * saf; basis = 'state'; }
    }
    if (estRent == null && estGross != null) estRent = estGross - ln.ua;
    if (estGross == null && estRent != null) estGross = estRent + ln.ua;
    if (k == null && estGross != null && saf) k = estGross / saf;
    const gap = estRent != null ? estRent - ln.rent : null;
    return { saf, safSrc, gross, curPct: saf ? gross / saf : null, estGross, estRent, gap, annual: gap != null ? gap * ln.units * 12 : null, basis, k, parts };
  }
  const plural = (n, w) => `${n} ${n === 1 ? w : w.replace(/y$/, 'ie') + 's'}`;
  function basisText(p, e) {
    if (e.basis === 'own') return `Own study ${e.parts[0].r.date.slice(0, 7)}`;
    if (e.basis === 'near') return e.parts.length === 1 ? `${e.parts[0].r.name} (${mi(e.parts[0].d)} mi)` : `${plural(e.parts.length, 'study')} within ${S.radius} mi`;
    if (e.basis === 'state') return `${FB} ${S.ratio}%`;
    return e.saf ? `No study within ${S.radius} mi` : 'No SAFMR';
  }

  /* ---------- filtering ---------- */
  const conOk = c => (c.status || S.oldCons) && S.docs.has(c.doc || '—') && S.ropts.has(ropCode(c.ropt));
  let OUT = [], NOEST = [], NEAR = [], LINES = [], RROWS = [], ZROWS = [], COV = { n: 0, est: 0, hidden: 0 }, REACH = {};   // NOEST: matching properties with no estimate, mapped but not listed
  // One screener row per property: its rent lines on the included contracts, with estimates (cached until the settings change)
  function rowOf(p) {
    if (p._rtok === TOK) return p._row;
    p._rtok = TOK; p._row = null;
    const okc = p.cons.map(conOk), ls = p.lines.filter(ln => okc[ln.c]);
    if (!ls.length) return null;
    let U = 0, R = 0, G = 0, SF = 0, GU = 0, GAP = 0, ANN = 0, n = 0, KU = 0, KW = 0;
    const bases = new Set();
    for (const ln of ls) {
      const e = ln.e = lineEst(p, ln);
      U += ln.units; R += ln.rent * ln.units;
      if (e.saf) { G += e.gross * ln.units; SF += e.saf * ln.units; }
      if (e.gap != null) { GU += ln.units; GAP += e.gap * ln.units; ANN += e.annual; n++; }
      if (ok(e.k)) { KU += e.k * ln.units; KW += ln.units; }
      bases.add(e.basis);
    }
    const own = ownStudy(p), refs = refsFor(p), nearest = p.near.find(o => studyOk(o.r)) || null;
    const cs = p.cons.filter((c, i) => okc[i] && ls.some(l => l.c === i));
    const est = n > 0;
    const row = { p, ls, cs, units: U, rent: U ? R / U : null, curPct: SF ? G / SF : null, gapU: GU ? GAP / GU : null, annual: est ? ANN : null,
      k: KW ? KU / KW : null, own, refs, nearest, est,
      next: cs.map(c => c.exp).filter(Boolean).sort()[0] || null, ov: cs.map(c => c.ovExp).filter(Boolean).sort()[0] || null,
      docs: [...new Set(cs.map(c => c.doc || '—'))].join(', '), ropts: [...new Set(cs.map(c => ropCode(c.ropt)))].join(', '),
      basis: bases.has('own') ? `Own study ${own.date.slice(0, 7)}` : bases.has('near') ? (refs.length === 1 ? `1 study within ${S.radius} mi` : `${refs.length} studies within ${S.radius} mi`)
        : bases.has('state') ? `${FB} ${S.ratio}%` : `None within ${S.radius} mi` };
    return (p._row = row);
  }
  function build() {
    TOK++;
    CALNOW = calib(S.cal, S.firms);
    const q = S.q.trim().toLowerCase(), cut = S.exp ? addMonths(+S.exp) : null;
    OUT = []; NOEST = []; LINES = []; COV = { n: 0, est: 0, hidden: 0 }; REACH = {};
    const AREA = S.ctr && S.areaOnly, outside = p => AREA && dist(S.ctr, p) > S.radius;
    for (const p of P) {
      if (S.stf && p.state !== S.stf) continue;
      if (S.county && p.county !== S.county) continue;
      if (!zoneOk(p.zone)) continue;
      if (S.rcsOnly && !p.rcs) continue;
      if (q && !p.hay.includes(q)) continue;
      if (outside(p)) continue;
      const row = rowOf(p); if (!row) continue;
      const { ls, own, refs, est } = row, U = row.units;
      if (cut && !(row.next && row.next <= cut)) continue;
      if (ok(S.minUnits) && U < +S.minUnits) continue;
      COV.n++; if (est) COV.est++;
      if (!est && !S.showNoEst) { COV.hidden++; if (!ok(S.minGap) && !ok(S.minAnnual)) NOEST.push(row); continue; }
      if (ok(S.minGap) && !(row.gapU >= +S.minGap)) continue;
      if (ok(S.minAnnual) && !(row.annual >= +S.minAnnual)) continue;
      OUT.push(row);
      if (!own) for (const o of refs) REACH[o.r.sid] = (REACH[o.r.sid] || 0) + 1;
      for (const ln of ls) LINES.push({ p, ln, e: ln.e, c: p.cons[ln.c] });
    }
    RROWS = [];
    for (const r of RCS) {
      const p = r.p;
      if (!S.firms.has(r.firm)) continue;
      if (S.stf && p.state !== S.stf) continue;
      if (S.county && p.county !== S.county) continue;
      if (q && !p.hay.includes(q)) continue;
      if (!zoneOk(p.zone ?? (p.zone = zoneOf(p.id)))) continue;
      if (outside(p)) continue;
      for (const x of r.asis) RROWS.push({ p, r, x, now: hudNow(p, x.bed) });
    }
    ZROWS = [];
    for (const z in SAF) {
      const a = SAF[z], ps = zipProps[z] || [];
      if (q && !(z.includes(q) || a[0].toLowerCase().includes(q) || ps.some(p => p.hay.includes(q)))) continue;
      if (S.stf && a[12] !== S.stf) continue;
      if (S.county && !ps.some(p => p.county === S.county)) continue;
      if (AREA && !ps.some(p => !outside(p))) continue;
      ZROWS.push({ z, a, ps });
    }
    NEAR = S.ctr ? nearRows() : [];
  }
  function hudNow(p, bed) {
    const ls = p.lines.filter(l => l.bed === bed && p.cons[l.c].status);
    return ls.length ? wavg(ls, l => l.rent) : null;
  }

  /* ---------- every property: screener properties, other HUD properties, LIHTC projects, rent-study properties ---------- */
  // One entry per place, keyed by HUD property id (LIHTC-only projects: "L:" + LIHTC id). The public lists (hud_all.js,
  // lihtc.js) load after the unlock; until then only the screener's own properties are searchable.
  const ENT = new Map();
  let HUDE = [], HUDALL = null, LIH = null, PUBERR = '';
  function entity(key, o) { let e = ENT.get(key); if (!e) { e = Object.assign({ key, hud: false, lih: null, p: null, h: null }, o); ENT.set(key, e); } return e; }
  function entOfP(p) {
    const e = entity(p.id, { id: p.nohud ? null : p.id, name: p.name, addr: p.addr, city: p.city, st: p.state, zip: p.zip, county: p.county, lat: p.lat, lon: p.lon,
      units: p.total ?? p.assisted, owner: p.owner, mgmt: p.mgmt, zone: p.zone ?? zoneOf(p.id) });
    e.p = p; e.hud = !p.nohud; return e;
  }
  for (const p of P) entOfP(p);
  for (const p of spById.values()) entOfP(p);
  const hayOf = e => [e.name, e.addr, e.city, e.st, stName[e.st], e.zip, e.county, e.id, e.lihId, e.owner, e.mgmt].filter(Boolean).join(' ').toLowerCase();
  function finishEnt() { for (const e of ENT.values()) { e.hay = hayOf(e); e.lname = (e.name || '').toLowerCase(); } }
  finishEnt();
  function addPublic() {
    if (HUDALL) for (const h of HUDALL.P) {
      const e = entity(h[0], { id: h[0], name: titleCase(h[3]), addr: h[4], city: titleCase(h[5]), st: h[6], zip: h[7], county: titleCase(h[8]), lat: h[1], lon: h[2],
        owner: h[11], mgmt: h[12], zone: h[19], approx: h[13] });
      e.h = h; e.hud = true;
      if (e.units == null) e.units = h[9] ?? h[10];
      if (!e.owner) e.owner = h[11];
      if (!e.zip) e.zip = h[7];
    }
    HUDE = [...ENT.values()].filter(e => e.h && e.lat != null);
    if (LIH) for (const q of LIH.P) {
      const e = (q[9] && ENT.get(q[9])) || entity(q[9] || 'L:' + (q[14] || `${q[0]},${q[1]}`), { id: q[9] || null, hud: !!q[9], name: titleCase(q[2]), addr: q[12],
        city: titleCase(q[3]), st: q[4], zip: q[13], lat: q[0], lon: q[1], units: q[5], zone: q[11], approx: q[10] });
      e.lih = q; e.lihId = q[14]; q._e = e;
    }
    finishEnt();
  }
  const isScreenP = e => !!(e && e.p && !e.p.away && pById.get(e.p.id) === e.p);
  // The subject an estimate is made for: the screener property itself, or a point carrying the studies at that place
  function subjOf(e) {
    if (isScreenP(e)) return e.p;
    return e._subj || (e._subj = { lat: e.lat, lon: e.lon, zip: e.zip, studies: e.p && e.p.studies, self: e.p || null, near: null });
  }
  const studyOf = e => (e.p && e.p.rcs) || null;
  const kindTxt = e => [studyOf(e) && 'RCS', e.hud && 'HUD', e.lih && 'LIHTC'].filter(Boolean).join(' + ');
  const kindBadges = e => (studyOf(e) ? '<span class="b rcs">RCS</span>' : '') + (e.hud ? '<span class="b hud">HUD</span>' : '') + (e.lih ? '<span class="b lih">LIHTC</span>' : '');
  const lihTxt = q => !q ? '–' : [q[7] ? `PIS ${q[7]}` : 'LIHTC', q[8] >= 0 && LIH ? LIH.cr[q[8]] : ''].filter(Boolean).join(' · ');
  const k2 = e => { if (e._k2tok !== TOK) { e._k2tok = TOK; e._k2 = subjectK(subjOf(e), 2).k; } return e._k2; };
  const m2 = e => { const k = k2(e), sf = safAt(e.zip, 2); return ok(k) && sf ? k * sf : null; };
  const nrow = r => r.p ? rowOf(r.p) : null;
  const contractTxt = r => { const x = nrow(r); if (x) return x.docs; const h = r.e.h; if (h) return h[14] || (h[15] ? 'Active' : 'No active contract'); return r.e.hud ? '' : r.e.lih ? 'LIHTC only' : ''; };
  function nearRows() {
    const c = S.ctr, out = [], bandN = S.radius / 69 + 0.02;
    for (const e of ENT.values()) {
      if (e.lat == null || Math.abs(e.lat - c.lat) > bandN) continue;
      const d = dist(c, e); if (d > S.radius) continue;
      if (!zoneOk(e.zone || 0)) continue;
      out.push({ e, d, p: isScreenP(e) ? e.p : null });
    }
    return out;
  }

  /* ---------- tables ---------- */
  const C = (k, t, v, o = {}) => ({ k, t, v, ...o });
  const feeOf = a => ok(a) && a > 0 ? a * S.fee / 100 : null;
  const estTag = x => x.safEst ? ' <span class="est" title="This ZIP was not in the SAFMR file on the study date (before FY2025 HUD published SAFMRs only for metro areas). Estimated as its FY2025 SAFMR × the state\'s median SAFMR change from that vintage to FY2025.">est.</span>' : '';
  const uaTag = x => !x.uaSrc || x.uaSrc === 'study' ? '' : x.uaSrc === 'included in the conclusion' ? ' <span class="est" title="The study concludes gross rents, so no allowance is added">gross</span>' : /median/.test(x.uaSrc) ? ` <span class="est" title="The grid has no utility allowance and the property has no HUD allowance for this bedroom count; the ${esc(x.uaSrc)} is used">area</span>` : ' <span class="est" title="The grid has no utility allowance; the current HUD allowance is used">HUD</span>';
  const studyBadge = p => p.rcs ? ` <span class="b rcs" title="Own rent study ${esc(p.rcs.date)}">RCS</span>` : '';
  const VIEWS = {
    near: { rows: () => NEAR, pid: r => r.e.key, cols: [
      C('name', 'Property', r => r.e.name, { f: r => `<b>${esc(r.e.name)}</b>` }),
      C('type', 'Type', r => kindTxt(r.e), { f: r => kindBadges(r.e), tip: 'RCS = rent study on file · HUD = HUD multifamily property · LIHTC = tax-credit project' }),
      C('city', 'City', r => r.e.city), C('st', 'State', r => r.e.st),
      C('d', 'Mi', r => r.d, { num: 1, f: r => mi(r.d), tip: 'Straight-line miles from the center' }),
      C('units', 'Units', r => r.e.units, { num: 1, f: r => int(r.e.units) }),
      C('rent', 'Avg contract rent', r => { const x = nrow(r); return x && x.rent; }, { num: 1, f: r => { const x = nrow(r); return money(x && x.rent); }, tip: 'HUD contract rent on the included rent lines (screener properties only)' }),
      C('curPct', 'Gross % SAFMR', r => { const x = nrow(r); return x && x.curPct; }, { num: 1, f: r => { const x = nrow(r); return pct(x && x.curPct); } }),
      C('k2', 'Market % (2BR)', r => k2(r.e), { num: 1, f: r => pct(k2(r.e)), tip: 'Estimated 2BR market gross as % of the FY2027 SAFMR, from the rent studies within the radius of this property (its own study first)' }),
      C('m2', 'Est. 2BR market gross', r => m2(r.e), { num: 1, f: r => money(m2(r.e)), tip: 'Market % (2BR) × the FY2027 2BR SAFMR for its ZIP. Gross = rent + tenant-paid utilities.' }),
      C('gapU', 'Gap / unit / mo', r => { const x = nrow(r); return x && x.gapU; }, { num: 1, f: r => { const x = nrow(r); return x ? `<span class="${sgn(x.gapU)}">${money(x.gapU)}</span>` : '–'; } }),
      C('annual', 'Annual uplift', r => { const x = nrow(r); return x && x.annual; }, { num: 1, f: r => { const x = nrow(r); return x ? `<b class="${sgn(x.annual)}">${money(x.annual)}</b>` : '–'; } }),
      C('study', 'Rent study', r => { const s = studyOf(r.e); return s && s.date; }, { f: r => { const s = studyOf(r.e); return s ? `${esc(s.firm)} ${esc(s.date.slice(0, 7))} · ${pct(s.ratio)}` : '–'; },
        tip: 'Latest rent study at the property: firm, date and its median as-is gross as % of the SAFMR then' }),
      C('lih', 'LIHTC', r => r.e.lih ? r.e.lih[7] : null, { f: r => esc(lihTxt(r.e.lih)), tip: 'Placed-in-service year and credit type (HUD LIHTC database and state award lists)' }),
      C('docs', 'Contract', r => contractTxt(r)),
      C('next', 'Term ends', r => { const x = nrow(r); return x ? x.next : r.e.h ? r.e.h[16] : null; }),
      C('ov', 'Overall exp.', r => { const x = nrow(r); return x ? x.ov : r.e.h ? r.e.h[17] : null; }),
      ...(ZN ? [C('zone', 'QCT/DDA', r => zoneTxt(r.e.zone || 0))] : []),
      C('owner', 'Owner', r => r.e.owner), C('id', 'ID', r => r.e.id || r.e.lihId),
    ] },
    props: { rows: () => OUT, pid: r => r.p.id, cols: [
      C('name', 'Property', r => r.p.name, { f: r => `<b>${esc(r.p.name)}</b>${studyBadge(r.p)}` }),
      C('city', 'City', r => r.p.city), ...(NAT ? [C('st', 'State', r => r.p.state)] : []), C('county', 'County', r => r.p.county),
      ...(ZN ? [C('zone', 'QCT/DDA', r => zoneTxt(r.p.zone), { tip: 'In a 2027 Qualified Census Tract and/or Difficult Development Area' })] : []),
      C('units', 'Units', r => r.units, { num: 1, f: r => int(r.units), tip: 'Units on the included rent lines' }),
      C('rent', 'Avg contract rent', r => r.rent, { num: 1, f: r => money(r.rent) }),
      C('curPct', 'Gross % SAFMR', r => r.curPct, { num: 1, f: r => pct(r.curPct), tip: 'Current contract rent + utility allowance, as % of the FY2027 SAFMR (unit-weighted)' }),
      C('k', 'Market % used', r => r.k, { num: 1, f: r => pct(r.k), tip: 'Estimated market gross as % of the FY2027 SAFMR, from the studies used (unit-weighted)' }),
      C('gapU', 'Gap / unit / mo', r => r.gapU, { num: 1, f: r => `<span class="${sgn(r.gapU)}">${money(r.gapU)}</span>` }),
      C('annual', 'Annual uplift', r => r.annual, { num: 1, f: r => `<b class="${sgn(r.annual)}">${money(r.annual)}</b>` }),
      C('fee', 'Fee / yr', r => feeOf(r.annual), { num: 1, f: r => money(feeOf(r.annual)), tip: 'Annual uplift × the fee %' }),
      C('basis', 'Estimate from', r => r.basis),
      C('nearest', 'Nearest study', r => r.own ? r.own.name : r.nearest && r.nearest.r.name, { tip: 'Nearest rent study at any distance (the property\'s own study when it has one)' }),
      C('nd', 'Mi', r => r.own ? 0 : r.nearest && r.nearest.d, { num: 1, f: r => r.own ? 'own' : mi(r.nearest && r.nearest.d) }),
      C('ndate', 'Study date', r => (r.own || (r.nearest && r.nearest.r) || {}).date),
      C('docs', 'Contract', r => r.docs), C('ropts', 'Renewal opt.', r => r.ropts, { tip: 'HUD renewal option code; see the filter for names' }),
      C('next', 'Term ends', r => r.next, { tip: 'Earliest current-term expiration among the included contracts' }),
      C('ov', 'Overall exp.', r => r.ov),
      C('owner', 'Owner', r => r.p.owner), C('otype', 'Owner type', r => r.p.ownerType), C('mgmt', 'Management agent', r => r.p.mgmt),
      C('id', 'HUD ID', r => r.p.id),
    ] },
    lines: { rows: () => LINES, pid: r => r.p.id, cols: [
      C('name', 'Property', r => r.p.name, { f: r => `<b>${esc(r.p.name)}</b>${studyBadge(r.p)}` }),
      C('city', 'City', r => r.p.city), ...(NAT ? [C('st', 'State', r => r.p.state)] : []),
      C('bed', 'BR', r => r.ln.bed, { f: r => bedName(r.ln.bed) }),
      C('units', 'Units', r => r.ln.units, { num: 1 }),
      C('rent', 'Contract rent', r => r.ln.rent, { num: 1, f: r => money(r.ln.rent) }),
      C('ua', 'UA', r => r.ln.ua, { num: 1, f: r => money(r.ln.ua) }),
      C('gross', 'Gross', r => r.e.gross, { num: 1, f: r => money(r.e.gross) }),
      C('saf', 'FY2027 SAFMR', r => r.e.saf, { num: 1, f: r => money(r.e.saf) + (r.e.safSrc === 'area FMR' ? ' <span class="est" title="ZIP not in the SAFMR file; area FMR">FMR</span>' : '') }),
      C('curPct', '% SAFMR', r => r.e.curPct, { num: 1, f: r => pct(r.e.curPct) }),
      C('k', 'Market % used', r => r.e.k, { num: 1, f: r => pct(r.e.k) }),
      C('est', 'Est. market rent', r => r.e.estRent, { num: 1, f: r => money(r.e.estRent), tip: 'Contract-rent basis (net of the current utility allowance)' }),
      C('gap', 'Gap / unit', r => r.e.gap, { num: 1, f: r => `<span class="${sgn(r.e.gap)}">${money(r.e.gap)}</span>` }),
      C('annual', 'Annual', r => r.e.annual, { num: 1, f: r => `<b class="${sgn(r.e.annual)}">${money(r.e.annual)}</b>` }),
      C('basis', 'Estimate from', r => basisText(r.p, r.e)),
      C('no', 'Contract', r => r.c.no), C('doc', 'Type', r => r.c.doc || '—'), C('ropt', 'Renewal opt.', r => ropCode(r.c.ropt)),
      C('exp', 'Term ends', r => r.c.exp),
    ] },
    rcs: { rows: () => RROWS, pid: r => r.p.id, cols: [
      C('name', 'Property', r => r.r.name, { f: r => `<b>${esc(r.r.name)}</b>` }),
      C('city', 'City', r => r.p.city), C('st', 'State', r => r.p.state),
      C('date', 'Last done', r => r.r.date, { f: r => esc(r.r.date) + (r.r.prelim ? ' <span class="b pre" title="Preliminary report">prelim</span>' : '') }),
      C('firm', 'Firm', r => r.r.firm),
      C('reach', 'Props using it', r => REACH[r.r.sid] || 0, { num: 1, tip: 'Properties in the current screen whose estimate draws on this study (within the radius)' }),
      C('studies', 'Studies', r => r.r.history.length, { num: 1, tip: 'Studies on file for this property, all firms' }),
      C('signer', 'Signed by', r => r.r.signer), C('client', 'Client', r => r.r.client),
      C('kind', 'Source', r => r.r.kind),
      C('unit', 'Unit', r => r.x.unit), C('runits', 'Units', r => r.x.units, { num: 1 }),
      C('contract', 'Contract at study', r => r.x.contract, { num: 1, f: r => money(r.x.contract) }),
      C('rcs', 'RCS as is', r => r.x.rcs, { num: 1, f: r => `<b>${money(r.x.rcs)}</b>` }),
      C('ren', 'As renovated', r => r.x.renRow ? r.x.renRow.rcs : null, { num: 1, f: r => money(r.x.renRow && r.x.renRow.rcs) }),
      C('ua', 'UA', r => r.x.ua, { num: 1, f: r => money(r.x.ua) + uaTag(r.x) }),
      C('gross', 'Gross', r => r.x.gross, { num: 1, f: r => money(r.x.gross) }),
      C('safmr', 'SAFMR then', r => r.x.safmr, { num: 1, f: r => money(r.x.safmr) + estTag(r.x), tip: 'SAFMR in effect on the study date' }),
      C('vint', 'Vintage', r => r.r.vintage),
      C('pct', '% SAFMR', r => r.x.pct, { num: 1, f: r => `<b>${pct(r.x.pct)}</b>`, tip: 'Study gross ÷ the SAFMR in effect on the study date' }),
      C('s27', 'FY2027 SAFMR', r => r.x.s27, { num: 1, f: r => money(r.x.s27) }),
      C('pct27', '% FY2027', r => r.x.pct27, { num: 1, f: r => pct(r.x.pct27) }),
      C('now', 'HUD rent now', r => r.now, { num: 1, f: r => money(r.now), tip: 'Current HUD contract rent for this bedroom count (unit-weighted)' }),
      C('vs', 'Room to RCS', r => ok(r.now) ? r.x.rcs - r.now : null, { num: 1, f: r => ok(r.now) ? `<span class="${sgn(r.x.rcs - r.now)}">${money(r.x.rcs - r.now)}</span>` : '–',
        tip: 'As-is conclusion minus today\'s HUD contract rent. Positive = today\'s rent is still below the study.' }),
      C('zip', 'ZIP', r => r.r.zip),
    ] },
    safmr: { rows: () => ZROWS, pid: () => null, cols: [
      C('zip', 'ZIP', r => r.z, { f: r => `<b>${esc(r.z)}</b>` }), ...(NAT ? [C('st', 'State', r => r.a[12])] : []),
      C('area', 'HUD area', r => r.a[0], { f: r => esc(r.a[0]) + (r.a[11] > 1 ? ` <span class="est" title="This ZIP is split across ${r.a[11]} HUD areas; first one shown">+${r.a[11] - 1}</span>` : '') }),
      C('props', 'HUD props', r => r.ps.length, { num: 1 }),
      ...[0, 1, 2, 3, 4].map(b => C('s' + b, `FY27 ${bedName(b)}`, r => r.a[1 + b], { num: 1, f: r => money(r.a[1 + b]) })),
      ...[0, 1, 2, 3, 4].map(b => C('o' + b, `FY26r ${bedName(b)}`, r => r.a[6 + b], { num: 1, f: r => money(r.a[6 + b]) })),
      C('chg', '2BR change', r => ok(r.a[8]) && r.a[8] ? r.a[3] / r.a[8] - 1 : null, { num: 1, f: r => ok(r.a[8]) && r.a[8] ? `${((r.a[3] / r.a[8] - 1) * 100).toFixed(1)}%` : '–', tip: 'FY2027 vs FY2026 revised, 2BR' }),
      C('cities', 'Cities (HUD props)', r => [...new Set(r.ps.map(p => p.city))].join(', ')),
    ] },
  };
  const colOf = (V, k) => V.cols.find(c => c.k === k) || V.cols[0];
  function sorted() {
    const V = VIEWS[S.view], so = S.sort[S.view], col = colOf(V, so.i);
    const empty = x => x == null || x === '' || (typeof x === 'number' && !isFinite(x));
    return V.rows().slice().sort((a, b) => {
      const x = col.v(a), y = col.v(b);
      if (empty(x)) return empty(y) ? 0 : 1;
      if (empty(y)) return -1;
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))) * so.d;
    });
  }
  let SHOWN = [];
  function renderTable() {
    const V = VIEWS[S.view], so = S.sort[S.view], rows = sorted();
    $('#ctbl thead').innerHTML = '<tr>' + V.cols.map(c => `<th data-k="${c.k}" class="${c.num ? 'num' : ''}"${c.tip ? ` title="${esc(c.tip)}"` : ''}>${esc(c.t)}${so.i === c.k ? `<span class="arr">${so.d > 0 ? ' ▲' : ' ▼'}</span>` : ''}</th>`).join('') + '</tr>';
    SHOWN = rows.slice(0, S.limit);
    $('#ctbl tbody').innerHTML = SHOWN.map((r, i) => {
      const id = V.pid(r);
      return `<tr data-i="${i}"${id ? ` data-id="${id}"` : ''}${id && id === S.sel ? ' class="sel"' : ''}>` +
        V.cols.map(c => `<td class="${c.num ? 'num' : ''}">${c.f ? c.f(r) : esc(c.v(r) ?? '–')}</td>`).join('') + '</tr>';
    }).join('');
    const em = $('#empty');
    em.hidden = rows.length > 0;
    em.innerHTML = S.view === 'near' ? (S.ctr ? `<b>Nothing within ${S.radius} miles of the center.</b> Widen the radius.` : '<b>No area set.</b> Search for any property, address or ZIP above, or drop a pin, to list everything within the radius.')
      : COV.hidden && S.view !== 'rcs' && S.view !== 'safmr'
      ? `<b>Nothing to show.</b> ${COV.hidden.toLocaleString()} matching properties have no rent study within ${S.radius} miles. They are the gray dots on the map. Widen the radius, or turn on "Also list properties with no estimate".`
      : '<b>Nothing matches.</b> Loosen a filter (contract type, renewal option, timing or gap) or clear the search.';
    $('#more').innerHTML = rows.length > S.limit ? `Showing ${S.limit.toLocaleString()} of ${rows.length.toLocaleString()} rows <button class="btn small" id="moreBtn">Show 300 more</button>` : '';
    renderSummary();
  }
  function renderSummary() {
    let t = '';
    if (S.view === 'near') {
      if (!S.ctr) t = 'Search for any property, address or ZIP, or drop a pin, to list everything within the radius.';
      else {
        const nR = NEAR.filter(r => studyOf(r.e)).length, nH = NEAR.filter(r => r.e.hud).length, nS = NEAR.filter(r => r.p).length, nL = NEAR.filter(r => r.e.lih).length;
        t = `Within ${S.radius} mi of <b>${esc(S.ctr.label)}</b>: ${NEAR.length.toLocaleString()} properties · ${nR.toLocaleString()} with rent studies · ${nH.toLocaleString()} HUD (${nS.toLocaleString()} in the screener) · ${nL.toLocaleString()} LIHTC` +
          (HUDALL || PUBERR ? '' : ' · still loading the HUD and LIHTC lists');
      }
    } else if (S.view === 'props' || S.view === 'lines') {
      const U = OUT.reduce((a, r) => a + r.units, 0), up = OUT.reduce((a, r) => a + Math.max(0, r.annual || 0), 0);
      const n = OUT.filter(r => r.annual > 0).length;
      t = `${OUT.length.toLocaleString()} properties · ${LINES.length.toLocaleString()} rent lines · ${U.toLocaleString()} units · ${n.toLocaleString()} below the estimate, worth <b>${money(up)}/yr</b>` +
        (S.fee ? ` (fee at ${S.fee}%: ${money(up * S.fee / 100)}/yr)` : '') +
        (COV.hidden ? ` · ${COV.hidden.toLocaleString()} more with no study within ${S.radius} mi (gray on the map, not listed)` : '');
    } else if (S.view === 'rcs') {
      const ps = new Set(RROWS.map(r => r.p.id));
      const ns = new Set(RROWS.map(r => r.r)).size;
      t = `${RROWS.length} unit types · ${plural(ns, 'study')} across ${ps.size} properties · each firm's latest study per property, as-is conclusions`;
    } else t = `${ZROWS.length.toLocaleString()} ${esc(SN)} ZIPs in the FY2027 SAFMR file`;
    $('#summary').innerHTML = t;
  }
  $('#ctbl thead').addEventListener('click', e => {
    const th = e.target.closest('th'); if (!th) return;
    const so = S.sort[S.view];
    if (so.i === th.dataset.k) so.d = -so.d; else { so.i = th.dataset.k; so.d = VIEWS[S.view].cols.find(c => c.k === th.dataset.k).num ? -1 : 1; }
    renderTable();
  });
  $('#ctbl tbody').addEventListener('click', e => {
    const tr = e.target.closest('tr'); if (!tr) return;
    if (S.view === 'safmr') {
      const r = SHOWN[+tr.dataset.i];
      $('#q').value = S.q = r.z; setView('props'); refresh(); return;
    }
    const en = ENT.get(tr.dataset.id); if (en) selectEnt(en, true);
  });
  $('#more').addEventListener('click', e => { if (e.target.id === 'moreBtn') { S.limit += 300; renderTable(); } });

  /* ---------- map ---------- */
  const map = L.map('map', { preferCanvas: true }).setView([37.2, -119.4], 6);
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
  const tiles = (svc, attr) => L.tileLayer(`${ESRI}${svc}/MapServer/tile/{z}/{y}/{x}`, { attribution: attr, maxZoom: 19, maxNativeZoom: 16 });
  L.layerGroup([tiles('Canvas/World_Light_Gray_Base', 'Tiles &copy; Esri | HUD Multifamily'), tiles('Canvas/World_Light_Gray_Reference', '')]).addTo(map);
  map.createPane('reach').style.zIndex = 390;   // radius circle and study links sit under the dots
  const reachRenderer = L.svg({ pane: 'reach' });
  const dots = L.layerGroup().addTo(map), ring = L.layerGroup().addTo(map), studyDots = L.layerGroup().addTo(map), lihDots = L.layerGroup().addTo(map), hudDots = L.layerGroup().addTo(map);
  const BANDS = [[500, '#0b5d27', '$500+'], [250, '#1a7f37', '$250–500'], [100, '#5cb270', '$100–250'], [0.5, '#b7dfc1', '$1–100']];
  const gapColor = g => { if (!ok(g)) return '#8b8f98'; for (const [v, c] of BANDS) if (g >= v) return c; return '#c2410c'; };
  const LIHC = '#db2777', HUDC = '#475569';
  const ZONE_STYLE = { qct: { color: '#7c3aed', fillColor: '#7c3aed' }, dda: { color: '#0d9488', fillColor: '#0d9488' } };
  // Map layers that aren't screen filters, so "Reset all" leaves them alone.
  const MAPOPT = { noEst: true, hud: true, lih: true, qct: false, dda: false };
  const legend = L.control({ position: 'bottomright' });
  let legendEl = null;
  function renderLegend() {
    if (!legendEl) return;
    legendEl.innerHTML = '<b>Gap per unit / month</b><br>' + BANDS.map(([, c, t]) => `<i style="background:${c}"></i>${t}`).join('<br>') +
      '<br><i style="background:#c2410c"></i>At or above the estimate<br><i style="background:#8b8f98"></i>No estimate' +
      '<br><i style="background:#fff;border:2.5px solid #111"></i>Rent study' +
      (MAPOPT.hud ? `<br><i style="background:${HUDC}"></i>Other HUD property (not in the screen)` : '') +
      (MAPOPT.lih ? `<br><i style="background:${LIHC}"></i>LIHTC, not a HUD property<br><i style="background:#fff;border:2px solid ${LIHC}"></i>LIHTC at a HUD property` : '') +
      (MAPOPT.qct ? `<br><i class="sq" style="background:${ZONE_STYLE.qct.color}"></i>2027 QCT` : '') +
      (MAPOPT.dda ? `<br><i class="sq" style="background:${ZONE_STYLE.dda.color}"></i>2027 DDA` : '');
  }
  legend.onAdd = () => { legendEl = L.DomUtil.create('div', 'legend'); renderLegend(); return legendEl; };
  legend.addTo(map);
  const layersCtl = L.control({ position: 'topleft' });
  layersCtl.onAdd = () => {
    const d = L.DomUtil.create('div', 'legend mapopts');
    d.innerHTML = `<b>On the map</b>
      <label class="chk"><input type="checkbox" id="mNoEst"> Screener properties with no estimate <i style="background:#8b8f98"></i></label>
      <label class="chk"><input type="checkbox" id="mHud"> Every other HUD property <i style="background:${HUDC}"></i></label>
      <label class="chk"><input type="checkbox" id="mLih"> LIHTC projects <i style="background:${LIHC}"></i></label>
      <div id="layerNote" class="hint" hidden></div>
      <label class="chk"><input type="checkbox" id="mQct"> 2027 QCTs <i class="sq" style="background:${ZONE_STYLE.qct.color}"></i></label>
      <label class="chk"><input type="checkbox" id="mDda"> 2027 DDAs <i class="sq" style="background:${ZONE_STYLE.dda.color}"></i></label>
      <div id="zoneNote" class="hint" hidden></div>`;
    L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
    return d;
  };
  layersCtl.addTo(map);
  $('#mNoEst').checked = MAPOPT.noEst; $('#mHud').checked = MAPOPT.hud; $('#mLih').checked = MAPOPT.lih;
  $('#mNoEst').addEventListener('change', e => { MAPOPT.noEst = e.target.checked; drawMarkers(); });
  $('#mHud').addEventListener('change', e => { MAPOPT.hud = e.target.checked; renderLegend(); drawExtra(); });
  $('#mLih').addEventListener('change', e => { MAPOPT.lih = e.target.checked; renderLegend(); drawExtra(); });

  // 2027 QCT / DDA polygons: the main map's file (assets/qct_dda_2027.js), loaded the first time either is turned on.
  map.createPane('zones').style.zIndex = 350;   // under the radius circle and the dots
  const zoneRenderer = L.canvas({ pane: 'zones', padding: 0.5 });
  const zoneLayers = { qct: L.layerGroup(), dda: L.layerGroup() };
  let zonesLoad = null;
  function loadZones() {
    if (!zonesLoad) zonesLoad = new Promise((res, rej) => {
      if (window.QCT_DDA_2027) return res();
      const el = document.createElement('script'); el.src = '../assets/qct_dda_2027.js'; el.onload = res; el.onerror = rej; document.head.appendChild(el);
    }).then(() => {
      for (const k of ['qct', 'dda']) L.geoJSON(window.QCT_DDA_2027[k], { renderer: zoneRenderer, interactive: false,
        style: { ...ZONE_STYLE[k], weight: 0.6, fillOpacity: 0.16 } }).addTo(zoneLayers[k]);
    }).catch(err => { zonesLoad = null; throw err; });
    return zonesLoad;
  }
  function setZoneLayer(k, on) {
    MAPOPT[k] = on; renderLegend();
    const note = $('#zoneNote');
    if (!on) { map.removeLayer(zoneLayers[k]); if (!MAPOPT.qct && !MAPOPT.dda) note.hidden = true; return; }
    note.hidden = false; note.textContent = 'Loading the 2027 QCT / DDA map…';
    loadZones().then(() => {
      if (MAPOPT[k]) zoneLayers[k].addTo(map);
      note.textContent = 'HUD 2027 designations. Filter by them with "2027 QCT / DDA" at the top left.';
    }).catch(() => { note.textContent = 'Could not load the QCT / DDA map. Try again.'; MAPOPT[k] = false; $(k === 'qct' ? '#mQct' : '#mDda').checked = false; renderLegend(); });
  }
  $('#mQct').addEventListener('change', e => setZoneLayer('qct', e.target.checked));
  $('#mDda').addEventListener('change', e => setZoneLayer('dda', e.target.checked));

  // Public layers, loaded right after the unlock: every located HUD property (hud_all.js) and every LIHTC project (lihtc.js).
  // About 37,000 and 50,000 points nationally, so only the ones inside the current view are drawn.
  const loadJs = (src, key) => new Promise((res, rej) => {
    if (window[key]) return res(window[key]);
    const el = document.createElement('script'); el.src = `${src}?v=${window.RS_BUILD || 1}`;
    el.onload = () => (window[key] ? res(window[key]) : rej(new Error('empty'))); el.onerror = rej; document.head.appendChild(el);
  });
  function lihTip(q) {
    const [, , name, city, st, units, liU, pis, cr, hud, approx, zone] = q;
    return `<b>${esc(name)}</b> · ${esc(titleCase(city || ''))}, ${esc(st)}<br>LIHTC${liU ? ` · ${liU.toLocaleString()}${units ? ` of ${units.toLocaleString()}` : ''} units low-income` : units ? ` · ${units.toLocaleString()} units` : ''}` +
      `${pis ? ` · placed in service ${pis}` : ''}${cr >= 0 ? ` · ${esc(LIH.cr[cr])}` : ''}` +
      (hud ? `<br>HUD property ${esc(hud)}` : '<br>Not a HUD multifamily property') +
      (zone ? `<br>2027 ${zoneTxt(zone)}` : '') + (approx ? '<br><i>Location approximate (ZIP centre)</i>' : '') + '<br><i>Click for the market rent here</i>';
  }
  let DRAWN = new Set();   // properties already drawn by the screener layers
  function drawExtra() {
    hudDots.clearLayers(); lihDots.clearLayers();
    const note = $('#layerNote');
    if (!MAPOPT.hud && !MAPOPT.lih) { note.hidden = true; return; }
    note.hidden = false;
    if (PUBERR) { note.textContent = PUBERR; return; }
    if (!HUDALL || !LIH) { note.textContent = 'Loading every HUD property and LIHTC project…'; return; }
    const b = map.getBounds().pad(0.15), so = b.getSouth(), no = b.getNorth(), we = b.getWest(), ea = b.getEast();
    const inV = (la, lo) => la >= so && la <= no && lo >= we && lo <= ea;
    const hs = [], ls = [];
    if (MAPOPT.hud) for (const e of HUDE) if (!DRAWN.has(e.key) && zoneOk(e.zone || 0) && inV(e.lat, e.lon)) hs.push(e);
    if (MAPOPT.lih) for (const q of LIH.P) if (zoneOk(q[11]) && inV(q[0], q[1])) ls.push(q);
    if (hs.length + ls.length > 15000) { note.textContent = `Zoom in to see the ${(hs.length + ls.length).toLocaleString()} other HUD properties and LIHTC projects in this view.`; return; }
    for (const q of ls) {
      const m = q[9]
        ? L.circleMarker([q[0], q[1]], { radius: 8.5, weight: 2, color: LIHC, fill: false })
        : L.circleMarker([q[0], q[1]], { radius: 4, weight: 1, color: '#fff', fillColor: LIHC, fillOpacity: q[10] ? 0.45 : 0.85 });
      m.bindTooltip(() => lihTip(q));
      m.on('click', () => { if (q._e) selectEnt(q._e, false); });
      lihDots.addLayer(m); m.bringToBack();   // same canvas as the screener dots (a separate one would block their hover and clicks), drawn behind them
    }
    for (const e of hs) {
      const m = L.circleMarker([e.lat, e.lon], { radius: 3.5, weight: 0.8, color: '#fff', fillColor: HUDC, fillOpacity: e.approx ? 0.4 : 0.85 });
      m.bindTooltip(() => `${esc(e.name)} · HUD ${esc(e.h[14] || (e.h[15] ? 'contract' : 'no active contract'))}${e.approx ? ' · location approximate' : ''}<br><i>Click for the market rent here</i>`);
      m.on('click', () => selectEnt(e, false));
      hudDots.addLayer(m); m.bringToBack();
    }
    note.textContent = `In view: ${hs.length.toLocaleString()} other HUD properties, ${ls.length.toLocaleString()} LIHTC projects (ringed when at a HUD property)${S.zone && ZN ? ', QCT/DDA filter applied' : ''}.`;
  }
  map.on('moveend', drawExtra);
  function drawMarkers() {
    dots.clearLayers(); studyDots.clearLayers(); DRAWN = new Set();
    const byP = new Map(OUT.map(r => [r.p, r]));
    // Matching properties with no study in range are drawn first (under the rest), so every property in the screen is on the map.
    if (S.view !== 'rcs' && MAPOPT.noEst) for (const r of NOEST) {
      const p = r.p;
      const m = L.circleMarker([p.lat, p.lon], { radius: p.rcs ? 7 : 4.5, weight: p.rcs ? 2.5 : 1, color: p.rcs ? '#111' : '#fff', fillColor: '#8b8f98', fillOpacity: 0.85 });
      m.bindTooltip(`${esc(p.name)} · no study within ${S.radius} mi`);
      m.on('click', () => select(p, false));
      dots.addLayer(m); DRAWN.add(p.id);
    }
    const list = S.view === 'rcs' ? RCS.filter(r => RROWS.some(x => x.r === r)).map(r => byP.get(r.p) || { p: r.p, gapU: null }) : OUT;
    for (const r of list) {
      const p = r.p;
      const m = L.circleMarker([p.lat, p.lon], { radius: p.rcs ? 7 : 5, weight: p.rcs ? 2.5 : 1, color: p.rcs ? '#111' : '#fff',
        fillColor: gapColor(r.gapU), fillOpacity: 0.92 });
      m.bindTooltip(`${esc(p.name)}${ok(r.gapU) ? ` · ${money(r.gapU)}/unit` : ''}`);
      m.on('click', () => select(p, false));
      dots.addLayer(m); DRAWN.add(p.id);
    }
    // Every usable study stays visible as a ringed dot, even when its own property is filtered out of the list.
    const grayP = new Set(S.view !== 'rcs' && MAPOPT.noEst ? NOEST.map(r => r.p) : []);
    if (S.view !== 'rcs') for (const r of RCS) {
      if (byP.has(r.p) || grayP.has(r.p) || !studyOk(r)) continue;
      const m = L.circleMarker([r.p.lat, r.p.lon], { radius: 6, weight: 2.5, color: '#111', fillColor: '#fff', fillOpacity: 0.9 });
      m.bindTooltip(`${esc(r.name)} · ${esc(r.firm)} rent study ${esc(r.date)}`);
      m.on('click', () => select(r.p, false));
      studyDots.addLayer(m); DRAWN.add(r.p.id);
    }
    drawExtra();
    drawRing();
  }
  function selRefs(sj) { return ownStudy(sj) ? [] : refsFor(sj); }   // studies the subject's estimate uses, with distance
  function drawRing() {
    ring.clearLayers();
    const c = S.ctr, e = S.selE, sj = e && subjOf(e);
    // The radius circle sits on the area's center, or on the selected property when no area is set
    const at = c || (e && !ownStudy(sj) ? e : null);
    if (at) L.circle([at.lat, at.lon], { renderer: reachRenderer, radius: S.radius * 1609.344, color: '#1f4e99', weight: 1.5, dashArray: '6 6', fillColor: '#1f4e99', fillOpacity: 0.05, interactive: false }).addTo(ring);
    if (c) L.circleMarker([c.lat, c.lon], { renderer: reachRenderer, radius: 5, color: '#1f4e99', weight: 2.5, fillColor: '#fff', fillOpacity: 1, interactive: false }).addTo(ring);
    if (!e) return;
    const refs = selRefs(sj);
    // Studies at the same property share one line and one label.
    const atP = new Map();
    for (const o of refs) { if (!atP.has(o.r.p)) atP.set(o.r.p, []); atP.get(o.r.p).push(o); }
    for (const [sp, os] of atP) {
      L.polyline([[e.lat, e.lon], [sp.lat, sp.lon]], { renderer: reachRenderer, color: '#1f4e99', weight: 2, opacity: 0.8, interactive: false }).addTo(ring);
      if (atP.size <= 8) L.tooltip({ permanent: true, direction: 'right', offset: [8, 0], className: 'reftip' })
        .setLatLng([sp.lat, sp.lon]).setContent(`${esc(os[0].r.name)} · ${mi(os[0].d)} mi · ` + os.map(o => `${esc(o.r.firm)} ${esc(o.r.date.slice(0, 7))}`).join(', ')).addTo(ring);
    }
    L.circleMarker([e.lat, e.lon], { radius: 12, color: '#b42318', weight: 3, fill: false, interactive: false }).addTo(ring);
  }

  /* ---------- detail ---------- */
  // Select any place: a screener property, another HUD property, a LIHTC project, a rent-study property or a pin
  function selectEnt(e, fromTable) {
    S.sel = e.key; S.selE = e;
    history.replaceState(null, '', e.pin ? location.pathname + location.search : '#sel=' + encodeURIComponent(e.key));
    $$('#ctbl tbody tr').forEach(tr => tr.classList.toggle('sel', tr.dataset.id === e.key));
    if (!fromTable) { const tr = $$('#ctbl tbody tr').find(tr => tr.dataset.id === e.key); if (tr) tr.scrollIntoView({ block: 'nearest' }); }
    drawRing();
    renderSel();
    // Frame the place, the studies it uses and the radius circle, keeping clear of the detail panel that covers the map's right side.
    const sj = subjOf(e), refs = selRefs(sj), padR = Math.min($('#detail').offsetWidth, $('#map').offsetWidth * 0.7) + 20;
    const pts = [[e.lat, e.lon], ...refs.map(o => [o.r.p.lat, o.r.p.lon])];
    const at = S.ctr || (!ownStudy(sj) ? e : null);
    if (at) { const c = L.latLng(at.lat, at.lon).toBounds(S.radius * 1609.344 * 2); pts.push(c.getSouthWest(), c.getNorthEast()); }
    map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [20, 20], paddingBottomRight: [padR, 20], maxZoom: 15 });
  }
  function select(p, fromTable) { selectEnt(ENT.get(p.id) || entOfP(p), fromTable); }
  function renderSel() { const e = S.selE; if (!e) return; if (isScreenP(e)) renderDetail(e.p); else renderOther(e); }
  function sourceSection(p, row) {
    const own = ownStudy(p), beds = [...new Set(p.lines.map(l => l.bed))].sort((a, b) => a - b);
    let h = '<h3>Where the estimate comes from</h3>';
    if (own) {
      const mode = modeFor(own);
      return h + `<p class="note">This property's own rent study (${esc(own.firm)}, ${esc(own.date)}, ${esc(own.signer || 'signer unknown')}), ${mode === 'asis' ? 'used as concluded' : 'moved with SAFMR since the study date'}. Its details are below.</p>`;
    }
    const refs = refsFor(p);
    if (!refs.length) return h + noStudyNote(p);
    h += `<p class="note">${plural(refs.length, 'rent study')} within ${S.radius} miles, ${HOW[S.combine]}. Each column is that study's market gross as % of SAFMR for the bedroom count${S.bedMatch ? '; <span class="est">*</span> = the study has no unit of that size, so its median is used' : ' (study medians)'}.</p>`;
    return h + refTable(refs, beds);
  }
  const HOW = { idw: 'averaged, closer studies counting more (weight = 1 ÷ distance)', median: 'combined by median', nearest: 'nearest study only' };
  function refTable(refs, beds) {
    let h = `<div class="scrollx"><table class="dt"><thead><tr><th>Study property</th><th class="num">Mi</th><th>Done</th><th>Firm</th>${beds.map(b => `<th class="num">${bedName(b)}</th>`).join('')}${S.combine === 'idw' ? '<th class="num">Weight</th>' : ''}</tr></thead><tbody>`;
    const perBed = Object.fromEntries(beds.map(b => [b, combine(refs, b)]));
    refs.forEach((o, i) => {
      h += `<tr><td class="wrap"><button class="link" data-goto="${esc(o.r.id)}">${esc(o.r.name)}</button><div class="subnote">${esc(o.r.p.city)}${o.r.prelim ? ' · prelim' : ''}${modeFor(o.r) === 'age' ? ' · moved with SAFMR' : ''}</div></td>
        <td class="num">${mi(o.d)}</td><td>${esc(o.r.date)}</td><td class="wrap">${esc(o.r.firm)}<div class="subnote">${esc(o.r.signer || '')}</div></td>` +
        beds.map(b => { const x = perBed[b].parts[i]; return `<td class="num">${pct(x.k)}${x.match ? '' : '<span class="est">*</span>'}</td>`; }).join('') +
        (S.combine === 'idw' ? `<td class="num">${pct(perBed[beds[0]].parts[i].share)}</td>` : '') + '</tr>';
    });
    h += `<tr class="tot"><td><b>Used here</b></td><td></td><td></td><td></td>${beds.map(b => `<td class="num"><b>${pct(perBed[b].k)}</b></td>`).join('')}${S.combine === 'idw' ? '<td></td>' : ''}</tr></tbody></table></div>`;
    return h;
  }
  // No study in range: the nearest one, and a button to widen the radius to it
  function noStudyNote(sj) {
    if (!sj.near) sj.near = nearList(sj, sj.self || sj);
    const nearest = sj.near.find(o => studyOk(o.r));
    let h = `<p class="note">No rent study within ${S.radius} miles${S.fallback === 'state' ? `, so the ${FB.toLowerCase()} ${S.ratio}% is used` : ''}.`;
    if (nearest) h += ` The nearest is <button class="link" data-goto="${esc(nearest.r.id)}">${esc(nearest.r.name)}</button>, ${mi(nearest.d)} miles away (${esc(nearest.r.firm)}, ${esc(nearest.r.date)}).
      ${nearest.d <= RMAX ? `<button class="link" data-widen="${Math.ceil(nearest.d)}">Widen the radius to ${Math.ceil(nearest.d)} miles</button>` : `That is beyond the ${RMAX}-mile limit.`}`;
    return h + '</p>';
  }
  // Market rents by bedroom at any place from the rent studies (own study, else those in the radius) × its ZIP's FY2027 SAFMR
  function marketSection(sj, zip) {
    const beds = [0, 1, 2, 3, 4], own = ownStudy(sj), ks = beds.map(b => subjectK(sj, b));
    let h = '<h3>Market rent here, from rent studies</h3>';
    if (!ks.some(x => ok(x.k))) return h + noStudyNote(sj);
    h += `<div class="scrollx"><table class="dt"><thead><tr><th>BR</th><th class="num">FY2027 SAFMR</th><th class="num">Market %</th><th class="num">Est. market gross</th></tr></thead><tbody>` +
      beds.map((b, i) => { const sf = safAt(zip, b), k = ks[i].k; return `<tr><td>${bedName(b)}</td><td class="num">${money(sf)}</td><td class="num">${pct(k)}</td><td class="num"><b>${ok(k) && sf ? money(k * sf) : '–'}</b></td></tr>`; }).join('') +
      '</tbody></table></div>';
    h += `<p class="note">Gross = rent + tenant-paid utilities; subtract a utility allowance for a contract rent. SAFMR for ZIP ${esc(zip || 'unknown')}${SAF[zip] ? ` (${esc(SAF[zip][0])})` : ', which is not in the SAFMR file, so only the % is shown'}.</p>`;
    if (own) h += `<p class="note">From this property's own rent study (${esc(own.firm)}, ${esc(own.date)}), ${modeFor(own) === 'asis' ? 'used as concluded' : 'moved with SAFMR since the study date'}. Its details are below.</p>`;
    else if (ks[0].basis === 'near') { const refs = refsFor(sj); h += `<p class="note">${plural(refs.length, 'rent study')} within ${S.radius} miles, ${HOW[S.combine]}${S.bedMatch ? '; <span class="est">*</span> = the study has no unit of that size, so its median is used' : ''}.</p>` + refTable(refs, beds); }
    else if (ks[0].basis === 'state') h += noStudyNote(sj);
    return h;
  }
  // Any place that is not a screener property: another HUD property, a LIHTC project, a rent-study property elsewhere, or a pin
  function renderOther(e) {
    const sj = subjOf(e), h = e.h, q = e.lih, zip = e.zip || nearestZip(e.lat, e.lon);
    const where = [e.addr, [[e.city, e.st].filter(Boolean).join(', '), e.zip].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    const at = e.pin ? `${e.lat.toFixed(5)}, ${e.lon.toFixed(5)}${zip ? ` · ZIP ${zip}` : ''}` : where || `${e.lat.toFixed(5)}, ${e.lon.toFixed(5)}`;
    let x = `<h2>${esc(e.name)} ${kindBadges(e)}</h2><div class="muted">${esc(at)}${e.county ? ` · ${esc(e.county)} County` : ''}</div>`;
    const links = [];
    if (e.hud && e.id) links.push(`<a href="../#sel=${esc(e.id)}" target="_blank" rel="noopener">Open on the national map</a>`);
    if (e.p && e.p.away && !NAT && stName[e.st]) links.push(`<a href="?st=${esc(e.st)}#sel=${esc(e.p.id)}">Open in the ${esc(stName[e.st])} screener</a>`);
    if (links.length) x += `<p class="tiny">${links.join(' · ')}</p>`;
    x += '<dl class="kv">';
    if (e.hud) x += `<dt>HUD property ID</dt><dd>${esc(e.id || '–')}</dd>`;
    if (e.owner) x += `<dt>Owner</dt><dd>${esc(e.owner)}</dd>`;
    if (e.mgmt) x += `<dt>Management agent</dt><dd>${esc(e.mgmt)}</dd>`;
    if (e.units != null) x += `<dt>Units</dt><dd>${int(e.units)}${h && h[10] != null && h[10] !== h[9] ? ` (${int(h[10])} assisted)` : ''}</dd>`;
    if (h) x += `<dt>HUD category</dt><dd>${esc(h[18] || '–')}</dd><dt>Active HUD contracts</dt><dd>${h[15] ? `${h[15]} (${esc(h[14] || 'type not on file')}) · term ends ${esc(h[16] || '?')} · overall ${esc(h[17] || '?')}` : "None in HUD's active list"}</dd>`;
    if (q) x += `<dt>LIHTC</dt><dd>${esc(lihTxt(q))}${q[6] ? ` · ${int(q[6])} low-income units` : ''}${q[14] ? `<div class="subnote">${esc(q[14])}</div>` : ''}</dd>`;
    if (ZN && !e.pin) x += `<dt>2027 QCT / DDA</dt><dd>${zoneTxt(e.zone || 0) || 'Neither'}</dd>`;
    x += '</dl>';
    if (e.approx) x += '<p class="note">Location approximate (ZIP or area centre), so distances are rough.</p>';
    const why = e.pin ? 'A point on the map.' : e.p && e.p.away ? `In ${esc(stName[e.st] || e.st)}, outside this screen; its rent studies feed estimates nearby.`
      : e.p && e.p.nohud ? 'Not a HUD property; its rent study feeds estimates nearby.'
      : e.hud ? "Not in the screener: HUD's rent file has no Section 8 rent lines on an active contract here, so there is no contract-rent gap."
      : 'LIHTC project, not a HUD property, so there is no HUD contract rent.';
    const isCtr = S.ctr && S.ctr.key === e.key;
    x += `<div class="callout muted">${why} The market rents below come from the rent studies near it.${isCtr ? '' : `<div><button class="btn small" data-center="${esc(e.key)}">List everything within ${S.radius} mi of here</button></div>`}</div>`;
    x += marketSection(sj, zip);
    if (e.p && e.p.studies) x += studySections(e.p);
    $('#detailBody').innerHTML = x;
    $('#detail').hidden = false;
  }
  // ZIP for a point with no address: the nearest property's ZIP that is in the SAFMR file (within 5 miles)
  function nearestZip(lat, lon) {
    let best = null;
    for (const e of ENT.values()) {
      if (e.lat == null || !e.zip || !SAF[e.zip] || Math.abs(e.lat - lat) > 0.08) continue;
      const d = dist({ lat, lon }, e); if (d <= 5 && (!best || d < best.d)) best = { d, z: e.zip };
    }
    return best ? best.z : null;
  }
  function renderDetail(p) {
    const row = OUT.find(r => r.p === p);
    const okc = p.cons.map(conOk);
    let h = `<h2>${esc(p.name)}</h2><div class="muted">${p.addr ? esc(p.addr) + ', ' : ''}${esc(p.city)}, ${esc(p.state)} ${esc(p.zip)}${p.county ? ` · ${esc(p.county)} County` : ''}</div>
      ${p.nohud ? `<div class="callout muted">${esc(p.nohud)} Its rent study is loaded so estimates for nearby HUD properties can use it; it has no HUD contracts or rent lines.</div>`
        : `<p class="tiny"><a href="../#sel=${esc(p.id)}" target="_blank" rel="noopener">Open on the national map</a></p>`}
      <dl class="kv"><dt>HUD property ID</dt><dd>${p.nohud ? '–' : esc(p.id)}</dd><dt>Owner</dt><dd>${esc(p.owner || '–')}${p.ownerType ? ` <span class="muted">(${esc(p.ownerType)})</span>` : ''}</dd>
      <dt>Management agent</dt><dd>${esc(p.mgmt || '–')}</dd><dt>Units (total / assisted)</dt><dd>${int(p.total)} / ${int(p.assisted)}</dd>
      <dt>SAFMR area</dt><dd>${esc(p.area || 'ZIP not in the SAFMR file')}</dd>${ZN ? `<dt>2027 QCT / DDA</dt><dd>${zoneTxt(p.zone ?? zoneOf(p.id)) || 'Neither'}</dd>` : ''}
      ${(() => { const q = (ENT.get(p.id) || {}).lih; return q ? `<dt>LIHTC</dt><dd>${esc(lihTxt(q))}${q[6] ? ` · ${int(q[6])} low-income units` : ''}</dd>` : ''; })()}</dl>
      ${S.ctr && S.ctr.key === p.id ? '' : `<p class="tiny"><button class="link" data-center="${esc(p.id)}">List everything within ${S.radius} mi of this property</button></p>`}`;
    if (row && row.est) h += `<div class="callout">Estimated gap <b class="${sgn(row.gapU)}">${money(row.gapU)}</b> per unit per month · <b class="${sgn(row.annual)}">${money(row.annual)}</b> a year on ${int(row.units)} units` +
      (S.fee && row.annual > 0 ? ` · fee at ${S.fee}%: <b>${money(feeOf(row.annual))}</b>/yr` : '') + `<div class="subnote">From: ${esc(row.basis)}. Changes with the settings on the left.</div></div>`;
    else if (row) h += `<div class="callout muted">No estimate: no usable rent study within ${S.radius} miles.</div>`;
    else if (p.lines.length) h += `<div class="callout muted">Not in the current list: no rent line passes the filters on the left${!S.showNoEst ? ', or it has no estimate' : ''}.</div>`;
    else if (!p.nohud) h += `<div class="callout muted">No HUD rent lines on file for this property, so it has no estimate. Its rent study is used for properties near it.</div>`;
    if (p.lines.length) h += sourceSection(p, row) + `<h3>Rents vs FY2027 SAFMR</h3><div class="scrollx"><table class="dt"><thead><tr><th>BR</th><th class="num">Units</th><th class="num">Contract</th><th class="num">UA</th><th class="num">Gross</th><th class="num">SAFMR</th><th class="num">% SAFMR</th><th class="num">Market %</th><th class="num">Est. market</th><th class="num">Gap</th><th>Contract</th></tr></thead><tbody>`;
    for (const ln of [...p.lines].sort((a, b) => a.bed - b.bed)) {
      const e = lineEst(p, ln), c = p.cons[ln.c];
      h += `<tr class="${okc[ln.c] ? '' : 'off'}"><td>${bedName(ln.bed)}</td><td class="num">${ln.units}</td><td class="num">${money(ln.rent)}</td><td class="num">${money(ln.ua)}</td><td class="num">${money(e.gross)}</td>
        <td class="num">${money(e.saf)}${e.safSrc === 'area FMR' ? ' <span class="est">FMR</span>' : ''}</td><td class="num">${pct(e.curPct)}</td><td class="num">${pct(e.k)}</td><td class="num">${money(e.estRent)}</td>
        <td class="num ${sgn(e.gap)}">${money(e.gap)}</td><td>${esc(c.no)}</td></tr>`;
    }
    if (p.lines.length) h += `</tbody></table></div><p class="note">Est. market = market % × SAFMR − UA (contract-rent basis). Gap = est. market − contract rent.${p.lines.some(ln => !okc[ln.c]) ? ' Grey rows are on contracts the filters leave out.' : ''}</p>`;
    h += studySections(p);
    if (p.cons.length) h += `<h3>Contracts</h3>`;
    for (const [i, c] of p.cons.entries()) {
      h += `<div class="contract${okc[i] ? '' : ' dim'}"><div class="contract-head"><b>${esc(c.no)}</b><span>${esc(c.doc || 'no doc type')}</span><span class="muted">${esc(c.prog || '')}</span><span class="muted">${esc(c.status || 'not in active list')}</span></div>
        <dl class="kv"><dt>Assisted units</dt><dd>${int(c.units)}</dd><dt>Current term</dt><dd>${esc(c.eff || '?')} to ${esc(c.exp || '?')}${c.term ? ` (${c.term} months)` : ''}</dd>
        <dt>Overall expiration</dt><dd>${esc(c.ovExp || '–')}</dd><dt>Renewal option</dt><dd>${esc(c.ropt || '–')}</dd></dl></div>`;
    }
    $('#detailBody').innerHTML = h;
    $('#detail').hidden = false;
  }
  function studySections(p) {
    let h = '';
    const own = ownStudy(p);
    for (const r of p.studies || []) {
      const tag = r === own ? ' <span class="b rcs">used</span>' : !studyOk(r) ? ' <span class="muted">· left out by the filters</span>' : '';
      h += `<h3>${p.studies.length > 1 ? `${esc(r.firm)} rent study` : `This property's rent study · ${esc(r.firm)}`}${tag}</h3>
        <dl class="kv"><dt>Last done</dt><dd>${esc(r.date)}${r.prelim ? ' <span class="b pre">prelim</span>' : ''}</dd><dt>Signed by</dt><dd>${esc(r.signer || '–')}</dd>
        <dt>Client</dt><dd>${esc(r.client || '–')}</dd><dt>Source</dt><dd>${esc(r.kind)}<br><span class="subnote">${esc(r.file)}</span></dd>
        <dt>SAFMR compared</dt><dd>${esc(r.vintage)}, ZIP ${esc(r.zip)}</dd><dt>Median % of SAFMR</dt><dd><b>${pct(r.ratio)}</b> then · ${pct(r.ratio27)} of FY2027</dd>
        <dt>Used by</dt><dd>${int(REACH[r.sid] || 0)} properties in the current screen (within ${S.radius} mi)</dd></dl>`;
      if (r.note) h += `<p class="note">${esc(r.note)}</p>`;
      h += `<div class="scrollx"><table class="dt"><thead><tr><th>Unit</th><th class="num">SF</th><th class="num">Units</th><th class="num">Contract then</th><th class="num">As is</th><th class="num">Renovated</th><th class="num">UA</th><th class="num">Gross</th><th class="num">SAFMR then</th><th class="num">%</th><th class="num">% FY27</th></tr></thead><tbody>`;
      for (const x of r.asis) h += `<tr><td>${esc(x.unit)}</td><td class="num">${int(x.sf)}</td><td class="num">${int(x.units)}</td><td class="num">${money(x.contract)}</td><td class="num"><b>${money(x.rcs)}</b></td>
        <td class="num">${money(x.renRow && x.renRow.rcs)}</td><td class="num">${money(x.ua)}${uaTag(x)}</td><td class="num">${money(x.gross)}</td>
        <td class="num">${money(x.safmr)}${estTag(x)}</td><td class="num"><b>${pct(x.pct)}</b></td><td class="num">${pct(x.pct27)}</td></tr>`;
      h += `</tbody></table></div>`;
    }
    const hist = p.rcs ? p.rcs.history : [];
    if (hist.length > 1) {
      h += `<h3>Study history <span class="muted">· ${hist.length} on file</span></h3><div class="scrollx"><table class="dt"><thead><tr><th>Date</th><th>Firm</th><th>Signed by</th><th>Source</th><th>As-is rents</th><th>Renovated</th></tr></thead><tbody>`;
      for (const s of [...hist].reverse()) h += `<tr><td>${esc(s.date)}${s.prelim ? ' <span class="b pre">prelim</span>' : ''}</td><td>${esc(s.firm)}</td><td>${esc(s.signer || '–')}</td><td class="wrap">${esc(s.kind)}</td>
        <td class="wrap">${s.asis.map(([u, v]) => `${esc(u)} ${money(v)}`).join('<br>')}</td><td class="wrap">${s.ren.map(([u, v]) => `${esc(u)} ${money(v)}`).join('<br>') || '–'}</td></tr>`;
      h += `</tbody></table></div>`;
    }
    return h;
  }
  $('#detailBody').addEventListener('click', e => {
    const g = e.target.closest('[data-goto]'), w = e.target.closest('[data-widen]'), c = e.target.closest('[data-center]');
    if (g) { const en = ENT.get(g.dataset.goto); if (en) selectEnt(en, false); }
    if (w) { S.radius = Math.min(+w.dataset.widen, RMAX); syncControls(); refresh(); if (S.selE) selectEnt(S.selE, false); }
    if (c) { const en = ENT.get(c.dataset.center) || (S.selE && S.selE.key === c.dataset.center ? S.selE : null); if (en) { setCenter(en); selectEnt(en, false); } }
  });
  $('#closeDetail').addEventListener('click', closeDetail);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || $('#about').open) return;
    if (!$('#sugg').hidden) { $('#sugg').hidden = true; return; }
    if (PIN) { setPin(false); return; }
    closeDetail();
  });
  // The whole state, or in the national view the lower 48 (Alaska, Hawaii and Puerto Rico would zoom the map far out).
  function fitHome() {
    if (NAT && !S.stf) return map.fitBounds([[24.5, -124.8], [49.4, -66.9]]);
    const pts = P.filter(p => p.lat != null && (!S.stf || p.state === S.stf)).map(p => [p.lat, p.lon]);
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [10, 10] });
  }
  function closeDetail() { $('#detail').hidden = true; S.sel = null; S.selE = null; history.replaceState(null, '', location.pathname + location.search); $$('#ctbl tbody tr.sel').forEach(tr => tr.classList.remove('sel')); drawRing(); }

  /* ---------- controls ---------- */
  const county = $('#county'), stateF = $('#stateF');
  // County names repeat across states, so in the national view the County list waits for a state.
  function fillCounties() {
    county.innerHTML = `<option value="">${NAT && !S.stf ? 'Pick a state first' : 'All counties'}</option>`;
    county.disabled = NAT && !S.stf;
    for (const c of [...new Set(P.filter(p => !NAT || p.state === S.stf).map(p => p.county).filter(Boolean))].sort()) county.insertAdjacentHTML('beforeend', `<option>${esc(c)}</option>`);
  }
  if (NAT) {
    $('#stateFRow').hidden = false;
    for (const c of [...new Set(P.map(p => p.state))].sort((a, b) => (stName[a] || a).localeCompare(stName[b] || b)))
      stateF.insertAdjacentHTML('beforeend', `<option value="${esc(c)}">${esc(stName[c] || c)}</option>`);
  }
  $('#radius').max = RMAX;
  const calSel = $('#cal');
  for (const k in CAL) calSel.insertAdjacentHTML('beforeend', `<option value="${esc(k)}">${esc(CAL[k][0])} (${RCS.filter(CAL[k][1]).length})</option>`);
  $('#fallback option[value="state"]').textContent = FB === 'National' ? 'Use a national %' : FB === 'Statewide' ? 'Use a statewide %' : 'Use a % from the studies loaded (this state has fewer than 5)';
  $('#f-doc').innerHTML = DOCS.filter(d => docCount[d]).map(d => `<label class="chk"><input type="checkbox" data-doc="${d}"> ${d === '—' ? 'No contract type on file' : d}<span class="n">${docCount[d]}</span></label>`).join('');
  $('#f-firm').innerHTML = FIRMS.map(f => `<label class="chk"><input type="checkbox" data-firm="${esc(f)}"> ${esc(f)}<span class="n">${firmN[f]}</span></label>`).join('');
  $('#f-ropt').innerHTML = ROPTS.map(r => `<label class="chk"><input type="checkbox" data-ropt="${esc(r)}"> <span><b>${esc(r)}</b> ${esc(ropLabel[r])}</span><span class="n">${ropCount[r]}</span></label>`).join('');
  function syncControls() {
    if (NAT) stateF.value = S.stf;
    fillCounties();
    county.value = S.county; $('#areaOnly').checked = S.areaOnly; $('#radius').value = S.radius; $('#combine').value = S.combine; calSel.value = S.cal;
    $('#bedMatch').checked = S.bedMatch; $('#useOwn').checked = S.useOwn; $('#rcsMode').value = S.rcsMode; $('#fallback').value = S.fallback;
    $('#stateBox').hidden = S.fallback !== 'state'; $('#ratio').value = S.ratio; $('#fee').value = S.fee;
    $('#oldCons').checked = S.oldCons; $('#exp').value = S.exp; $('#minUnits').value = S.minUnits; $('#minGap').value = S.minGap; $('#minAnnual').value = S.minAnnual;
    $('#rcsOnly').checked = S.rcsOnly; $('#showNoEst').checked = S.showNoEst; $('#zone').value = S.zone;
    $$('[data-doc]').forEach(i => { i.checked = S.docs.has(i.dataset.doc); });
    $$('[data-ropt]').forEach(i => { i.checked = S.ropts.has(i.dataset.ropt); });
    $$('[data-firm]').forEach(i => { i.checked = S.firms.has(i.dataset.firm); });
  }
  function renderCal() {
    const c = CALNOW;
    $('#ratioVal').textContent = S.ratio + '%';
    $('#covStats').textContent = `${COV.est.toLocaleString()} of ${COV.n.toLocaleString()} properties in the screen get an estimate at this radius.`;
    $('#calStats').innerHTML = c.n ? `The ${c.n} studies in use: median <b>${pct(c.med)}</b> of the SAFMR in effect on the study date (25th–75th pct ${pct(c.p25)}–${pct(c.p75)}).` : 'No studies in this set.';
    const yr = Object.keys(c.byYear).sort(), bd = Object.keys(c.byBed).sort();
    $('#calTables').innerHTML = `<table class="mini"><thead><tr><th>Study year</th><th class="num">Properties</th><th class="num">Median</th><th class="num">25th–75th</th></tr></thead><tbody>` +
      yr.map(y => `<tr><td>${y}</td><td class="num">${c.byYear[y].length}</td><td class="num">${pct(median(c.byYear[y]))}</td><td class="num">${pct(quant(c.byYear[y], 0.25))}–${pct(quant(c.byYear[y], 0.75))}</td></tr>`).join('') +
      `</tbody></table><table class="mini"><thead><tr><th>Bedrooms</th><th class="num">Properties</th><th class="num">Median</th></tr></thead><tbody>` +
      bd.map(b => `<tr><td>${bedName(+b)}</td><td class="num">${c.byBed[b].length}</td><td class="num">${pct(median(c.byBed[b]))}</td></tr>`).join('') +
      `</tbody></table><p class="hint">One vote per study (each firm's latest at a property): the median of its as-is unit types, vs the SAFMR on the study date.</p>`;
    $('#f-doc-n').textContent = `${S.docs.size} of ${DOCS.filter(d => docCount[d]).length}`;
    $('#f-ropt-n').textContent = `${S.ropts.size} of ${ROPTS.length}`;
    $('#f-firm-n').textContent = S.firms.size === FIRMS.length ? `all ${FIRMS.length}` : `${S.firms.size} of ${FIRMS.length}`;
  }
  function renderCtr() {
    $('#ctrInfo').innerHTML = S.ctr ? `Area: <b>${esc(S.ctr.label)}</b> · ${S.radius} mi · see the Nearby tab` : 'No area set. Pick a search result or drop a pin to see everything within the radius.';
    const tf = $('#textF');
    tf.hidden = !S.q; tf.innerHTML = S.q ? `Tables filtered to “${esc(S.q)}” · <button class="link" id="clearTextF">clear</button>` : '';
  }
  function refresh() { S.limit = 300; build(); renderCal(); renderCtr(); renderTable(); drawMarkers(); if (S.selE && !$('#detail').hidden) renderSel(); }
  $('#textF').addEventListener('click', e => { if (e.target.id === 'clearTextF') { S.q = ''; refresh(); } });

  /* ---------- search any place, set the area ---------- */
  function setCenter(e) {
    S.ctr = e ? { lat: e.lat, lon: e.lon, label: e.name, key: e.key } : null;
    if (e) setView('near'); else if (S.view === 'near') setView('props');
    refresh();
  }
  $('#clearCtr').addEventListener('click', () => { $('#q').value = ''; setCenter(null); });
  let PIN = false;
  function setPin(on) { PIN = on; document.body.classList.toggle('pinmode', on); $('#pinBtn').classList.toggle('on', on); $('#pinBtn').textContent = on ? 'Click the map…' : 'Drop a pin'; }
  $('#pinBtn').addEventListener('click', () => setPin(!PIN));
  map.on('click', ev => { if (!PIN) return; setPin(false); pinAt(ev.latlng.lat, ev.latlng.lng, 'Dropped pin'); });
  function pinAt(lat, lon, label, zip) {
    $('#sugg').hidden = true;
    const e = { key: 'pin', pin: true, name: label, lat, lon, zip: zip || nearestZip(lat, lon), hud: false, lih: null, p: null, h: null };
    setCenter(e); selectEnt(e, false);
  }
  function pick(e) { $('#sugg').hidden = true; $('#q').value = e.name; setCenter(e); selectEnt(e, false); }
  let suggItems = [], suggHi = -1;
  function showSugg(items) {
    suggItems = items; suggHi = items.length ? 0 : -1;
    const el = $('#sugg');
    if (!items.length) { el.hidden = true; return; }
    el.innerHTML = items.map((it, i) => `<div data-i="${i}" class="${i === suggHi ? 'hi' : ''}">${it.html}</div>`).join('');
    el.hidden = false;
  }
  function matches(q) {
    const toks = q.toLowerCase().replace(/[.,;#]/g, ' ').split(/\s+/).filter(Boolean), qt = q.trim().toLowerCase();
    if (!toks.length) return [];
    const res = [];
    for (const e of ENT.values()) {
      if (e.lat == null || !toks.every(t => e.hay.includes(t))) continue;
      const nm = e.lname, sc = (e.id && e.id.toLowerCase() === qt) || (e.lihId && e.lihId.toLowerCase() === qt) || nm === qt ? 0 : nm.startsWith(qt) ? 1 : nm.startsWith(toks[0]) ? 2 : nm.includes(toks[0]) ? 3 : 4;
      res.push([sc - (studyOf(e) ? 0.5 : 0) - (isScreenP(e) ? 0.2 : 0), e]);
      if (res.length > 800) break;
    }
    return res.sort((a, b) => a[0] - b[0]).slice(0, 10).map(x => x[1]);
  }
  function suggest() {
    const q = $('#q').value.trim();
    if (!q) return showSugg([]);
    const items = matches(q).map(e => ({ html: `${esc(e.name)} ${kindBadges(e)}<small>${esc([e.addr, e.city, e.st, e.zip].filter(Boolean).join(', '))}${e.id ? ' · ' + esc(e.id) : e.lihId ? ' · ' + esc(e.lihId) : ''}${e.approx ? ' · approximate location' : ''}</small>`, go: () => pick(e) }));
    if (/^\d{5}$/.test(q)) {
      const zs = [...ENT.values()].filter(e => e.zip === q && e.lat != null && !e.approx);
      if (zs.length) items.unshift({ html: `ZIP ${esc(q)}<small>Center on the ${zs.length} properties in this ZIP${SAF[q] ? ' · ' + esc(SAF[q][0]) : ''}</small>`,
        go: () => pinAt(zs.reduce((a, e) => a + e.lat, 0) / zs.length, zs.reduce((a, e) => a + e.lon, 0) / zs.length, `ZIP ${q}`, q) });
    }
    const ll = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (ll) items.unshift({ html: `Use coordinates ${esc(q)}`, go: () => pinAt(+ll[1], +ll[2], `Coordinates ${q}`) });
    else items.push({ html: `Find address on map: “${esc(q)}”<small>Esri World Geocoder (sends this text to geocode.arcgis.com)</small>`, go: () => geocode(q) });
    items.push({ html: `Only list properties matching “${esc(q)}”<small>Text filter on the Screener, Rents by bedroom and Rent studies tabs</small>`, go: () => { $('#sugg').hidden = true; S.q = q; refresh(); } });
    if (!HUDALL && !PUBERR) items.push({ html: '<small>Still loading every HUD property and LIHTC project; more results in a moment.</small>', go: () => {} });
    showSugg(items);
  }
  async function geocode(q) {
    const el = $('#sugg');
    el.hidden = false; el.innerHTML = '<div>Geocoding…</div>';
    try {
      const u = 'https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?' +
        new URLSearchParams({ SingleLine: q, f: 'json', maxLocations: '6', countryCode: 'USA', outFields: 'Match_addr,Postal' });
      const d = await (await fetch(u)).json();
      const cands = (d.candidates || []).filter(c => c.score >= 70);
      if (!cands.length) { el.innerHTML = '<div>No address match.</div>'; return; }
      showSugg(cands.map(c => ({ html: `${esc(c.address)}<small>match score ${Math.round(c.score)}</small>`,
        go: () => pinAt(c.location.y, c.location.x, c.address, c.attributes && /^\d{5}$/.test(c.attributes.Postal || '') ? c.attributes.Postal : null) })));
    } catch (err) { el.innerHTML = '<div>Address search failed. Try again.</div>'; }
  }
  let qT;
  $('#q').addEventListener('input', e => { clearTimeout(qT); qT = setTimeout(suggest, 140); });
  $('#q').addEventListener('keydown', e => {
    const el = $('#sugg');
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!suggItems.length) return;
      suggHi = (suggHi + (e.key === 'ArrowDown' ? 1 : -1) + suggItems.length) % suggItems.length;
      [...el.children].forEach((c, i) => c.classList.toggle('hi', i === suggHi)); e.preventDefault();
    } else if (e.key === 'Enter') { e.preventDefault(); if (el.hidden) suggest(); else if (suggItems[suggHi]) suggItems[suggHi].go(); }
  });
  $('#sugg').addEventListener('click', e => { const d = e.target.closest('[data-i]'); if (d) suggItems[+d.dataset.i]?.go(); });
  document.addEventListener('click', e => { if (!e.target.closest('.searchwrap')) $('#sugg').hidden = true; });
  county.addEventListener('change', () => { S.county = county.value; refresh(); });
  stateF.addEventListener('change', () => { S.stf = stateF.value; S.county = ''; syncControls(); refresh(); fitHome(); });
  $('#radius').addEventListener('change', e => { const v = +e.target.value; if (v > 0) { S.radius = Math.min(v, RMAX); syncControls(); refresh(); } else syncControls(); });
  $$('[data-r]').forEach(b => b.addEventListener('click', () => { S.radius = +b.dataset.r; syncControls(); refresh(); }));
  $('#ratio').addEventListener('input', e => { S.ratio = +e.target.value; $('#ratioVal').textContent = S.ratio + '%'; clearTimeout(qT); qT = setTimeout(refresh, 60); });
  $$('[data-q]').forEach(b => b.addEventListener('click', () => { const v = calib('all')[b.dataset.q]; if (ok(v)) { S.ratio = Math.round(v * 100); syncControls(); refresh(); } }));
  const bind = (id, k, f = x => x) => $(id).addEventListener('change', e => { S[k] = f(e.target.type === 'checkbox' ? e.target.checked : e.target.value); syncControls(); refresh(); });
  bind('#combine', 'combine'); bind('#cal', 'cal'); bind('#bedMatch', 'bedMatch'); bind('#useOwn', 'useOwn'); bind('#rcsMode', 'rcsMode'); bind('#fallback', 'fallback');
  bind('#fee', 'fee', v => (ok(v) ? +v : 0)); bind('#oldCons', 'oldCons'); bind('#exp', 'exp');
  bind('#minUnits', 'minUnits'); bind('#minGap', 'minGap'); bind('#minAnnual', 'minAnnual'); bind('#rcsOnly', 'rcsOnly'); bind('#showNoEst', 'showNoEst'); bind('#zone', 'zone');
  bind('#areaOnly', 'areaOnly');
  $('#f-doc').addEventListener('change', e => { const d = e.target.dataset.doc; e.target.checked ? S.docs.add(d) : S.docs.delete(d); refresh(); });
  $('#f-ropt').addEventListener('change', e => { const r = e.target.dataset.ropt; e.target.checked ? S.ropts.add(r) : S.ropts.delete(r); refresh(); });
  $('#f-firm').addEventListener('change', e => { const f = e.target.dataset.firm; e.target.checked ? S.firms.add(f) : S.firms.delete(f); refresh(); });
  $('[data-all="firm"]').addEventListener('click', () => { S.firms = new Set(FIRMS); syncControls(); refresh(); });
  $('[data-none="firm"]').addEventListener('click', () => { S.firms = new Set(); syncControls(); refresh(); });
  $('[data-all="ropt"]').addEventListener('click', () => { S.ropts = new Set(ROPTS); syncControls(); refresh(); });
  $('[data-none="ropt"]').addEventListener('click', () => { S.ropts = new Set(); syncControls(); refresh(); });
  $('#resetAll').addEventListener('click', () => { const f = S.stf; Object.assign(S, DEF()); $('#q').value = ''; syncControls(); refresh(); if (f) fitHome(); });
  function setView(v) { S.view = v; $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === v)); }
  $$('.tab').forEach(t => t.addEventListener('click', () => { setView(t.dataset.view); S.limit = 300; renderTable(); drawMarkers(); }));
  $('#filtersBtn').addEventListener('click', () => document.body.classList.toggle('filters-open'));

  /* ---------- CSV ---------- */
  $('#exportBtn').addEventListener('click', () => {
    const V = VIEWS[S.view], rows = sorted();
    const cell = v => { if (v == null || (typeof v === 'number' && !isFinite(v))) return ''; const s = typeof v === 'number' ? String(Math.round(v * 10000) / 10000) : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = [V.cols.map(c => cell(c.t)).join(','), ...rows.map(r => V.cols.map(c => cell(c.v(r))).join(','))].join('\r\n');
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv' })), download: `${ST.toLowerCase()}-${S.view}-${today}.csv` });
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });

  /* ---------- about ---------- */
  const reports = RCS.filter(r => !r.kind.startsWith('Grid workbook')).length, nProps = new Set(HOME.map(r => r.id)).size;
  const nAway = new Set(RCS.filter(r => r.p.away).map(r => r.id)).size, homeFirms = new Set(HOME.map(r => r.firm)).size;
  $('#asof').textContent = `HUD contract rents as of ${M.hud.asof} · FY2027 SAFMRs · ${nProps ? `${nProps} ${SN} ${nProps === 1 ? 'property' : 'properties'} with rent studies from ${homeFirms} ${homeFirms === 1 ? 'firm' : 'firms'} (${M.studies} ${M.studies === 1 ? 'study' : 'studies'} on file)` : `No ${SN} rent studies on file yet`}` +
    (nAway ? ` · ${nAway} ${nProps ? 'more ' : ''}${nAway === 1 ? 'property' : 'properties'} with studies nearby across the state line${nProps ? '' : ' (widen the radius to use them)'}` : '');
  const vint = M.safmr_vintages.map(v => `${esc(v.label)} (from ${esc(v.eff)})`).join(', ');
  $('#aboutBody').innerHTML = `<h2>How this screen works</h2>
    <h3>1. What each rent study concluded, as a % of SAFMR</h3>
    <p>${nProps} ${esc(SN)} properties have rent comparability studies in the Rent Grid Library (${esc(M.library)})${nAway ? `, and ${nAway} properties in neighboring states within ${M.border_miles} miles of a ${esc(SN)} property are loaded too, so estimates near the state line can use them` : ''}.
      The studies loaded come from ${FIRMS.length} appraisal firms: ${FIRMS.map(f => `${esc(f)} ${firmN[f]}`).join(', ')}.
      The screen uses each firm's latest study at each property (${RCS.length} studies: ${reports} PDF reports, ${RCS.length - reports} grid workbooks dated by last save). Every firm's study counts the same; untick firms under "Appraisal firms" to leave them out.
      For each study's as-is conclusion, gross rent = the concluded contract rent + the study's utility allowance. That is divided by the HUD Small Area FMR for the study's ZIP and bedroom count <i>in effect on the study date</i>,
      including mid-year revisions: ${vint}. Where a grid has no utility allowance, the current HUD allowance is used and marked "HUD"; for a property with no HUD allowance (not in the HUD file), the county's median HUD allowance for that bedroom count is used and marked "area".
      Before FY2025, HUD published SAFMRs only for metro areas; for a study in a ZIP missing from its vintage, the SAFMR then is estimated as the ZIP's FY2025 SAFMR × the state's median SAFMR change from that vintage to FY2025 (marked "est.").</p>
    <h3>2. Nearby studies set each property's market %</h3>
    <ul><li>For each HUD property, the studies within the radius (default 5 miles, straight-line) are used. With "Match the bedroom count" on, a study contributes its own % for that unit size when it has one, otherwise its median.</li>
      <li>"Average, closer ones count more" weights each study by 1 ÷ distance (distances under a quarter mile count as a quarter mile). "Median" and "Nearest study only" are the alternatives.</li>
      <li>"Bring studies to today": a study under 12 months old is used as concluded (its gross rent ÷ today's SAFMR at its ZIP). An older study keeps its % of the SAFMR on its study date, which moves the conclusion with SAFMR growth since then. Either rule can be applied to all studies.</li>
      <li>A property with its own study uses that study first (its latest that passes the filters). Unit types it did not cover use its median.</li>
      <li>Where a study gives no utility allowance, the property's current HUD allowance for that bedroom count is added to get gross rent (marked "HUD"); if the property has none, the median HUD allowance for that bedroom count in its county (else its state) is used (marked "area"). Where it states its conclusions already include all utilities, the conclusion is the gross rent.</li>
      ${NAT ? `<li>This national view searches for studies up to ${RMAX} miles away, so the radius stops at ${RMAX} miles. At any radius up to that, a property gets the same estimate here as on its state's page.</li>` : ''}
      <li>With no study in range, the property gets no estimate unless you choose the ${FB.toLowerCase()} % (the slider; it starts at the median of ${POOL === HOME ? `the ${esc(SN)} studies` : 'all the studies loaded, because this state has fewer than 5'}, ${pct(calib('all').med)}).</li></ul>
    <h3>3. The screen</h3>
    <ul><li>Search finds any located HUD multifamily property (not only those with Section 8 rent lines), any LIHTC project, any rent-study property, a ZIP, an address (Esri geocoder) or coordinates; "Drop a pin" picks any point. The pick becomes the center of the area: the Nearby tab lists everything within the radius, and every place gets a market rent from the studies in range (its own study first) × its ZIP's FY2027 SAFMR. "Limit the other tabs to this area" narrows the Screener, Rents by bedroom, Rent studies and SAFMR tabs to the circle.</li>
      <li>The map shows the screener's properties (colored by gap), every other HUD property (slate), every LIHTC project (pink; ringed at a HUD property) and every rent study (black ring). Other HUD properties and LIHTC projects are drawn only for the part of the map in view.</li><li>Estimated market gross = market % × the FY2027 SAFMR (effective ${esc(M.safmr_vintages[M.safmr_vintages.length - 1].eff)}) for the property's ZIP and bedroom count.</li>
      <li>Estimated market rent = that minus the line's current utility allowance. Gap = estimated market rent − current contract rent. Annual uplift = gap × units × 12, summed over the property's included lines (lines above the estimate count as negatives).</li>
      <li>5BR and larger: 4BR SAFMR + 15% per extra bedroom (HUD's convention). ZIPs split across HUD areas use the area most properties in that county use. ZIPs missing from the SAFMR file use the line's area FMR ("FMR").</li></ul>
    <h3>4. What the screen does not decide</h3>
    <p>SAFMR is HUD's 40th-percentile rent standard, not a comparable-rent conclusion, and a study a few miles away may cover a different product. Whether a contract's rents can actually move depends on HUD's renewal rules: the contract type (HAP vs budget-based PRAC, PAC or RAC), the renewal option, timing and an actual rent comparability study.</p>
    <h3>Sources</h3>
    <p>HUD Multifamily contract rents and utility allowances (${esc(M.hud.name)}, as of ${esc(M.hud.asof)}); HUD FY2019–FY2027 Small Area FMR files; rent studies in the Rent Grid Library. Built ${esc(M.built)}.
      ${P.length.toLocaleString()} ${esc(SN)} HUD properties with rent lines, ${M.lines.toLocaleString()} rent lines.</p>`;
  $('#aboutBtn').addEventListener('click', () => $('#about').showModal());

  /* ---------- go ---------- */
  syncControls();
  refresh();
  fitHome();
  const fromHash = () => {
    const m = /sel=([^&]+)/.exec(location.hash), e0 = m && ENT.get(decodeURIComponent(m[1]));
    if (e0 && e0.key !== S.sel && e0.lat != null) { map.setView([e0.lat, e0.lon], 13); selectEnt(e0, false); }
  };
  fromHash();
  window.addEventListener('hashchange', fromHash);
  Promise.all([loadJs('hud_all.js', 'RS_HUD'), loadJs('lihtc.js', 'RS_LIHTC')]).then(([h, l]) => {
    HUDALL = h; LIH = l; addPublic();
    if (S.ctr) refresh(); else { drawExtra(); renderSummary(); }
    fromHash();
    if ($('#q') === document.activeElement && $('#q').value.trim()) suggest();
  }).catch(() => { PUBERR = 'Could not load the HUD and LIHTC lists. Reload the page.'; drawExtra(); });
}
})();

/* Rent screener, one state at a time: rent-study (RCS) conclusions vs HUD Small Area FMRs, and an estimate of market rent
   for every HUD rent line in the state from the rent studies near it (including studies just across the state line).
   Each state's data file (data/<ST>.enc.js) is encrypted; nothing renders until the password unlocks it. */
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
let ST = (new URLSearchParams(location.search).get('st') || store.get('rsState') || 'CA').toUpperCase();
if (!stName[ST]) ST = 'CA';
const fillStates = sel => { sel.innerHTML = STATES.map(([c, n]) => `<option value="${c}">${esc(n)}</option>`).join(''); sel.value = ST; };
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
  const M = D.meta, P = D.props, RCS = D.rcs, SAF = D.safmr, SN = stName[ST];
  const pById = new Map(P.map(p => [p.id, p]));
  // Properties in other states that have a study near this state's properties: location and name only.
  const spById = new Map((D.sprops || []).map(p => [p.id, Object.assign(p, { cons: [], lines: [], away: true, county: titleCase(p.county), city: titleCase(p.city),
    hay: [p.name, p.addr, p.city, p.state, p.zip, p.county].join(' ').toLowerCase() })]));
  const today = new Date().toISOString().slice(0, 10);
  const addMonths = n => { const d = new Date(); d.setMonth(d.getMonth() + n); return d.toISOString().slice(0, 10); };
  const yearAgo = addMonths(-12);
  for (const p of P) {
    p.state = ST; p.county = titleCase(p.county); p.city = titleCase(p.city);
    p.hay = [p.name, p.addr, p.city, p.zip, p.county, p.owner, p.mgmt, p.id].join(' ').toLowerCase();
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
  for (const p of P) p.near = RCS.filter(r => r.p !== p).map(r => ({ r, d: dist(p, r.p) })).filter(o => o.d <= 500).sort((a, b) => a.d - b.d);
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
  const POOL = HOME.filter(r => ok(r.ratio)).length >= 5 ? HOME : RCS, FB = POOL === HOME ? 'Statewide' : 'Regional';
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
  const DEF = () => ({ q: '', county: '', radius: 5, combine: 'idw', cal: 'all', bedMatch: true, useOwn: true, rcsMode: 'auto',
    fallback: 'none', ratio: Math.round(calib('all').med * 100), fee: 5, firms: new Set(FIRMS),
    docs: new Set(['HAP']), ropts: new Set(ROPTS), oldCons: false, exp: '', minUnits: '', minGap: '', minAnnual: '', rcsOnly: false, showNoEst: false });
  const S = Object.assign(DEF(), { view: 'props', sel: null, limit: 300,
    sort: { props: { i: 'annual', d: -1 }, lines: { i: 'annual', d: -1 }, rcs: { i: 'date', d: -1 }, safmr: { i: 'props', d: -1 } } });
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
  let OUT = [], LINES = [], RROWS = [], ZROWS = [], COV = { n: 0, est: 0, hidden: 0 }, REACH = {};
  function build() {
    TOK++;
    CALNOW = calib(S.cal, S.firms);
    const q = S.q.trim().toLowerCase(), cut = S.exp ? addMonths(+S.exp) : null;
    OUT = []; LINES = []; COV = { n: 0, est: 0, hidden: 0 }; REACH = {};
    for (const p of P) {
      if (S.county && p.county !== S.county) continue;
      if (S.rcsOnly && !p.rcs) continue;
      if (q && !p.hay.includes(q)) continue;
      const okc = p.cons.map(conOk), ls = p.lines.filter(ln => okc[ln.c]);
      if (!ls.length) continue;
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
      if (cut && !(row.next && row.next <= cut)) continue;
      if (ok(S.minUnits) && U < +S.minUnits) continue;
      COV.n++; if (est) COV.est++;
      if (!est && !S.showNoEst) { COV.hidden++; continue; }
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
      if (S.county && p.county !== S.county) continue;
      if (q && !p.hay.includes(q)) continue;
      for (const x of r.asis) RROWS.push({ p, r, x, now: hudNow(p, x.bed) });
    }
    ZROWS = [];
    for (const z in SAF) {
      const a = SAF[z], ps = zipProps[z] || [];
      if (q && !(z.includes(q) || a[0].toLowerCase().includes(q) || ps.some(p => p.hay.includes(q)))) continue;
      if (S.county && !ps.some(p => p.county === S.county)) continue;
      ZROWS.push({ z, a, ps });
    }
  }
  function hudNow(p, bed) {
    const ls = p.lines.filter(l => l.bed === bed && p.cons[l.c].status);
    return ls.length ? wavg(ls, l => l.rent) : null;
  }

  /* ---------- tables ---------- */
  const C = (k, t, v, o = {}) => ({ k, t, v, ...o });
  const feeOf = a => ok(a) && a > 0 ? a * S.fee / 100 : null;
  const estTag = x => x.safEst ? ' <span class="est" title="This ZIP was not in the SAFMR file on the study date (before FY2025 HUD published SAFMRs only for metro areas). Estimated as its FY2025 SAFMR × the state\'s median SAFMR change from that vintage to FY2025.">est.</span>' : '';
  const uaTag = x => !x.uaSrc || x.uaSrc === 'study' ? '' : x.uaSrc === 'included in the conclusion' ? ' <span class="est" title="The study concludes gross rents, so no allowance is added">gross</span>' : /median/.test(x.uaSrc) ? ` <span class="est" title="The grid has no utility allowance and the property has no HUD allowance for this bedroom count; the ${esc(x.uaSrc)} is used">area</span>` : ' <span class="est" title="The grid has no utility allowance; the current HUD allowance is used">HUD</span>';
  const studyBadge = p => p.rcs ? ` <span class="b rcs" title="Own rent study ${esc(p.rcs.date)}">RCS</span>` : '';
  const VIEWS = {
    props: { rows: () => OUT, pid: r => r.p.id, cols: [
      C('name', 'Property', r => r.p.name, { f: r => `<b>${esc(r.p.name)}</b>${studyBadge(r.p)}` }),
      C('city', 'City', r => r.p.city), C('county', 'County', r => r.p.county),
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
      C('city', 'City', r => r.p.city),
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
      C('zip', 'ZIP', r => r.z, { f: r => `<b>${esc(r.z)}</b>` }),
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
    em.innerHTML = COV.hidden && S.view !== 'rcs' && S.view !== 'safmr'
      ? `<b>Nothing to show.</b> ${COV.hidden.toLocaleString()} matching properties have no rent study within ${S.radius} miles. Widen the radius, or turn on "Also list properties with no estimate".`
      : '<b>Nothing matches.</b> Loosen a filter (contract type, renewal option, timing or gap) or clear the search.';
    $('#more').innerHTML = rows.length > S.limit ? `Showing ${S.limit.toLocaleString()} of ${rows.length.toLocaleString()} rows <button class="btn small" id="moreBtn">Show 300 more</button>` : '';
    renderSummary();
  }
  function renderSummary() {
    let t = '';
    if (S.view === 'props' || S.view === 'lines') {
      const U = OUT.reduce((a, r) => a + r.units, 0), up = OUT.reduce((a, r) => a + Math.max(0, r.annual || 0), 0);
      const n = OUT.filter(r => r.annual > 0).length;
      t = `${OUT.length.toLocaleString()} properties · ${LINES.length.toLocaleString()} rent lines · ${U.toLocaleString()} units · ${n.toLocaleString()} below the estimate, worth <b>${money(up)}/yr</b>` +
        (S.fee ? ` (fee at ${S.fee}%: ${money(up * S.fee / 100)}/yr)` : '') +
        (COV.hidden ? ` · ${COV.hidden.toLocaleString()} more with no study within ${S.radius} mi not listed` : '');
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
    const p = pById.get(tr.dataset.id); if (p) select(p, true);
  });
  $('#more').addEventListener('click', e => { if (e.target.id === 'moreBtn') { S.limit += 300; renderTable(); } });

  /* ---------- map ---------- */
  const map = L.map('map', { preferCanvas: true }).setView([37.2, -119.4], 6);
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
  const tiles = (svc, attr) => L.tileLayer(`${ESRI}${svc}/MapServer/tile/{z}/{y}/{x}`, { attribution: attr, maxZoom: 19, maxNativeZoom: 16 });
  L.layerGroup([tiles('Canvas/World_Light_Gray_Base', 'Tiles &copy; Esri | HUD Multifamily'), tiles('Canvas/World_Light_Gray_Reference', '')]).addTo(map);
  map.createPane('reach').style.zIndex = 390;   // radius circle and study links sit under the dots
  const reachRenderer = L.svg({ pane: 'reach' });
  const dots = L.layerGroup().addTo(map), ring = L.layerGroup().addTo(map), studyDots = L.layerGroup().addTo(map);
  const BANDS = [[500, '#0b5d27', '$500+'], [250, '#1a7f37', '$250–500'], [100, '#5cb270', '$100–250'], [0.5, '#b7dfc1', '$1–100']];
  const gapColor = g => { if (!ok(g)) return '#8b8f98'; for (const [v, c] of BANDS) if (g >= v) return c; return '#c2410c'; };
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => {
    const d = L.DomUtil.create('div', 'legend');
    d.innerHTML = '<b>Gap per unit / month</b><br>' + BANDS.map(([, c, t]) => `<i style="background:${c}"></i>${t}`).join('<br>') +
      '<br><i style="background:#c2410c"></i>At or above the estimate<br><i style="background:#8b8f98"></i>No estimate' +
      '<br><i style="background:#fff;border:2.5px solid #111"></i>Rent study';
    return d;
  };
  legend.addTo(map);
  function drawMarkers() {
    dots.clearLayers(); studyDots.clearLayers();
    const byP = new Map(OUT.map(r => [r.p, r]));
    const list = S.view === 'rcs' ? RCS.filter(r => RROWS.some(x => x.r === r)).map(r => byP.get(r.p) || { p: r.p, gapU: null }) : OUT;
    for (const r of list) {
      const p = r.p;
      const m = L.circleMarker([p.lat, p.lon], { radius: p.rcs ? 7 : 5, weight: p.rcs ? 2.5 : 1, color: p.rcs ? '#111' : '#fff',
        fillColor: gapColor(r.gapU), fillOpacity: 0.92 });
      m.bindTooltip(`${esc(p.name)}${ok(r.gapU) ? ` · ${money(r.gapU)}/unit` : ''}`);
      m.on('click', () => select(p, false));
      dots.addLayer(m);
    }
    // Every usable study stays visible as a ringed dot, even when its own property is filtered out of the list.
    if (S.view !== 'rcs') for (const r of RCS) {
      if (byP.has(r.p) || !studyOk(r)) continue;
      const m = L.circleMarker([r.p.lat, r.p.lon], { radius: 6, weight: 2.5, color: '#111', fillColor: '#fff', fillOpacity: 0.9 });
      m.bindTooltip(`${esc(r.name)} · ${esc(r.firm)} rent study ${esc(r.date)}`);
      m.on('click', () => select(r.p, false));
      studyDots.addLayer(m);
    }
    drawRing();
  }
  function selRefs(p) {   // studies the selected property's estimate uses, with distance
    const own = ownStudy(p);
    if (own) return [];
    return refsFor(p);
  }
  function drawRing() {
    ring.clearLayers();
    const p = S.sel && pById.get(S.sel);
    if (!p) return;
    if (!ownStudy(p)) L.circle([p.lat, p.lon], { renderer: reachRenderer, radius: S.radius * 1609.344, color: '#1f4e99', weight: 1.5, dashArray: '6 6', fillColor: '#1f4e99', fillOpacity: 0.05, interactive: false }).addTo(ring);
    const refs = selRefs(p);
    // Studies at the same property share one line and one label.
    const atP = new Map();
    for (const o of refs) { if (!atP.has(o.r.p)) atP.set(o.r.p, []); atP.get(o.r.p).push(o); }
    for (const [sp, os] of atP) {
      L.polyline([[p.lat, p.lon], [sp.lat, sp.lon]], { renderer: reachRenderer, color: '#1f4e99', weight: 2, opacity: 0.8, interactive: false }).addTo(ring);
      if (atP.size <= 8) L.tooltip({ permanent: true, direction: 'right', offset: [8, 0], className: 'reftip' })
        .setLatLng([sp.lat, sp.lon]).setContent(`${esc(os[0].r.name)} · ${mi(os[0].d)} mi · ` + os.map(o => `${esc(o.r.firm)} ${esc(o.r.date.slice(0, 7))}`).join(', ')).addTo(ring);
    }
    L.circleMarker([p.lat, p.lon], { radius: 12, color: '#b42318', weight: 3, fill: false, interactive: false }).addTo(ring);
  }

  /* ---------- detail ---------- */
  function select(p, fromTable) {
    S.sel = p.id;
    history.replaceState(null, '', '#sel=' + p.id);
    $$('#ctbl tbody tr.sel').forEach(tr => tr.classList.remove('sel'));
    $$(`#ctbl tbody tr[data-id="${p.id}"]`).forEach(tr => tr.classList.add('sel'));
    if (!fromTable) { const tr = $(`#ctbl tbody tr[data-id="${p.id}"]`); if (tr) tr.scrollIntoView({ block: 'nearest' }); }
    drawRing();
    renderDetail(p);
    // Frame the property and the studies it uses, keeping clear of the detail panel that covers the map's right side.
    const refs = selRefs(p), padR = Math.min($('#detail').offsetWidth, $('#map').offsetWidth * 0.7) + 20;
    const pts = [[p.lat, p.lon], ...refs.map(o => [o.r.p.lat, o.r.p.lon])];
    if (!ownStudy(p)) { const c = L.latLng(p.lat, p.lon).toBounds(S.radius * 1609.344 * 2); pts.push(c.getSouthWest(), c.getNorthEast()); }
    map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [20, 20], paddingBottomRight: [padR, 20], maxZoom: 15 });
  }
  function sourceSection(p, row) {
    const own = ownStudy(p), beds = [...new Set(p.lines.map(l => l.bed))].sort((a, b) => a - b);
    let h = '<h3>Where the estimate comes from</h3>';
    if (own) {
      const mode = modeFor(own);
      return h + `<p class="note">This property's own rent study (${esc(own.firm)}, ${esc(own.date)}, ${esc(own.signer || 'signer unknown')}), ${mode === 'asis' ? 'used as concluded' : 'moved with SAFMR since the study date'}. Its details are below.</p>`;
    }
    const refs = refsFor(p);
    if (!refs.length) {
      const nearest = p.near.find(o => studyOk(o.r));
      h += `<p class="note">No rent study within ${S.radius} miles${S.fallback === 'state' ? `, so the ${FB.toLowerCase()} ${S.ratio}% is used` : ''}.`;
      if (nearest) h += ` The nearest is <button class="link" data-goto="${esc(nearest.r.id)}">${esc(nearest.r.name)}</button>, ${mi(nearest.d)} miles away (${esc(nearest.r.firm)}, ${esc(nearest.r.date)}).
        <button class="link" data-widen="${Math.ceil(nearest.d)}">Widen the radius to ${Math.ceil(nearest.d)} miles</button>`;
      return h + '</p>';
    }
    const how = { idw: 'averaged, closer studies counting more (weight = 1 ÷ distance)', median: 'combined by median', nearest: 'nearest study only' }[S.combine];
    h += `<p class="note">${plural(refs.length, 'rent study')} within ${S.radius} miles, ${how}. Each column is that study's market gross as % of SAFMR for the bedroom count${S.bedMatch ? '; <span class="est">*</span> = the study has no unit of that size, so its median is used' : ' (study medians)'}.</p>`;
    h += `<div class="scrollx"><table class="dt"><thead><tr><th>Study property</th><th class="num">Mi</th><th>Done</th><th>Firm</th>${beds.map(b => `<th class="num">${bedName(b)}</th>`).join('')}${S.combine === 'idw' ? '<th class="num">Weight</th>' : ''}</tr></thead><tbody>`;
    const perBed = Object.fromEntries(beds.map(b => [b, combine(refs, b)]));
    refs.forEach((o, i) => {
      h += `<tr><td class="wrap"><button class="link" data-goto="${esc(o.r.id)}">${esc(o.r.name)}</button><div class="subnote">${esc(o.r.p.city)}${o.r.prelim ? ' · prelim' : ''}${modeFor(o.r) === 'age' ? ' · moved with SAFMR' : ''}</div></td>
        <td class="num">${mi(o.d)}</td><td>${esc(o.r.date)}</td><td class="wrap">${esc(o.r.firm)}<div class="subnote">${esc(o.r.signer || '')}</div></td>` +
        beds.map(b => { const x = perBed[b].parts[i]; return `<td class="num">${pct(x.k)}${x.match ? '' : '<span class="est">*</span>'}</td>`; }).join('') +
        (S.combine === 'idw' ? `<td class="num">${pct(perBed[beds[0]].parts[i].share)}</td>` : '') + '</tr>';
    });
    h += `<tr class="tot"><td><b>Used for this property</b></td><td></td><td></td><td></td>${beds.map(b => `<td class="num"><b>${pct(perBed[b].k)}</b></td>`).join('')}${S.combine === 'idw' ? '<td></td>' : ''}</tr></tbody></table></div>`;
    return h;
  }
  function renderDetail(p) {
    const row = OUT.find(r => r.p === p);
    const okc = p.cons.map(conOk);
    if (p.away) return renderAway(p);
    let h = `<h2>${esc(p.name)}</h2><div class="muted">${p.addr ? esc(p.addr) + ', ' : ''}${esc(p.city)}, ${esc(ST)} ${esc(p.zip)}${p.county ? ` · ${esc(p.county)} County` : ''}</div>
      ${p.nohud ? `<div class="callout muted">${esc(p.nohud)} Its rent study is loaded so estimates for nearby HUD properties can use it; it has no HUD contracts or rent lines.</div>`
        : `<p class="tiny"><a href="../#sel=${esc(p.id)}" target="_blank" rel="noopener">Open on the national map</a></p>`}
      <dl class="kv"><dt>HUD property ID</dt><dd>${p.nohud ? '–' : esc(p.id)}</dd><dt>Owner</dt><dd>${esc(p.owner || '–')}${p.ownerType ? ` <span class="muted">(${esc(p.ownerType)})</span>` : ''}</dd>
      <dt>Management agent</dt><dd>${esc(p.mgmt || '–')}</dd><dt>Units (total / assisted)</dt><dd>${int(p.total)} / ${int(p.assisted)}</dd>
      <dt>SAFMR area</dt><dd>${esc(p.area || 'ZIP not in the SAFMR file')}</dd></dl>`;
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
  // A study property in another state: its studies only, with a link to that state's screener.
  function renderAway(p) {
    const n = stName[p.state] || p.state;
    let h = `<h2>${esc(p.name)}</h2><div class="muted">${esc(p.addr || '')}${p.addr ? ', ' : ''}${esc(p.city)}, ${esc(p.state)} ${esc(p.zip)}</div>
      <div class="callout muted">This property is in ${esc(n)}. Its rent studies are loaded here so estimates for nearby ${esc(SN)} properties can use them.
      <div class="subnote"><a href="?st=${esc(p.state)}#sel=${esc(p.id)}">Open it in the ${esc(n)} screener</a></div></div>`;
    h += studySections(p);
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
    const g = e.target.closest('[data-goto]'), w = e.target.closest('[data-widen]');
    if (g) { const p = pById.get(g.dataset.goto); if (p) select(p, false); }
    if (w) { S.radius = +w.dataset.widen; syncControls(); refresh(); drawRing(); const p = pById.get(S.sel); if (p) select(p, false); }
  });
  $('#closeDetail').addEventListener('click', closeDetail);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#about').open) closeDetail(); });
  function closeDetail() { $('#detail').hidden = true; S.sel = null; history.replaceState(null, '', location.pathname + location.search); $$('#ctbl tbody tr.sel').forEach(tr => tr.classList.remove('sel')); drawRing(); }

  /* ---------- controls ---------- */
  const county = $('#county');
  for (const c of [...new Set(P.map(p => p.county).filter(Boolean))].sort()) county.insertAdjacentHTML('beforeend', `<option>${esc(c)}</option>`);
  const calSel = $('#cal');
  for (const k in CAL) calSel.insertAdjacentHTML('beforeend', `<option value="${esc(k)}">${esc(CAL[k][0])} (${RCS.filter(CAL[k][1]).length})</option>`);
  $('#fallback option[value="state"]').textContent = FB === 'Statewide' ? 'Use a statewide %' : 'Use a % from the studies loaded (this state has fewer than 5)';
  $('#f-doc').innerHTML = DOCS.filter(d => docCount[d]).map(d => `<label class="chk"><input type="checkbox" data-doc="${d}"> ${d === '—' ? 'No contract type on file' : d}<span class="n">${docCount[d]}</span></label>`).join('');
  $('#f-firm').innerHTML = FIRMS.map(f => `<label class="chk"><input type="checkbox" data-firm="${esc(f)}"> ${esc(f)}<span class="n">${firmN[f]}</span></label>`).join('');
  $('#f-ropt').innerHTML = ROPTS.map(r => `<label class="chk"><input type="checkbox" data-ropt="${esc(r)}"> <span><b>${esc(r)}</b> ${esc(ropLabel[r])}</span><span class="n">${ropCount[r]}</span></label>`).join('');
  function syncControls() {
    $('#q').value = S.q; county.value = S.county; $('#radius').value = S.radius; $('#combine').value = S.combine; calSel.value = S.cal;
    $('#bedMatch').checked = S.bedMatch; $('#useOwn').checked = S.useOwn; $('#rcsMode').value = S.rcsMode; $('#fallback').value = S.fallback;
    $('#stateBox').hidden = S.fallback !== 'state'; $('#ratio').value = S.ratio; $('#fee').value = S.fee;
    $('#oldCons').checked = S.oldCons; $('#exp').value = S.exp; $('#minUnits').value = S.minUnits; $('#minGap').value = S.minGap; $('#minAnnual').value = S.minAnnual;
    $('#rcsOnly').checked = S.rcsOnly; $('#showNoEst').checked = S.showNoEst;
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
  function refresh() { S.limit = 300; build(); renderCal(); renderTable(); drawMarkers(); if (S.sel && !$('#detail').hidden) renderDetail(pById.get(S.sel)); }
  let qT;
  $('#q').addEventListener('input', e => { clearTimeout(qT); qT = setTimeout(() => { S.q = e.target.value; refresh(); }, 180); });
  county.addEventListener('change', () => { S.county = county.value; refresh(); });
  $('#radius').addEventListener('change', e => { const v = +e.target.value; if (v > 0) { S.radius = v; refresh(); } else syncControls(); });
  $$('[data-r]').forEach(b => b.addEventListener('click', () => { S.radius = +b.dataset.r; syncControls(); refresh(); }));
  $('#ratio').addEventListener('input', e => { S.ratio = +e.target.value; $('#ratioVal').textContent = S.ratio + '%'; clearTimeout(qT); qT = setTimeout(refresh, 60); });
  $$('[data-q]').forEach(b => b.addEventListener('click', () => { const v = calib('all')[b.dataset.q]; if (ok(v)) { S.ratio = Math.round(v * 100); syncControls(); refresh(); } }));
  const bind = (id, k, f = x => x) => $(id).addEventListener('change', e => { S[k] = f(e.target.type === 'checkbox' ? e.target.checked : e.target.value); syncControls(); refresh(); });
  bind('#combine', 'combine'); bind('#cal', 'cal'); bind('#bedMatch', 'bedMatch'); bind('#useOwn', 'useOwn'); bind('#rcsMode', 'rcsMode'); bind('#fallback', 'fallback');
  bind('#fee', 'fee', v => (ok(v) ? +v : 0)); bind('#oldCons', 'oldCons'); bind('#exp', 'exp');
  bind('#minUnits', 'minUnits'); bind('#minGap', 'minGap'); bind('#minAnnual', 'minAnnual'); bind('#rcsOnly', 'rcsOnly'); bind('#showNoEst', 'showNoEst');
  $('#f-doc').addEventListener('change', e => { const d = e.target.dataset.doc; e.target.checked ? S.docs.add(d) : S.docs.delete(d); refresh(); });
  $('#f-ropt').addEventListener('change', e => { const r = e.target.dataset.ropt; e.target.checked ? S.ropts.add(r) : S.ropts.delete(r); refresh(); });
  $('#f-firm').addEventListener('change', e => { const f = e.target.dataset.firm; e.target.checked ? S.firms.add(f) : S.firms.delete(f); refresh(); });
  $('[data-all="firm"]').addEventListener('click', () => { S.firms = new Set(FIRMS); syncControls(); refresh(); });
  $('[data-none="firm"]').addEventListener('click', () => { S.firms = new Set(); syncControls(); refresh(); });
  $('[data-all="ropt"]').addEventListener('click', () => { S.ropts = new Set(ROPTS); syncControls(); refresh(); });
  $('[data-none="ropt"]').addEventListener('click', () => { S.ropts = new Set(); syncControls(); refresh(); });
  $('#resetAll').addEventListener('click', () => { Object.assign(S, DEF()); syncControls(); refresh(); });
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
      <li>With no study in range, the property gets no estimate unless you choose the ${FB.toLowerCase()} % (the slider; it starts at the median of ${POOL === HOME ? `the ${esc(SN)} studies` : 'all the studies loaded, because this state has fewer than 5'}, ${pct(calib('all').med)}).</li></ul>
    <h3>3. The screen</h3>
    <ul><li>Estimated market gross = market % × the FY2027 SAFMR (effective ${esc(M.safmr_vintages[M.safmr_vintages.length - 1].eff)}) for the property's ZIP and bedroom count.</li>
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
  map.fitBounds(L.latLngBounds(P.filter(p => p.lat != null).map(p => [p.lat, p.lon])), { padding: [10, 10] });
  const fromHash = () => {
    const m = /sel=(\w+)/.exec(location.hash), p0 = m && pById.get(m[1]);
    if (p0 && p0.id !== S.sel) { map.setView([p0.lat, p0.lon], 13); select(p0, false); }
  };
  fromHash();
  window.addEventListener('hashchange', fromHash);
}
})();

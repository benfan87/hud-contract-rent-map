/* California rent screener: rent-study (RCS) conclusions vs HUD Small Area FMRs, and a SAFMR-based screen of every
   California HUD rent line. The data file (ca_data.enc.js) is encrypted; nothing renders until the password unlocks it. */
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
const bedName = b => b === 0 ? 'Studio' : b + 'BR';
const sgn = v => !ok(v) ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '';
const ropCode = r => r ? r.split(':')[0] : '—';
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

/* ---------- unlock ---------- */
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
async function decrypt(pw) {
  const E = window.CA_ENC;
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveKey']);
  const key = await crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt: b64(E.salt), iterations: E.iter },
    base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  const gz = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(E.iv) }, key, b64(E.ct));
  const text = await new Response(new Blob([gz]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  return JSON.parse(text);
}
const pwIn = $('#pw'), gateErr = $('#gateErr'), gateBtn = $('#gateBtn');
async function unlock(pw, quiet) {
  if (!window.CA_ENC) { gateErr.textContent = 'The data file did not load. Reload the page.'; return; }
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
  const M = D.meta, P = D.props, RCS = D.rcs, SAF = D.safmr;
  const pById = new Map(P.map(p => [p.id, p]));
  for (const r of RCS) {
    r.p = pById.get(r.id); r.p.rcs = r;
    r.ratio = median(r.asis.map(x => x.pct).filter(ok));
    r.asis.forEach((x, i) => { x.renRow = r.ren.length === r.asis.length ? r.ren[i] : r.ren.find(y => y.unit === x.unit && y.sf === x.sf) || null; });
  }
  for (const p of P) p.hay = [p.name, p.addr, p.city, p.zip, p.county, p.owner, p.mgmt, p.id].join(' ').toLowerCase();
  const zipProps = {};
  for (const p of P) (zipProps[p.zip] = zipProps[p.zip] || []).push(p);
  const today = new Date().toISOString().slice(0, 10);
  const addMonths = n => { const d = new Date(); d.setMonth(d.getMonth() + n); return d.toISOString().slice(0, 10); };

  // Which studies the market % is learned from
  const CAL = {
    all: ['All studies', () => true],
    y2025: ['Studies dated 2025 or later', r => r.date >= '2025'],
    y2024: ['Studies dated 2024 or later', r => r.date >= '2024'],
    final: ['Final reports and grids (no prelims)', r => !r.prelim],
  };
  for (const s of [...new Set(RCS.map(r => r.signer).filter(Boolean))].sort()) CAL['by:' + s] = ['Signed by ' + s, r => r.signer === s];
  function calib(setKey) {
    const set = RCS.filter(CAL[setKey][1]).filter(r => ok(r.ratio));
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
  const DEF = () => ({ q: '', county: '', cal: 'all', ratio: Math.round(calib('all').med * 100), byBed: false, rcsMode: 'auto', fee: 5,
    docs: new Set(['HAP']), ropts: new Set(ROPTS), oldCons: false, exp: '', minUnits: '', minGap: '', minAnnual: '', rcsOnly: false });
  const S = Object.assign(DEF(), { view: 'props', sel: null, limit: 300,
    sort: { props: { i: 'annual', d: -1 }, lines: { i: 'annual', d: -1 }, rcs: { i: 'date', d: -1 }, safmr: { i: 'props', d: -1 } } });
  let CALNOW = calib(S.cal);

  /* ---------- estimate ---------- */
  function ratioFor(bed) {
    const r = S.ratio / 100;
    if (!S.byBed) return r;
    const b = CALNOW.byBed[Math.min(bed, 4)];
    return b && b.length >= 3 && CALNOW.med ? r * median(b) / CALNOW.med : r;
  }
  const yearAgo = addMonths(-12);
  const modeFor = r => S.rcsMode === 'auto' ? (r.date >= yearAgo ? 'asis' : 'age') : S.rcsMode;
  const wavg = (rows, f) => { let s = 0, w = 0; for (const x of rows) { const u = x.units || 1; s += f(x) * u; w += u; } return w ? s / w : null; };
  function lineEst(p, ln) {
    const saf = ln.s27 ?? ln.fmr, safSrc = ln.s27 != null ? 'SAFMR' : ln.fmr != null ? 'area FMR' : null;
    const gross = ln.rent + ln.ua;
    let estGross = null, estRent = null, basis = null;
    const r = p.rcs, mode = r && modeFor(r);
    if (r && mode !== 'ignore') {
      const rows = r.asis.filter(x => x.bed === ln.bed && ok(x.gross));
      if (mode === 'asis' && rows.length) { estRent = wavg(rows, x => x.rcs); basis = 'rcs'; }
      else if (mode === 'age' && saf && rows.some(x => ok(x.pct))) { estGross = wavg(rows.filter(x => ok(x.pct)), x => x.pct) * saf; basis = 'aged'; }
      else if (ok(r.ratio) && saf) { estGross = r.ratio * saf; basis = 'pratio'; }
    }
    if (basis == null && saf) { estGross = ratioFor(ln.bed) * saf; basis = 'ratio'; }
    if (estRent == null && estGross != null) estRent = estGross - ln.ua;
    if (estGross == null && estRent != null) estGross = estRent + ln.ua;
    const gap = estRent != null ? estRent - ln.rent : null;
    return { saf, safSrc, gross, curPct: saf ? gross / saf : null, estGross, estRent, gap, annual: gap != null ? gap * ln.units * 12 : null, basis };
  }
  const basisText = (p, e, ln) => {
    const r = p.rcs, d = r ? r.date.slice(0, 7) : '';
    return { rcs: `Study ${d}`, aged: `Study ${d}, aged`, pratio: `Study ${d} ratio (${pct(r && r.ratio)})`,
      ratio: `${pct(ratioFor(ln.bed))} × ${e.safSrc || 'SAFMR'}` }[e.basis] || 'No SAFMR';
  };

  /* ---------- filtering ---------- */
  const conOk = c => (c.status || S.oldCons) && S.docs.has(c.doc || '—') && S.ropts.has(ropCode(c.ropt));
  let OUT = [], LINES = [], RROWS = [], ZROWS = [];
  function build() {
    CALNOW = calib(S.cal);
    const q = S.q.trim().toLowerCase(), cut = S.exp ? addMonths(+S.exp) : null;
    OUT = []; LINES = [];
    for (const p of P) {
      if (S.county && p.county !== S.county) continue;
      if (S.rcsOnly && !p.rcs) continue;
      if (q && !p.hay.includes(q)) continue;
      const okc = p.cons.map(conOk), ls = p.lines.filter(ln => okc[ln.c]);
      if (!ls.length) continue;
      let U = 0, R = 0, G = 0, SF = 0, GU = 0, GAP = 0, ANN = 0, n = 0;
      const basis = new Set();
      for (const ln of ls) {
        const e = ln.e = lineEst(p, ln);
        U += ln.units; R += ln.rent * ln.units;
        if (e.saf) { G += e.gross * ln.units; SF += e.saf * ln.units; }
        if (e.gap != null) { GU += ln.units; GAP += e.gap * ln.units; ANN += e.annual; n++; }
        basis.add(e.basis);
      }
      const cs = p.cons.filter((c, i) => okc[i] && ls.some(l => l.c === i));
      const next = cs.map(c => c.exp).filter(Boolean).sort()[0] || null;
      const ov = cs.map(c => c.ovExp).filter(Boolean).sort()[0] || null;
      const row = { p, ls, cs, units: U, rent: U ? R / U : null, curPct: SF ? G / SF : null, gapU: GU ? GAP / GU : null, annual: n ? ANN : null, next, ov,
        docs: [...new Set(cs.map(c => c.doc || '—'))].join(', '), ropts: [...new Set(cs.map(c => ropCode(c.ropt)))].join(', '),
        basis: p.rcs && S.rcsMode !== 'ignore' && [...basis].some(b => b !== 'ratio') ? `Study ${p.rcs.date.slice(0, 7)}${modeFor(p.rcs) === 'age' ? ', aged' : ''}` : `${S.byBed ? 'By-BR %' : S.ratio + '%'} × SAFMR` };
      if (cut && !(row.next && row.next <= cut)) continue;
      if (ok(S.minUnits) && U < +S.minUnits) continue;
      if (ok(S.minGap) && !(row.gapU >= +S.minGap)) continue;
      if (ok(S.minAnnual) && !(row.annual >= +S.minAnnual)) continue;
      OUT.push(row);
      for (const ln of ls) LINES.push({ p, ln, e: ln.e, c: p.cons[ln.c] });
    }
    RROWS = [];
    for (const r of RCS) {
      const p = r.p;
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
  const studyBadge = p => p.rcs ? ` <span class="b rcs" title="Rent study ${esc(p.rcs.date)}">RCS</span>` : '';
  const VIEWS = {
    props: { rows: () => OUT, pid: r => r.p.id, cols: [
      C('name', 'Property', r => r.p.name, { f: r => `<b>${esc(r.p.name)}</b>${studyBadge(r.p)}` }),
      C('city', 'City', r => r.p.city), C('county', 'County', r => r.p.county),
      C('units', 'Units', r => r.units, { num: 1, f: r => int(r.units), tip: 'Units on the included rent lines' }),
      C('docs', 'Contract', r => r.docs), C('ropts', 'Renewal opt.', r => r.ropts, { tip: 'HUD renewal option code; see the filter for names' }),
      C('next', 'Term ends', r => r.next, { tip: 'Earliest current-term expiration among the included contracts' }),
      C('ov', 'Overall exp.', r => r.ov),
      C('rent', 'Avg contract rent', r => r.rent, { num: 1, f: r => money(r.rent) }),
      C('curPct', 'Gross % SAFMR', r => r.curPct, { num: 1, f: r => pct(r.curPct), tip: 'Current contract rent + utility allowance, as % of the FY2027 SAFMR (unit-weighted)' }),
      C('basis', 'Market basis', r => r.basis),
      C('gapU', 'Gap / unit / mo', r => r.gapU, { num: 1, f: r => `<span class="${sgn(r.gapU)}">${money(r.gapU)}</span>` }),
      C('annual', 'Annual uplift', r => r.annual, { num: 1, f: r => `<b class="${sgn(r.annual)}">${money(r.annual)}</b>` }),
      C('fee', 'Fee / yr', r => feeOf(r.annual), { num: 1, f: r => money(feeOf(r.annual)), tip: 'Annual uplift × the fee %' }),
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
      C('est', 'Est. market rent', r => r.e.estRent, { num: 1, f: r => money(r.e.estRent), tip: 'Contract-rent basis (net of the current utility allowance)' }),
      C('gap', 'Gap / unit', r => r.e.gap, { num: 1, f: r => `<span class="${sgn(r.e.gap)}">${money(r.e.gap)}</span>` }),
      C('annual', 'Annual', r => r.e.annual, { num: 1, f: r => `<b class="${sgn(r.e.annual)}">${money(r.e.annual)}</b>` }),
      C('basis', 'Basis', r => basisText(r.p, r.e, r.ln)),
      C('no', 'Contract', r => r.c.no), C('doc', 'Type', r => r.c.doc || '—'), C('ropt', 'Renewal opt.', r => ropCode(r.c.ropt)),
      C('exp', 'Term ends', r => r.c.exp),
    ] },
    rcs: { rows: () => RROWS, pid: r => r.p.id, cols: [
      C('name', 'Property', r => r.r.name, { f: r => `<b>${esc(r.r.name)}</b>` }),
      C('city', 'City', r => r.p.city),
      C('date', 'Last done', r => r.r.date, { f: r => esc(r.r.date) + (r.r.prelim ? ' <span class="b pre" title="Preliminary report">prelim</span>' : '') }),
      C('studies', 'Studies', r => r.r.history.length, { num: 1, tip: 'Studies on file for this property' }),
      C('signer', 'Signed by', r => r.r.signer), C('client', 'Client', r => r.r.client),
      C('kind', 'Source', r => r.r.kind),
      C('unit', 'Unit', r => r.x.unit), C('runits', 'Units', r => r.x.units, { num: 1 }),
      C('contract', 'Contract at study', r => r.x.contract, { num: 1, f: r => money(r.x.contract) }),
      C('rcs', 'RCS as is', r => r.x.rcs, { num: 1, f: r => `<b>${money(r.x.rcs)}</b>` }),
      C('ren', 'As renovated', r => r.x.renRow ? r.x.renRow.rcs : null, { num: 1, f: r => money(r.x.renRow && r.x.renRow.rcs) }),
      C('ua', 'UA', r => r.x.ua, { num: 1, f: r => money(r.x.ua) + (r.x.uaSrc && r.x.uaSrc !== 'study' ? ' <span class="est" title="The grid has no utility allowance; current HUD allowance used">HUD</span>' : '') }),
      C('gross', 'Gross', r => r.x.gross, { num: 1, f: r => money(r.x.gross) }),
      C('safmr', 'SAFMR then', r => r.x.safmr, { num: 1, f: r => money(r.x.safmr), tip: 'SAFMR in effect on the study date' }),
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
  function renderTable() {
    const V = VIEWS[S.view], so = S.sort[S.view], rows = sorted();
    $('#ctbl thead').innerHTML = '<tr>' + V.cols.map(c => `<th data-k="${c.k}" class="${c.num ? 'num' : ''}"${c.tip ? ` title="${esc(c.tip)}"` : ''}>${esc(c.t)}${so.i === c.k ? `<span class="arr">${so.d > 0 ? ' ▲' : ' ▼'}</span>` : ''}</th>`).join('') + '</tr>';
    const shown = rows.slice(0, S.limit);
    $('#ctbl tbody').innerHTML = shown.map((r, i) => {
      const id = V.pid(r);
      return `<tr data-i="${i}"${id ? ` data-id="${id}"` : ''}${id && id === S.sel ? ' class="sel"' : ''}>` +
        V.cols.map(c => `<td class="${c.num ? 'num' : ''}">${c.f ? c.f(r) : esc(c.v(r) ?? '–')}</td>`).join('') + '</tr>';
    }).join('');
    $('#ctbl tbody').rows_ = shown;
    const em = $('#empty');
    em.hidden = rows.length > 0;
    em.innerHTML = '<b>Nothing matches.</b> Loosen a filter (contract type, renewal option, timing or gap) or clear the search.';
    $('#more').innerHTML = rows.length > S.limit ? `Showing ${S.limit.toLocaleString()} of ${rows.length.toLocaleString()} rows <button class="btn small" id="moreBtn">Show 300 more</button>` : '';
    renderSummary();
  }
  function renderSummary() {
    let t = '';
    if (S.view === 'props' || S.view === 'lines') {
      const U = OUT.reduce((a, r) => a + r.units, 0), up = OUT.reduce((a, r) => a + Math.max(0, r.annual || 0), 0);
      const n = OUT.filter(r => r.annual > 0).length;
      t = `${OUT.length.toLocaleString()} properties · ${LINES.length.toLocaleString()} rent lines · ${U.toLocaleString()} units · ${n.toLocaleString()} below the estimate, worth <b>${money(up)}/yr</b>` +
        (S.fee ? ` (fee at ${S.fee}%: ${money(up * S.fee / 100)}/yr)` : '');
    } else if (S.view === 'rcs') {
      const ps = new Set(RROWS.map(r => r.p.id));
      t = `${RROWS.length} unit types across ${ps.size} properties · latest study per property, as-is conclusions`;
    } else t = `${ZROWS.length.toLocaleString()} California ZIPs in the FY2027 SAFMR file`;
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
      const r = $('#ctbl tbody').rows_[+tr.dataset.i];
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
  const dots = L.layerGroup().addTo(map), ring = L.layerGroup().addTo(map);
  const BANDS = [[500, '#0b5d27', '$500+'], [250, '#1a7f37', '$250–500'], [100, '#5cb270', '$100–250'], [0.5, '#b7dfc1', '$1–100']];
  const gapColor = g => { if (!ok(g)) return '#8b8f98'; for (const [v, c] of BANDS) if (g >= v) return c; return '#c2410c'; };
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => {
    const d = L.DomUtil.create('div', 'legend');
    d.innerHTML = '<b>Gap per unit / month</b><br>' + BANDS.map(([, c, t]) => `<i style="background:${c}"></i>${t}`).join('<br>') +
      '<br><i style="background:#c2410c"></i>At or above the estimate<br><i style="background:#fff;border:2.5px solid #111"></i>Has a rent study';
    return d;
  };
  legend.addTo(map);
  function drawMarkers() {
    dots.clearLayers();
    const list = S.view === 'rcs' ? [...new Map(RROWS.map(r => [r.p.id, { p: r.p, gapU: (OUT.find(o => o.p === r.p) || {}).gapU }])).values()] : OUT;
    for (const r of list) {
      const p = r.p;
      const m = L.circleMarker([p.lat, p.lon], { radius: p.rcs ? 7 : 5, weight: p.rcs ? 2.5 : 1, color: p.rcs ? '#111' : '#fff',
        fillColor: gapColor(r.gapU), fillOpacity: 0.92 });
      m.bindTooltip(`${esc(p.name)}${ok(r.gapU) ? ` · ${money(r.gapU)}/unit` : ''}`);
      m.on('click', () => select(p, false));
      dots.addLayer(m);
    }
    drawRing();
  }
  function drawRing() {
    ring.clearLayers();
    const p = S.sel && pById.get(S.sel);
    if (p) L.circleMarker([p.lat, p.lon], { radius: 12, color: '#b42318', weight: 3, fill: false, interactive: false }).addTo(ring);
  }

  /* ---------- detail ---------- */
  function select(p, fromTable) {
    S.sel = p.id;
    history.replaceState(null, '', '#sel=' + p.id);
    $$('#ctbl tbody tr.sel').forEach(tr => tr.classList.remove('sel'));
    $$(`#ctbl tbody tr[data-id="${p.id}"]`).forEach(tr => tr.classList.add('sel'));
    if (!fromTable) { const tr = $(`#ctbl tbody tr[data-id="${p.id}"]`); if (tr) tr.scrollIntoView({ block: 'nearest' }); }
    else map.panTo([p.lat, p.lon]);
    drawRing();
    renderDetail(p);
  }
  function renderDetail(p) {
    const row = OUT.find(r => r.p === p), r = p.rcs;
    const okc = p.cons.map(conOk);
    let h = `<h2>${esc(p.name)}</h2><div class="muted">${esc(p.addr)}, ${esc(p.city)}, CA ${esc(p.zip)} · ${esc(p.county)} County</div>
      <p class="tiny"><a href="../#sel=${esc(p.id)}" target="_blank" rel="noopener">Open on the national map</a></p>
      <dl class="kv"><dt>HUD property ID</dt><dd>${esc(p.id)}</dd><dt>Owner</dt><dd>${esc(p.owner || '–')}${p.ownerType ? ` <span class="muted">(${esc(p.ownerType)})</span>` : ''}</dd>
      <dt>Management agent</dt><dd>${esc(p.mgmt || '–')}</dd><dt>Units (total / assisted)</dt><dd>${int(p.total)} / ${int(p.assisted)}</dd>
      <dt>SAFMR area</dt><dd>${esc(p.area || 'ZIP not in the SAFMR file')}</dd></dl>`;
    if (row) h += `<div class="callout">Estimated gap <b class="${sgn(row.gapU)}">${money(row.gapU)}</b> per unit per month · <b class="${sgn(row.annual)}">${money(row.annual)}</b> a year on ${int(row.units)} units` +
      (S.fee && row.annual > 0 ? ` · fee at ${S.fee}%: <b>${money(feeOf(row.annual))}</b>/yr` : '') + `<div class="subnote">Basis: ${esc(row.basis)}. Changes with the settings on the left.</div></div>`;
    else h += `<div class="callout muted">Not in the current screen: no rent line passes the filters on the left.</div>`;
    h += `<h3>Rents vs FY2027 SAFMR</h3><div class="scrollx"><table class="dt"><thead><tr><th>BR</th><th class="num">Units</th><th class="num">Contract</th><th class="num">UA</th><th class="num">Gross</th><th class="num">SAFMR</th><th class="num">% SAFMR</th><th class="num">Est. market</th><th class="num">Gap</th><th>Basis</th><th>Contract</th></tr></thead><tbody>`;
    for (const ln of [...p.lines].sort((a, b) => a.bed - b.bed)) {
      const e = lineEst(p, ln), c = p.cons[ln.c];
      h += `<tr class="${okc[ln.c] ? '' : 'off'}"><td>${bedName(ln.bed)}</td><td class="num">${ln.units}</td><td class="num">${money(ln.rent)}</td><td class="num">${money(ln.ua)}</td><td class="num">${money(e.gross)}</td>
        <td class="num">${money(e.saf)}${e.safSrc === 'area FMR' ? ' <span class="est">FMR</span>' : ''}</td><td class="num">${pct(e.curPct)}</td><td class="num">${money(e.estRent)}</td>
        <td class="num ${sgn(e.gap)}">${money(e.gap)}</td><td>${esc(basisText(p, e, ln))}</td><td>${esc(c.no)}</td></tr>`;
    }
    h += `</tbody></table></div>`;
    if (p.lines.some((ln) => !okc[ln.c])) h += `<p class="note">Grey rows are on contracts the filters leave out.</p>`;
    if (r) {
      h += `<h3>Rent study <span class="muted">· ${r.history.length} on file</span></h3>
        <dl class="kv"><dt>Last done</dt><dd>${esc(r.date)}${r.prelim ? ' <span class="b pre">prelim</span>' : ''}</dd><dt>Signed by</dt><dd>${esc(r.signer || '–')}</dd>
        <dt>Client</dt><dd>${esc(r.client || '–')}</dd><dt>Source</dt><dd>${esc(r.kind)}<br><span class="subnote">${esc(r.file)}</span></dd>
        <dt>SAFMR compared</dt><dd>${esc(r.vintage)}, ZIP ${esc(r.zip)}</dd><dt>Median % of SAFMR</dt><dd><b>${pct(r.ratio)}</b></dd></dl>`;
      if (r.note) h += `<p class="note">${esc(r.note)}</p>`;
      h += `<div class="scrollx"><table class="dt"><thead><tr><th>Unit</th><th class="num">SF</th><th class="num">Units</th><th class="num">Contract then</th><th class="num">As is</th><th class="num">Renovated</th><th class="num">UA</th><th class="num">Gross</th><th class="num">SAFMR then</th><th class="num">%</th><th class="num">% FY27</th></tr></thead><tbody>`;
      for (const x of r.asis) h += `<tr><td>${esc(x.unit)}</td><td class="num">${int(x.sf)}</td><td class="num">${int(x.units)}</td><td class="num">${money(x.contract)}</td><td class="num"><b>${money(x.rcs)}</b></td>
        <td class="num">${money(x.renRow && x.renRow.rcs)}</td><td class="num">${money(x.ua)}${x.uaSrc && x.uaSrc !== 'study' ? ' <span class="est">HUD</span>' : ''}</td><td class="num">${money(x.gross)}</td>
        <td class="num">${money(x.safmr)}</td><td class="num"><b>${pct(x.pct)}</b></td><td class="num">${pct(x.pct27)}</td></tr>`;
      h += `</tbody></table></div>`;
      if (r.history.length > 1) {
        h += `<h3>Study history</h3><table class="dt"><thead><tr><th>Date</th><th>Signed by</th><th>Source</th><th>As-is rents</th><th>Renovated</th></tr></thead><tbody>`;
        for (const s of [...r.history].reverse()) h += `<tr><td>${esc(s.date)}${s.prelim ? ' <span class="b pre">prelim</span>' : ''}</td><td>${esc(s.signer || '–')}</td><td class="wrap">${esc(s.kind)}</td>
          <td class="wrap">${s.asis.map(([u, v]) => `${esc(u)} ${money(v)}`).join('<br>')}</td><td class="wrap">${s.ren.map(([u, v]) => `${esc(u)} ${money(v)}`).join('<br>') || '–'}</td></tr>`;
        h += `</tbody></table>`;
      }
    }
    h += `<h3>Contracts</h3>`;
    for (const [i, c] of p.cons.entries()) {
      h += `<div class="contract${okc[i] ? '' : ' dim'}"><div class="contract-head"><b>${esc(c.no)}</b><span>${esc(c.doc || 'no doc type')}</span><span class="muted">${esc(c.prog || '')}</span><span class="muted">${esc(c.status || 'not in active list')}</span></div>
        <dl class="kv"><dt>Assisted units</dt><dd>${int(c.units)}</dd><dt>Current term</dt><dd>${esc(c.eff || '?')} to ${esc(c.exp || '?')}${c.term ? ` (${c.term} months)` : ''}</dd>
        <dt>Overall expiration</dt><dd>${esc(c.ovExp || '–')}</dd><dt>Renewal option</dt><dd>${esc(c.ropt || '–')}</dd></dl></div>`;
    }
    $('#detailBody').innerHTML = h;
    $('#detail').hidden = false;
  }
  $('#closeDetail').addEventListener('click', closeDetail);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#about').open) closeDetail(); });
  function closeDetail() { $('#detail').hidden = true; S.sel = null; history.replaceState(null, '', location.pathname + location.search); $$('#ctbl tbody tr.sel').forEach(tr => tr.classList.remove('sel')); drawRing(); }

  /* ---------- controls ---------- */
  const county = $('#county');
  for (const c of [...new Set(P.map(p => p.county).filter(Boolean))].sort()) county.insertAdjacentHTML('beforeend', `<option>${esc(c)}</option>`);
  const calSel = $('#cal');
  for (const k in CAL) calSel.insertAdjacentHTML('beforeend', `<option value="${esc(k)}">${esc(CAL[k][0])} (${RCS.filter(CAL[k][1]).length})</option>`);
  $('#f-doc').innerHTML = DOCS.filter(d => docCount[d]).map(d => `<label class="chk"><input type="checkbox" data-doc="${d}"> ${d === '—' ? 'No contract type on file' : d}<span class="n">${docCount[d]}</span></label>`).join('');
  $('#f-ropt').innerHTML = ROPTS.map(r => `<label class="chk"><input type="checkbox" data-ropt="${esc(r)}"> <span><b>${esc(r)}</b> ${esc(ropLabel[r])}</span><span class="n">${ropCount[r]}</span></label>`).join('');
  function syncControls() {
    $('#q').value = S.q; county.value = S.county; calSel.value = S.cal; $('#ratio').value = S.ratio; $('#byBed').checked = S.byBed;
    $('#rcsMode').value = S.rcsMode; $('#fee').value = S.fee; $('#oldCons').checked = S.oldCons; $('#exp').value = S.exp;
    $('#minUnits').value = S.minUnits; $('#minGap').value = S.minGap; $('#minAnnual').value = S.minAnnual; $('#rcsOnly').checked = S.rcsOnly;
    $$('[data-doc]').forEach(i => { i.checked = S.docs.has(i.dataset.doc); });
    $$('[data-ropt]').forEach(i => { i.checked = S.ropts.has(i.dataset.ropt); });
  }
  function renderCal() {
    const c = CALNOW;
    $('#ratioVal').textContent = S.ratio + '%';
    $('#calStats').innerHTML = c.n ? `${c.n} properties: median <b>${pct(c.med)}</b> of the SAFMR in effect on the study date (25th–75th pct ${pct(c.p25)}–${pct(c.p75)}).` : 'No studies in this set.';
    const yr = Object.keys(c.byYear).sort(), bd = Object.keys(c.byBed).sort();
    $('#calTables').innerHTML = `<table class="mini"><thead><tr><th>Study year</th><th class="num">Properties</th><th class="num">Median</th><th class="num">25th–75th</th></tr></thead><tbody>` +
      yr.map(y => `<tr><td>${y}</td><td class="num">${c.byYear[y].length}</td><td class="num">${pct(median(c.byYear[y]))}</td><td class="num">${pct(quant(c.byYear[y], 0.25))}–${pct(quant(c.byYear[y], 0.75))}</td></tr>`).join('') +
      `</tbody></table><table class="mini"><thead><tr><th>Bedrooms</th><th class="num">Properties</th><th class="num">Median</th><th class="num">Ratio used</th></tr></thead><tbody>` +
      bd.map(b => `<tr><td>${bedName(+b)}</td><td class="num">${c.byBed[b].length}</td><td class="num">${pct(median(c.byBed[b]))}</td><td class="num">${pct(ratioFor(+b))}</td></tr>`).join('') +
      `</tbody></table><p class="hint">One vote per property: the median of its as-is unit types. A bedroom count needs 3 or more properties to get its own ratio.</p>`;
    $('#f-doc-n').textContent = `${S.docs.size} of ${DOCS.filter(d => docCount[d]).length}`;
    $('#f-ropt-n').textContent = `${S.ropts.size} of ${ROPTS.length}`;
  }
  function refresh() { S.limit = 300; build(); renderCal(); renderTable(); drawMarkers(); if (S.sel && !$('#detail').hidden) renderDetail(pById.get(S.sel)); }
  let qT;
  $('#q').addEventListener('input', e => { clearTimeout(qT); qT = setTimeout(() => { S.q = e.target.value; refresh(); }, 180); });
  county.addEventListener('change', () => { S.county = county.value; refresh(); });
  $('#ratio').addEventListener('input', e => { S.ratio = +e.target.value; $('#ratioVal').textContent = S.ratio + '%'; clearTimeout(qT); qT = setTimeout(refresh, 60); });
  $$('[data-q]').forEach(b => b.addEventListener('click', () => { const v = CALNOW[b.dataset.q]; if (ok(v)) { S.ratio = Math.round(v * 100); syncControls(); refresh(); } }));
  calSel.addEventListener('change', () => { S.cal = calSel.value; const c = calib(S.cal); if (ok(c.med)) S.ratio = Math.round(c.med * 100); syncControls(); refresh(); });
  const bind = (id, k, f = x => x) => $(id).addEventListener('change', e => { S[k] = f(e.target.type === 'checkbox' ? e.target.checked : e.target.value); refresh(); });
  bind('#byBed', 'byBed'); bind('#rcsMode', 'rcsMode'); bind('#fee', 'fee', v => (ok(v) ? +v : 0)); bind('#oldCons', 'oldCons'); bind('#exp', 'exp');
  bind('#minUnits', 'minUnits'); bind('#minGap', 'minGap'); bind('#minAnnual', 'minAnnual'); bind('#rcsOnly', 'rcsOnly');
  $('#f-doc').addEventListener('change', e => { const d = e.target.dataset.doc; e.target.checked ? S.docs.add(d) : S.docs.delete(d); refresh(); });
  $('#f-ropt').addEventListener('change', e => { const r = e.target.dataset.ropt; e.target.checked ? S.ropts.add(r) : S.ropts.delete(r); refresh(); });
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
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv' })), download: `ca-${S.view}-${today}.csv` });
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });

  /* ---------- about ---------- */
  const reports = RCS.filter(r => r.kind.startsWith('RCS')).length;
  $('#asof').textContent = `HUD contract rents as of ${M.hud.asof} · FY2027 SAFMRs · ${RCS.length} properties with rent studies (${M.studies} studies)`;
  const vint = M.safmr_vintages.map(v => `${esc(v.label)} (from ${esc(v.eff)})`).join(', ');
  $('#aboutBody').innerHTML = `<h2>How this screen works</h2>
    <h3>1. What our rent studies concluded, as a % of SAFMR</h3>
    <p>${RCS.length} California properties have rent comparability studies in the Rent Grid Library (${esc(M.library)}): ${reports} with a PDF report, ${RCS.length - reports} with only the grid workbook (dated by last save).
      For each study's as-is conclusion, gross rent = the concluded contract rent + the study's utility allowance. That is divided by the HUD Small Area FMR for the study's ZIP and bedroom count <i>in effect on the study date</i>,
      including mid-year revisions: ${vint}. Where a grid has no utility allowance, the current HUD allowance is used and marked "HUD".</p>
    <h3>2. The market %</h3>
    <p>Each property gets one vote: the median of its as-is unit types. The slider starts at the median of those votes; pick another study set under "Learn from", or move the slider.
      The spread is wide (25th–75th percentile ${pct(M.calibration.p25)}–${pct(M.calibration.p75)} across all studies), so read the screen as a ranking of where to look, not as a rent conclusion.</p>
    <h3>3. The screen</h3>
    <ul><li>Estimated market gross = market % × the FY2027 SAFMR (effective ${esc(M.safmr_vintages[M.safmr_vintages.length - 1].eff)}) for the property's ZIP and bedroom count.</li>
      <li>Estimated market rent = that minus the line's current utility allowance. Gap = estimated market rent − current contract rent. Annual uplift = gap × units × 12, summed over the property's included lines (lines above the estimate count as negatives).</li>
      <li>Where a property has a study, by default a study under 12 months old is used as concluded. For an older study, each unit type's own study % is applied to today's SAFMR, which moves the conclusion with SAFMR growth.
        You can always use the conclusion as is, always move it, or ignore it. Unit types the study did not cover use the property's median study %.</li>
      <li>5BR and larger: 4BR SAFMR + 15% per extra bedroom (HUD's convention). ZIPs split across HUD areas use the area most properties in that county use. ZIPs missing from the SAFMR file use the line's area FMR ("FMR").</li></ul>
    <h3>4. What the screen does not decide</h3>
    <p>SAFMR is HUD's 40th-percentile rent standard, not a comparable-rent conclusion. Whether a contract's rents can actually move depends on HUD's renewal rules: the contract type (HAP vs budget-based PRAC, PAC or RAC), the renewal option, timing and an actual rent comparability study.
      The contract type and renewal option filters are there for that.</p>
    <h3>Sources</h3>
    <p>HUD Multifamily contract rents and utility allowances (${esc(M.hud.name)}, as of ${esc(M.hud.asof)}); HUD FY2019–FY2027 Small Area FMR files; rent studies in the Rent Grid Library. Built ${esc(M.built)}.
      ${P.length.toLocaleString()} California HUD properties with rent lines, ${M.lines.toLocaleString()} rent lines.</p>`;
  $('#aboutBtn').addEventListener('click', () => $('#about').showModal());

  /* ---------- go ---------- */
  syncControls();
  refresh();
  const fit = L.latLngBounds(P.map(p => [p.lat, p.lon]));
  map.fitBounds(fit, { padding: [10, 10] });
  const fromHash = () => {
    const m = /sel=(\w+)/.exec(location.hash), p0 = m && pById.get(m[1]);
    if (p0 && p0.id !== S.sel) { map.setView([p0.lat, p0.lon], 13); select(p0, false); }
  };
  fromHash();
  window.addEventListener('hashchange', fromHash);
}
})();

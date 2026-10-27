/* HUD Contract Rent Map: search, radius, filters, linked map + table, detail, CSV export.
   Data: assets/hud_data.js (built by tools/build_data.py). No server needed. */
(() => {
'use strict';
const H = window.HUD_DATA, D = H.dict;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const money = v => v == null ? '' : '$' + Math.round(v).toLocaleString();
const num = v => v == null ? '' : v.toLocaleString();
const dict = (k, i) => (i == null || i < 0) ? null : D[k][i];
const UNK = 'Unknown';

/* ---------- model ---------- */
const props = H.P.map((p, i) => ({
  i, id: p[0], name: p[1], addr: p[2], city: p[3], st: p[4], zip: p[5], county: p[6], metro: p[7],
  lat: p[8], lon: p[9], loc: p[10], locNote: dict('locnote', p[11]), total: p[12], assisted: p[13],
  propcat: dict('propcat', p[14]), owner: p[15], mgmt: p[16], office: dict('office', p[17]), fha: dict('fha', p[18]),
  cons: [], dist: null,
}));
for (const p of props) p.lc = !p.loc ? 'N' : p.loc === 'C' ? 'C' : (p.loc === 'R' || p.loc === '4') ? 'P' : 'A';
const cons = H.C.map((c, i) => ({
  i, p: c[0], no: c[1], status: c[2], program: c[3], group: c[4], pcat: c[5], doc: c[6], units: c[7], maxUnits: c[8],
  eff: c[9], curExp: c[10], ovExp: c[11], term: c[12], ropt: c[13], rstat: c[14], rexp: c[15], rfinal: c[16],
  pct: c[17], band: c[18], rtype: c[19], signed: c[20], signedYear: c[21], signedBad: c[22], rwCur: c[23], rwOv: c[24], lines: [],
  effYear: c[9] ? +c[9].slice(0, 4) : null,
}));
for (const c of cons) props[c.p].cons.push(c);
const BASIS_ORDER = { V: 0, R: 1, E: 2, U: 3 };
const lines = H.L.map((l, i) => ({
  i, c: l[0], bed: l[1], units: l[2], rent: l[3], ua: l[4], gross: l[5], basis: l[6], source: dict('source', l[7]),
  fmrRent: l[8], fmrAssist: l[9], q: l[10], flag: dict('flag', l[11]), bedUnits: l[12], bedSrc: l[13], fmr2: l[14],
  vd: l[15] >= 0 ? H.VD[l[15]] : null,
}));
for (const l of lines) cons[l.c].lines.push(l);
for (const c of cons) c.lines.sort((a, b) => a.bed - b.bed || BASIS_ORDER[a.basis] - BASIS_ORDER[b.basis] || (a.source || '').localeCompare(b.source || ''));
for (const p of props) p.s = [p.id, p.name, p.addr, p.city, p.st, p.zip, ...p.cons.map(c => c.no)].join(' ').toLowerCase();
const byId = new Map(props.map(p => [p.id, p]));

/* ---------- labels ---------- */
const DOC_LABEL = {
  HAP: 'HAP: Section 8 Housing Assistance Payments', PRAC: 'PRAC: Project Rental Assistance Contract',
  PAC: 'PAC: Project Assistance Contract', RAC: 'RAC: 811 PRA Rental Assistance Contract', COOP: 'COOP: 811 PRA Cooperative Agreement',
};
const BASIS_LABEL = { V: 'Verified document', R: 'Reported (HUD rent file)', E: 'Estimated gross (FMR × HUD ratio)', U: 'Unavailable' };
const BASIS_SHORT = { V: 'Verified', R: 'Reported', E: 'Estimate', U: 'Unavailable', N: 'No rent data' };
const LOC_CLASS = { P: 'Precise HUD geocode (rooftop / ZIP+4)', A: 'Approximate HUD geocode (block group / tract / ZIP)', C: 'ZIP centroid: not located by HUD GIS', N: 'No location' };
const BED_LABEL = b => b === 0 ? 'Studio' : b >= 5 ? '5+ BR' : `${b} BR`;
const bedKey = b => Math.min(b, 5);
const COLORS = { V: '#1a7f37', R: '#2563eb', E: '#c26a00', U: '#8b8f98', N: '#8b8f98' };
const label = {
  doc: i => i < 0 ? 'Unknown (no assistance-file match)' : (DOC_LABEL[D.doc[i]] || D.doc[i]),
  program: i => i < 0 ? 'Unknown (no assistance-file match)' : D.program[i],
  status: i => i < 0 ? 'Unknown (no contract metadata)' : D.status[i],
  ropt: i => i < 0 ? 'None / no renewal record' : D.ropt[i],
};

/* ---------- state ---------- */
const COUNTS = { doc: new Map(), program: new Map(), status: new Map(), ropt: new Map() };
const progGroup = new Map();
for (const c of cons) {
  for (const k in COUNTS) COUNTS[k].set(c[k], (COUNTS[k].get(c[k]) || 0) + 1);
  if (c.program >= 0) progGroup.set(c.program, c.group);
}
const allOf = k => new Set(COUNTS[k].keys());
const defaults = () => ({
  doc: allOf('doc'), program: allOf('program'), status: allOf('status'), ropt: allOf('ropt'),
  yearMin: null, yearMax: null, yearUnknown: true, minTerm: 0,  // contract-term effective year + minimum length (months)
  bed: new Set([0, 1, 2, 3, 4, 5]), basis: new Set(['V', 'R', 'E', 'U']), loc: new Set(['P', 'A', 'C']), propOnly: false,
});
const state = { f: defaults(), center: null, radius: 3, view: 'lines', sort: null, selected: null, pinMode: false, result: null };
const PSEUDO = { doc: -1, program: -1, status: -1, ropt: -1, effYear: null, term: null };

/* ---------- filtering ---------- */
function contractOK(c) {
  const f = state.f;
  if (!f.doc.has(c.doc) || !f.program.has(c.program) || !f.status.has(c.status) || !f.ropt.has(c.ropt)) return false;
  if (f.minTerm && !(c.term >= f.minTerm)) return false;
  if (c.effYear == null) return f.yearUnknown;
  return (f.yearMin == null || c.effYear >= f.yearMin) && (f.yearMax == null || c.effYear <= f.yearMax);
}
const lineOK = l => state.f.bed.has(bedKey(l.bed)) && state.f.basis.has(l.basis);

function haversine(a, b, c, d) {
  const R = 3958.7613, r = Math.PI / 180, dl = (d - b) * r, da = (c - a) * r;
  const h = Math.sin(da / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function compute() {
  const f = state.f, ctr = state.center, lineDefault = f.bed.size === 6 && f.basis.size === 4;
  const out = []; let unlocated = 0, hiddenPropOnly = 0;
  for (const p of props) {
    const located = p.lc !== 'N';
    if (located && !f.loc.has(p.lc)) continue;
    if (ctr && located && p.dist > state.radius) continue;
    let mc = [];
    if (!p.cons.length) {
      if (!lineDefault || !contractOK(PSEUDO)) continue;
      if (!f.propOnly) { if (!ctr || located) hiddenPropOnly++; continue; }
    } else {
      for (const c of p.cons) {
        if (!contractOK(c)) continue;
        const ml = c.lines.filter(lineOK);
        if (!lineDefault && !ml.length) continue;
        mc.push({ c, lines: ml });
      }
      if (!mc.length) continue;
    }
    if (ctr && !located) { unlocated++; continue; }
    out.push({ p, mc, best: bestBasis(mc) });
  }
  return { out, unlocated, hiddenPropOnly };
}
function bestBasis(mc) {
  let b = 'N';
  for (const { lines: ls } of mc) for (const l of ls) if (b === 'N' || BASIS_ORDER[l.basis] < BASIS_ORDER[b]) b = l.basis;
  return b;
}

/* ---------- map ---------- */
// One shared canvas for dots, radius circle and highlight rings. A second canvas (Leaflet's default
// renderer) would stack on top of the dots and swallow their clicks.
const renderer = L.canvas({ padding: 0.5 });
const map = L.map('map', { preferCanvas: true, renderer, worldCopyJump: true }).setView([39.5, -98.35], 4);
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
const esriTiles = (svc, attr) => L.tileLayer(`${ESRI}${svc}/MapServer/tile/{z}/{y}/{x}`, { attribution: attr, maxZoom: 19, maxNativeZoom: svc.includes('Gray') ? 16 : 19 });
const ESRI_ATTR = 'Tiles &copy; Esri | HUD Multifamily Properties - Assisted';
const bases = {
  'Light gray': L.layerGroup([esriTiles('Canvas/World_Light_Gray_Base', ESRI_ATTR), esriTiles('Canvas/World_Light_Gray_Reference', '')]),
  'Streets': esriTiles('World_Street_Map', ESRI_ATTR),
  'Imagery': L.layerGroup([esriTiles('World_Imagery', 'Imagery &copy; Esri, Maxar, Earthstar Geographics'), esriTiles('Reference/World_Boundaries_and_Places', '')]),
};
bases['Light gray'].addTo(map);
L.control.layers(bases, null, { position: 'topright' }).addTo(map);
const markers = L.layerGroup().addTo(map);
let centerMarker = null, circle = null, hilite = null;
const legend = L.control({ position: 'bottomright' });
legend.onAdd = () => {
  const el = L.DomUtil.create('div', 'legend');
  el.innerHTML = ['V', 'R', 'E', 'N'].map(k => `<div><i style="background:${COLORS[k]}"></i>${k === 'V' ? 'Verified rent document' : k === 'R' ? 'Reported HUD rent' : k === 'E' ? 'Estimated gross only' : 'No rent data'}</div>`).join('')
    + '<div><i class="hollow"></i>Approximate location</div>';
  return el;
};
legend.addTo(map);

map.on('click', e => {
  if (!state.pinMode) return;
  setPinMode(false);
  setCenter({ lat: e.latlng.lat, lon: e.latlng.lng, label: `Dropped pin (${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)})` });
});

function drawMarkers(out) {
  markers.clearLayers();
  clearHover();
  const tips = out.length <= 4000;
  for (const r of out) {
    const p = r.p;
    if (p.lat == null) continue;
    const precise = p.lc === 'P';
    const m = L.circleMarker([p.lat, p.lon], {
      renderer, radius: state.center ? 7 : 4, weight: precise ? 1 : 1.5, color: precise ? '#fff' : COLORS[r.best],
      fillColor: COLORS[r.best], fillOpacity: precise ? 0.9 : 0.25, dashArray: precise ? null : '3 3',
    });
    if (tips) m.bindTooltip(`${esc(p.name || 'HUD ' + p.id)}${p.dist != null && state.center ? ` · ${p.dist.toFixed(2)} mi` : ''}`);
    m.on('click', () => { if (!state.pinMode) select(p, { fromMap: true }); });
    m.on('mouseover', () => setRowHover(p.id));
    m.on('mouseout', () => setRowHover(null));
    markers.addLayer(m);
  }
}
function drawCenter() {
  if (centerMarker) { map.removeLayer(centerMarker); centerMarker = null; }
  if (circle) { map.removeLayer(circle); circle = null; }
  if (!state.center) return;
  const ll = [state.center.lat, state.center.lon];
  circle = L.circle(ll, { radius: state.radius * 1609.344, color: '#1f4e99', weight: 1.2, fillOpacity: 0.04, interactive: false }).addTo(map);
  centerMarker = L.marker(ll, {
    draggable: true, zIndexOffset: 1000, title: 'Search center (drag to move)',
    icon: L.divIcon({ className: '', html: '<div style="width:22px;height:22px;border-radius:50%;border:3px solid #b42318;box-shadow:0 0 0 2px #fff, inset 0 0 0 1.5px #fff"></div>', iconSize: [22, 22], iconAnchor: [11, 11] }),
  }).addTo(map);
  centerMarker.on('dragend', e => {
    const g = e.target.getLatLng();
    setCenter({ lat: g.lat, lon: g.lng, label: `Dropped pin (${g.lat.toFixed(5)}, ${g.lng.toFixed(5)})` }, { fit: false });
  });
}
function drawHilite() {
  if (hilite) { map.removeLayer(hilite); hilite = null; }
  const p = state.selected && byId.get(state.selected);
  if (p && p.lat != null) hilite = L.layerGroup([
    L.circleMarker([p.lat, p.lon], { radius: 14, color: '#111', weight: 3.5, fill: false, interactive: false }),
    L.circleMarker([p.lat, p.lon], { radius: 11, color: '#fff', weight: 2, fill: false, interactive: false }),
  ]).addTo(map);
}
// Table row hover -> red ring on its dot; dot hover -> its rows tinted.
let hoverRing = null;
function clearHover() { if (hoverRing) { map.removeLayer(hoverRing); hoverRing = null; } }
function showHover(p) {
  if (hoverRing?.pid === p.id) return;
  clearHover();
  if (p.lat == null) return;
  hoverRing = L.circleMarker([p.lat, p.lon], { radius: 12, color: '#b42318', weight: 3, fill: false, interactive: false }).addTo(map);
  hoverRing.pid = p.id;
}
function setRowHover(pid) {
  document.querySelectorAll('#tbl tbody tr.hov').forEach(tr => tr.classList.remove('hov'));
  if (pid) document.querySelectorAll(`#tbl tbody tr[data-pid="${CSS.escape(pid)}"]`).forEach(tr => tr.classList.add('hov'));
}
// Keep a property's dot visible beside the detail panel, which overlays the right side of the map.
function panIntoView(p) {
  if (p.lat == null) return;
  const mr = $('#map').getBoundingClientRect(), det = $('#detail');
  const cover = det.hidden ? 0 : Math.max(0, mr.right - det.getBoundingClientRect().left);
  const visW = mr.width - cover;
  if (visW < 40) return map.panTo([p.lat, p.lon]);  // panel covers the map (phone layout)
  const pt = map.latLngToContainerPoint([p.lat, p.lon]), pad = 30;
  if (pt.x > pad && pt.x < visW - pad && pt.y > pad && pt.y < mr.height - pad) return;
  map.panBy([pt.x - visW / 2, pt.y - mr.height / 2]);
}

/* ---------- center / radius ---------- */
function setCenter(c, { fit = true } = {}) {
  state.center = c;
  if (c) for (const p of props) p.dist = p.lat == null ? null : haversine(c.lat, c.lon, p.lat, p.lon);
  else for (const p of props) p.dist = null;
  $('#centerInfo').innerHTML = c ? `<b>Center:</b> ${esc(c.label)}` : 'No center set. Search or drop a pin.';
  $('#centerInfo').classList.toggle('muted', !c);
  drawCenter();
  if (c && fit) map.fitBounds(circle.getBounds(), { padding: [20, 20] });
  refresh();
}
function setRadius(r) {
  if (!(r > 0)) return;
  state.radius = r;
  if (circle) { circle.setRadius(r * 1609.344); map.fitBounds(circle.getBounds(), { padding: [20, 20] }); }
  refresh();
}
function setPinMode(on) {
  state.pinMode = on;
  $('#pinBtn').classList.toggle('on', on);
  $('#pinBtn').textContent = on ? 'Click the map…' : 'Drop a pin';
  document.body.classList.toggle('pin-mode', on);
}

/* ---------- table ---------- */
const MAX_ROWS = 1000;
const fmtPct = v => v == null ? '' : v.toFixed(1) + '%';
const unk = v => v == null || v === '' ? UNK : v;
const pname = p => p.name || `(name unavailable) ${p.id}`;
const signedText = c => c.signed || (c.signedBad ? `${UNK} (source: ${c.signedBad})` : UNK);
const doc = c => c.doc < 0 ? UNK : D.doc[c.doc];
const badge = b => `<span class="b ${b}">${BASIS_SHORT[b]}</span>`;

const LINE_COLS = [
  { k: 'dist', h: 'Mi', n: 1, v: r => r.p.dist, f: v => v == null ? '' : v.toFixed(2) },
  { k: 'name', h: 'Property', v: r => r.p.name || null, f: (v, r) => esc(pname(r.p)) },
  { k: 'city', h: 'City', v: r => r.p.city ? `${r.p.city}, ${r.p.st}` : '' },
  { k: 'con', h: 'Contract', v: r => r.c.no },
  { k: 'doc', h: 'Type', v: r => doc(r.c) },
  { k: 'prog', h: 'Program', v: r => dict('program', r.c.program) || UNK },
  { k: 'status', h: 'Status', v: r => dict('status', r.c.status) || UNK },
  { k: 'bed', h: 'BR', n: 1, v: r => r.l ? r.l.bed : null, f: v => v == null ? '' : v === 0 ? '0 (studio)' : v },
  { k: 'units', h: 'Units', n: 1, v: r => r.l ? r.l.units : null, f: num },
  { k: 'rent', h: 'Contract rent', n: 1, v: r => r.l ? r.l.rent : null, f: (v, r) => v != null ? money(v) : r.l && r.l.basis === 'E' ? '<span class="muted" title="Utility allowance not reported, so contract rent is not estimated">n/a</span>' : '' },
  { k: 'ua', h: 'UA', n: 1, v: r => r.l ? r.l.ua : null, f: (v, r) => v != null ? money(v) : r.l && r.l.basis !== 'V' && r.l.basis !== 'R' ? '<span class="muted">unknown</span>' : '' },
  { k: 'gross', h: 'Gross rent', n: 1, v: r => r.l ? r.l.gross : null, f: (v, r) => v == null ? '' : money(v) + (r.l.basis === 'E' ? ' <span class="est">est.</span>' : '') },
  { k: 'basis', h: 'Basis', v: r => r.l ? BASIS_ORDER[r.l.basis] : 9, f: (v, r) => r.l ? badge(r.l.basis) : '<span class="muted">no bedroom data</span>' },
  { k: 'src', h: 'Source', v: r => r.l ? (r.l.vd ? `${r.l.vd[0]}, eff. ${r.l.vd[1]}` : r.l.source) : '' },
  { k: 'pct', h: 'HUD rent/FMR', n: 1, v: r => r.c.pct, f: fmtPct },
  { k: 'eff', h: 'Term effective', v: r => r.c.eff || '' },
  { k: 'cur', h: 'Current exp.', v: r => r.c.curExp || '' },
  { k: 'ov', h: 'Overall exp.', v: r => r.c.ovExp || '' },
  { k: 'term', h: 'Term (mo)', n: 1, v: r => r.c.term, f: num },
  { k: 'signed', h: 'Renewal owner-signed', v: r => r.c.signed || '', f: (v, r) => v || `<span class="muted">${r.c.signedBad ? 'Unknown*' : UNK}</span>` },
];
const PROP_COLS = [
  { k: 'dist', h: 'Mi', n: 1, v: r => r.p.dist, f: v => v == null ? '' : v.toFixed(2) },
  { k: 'name', h: 'Property', v: r => r.p.name || null, f: (v, r) => esc(pname(r.p)) },
  { k: 'addr', h: 'Address', v: r => r.p.addr },
  { k: 'city', h: 'City', v: r => r.p.city ? `${r.p.city}, ${r.p.st}` : '' },
  { k: 'ncon', h: 'Contracts', n: 1, v: r => r.mc.length, f: (v, r) => v === r.p.cons.length ? v : `${v} of ${r.p.cons.length}` },
  { k: 'prog', h: 'Programs', v: r => uniq(r.mc.map(m => dict('program', m.c.program) || UNK)).join(', ') },
  { k: 'status', h: 'Status', v: r => uniq(r.mc.map(m => dict('status', m.c.status) || UNK)).join(', ') },
  { k: 'assisted', h: 'Assisted units', n: 1, v: r => r.p.assisted, f: num },
  { k: 'mix', h: 'Bedroom mix (contract units)', v: r => bedMix(r.mc) },
  { k: 'best', h: 'Best rent basis', v: r => BASIS_ORDER[r.best] ?? 9, f: (v, r) => badge(r.best) },
  { k: 'cur', h: 'Next current exp.', v: r => minOf(r.mc.map(m => m.c.curExp)) },
  { k: 'signed', h: 'Latest owner-signed', v: r => maxOf(r.mc.map(m => m.c.signed)) },
  { k: 'loc', h: 'Location', v: r => r.p.lc, f: (v, r) => v === 'P' ? 'Precise' : v === 'A' ? '<span class="b out">Approx. (HUD)</span>' : v === 'C' ? '<span class="b out">ZIP centroid</span>' : '<span class="flag">None</span>' },
];
const uniq = a => [...new Set(a)];
const minOf = a => a.filter(Boolean).sort()[0] || '';
const maxOf = a => a.filter(Boolean).sort().pop() || '';
function bedMix(mc) {
  const t = new Map();
  for (const { c } of mc) {
    const seen = new Set();
    for (const l of c.lines) if (!seen.has(l.bed)) { seen.add(l.bed); if (l.bedUnits != null) t.set(l.bed, (t.get(l.bed) || 0) + l.bedUnits); }
  }
  return [...t].sort((a, b) => a[0] - b[0]).map(([b, u]) => `${b === 0 ? '0BR' : b + 'BR'} ${u}`).join(' · ');
}

function rowsFor(view, out) {
  if (view === 'props') return out;
  const rows = [];
  for (const r of out) for (const { c, lines: ls } of r.mc) {
    if (ls.length) for (const l of ls) rows.push({ p: r.p, c, l });
    else if (!c.lines.length) rows.push({ p: r.p, c, l: null });
  }
  return rows;
}
function sortRows(rows, cols) {
  const s = state.sort || (state.center ? { k: 'dist', dir: 1 } : { k: 'name', dir: 1 });
  const col = cols.find(c => c.k === s.k) || cols[0];
  const key = r => { const v = col.v(r); return v == null || v === '' ? null : v; };
  return rows.map(r => [key(r), r]).sort((a, b) => {
    if (a[0] == null) return b[0] == null ? 0 : 1;
    if (b[0] == null) return -1;
    return (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0) * s.dir;
  }).map(x => x[1]);
}
function renderTable() {
  const cols = state.view === 'props' ? PROP_COLS : LINE_COLS;
  const rows = sortRows(rowsFor(state.view, state.result.out), cols);
  state.rows = rows;
  const s = state.sort || (state.center ? { k: 'dist', dir: 1 } : { k: 'name', dir: 1 });
  $('#tbl thead').innerHTML = '<tr>' + cols.map(c => `<th data-k="${c.k}" class="${c.n ? 'num' : ''}">${esc(c.h)}${s.k === c.k ? (s.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('') + '</tr>';
  let offset = 0;
  if (state.selected && rows.length > MAX_ROWS) {
    const at = rows.findIndex(r => r.p.id === state.selected);
    if (at >= MAX_ROWS) offset = Math.max(0, Math.min(at - 20, rows.length - MAX_ROWS));
  }
  const shown = rows.slice(offset, offset + MAX_ROWS);
  $('#tbl tbody').innerHTML = shown.map((r, i) => `<tr data-i="${offset + i}" data-pid="${esc(r.p.id)}" class="${r.p.id === state.selected ? 'sel' : ''}">` + cols.map(c => {
    const v = c.v(r);
    return `<td class="${c.n ? 'num' : ''}">${c.f ? c.f(v, r) : esc(v)}</td>`;
  }).join('') + '</tr>').join('');
  $('#more').textContent = rows.length > MAX_ROWS ? `Showing rows ${(offset + 1).toLocaleString()}–${(offset + shown.length).toLocaleString()} of ${rows.length.toLocaleString()}. Narrow the search or export to get all rows.` : '';
}

/* ---------- refresh ---------- */
function refresh() {
  state.result = compute();
  const { out, unlocated, hiddenPropOnly } = state.result;
  drawMarkers(out);
  drawHilite();
  renderTable();
  const nLines = out.reduce((a, r) => a + r.mc.reduce((b, m) => b + m.lines.length, 0), 0);
  const where = state.center ? ` within ${state.radius} mi of ${state.center.label}` : ' nationwide';
  let msg = `${out.length.toLocaleString()} properties · ${nLines.toLocaleString()} rent lines${where}`;
  if (unlocated) msg += ` · ${unlocated.toLocaleString()} matching records nationwide have no map location, so no radius can include them (find them by name, ID or contract #)`;
  if (hiddenPropOnly && !state.f.propOnly) msg += ` · ${hiddenPropOnly.toLocaleString()} property-only records hidden`;
  $('#summary').textContent = msg;
  updateFilterCounts();
  writeHash();
}

/* ---------- detail ---------- */
function select(p, { fromMap = false } = {}) {
  state.selected = p.id;
  renderDetail(p);
  drawHilite();
  const inTable = state.rows.some(r => r.p.id === p.id);
  if (inTable && !document.querySelector(`#tbl tbody tr[data-pid="${CSS.escape(p.id)}"]`)) renderTable();
  const trs = [...document.querySelectorAll('#tbl tbody tr')].filter(tr => {
    const on = tr.dataset.pid === p.id;
    tr.classList.toggle('sel', on);
    tr.classList.remove('flash');
    return on;
  });
  if (trs.length) {
    const wrap = $('.tablewrap'), wr = wrap.getBoundingClientRect(), head = $('#tbl thead').offsetHeight;
    const top = trs[0].getBoundingClientRect().top, bottom = trs[trs.length - 1].getBoundingClientRect().bottom;
    if (top < wr.top + head || bottom > wr.bottom) wrap.scrollTop += top - wr.top - head - Math.max(0, (wr.height - head - (bottom - top)) / 2);
    if (fromMap) { void trs[0].offsetWidth; trs.forEach(tr => tr.classList.add('flash')); }
  }
  $('#selNote').hidden = inTable;
  $('#selNote').textContent = inTable ? '' : `${pname(p)} is selected but doesn't match the current radius or filters, so it has no rows in the table.`;
  panIntoView(p);
  writeHash();
}
function kv(pairs) {
  return '<dl class="kv">' + pairs.filter(x => x).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v === '' || v == null ? `<span class="muted">${UNK}</span>` : v}</dd>`).join('') + '</dl>';
}
function renderDetail(p) {
  const matched = new Set((state.result.out.find(r => r.p === p)?.mc || []).map(m => m.c));
  const loc = p.lc === 'N' ? `<span class="flag">No location: ${esc(p.locNote)}</span>`
    : `${esc(LOC_CLASS[p.lc])}${p.lc !== 'P' ? ` <span class="muted">(${esc(p.locNote)})</span>` : ''}`;
  let h = `<h2>${esc(pname(p))}</h2>
    <div class="muted">${esc([p.addr, p.city, [p.st, p.zip].filter(Boolean).join(' ')].filter(Boolean).join(', ') || 'Address not in HUD property files')} · HUD property ID ${esc(p.id)}</div>`;
  h += kv([
    state.center && p.dist != null && ['Distance from center', `${p.dist.toFixed(2)} mi`],
    ['Location', loc],
    ['County / metro', esc([p.county, p.metro].filter(Boolean).join(' · '))],
    ['Property category', esc(p.propcat || '')],
    ['Total units', num(p.total)],
    ['Assisted units (property)', num(p.assisted)],
    ['Owner', esc(p.owner)],
    ['Management', esc(p.mgmt)],
    ['HUD servicing office', esc(p.office || '')],
    p.fha && ['FHA programs', esc(p.fha)],
  ]);
  h += `<h3>Contracts (${p.cons.length})${matched.size < p.cons.length ? ` <span class="cnt">· ${matched.size} match current filters</span>` : ''}</h3>`;
  if (!p.cons.length) h += '<p class="note">No assistance contract in the HUD source files for this property ID. That does not prove the property has no assistance.</p>';
  for (const c of p.cons) h += contractCard(c, matched.has(c));
  h += `<p class="note">Rents are monthly per unit. Reported amounts come from HUD's contract rent / utility file (two overlapping tabs, never added together). Estimates = assistance-file bedroom FMR × HUD contract gross-rent/FMR %, the same % for every bedroom size, so they are gross rents only. Contract rent is not estimated when the utility allowance is unknown. The HUD files do not publish a last-approved RCS date or market-reset date.</p>`;
  $('#detailBody').innerHTML = h;
  $('#detail').hidden = false;
  $('.detail-scroll').scrollTop = 0;
}
function contractCard(c, isMatch) {
  const head = `<div class="contract-head"><b>${esc(c.no)}</b><span class="b out">${esc(doc(c))}</span>
    <span>${esc(dict('program', c.program) || 'Program unknown')}${c.group >= 0 ? ` · ${esc(D.group[c.group])}` : ''}${c.pcat >= 0 ? ` · ${esc(D.pcat[c.pcat])}` : ''}</span>
    <span class="${c.status >= 0 && D.status[c.status] !== 'Active' ? 'flag' : ''}">${esc(dict('status', c.status) || 'Status unknown')}</span></div>`;
  const signed = c.signed ? esc(c.signed) : c.signedBad ? `<span class="muted">${UNK}: source shows ${esc(c.signedBad)}, treated as a placeholder/invalid date</span>` : '';
  const fields = kv([
    ['Contract assisted units', num(c.units) + (c.maxUnits != null ? ` <span class="muted">(max ${num(c.maxUnits)})</span>` : '')],
    ['HUD gross rent / FMR', c.pct != null ? `${c.pct.toFixed(2)}%${c.band >= 0 ? ` <span class="muted">(${esc(D.band[c.band])})</span>` : ''}` : ''],
    ['Contract-term effective date', esc(c.eff || '')],
    ['Current term expiration', esc(c.curExp || '')],
    ['Overall expiration', esc(c.ovExp || '')],
    ['Term (months)', num(c.term)],
    ['Renewal option', esc(dict('ropt', c.ropt) || '')],
    ['Renewal status / type', esc([dict('rstat', c.rstat), dict('rtype', c.rtype)].filter(Boolean).join(' · '))],
    ['Renewal expiration', esc(c.rexp || '')],
    ['Renewal rents final', esc(c.rfinal || '')],
    ['Renewal owner-signature date', signed],
    (c.rwCur || c.rwOv) && ['Renewal-file expirations', esc(`current ${c.rwCur || UNK} · overall ${c.rwOv || UNK}`)],
    ['Last approved RCS / market reset', '<span class="muted">Not published in HUD files</span>'],
  ]);
  let t = '';
  if (c.lines.length) {
    t = '<div class="scrollx"><table><thead><tr><th class="num">Units</th><th class="num">Contract rent</th><th class="num">UA</th><th class="num">Gross</th><th>Basis</th><th>Source</th><th class="num">FMR (asst. / rent file)</th></tr></thead><tbody>';
    let lastBed = null;
    for (const l of c.lines) {
      if (l.bed !== lastBed) {
        lastBed = l.bed;
        const src = l.bedSrc === 'A' ? 'assistance file' : l.bedSrc === 'R' ? 'largest single-tab cohort total' : l.bedSrc === 'V' ? 'verified document' : '';
        t += `<tr><td colspan="7" style="background:#f6f8fb"><b>${BED_LABEL(l.bed)}</b>${l.bedUnits != null ? ` · ${num(l.bedUnits)} contract units <span class="muted">(${src})</span>` : ''}</td></tr>`;
      }
      const ok = lineOK(l);
      const src = l.vd ? `${esc(l.vd[0])}, eff. ${esc(l.vd[1])}${l.vd[2] ? ` · <a href="${esc(l.vd[2])}" target="_blank" rel="noopener">open</a>` : ''}` : esc(l.source);
      const fmr = [l.fmrAssist, l.fmrRent].map(v => v == null ? '–' : money(v)).join(' / ') + (l.fmr2 ? ` <span class="muted">(Tab 2: ${money(l.fmr2)})</span>` : '');
      const notes = [l.flag, l.vd && l.vd[3]].filter(Boolean).map(esc).join('; ');
      t += `<tr style="${ok ? '' : 'opacity:.45'}"><td class="num">${num(l.units)}</td>
        <td class="num">${l.rent != null ? money(l.rent) : l.basis === 'E' ? '<span class="muted" title="UA unknown">n/a</span>' : ''}</td>
        <td class="num">${l.ua != null ? money(l.ua) : (l.basis === 'E' || l.basis === 'U') ? '<span class="muted">unknown</span>' : ''}</td>
        <td class="num">${l.gross != null ? money(l.gross) + (l.basis === 'E' ? ' <span class="est">est.</span>' : '') : ''}</td>
        <td>${badge(l.basis)}</td><td class="srccell">${src}</td><td class="num">${fmr}</td></tr>`;
      if (notes) t += `<tr style="${ok ? '' : 'opacity:.45'}"><td></td><td colspan="6" class="linenote${l.basis === 'V' ? ' info' : ''}">${notes}</td></tr>`;
    }
    t += '</tbody></table></div>';
  } else t = '<p class="note">No bedroom-level rent or unit data for this contract in the source files.</p>';
  return `<div class="contract ${isMatch ? '' : 'dim'}">${head}${fields}${t}</div>`;
}

/* ---------- filters UI ---------- */
function checkList(el, items, set, onChange, opts = {}) {
  el.innerHTML = items.map(it => it.group ? `<div class="grp">${esc(it.group)}</div>` :
    `<label class="chk"><input type="checkbox" value="${esc(it.v)}" ${set.has(it.v) ? 'checked' : ''}><span>${esc(it.label)}</span>${it.n != null ? `<span class="n">${it.n.toLocaleString()}</span>` : ''}</label>`).join('');
  el.onchange = e => {
    const raw = e.target.value, v = opts.numeric ? +raw : raw;
    e.target.checked ? set.add(v) : set.delete(v);
    onChange();
  };
}
function buildFilters() {
  const f = state.f;
  const sortByCount = k => [...COUNTS[k]].sort((a, b) => b[1] - a[1]);
  for (const k of ['doc', 'status', 'ropt']) {
    const items = sortByCount(k).map(([v, n]) => ({ v, label: label[k](v), n }));
    if (k === 'ropt') items.sort((a, b) => (a.v < 0) - (b.v < 0) || a.label.localeCompare(b.label, undefined, { numeric: true }));
    checkList($(`#f-${k}`), items, f[k], refresh, { numeric: true });
  }
  // programs grouped by HUD program group
  const groups = new Map();
  for (const [v, n] of COUNTS.program) {
    const g = v < 0 ? 'Unknown' : (progGroup.get(v) >= 0 ? D.group[progGroup.get(v)] : 'Other');
    if (!groups.has(g)) groups.set(g, { n: 0, items: [] });
    groups.get(g).n += n; groups.get(g).items.push({ v, label: label.program(v), n });
  }
  const pitems = [];
  for (const [g, o] of [...groups].sort((a, b) => b[1].n - a[1].n)) { pitems.push({ group: g }); pitems.push(...o.items.sort((a, b) => b.n - a.n)); }
  checkList($('#f-program'), pitems, f.program, refresh, { numeric: true });
  checkList($('#f-bed'), [0, 1, 2, 3, 4, 5].map(v => ({ v, label: v === 0 ? 'Studio' : v === 5 ? '5+' : `${v} BR` })), f.bed, refresh, { numeric: true });
  checkList($('#f-basis'), ['V', 'R', 'E', 'U'].map(v => ({ v, label: BASIS_LABEL[v], n: H.meta.basis_counts[v] || 0 })), f.basis, refresh);
  const locN = { P: 0, A: 0, C: 0 }; let none = 0;
  for (const p of props) p.lc === 'N' ? none++ : locN[p.lc]++;
  checkList($('#f-loc'), ['P', 'A', 'C'].map(v => ({ v, label: LOC_CLASS[v], n: locN[v] })), f.loc, refresh);
  $('#f-loc').insertAdjacentHTML('beforeend', `<p class="hint">${none.toLocaleString()} property IDs have no location (mostly IDs with no property/address match in HUD's property files). They stay searchable by name, ID or contract # but can't be placed in a radius.</p>`);
  $('#yearMin').value = f.yearMin ?? ''; $('#yearMax').value = f.yearMax ?? ''; $('#yearUnknown').checked = f.yearUnknown;
  $('#minTerm').value = String(f.minTerm);
  $('#propOnly').checked = f.propOnly;
}
function updateFilterCounts() {
  const f = state.f;
  for (const k of ['doc', 'program', 'status', 'ropt']) {
    const total = COUNTS[k].size;
    $(`#f-${k}-n`).textContent = f[k].size === total ? '(all)' : `(${f[k].size} of ${total})`;
  }
  const y = f.yearMin == null && f.yearMax == null ? 'any year' : `${f.yearMin ?? '…'}–${f.yearMax ?? '…'}`;
  const len = { 13: ', > 1 yr', 60: ', 5+ yrs', 240: ', 20+ yrs' }[f.minTerm] || '';
  $('#f-year-n').textContent = `(${y}${len}${f.yearUnknown && !f.minTerm ? ', incl. unknown' : ', known only'})`;
}

/* ---------- search ---------- */
let suggItems = [], suggHi = -1;
function localMatches(q) {
  const toks = q.toLowerCase().replace(/[.,;#]/g, ' ').split(/\s+/).filter(Boolean);
  if (!toks.length) return [];
  const res = [];
  for (const p of props) {
    if (toks.every(t => p.s.includes(t))) {
      const nm = (p.name || '').toLowerCase();
      const score = p.id === q.trim() ? 0 : p.cons.some(c => c.no.toLowerCase() === q.trim().toLowerCase()) ? 0 : nm.startsWith(toks[0]) ? 1 : nm.includes(toks[0]) ? 2 : 3;
      res.push([score, p]);
      if (res.length > 400) break;
    }
  }
  return res.sort((a, b) => a[0] - b[0] || (a[1].lc === 'N') - (b[1].lc === 'N')).slice(0, 10).map(x => x[1]);
}
function showSugg(items) {
  suggItems = items; suggHi = items.length ? 0 : -1;
  const el = $('#sugg');
  if (!items.length) { el.hidden = true; return; }
  el.innerHTML = items.map((it, i) => `<div data-i="${i}" class="${i === suggHi ? 'hi' : ''}">${it.html}</div>`).join('');
  el.hidden = false;
}
function suggest() {
  const q = $('#q').value.trim();
  if (!q) return showSugg([]);
  const items = localMatches(q).map(p => ({
    html: `${esc(pname(p))}<small>${esc([p.addr, p.city, p.st].filter(Boolean).join(', '))} · ${esc(p.id)}${p.lc === 'N' ? ' · no map location' : ''}</small>`,
    go: () => pickProperty(p),
  }));
  const ll = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (ll) items.unshift({ html: `Use coordinates ${esc(q)}`, go: () => setCenter({ lat: +ll[1], lon: +ll[2], label: `Coordinates ${q}` }) });
  else items.push({ html: `Find address on map: “${esc(q)}”<small>Esri World Geocoder (sends this text to geocode.arcgis.com)</small>`, go: () => geocode(q) });
  showSugg(items);
}
function pickProperty(p) {
  $('#sugg').hidden = true;
  $('#q').value = pname(p);
  if (p.lat != null) setCenter({ lat: p.lat, lon: p.lon, label: `${pname(p)}${p.lc !== 'P' ? ' (approximate location)' : ''}`, pid: p.id });
  select(p);
}
async function geocode(q) {
  const el = $('#sugg');
  el.hidden = false; el.innerHTML = '<div>Geocoding…</div>';
  try {
    const u = 'https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?' +
      new URLSearchParams({ SingleLine: q, f: 'json', maxLocations: '6', countryCode: 'USA', outFields: 'Match_addr' });
    const d = await (await fetch(u)).json();
    const cands = (d.candidates || []).filter(c => c.score >= 70);
    if (!cands.length) { el.innerHTML = '<div>No address match.</div>'; return; }
    showSugg(cands.map(c => ({ html: `${esc(c.address)}<small>match score ${Math.round(c.score)}</small>`, go: () => { el.hidden = true; setCenter({ lat: c.location.y, lon: c.location.x, label: c.address }); } })));
  } catch (err) { el.innerHTML = `<div class="flag">Geocoder unavailable (${esc(err.message)}). Drop a pin instead.</div>`; }
}

/* ---------- export ---------- */
function csvCell(v) { if (v == null) return ''; const s = String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; }
function download(name, rows) {
  const blob = new Blob(['﻿' + rows.map(r => r.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function exportName(kind) {
  const c = state.center, d = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const tag = c ? `${(c.label || 'pin').replace(/[^A-Za-z0-9]+/g, '-').slice(0, 40)}-${state.radius}mi` : 'national';
  return `HUD-${kind}-${tag}-${d}.csv`;
}
function linesTable() {
  const head = ['Distance (mi)', 'HUD property ID', 'Property', 'Address', 'City', 'State', 'ZIP', 'Location precision', 'Contract number', 'Contract type',
    'Assistance program', 'Program group', 'Contract status', 'Bedrooms', 'Units in line', 'Contract bedroom units', 'Contract rent', 'Utility allowance',
    'Gross rent', 'Rent basis', 'Rent source', 'Assistance-file FMR', 'Rent-file FMR', 'Gross rent / rent-file FMR', 'HUD contract rent/FMR %',
    'Contract-term effective date', 'Current term expiration', 'Overall expiration', 'Contract term (months)', 'Renewal option', 'Renewal status', 'Renewal type',
    'Renewal owner-signature date', 'Owner-signature date in source (if invalid)', 'Review notes', 'Verified document', 'Verified effective date'];
  const rows = sortRows(rowsFor('lines', state.result.out), LINE_COLS).map(({ p, c, l }) => [
    p.dist != null && state.center ? p.dist.toFixed(2) : '', p.id, p.name, p.addr, p.city, p.st, p.zip, LOC_CLASS[p.lc], c.no, doc(c),
    dict('program', c.program) || UNK, dict('group', c.group) || UNK, dict('status', c.status) || UNK, l?.bed, l?.units, l?.bedUnits,
    l?.rent, l?.ua, l?.gross, l ? BASIS_LABEL[l.basis] : 'No bedroom data', l?.source, l?.fmrAssist, l?.fmrRent, l?.q, c.pct,
    c.eff, c.curExp, c.ovExp, c.term, dict('ropt', c.ropt), dict('rstat', c.rstat), dict('rtype', c.rtype),
    c.signed || UNK, c.signedBad, [l?.flag, l?.vd?.[3]].filter(Boolean).join('; '), l?.vd?.[0], l?.vd?.[1]]);
  return [head, ...rows];
}
const exportLines = () => download(exportName('rents-by-bedroom'), linesTable());
function propsTable() {
  const head = ['Distance (mi)', 'HUD property ID', 'Property', 'Address', 'City', 'State', 'ZIP', 'County', 'Location precision', 'Total units',
    'Assisted units (property)', 'Matching contracts', 'All contracts', 'Contract numbers', 'Contract types', 'Programs', 'Statuses',
    'Bedroom mix (contract units)', 'Best rent basis', 'Next current expiration', 'Latest renewal owner-signature date', 'Owner', 'Management'];
  const rows = sortRows(state.result.out, PROP_COLS).map(r => [
    r.p.dist != null && state.center ? r.p.dist.toFixed(2) : '', r.p.id, r.p.name, r.p.addr, r.p.city, r.p.st, r.p.zip, r.p.county, LOC_CLASS[r.p.lc],
    r.p.total, r.p.assisted, r.mc.length, r.p.cons.length, r.mc.map(m => m.c.no).join('; '), uniq(r.mc.map(m => doc(m.c))).join('; '),
    uniq(r.mc.map(m => dict('program', m.c.program) || UNK)).join('; '), uniq(r.mc.map(m => dict('status', m.c.status) || UNK)).join('; '),
    bedMix(r.mc), BASIS_SHORT[r.best], minOf(r.mc.map(m => m.c.curExp)), maxOf(r.mc.map(m => m.c.signed)) || UNK, r.p.owner, r.p.mgmt]);
  return [head, ...rows];
}
const exportProps = () => download(exportName('properties'), propsTable());

/* ---------- URL hash (shareable state) ---------- */
let hashLock = false;
function writeHash() {
  if (hashLock) return;
  const h = new URLSearchParams();
  if (state.center?.pid) h.set('pid', state.center.pid);
  else if (state.center) { h.set('lat', state.center.lat.toFixed(6)); h.set('lon', state.center.lon.toFixed(6)); }
  if (state.center) h.set('r', state.radius);
  if (state.selected && state.selected !== state.center?.pid) h.set('sel', state.selected);
  try { history.replaceState(null, '', h.toString() ? '#' + h : location.pathname + location.search); } catch { /* some file:// contexts */ }
}
function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  hashLock = true;
  if (h.get('r')) { state.radius = +h.get('r'); syncRadiusUI(); }
  const p = h.get('pid') && byId.get(h.get('pid'));
  if (p) pickProperty(p);
  else if (h.get('lat') && h.get('lon')) setCenter({ lat: +h.get('lat'), lon: +h.get('lon'), label: `Pin (${h.get('lat')}, ${h.get('lon')})` });
  const s = h.get('sel') && byId.get(h.get('sel'));
  if (s) select(s);
  hashLock = false;
  writeHash();
}
function syncRadiusUI() {
  const opt = [...$('#radius').options].find(o => +o.value === state.radius);
  if (opt) { $('#radius').value = opt.value; $('#radiusCustom').value = ''; } else $('#radiusCustom').value = state.radius;
}

/* ---------- about ---------- */
function renderAbout() {
  const m = H.meta, s = m.stats;
  $('#asof').textContent = `HUD files published ${m.hud_published} · downloaded ${m.downloaded} · ${m.properties.toLocaleString()} property IDs · ${m.contracts.toLocaleString()} contracts`;
  $('#aboutBody').innerHTML = `<h2 style="margin-top:0">About the data</h2>
  <p>Source: <b>${esc(m.workbook)}</b> (tab <i>HUD National Rents</i>, ${m.source_rows.toLocaleString()} rows; formula values read from the saved workbook and re-checked against the reconciliation formulas). Built ${esc(m.built)}.</p>
  <h3>Rents</h3><ul>
  <li><b>Reported</b>: contract rent and utility allowance from HUD's contract rent/utility file. Gross = rent + UA. Reported $0 rents are kept and flagged.</li>
  <li><b>Estimated gross</b>: ROUND(assistance-file bedroom FMR × HUD contract gross-rent/FMR % ÷ 100). The single contract % is applied to every bedroom size, so mixed-bedroom results are estimates. Contract rent is <i>not</i> estimated because the UA is unknown. Missing UAs are never treated as $0.</li>
  <li><b>Verified document</b>: rents from a separately reviewed document (e.g., a signed HUD-92458 rent schedule). Shown alongside, never merged into, HUD amounts.</li>
  <li>The two HUD rent tabs overlap. ${s.profiles_identical.toLocaleString()} contract-bedrooms with identical rents in both tabs are shown once. ${s.profiles_conflict.toLocaleString()} with different rents keep both versions, labeled by tab. Units are never summed across tabs.</li></ul>
  <h3>Dates</h3><ul>
  <li><b>Contract-term effective year</b> (filter) = HUD <code>tracs_effective_date</code>, the start of the current contract (start + term months = overall expiration for 92% of contracts). 12-month contracts restart every year, so pair it with a minimum contract length to find newly started long-term contracts.</li>
  <li><b>Renewal owner-signed</b> (shown, not filtered) = HUD <code>owner_submitted_date</code>, the owner's signature on HUD's latest renewal action. For a new renewal contract it usually precedes the start date; for an "Amend Rents" action it is the latest rent change on an older contract. It is not the HAP execution date or when the quoted rent took effect. ${s.signed_valid.toLocaleString()} contracts have a usable date. ${s.signed_invalid} contracts show placeholder or future dates (e.g., 1900-01-02 or 2099) and are treated as unknown.</li>
  <li>Contract-term effective / current / overall expiration come from the assistance-contract file (with renewal-file dates shown separately). No reliable last-approved-RCS or market-reset date is published.</li></ul>
  <h3>Locations</h3><ul>
  <li>Coordinates from HUD's <a href="${esc(m.gis_source)}" target="_blank" rel="noopener">Multifamily Properties - Assisted</a> GIS layer (${m.gis_features.toLocaleString()} features, downloaded ${esc(m.gis_downloaded)}), joined by HUD property ID. ${s.loc_precise.toLocaleString()} precise (rooftop/ZIP+4), ${s.loc_approx_hud.toLocaleString()} approximate HUD geocodes (block group/tract/ZIP).</li>
  <li>${s.loc_zip_fallback.toLocaleString()} property IDs are not located by HUD's layer (mostly FHA-insured or other property-only records with no assistance contract). These are placed at the Census ZIP (ZCTA) centroid and flagged approximate.</li>
  <li>${s.loc_none.toLocaleString()} have no usable location, mostly rent records whose property ID has no property/address match in HUD's property files. They remain searchable by name, ID or contract number.</li>
  <li>Distances are great-circle (haversine) miles from the search center.</li></ul>
  <p class="note">HUD contract rents and FMRs are not market asking rents or RCS conclusions. Use for screening and verify before relying on any figure.</p>`;
}

/* ---------- resizable panes ---------- */
// Sizes live in CSS variables on <body>; remembered per browser (localStorage may be unavailable).
const SIZE_KEY = 'hudmap.sizes.v1';
let sizes = {};
try { sizes = JSON.parse(localStorage.getItem(SIZE_KEY)) || {}; } catch { sizes = {}; }
const saveSizes = () => { try { localStorage.setItem(SIZE_KEY, JSON.stringify(sizes)); } catch { /* private mode */ } };
const relayout = () => requestAnimationFrame(() => map.invalidateSize({ pan: false }));
function setSize(name, px) {
  if (px == null) { delete sizes[name]; document.body.style.removeProperty(name); }
  else { sizes[name] = Math.round(px); document.body.style.setProperty(name, sizes[name] + 'px'); }
  relayout();
}
const PANES = {
  splitSide: { name: '--side-w', axis: 'x', size: e => e.clientX - $('.layout').getBoundingClientRect().left,
    min: () => 220, max: () => Math.min(620, innerWidth - 420), cur: () => $('.side').getBoundingClientRect().width },
  splitMap: { name: '--map-h', axis: 'y', size: e => e.clientY - $('.main').getBoundingClientRect().top,
    min: () => 140, max: () => $('.main').getBoundingClientRect().height - 170, cur: () => $('#map').getBoundingClientRect().height },
  splitDetail: { name: '--detail-w', axis: 'x', size: e => $('.layout').getBoundingClientRect().right - e.clientX,
    min: () => 320, max: () => $('.layout').getBoundingClientRect().width - 160, cur: () => $('#detail').getBoundingClientRect().width, invert: true },
};
function setMapMax(on) {
  document.body.classList.toggle('map-max', on);
  $('#expandMap').textContent = on ? 'Show table' : 'Expand map';
  relayout();
}
for (const [id, P] of Object.entries(PANES)) {
  const el = document.getElementById(id), clamp = v => Math.max(P.min(), Math.min(P.max(), v));
  el.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    e.preventDefault();
    if (id === 'splitMap') setMapMax(false);
    el.setPointerCapture(e.pointerId);
    el.classList.add('active');
    document.body.classList.add('resizing', P.axis === 'x' ? 'res-col' : 'res-row');
    const move = ev => setSize(P.name, clamp(P.size(ev)));
    const up = () => {
      el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up);
      el.classList.remove('active'); document.body.classList.remove('resizing', 'res-col', 'res-row');
      saveSizes();
    };
    el.addEventListener('pointermove', move); el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
  });
  el.addEventListener('dblclick', () => { if (id === 'splitMap') setMapMax(false); setSize(P.name, null); saveSizes(); });
  el.addEventListener('keydown', e => {  // arrow keys nudge by 24px
    const grow = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!grow) return;
    e.preventDefault();
    setSize(P.name, clamp(P.cur() + grow * 24 * (P.invert ? -1 : 1))); saveSizes();
  });
}
for (const [name, px] of Object.entries(sizes)) document.body.style.setProperty(name, px + 'px');
$('#expandMap').onclick = () => setMapMax(!document.body.classList.contains('map-max'));
addEventListener('resize', relayout);

/* ---------- wiring ---------- */
let t;
$('#q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(suggest, 120); });
$('#q').addEventListener('keydown', e => {
  const el = $('#sugg');
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    if (!suggItems.length) return;
    suggHi = (suggHi + (e.key === 'ArrowDown' ? 1 : -1) + suggItems.length) % suggItems.length;
    [...el.children].forEach((c, i) => c.classList.toggle('hi', i === suggHi)); e.preventDefault();
  } else if (e.key === 'Enter') { if (suggItems[suggHi]) suggItems[suggHi].go(); }
  else if (e.key === 'Escape') el.hidden = true;
});
$('#sugg').addEventListener('click', e => { const d = e.target.closest('[data-i]'); if (d) suggItems[+d.dataset.i]?.go(); });
document.addEventListener('click', e => { if (!e.target.closest('.searchwrap')) $('#sugg').hidden = true; });
$('#pinBtn').onclick = () => setPinMode(!state.pinMode);
$('#clearBtn').onclick = () => { $('#q').value = ''; setCenter(null); map.setView([39.5, -98.35], 4); };
$('#radius').onchange = e => { $('#radiusCustom').value = ''; setRadius(+e.target.value); };
$('#radiusCustom').onchange = e => { if (+e.target.value > 0) setRadius(+e.target.value); };
$('#yearMin').onchange = e => { state.f.yearMin = e.target.value ? +e.target.value : null; refresh(); };
$('#yearMax').onchange = e => { state.f.yearMax = e.target.value ? +e.target.value : null; refresh(); };
$('#yearUnknown').onchange = e => { state.f.yearUnknown = e.target.checked; refresh(); };
$('#minTerm').onchange = e => { state.f.minTerm = +e.target.value; refresh(); };
$('#propOnly').onchange = e => { state.f.propOnly = e.target.checked; refresh(); };
$('#resetFilters').onclick = () => { state.f = defaults(); buildFilters(); refresh(); };
document.querySelectorAll('[data-all],[data-none]').forEach(b => b.onclick = () => {
  const k = b.dataset.all || b.dataset.none;
  state.f[k] = b.dataset.all ? allOf(k) : new Set(); buildFilters(); refresh();
});
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === b));
  state.view = b.dataset.view; state.sort = null; renderTable();
});
$('#tbl thead').addEventListener('click', e => {
  const th = e.target.closest('th'); if (!th) return;
  const k = th.dataset.k, cur = state.sort || (state.center ? { k: 'dist', dir: 1 } : { k: 'name', dir: 1 });
  state.sort = { k, dir: cur.k === k ? -cur.dir : 1 }; renderTable();
});
$('#tbl tbody').addEventListener('click', e => { const tr = e.target.closest('tr'); if (tr) select(state.rows[+tr.dataset.i].p); });
$('#tbl tbody').addEventListener('mouseover', e => { const p = byId.get(e.target.closest('tr')?.dataset.pid); if (p) showHover(p); });
$('#tbl tbody').addEventListener('mouseleave', clearHover);
$('#closeDetail').onclick = () => {
  $('#detail').hidden = true; state.selected = null; drawHilite(); writeHash();
  document.querySelectorAll('#tbl tbody tr.sel').forEach(tr => tr.classList.remove('sel'));
  $('#selNote').hidden = true;
};
$('#exportLines').onclick = exportLines;
$('#exportProps').onclick = exportProps;
$('#aboutBtn').onclick = () => $('#about').showModal();

renderAbout();
buildFilters();
hashLock = true; refresh(); hashLock = false;  // keep an incoming #pid=… hash for readHash()
readHash();
$('#loading').remove();

// Exposed for console checks and automated tests.
window.HUDMAP = { state, map, props, cons, lines, byId, D, compute, defaults, setCenter, setRadius, pickProperty, select, refresh, rowsFor, haversine, localMatches, linesTable, propsTable };
})();

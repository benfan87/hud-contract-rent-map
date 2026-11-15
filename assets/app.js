/* HUD Contract Rent Map: search, radius, filters, linked map + table, detail, CSV export.
   Data: assets/hud_data.js (rents/UAs refreshed by tools/merge_rent_ua.py). No server needed. */
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
// Financing, LIHTC and 2027 QCT/DDA (tools/merge_fha.py, tools/merge_lihtc.py, tools/build_qct_dda.py)
for (const p of props) { p.loans = []; p.ownSince = H.P[p.i][19] || null; p.ownYear = p.ownSince ? +p.ownSince.slice(0, 4) : null; p.lih = null; p.qct = null; p.dda = null; }
for (const f of (H.F || [])) props[f[0]].loans.push({ fha: f[1], soa: f[2], soaCode: f[3], primary: f[4], insured: f[5], initEnd: f[6], finalEnd: f[7],
  amt: f[8], maturity: f[9], rate: f[10], upb: f[11], holder: dict('lender', f[12]), servicer: dict('lender', f[13]), te: f[14], tc: f[15], term: f[16] });
for (const p of props) p.loans.sort((a, b) => b.primary - a.primary);
const LIREC = (H.LI || []).map(r => ({ project: r[0], addr: r[1], city: r[2], st: r[3], zip: r[4], id: r[5], hudId: r[6], alloc: r[7], pis: r[8],
  credit: r[9], bond: r[10], type: r[11], units: r[12], liUnits: r[13], src: D.lsrc[r[14]], url: D.lsrcUrl[r[14]], company: r[15] }));
for (const r of (H.PL || [])) props[r[0]].lih = { links: r[1].map(([i, t, why]) => ({ rec: LIREC[i], tier: t, why })), best: r[2],
  lastAlloc: r[3], lastPis: r[4], y15: r[5], y15est: !!r[6], resynd: r[7], first: r[8] };
for (const z of (H.Z || [])) { props[z[0]].qct = !!z[1]; props[z[0]].dda = !!z[2]; }
// Owner / management-agent contacts and sponsor groups (tools/merge_owners.py)
const SP = D.spon || [], SP_N = new Map();
const rec9 = r => r && { pid: r[0], name: r[1], type: r[2], addr: r[3], city: r[4], st: r[5], zip: r[6], phone: r[7], email: r[8] };
for (const p of props) { p.ow = null; p.ag = null; p.spon = -1; }
for (const r of (H.OW || [])) {
  const p = props[r[0]], o = r[1] >= 0 ? D.own[r[1]] : null;
  p.ow = rec9(o); p.ag = r[2] >= 0 ? rec9(D.mga[r[2]]) : null; p.spon = o && o[9] != null ? o[9] : -1;
  if (p.spon >= 0) SP_N.set(p.spon, (SP_N.get(p.spon) || 0) + 1);
}
const sponLabel = i => i == null || i < 0 ? '' : SP[i][1] === 'email' ? '@' + SP[i][0] : SP[i][0];
const SP_TEXT = new Map();  // sponsor -> searchable text (label + owner entity names)
for (const p of props) if (p.spon >= 0) SP_TEXT.set(p.spon, (SP_TEXT.get(p.spon) || SP[p.spon][0].toLowerCase()) + ' | ' + (p.ow.name || '').toLowerCase());
const STATE_NAMES = { AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware',
  DC: 'District of Columbia', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky',
  LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana',
  NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio',
  OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah',
  VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming', PR: 'Puerto Rico', VI: 'U.S. Virgin Islands',
  GU: 'Guam', AS: 'American Samoa', MP: 'Northern Mariana Islands' };
const stName = c => c ? `${STATE_NAMES[c] || c} (${c})` : 'Unknown state';
const STATE_N = new Map();
for (const p of props) STATE_N.set(p.st || '', (STATE_N.get(p.st || '') || 0) + 1);
const CITY_N = new Map();  // "CITY|ST" -> property count
for (const p of props) {
  p.ck = (p.city || '').trim().toUpperCase().replace(/\s+/g, ' ') + '|' + (p.st || '');
  if (p.city) CITY_N.set(p.ck, (CITY_N.get(p.ck) || 0) + 1);
}
const titleCase = t => t.toLowerCase().replace(/\b[a-z]/g, c => c.toUpperCase());
const cityLabel = k => { const [c, st] = k.split('|'); return `${titleCase(c)}${st ? ', ' + st : ''}`; };
const pSize = p => p.total || p.assisted || null;  // total units (assisted units when HUD has no total)
const SOA_N = new Map();
for (const p of props) {
  p.soaKeys = p.loans.length ? [...new Set(p.loans.map(l => l.soa))] : [-1];
  for (const k of p.soaKeys) SOA_N.set(k, (SOA_N.get(k) || 0) + 1);
}
const cons = H.C.map((c, i) => ({
  i, p: c[0], no: c[1], status: c[2], program: c[3], group: c[4], pcat: c[5], doc: c[6], units: c[7], maxUnits: c[8],
  eff: c[9], curExp: c[10], ovExp: c[11], term: c[12], ropt: c[13], rstat: c[14], rexp: c[15], rfinal: c[16],
  pct: c[17], band: c[18], rtype: c[19], signed: c[20], signedYear: c[21], signedBad: c[22], rwCur: c[23], rwOv: c[24], lines: [],
  effYear: c[9] ? +c[9].slice(0, 4) : null, ovYear: c[11] ? +c[11].slice(0, 4) : null,
}));
// Old contract: number only in HUD's rent/UA file, not in HUD's active Section 8 contract list (no type, program,
// status or dates). Usually a predecessor contract that a renewal or combined contract replaced.
const OLD_STATUS = 'Not in HUD active list';
for (const c of cons) c.old = c.status < 0 && c.program < 0 && c.doc < 0 && !c.eff;
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
  if (c.old) continue;
  for (const k in COUNTS) COUNTS[k].set(c[k], (COUNTS[k].get(c[k]) || 0) + 1);
  if (c.program >= 0) progGroup.set(c.program, c.group);
}
const allOf = k => new Set((k === 'soa' ? SOA_N : k === 'st' ? STATE_N : COUNTS[k]).keys());
const defaults = () => ({
  doc: allOf('doc'), program: allOf('program'), status: allOf('status'), ropt: allOf('ropt'),
  yearMin: null, yearMax: null, yearUnknown: true, minTerm: 0,  // contract-term effective year + minimum length (months)
  ovMin: null, ovMax: null, ovUnknown: false,  // overall contract expiration year (unknown dates are left out while a range is set)
  ownMin: null, ownMax: null,  // ownership effective year (properties without a date are left out while a range is set)
  bed: new Set([0, 1, 2, 3, 4, 5]), basis: new Set(['V', 'R', 'E', 'U']), loc: new Set(['P', 'A', 'C']), propOnly: false, oldCons: false,
  st: allOf('st'), city: new Set(), spon: new Set(), unitsMin: null, unitsMax: null,
  soa: allOf('soa'), tcOnly: false, lih: 'any', lihPossible: false, y15Min: null, y15Max: null, allocBefore: null, zone: 'any',
});
const state = { f: defaults(), center: null, radius: 3, view: 'lines', sort: null, selected: null, pinMode: false, result: null };
const PSEUDO = { doc: -1, program: -1, status: -1, ropt: -1, effYear: null, ovYear: null, term: null };

/* ---------- filtering ---------- */
function contractOK(c) {
  const f = state.f;
  if (c.old) { if (!f.oldCons) return false; }  // no type/program/status to filter on
  else {
    // a value no listed contract has (e.g. "Unknown" for the property-only placeholder) can't be unticked, so it passes
    const ok = k => f[k].has(c[k]) || !COUNTS[k].has(c[k]);
    if (!ok('doc') || !ok('program') || !ok('status') || !ok('ropt')) return false;
  }
  if (f.minTerm && !(c.term >= f.minTerm)) return false;
  if (f.ovMin != null || f.ovMax != null) {
    if (c.ovYear == null) { if (!f.ovUnknown) return false; }
    else if ((f.ovMin != null && c.ovYear < f.ovMin) || (f.ovMax != null && c.ovYear > f.ovMax)) return false;
  }
  if (c.effYear == null) return f.yearUnknown;
  return (f.yearMin == null || c.effYear >= f.yearMin) && (f.yearMax == null || c.effYear <= f.yearMax);
}
const hasLih = (p, poss = state.f.lihPossible) => !!p.lih && p.lih.best <= (poss ? 2 : 1);
function propOK(p) {
  const f = state.f;
  if (f.st.size !== STATE_N.size && !f.st.has(p.st || '')) return false;
  if (f.city.size && !f.city.has(p.ck)) return false;
  if (f.spon.size && !f.spon.has(p.spon)) return false;
  if (f.unitsMin != null || f.unitsMax != null) {
    const u = pSize(p);
    if (u == null || (f.unitsMin != null && u < f.unitsMin) || (f.unitsMax != null && u > f.unitsMax)) return false;
  }
  if (f.ownMin != null || f.ownMax != null) {
    const y = p.ownYear;
    if (y == null || (f.ownMin != null && y < f.ownMin) || (f.ownMax != null && y > f.ownMax)) return false;
  }
  if (f.soa.size !== SOA_N.size && !p.soaKeys.some(k => f.soa.has(k))) return false;
  if (f.tcOnly && !p.loans.some(l => l.tc)) return false;
  const has = hasLih(p);
  if ((f.lih === 'yes' && !has) || (f.lih === 'no' && has)) return false;
  if (f.y15Min != null || f.y15Max != null) {
    const y = has ? p.lih.y15 : null;
    if (y == null || (f.y15Min != null && y < f.y15Min) || (f.y15Max != null && y > f.y15Max)) return false;
  }
  if (f.allocBefore != null && has && p.lih.lastAlloc != null && p.lih.lastAlloc >= f.allocBefore) return false;
  if (f.zone !== 'any') {
    if (p.qct == null) return false;
    if ((f.zone === 'qct' && !p.qct) || (f.zone === 'dda' && !p.dda) || (f.zone === 'either' && !p.qct && !p.dda)) return false;
  }
  return true;
}
const lineOK = l => state.f.bed.has(bedKey(l.bed)) && state.f.basis.has(l.basis);

function haversine(a, b, c, d) {
  const R = 3958.7613, r = Math.PI / 180, dl = (d - b) * r, da = (c - a) * r;
  const h = Math.sin(da / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function compute() {
  const f = state.f, ctr = state.center, lineDefault = f.bed.size === 6 && f.basis.size === 4;
  const out = []; let unlocated = 0, hiddenPropOnly = 0, hiddenOld = 0, hiddenOldProps = 0;
  for (const p of props) {
    if (!propOK(p)) continue;
    const located = p.lc !== 'N';
    if (located && !f.loc.has(p.lc)) continue;
    if (ctr && located && p.dist > state.radius) continue;
    let mc = [];
    if (!p.cons.length) {
      if (!lineDefault || !contractOK(PSEUDO)) continue;
      if (!f.propOnly) { if (!ctr || located) hiddenPropOnly++; continue; }
    } else {
      let oldHere = 0;
      for (const c of p.cons) {
        if (c.old && !f.oldCons) { oldHere++; continue; }
        if (!contractOK(c)) continue;
        const ml = c.lines.filter(lineOK);
        if (!lineDefault && !ml.length) continue;
        mc.push({ c, lines: ml });
      }
      if (oldHere && (!ctr || located)) { hiddenOld += oldHere; if (!mc.length && oldHere === p.cons.length) hiddenOldProps++; }
      if (!mc.length) continue;
    }
    if (ctr && !located) { unlocated++; continue; }
    out.push({ p, mc, best: bestBasis(mc) });
  }
  return { out, unlocated, hiddenPropOnly, hiddenOld, hiddenOldProps };
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
map.createPane('zones').style.zIndex = 350;  // below the dots canvas (overlayPane, 400)
const zoneRenderer = L.canvas({ pane: 'zones', padding: 0.5 });
const zoneLayers = { qct: L.layerGroup(), dda: L.layerGroup() };
const ZONE_STYLE = { qct: { color: '#7c3aed', fillColor: '#7c3aed' }, dda: { color: '#0d9488', fillColor: '#0d9488' } };
let zonesLoading = null;
function loadZones() {
  zonesLoading = zonesLoading || new Promise((res, rej) => {
    if (window.QCT_DDA_2027) return res();
    const sc = Object.assign(document.createElement('script'), { src: 'assets/qct_dda_2027.js', onload: res, onerror: rej });
    document.head.appendChild(sc);
  }).then(() => {
    for (const k of ['qct', 'dda']) L.geoJSON(window.QCT_DDA_2027[k], { renderer: zoneRenderer, interactive: false,
      style: { ...ZONE_STYLE[k], weight: 0.6, fillOpacity: 0.16 } }).addTo(zoneLayers[k]);
  }).catch(() => { zonesLoading = null; alert('Could not load the 2027 QCT/DDA layer.'); });
  return zonesLoading;
}
L.control.layers(bases, { '2027 QCTs (qualified census tracts)': zoneLayers.qct, '2027 DDAs (difficult development areas)': zoneLayers.dda }, { position: 'topright' }).addTo(map);
map.on('overlayadd', e => { if (e.layer === zoneLayers.qct || e.layer === zoneLayers.dda) loadZones(); });
const markers = L.layerGroup().addTo(map);
let centerMarker = null, circle = null, hilite = null;
const legend = L.control({ position: 'bottomright' });
legend.onAdd = () => {
  const el = L.DomUtil.create('div', 'legend');
  el.innerHTML = ['V', 'R', 'E', 'N'].map(k => `<div><i style="background:${COLORS[k]}"></i>${k === 'V' ? 'Verified rent document' : k === 'R' ? 'Reported HUD rent' : k === 'E' ? 'Estimated gross only' : 'No rent data'}</div>`).join('')
    + '<div><i class="hollow"></i>Approximate location</div>'
    + '<div><i style="background:#7c3aed;opacity:.5;border-radius:2px"></i>2027 QCT · <i style="background:#0d9488;opacity:.5;border-radius:2px"></i>2027 DDA <span class="muted">(layers menu)</span></div>';
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
const doc = c => c.old ? 'Old contract' : c.doc < 0 ? UNK : D.doc[c.doc];
const statusOf = c => c.old ? OLD_STATUS : dict('status', c.status) || UNK;
const programOf = c => c.old ? '—' : dict('program', c.program) || UNK;
const badge = b => `<span class="b ${b}">${BASIS_SHORT[b]}</span>`;

const loanText = p => uniq(p.loans.map(l => l.soa >= 0 ? D.soa[l.soa] : l.soaCode || 'Unknown')).join('; ');
const y15Html = p => !hasLih(p) || p.lih.y15 == null ? '' : p.lih.y15 + (p.lih.y15est ? ' <span class="est">est.</span>' : '');
const lihHtml = p => !p.lih ? '' : !hasLih(p) ? '<span class="muted">possible match</span>'
  : `${p.lih.lastAlloc ?? '–'} / ${p.lih.lastPis ?? '–'}${p.lih.resynd ? ` <span class="b out">resynd. ${p.lih.resynd}</span>` : ''}`;
const zoneText = p => p.qct == null ? '' : [p.qct && 'QCT', p.dda && 'DDA'].filter(Boolean).join(' + ') || 'No';
const LINE_COLS = [
  { k: 'dist', h: 'Mi', n: 1, v: r => r.p.dist, f: v => v == null ? '' : v.toFixed(2) },
  { k: 'name', h: 'Property', v: r => r.p.name || null, f: (v, r) => esc(pname(r.p)) },
  { k: 'city', h: 'City', v: r => r.p.city ? `${r.p.city}, ${r.p.st}` : '' },
  { k: 'con', h: 'Contract', v: r => r.c.no },
  { k: 'doc', h: 'Type', v: r => doc(r.c) },
  { k: 'prog', h: 'Program', v: r => programOf(r.c) },
  { k: 'status', h: 'Status', v: r => statusOf(r.c), f: (v, r) => r.c.old ? `<span class="b out" title="In HUD's rent/UA file only. Not in HUD's active Section 8 contract list; likely replaced by a renewal or combined contract. Rents may be years old.">${esc(v)}</span>` : esc(v) },
  { k: 'bed', h: 'BR', n: 1, v: r => r.l ? r.l.bed : null, f: v => v == null ? '' : v === 0 ? '0 (studio)' : v },
  { k: 'units', h: 'Units', n: 1, v: r => r.l ? r.l.units : null, f: num },
  { k: 'rent', h: 'Contract rent', n: 1, v: r => r.l ? r.l.rent : null, f: (v, r) => v != null ? money(v) : r.l && r.l.basis === 'E' ? '<span class="muted" title="Utility allowance not reported, so contract rent is not estimated">n/a</span>' : '' },
  { k: 'ua', h: 'UA', n: 1, v: r => r.l ? r.l.ua : null, f: (v, r) => v != null ? money(v) : r.l && r.l.basis !== 'V' && r.l.basis !== 'R' ? '<span class="muted">unknown</span>' : '' },
  { k: 'gross', h: 'Gross rent', n: 1, v: r => r.l ? r.l.gross : null, f: (v, r) => v == null ? '' : money(v) + (r.l.basis === 'E' ? ' <span class="est">est.</span>' : '') },
  { k: 'basis', h: 'Basis', v: r => r.l ? BASIS_ORDER[r.l.basis] : 9, f: (v, r) => r.l ? badge(r.l.basis) : '<span class="muted">no bedroom data</span>' },
  { k: 'src', h: 'Source', v: r => r.l ? (r.l.vd ? `${r.l.vd[0]}, eff. ${r.l.vd[1]}` : r.l.source) : '' },
  { k: 'pct', h: 'HUD rent/FMR', n: 1, v: r => r.c.pct, f: fmtPct },
  { k: 'loan', h: 'FHA loan', v: r => loanText(r.p) },
  { k: 'y15', h: 'LIHTC Year 15', n: 1, v: r => hasLih(r.p) ? r.p.lih.y15 : null, f: (v, r) => y15Html(r.p) },
  { k: 'zone', h: '2027 QCT/DDA', v: r => zoneText(r.p) },
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
  { k: 'prog', h: 'Programs', v: r => uniq(r.mc.map(m => programOf(m.c))).join(', ') },
  { k: 'status', h: 'Status', v: r => uniq(r.mc.map(m => statusOf(m.c))).join(', ') },
  { k: 'total', h: 'Total units', n: 1, v: r => pSize(r.p), f: num },
  { k: 'assisted', h: 'Assisted units', n: 1, v: r => r.p.assisted, f: num },
  { k: 'mix', h: 'Bedroom mix (contract units)', v: r => bedMix(r.mc) },
  { k: 'best', h: 'Best rent basis', v: r => BASIS_ORDER[r.best] ?? 9, f: (v, r) => badge(r.best) },
  { k: 'cur', h: 'Next current exp.', v: r => minOf(r.mc.map(m => m.c.curExp)) },
  { k: 'ov', h: 'Next overall exp.', v: r => minOf(r.mc.map(m => m.c.ovExp)) },
  { k: 'signed', h: 'Latest owner-signed', v: r => maxOf(r.mc.map(m => m.c.signed)) },
  { k: 'loan', h: 'FHA loan', v: r => loanText(r.p) },
  { k: 'lih', h: 'LIHTC alloc. / PIS', v: r => hasLih(r.p) ? (r.p.lih.lastAlloc ?? r.p.lih.lastPis) : null, f: (v, r) => lihHtml(r.p) },
  { k: 'y15', h: 'Year 15', n: 1, v: r => hasLih(r.p) ? r.p.lih.y15 : null, f: (v, r) => y15Html(r.p) },
  { k: 'zone', h: '2027 QCT/DDA', v: r => zoneText(r.p) },
  { k: 'owner', h: 'Owner', v: r => r.p.ow?.name || r.p.owner || '' },
  { k: 'own', h: 'Owned since', v: r => r.p.ownSince || '' },
  { k: 'spon', h: 'Owner group', v: r => sponLabel(r.p.spon) },
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
  const { out, unlocated, hiddenPropOnly, hiddenOld, hiddenOldProps } = state.result;
  drawMarkers(out);
  drawHilite();
  renderTable();
  const nLines = out.reduce((a, r) => a + r.mc.reduce((b, m) => b + m.lines.length, 0), 0);
  const stSel = state.f.st.size !== STATE_N.size ? [...state.f.st] : null;
  const inSt = stSel ? (stSel.length <= 3 ? stSel.map(c => STATE_NAMES[c] || c || 'unknown state').join(', ') : `${stSel.length} states`) : null;
  const cs = [...state.f.city], inCity = cs.length ? (cs.length <= 3 ? cs.map(cityLabel).join('; ') : `${cs.length} cities`) : null;
  const inSp = state.f.spon.size ? 'owner group ' + [...state.f.spon].map(sponLabel).join('; ') : null;
  const inArea = [inSp, inCity, inSt].filter(Boolean).join(' · ') || null;
  const where = state.center ? ` within ${state.radius} mi of ${state.center.label}${inArea ? ` (${inArea} only)` : ''}` : inArea ? ` in ${inArea}` : ' nationwide';
  let msg = `${out.length.toLocaleString()} properties · ${nLines.toLocaleString()} rent lines${where}`;
  if (unlocated) msg += ` · ${unlocated.toLocaleString()} matching records nationwide have no map location, so no radius can include them (find them by name, ID or contract #)`;
  if (hiddenPropOnly && !state.f.propOnly) msg += ` · ${hiddenPropOnly.toLocaleString()} property-only records hidden`;
  if (hiddenOld) msg += ` · ${hiddenOld.toLocaleString()} old rent-file-only contracts hidden${hiddenOldProps ? ` (${hiddenOldProps.toLocaleString()} properties have only old contracts)` : ''}`;
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
    p.qct != null && ['2027 QCT / DDA', esc(zoneText(p))],
    ['HUD servicing office', esc(p.office || '')],
    p.fha && ['FHA programs', esc(p.fha)],
  ]);
  h += ownerHtml(p) + financingHtml(p) + lihtcHtml(p);
  h += `<h3>Contracts (${p.cons.length})${matched.size < p.cons.length ? ` <span class="cnt">· ${matched.size} match current filters</span>` : ''}</h3>`;
  if (!p.cons.length) h += '<p class="note">No assistance contract in the HUD source files for this property ID. That does not prove the property has no assistance.</p>';
  for (const c of p.cons) h += contractCard(c, matched.has(c));
  h += `<p class="note">Rents are monthly per unit. Reported amounts come from HUD's contract rent / utility allowance file${H.meta.rent_file ? ` (as of ${esc(H.meta.rent_file.asof)})` : ''}. A bedroom size can have several rent rows (rent tiers); each is shown with its own unit count. Estimates = assistance-file bedroom FMR × HUD contract gross-rent/FMR %, the same % for every bedroom size, so they are gross rents only. Contract rent is not estimated when the utility allowance is unknown. The HUD files do not publish a last-approved RCS date or market-reset date.</p>`;
  $('#detailBody').innerHTML = h;
  $('#detail').hidden = false;
  $('.detail-scroll').scrollTop = 0;
}
function contactHtml(r) {
  if (!r) return '';
  const a = [r.addr, r.city, [r.st, r.zip].filter(Boolean).join(' ')].filter(Boolean).join(', ');
  return [a && esc(a), r.phone && `<a href="tel:${esc(r.phone.replace(/[^0-9+]/g, ''))}">${esc(r.phone)}</a>`,
    r.email && `<a href="mailto:${esc(r.email)}">${esc(r.email)}</a>`].filter(Boolean).join('<br>');
}
function ownerHtml(p) {
  const o = p.ow, g = p.spon, a = p.ag;
  const name = o?.name || p.owner, q = encodeURIComponent(name || '');
  const look = [];
  if (name) look.push(`<a href="https://opencorporates.com/companies?q=${q}" target="_blank" rel="noopener">OpenCorporates (all states)</a>`);
  if (p.st === 'AZ' || o?.st === 'AZ') look.push('<a href="https://ecorp.azcc.gov/EntitySearch/Index" target="_blank" rel="noopener">Arizona Corporation Commission eCorp</a> (search the owner name; shows members, managers and statutory agent)');
  if (p.st === 'AZ' && /maricopa/i.test(p.county || '') && p.addr) look.push(`<a href="https://mcassessor.maricopa.gov/mcs/?q=${encodeURIComponent(p.addr + ' ' + (p.city || ''))}" target="_blank" rel="noopener">Maricopa County Assessor</a> (owner of record, tax mailing address)`);
  let h = '<h3>Owner &amp; management</h3>' + kv([
    ['Owner entity', name ? esc(name) + (o?.type ? ` <span class="muted">· ${esc(o.type)}</span>` : '') : ''],
    o?.pid && ['HUD owner participant ID', esc(o.pid)],
    ['Owner contact (HUD)', o ? contactHtml(o) : ''],
    ['Ownership effective date', esc(p.ownSince || '')],
    ['Owner group (likely sponsor)', g >= 0 ? `<b>${esc(sponLabel(g))}</b> · ${(SP_N.get(g) || 0).toLocaleString()} properties, ${SP[g][2].toLocaleString()} owner entities
      <br><button class="link" data-show-spon="${g}">Show this group's whole portfolio</button>` : (o ? '<span class="muted">No other HUD property shares this owner\'s email domain or mailing address</span>' : '')],
    ['Management agent', a?.name || p.mgmt ? esc(a?.name || p.mgmt) + (a?.type ? ` <span class="muted">· ${esc(a.type)}</span>` : '') : ''],
    a && ['Management contact (HUD)', contactHtml(a)],
    look.length && ['Look up the owner entity', look.join('<br>')],
  ]);
  return h + `<p class="note">From HUD's MF Assistance &amp; Section 8 property file. The owner entity is usually a single-asset LLC or LP. "Owner group" puts together owner entities that share an organization's email domain (or, without one, a mailing address). It points to the sponsor but isn't proof: the contact can be a sponsor, an accountant or a management company. Confirm with state entity records (members/managers) and the recorded deed or deed of trust signature block.</p>`;
}
function financingHtml(p) {
  if (!p.loans.length) return '<h3>FHA financing</h3><p class="note">No FHA-insured or HUD-held loan for this property ID in HUD\'s portfolio file.</p>';
  let t = `<h3>FHA financing (${p.loans.length})</h3><div class="scrollx"><table><thead><tr><th>FHA #</th><th>Loan type</th><th>Final endorsement</th><th>Maturity</th><th class="num">Rate</th><th class="num">Original</th><th class="num">Balance</th><th>Flags</th><th>Servicer</th></tr></thead><tbody>`;
  for (const l of p.loans) t += `<tr><td>${esc(l.fha)}${l.primary ? '' : ' <span class="muted">(secondary)</span>'}</td><td>${esc(l.soa >= 0 ? D.soa[l.soa] : l.soaCode || '')}</td>
    <td>${esc(l.finalEnd || l.initEnd || '')}</td><td>${esc(l.maturity || '')}</td><td class="num">${l.rate != null ? l.rate.toFixed(2) + '%' : ''}</td>
    <td class="num">${money(l.amt)}</td><td class="num">${money(l.upb)}</td><td>${esc([l.tc && 'LIHTC (TC)', l.te && 'Tax-exempt bonds (TE)', !l.insured && 'Not insured'].filter(Boolean).join(', '))}</td><td>${esc(l.servicer || '')}</td></tr>`;
  return t + `</tbody></table></div><p class="note">HUD active MF insured mortgages (as of ${esc(H.meta.fha.loans_asof)}), linked by HUD's active-portfolio FHA list. A loan with no active-mortgage record shows its type only.</p>`;
}
function lihtcHtml(p) {
  const L = p.lih, TL = ['High', 'Medium', 'Possible'];
  if (!L) return '<h3>LIHTC</h3><p class="note">No LIHTC record matched by address, location or name. That does not prove the property has no tax credits.</p>';
  let h = `<h3>LIHTC (${L.links.length} record${L.links.length > 1 ? 's' : ''})</h3>`;
  if (L.best < 2) h += kv([
    ['Latest allocation year', esc(L.lastAlloc ?? '')],
    ['Latest placed-in-service year', esc(L.lastPis ?? '')],
    ['Year 15 (compliance period ends)', L.y15 ? `${L.y15}${L.y15est ? ' <span class="est">est.</span> <span class="muted">(allocation + 16; PIS not published yet)</span>' : ''}` : ''],
    ['Extended use (~30 yrs) ends', L.y15 ? `≈ ${L.y15 + 15} <span class="muted">(depends on the state agreement)</span>` : ''],
    ['Resyndication', L.resynd ? `New allocation in ${L.resynd}` : '<span class="muted">None found</span>'],
  ]);
  h += '<div class="scrollx"><table><thead><tr><th>Match</th><th>Source record</th><th class="num">Alloc.</th><th class="num">PIS</th><th>Credit</th><th>Type</th><th class="num">Units</th><th>Source</th></tr></thead><tbody>';
  for (const { rec: r, tier, why } of L.links) h += `<tr style="${tier === 2 ? 'opacity:.6' : ''}"><td><span class="b ${tier === 0 ? 'V' : tier === 1 ? 'R' : 'U'}">${TL[tier]}</span></td>
    <td>${esc(r.project)}<div class="muted">${esc([r.addr, r.city, r.zip].filter(Boolean).join(', '))}${r.id ? ` · ID ${esc(r.id)}` : ''}</div><div class="muted">${esc(why)}</div></td>
    <td class="num">${r.alloc ?? '–'}</td><td class="num">${r.pis ?? '–'}</td><td>${esc(r.credit || '')}${r.bond ? ' · bonds' : ''}</td><td>${esc(r.type || '')}</td>
    <td class="num">${num(r.units)}</td><td class="srccell"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.src)}</a></td></tr>`;
  return h + '</tbody></table></div><p class="note">LIHTC records carry no HUD property ID, so they are matched by address, location and name. "Possible" matches are left out of the summary and filters unless you tick "Count possible matches". Year 15 = latest PIS + 14.</p>';
}
function contractCard(c, isMatch) {
  const head = `<div class="contract-head"><b>${esc(c.no)}</b><span class="b out">${esc(doc(c))}</span>
    <span>${esc(dict('program', c.program) || 'Program unknown')}${c.group >= 0 ? ` · ${esc(D.group[c.group])}` : ''}${c.pcat >= 0 ? ` · ${esc(D.pcat[c.pcat])}` : ''}</span>
    <span class="${c.old || (c.status >= 0 && D.status[c.status] !== 'Active') ? 'flag' : ''}">${esc(c.old ? OLD_STATUS : dict('status', c.status) || 'Status unknown')}</span></div>`
    + (c.old ? `<p class="note flag">Old contract: this number is in HUD's rent/UA file but not in HUD's active Section 8 contract list, so it has no type, program, status or dates. It is most likely a predecessor contract that a renewal or combined contract replaced${props[c.p].cons.some(x => !x.old && x.status >= 0 && D.status[x.status] === 'Active') ? ' (this property has an active contract, listed separately)' : ''}. Its rents may be years old; don't use them as current rents.</p>` : '');
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
        const src = l.bedSrc === 'A' ? 'assistance file' : l.bedSrc === 'R' ? 'largest single-tab cohort total' : l.bedSrc === 'V' ? 'verified document' : l.bedSrc === 'F' ? 'HUD rent/UA file total' : '';
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
  checkList($('#f-st'), [...STATE_N].sort((a, b) => (a[0] === '') - (b[0] === '') || stName(a[0]).localeCompare(stName(b[0])))
    .map(([v, n]) => ({ v, label: stName(v), n })), f.st, refresh);
  $('#f-city').innerHTML = [...f.city].map(k => `<span class="chip">${esc(cityLabel(k))} <span class="n">${(CITY_N.get(k) || 0).toLocaleString()}</span><button class="link" data-k="${esc(k)}" title="Remove">×</button></span>`).join('')
    + (f.city.size ? ' <button class="link" id="cityClear">Clear cities</button>' : '');
  $('#f-spon').innerHTML = [...f.spon].map(i => `<span class="chip">${esc(sponLabel(i))} <span class="n">${(SP_N.get(i) || 0).toLocaleString()}</span><button class="link" data-sp="${i}" title="Remove">×</button></span>`).join('')
    || '<span class="muted">All owners</span>';
  $('#unitsMin').value = f.unitsMin ?? ''; $('#unitsMax').value = f.unitsMax ?? '';
  const soaItems = [...SOA_N].sort((a, b) => b[1] - a[1]).map(([v, n]) => ({ v, label: v < 0 ? 'No FHA loan in HUD files' : D.soa[v], n }));
  checkList($('#f-soa'), soaItems, f.soa, refresh, { numeric: true });
  $('#tcOnly').checked = f.tcOnly; $('#lih').value = f.lih; $('#lihPossible').checked = f.lihPossible; $('#zone').value = f.zone;
  for (const k of ['y15Min', 'y15Max', 'allocBefore']) $('#' + k).value = f[k] ?? '';
  $('#yearMin').value = f.yearMin ?? ''; $('#yearMax').value = f.yearMax ?? ''; $('#yearUnknown').checked = f.yearUnknown;
  $('#ovMin').value = f.ovMin ?? ''; $('#ovMax').value = f.ovMax ?? ''; $('#ovUnknown').checked = f.ovUnknown;
  $('#ownMin').value = f.ownMin ?? ''; $('#ownMax').value = f.ownMax ?? '';
  $('#minTerm').value = String(f.minTerm);
  $('#propOnly').checked = f.propOnly;
  $('#oldCons').checked = f.oldCons;
}
function updateFilterCounts() {
  const f = state.f;
  for (const k of ['doc', 'program', 'status', 'ropt']) {
    const total = COUNTS[k].size;
    $(`#f-${k}-n`).textContent = f[k].size === total ? '(all)' : `(${f[k].size} of ${total})`;
  }
  const y = f.yearMin == null && f.yearMax == null ? 'any start' : `start ${f.yearMin ?? '…'}–${f.yearMax ?? '…'}`;
  const len = { 13: ', > 1 yr', 60: ', 5+ yrs', 240: ', 20+ yrs' }[f.minTerm] || '';
  const ov = f.ovMin == null && f.ovMax == null ? '' : `, overall exp. ${f.ovMin ?? '…'}–${f.ovMax ?? '…'}${f.ovUnknown ? ' + unknown' : ''}`;
  $('#f-year-n').textContent = `(${y}${len}${f.yearUnknown && !f.minTerm ? ', incl. unknown' : ', known only'}${ov})`;
  const fin = [f.soa.size !== SOA_N.size && `${f.soa.size} loan type${f.soa.size === 1 ? '' : 's'}`, f.tcOnly && 'TC loans',
    f.lih !== 'any' && (f.lih === 'yes' ? 'LIHTC' : 'no LIHTC'), (f.y15Min != null || f.y15Max != null) && `Y15 ${f.y15Min ?? '…'}–${f.y15Max ?? '…'}`,
    f.allocBefore != null && `no alloc. since ${f.allocBefore}`, f.zone !== 'any' && { qct: 'QCT', dda: 'DDA', either: 'QCT/DDA' }[f.zone]].filter(Boolean);
  const stTxt = f.st.size === STATE_N.size ? 'all states' : f.st.size <= 3 ? [...f.st].map(c => c || '?').join(', ') : `${f.st.size} states`;
  const szTxt = f.unitsMin == null && f.unitsMax == null ? '' : `, ${f.unitsMin ?? 0}–${f.unitsMax ?? '∞'} units`;
  const ctTxt = f.city.size ? `, ${f.city.size === 1 ? cityLabel([...f.city][0]) : f.city.size + ' cities'}` : '';
  const spTxt = f.spon.size ? `, owner group ${[...f.spon].map(sponLabel).join('; ')}` : '';
  const ownTxt = f.ownMin == null && f.ownMax == null ? '' : `, owned since ${f.ownMin ?? '…'}–${f.ownMax ?? '…'}`;
  $('#f-st-n').textContent = `(${stTxt}${ctTxt}${spTxt}${szTxt}${ownTxt})`;
  $('#f-fin-n').textContent = fin.length ? `(${fin.join(', ')})` : '(any)';
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
  const stItems = stateMatches(q).map(([c, n]) => ({
    html: `Show all of ${esc(n)} (${c})<small>State filter · ${STATE_N.get(c).toLocaleString()} property IDs; clears the search center</small>`,
    go: () => filterToState(c),
  }));
  const ctItems = cityMatches(q).map(([k, n]) => ({
    html: `Show all of ${esc(cityLabel(k))}<small>City filter · ${n.toLocaleString()} property ID${n === 1 ? '' : 's'}; clears the search center</small>`,
    go: () => filterToCity(k),
  }));
  const items = localMatches(q).map(p => ({
    html: `${esc(pname(p))}<small>${esc([p.addr, p.city, p.st].filter(Boolean).join(', '))} · ${esc(p.id)}${p.lc === 'N' ? ' · no map location' : ''}</small>`,
    go: () => pickProperty(p),
  }));
  const ll = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (ll) items.unshift({ html: `Use coordinates ${esc(q)}`, go: () => setCenter({ lat: +ll[1], lon: +ll[2], label: `Coordinates ${q}` }) });
  else items.push({ html: `Find address on map: “${esc(q)}”<small>Esri World Geocoder (sends this text to geocode.arcgis.com)</small>`, go: () => geocode(q) });
  const spItems = sponMatches(q).map(i => ({
    html: `Owner group ${esc(sponLabel(i))}<small>${(SP_N.get(i) || 0).toLocaleString()} properties, ${SP[i][2].toLocaleString()} owner entities; shows the whole portfolio and clears the search center</small>`,
    go: () => filterToSponsor(i),
  }));
  showSugg([...stItems, ...ctItems, ...spItems, ...items]);
}
function stateMatches(q) {
  const t = q.trim().toLowerCase().replace(/\.$/, '');
  if (t.length < 2) return [];
  return Object.entries(STATE_NAMES).filter(([c, n]) => STATE_N.has(c) &&
    (c.toLowerCase() === t || (t.length >= 3 && n.toLowerCase().startsWith(t)))).slice(0, 3);
}
function cityMatches(q) {
  let t = q.trim().toUpperCase().replace(/[.,]+/g, ' ').replace(/\s+/g, ' ');
  let st = null;
  const m = t.match(/^(.*\S)\s+([A-Z]{2})$/);
  if (m && STATE_NAMES[m[2]]) { t = m[1]; st = m[2]; }
  if (t.length < 3) return [];
  const res = [];
  for (const [k, n] of CITY_N) {
    const [c, s2] = k.split('|');
    if ((st && s2 !== st) || !c.startsWith(t)) continue;
    res.push([k, n, c === t ? 0 : 1]);
  }
  return res.sort((a, b) => a[2] - b[2] || b[1] - a[1]).slice(0, 4);
}
function fitTo(pred) {
  const pts = props.filter(p => pred(p) && p.lat != null && p.lc !== 'C').map(p => [p.lat, p.lon]);
  if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [20, 20], maxZoom: 12 });
}
function sponMatches(q) {
  const t = q.trim().toLowerCase().replace(/^@/, '');
  if (t.length < 3) return [];
  const res = [];
  for (const [i, txt] of SP_TEXT) {
    const at = txt.indexOf(t);
    if (at >= 0) res.push([i, at < SP[i][0].length ? 0 : 1]);
  }
  return res.sort((a, b) => a[1] - b[1] || (SP_N.get(b[0]) || 0) - (SP_N.get(a[0]) || 0)).slice(0, 3).map(r => r[0]);
}
function filterToSponsor(i) {
  $('#sugg').hidden = true; $('#q').value = '';
  state.f.spon = new Set([i]); state.f.city = new Set(); state.f.st = allOf('st');
  setCenter(null);
  fitTo(p => p.spon === i);
  $('#detail').hidden = true;
  buildFilters(); refresh();
}
function filterToCity(k, add = false) {
  $('#sugg').hidden = true; $('#q').value = '';
  if (!add) state.f.city = new Set();
  state.f.city.add(k);
  const st = k.split('|')[1];
  if (st && state.f.st.size !== STATE_N.size && !state.f.st.has(st)) state.f.st.add(st);
  setCenter(null);
  fitTo(p => state.f.city.has(p.ck));
  buildFilters(); refresh();
}
function filterToState(code) {
  $('#sugg').hidden = true; $('#q').value = '';
  state.f.st = new Set([code]); state.f.city = new Set();
  setCenter(null);
  const pts = props.filter(p => p.st === code && p.lat != null && p.lc !== 'C').map(p => [p.lat, p.lon]);
  if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [20, 20], maxZoom: 9 });
  buildFilters(); refresh();
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
const FIN_HEAD = ['FHA loan types', 'FHA numbers', 'Primary loan final endorsement', 'Primary loan maturity', 'Primary loan rate', 'Primary loan balance',
  'Loan includes LIHTC (TC)', 'Loan tax-exempt bonds (TE)', 'Ownership effective date', 'LIHTC match confidence', 'LIHTC latest allocation year',
  'LIHTC latest PIS year', 'LIHTC Year 15', 'Year 15 estimated', 'LIHTC resyndication year', 'LIHTC records', 'LIHTC sources', '2027 QCT', '2027 DDA'];
const OWN_HEAD = ['Owner HUD participant ID', 'Owner company type', 'Owner mailing address', 'Owner city', 'Owner state', 'Owner ZIP', 'Owner phone',
  'Owner email', 'Owner group (likely sponsor)', 'Owner group properties', 'Management agent', 'Management phone', 'Management email'];
function ownCsv(p) {
  const o = p.ow || {}, a = p.ag || {};
  return [o.pid, o.type, o.addr, o.city, o.st, o.zip, o.phone, o.email, sponLabel(p.spon), p.spon >= 0 ? SP_N.get(p.spon) : '', a.name || p.mgmt, a.phone, a.email];
}
function finCsv(p) {
  const pl = p.loans[0], L = p.lih, ok = hasLih(p), yn = (b, any) => any ? (b ? 'Y' : 'N') : '';
  return [loanText(p), p.loans.map(l => l.fha).join('; '), pl?.finalEnd, pl?.maturity, pl?.rate, pl?.upb, yn(p.loans.some(l => l.tc), p.loans.length),
    yn(p.loans.some(l => l.te), p.loans.length), p.ownSince, L ? ['High', 'Medium', 'Possible'][L.best] : 'None', ok ? L.lastAlloc : '', ok ? L.lastPis : '',
    ok ? L.y15 : '', ok && L.y15est ? 'Y' : '', ok ? L.resynd : '',
    L ? L.links.map(x => `${x.rec.project} [${x.rec.id || 'no ID'}; alloc ${x.rec.alloc ?? '?'}; PIS ${x.rec.pis ?? '?'}; ${['high', 'medium', 'possible'][x.tier]}]`).join(' | ') : '',
    L ? uniq(L.links.map(x => x.rec.src)).join(' | ') : '', yn(p.qct, p.qct != null), yn(p.dda, p.qct != null)];
}
function linesTable() {
  const head = ['Distance (mi)', 'HUD property ID', 'Property', 'Address', 'City', 'State', 'ZIP', 'Location precision', 'Contract number', 'Contract type',
    'Assistance program', 'Program group', 'Contract status', 'Bedrooms', 'Units in line', 'Contract bedroom units', 'Contract rent', 'Utility allowance',
    'Gross rent', 'Rent basis', 'Rent source', 'Assistance-file FMR', 'Rent-file FMR', 'Gross rent / rent-file FMR', 'HUD contract rent/FMR %',
    'Contract-term effective date', 'Current term expiration', 'Overall expiration', 'Contract term (months)', 'Renewal option', 'Renewal status', 'Renewal type',
    'Renewal owner-signature date', 'Owner-signature date in source (if invalid)', 'Review notes', 'Verified document', 'Verified effective date', 'Owner', ...FIN_HEAD, ...OWN_HEAD];
  const rows = sortRows(rowsFor('lines', state.result.out), LINE_COLS).map(({ p, c, l }) => [
    p.dist != null && state.center ? p.dist.toFixed(2) : '', p.id, p.name, p.addr, p.city, p.st, p.zip, LOC_CLASS[p.lc], c.no, doc(c),
    programOf(c), c.old ? '' : dict('group', c.group) || UNK, statusOf(c), l?.bed, l?.units, l?.bedUnits,
    l?.rent, l?.ua, l?.gross, l ? BASIS_LABEL[l.basis] : 'No bedroom data', l?.source, l?.fmrAssist, l?.fmrRent, l?.q, c.pct,
    c.eff, c.curExp, c.ovExp, c.term, dict('ropt', c.ropt), dict('rstat', c.rstat), dict('rtype', c.rtype),
    c.signed || UNK, c.signedBad, [l?.flag, l?.vd?.[3]].filter(Boolean).join('; '), l?.vd?.[0], l?.vd?.[1], p.ow?.name || p.owner, ...finCsv(p), ...ownCsv(p)]);
  return [head, ...rows];
}
const exportLines = () => download(exportName('rents-by-bedroom'), linesTable());
function propsTable() {
  const head = ['Distance (mi)', 'HUD property ID', 'Property', 'Address', 'City', 'State', 'ZIP', 'County', 'Location precision', 'Total units',
    'Assisted units (property)', 'Matching contracts', 'All contracts', 'Contract numbers', 'Contract types', 'Programs', 'Statuses',
    'Bedroom mix (contract units)', 'Best rent basis', 'Next current expiration', 'Next overall expiration', 'Latest renewal owner-signature date', 'Owner', 'Management', ...FIN_HEAD, ...OWN_HEAD];
  const rows = sortRows(state.result.out, PROP_COLS).map(r => [
    r.p.dist != null && state.center ? r.p.dist.toFixed(2) : '', r.p.id, r.p.name, r.p.addr, r.p.city, r.p.st, r.p.zip, r.p.county, LOC_CLASS[r.p.lc],
    r.p.total, r.p.assisted, r.mc.length, r.p.cons.length, r.mc.map(m => m.c.no).join('; '), uniq(r.mc.map(m => doc(m.c))).join('; '),
    uniq(r.mc.map(m => programOf(m.c))).join('; '), uniq(r.mc.map(m => statusOf(m.c))).join('; '),
    bedMix(r.mc), BASIS_SHORT[r.best], minOf(r.mc.map(m => m.c.curExp)), minOf(r.mc.map(m => m.c.ovExp)), maxOf(r.mc.map(m => m.c.signed)) || UNK, r.p.ow?.name || r.p.owner, r.p.ag?.name || r.p.mgmt, ...finCsv(r.p), ...ownCsv(r.p)]);
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
  $('#asof').textContent = `HUD files published ${m.hud_published} (downloaded ${m.downloaded})${m.rent_file ? ` · rents & UAs as of ${m.rent_file.asof}` : ''} · ${m.properties.toLocaleString()} property IDs · ${m.contracts.toLocaleString()} contracts`;
  $('#aboutBody').innerHTML = `<h2 style="margin-top:0">About the data</h2>
  <p>Source: <b>${esc(m.workbook)}</b> (tab <i>HUD National Rents</i>, ${m.source_rows.toLocaleString()} rows; formula values read from the saved workbook and re-checked against the reconciliation formulas). Built ${esc(m.built)}.</p>${m.rent_file ? `<p>Rents and utility allowances: HUD <a href="${esc(m.rent_file.page)}" target="_blank" rel="noopener"><i>${esc(m.rent_file.name)}</i></a> (as of ${esc(m.rent_file.asof)}, downloaded ${esc(m.rent_file.downloaded)}, ${m.rent_file.rows.toLocaleString()} rows covering ${m.rent_file.contracts.toLocaleString()} contracts). For every contract in that file, its rows replace the earlier reported and estimated rents; ${m.rent_file.contracts_added.toLocaleString()} contracts that were only in that file were added (${m.rent_file.properties_added.toLocaleString()} of them have no property/address match, so they are searchable but not mapped).</p>` : ''}
  <h3>Rents</h3><ul>
  <li><b>Reported</b>: contract rent and utility allowance by bedroom size from HUD's contract rent/UA file. Gross = rent + UA. A $0 UA is as reported by HUD (typically owner-paid utilities). Reported $0 rents are kept and flagged. When HUD lists several rent rows for one bedroom size (rent tiers within a contract), each row is shown with its own unit count; rows showing 0 units are flagged for review.</li>
  <li><b>Estimated gross</b>: ROUND(assistance-file bedroom FMR × HUD contract gross-rent/FMR % ÷ 100). The single contract % is applied to every bedroom size, so mixed-bedroom results are estimates. Contract rent is <i>not</i> estimated because the UA is unknown. Missing UAs are never treated as $0.</li>
  <li><b>Verified document</b>: rents from a separately reviewed document (e.g., a signed HUD-92458 rent schedule). Shown alongside, never merged into, HUD amounts.</li>
  <li>Estimates now remain only for contracts missing from HUD's latest rent/UA file.</li></ul>
  ${m.fha ? `<h3>Financing</h3><ul>
  <li><b>FHA loans</b>: HUD <a href="${esc(m.fha.loan_page)}" target="_blank" rel="noopener">active MF insured mortgages</a> (as of ${esc(m.fha.loans_asof)}), linked to HUD property IDs by the "All active Properties with FHA" tab of HUD's <a href="${esc(m.fha.portfolio_page)}" target="_blank" rel="noopener">Active Multifamily Portfolio</a> file. Loan type = HUD Section of the Act (e.g. 223(f), 221(d)(4), 223(a)(7)). TC / TE = HUD's codes for loans that include LIHTC / tax-exempt bonds.</li>
  <li><b>Ownership effective date</b>: HUD's MF Assistance &amp; Section 8 property file. A recent date often marks a sale or resyndication.</li></ul>` : ''}
  ${m.lihtc ? `<h3>LIHTC</h3><ul>
  <li>Sources: ${D.lsrc.map((t, i) => `<a href="${esc(D.lsrcUrl[i])}" target="_blank" rel="noopener">${esc(t)}</a>`).join('; ')}. Each record in a property's panel names its source.</li>
  <li>HUD's LIHTC data covers projects placed in service through about 2020-2022 and has no HUD property ID. State award lists (so far Arizona, 1987 to present) add recent allocations but no PIS dates.</li>
  <li>Matching: <b>High</b> = same address, or within 100 m with a similar name. <b>Medium</b> = same address under another name, similar name within 250 m, or same name in the same ZIP. <b>Possible</b> = a neighbor on the same street; not used unless you tick "Count possible matches". ${m.lihtc.properties.toLocaleString()} properties have at least one match.</li>
  <li><b>Year 15</b> = latest PIS + 14. If the latest allocation is newer than the latest PIS, allocation + 16 (marked est.). <b>Resyndication</b> = a later allocation at least 5 years after the earlier allocation/PIS years (HUD and state lists often record the same deal a year apart).</li></ul>` : ''}
  ${H.meta.owners ? `<h3>Owners</h3><ul>
  <li>Owner entity, management agent and their contacts come from HUD's <a href="${esc(H.meta.owners.source)}" target="_blank" rel="noopener">MF Assistance &amp; Section 8 property file</a> (${H.meta.owners.properties.toLocaleString()} properties).</li>
  <li><b>Owner group (likely sponsor)</b>: owner entities that share an organization's email domain (free and ISP mail such as gmail.com is ignored), or, without one, the same mailing address. ${H.meta.owners.sponsor_groups.toLocaleString()} groups cover ${H.meta.owners.properties_in_groups.toLocaleString()} properties. It's a lead, not proof of control: confirm with state entity filings and recorded deeds. Search a sponsor name or email domain (e.g. "mercyhousing") to see its portfolio.</li></ul>` : ''}
  ${H.meta.zones ? `<h3>2027 QCT / DDA</h3><ul><li>${esc(H.meta.zones.note)}</li></ul>` : ''}
  <h3>Old contracts</h3><ul>
  <li>${cons.filter(c => c.old).length.toLocaleString()} contract numbers appear only in HUD's rent/UA file, not in HUD's active Section 8 contract list, so they have no type, program, status or dates. Most are predecessor contracts replaced by a renewal or a combined contract (e.g., an original "L" LMSA contract renewed under an "M" number). They're hidden by default; tick "Include old rent-file-only contracts" under Contract type to show them, labeled "${OLD_STATUS}". Their rents may be years old.</li></ul>
  <h3>Dates</h3><ul>
  <li><b>Contract-term effective year</b> (filter) = HUD <code>tracs_effective_date</code>, the start of the current contract (start + term months = overall expiration for 92% of contracts). 12-month contracts restart every year, so pair it with a minimum contract length to find newly started long-term contracts.</li>
  <li><b>Renewal owner-signed</b> (shown, not filtered) = HUD <code>owner_submitted_date</code>, the owner's signature on HUD's latest renewal action. For a new renewal contract it usually precedes the start date; for an "Amend Rents" action it is the latest rent change on an older contract. It is not the HAP execution date or when the quoted rent took effect. ${s.signed_valid.toLocaleString()} contracts have a usable date. ${s.signed_invalid} contracts show placeholder or future dates (e.g., 1900-01-02 or 2099) and are treated as unknown.</li>
  <li><b>Overall contract expiration</b> (filter, and "Next overall exp." on the Properties tab = the earliest overall expiration among a property's matching contracts) = HUD <code>tracs_overall_expiration_date</code>, the end of the whole contract including its remaining option terms; "Next current exp." is only the end of the current term, so look at the overall date for when the contract actually runs out. ${cons.filter(c => c.ovExp).length.toLocaleString()} contracts have one; while an expiration range is set, contracts without a date are left out unless you tick "Include unknown".</li>
  <li><b>Owned since</b> (Properties tab, filter under Location, size &amp; owner) = HUD <code>ownership_effective_date</code> from the MF Assistance &amp; Section 8 property file: when the current owner entity took over, as HUD records it. ${props.filter(p => p.ownSince).length.toLocaleString()} properties have one; a long-held property (e.g. since the 1980s) is often an untouched original owner, a recent date often a sale or resyndication. Properties without a date are left out while a range is set.</li>
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
for (const k of ['ovMin', 'ovMax', 'ownMin', 'ownMax']) $('#' + k).onchange = e => { state.f[k] = e.target.value === '' ? null : +e.target.value; refresh(); };
$('#ovUnknown').onchange = e => { state.f.ovUnknown = e.target.checked; refresh(); };
$('#ovPreset').onchange = e => {  // "expires within N years": overall expiration up to and including that year (already-expired contracts stay in)
  const v = e.target.value; state.f.ovMin = null; state.f.ovMax = v === '' ? null : v === '-' ? null : new Date().getFullYear() + +v;
  e.target.value = ''; buildFilters(); refresh();
};
$('#ownPreset').onchange = e => {
  const [a, b] = e.target.value.split('-'); state.f.ownMin = a ? +a : null; state.f.ownMax = b ? +b : null;
  e.target.value = ''; buildFilters(); refresh();
};
$('#cityIn').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  const m = cityMatches(e.target.value);
  if (!m.length) { $('#cityMsg').textContent = `No city matching "${e.target.value}".`; return; }
  $('#cityMsg').textContent = ''; e.target.value = '';
  filterToCity(m[0][0], true);
});
$('#cityIn').addEventListener('input', e => {
  const m = cityMatches(e.target.value);
  $('#cityMsg').textContent = m.length ? 'Enter adds: ' + m.map(([k, n]) => `${cityLabel(k)} (${n})`).join(' · ') : '';
});
$('#f-spon').onclick = e => {
  if (e.target.dataset.sp == null) return;
  state.f.spon.delete(+e.target.dataset.sp);
  buildFilters(); refresh();
};
$('#detailBody').addEventListener('click', e => {
  const b = e.target.closest('[data-show-spon]');
  if (b) filterToSponsor(+b.dataset.showSpon);
});
$('#f-city').onclick = e => {
  if (e.target.id === 'cityClear') state.f.city = new Set();
  else if (e.target.dataset.k) state.f.city.delete(e.target.dataset.k);
  else return;
  buildFilters(); refresh();
};
for (const k of ['unitsMin', 'unitsMax']) $('#' + k).onchange = e => { state.f[k] = e.target.value === '' ? null : +e.target.value; refresh(); };
$('#sizePreset').onchange = e => {
  const [a, b] = e.target.value.split('-'); state.f.unitsMin = a ? +a : null; state.f.unitsMax = b ? +b : null;
  e.target.value = ''; buildFilters(); refresh();
};
$('#tcOnly').onchange = e => { state.f.tcOnly = e.target.checked; refresh(); };
$('#lih').onchange = e => { state.f.lih = e.target.value; refresh(); };
$('#lihPossible').onchange = e => { state.f.lihPossible = e.target.checked; refresh(); };
for (const k of ['y15Min', 'y15Max', 'allocBefore']) $('#' + k).onchange = e => { state.f[k] = e.target.value === '' ? null : +e.target.value; refresh(); };
$('#zone').onchange = e => { state.f.zone = e.target.value; refresh(); };
$('#targetBtn').onclick = () => {
  const f = state.f = defaults();
  f.soa = new Set([...SOA_N.keys()].filter(k => k >= 0 && /223\(f\)/.test(D.soa[k])));
  f.status = new Set([...COUNTS.status.keys()].filter(k => D.status[k] === 'Active'));
  f.doc = new Set([...COUNTS.doc.keys()].filter(k => D.doc[k] === 'HAP'));
  f.lih = 'yes'; f.y15Max = new Date().getFullYear() + 1;
  state.view = 'props'; document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === 'props'));
  buildFilters(); refresh();
};
$('#propOnly').onchange = e => { state.f.propOnly = e.target.checked; refresh(); };
$('#oldCons').onchange = e => { state.f.oldCons = e.target.checked; refresh(); };
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

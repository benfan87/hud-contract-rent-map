/* HUD + LIHTC map: every located HUD multifamily property and every LIHTC project on one map, with the same layers,
   search, area radius and detail panel as the rent screener (../screener/), minus the rent studies, estimates and
   password. Data: ../screener/hud_all.js, ../screener/lihtc.js, ../screener/zones.js (public HUD data, not encrypted). */
(function () {
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const ok = v => v != null && v !== '' && isFinite(v);
const int = v => !ok(v) ? '–' : Math.round(v).toLocaleString('en-US');
const mi = v => !ok(v) ? '–' : v < 10 ? v.toFixed(1) : Math.round(v).toString();
const titleCase = s => s && s === s.toUpperCase() ? s.toLowerCase().replace(/(^|[\s-])\w/g, c => c.toUpperCase()) : s;
const plural = (n, one, many = one + 's') => `${n.toLocaleString()} ${n === 1 ? one : many}`;
const stName = Object.fromEntries(window.RS_STATES || []);
const today = new Date().toISOString().slice(0, 10);
const addYears = n => { const d = new Date(); d.setFullYear(d.getFullYear() + n); return d.toISOString().slice(0, 10); };

/* ---------- 2027 QCT / DDA membership (zones.js): 1 = QCT, 2 = DDA ---------- */
const ZN = window.RS_ZONES || null, ZQ = new Set(ZN ? ZN.qct : []), ZD = new Set(ZN ? ZN.dda : []);
const zoneOf = id => (ZQ.has(id) ? 1 : 0) | (ZD.has(id) ? 2 : 0);
const zoneTxt = z => [z & 1 ? 'QCT' : '', z & 2 ? 'DDA' : ''].filter(Boolean).join(', ');
const ZONEF = { qct: z => z & 1, dda: z => z & 2, either: z => z > 0, both: z => z === 3, neither: z => !z };

/* ---------- data ---------- */
const loadJs = (src, key) => new Promise((res, rej) => {
  if (window[key]) return res(window[key]);
  const el = document.createElement('script'); el.src = src;
  el.onload = () => (window[key] ? res(window[key]) : rej(new Error('empty'))); el.onerror = rej; document.head.appendChild(el);
});
Promise.all([loadJs('../screener/hud_all.js?v=1', 'RS_HUD'), loadJs('../screener/lihtc.js?v=1', 'RS_LIHTC')])
  .then(([h, l]) => { start(h, l); $('#loading').remove(); })
  .catch(() => { $('#loading div').innerHTML = 'The HUD and LIHTC files did not load.<small>Check the connection and reload the page.</small>'; });

function start(HUD, LIH) {
  // One entry per place, keyed by HUD property id (LIHTC-only projects: "L:" + LIHTC id). A LIHTC project matched to a
  // HUD property is the same entry as that property.
  const ENT = new Map();
  for (const h of HUD.P) ENT.set(h[0], { key: h[0], id: h[0], hud: true, lih: null, h, name: titleCase(h[3]) || `HUD ${h[0]}`, addr: h[4], city: titleCase(h[5]), st: h[6], zip: h[7],
    county: titleCase(h[8]), lat: h[1], lon: h[2], units: h[9] ?? h[10], owner: h[11], mgmt: h[12], zone: h[19], approx: h[13], spon: h[20] ?? -1 });
  for (const q of LIH.P) {
    let e = q[9] && ENT.get(q[9]);
    if (!e) { e = { key: q[9] || 'L:' + (q[14] || `${q[0]},${q[1]}`), id: q[9] || null, hud: !!q[9], lih: null, h: null, name: titleCase(q[2]) || 'LIHTC project', addr: q[12],
      city: titleCase(q[3]), st: q[4], zip: q[13], lat: q[0], lon: q[1], units: q[5], zone: q[11], approx: q[10] }; ENT.set(e.key, e); }
    e.lih = q; e.lihId = q[14]; q._e = e;
  }
  const ALL = [...ENT.values()].filter(e => e.lat != null);
  // Owner groups (likely sponsors): HUD owner entities sharing an organization's email domain, else a mailing address
  const SP = HUD.sp || [], SP_N = new Map(), SP_TEXT = new Map();
  for (const e of ALL) {
    if (e.spon == null || e.spon < 0) e.spon = -1;
    else { SP_N.set(e.spon, (SP_N.get(e.spon) || 0) + 1); SP_TEXT.set(e.spon, (SP_TEXT.get(e.spon) || SP[e.spon].toLowerCase()) + ' | ' + (e.owner || '').toLowerCase()); }
    e.hay = [e.name, e.addr, e.city, e.st, stName[e.st], e.zip, e.county, e.id, e.lihId, e.owner, e.mgmt, e.spon >= 0 ? SP[e.spon] : ''].filter(Boolean).join(' ').toLowerCase();
    e.lname = (e.name || '').toLowerCase();
  }
  const sponLabel = i => i == null || i < 0 ? '' : SP[i];
  const lihTxt = q => !q ? '–' : [q[7] ? `PIS ${q[7]}` : 'LIHTC', q[8] >= 0 ? LIH.cr[q[8]] : ''].filter(Boolean).join(' · ');
  const kindTxt = e => [e.hud && 'HUD', e.lih && 'LIHTC'].filter(Boolean).join(' + ');
  const kindBadges = e => (e.hud ? '<span class="b hud">HUD</span>' : '') + (e.lih ? '<span class="b lih">LIHTC</span>' : '') + (e.pin ? '<span class="b pin">Pin</span>' : '');
  const contractTxt = e => { const h = e.h; if (h) return h[15] ? (h[14] || 'Active') : 'No active contract'; return e.hud ? 'Not located in HUD files' : 'LIHTC only'; };
  const R_EARTH = 3958.8, rad = Math.PI / 180;
  const dist = (a, b) => {
    const dp = (b.lat - a.lat) * rad, dl = (b.lon - a.lon) * rad;
    const h = Math.sin(dp / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dl / 2) ** 2;
    return 2 * R_EARTH * Math.asin(Math.sqrt(h));
  };

  /* ---------- state ---------- */
  const DEF = () => ({ stf: '', county: '', zone: '', type: 'any', minUnits: '', pisMin: '', pisMax: '', activeOnly: false, exp: '', spon: -1 });
  const S = Object.assign(DEF(), { radius: 5, ctr: null, view: 'near', sel: null, selE: null, limit: 300, sort: { near: { i: 'd', d: 1 }, view: { i: 'name', d: 1 } } });
  // Map layers are not filters: "Reset all" leaves them alone, but a layer that is off also leaves the lists.
  const MAPOPT = { hud: true, lih: true, qct: false, dda: false };
  const TYPEF = { any: () => true, hud: e => e.hud, lih: e => !!e.lih, lihHud: e => e.lih && e.hud, lihOnly: e => e.lih && !e.hud, hudNoLih: e => e.hud && !e.lih };
  const layerOn = e => (e.lih && MAPOPT.lih) || (e.hud && MAPOPT.hud);
  function entOk(e) {
    if (!layerOn(e) || !TYPEF[S.type](e)) return false;
    if (S.spon >= 0 && e.spon !== S.spon) return false;
    if (S.stf && e.st !== S.stf) return false;
    if (S.county && e.county !== S.county) return false;
    if (S.zone && ZN && !ZONEF[S.zone](e.zone || 0)) return false;
    if (ok(S.minUnits) && !(e.units >= +S.minUnits)) return false;
    if (ok(S.pisMin) || ok(S.pisMax)) { const y = e.lih && e.lih[7]; if (!y || (ok(S.pisMin) && y < +S.pisMin) || (ok(S.pisMax) && y > +S.pisMax)) return false; }
    if (S.activeOnly && !(e.h && e.h[15])) return false;
    if (S.exp) { const d = e.h && e.h[17]; if (!d || d > addYears(+S.exp)) return false; }
    return true;
  }

  /* ---------- rows ---------- */
  let NEAR = [], INVIEW = [];
  function nearRows() {
    const c = S.ctr, out = [], bandN = S.radius / 69 + 0.02;
    for (const e of ALL) {
      if (Math.abs(e.lat - c.lat) > bandN || !entOk(e)) continue;
      const d = dist(c, e); if (d <= S.radius) out.push({ e, d });
    }
    return out;
  }
  function viewRows() {
    const b = map.getBounds(), so = b.getSouth(), no = b.getNorth(), we = b.getWest(), ea = b.getEast(), out = [];
    for (const e of ALL) if (e.lat >= so && e.lat <= no && e.lon >= we && e.lon <= ea && entOk(e)) out.push({ e, d: S.ctr ? dist(S.ctr, e) : null });
    return out;
  }
  const C = (k, t, v, o = {}) => ({ k, t, v, ...o });
  const COLS = [
    C('name', 'Property', r => r.e.name, { f: r => `<b>${esc(r.e.name)}</b>` }),
    C('type', 'Type', r => kindTxt(r.e), { f: r => kindBadges(r.e), tip: 'HUD = HUD multifamily property · LIHTC = tax-credit project' }),
    C('city', 'City', r => r.e.city), C('st', 'State', r => r.e.st), C('county', 'County', r => r.e.county),
    C('d', 'Mi', r => r.d, { num: 1, f: r => mi(r.d), tip: 'Straight-line miles from the center of the area' }),
    C('units', 'Units', r => r.e.units, { num: 1, f: r => int(r.e.units), tip: 'Total units (HUD property file, else the LIHTC record)' }),
    C('lih', 'LIHTC', r => r.e.lih ? r.e.lih[7] : null, { f: r => esc(lihTxt(r.e.lih)), tip: 'Placed-in-service year and credit type (HUD LIHTC database and state award lists)' }),
    C('liu', 'Low-income units', r => r.e.lih ? r.e.lih[6] : null, { num: 1, f: r => int(r.e.lih && r.e.lih[6]) }),
    C('docs', 'HUD contract', r => contractTxt(r.e), { tip: 'Active contract types in HUD\'s Section 8 / multifamily files' }),
    C('next', 'Term ends', r => r.e.h ? r.e.h[16] : null, { tip: 'Earliest current-term expiration among the property\'s active contracts' }),
    C('ov', 'Overall exp.', r => r.e.h ? r.e.h[17] : null, { tip: 'Earliest overall contract expiration, including remaining option terms' }),
    C('cat', 'HUD category', r => r.e.h ? r.e.h[18] : null),
    ...(ZN ? [C('zone', '2027 QCT/DDA', r => zoneTxt(r.e.zone || 0), { tip: 'In a 2027 Qualified Census Tract and/or Difficult Development Area' })] : []),
    C('owner', 'Owner', r => r.e.owner), C('spon', 'Owner group', r => sponLabel(r.e.spon), { tip: 'Likely sponsor: owner entities sharing an email domain or mailing address' }),
    C('mgmt', 'Management agent', r => r.e.mgmt),
    C('id', 'ID', r => r.e.id || r.e.lihId, { tip: 'HUD property ID, else the LIHTC id' }),
  ];
  const VIEWS = { near: { rows: () => NEAR, cols: COLS }, view: { rows: () => INVIEW, cols: COLS.filter(c => c.k !== 'd' || S.ctr) } };
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
    $('#ctbl thead').innerHTML = '<tr>' + V.cols.map(c => `<th data-k="${c.k}" class="${c.num ? 'num' : ''}" title="${esc(c.tip ? c.tip + '. Click to sort' : 'Click to sort')}">${esc(c.t)}${so.i === c.k ? `<span class="arr">${so.d > 0 ? ' ▲' : ' ▼'}</span>` : ''}</th>`).join('') + '</tr>';
    SHOWN = rows.slice(0, S.limit);
    $('#ctbl tbody').innerHTML = SHOWN.map((r, i) => `<tr data-i="${i}" data-id="${esc(r.e.key)}"${r.e.key === S.sel ? ' class="sel"' : ''}>` +
      V.cols.map(c => `<td class="${c.num ? 'num' : ''}">${c.f ? c.f(r) : esc(c.v(r) ?? '–')}</td>`).join('') + '</tr>').join('');
    const em = $('#empty');
    em.hidden = rows.length > 0;
    em.innerHTML = S.view === 'near'
      ? (S.ctr ? `<b>Nothing within ${S.radius} miles of the center</b> passes the filters. Widen the radius or <button class="link" data-act="reset">reset the filters</button>.`
        : '<b>No area set.</b> Search for any property, address or ZIP above, or drop a pin, to list everything within the radius.')
      : `<b>Nothing in this part of the map</b> passes the filters. Pan or zoom out, or <button class="link" data-act="reset">reset the filters</button>.`;
    $('#more').innerHTML = rows.length > S.limit ? `Showing ${S.limit.toLocaleString()} of ${rows.length.toLocaleString()} rows <button class="btn small" id="moreBtn">Show 300 more</button>` : '';
    renderSummary(rows);
  }
  function renderSummary(rows) {
    const nH = rows.filter(r => r.e.hud).length, nL = rows.filter(r => r.e.lih).length, nB = rows.filter(r => r.e.hud && r.e.lih).length;
    const mix = `${plural(rows.length, 'place')} · ${nH.toLocaleString()} HUD · ${nL.toLocaleString()} LIHTC (${nB.toLocaleString()} at a HUD property)`;
    $('#summary').innerHTML = S.view === 'near'
      ? (S.ctr ? `Within ${S.radius} mi of <b>${esc(S.ctr.label)}</b>: ${mix}` : 'Search for any property, address or ZIP, or drop a pin, to list everything within the radius.')
      : `In the part of the map in view: ${mix}`;
  }
  $('#ctbl thead').addEventListener('click', e => {
    const th = e.target.closest('th'); if (!th) return;
    const so = S.sort[S.view];
    if (so.i === th.dataset.k) so.d = -so.d; else { so.i = th.dataset.k; so.d = colOf(VIEWS[S.view], th.dataset.k).num ? -1 : 1; }
    renderTable();
  });
  $('#ctbl tbody').addEventListener('click', e => { const tr = e.target.closest('tr'); if (!tr) return; const en = ENT.get(tr.dataset.id); if (en) selectEnt(en, true); });
  $('#more').addEventListener('click', e => { if (e.target.id === 'moreBtn') { S.limit += 300; renderTable(); } });
  $('#empty').addEventListener('click', e => { if (e.target.dataset.act === 'reset') resetAll(); });

  /* ---------- map ---------- */
  const map = L.map('map', { preferCanvas: true }).setView([39.5, -98.35], 4);
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
  const tiles = (svc, attr) => L.tileLayer(`${ESRI}${svc}/MapServer/tile/{z}/{y}/{x}`, { attribution: attr, maxZoom: 19, maxNativeZoom: 16 });
  L.layerGroup([tiles('Canvas/World_Light_Gray_Base', 'Tiles &copy; Esri | HUD Multifamily | HUD LIHTC database'), tiles('Canvas/World_Light_Gray_Reference', '')]).addTo(map);
  map.createPane('reach').style.zIndex = 390;   // radius circle under the dots
  const reachRenderer = L.svg({ pane: 'reach' });
  const dots = L.layerGroup().addTo(map), ring = L.layerGroup().addTo(map);
  const LIHC = '#db2777', HUDC = '#475569';
  const ZONE_STYLE = { qct: { color: '#7c3aed', fillColor: '#7c3aed' }, dda: { color: '#0d9488', fillColor: '#0d9488' } };
  const legend = L.control({ position: 'bottomright' });
  let legendEl = null;
  function renderLegend() {
    if (!legendEl) return;
    legendEl.innerHTML = (MAPOPT.hud ? `<i style="background:${HUDC}"></i>HUD multifamily property<br>` : '') +
      (MAPOPT.lih ? `<i style="background:${LIHC}"></i>LIHTC project, not a HUD property<br><i class="ring"></i>LIHTC at a HUD property<br>` : '') +
      '<i class="approx"></i>Approximate location (ZIP centre)' +
      (MAPOPT.qct ? `<br><i class="sq" style="background:${ZONE_STYLE.qct.color}"></i>2027 QCT` : '') +
      (MAPOPT.dda ? `<br><i class="sq" style="background:${ZONE_STYLE.dda.color}"></i>2027 DDA` : '');
  }
  legend.onAdd = () => { legendEl = L.DomUtil.create('div', 'legend'); renderLegend(); return legendEl; };
  legend.addTo(map);
  const layersCtl = L.control({ position: 'topleft' });
  layersCtl.onAdd = () => {
    const d = L.DomUtil.create('div', 'legend mapopts');
    d.innerHTML = `<b>On the map</b>
      <label class="chk"><input type="checkbox" id="mHud"> HUD properties <i style="background:${HUDC}"></i></label>
      <label class="chk"><input type="checkbox" id="mLih"> LIHTC projects <i style="background:${LIHC}"></i></label>
      <div id="layerNote" class="hint" hidden></div>
      <label class="chk"><input type="checkbox" id="mQct"> 2027 QCTs <i class="sq" style="background:${ZONE_STYLE.qct.color}"></i></label>
      <label class="chk"><input type="checkbox" id="mDda"> 2027 DDAs <i class="sq" style="background:${ZONE_STYLE.dda.color}"></i></label>
      <div id="zoneNote" class="hint" hidden></div>`;
    L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
    return d;
  };
  layersCtl.addTo(map);
  $('#mHud').checked = MAPOPT.hud; $('#mLih').checked = MAPOPT.lih;
  $('#mHud').addEventListener('change', e => { MAPOPT.hud = e.target.checked; renderLegend(); refresh(); });
  $('#mLih').addEventListener('change', e => { MAPOPT.lih = e.target.checked; renderLegend(); refresh(); });

  // 2027 QCT / DDA polygons: the main map's file (../assets/qct_dda_2027.js), loaded the first time either is turned on.
  map.createPane('zones').style.zIndex = 350;
  const zoneRenderer = L.canvas({ pane: 'zones', padding: 0.5 });
  const zoneLayers = { qct: L.layerGroup(), dda: L.layerGroup() };
  let zonesLoad = null;
  function loadZones() {
    if (!zonesLoad) zonesLoad = new Promise((res, rej) => {
      if (window.QCT_DDA_2027) return res();
      const el = document.createElement('script'); el.src = '../assets/qct_dda_2027.js'; el.onload = res; el.onerror = rej; document.head.appendChild(el);
    }).then(() => {
      for (const k of ['qct', 'dda']) L.geoJSON(window.QCT_DDA_2027[k], { renderer: zoneRenderer, interactive: false, style: { ...ZONE_STYLE[k], weight: 0.6, fillOpacity: 0.16 } }).addTo(zoneLayers[k]);
    }).catch(err => { zonesLoad = null; throw err; });
    return zonesLoad;
  }
  function setZoneLayer(k, on) {
    MAPOPT[k] = on; renderLegend();
    const note = $('#zoneNote');
    if (!on) { map.removeLayer(zoneLayers[k]); if (!MAPOPT.qct && !MAPOPT.dda) note.hidden = true; return; }
    note.hidden = false; note.textContent = 'Loading the 2027 QCT / DDA map…';
    loadZones().then(() => { if (MAPOPT[k]) zoneLayers[k].addTo(map); note.textContent = 'HUD 2027 designations. Filter by them with "2027 QCT / DDA" in the sidebar.'; })
      .catch(() => { note.textContent = 'Could not load the QCT / DDA map. Try again.'; MAPOPT[k] = false; $(k === 'qct' ? '#mQct' : '#mDda').checked = false; renderLegend(); });
  }
  $('#mQct').addEventListener('change', e => setZoneLayer('qct', e.target.checked));
  $('#mDda').addEventListener('change', e => setZoneLayer('dda', e.target.checked));

  // Dots are drawn for the part of the map in view. Past the cap, every k-th place is drawn so the national view still shows the pattern.
  const CAP = 20000;
  function tip(e) {
    const q = e.lih, h = e.h;
    let t = `<b>${esc(e.name)}</b> · ${esc([e.city, e.st].filter(Boolean).join(', '))}`;
    if (h) t += `<br>HUD ${esc(h[15] ? (h[14] || 'active contract') : 'no active contract')}${e.units != null ? ` · ${int(e.units)} units` : ''}${h[17] ? ` · overall exp. ${esc(h[17])}` : ''}`;
    if (q) t += `<br>LIHTC${q[6] ? ` · ${int(q[6])}${q[5] ? ` of ${int(q[5])}` : ''} units low-income` : q[5] ? ` · ${int(q[5])} units` : ''}${q[7] ? ` · placed in service ${q[7]}` : ''}${q[8] >= 0 ? ` · ${esc(LIH.cr[q[8]])}` : ''}`;
    if (e.zone) t += `<br>2027 ${zoneTxt(e.zone)}`;
    if (e.approx) t += '<br><i>Location approximate (ZIP centre)</i>';
    return t + '<br><i>Click for details</i>';
  }
  function drawDots() {
    dots.clearLayers();
    const note = $('#layerNote');
    if (!MAPOPT.hud && !MAPOPT.lih) { note.hidden = false; note.textContent = 'Both layers are off.'; return; }
    const b = map.getBounds().pad(0.15), so = b.getSouth(), no = b.getNorth(), we = b.getWest(), ea = b.getEast();
    const vis = [];
    for (const e of ALL) if (e.lat >= so && e.lat <= no && e.lon >= we && e.lon <= ea && entOk(e)) vis.push(e);
    const step = Math.max(1, Math.ceil(vis.length / CAP));
    let nH = 0, nL = 0;
    for (let i = 0; i < vis.length; i += step) {
      const e = vis[i], asLih = e.lih && MAPOPT.lih;
      const m = asLih && e.hud ? L.circleMarker([e.lat, e.lon], { radius: 7, weight: 2, color: LIHC, fillColor: HUDC, fillOpacity: e.approx ? 0.3 : 0.7 })
        : asLih ? L.circleMarker([e.lat, e.lon], { radius: 4, weight: 1, color: '#fff', fillColor: LIHC, fillOpacity: e.approx ? 0.45 : 0.85 })
        : L.circleMarker([e.lat, e.lon], { radius: 3.5, weight: 0.8, color: '#fff', fillColor: HUDC, fillOpacity: e.approx ? 0.4 : 0.85 });
      if (e.key === S.sel) m.setStyle({ color: '#111', weight: 3, radius: 8 });
      m.bindTooltip(() => tip(e));
      m.on('click', () => selectEnt(e, false));
      dots.addLayer(m);
      if (e.hud) nH++; if (e.lih) nL++;
    }
    note.hidden = false;
    note.textContent = step > 1 ? `${vis.length.toLocaleString()} places in view; drawing 1 in ${step}. Zoom in to see them all.`
      : `In view: ${vis.filter(e => e.hud).length.toLocaleString()} HUD properties, ${vis.filter(e => e.lih).length.toLocaleString()} LIHTC projects (ringed when at a HUD property).`;
  }
  function drawRing() {
    ring.clearLayers();
    const c = S.ctr;
    if (!c) return;
    L.circle([c.lat, c.lon], { renderer: reachRenderer, radius: S.radius * 1609.344, color: '#1f4e99', weight: 1.5, dashArray: '6 6', fillColor: '#1f4e99', fillOpacity: 0.05, interactive: false }).addTo(ring);
    L.circleMarker([c.lat, c.lon], { renderer: reachRenderer, radius: 5, color: '#1f4e99', weight: 2.5, fillColor: '#fff', fillOpacity: 1, interactive: false }).addTo(ring);
  }
  let moveT;
  map.on('moveend', () => { clearTimeout(moveT); moveT = setTimeout(() => { drawDots(); if (S.view === 'view') { INVIEW = viewRows(); S.limit = 300; renderTable(); } }, 80); });

  /* ---------- selection and detail ---------- */
  function selectEnt(e, fromTable) {
    S.sel = e.key; S.selE = e;
    history.replaceState(null, '', e.pin ? location.pathname + location.search : '#sel=' + encodeURIComponent(e.key));
    $$('#ctbl tbody tr').forEach(tr => tr.classList.toggle('sel', tr.dataset.id === e.key));
    if (!fromTable) { const tr = $$('#ctbl tbody tr').find(tr => tr.dataset.id === e.key); if (tr) tr.scrollIntoView({ block: 'nearest' }); }
    renderDetail(e);
    // Frame the place and the radius circle, keeping clear of the detail panel that covers the map's right side.
    const padR = Math.min($('#detail').offsetWidth, $('#map').offsetWidth * 0.7) + 20, pts = [[e.lat, e.lon]];
    if (S.ctr) { const c = L.latLng(S.ctr.lat, S.ctr.lon).toBounds(S.radius * 1609.344 * 2); pts.push(c.getSouthWest(), c.getNorthEast()); }
    map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [20, 20], paddingBottomRight: [padR, 20], maxZoom: 15 });
    drawDots();
  }
  function renderDetail(e) {
    const h = e.h, q = e.lih;
    const where = [e.addr, [[e.city, e.st].filter(Boolean).join(', '), e.zip].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    const at = e.pin ? `${e.lat.toFixed(5)}, ${e.lon.toFixed(5)}` : where || `${e.lat.toFixed(5)}, ${e.lon.toFixed(5)}`;
    let x = `<h2>${esc(e.name)} ${kindBadges(e)}</h2><div class="muted">${esc(at)}${e.county ? ` · ${esc(e.county)} County` : ''}</div>`;
    const links = [];
    if (e.hud && e.id) links.push(`<a href="../#sel=${esc(e.id)}" target="_blank" rel="noopener">Open on the contract rent map</a> <span class="muted">(contracts, rents by bedroom, owner contacts, financing)</span>`);
    if (!e.pin) links.push(`<a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(where || `${e.lat},${e.lon}`)}" target="_blank" rel="noopener">Google Maps</a>`);
    if (links.length) x += `<p class="links">${links.join(' · ')}</p>`;
    x += '<dl class="kv">';
    if (e.hud) x += `<dt>HUD property ID</dt><dd>${esc(e.id || '–')}</dd>`;
    if (e.owner) x += `<dt>Owner</dt><dd>${esc(e.owner)}</dd>`;
    if (e.spon >= 0) x += `<dt>Owner group (likely sponsor)</dt><dd><b>${esc(sponLabel(e.spon))}</b> · ${(SP_N.get(e.spon) || 0).toLocaleString()} properties${S.spon === e.spon ? '' : ` · <button class="link" data-spon="${e.spon}">Show this group's whole portfolio</button>`}</dd>`;
    if (e.mgmt) x += `<dt>Management agent</dt><dd>${esc(e.mgmt)}</dd>`;
    if (e.units != null) x += `<dt>Units</dt><dd>${int(e.units)}${h && h[10] != null && h[10] !== h[9] ? ` (${int(h[10])} assisted)` : ''}</dd>`;
    if (h) x += `<dt>HUD category</dt><dd>${esc(h[18] || '–')}</dd><dt>Active HUD contracts</dt><dd>${h[15] ? `${h[15]} (${esc(h[14] || 'type not on file')}) · term ends ${esc(h[16] || '?')} · overall expiration ${esc(h[17] || '?')}` : "None in HUD's active list"}</dd>`;
    if (e.hud && !h) x += `<dt>HUD files</dt><dd>Property ID ${esc(e.id)} is on this LIHTC record but HUD's files give it no location; shown at the LIHTC address.</dd>`;
    if (q) x += `<dt>LIHTC</dt><dd>${esc(lihTxt(q))}${q[6] ? ` · ${int(q[6])} low-income units${q[5] ? ` of ${int(q[5])}` : ''}` : ''}${q[14] ? `<div class="subnote">ID ${esc(q[14])}</div>` : ''}</dd>`;
    if (e.hud && !q) x += '<dt>LIHTC</dt><dd>No LIHTC record matched by address, location or name. That does not prove the property has no tax credits.</dd>';
    if (ZN && !e.pin) x += `<dt>2027 QCT / DDA</dt><dd>${zoneTxt(e.zone || 0) || 'Neither'}</dd>`;
    x += '</dl>';
    if (e.approx) x += '<p class="note">Location approximate (ZIP or area centre), so distances are rough.</p>';
    const isCtr = S.ctr && S.ctr.key === e.key;
    if (!isCtr) x += `<div class="callout muted">${e.pin ? 'A point on the map.' : e.lih && !e.hud ? 'LIHTC project, not in HUD\'s Section 8 / multifamily files.' : 'HUD multifamily property.'}<div><button class="btn small" data-center="${esc(e.key)}">List everything within ${S.radius} mi of here</button></div></div>`;
    $('#detailBody').innerHTML = x;
    $('#detail').hidden = false;
    $('.detail-scroll').scrollTop = 0;
  }
  $('#detailBody').addEventListener('click', ev => {
    const b = ev.target.closest('[data-center]'); if (b) { const e = b.dataset.center === 'pin' ? S.selE : ENT.get(b.dataset.center); if (e) setCenter(e); }
    const g = ev.target.closest('[data-spon]'); if (g) filterToSponsor(+g.dataset.spon);
  });
  function filterToSponsor(i) {
    $('#sugg').hidden = true; $('#q').value = '';
    S.spon = i; S.stf = ''; S.county = ''; S.ctr = null;
    setView('view');   // the In view list shows the portfolio once the map frames it
    const pts = ALL.filter(e => e.spon === i && !e.approx).map(e => [e.lat, e.lon]);
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [20, 20], maxZoom: 12 });
    syncControls(); refresh();
  }
  $('#f-spon').addEventListener('click', e => { if (e.target.dataset.clearSpon != null) { S.spon = -1; syncControls(); refresh(); } });
  function closeDetail() { $('#detail').hidden = true; S.sel = null; S.selE = null; history.replaceState(null, '', location.pathname + location.search); $$('#ctbl tbody tr.sel').forEach(tr => tr.classList.remove('sel')); drawDots(); }
  $('#closeDetail').addEventListener('click', closeDetail);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || $('#about').open) return;
    if (!$('#sugg').hidden) { $('#sugg').hidden = true; return; }
    if (!$('#detail').hidden) closeDetail();
  });

  /* ---------- controls ---------- */
  const county = $('#county'), stateF = $('#stateF');
  const stN = {};
  for (const e of ALL) stN[e.st] = (stN[e.st] || 0) + 1;
  stateF.innerHTML = '<option value="">All states</option>' + Object.keys(stN).filter(c => c).sort((a, b) => (stName[a] || a).localeCompare(stName[b] || b))
    .map(c => `<option value="${esc(c)}">${esc(stName[c] || c)} (${stN[c].toLocaleString()})</option>`).join('');
  function fillCounties() {
    if (!S.stf) { county.innerHTML = '<option value="">All counties (pick a state first)</option>'; county.disabled = true; return; }
    const n = {};
    for (const e of ALL) if (e.st === S.stf && e.county) n[e.county] = (n[e.county] || 0) + 1;
    county.disabled = false;
    county.innerHTML = '<option value="">All counties</option>' + Object.keys(n).sort().map(c => `<option value="${esc(c)}">${esc(c)} (${n[c].toLocaleString()})</option>`).join('');
    county.value = S.county;
  }
  function syncControls() {
    stateF.value = S.stf; fillCounties();
    $('#zone').value = S.zone; $('#type').value = S.type; $('#minUnits').value = S.minUnits; $('#pisMin').value = S.pisMin; $('#pisMax').value = S.pisMax;
    $('#activeOnly').checked = S.activeOnly; $('#exp').value = S.exp; $('#radius').value = S.radius;
    $('#f-spon').innerHTML = S.spon >= 0 ? `<span class="chip">${esc(sponLabel(S.spon))} <span class="n">${(SP_N.get(S.spon) || 0).toLocaleString()}</span><button class="link" data-clear-spon title="Remove">×</button></span>` : '<span class="muted">All owners</span>';
  }
  function renderCtr() {
    $('#ctrInfo').innerHTML = S.ctr ? `Area: <b>${esc(S.ctr.label)}</b> · ${S.radius} mi · see the Nearby tab` : 'No area set. Pick a search result or drop a pin to list everything within the radius.';
    const n = [S.type !== 'any', S.stf, S.county, S.zone, ok(S.minUnits), ok(S.pisMin) || ok(S.pisMax), S.activeOnly, S.exp, S.spon >= 0].filter(Boolean).length;
    $('#filtersBtn').textContent = n ? `Filters (${n})` : 'Filters';
  }
  function refresh() {
    S.limit = 300;
    NEAR = S.ctr ? nearRows() : [];
    INVIEW = S.view === 'view' ? viewRows() : [];
    renderCtr(); drawRing(); drawDots(); renderTable();
    if (S.selE && !$('#detail').hidden) renderDetail(S.selE);
  }
  function fitState() {
    if (!S.stf) return map.fitBounds([[24.5, -124.8], [49.4, -66.9]]);
    const pts = ALL.filter(e => e.st === S.stf && !e.approx).map(e => [e.lat, e.lon]);
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [10, 10] });
  }
  function resetAll() { const f = S.stf; Object.assign(S, DEF()); syncControls(); refresh(); if (f) fitState(); }

  /* ---------- search any place, set the area ---------- */
  function setCenter(e) {
    S.ctr = e ? { lat: e.lat, lon: e.lon, label: e.name, key: e.key } : null;
    if (e) setView('near');
    refresh();
    if (e) { const c = L.latLng(e.lat, e.lon).toBounds(S.radius * 1609.344 * 2); map.fitBounds(c, { padding: [20, 20] }); }
  }
  $('#clearCtr').addEventListener('click', () => { $('#q').value = ''; setCenter(null); });
  let PIN = false;
  function setPin(on) { PIN = on; document.body.classList.toggle('pinmode', on); $('#pinBtn').classList.toggle('on', on); $('#pinBtn').textContent = on ? 'Click the map…' : 'Drop a pin'; }
  $('#pinBtn').addEventListener('click', () => setPin(!PIN));
  map.on('click', ev => { if (!PIN) return; setPin(false); pinAt(ev.latlng.lat, ev.latlng.lng, 'Dropped pin'); });
  function pinAt(lat, lon, label) {
    $('#sugg').hidden = true;
    const e = { key: 'pin', pin: true, name: label, lat, lon, hud: false, lih: null, h: null };
    if (!$('#detail').hidden) closeDetail();   // a pin has nothing to show in the panel; the Nearby list is the result
    setCenter(e);
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
    for (const e of ALL) {
      if (!toks.every(t => e.hay.includes(t))) continue;
      const nm = e.lname, sc = (e.id && e.id.toLowerCase() === qt) || (e.lihId && e.lihId.toLowerCase() === qt) || nm === qt ? 0 : nm.startsWith(qt) ? 1 : nm.startsWith(toks[0]) ? 2 : nm.includes(toks[0]) ? 3 : 4;
      res.push([sc + (e.approx ? 0.5 : 0), e]);
      if (res.length > 800) break;
    }
    return res.sort((a, b) => a[0] - b[0]).slice(0, 10).map(x => x[1]);
  }
  function suggest() {
    const q = $('#q').value.trim();
    if (!q) return showSugg([]);
    const items = matches(q).map(e => ({ html: `${esc(e.name)} ${kindBadges(e)}<small>${esc([e.addr, e.city, e.st, e.zip].filter(Boolean).join(', '))}${e.id ? ' · ' + esc(e.id) : e.lihId ? ' · ' + esc(e.lihId) : ''}${e.approx ? ' · approximate location' : ''}</small>`, go: () => pick(e) }));
    const t = q.toLowerCase().replace(/^@/, '');
    if (t.length >= 3) {
      const sp = [];
      for (const [i, txt] of SP_TEXT) { const at = txt.indexOf(t); if (at >= 0) sp.push([i, at < SP[i].length ? 0 : 1]); }
      sp.sort((a, b) => a[1] - b[1] || (SP_N.get(b[0]) || 0) - (SP_N.get(a[0]) || 0)).slice(0, 3).forEach(([i]) => items.unshift({
        html: `Owner group ${esc(sponLabel(i))}<small>${(SP_N.get(i) || 0).toLocaleString()} HUD properties · shows the whole portfolio and clears the area</small>`, go: () => filterToSponsor(i) }));
    }
    const st = Object.keys(stName).find(c => c !== 'US' && (c.toLowerCase() === q.toLowerCase() || (q.length >= 3 && stName[c].toLowerCase().startsWith(q.toLowerCase()))));
    if (st && stN[st]) items.unshift({ html: `Show all of ${esc(stName[st])} (${st})<small>State filter · ${stN[st].toLocaleString()} places</small>`, go: () => { $('#sugg').hidden = true; $('#q').value = ''; S.stf = st; S.county = ''; syncControls(); refresh(); fitState(); } });
    if (/^\d{5}$/.test(q)) {
      const zs = ALL.filter(e => e.zip === q && !e.approx);
      if (zs.length) items.unshift({ html: `ZIP ${esc(q)}<small>Center on the ${zs.length} places in this ZIP</small>`,
        go: () => pinAt(zs.reduce((a, e) => a + e.lat, 0) / zs.length, zs.reduce((a, e) => a + e.lon, 0) / zs.length, `ZIP ${q}`) });
    }
    const ll = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (ll) items.unshift({ html: `Use coordinates ${esc(q)}`, go: () => pinAt(+ll[1], +ll[2], `Coordinates ${q}`) });
    else items.push({ html: `Find address on map: “${esc(q)}”<small>Esri World Geocoder (sends this text to geocode.arcgis.com)</small>`, go: () => geocode(q) });
    showSugg(items);
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
      showSugg(cands.map(c => ({ html: `${esc(c.address)}<small>match score ${Math.round(c.score)}</small>`, go: () => pinAt(c.location.y, c.location.x, c.address) })));
    } catch (err) { el.innerHTML = '<div>Address search failed. Try again.</div>'; }
  }
  let qT;
  $('#q').addEventListener('input', () => { clearTimeout(qT); qT = setTimeout(suggest, 140); });
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
  stateF.addEventListener('change', () => { S.stf = stateF.value; S.county = ''; syncControls(); refresh(); fitState(); });
  county.addEventListener('change', () => { S.county = county.value; refresh(); });
  $('#radius').addEventListener('change', e => { const v = +e.target.value; if (v > 0) { S.radius = Math.min(v, 500); syncControls(); refresh(); } else syncControls(); });
  $$('[data-r]').forEach(b => b.addEventListener('click', () => { S.radius = +b.dataset.r; syncControls(); refresh(); }));
  const bind = (id, k) => $(id).addEventListener('change', e => { S[k] = e.target.type === 'checkbox' ? e.target.checked : e.target.value; syncControls(); refresh(); });
  bind('#type', 'type'); bind('#zone', 'zone'); bind('#minUnits', 'minUnits'); bind('#pisMin', 'pisMin'); bind('#pisMax', 'pisMax'); bind('#activeOnly', 'activeOnly'); bind('#exp', 'exp');
  $('#resetAll').addEventListener('click', resetAll);
  function setView(v) { S.view = v; $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === v)); }
  $$('.tab').forEach(t => t.addEventListener('click', () => { setView(t.dataset.view); refresh(); }));
  $('#filtersBtn').addEventListener('click', () => { const on = document.body.classList.toggle('filters-open'); if (on) $('#filtersBlock').scrollIntoView({ behavior: 'smooth', block: 'start' }); });

  /* ---------- CSV ---------- */
  $('#exportBtn').addEventListener('click', () => {
    const V = VIEWS[S.view], rows = sorted();
    const cell = v => { if (v == null || (typeof v === 'number' && !isFinite(v))) return ''; const s = typeof v === 'number' ? String(Math.round(v * 10000) / 10000) : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const cols = [...V.cols, C('lat', 'Latitude', r => r.e.lat), C('lon', 'Longitude', r => r.e.lon), C('approx', 'Location approximate', r => r.e.approx ? 'Y' : '')];
    const csv = [cols.map(c => cell(c.t)).join(','), ...rows.map(r => cols.map(c => cell(c.v(r))).join(','))].join('\r\n');
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv' })), download: `hud-lihtc-${S.view}-${today}.csv` });
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });

  /* ---------- about ---------- */
  const nHud = HUD.P.length, nLih = LIH.P.length, nOn = LIH.meta.on_hud, nOnly = LIH.meta.lihtc_only;
  $('#asof').textContent = `${nHud.toLocaleString()} HUD multifamily properties (HUD files ${HUD.meta.hud_built.slice(0, 10)}) · ${nLih.toLocaleString()} LIHTC projects (${nOn.toLocaleString()} at HUD properties; LIHTC lists built ${LIH.meta.lihtc_built})`;
  $('#aboutBody').innerHTML = `<h2>About the data</h2>
    <p>One map of every located HUD multifamily property and every LIHTC project, from public HUD data. It is the same map as the rent screener without the rent studies: no password, and nothing proprietary.</p>
    <h3>HUD multifamily properties (slate dots)</h3>
    <ul><li>${nHud.toLocaleString()} properties from HUD's Multifamily Assistance &amp; Section 8 contract, property and active-portfolio files (published ${esc(HUD.meta.hud_built.slice(0, 10))}), with the owner entity, management agent, unit counts, HUD property category, active contract types and the earliest current-term and overall contract expirations. ${HUD.meta.unlocated_left_out.toLocaleString()} property IDs with no usable location are left out; they are searchable on the <a href="../">contract rent map</a>.</li>
      <li>Coordinates come from HUD's <i>Multifamily Properties - Assisted</i> GIS layer; properties it does not locate are placed at their ZIP centroid and drawn hollow ("approximate").</li>
      <li>Click "Open on the contract rent map" in a property's panel for its contracts, rents by bedroom, utility allowances, owner contacts, FHA financing and LIHTC match details.</li></ul>
    <h3>LIHTC projects (pink dots)</h3>
    <ul><li>${nLih.toLocaleString()} projects: HUD's LIHTC database (projects placed in service through about 2020–2022) plus state housing-agency award and property lists for newer allocations. ${nOn.toLocaleString()} are matched to a HUD property by address, location and name (high or medium confidence) and drawn as a pink ring on that property's dot; ${nOnly.toLocaleString()} are LIHTC-only. ${LIH.meta.lihtc_only_unlocated.toLocaleString()} LIHTC-only records with no location are left out.</li>
      <li>Units = total units; low-income units = the largest low-income count on the project's records; placed-in-service year and credit type come from its latest allocation. Matching is by address and name, so treat a match as a lead to verify, not a conclusion.</li></ul>
    <h3>2027 QCT / DDA</h3>
    <ul><li>HUD's 2027 Qualified Census Tracts and Difficult Development Areas (effective 2027-01-01), tested point-in-polygon for every place. Turn the polygons on from "On the map"; filter by them in the sidebar.</li></ul>
    <h3>Using the map</h3>
    <ul><li>Search finds any HUD property, LIHTC project, state, ZIP, address (Esri geocoder) or coordinates; "Drop a pin" picks any point. The pick becomes the center of an area, and the Nearby tab lists everything within the radius. The In view tab lists whatever is inside the current map window.</li>
      <li>Owner group (likely sponsor): HUD owner entities are usually single-asset LLCs or LPs, so they are grouped by a shared organization email domain (free and ISP mail ignored) or, without one, a shared mailing address. Search a sponsor name or email domain (e.g. "mercyhousing") and pick the owner-group result, or open a HUD property and click "Show this group's whole portfolio". It is a lead, not proof of control.</li>
      <li>The checkboxes at the top left of the map switch the HUD and LIHTC layers on and off; the "Show" filter in the sidebar does the same with finer splits (for example LIHTC projects that are not HUD properties). Both lists follow the layers and filters.</li>
      <li>Past ${CAP.toLocaleString()} places in view, the map draws a sample (1 in 2, 1 in 3 …) so the national view still shows the pattern; zoom in to see every place.</li></ul>
    <p class="note">For screening only. HUD and state files lag sales, resyndications and new contracts; verify before relying on any record. Built ${esc(LIH.meta.built)}.</p>`;
  $('#aboutBtn').addEventListener('click', () => $('#about').showModal());

  /* ---------- go ---------- */
  syncControls();
  refresh();
  const fromHash = () => {
    const m = /sel=([^&]+)/.exec(location.hash), e0 = m && ENT.get(decodeURIComponent(m[1]));
    if (e0 && e0.key !== S.sel && e0.lat != null) { map.setView([e0.lat, e0.lon], 13); selectEnt(e0, false); }
  };
  fromHash();
  window.addEventListener('hashchange', fromHash);
  window.HLMAP = { S, MAPOPT, ENT, ALL, SP, SP_N, map, refresh, setCenter, selectEnt, entOk, nearRows, viewRows, filterToSponsor };
}
})();

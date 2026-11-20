"""Build the rent screener's public map layers:
  screener/lihtc.js   one map point per LIHTC project, for the "LIHTC projects" layer
  screener/hud_all.js every located HUD multifamily property (not only those with Section 8 rent lines), so the
                      screener can search, map and query any HUD property
  screener/zones.js   HUD property ids inside a 2027 QCT / DDA, for the screener's QCT/DDA filter
                      (the polygons themselves come from assets/qct_dda_2027.js, tools/build_qct_dda.py)

Inputs (already built for the main map):
  assets/hud_data.js    HUD properties; H.PL links each HUD property to its LIHTC records (tools/merge_lihtc.py)
  assets/lihtc_all.js   every LIHTC project not attached to a HUD property (tools/build_lihtc_all.py)
Rules:
  - A HUD property with a high or medium LIHTC match (PL "best" < 2) is one project, placed at the HUD property and
    carrying its HUD property id, so the screener can open that property when it has one.
  - Every LIHTC-only project with a location is one project; ZIP-centroid locations are flagged approximate.
  - Units = total units; LI units = the largest low-income unit count on its records; placed in service and credit
    type come from its latest allocation.
  - QCT / DDA flags: H.Z for HUD properties and zq / zd for LIHTC-only projects (both from the same 2027
    point-in-polygon test, tools/build_qct_dda.py).
The data is public (HUD's LIHTC database and state award lists), so this file is not encrypted.
Usage: python tools/build_screener_layers.py
"""
import datetime as dt
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_js(name, var):
    s = (ROOT / 'assets' / name).read_text(encoding='utf-8')
    pre = f'window.{var}='
    assert s.startswith(pre), name
    return json.loads(s[len(pre):].rstrip().rstrip(';'))


H = load_js('hud_data.js', 'HUD_DATA')
X = load_js('lihtc_all.js', 'LIHTC_ALL')
CR = []


def cr(v):
    if v is None or v == '':
        return -1
    if v not in CR:
        CR.append(v)
    return CR.index(v)


def latest(recs):   # the record with the latest allocation (then placed-in-service) year
    return max(recs, key=lambda r: (r[7] or 0, r[8] or 0))


ZONE = {z[0]: (1 if z[1] else 0) | (2 if z[2] else 0) for z in H.get('Z', [])}   # HUD P index -> 1 QCT | 2 DDA
rows = []
# 1) LIHTC projects on HUD properties
n_hud = 0
for pl in H.get('PL', []):
    pi, links, best = pl[0], pl[1], pl[2]
    if best is None or best >= 2:
        continue
    p = H['P'][pi]
    if p[8] is None:
        continue
    recs = [H['LI'][i] for i, tier, _ in links if tier < 2]
    if not recs:
        continue
    lr = latest(recs)
    li_units = max((r[13] or 0) for r in recs) or None
    rows.append([round(p[8], 5), round(p[9], 5), p[1], p[3], p[4], p[12], li_units, pl[4], cr(lr[9]), p[0], 0, ZONE.get(pi, 0), p[2], p[5], lr[6] or lr[5]])
    n_hud += 1

# 2) LIHTC-only projects
li = 0
n_only = n_noloc = 0
zq, zd = set(X['zq']), set(X['zd'])
for j, q in enumerate(X['P']):
    recs = X['LI'][li: li + q[10]]
    li += q[10]
    if q[6] is None:
        n_noloc += 1
        continue
    lr = latest(recs)
    li_units = max((r[13] or 0) for r in recs) or None
    credit = X['cr'][lr[9]] if lr[9] is not None else None
    rows.append([round(q[6], 5), round(q[7], 5), q[1], q[3], q[4], q[9], li_units, q[12], cr(credit), '', 1 if q[8] == 'C' else 0, (1 if j in zq else 0) | (2 if j in zd else 0), q[2], q[5], q[0]])
    n_only += 1
assert li == len(X['LI'])

out = {'meta': {'built': dt.date.today().isoformat(), 'hud_built': H['meta'].get('built'), 'lihtc_built': X['meta'].get('built'),
                'on_hud': n_hud, 'lihtc_only': n_only, 'lihtc_only_unlocated': n_noloc,
                'cols': ['lat', 'lon', 'name', 'city', 'st', 'units', 'liUnits', 'pis', 'credit (index into cr, -1 none)', 'hud property id ("" = LIHTC only)', 'approx (ZIP centroid)', 'zone (1 = 2027 QCT, 2 = 2027 DDA)', 'addr', 'zip', 'LIHTC id (HUD LIHTC id, else state id)']},
       'cr': CR, 'P': rows}
dest = ROOT / 'screener' / 'lihtc.js'
dest.write_text('window.RS_LIHTC=' + json.dumps(out, separators=(',', ':'), ensure_ascii=False) + ';', encoding='utf-8')
print(f'{dest}: {len(rows):,} projects ({n_hud:,} on HUD properties, {n_only:,} LIHTC only; {n_noloc:,} LIHTC-only without a location left out), {dest.stat().st_size / 1e6:.1f} MB')

# 3) QCT / DDA membership of every HUD property (ids only)
qct = sorted(H['P'][i][0] for i, z in ZONE.items() if z & 1)
dda = sorted(H['P'][i][0] for i, z in ZONE.items() if z & 2)
zout = {'meta': {'year': 2027, 'built': dt.date.today().isoformat(), 'hud_built': H['meta'].get('built'), 'tested': len(ZONE),
                 'note': 'HUD property ids inside a 2027 QCT / DDA (tools/build_qct_dda.py point-in-polygon test)'}, 'qct': qct, 'dda': dda}
zdest = ROOT / 'screener' / 'zones.js'
zdest.write_text('window.RS_ZONES=' + json.dumps(zout, separators=(',', ':')) + ';', encoding='utf-8')
print(f'{zdest}: {len(ZONE):,} HUD properties tested, {len(qct):,} in a QCT, {len(dda):,} in a DDA, {zdest.stat().st_size / 1e3:.0f} KB')

# 4) Every located HUD property (public HUD data), so any HUD property can be searched and queried
D = H['dict']
cons = {}
for c in H['C']:
    cons.setdefault(c[0], []).append(c)
# Owner group (likely sponsor, tools/merge_owners.py): owner entities sharing an organization's email domain, else a
# mailing address. Label shown as "@domain" for email groups. Index into hout.sp, -1 = none.
SPON = {r[0]: D['own'][r[1]][9] for r in H.get('OW', []) if r[1] >= 0 and D['own'][r[1]][9] is not None and D['own'][r[1]][9] >= 0}
SP = [('@' + g[0]) if g[1] == 'email' else g[0] for g in D.get('spon', [])]
hrows = []
for i, p in enumerate(H['P']):
    if p[8] is None:
        continue
    cs = cons.get(i, [])
    act = [c for c in cs if c[2] == 0]
    docs = sorted({D['doc'][c[6]] for c in act if c[6] is not None and c[6] >= 0})
    nxt = min((c[10] for c in act if c[10]), default=None)
    ov = min((c[11] for c in act if c[11]), default=None)
    pc = D['propcat'][p[14]] if p[14] is not None and p[14] >= 0 else None
    hrows.append([p[0], round(p[8], 5), round(p[9], 5), p[1], p[2], p[3], p[4], p[5], p[6], p[12], p[13], p[15], p[16],
                  0 if p[10] in ('R', '4', 'B', 'T') else 1, ', '.join(docs), len(act), nxt, ov, pc, ZONE.get(i, 0), SPON.get(i, -1)])
hout = {'meta': {'built': dt.date.today().isoformat(), 'hud_built': H['meta'].get('built'), 'properties': len(hrows),
                 'unlocated_left_out': len(H['P']) - len(hrows),
                 'cols': ['id', 'lat', 'lon', 'name', 'addr', 'city', 'st', 'zip', 'county', 'total units', 'assisted units', 'owner',
                          'management agent', 'approx (1 = ZIP / area centroid)', 'active contract doc types', 'active contracts',
                          'earliest current-term end', 'earliest overall expiration', 'HUD property category', 'zone (1 = 2027 QCT, 2 = 2027 DDA)',
                          'owner group (index into sp, -1 none)']},
        'sp': SP, 'P': hrows}
hdest = ROOT / 'screener' / 'hud_all.js'
hdest.write_text('window.RS_HUD=' + json.dumps(hout, separators=(',', ':'), ensure_ascii=False) + ';', encoding='utf-8')
print(f'{hdest}: {len(hrows):,} located HUD properties ({len(H["P"]) - len(hrows):,} without a location left out; {sum(1 for r in hrows if r[20] >= 0):,} in {len(SP):,} owner groups), {hdest.stat().st_size / 1e6:.1f} MB')

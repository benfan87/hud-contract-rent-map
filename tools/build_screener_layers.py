"""Build the rent screener's public map layers:
  screener/lihtc.js   one map point per LIHTC project, for the "LIHTC projects" layer
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
    rows.append([round(p[8], 5), round(p[9], 5), p[1], p[3], p[4], p[12], li_units, pl[4], cr(lr[9]), p[0], 0, ZONE.get(pi, 0)])
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
    rows.append([round(q[6], 5), round(q[7], 5), q[1], q[3], q[4], q[9], li_units, q[12], cr(credit), '', 1 if q[8] == 'C' else 0, (1 if j in zq else 0) | (2 if j in zd else 0)])
    n_only += 1
assert li == len(X['LI'])

out = {'meta': {'built': dt.date.today().isoformat(), 'hud_built': H['meta'].get('built'), 'lihtc_built': X['meta'].get('built'),
                'on_hud': n_hud, 'lihtc_only': n_only, 'lihtc_only_unlocated': n_noloc,
                'cols': ['lat', 'lon', 'name', 'city', 'st', 'units', 'liUnits', 'pis', 'credit (index into cr, -1 none)', 'hud property id ("" = LIHTC only)', 'approx (ZIP centroid)', 'zone (1 = 2027 QCT, 2 = 2027 DDA)']},
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

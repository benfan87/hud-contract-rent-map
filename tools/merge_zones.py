"""Add 2027 QCT/DDA flags (tools/build_qct_dda.py output) to assets/hud_data.js as H.Z = [[property index, in_qct, in_dda], ...].
Usage: python tools/merge_zones.py <property_qct_dda_YYYY.json> --year YYYY"""
import argparse, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "hud_data.js"
ap = argparse.ArgumentParser(); ap.add_argument("flags"); ap.add_argument("--year", required=True); a = ap.parse_args()
z = json.load(open(a.flags, encoding="utf-8"))
s = DATA.read_text(encoding="utf-8"); d = json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))
pidx = {p[0]: i for i, p in enumerate(d["P"])}
d["Z"] = [[pidx[k], v[0], v[1]] for k, v in z.items() if k in pidx]
q, dd = sum(r[1] for r in d["Z"]), sum(r[2] for r in d["Z"])
d["meta"]["zones"] = {"year": a.year, "tagged": len(d["Z"]), "qct": q, "dda": dd, "note":
    f"{a.year} Qualified Census Tracts and Difficult Development Areas from HUD (Federal Register 2026-20390, effective {a.year}-01-01), "
    f"with Census 2020 tract, ZCTA and county boundaries. {len(d['Z']):,} located properties tagged: {q:,} in a QCT, {dd:,} in a DDA. "
    "Properties placed at a ZIP centroid (approximate location) may be tagged wrongly. The map layer is simplified (~400 m) for speed; "
    "the property tags use full boundaries."}
DATA.write_text("window.HUD_DATA=" + json.dumps(d, separators=(",", ":"), ensure_ascii=False) + ";", encoding="utf-8")
print(d["meta"]["zones"]["tagged"], q, dd)

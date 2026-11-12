#!/usr/bin/env python
"""Build HUD QCT / DDA overlay data for the map.

Usage:  python -I -X utf8 tools/build_qct_dda.py [YEAR] [--geo-dir DIR] [--target-mb 4]

Requires: shapely>=2.1 (coverage_simplify), pyshp, openpyxl.

Inputs (downloaded into --geo-dir, default ../hud_src/geo next to the repo):
  HUD  https://www.huduser.gov/portal/datasets/qct/QCT{YEAR}CSV.zip        (QCT tract list, 2020 tracts)
  HUD  https://www.huduser.gov/portal/datasets/qct/{YEAR}-DDAs-Data-Used-to-Designate.xlsx
       (sheet "{YEAR} MDDA" = metro Small Area DDAs by 2020 ZCTA; "{YEAR} NMDDA" = non-metro counties)
  Census cartographic boundary files (2020, 1:500k): tract, ZCTA, county
Outputs:
  assets/qct_dda_{YEAR}.js                      window.QCT_DDA_{YEAR}={meta,qct,dda};
  <geo-dir>/property_qct_dda_{YEAR}.json        {propertyId:[in_qct,in_dda,tractGEOID]}
Property points come from assets/hud_data.js (HUD_DATA.P: 0=id, 8=lat, 9=lon, 10=location code).
Point-in-polygon runs on the UNSIMPLIFIED Census boundaries.
"""
import argparse, csv, datetime, io, json, os, urllib.request, zipfile

import numpy as np
import openpyxl
import shapefile
import shapely
from shapely import STRtree
from shapely.geometry import shape, mapping

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
HUD = "https://www.huduser.gov/portal/datasets/qct/"
CB = "https://www2.census.gov/geo/tiger/GENZ2020/shp/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return
    print("downloading", url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)


def read_shp(zpath, key):
    """Return {attr value: shapely geom} for a Census cartographic zip."""
    base = os.path.basename(zpath)[:-4]
    z = zipfile.ZipFile(zpath)
    rd = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")),
                          shx=io.BytesIO(z.read(base + ".shx")))
    out = {}
    for sr in rd.iterShapeRecords():
        out[sr.record.as_dict()[key]] = shape(sr.shape.__geo_interface__)
    return out


def rnd_coords(c, nd):
    if isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [rnd_coords(x, nd) for x in c]


def clean_poly(coords, nd):
    """Round rings, drop consecutive dupes and degenerate rings."""
    rings = []
    for i, ring in enumerate(coords):
        r = []
        for p in rnd_coords(ring, nd):
            if not r or r[-1] != p:
                r.append(p)
        if len(r) >= 4 and r[0] == r[-1]:
            rings.append(r)
        elif i == 0:
            return None
    return rings


def to_geom(g, nd):
    m = mapping(g)
    if m["type"] == "Polygon":
        p = clean_poly(m["coordinates"], nd)
        return {"type": "Polygon", "coordinates": p} if p else None
    ps = [clean_poly(p, nd) for p in m["coordinates"]]
    ps = [p for p in ps if p]
    if not ps:
        return None
    return {"type": "MultiPolygon", "coordinates": ps}


def simplify_fc(items, tol, nd, groups=None):
    """items: list of (props, geom). Topology-preserving coverage simplification."""
    geoms = np.array([g for _, g in items], dtype=object)
    sg = np.empty(len(items), dtype=object)
    groups = groups or [0] * len(items)  # simplify each group as its own coverage, tolerance scaled by group factor
    for gi in sorted(set(groups)):
        idx = [i for i, x in enumerate(groups) if x == gi]
        sg[idx] = shapely.coverage_simplify(geoms[idx], tol * (1 if gi == 0 else 3), simplify_boundary=True)
    feats = []
    for (props, _), g in zip(items, sg):
        gg = to_geom(g, nd) if g is not None and not g.is_empty else None
        if gg:
            feats.append({"type": "Feature", "properties": props, "geometry": gg})
    return {"type": "FeatureCollection", "features": feats}


def csimp(geoms, tol, nd):
    """Coverage-simplify, then snap to the output grid so shared edges stay identical."""
    sg = shapely.coverage_simplify(np.array(geoms, dtype=object), tol, simplify_boundary=True)
    return shapely.set_precision(sg, 10 ** -nd)


def dissolve_fc(items, tol, nd, groups=None, key=None, idkey="ids"):
    """Dissolve adjacent polygons. items: [(props, geom)] where props["id"] is the member id.
    key=None -> one feature per contiguous cluster (props: n, ids); else one per key(props) (props from first + ids)."""
    sg = csimp([g for _, g in items], tol, nd)
    feats = []
    sg = np.array([g if (g is not None and not g.is_empty) else None for g in sg], dtype=object)
    if key is None:
        parts = [p for g in [shapely.union_all([g for g in sg if g is not None])] for p in (g.geoms if hasattr(g, "geoms") else [g])]
        ptree = STRtree(parts)
        members = [[] for _ in parts]
        reps = [g.point_on_surface() if g is not None else None for g in sg]
        for (props, _), pt, g in zip(items, reps, sg):
            if pt is None or pt.is_empty:  # sliver tract vanished in simplification
                continue
            j = ptree.query(pt, predicate="intersects")
            if len(j) == 0:
                j = [ptree.nearest(pt)]
            members[int(j[0])].append(props["id"])
        for part, ids in zip(parts, members):
            gg = to_geom(part, nd)
            if gg and ids:
                feats.append({"type": "Feature", "properties": {"n": len(ids), idkey: ids}, "geometry": gg})
    else:
        bykey = {}
        for (props, _), g in zip(items, sg):
            if g is None:
                continue
            bykey.setdefault(key(props), []).append((props, g))
        for k, mem in bykey.items():
            u = shapely.union_all([g for _, g in mem])
            gg = to_geom(u, nd)
            if gg:
                pr = {k2: v for k2, v in mem[0][0].items() if k2 != "id"}
                pr[idkey] = [m[0]["id"] for m in mem]
                feats.append({"type": "Feature", "properties": pr, "geometry": gg})
    return {"type": "FeatureCollection", "features": feats}


def dumps(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", nargs="?", default="2027")
    ap.add_argument("--geo-dir", default=os.path.join(os.path.dirname(ROOT), "hud_src", "geo"))
    ap.add_argument("--no-dissolve", action="store_true", help="keep one polygon per tract/ZCTA (much larger)")
    ap.add_argument("--target-mb", type=float, default=4.0)
    a = ap.parse_args()
    Y, G = a.year, a.geo_dir
    os.makedirs(G, exist_ok=True)
    today = datetime.date.today().isoformat()

    srcs = {
        "qct_csv": (HUD + f"QCT{Y}CSV.zip", f"QCT{Y}CSV.zip"),
        "dda_xlsx": (HUD + f"{Y}-DDAs-Data-Used-to-Designate.xlsx", f"{Y}-DDAs-Data-Used-to-Designate.xlsx"),
        "tract": (CB + "cb_2020_us_tract_500k.zip", "cb_2020_us_tract_500k.zip"),
        "zcta": (CB + "cb_2020_us_zcta520_500k.zip", "cb_2020_us_zcta520_500k.zip"),
        "county": (CB + "cb_2020_us_county_500k.zip", "cb_2020_us_county_500k.zip"),
        # Connecticut: HUD (2022+ ACS vintage) uses the new planning-region county codes (09110..09190)
        "ct_tract": ("https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_09_tract_500k.zip", "cb_2022_09_tract_500k.zip"),
        "ct_county": ("https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip", "cb_2023_us_county_500k.zip"),
        # tract-level HUD workbook: used only to expand the Puerto Rico non-metro area into municipios
        "qct_xlsx": (HUD + f"qct_data_{Y}.xlsx", f"qct_data_{Y}.xlsx"),
    }
    for u, f in srcs.values():
        fetch(u, os.path.join(G, f))
    P = lambda k: os.path.join(G, srcs[k][1])

    # --- HUD lists ---
    z = zipfile.ZipFile(P("qct_csv"))
    nm = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
    qct_ids = sorted({r["fips"] for r in csv.DictReader(io.StringIO(z.read(nm).decode("latin1")))})
    print("QCT tracts:", len(qct_ids))

    wb = openpyxl.load_workbook(P("dda_xlsx"), read_only=True)
    zc = {}  # zcta -> set of HUD area names
    for r in list(wb[f"{Y} MDDA"].iter_rows(values_only=True))[1:]:
        if r[-1] == 1:
            zc.setdefault(str(int(r[0])).zfill(5), set()).add(str(r[2]))
    nmc = {}  # county fips -> name
    for r in list(wb[f"{Y} NMDDA"].iter_rows(values_only=True))[1:]:
        if r[-1] == 1:
            nmc[str(r[0]).zfill(5)] = str(r[2])
    n_nm_areas = len(nmc)
    print("SDDA ZCTAs:", len(zc), " non-metro DDA counties:", len(nmc))

    # --- Census geometry (unsimplified) ---
    tracts = read_shp(P("tract"), "GEOID")
    zctas = read_shp(P("zcta"), "ZCTA5CE20")
    counties = read_shp(P("county"), "GEOID")
    # Connecticut: swap in planning-region geography so HUD GEOIDs match
    tracts = {k: v for k, v in tracts.items() if not k.startswith("09")}
    tracts.update(read_shp(P("ct_tract"), "GEOID"))
    counties = {k: v for k, v in counties.items() if not k.startswith("09")}
    counties.update({k: v for k, v in read_shp(P("ct_county"), "GEOID").items() if k.startswith("09")})
    # Puerto Rico "HUD Nonmetro Area" (72923) -> non-metro municipios (tract metro flag == 0)
    if "72923" in nmc:
        nm_name = nmc.pop("72923")
        wbq = openpyxl.load_workbook(P("qct_xlsx"), read_only=True)
        for ws in wbq:
            it = ws.iter_rows(values_only=True)
            h = next(it)
            if "stcnty" not in h:
                continue
            ci, mi = h.index("stcnty"), h.index("metro")
            for r in it:
                if str(r[ci]).startswith("72") and r[mi] == 0:
                    nmc[str(r[ci]).zfill(5)] = nm_name
    miss = [t for t in qct_ids if t not in tracts]
    print("QCT tracts missing geometry:", len(miss), miss[:5])
    zmiss = [z_ for z_ in zc if z_ not in zctas]
    cmiss = [c for c in nmc if c not in counties]
    print("SDDA ZCTAs missing geometry:", len(zmiss), zmiss[:5], " NM counties missing:", len(cmiss), cmiss[:5])

    # --- property tagging ---
    hp = os.path.join(ROOT, "assets", "hud_data.js")
    s = open(hp, encoding="utf8").read()
    props = json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))["P"]
    del s
    rows = [(r[0], r[8], r[9], r[10]) for r in props if r[8] is not None and r[9] is not None]
    pts = shapely.points(np.array([[r[2], r[1]] for r in rows]))
    tkeys = list(tracts)
    ttree = STRtree([tracts[k] for k in tkeys])
    pi, ti = ttree.query(pts, predicate="intersects")
    tract_of = {}
    for i, j in zip(pi, ti):
        tract_of.setdefault(int(i), tkeys[j])
    nearest_used = 0
    for i in range(len(rows)):
        if i not in tract_of:
            j = ttree.nearest(pts[i])
            if shapely.distance(pts[i], tracts[tkeys[j]]) <= 0.01:  # ~1 km: shoreline/cartographic-clip gaps
                tract_of[i] = tkeys[j]
                nearest_used += 1
    zkeys = list(zctas)
    ztree = STRtree([zctas[k] for k in zkeys])
    zi, zj = ztree.query(pts, predicate="intersects")
    zcta_of = {}
    for i, j in zip(zi, zj):
        zcta_of.setdefault(int(i), set()).add(zkeys[j])
    zfallback = 0
    for i in range(len(rows)):
        if i not in zcta_of:
            j = ztree.nearest(pts[i])
            if shapely.distance(pts[i], zctas[zkeys[j]]) <= 0.01:
                zcta_of[i] = {zkeys[j]}
                zfallback += 1
    qset, zset, out = set(qct_ids), set(zc), {}
    n_q = n_d = n_any = ap_q = ap_d = ap_any = ap_all = notract = 0
    for i, (pid, la, lo, loc) in enumerate(rows):
        t = tract_of.get(i, "")
        iq = 1 if t in qset else 0
        idd = 1 if (t[:5] in nmc or (zcta_of.get(i, set()) & zset)) else 0
        out[str(pid)] = [iq, idd, t]
        notract += (t == "")
        n_q += iq; n_d += idd; n_any += (iq or idd)
        if loc == "C":
            ap_all += 1; ap_q += iq; ap_d += idd; ap_any += (iq or idd)
    json.dump(out, open(os.path.join(G, f"property_qct_dda_{Y}.json"), "w"), separators=(",", ":"))
    print(f"properties with coords {len(rows)}; no tract {notract} (nearest-fallback used {nearest_used}, zcta fallback {zfallback})")
    print(f"in QCT {n_q} (approx {ap_q}); in DDA {n_d} (approx {ap_d}); either {n_any} (approx {ap_any}); all approx-located {ap_all}")

    # --- simplified overlay ---
    q_items = [({"id": t}, tracts[t]) for t in qct_ids if t in tracts]
    d_items = [({"id": k, "name": "; ".join(sorted(zc[k])), "type": "metro"}, zctas[k]) for k in sorted(zc) if k in zctas]
    d_items += [({"id": k, "name": nmc[k], "type": "nonmetro"}, counties[k]) for k in sorted(nmc) if k in counties]
    meta = {
        "year": int(Y), "effective": f"{Y}-01-01", "generated": today,
        "counts": {"qct_tracts": len(qct_ids), "sdda_zctas": len(zc), "nonmetro_dda_areas": n_nm_areas},
        "sources": [
            {"name": f"HUD {Y} QCT list (QCT{Y}CSV.zip)", "url": srcs["qct_csv"][0], "retrieved": today},
            {"name": f"HUD {Y} DDAs data used to designate", "url": srcs["dda_xlsx"][0], "retrieved": today},
            {"name": "Federal Register 2026-20390, published 2026-10-06 (designation notice)",
             "url": "https://www.federalregister.gov/documents/2026/10/06/2026-20390/statutorily-mandated-designation-of-difficult-development-areas-and-qualified-census-tracts-for-2027"},
            {"name": "Census 2020 cartographic boundary tracts/ZCTAs/counties, 1:500k", "url": CB, "retrieved": today},
        ],
        "notes": "QCTs use 2020 census tracts. Metro DDAs = Small Area DDAs by 2020 ZCTA; non-metro DDAs = whole non-metropolitan counties. Geometry simplified for display.",
    }
    budget = a.target_mb * 1e6
    for tol, nd in [(0.0005, 5), (0.001, 5), (0.0015, 5), (0.002, 5), (0.002, 4), (0.003, 4), (0.004, 4), (0.005, 4)]:
        if a.no_dissolve:
            qfc = simplify_fc(q_items, tol, nd)
            dfc = simplify_fc(d_items, tol, nd, [0 if i[0]["type"] == "metro" else 1 for i in d_items])
        else:
            qfc = dissolve_fc(q_items, tol, nd)  # contiguous QCT clusters; props n + ids (tract GEOIDs)
            dm = dissolve_fc([i for i in d_items if i[0]["type"] == "metro"], tol, nd, key=lambda p: p["name"], idkey="zctas")
            dn = simplify_fc([i for i in d_items if i[0]["type"] == "nonmetro"], tol * 3, nd)
            dfc = {"type": "FeatureCollection", "features": dm["features"] + dn["features"]}
        meta["simplify_tolerance_deg"], meta["simplify_decimals"] = tol, nd
        txt = f"window.QCT_DDA_{Y}=" + dumps({"meta": meta, "qct": qfc, "dda": dfc}) + ";\n"
        size = len(txt.encode("utf8"))
        print(f"tol {tol} dec {nd}: {size/1e6:.2f} MB")
        if size <= budget:
            break
    open(os.path.join(ROOT, "assets", f"qct_dda_{Y}.js"), "w", encoding="utf8").write(txt)
    print("wrote", len(qfc["features"]), "qct features,", len(dfc["features"]), "dda features,", f"{size/1e6:.2f} MB")


if __name__ == "__main__":
    main()

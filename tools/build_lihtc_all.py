"""Build assets/lihtc_all.js: every LIHTC project that isn't already attached to a HUD property, for the
full ("?all") version of the site.

Inputs (same files as the LIHTC match step):
  <hud_lihtc.json>   tools/fetch_lihtc_hud.py output (HUD LIHTC database, all records)
  <state.json> ...   tools/parse_az_lihtc.py-style state award lists (optional, any number)
  <matches.json>     tools/match_lihtc.py output; records it links to a HUD property at high/medium confidence
                     are already on the site and are left out here
Rules:
  - Records left over are grouped into projects: same street number + street + ZIP, the same name in the same
    ZIP, or within 60 m with a similar name. Resyndications and renamed rounds at one address become one project.
  - Location: the LIHTC record's own coordinates (HUD's geocode); otherwise the Census ZIP (ZCTA) centroid,
    flagged approximate; otherwise none.
  - Year 15 / resyndication: the same rules as tools/merge_lihtc.py.
  - 2027 QCT/DDA: the same point-in-polygon test as tools/build_qct_dda.py.
  - A project whose only HUD link is a "possible" (low) match keeps that HUD property as a possible duplicate.
Usage: python tools/build_lihtc_all.py <hud_lihtc.json> [<state.json> ...] <matches.json> [--year 2027] [--geo-dir DIR]
"""
import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from match_lihtc import addr_key, dist_m, name_key, sim, year  # noqa: E402
from merge_lihtc import HUD_CREDIT, HUD_TYPE  # noqa: E402

HUD_PAGE = "https://hudgis-hud.opendata.arcgis.com/maps/HUD::low-income-housing-tax-credit-properties-1/about"
LI_COLS = ["project", "addr", "city", "st", "zip", "id", "hudId", "alloc", "pis", "credit", "bond", "type", "units",
           "liUnits", "src", "company"]
# E row: [flags, possible HUD duplicate property id, note]
FLAG_BITS = {"nonprofit": 1, "rd515": 2, "home": 4, "fha": 8, "hudmf": 16, "ra_fed": 32, "ra_state": 64, "bond": 128,
             "nonprog": 256}
SMALL = {"OF", "AT", "THE", "AND", "ON", "IN", "BY", "FOR"}
ROMAN = re.compile(r"^(I{1,3}|IV|V|VI{0,3}|IX|X|LP|LLC|II|USA|YWCA|YMCA|HUD|CDC|VOA)$")


def title(s):
    if not s or not s.isupper():
        return s
    out = []
    for i, w in enumerate(s.split()):
        if ROMAN.match(w) or re.match(r"^\d", w) or re.match(r"^[A-Z]\.?$", w) and len(w) == 1:
            out.append(w)
        elif i and w in SMALL:
            out.append(w.lower())
        else:
            out.append(w[0] + w[1:].lower() if "-" not in w else "-".join(x[:1] + x[1:].lower() for x in w.split("-")))
    t = " ".join(out)
    return re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), t)


def yn(v):
    return v in ("1", 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--year", default="2027")
    ap.add_argument("--geo-dir", default=os.path.join(os.path.dirname(ROOT), "hud_src", "geo"))
    a = ap.parse_args()
    *srcs, mfile = a.files

    rows, sources = [], []
    for f in srcs:
        d = json.load(open(f, encoding="utf-8"))
        label = None
        for r in d["rows"]:
            r.setdefault("_src", f"HUD LIHTC Database (HUD eGIS layer, fetched {d['fetched']})")
            r.setdefault("_url", HUD_PAGE)
            label = r["_src"]
            rows.append(r)
        sources.append({"file": pathlib.Path(f).name, "source": d["source"], "fetched": d["fetched"], "label": label})
    mt = json.load(open(mfile, encoding="utf-8"))
    linked, possible = set(), {}
    for pid, ms in mt["matches"].items():
        for m in ms:
            k = (m["source"], m["hud_id"], m["state_id"], m["project"], m["addr"])
            if m["tier"] in ("high", "medium"):
                linked.add(k)
            else:
                possible.setdefault(k, (pid, m["why"]))
    key = lambda r: (r["_src"], r["HUD_ID"], r["STATE_ID"], r["PROJECT"], r["PROJ_ADD"])
    left = [r for r in rows if key(r) not in linked]
    print(f"{len(rows)} LIHTC records; {len(rows) - len(left)} already on HUD properties; {len(left)} to add")

    # ---- group records into projects (union-find) ----
    par = list(range(len(left)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            par[max(ri, rj)] = min(ri, rj)

    info = []
    for r in left:
        zip5 = (r.get("STD_ZIP5") or r.get("PROJ_ZIP") or "")[:5]
        num, street = addr_key(r.get("STD_ADDR") or r.get("PROJ_ADD"))
        info.append((zip5, num, street, name_key(r.get("PROJECT"))))
    by_addr, by_name, grid = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for i, (z, num, street, nk) in enumerate(info):
        if num and z:
            by_addr[(z, num)].append(i)
        if nk and z:
            by_name[(z, frozenset(nk))].append(i)
        r = left[i]
        if r.get("LAT") and r.get("LON"):
            grid[(int(r["LAT"] * 200), int(r["LON"] * 200))].append(i)
    for ids in by_addr.values():
        for x in ids[1:]:
            for y in ids[:ids.index(x)]:
                if sim(info[x][2], info[y][2]) >= 0.5:
                    union(x, y)
    for ids in by_name.values():
        for x in ids[1:]:
            union(ids[0], x)
    for (gy, gx), ids in grid.items():
        near = [j for dy in (-1, 0, 1) for dx in (-1, 0, 1) for j in grid.get((gy + dy, gx + dx), ())]
        for i in ids:
            ri = left[i]
            for j in near:
                if j < i and sim(info[i][3], info[j][3]) >= 0.5 and \
                        dist_m(ri["LAT"], ri["LON"], left[j]["LAT"], left[j]["LON"]) <= 60:
                    union(i, j)
    groups = collections.defaultdict(list)
    for i in range(len(left)):
        groups[find(i)].append(i)
    print(f"{len(groups)} projects")

    # ---- ZIP (ZCTA) centroids and 2027 QCT/DDA ----
    import shapely
    from build_qct_dda import load_inputs, tag_points
    Z = load_inputs(a.year, a.geo_dir)
    zcent = {}
    for z, g in Z["zctas"].items():
        p = g.point_on_surface()
        zcent[z] = (round(p.y, 6), round(p.x, 6))

    lsrc = []

    def src_i(r):
        t = (r["_src"], r["_url"])
        if t not in lsrc:
            lsrc.append(t)
        return lsrc.index(t)

    P, LI, PL, E, ids_seen = [], [], [], [], set()
    n_loc = collections.Counter()
    for gi, members in enumerate(groups.values()):
        recs = [left[i] for i in members]
        recs.sort(key=lambda r: (year(r["YR_ALLOC"]) or (year(r["YR_PIS"]) or 0) - 1, year(r["YR_PIS"]) or 0))
        hud = [r for r in recs if r["_src"].startswith("HUD")]
        lead = (hud or recs)[-1]
        pid = lead["HUD_ID"] if lead.get("HUD_ID") else f"{lead['PROJ_ST']}-LIHTC-{lead['STATE_ID'] or gi}"
        while pid in ids_seen:
            pid += "+"
        ids_seen.add(pid)
        pts = [(r["LAT"], r["LON"]) for r in recs if r.get("LAT") and r.get("LON")]
        zip5 = next(((r.get("STD_ZIP5") or r.get("PROJ_ZIP") or "")[:5] for r in reversed(recs) if (r.get("STD_ZIP5") or r.get("PROJ_ZIP"))), "")
        if pts:
            lat, lon, loc = round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6), "L"
        elif zip5 in zcent:
            (lat, lon), loc = zcent[zip5], "C"
        else:
            lat = lon = loc = None
        n_loc[loc] += 1
        units = max([r["N_UNITS"] or 0 for r in recs]) or None
        p_i = len(P)
        P.append([pid, title(lead["PROJECT"]), lead["PROJ_ADD"], title(lead["PROJ_CTY"]) if lead["PROJ_CTY"] else None,
                  lead["PROJ_ST"], zip5 or None, None, None, lat, lon, loc, -1, units, None, -1, None, None, -1, -1, None])
        links, flags = [], 0
        for r in recs:
            h = r["_src"].startswith("HUD")
            bond = r["BOND"]
            links.append([len(LI), 0, "LIHTC-only project (no HUD Section 8 / multifamily property match)"])
            LI.append([title(r["PROJECT"]), r["PROJ_ADD"], title(r["PROJ_CTY"]) if r["PROJ_CTY"] else r["PROJ_CTY"], r["PROJ_ST"],
                       (r.get("PROJ_ZIP") or "")[:5], r["STATE_ID"] or r["HUD_ID"], r["HUD_ID"], year(r["YR_ALLOC"]),
                       year(r["YR_PIS"]), HUD_CREDIT.get(r["CREDIT"], r["CREDIT"]) if h else r["CREDIT"],
                       1 if bond in ("1", 1) else 0 if bond in ("2", 2) else None,
                       HUD_TYPE.get(r["TYPE"], r["TYPE"]) if h else (r["TYPE"] or None), r["N_UNITS"], r["LI_UNITS"],
                       src_i(r), r["COMPANY"] or None])
            flags |= (FLAG_BITS["nonprofit"] * yn(r.get("NON_PROF"))) | (FLAG_BITS["rd515"] * yn(r.get("FMHA_515"))) \
                | (FLAG_BITS["home"] * yn(r.get("HOME"))) | (FLAG_BITS["fha"] * yn(r.get("FHA"))) \
                | (FLAG_BITS["hudmf"] * yn(r.get("MFF_RA"))) | (FLAG_BITS["bond"] * yn(bond)) \
                | (FLAG_BITS["nonprog"] * yn(r.get("NONPROG")))
            ra = r.get("RENTASSIST")
            if ra in ("1", "3"):
                flags |= FLAG_BITS["ra_fed"]
            if ra in ("2", "3"):
                flags |= FLAG_BITS["ra_state"]
        allocs = sorted({LI[i][7] for i, _, _ in links if LI[i][7]})
        piss = sorted({LI[i][8] for i, _, _ in links if LI[i][8]})
        last_a, last_p = (allocs[-1] if allocs else None), (piss[-1] if piss else None)
        if last_p and (last_a is None or last_a <= last_p + 1):
            y15, est = last_p + 14, 0
        elif last_a:
            y15, est = last_a + 16, 1
        else:
            y15, est = None, 0
        years = sorted(set(allocs) | {y - 1 for y in piss})
        resynd = None
        for x, y in zip(years, years[1:]):
            if y - x >= 5:
                resynd = y
        PL.append([p_i, links, 0, last_a, last_p, y15, est, resynd, years[0] if years else None])
        dup = next((possible[key(r)] for r in recs if key(r) in possible), None)
        E.append([flags, dup[0] if dup else None, dup[1] if dup else None])

    pts = [(i, p[8], p[9], p[10]) for i, p in enumerate(P) if p[8] is not None]
    tags, st = tag_points(pts, Z)
    ZR = [[i, v[0], v[1]] for i, v in tags.items()]
    print("QCT/DDA tagging:", st)

    # ---- compact file format (see meta.format; assets/app.js expands it) ----
    CR, TY = [], []

    def code(tab, v):
        if v is None:
            return None
        if v not in tab:
            tab.append(v)
        return tab.index(v)

    PC, LC = [], []
    for j, (p, pl) in enumerate(zip(P, PL)):
        assert pl[0] == j and [x[0] for x in pl[1]] == list(range(len(LC), len(LC) + len(pl[1])))
        for li, _, _ in pl[1]:
            r = LI[li]
            LC.append([None if r[0] == p[1] else r[0], None if r[1] == p[2] else r[1], None if r[2] == p[3] else r[2],
                       None if r[3] == p[4] else r[3], None if r[4] == p[5] else r[4], r[5], None if r[6] == r[5] else r[6],
                       r[7], r[8], code(CR, r[9]), r[10], code(TY, r[11]), r[12], r[13], r[14], r[15]])
        PC.append([p[0], p[1], p[2], p[3], p[4], p[5], p[8], p[9], p[10], p[12], len(pl[1])] + pl[3:])
    zq = sorted(int(i) for i, v in tags.items() if v[0])
    zd = sorted(int(i) for i, v in tags.items() if v[1])
    meta = {"built": dt.date.today().isoformat(), "zones_year": int(a.year),
            "sources": [{k: v for k, v in s.items() if k != "label"} for s in sources],
            "records_total": len(rows), "records_on_hud_properties": len(rows) - len(left), "records_added": len(left),
            "projects": len(P), "located_lihtc": n_loc["L"], "located_zip": n_loc["C"], "no_location": n_loc[None],
            "possible_hud_duplicates": sum(1 for e in E if e[1]), "flag_bits": FLAG_BITS,
            "format": {"P": "id, name, addr, city, st, zip, lat, lon, loc (L = LIHTC geocode, C = ZIP centroid, null = none), "
                            "units, nRecords, lastAlloc, lastPis, y15, y15est, resynd, firstYear; records are LI rows in order",
                       "LI": LI_COLS[:5] + ["id", "hudId (null = same as id)", "alloc", "pis", "credit (index into cr)",
                                            "bond", "type (index into ty)", "units", "liUnits", "src (index into lsrc)",
                                            "company"] + ["(project/addr/city/st/zip null = same as the project)"],
                       "zq/zd": "P indexes in a 2027 QCT / DDA (every located project was tested)",
                       "F": "flag bits per P row (flag_bits)", "dup": "[P index, possible HUD duplicate property id, why]"},
            "rules": __doc__.split("Usage:")[0].strip()}
    out = {"meta": meta, "lsrc": lsrc, "cr": CR, "ty": TY, "P": PC, "LI": LC, "zq": zq, "zd": zd,
           "F": [e[0] for e in E], "dup": [[i, e[1], e[2]] for i, e in enumerate(E) if e[1]]}
    dest = ROOT / "assets" / "lihtc_all.js"
    dest.write_text("window.LIHTC_ALL=" + json.dumps(out, separators=(",", ":"), ensure_ascii=False) + ";", encoding="utf-8")
    print({k: v for k, v in meta.items() if k not in ("rules", "format", "flag_bits", "sources")},
          f"{dest.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

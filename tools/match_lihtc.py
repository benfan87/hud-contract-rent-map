"""Match HUD LIHTC database records to the site's HUD properties.

HUD's LIHTC data has no HUD multifamily property ID, so records are matched on address, location and name:
  high    same street number + street name + ZIP (names not unrelated), or within 100 m with a similar name
  medium  same address under a different name, within 250 m with a similar name, or same name in the same ZIP
  low     within 100 m on the same street, names differ (shown as "possible", needs checking)
Usage: python tools/match_lihtc.py <source.json> [<source.json> ...] <out_matches.json>
  Sources: tools/fetch_lihtc_hud.py output, tools/parse_az_lihtc.py output (same row shape).
"""
import collections
import json
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
STOP = {"APARTMENTS", "APARTMENT", "APTS", "APT", "THE", "AT", "OF", "HOMES", "HOUSING", "VILLAGE", "MANOR",
        "TOWERS", "TOWER", "PLAZA", "COURT", "CT", "ESTATES", "SENIOR", "SENIORS", "II", "III", "IV", "I", "PHASE",
        "LP", "LLC", "INC", "AND", "&", "RESIDENCES", "PLACE", "GARDENS", "HOUSE"}
ABBR = {"STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "ROAD": "RD", "DRIVE": "DR", "BOULEVARD": "BLVD",
        "LANE": "LN", "PLACE": "PL", "COURT": "CT", "PARKWAY": "PKWY", "HIGHWAY": "HWY", "CIRCLE": "CIR",
        "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "TERRACE": "TER", "SQUARE": "SQ", "WAY": "WAY"}


def words(s):
    return re.findall(r"[A-Z0-9]+", (s or "").upper())


def name_key(s):
    return {w for w in words(s) if w not in STOP and len(w) > 1}


def addr_key(s):
    w = [ABBR.get(x, x) for x in words(s)]
    if not w or not w[0].isdigit():
        return None, frozenset(x for x in w if x not in {"N", "S", "E", "W"})
    return w[0], frozenset(x for x in w[1:] if x not in {"N", "S", "E", "W", "ST", "AVE", "RD", "DR", "BLVD", "LN"})


def sim(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def dist_m(a, b, c, d):
    r = math.pi / 180
    x = (d - b) * r * math.cos((a + c) / 2 * r)
    return 6371000 * math.hypot(x, (c - a) * r)


def year(v):
    return int(v) if v and v.isdigit() and 1985 <= int(v) <= 2035 else None


def main():
    srcs, out = sys.argv[1:-1], sys.argv[-1]
    HUD_PAGE = "https://hudgis-hud.opendata.arcgis.com/maps/HUD::low-income-housing-tax-credit-properties-1/about"
    rows_in, sources = [], []
    for src in srcs:
        lih = json.load(open(src, encoding="utf-8"))
        sources.append({"file": src.replace("\\", "/").split("/")[-1], "source": lih["source"], "fetched": lih["fetched"]})
        for r in lih["rows"]:
            r.setdefault("_src", f"HUD LIHTC Database (HUD eGIS layer, fetched {lih['fetched']})")
            r.setdefault("_url", HUD_PAGE)
            rows_in.append(r)
    s = (ROOT / "assets" / "hud_data.js").read_text(encoding="utf-8")
    P = json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))["P"]

    recs = []
    for r in rows_in:
        zip5 = (r.get("STD_ZIP5") or r.get("PROJ_ZIP") or "")[:5]
        num, street = addr_key(r.get("STD_ADDR") or r.get("PROJ_ADD"))
        recs.append({"r": r, "zip": zip5, "num": num, "street": street, "name": name_key(r.get("PROJECT")),
                     "city": (r.get("STD_CITY") or r.get("PROJ_CTY") or "").upper().strip(),
                     "st": r.get("PROJ_ST")})
    grid, by_addr, by_name = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for i, x in enumerate(recs):
        r = x["r"]
        if r.get("LAT") and r.get("LON"):
            grid[(int(r["LAT"] * 100), int(r["LON"] * 100))].append(i)
        if x["num"]:
            by_addr[(x["zip"], x["num"])].append(i)
        if x["name"]:
            by_name[(x["st"], x["city"])].append(i)

    matches, tiers = {}, collections.Counter()
    for p in P:
        pid, pname, paddr, pcity, pst, pzip, lat, lon, loc = p[0], p[1], p[2], (p[3] or "").upper().strip(), p[4], p[5], p[8], p[9], p[10]
        pn, (pnum, pstreet) = name_key(pname), addr_key(paddr)
        cand = {}
        if lat is not None and loc != "C":  # ZIP-centroid placements are too rough for distance matching
            gy, gx = int(lat * 100), int(lon * 100)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for i in grid.get((gy + dy, gx + dx), ()):
                        r = recs[i]["r"]
                        dm = dist_m(lat, lon, r["LAT"], r["LON"])
                        if dm <= 250:
                            cand[i] = dm
        if pnum:
            for i in by_addr.get((pzip, pnum), ()):
                cand.setdefault(i, None)
        for i in by_name.get((pst, pcity), ()):
            if sim(pn, recs[i]["name"]) >= 0.6:
                cand.setdefault(i, None)
        out_rows = []
        for i, dm in cand.items():
            x = recs[i]
            ns = sim(pn, x["name"])
            same_addr = pnum and x["num"] == pnum and x["zip"] == pzip and sim(pstreet, x["street"]) >= 0.5
            same_street = sim(pstreet, x["street"]) >= 0.5
            if (same_addr and ns >= 0.2) or (dm is not None and dm <= 100 and ns >= 0.5):
                tier = "high"
            elif same_addr or (dm is not None and dm <= 250 and ns >= 0.5) or (ns >= 0.75 and x["zip"] == pzip):
                tier = "medium"  # same address under another name (renamed?), or same name nearby / same ZIP
            elif dm is not None and dm <= 100 and same_street:
                tier = "low"  # neighbor on the same street, names differ: possible only
            else:
                continue
            r = x["r"]
            why = [w for w, ok in (("same address", same_addr), (f"{round(dm)} m away" if dm is not None else "", dm is not None),
                                   (f"name match {ns:.0%}", ns >= 0.5), ("name differs", ns < 0.2)) if ok]
            out_rows.append({"hud_id": r["HUD_ID"], "project": r["PROJECT"], "addr": r["PROJ_ADD"], "city": r["PROJ_CTY"],
                             "st": r["PROJ_ST"], "zip": r["PROJ_ZIP"], "state_id": r["STATE_ID"],
                             "yr_alloc": year(r["YR_ALLOC"]), "yr_pis": year(r["YR_PIS"]),
                             "type": r["TYPE"], "credit": r["CREDIT"], "bond": r["BOND"], "fha": r.get("FHA"),
                             "mff_ra": r.get("MFF_RA"), "units": r["N_UNITS"], "li_units": r["LI_UNITS"],
                             "allocamt": r["ALLOCAMT"], "nonprog": r.get("NONPROG"), "company": r["COMPANY"],
                             "source": r["_src"], "url": r["_url"],
                             "tier": tier, "why": ", ".join(why)})
        if out_rows:
            out_rows.sort(key=lambda m: ({"high": 0, "medium": 1, "low": 2}[m["tier"]], -(m["yr_pis"] or 0)))
            matches[pid] = out_rows
            tiers[out_rows[0]["tier"]] += 1
    json.dump({"sources": sources, "matches": matches},
              open(out, "w", encoding="utf-8"), separators=(",", ":"))
    used = {(m["hud_id"], m["state_id"], m["project"]) for v in matches.values() for m in v if m["tier"] != "low"}
    print("properties matched (best tier):", dict(tiers), "| LIHTC records used (high/medium):", len(used), "of", len(recs))


if __name__ == "__main__":
    main()

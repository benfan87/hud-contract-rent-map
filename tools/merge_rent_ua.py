"""Refresh the site's per-bedroom rents and utility allowances from HUD's
"Contracts with Rent amt and Utility Allowance amt" workbook.

Works off the published data (assets/hud_data.js) and replaces, for every contract
in HUD's file, the reported/estimated bedroom lines with HUD's rows. Verified-document
lines are kept. Contracts not in HUD's file keep their existing lines.

Usage:
    python tools/merge_rent_ua.py [path/to/contractsrentutilityamt.xlsx] --asof YYYY-MM-DD

Source page: https://www.hud.gov/hud-partners/multifamily-preservation
Requires: openpyxl
"""
import argparse
import collections
import datetime as dt
import json
import pathlib
import urllib.request

import openpyxl

URL = "https://www.hud.gov/sites/default/files/Housing/documents/contractsrentutilityamt.xlsx"
PAGE = "https://www.hud.gov/hud-partners/multifamily-preservation"
ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "hud_data.js"
SRC_LABEL = "HUD rent/UA file"
ZERO_FLAG = "Reported zero retained; review"
FMR0_FLAG = "Rent file shows no FMR"
UNITS0_FLAG = "0 units on this rent row in HUD's file (often a prior rent tier); review"


def load_site():
    s = DATA.read_text(encoding="utf-8")
    return json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))


def load_hud(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    rows, n = [], 0
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        hdr = [str(h).strip() for h in next(it)]
        want = ["property_id", "contract_number", "assistance_bedroom_count", "assistance_unit_count",
                "contract_rent_amount", "fair_market_rent_amount", "utility_allowance_amount"]
        if hdr[:7] != want:
            raise SystemExit(f"Unexpected columns in tab {ws.title!r}: {hdr}")
        for r in it:
            if r[1] is None or r[2] is None:
                continue
            n += 1
            rows.append({"pid": str(int(r[0])), "cno": str(r[1]).strip(), "bed": int(r[2]),
                         "units": int(r[3] or 0), "rent": r[4], "fmr": r[5], "ua": r[6]})
    return rows, n


def idx(lst, val):
    if val not in lst:
        lst.append(val)
    return lst.index(val)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="?", default=str(ROOT.parent / "hud_src" / "contractsrentutilityamt.xlsx"))
    ap.add_argument("--asof", required=True, help="'as of' date HUD shows for the file, YYYY-MM-DD")
    a = ap.parse_args()
    x = pathlib.Path(a.xlsx)
    if not x.exists():
        x.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        x.write_bytes(urllib.request.urlopen(req).read())

    d = load_site()
    P, C, L, D, meta = d["P"], d["C"], d["L"], d["dict"], d["meta"]
    hud, nrows = load_hud(x)

    src = idx(D["source"], f"{SRC_LABEL} (as of {a.asof})")
    zf, ff, uf = idx(D["flag"], ZERO_FLAG), idx(D["flag"], FMR0_FLAG), idx(D["flag"], UNITS0_FLAG)
    nomatch = D["locnote"].index("No property/address match in HUD property files")

    by_con = collections.defaultdict(list)
    for r in hud:
        by_con[r["cno"]].append(r)

    pidx = {p[0]: i for i, p in enumerate(P)}
    cidx = {c[1]: i for i, c in enumerate(C)}
    new_props = new_cons = 0
    for cno, rs in by_con.items():
        if cno in cidx:
            continue
        pid = rs[0]["pid"]
        if pid not in pidx:  # rent record with no property file match: searchable, not mapped
            pidx[pid] = len(P)
            P.append([pid, "", "", "", "", "", "", "", None, None, "", nomatch, None, None, -1, "", "", -1, -1])
            new_props += 1
        cidx[cno] = len(C)
        C.append([pidx[pid], cno, -1, -1, -1, -1, -1, sum(r["units"] for r in rs)] + [None] * 5
                 + [-1, -1, None, None, None, -1, -1] + [None] * 5)
        new_cons += 1

    old_by_c = collections.defaultdict(list)
    for l in L:
        old_by_c[l[0]].append(l)

    out, replaced, before = [], 0, collections.Counter()
    hud_ci = {cidx[c] for c in by_con}
    for ci, ls in old_by_c.items():
        if ci not in hud_ci:
            out.extend(ls)
        else:
            out.extend(l for l in ls if l[6] == "V")
            before.update(l[6] for l in ls if l[6] != "V")
    for cno, rs in by_con.items():
        ci = cidx[cno]
        old = old_by_c.get(ci, [])
        if old:
            replaced += 1
        fmr_a = {l[1]: l[9] for l in old if l[9] is not None}
        bed_u = {l[1]: (l[12], l[13]) for l in old if l[13] == "A" and l[12] is not None}
        tot = collections.Counter()
        for r in rs:
            tot[r["bed"]] += r["units"]
        for r in sorted(rs, key=lambda r: (r["bed"], r["rent"] or 0, r["units"])):
            rent, ua, fmr = r["rent"], r["ua"], r["fmr"] or None
            gross = None if rent is None or ua is None else rent + ua
            q = round(gross / fmr, 3) if gross is not None and fmr else None
            flag = zf if rent == 0 else uf if r["units"] == 0 else ff if not fmr else -1
            bu, bs = bed_u.get(r["bed"], (tot[r["bed"]], "F"))
            out.append([ci, r["bed"], r["units"], rent, ua, gross, "R", src, fmr,
                        fmr_a.get(r["bed"]), q, flag, bu, bs, None, -1])

    d["L"] = out
    meta["stats"]["loc_none"] = sum(1 for p in P if not p[10])
    bc =collections.Counter(l[6] for l in out)
    meta.update({
        "built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "properties": len(P), "contracts": len(C), "lines": len(out), "basis_counts": dict(bc),
        "rent_file": {"name": "Contracts with Rent amt and Utility Allowance amt", "asof": a.asof,
                      "url": URL, "page": PAGE, "downloaded": dt.date.today().isoformat(), "rows": nrows,
                      "contracts": len(by_con), "contracts_replaced": replaced,
                      "contracts_added": new_cons, "properties_added": new_props,
                      "replaced_basis": dict(before)},
    })
    DATA.write_text("window.HUD_DATA=" + json.dumps(d, separators=(",", ":"), ensure_ascii=False) + ";",
                    encoding="utf-8")
    print(json.dumps(meta["rent_file"], indent=1), "\nbasis_counts", dict(bc))


if __name__ == "__main__":
    main()

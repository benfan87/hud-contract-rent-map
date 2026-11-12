"""Add FHA-insured loans (loan type / Section of the Act, dates, rate, balance, LIHTC & bond flags)
and ownership effective dates to assets/hud_data.js.

Inputs (HUD, all public; downloaded if missing):
  activeportfoliopropdata.xlsx       tab "All active Properties with FHA": property_id -> fha_number, SOA
      https://www.hud.gov/hud-partners/multifamily-preservation
  FHA-BF90-RM-A.xlsx                 Active MF insured mortgages, keyed by FHA project number
      https://www.hud.gov/hud-partners/multifamily-fhasl-active
  MF-Properties-with-Assistance-Sec8-Contracts1.xlsx   ownership_effective_date by property_id
      https://www.hud.gov/hud-partners/multifamily-assist-section8-database

Writes H.F (one row per property-FHA number), H.dict.soa / H.dict.lender, P[i][19] = ownership
effective date, and meta.fha. Rerunnable: replaces what a previous run added.

Usage: python tools/merge_fha.py <folder with the xlsx files> --loans-asof YYYY-MM-DD
"""
import argparse
import datetime as dt
import json
import pathlib
import urllib.request

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "hud_data.js"
FILES = {
    "portfolio": ("activeportfoliopropdata.xlsx",
                  "https://www.hud.gov/sites/default/files/Housing/documents/activeportfoliopropdata.xlsx"),
    "loans": ("FHA-BF90-RM-A.xlsx", "https://www.hud.gov/sites/default/files/Housing/documents/FHA-BF90-RM-A.xlsx"),
    "props": ("MF-Properties-with-Assistance-Sec8-Contracts1.xlsx",
              "https://www.hud.gov/sites/dfiles/Housing/documents/MF-Properties-with-Assistance-Sec8-Contracts1.xlsx"),
}
F_COLS = ["p", "fha", "soa", "soaCode", "primary", "insured", "initEnd", "finalEnd", "amt", "maturity", "rate",
          "upb", "holder", "servicer", "te", "tc", "term", "units"]


def sheet_rows(path, name_has=None):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = next(w for w in wb.worksheets if name_has is None or name_has in w.title)
    ws.reset_dimensions()  # HUD's files report a wrong sheet size
    return list(ws.iter_rows(values_only=True))


def s(v):
    return v.strip() if isinstance(v, str) else v


def day(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    v = s(v)
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def idx(lst, val):
    if val is None or val == "":
        return -1
    if val not in lst:
        lst.append(val)
    return lst.index(val)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--loans-asof", required=True, help="'Current as of' date on HUD's insured-mortgage page")
    a = ap.parse_args()
    folder = pathlib.Path(a.folder)
    for name, url in FILES.values():
        if not (folder / name).exists():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            (folder / name).write_bytes(urllib.request.urlopen(req).read())

    s_ = DATA.read_text(encoding="utf-8")
    d = json.loads(s_[s_.index("=") + 1:].rstrip().rstrip(";"))
    P, D, meta = d["P"], d["dict"], d["meta"]
    pidx = {p[0]: i for i, p in enumerate(P)}
    D["soa"], D["lender"] = [], []

    rows = sheet_rows(folder / FILES["loans"][0])
    hdr = [s(h) for h in rows[1]]
    loans = {s(r[0]): dict(zip(hdr, r)) for r in rows[2:] if r and r[0]}

    rows = sheet_rows(folder / FILES["portfolio"][0], "FHA")
    hdr = [s(h) for h in rows[0]]
    F, seen, off_site, no_loan = [], set(), 0, 0
    for r in rows[1:]:
        r = dict(zip(hdr, r))
        if not r.get("property_id"):
            continue
        pid, fha = str(int(r["property_id"])), s(r["fha_number"])
        if pid not in pidx:
            off_site += 1
            continue
        if (pid, fha) in seen:
            continue
        seen.add((pid, fha))
        ln = loans.get(fha)
        if ln is None:
            no_loan += 1
            ln = {}
        F.append([pidx[pid], fha, idx(D["soa"], s(r["soa_description_text"]) or s(ln.get("SOA CATEGORY/SUB CATEGORY"))),
                  s(r["soa_code"]) or s(ln.get("SECTION OF ACT CODE")),
                  1 if s(r["is_primary_fha_ind"]) == "Y" else 0, 1 if s(r["is_insured_ind"]) == "Y" else 0,
                  day(ln.get("INITIAL ENDORSEMENT DATE")), day(ln.get("FINAL ENDORSEMENT DATE")),
                  ln.get("ORIGINAL MORTGAGE AMOUNT"), day(ln.get("MATURITY DATE")), ln.get("INTEREST RATE"),
                  ln.get("AMORITIZED PRINCIPAL BALANCE"), idx(D["lender"], s(ln.get("HOLDER NAME"))),
                  idx(D["lender"], s(ln.get("SERVICER NAME"))), 1 if s(ln.get("TE")) else 0,
                  1 if s(ln.get("TC")) else 0, ln.get("TERM IN MONTHS"), ln.get("UNITS")])
    d["F"] = F

    rows = sheet_rows(folder / FILES["props"][0])
    hdr = [s(h) for h in rows[0]]
    own = {}
    for r in rows[1:]:
        r = dict(zip(hdr, r))
        if r.get("property_id"):
            own[str(int(r["property_id"]))] = day(r.get("ownership_effective_date"))
    for p in P:
        del p[19:]
        p.append(own.get(p[0]))

    soa223f = {i for i, v in enumerate(D["soa"]) if "223(f)" in v and "223(a)(7)" not in v}
    meta["fha"] = {
        "cols": F_COLS, "loans_asof": a.loans_asof, "downloaded": dt.date.today().isoformat(),
        "loan_page": "https://www.hud.gov/hud-partners/multifamily-fhasl-active",
        "portfolio_page": "https://www.hud.gov/hud-partners/multifamily-preservation",
        "rows": len(F), "properties": len({f[0] for f in F}), "no_active_loan_record": no_loan,
        "property_not_on_site": off_site, "owner_dates": sum(1 for p in P if p[19]),
        "props_223f": len({f[0] for f in F if f[2] in soa223f}),
    }
    DATA.write_text("window.HUD_DATA=" + json.dumps(d, separators=(",", ":"), ensure_ascii=False) + ";",
                    encoding="utf-8")
    print(json.dumps(meta["fha"], indent=1))


if __name__ == "__main__":
    main()

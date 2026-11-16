"""North Dakota Housing Finance Agency (NDHFA) LIHTC lists -> standard CSV.

Primary source: the cumulative "Master LIHTC Project Listing" (1987-present). One line per TC number:
  TC # | Year | Project Name | Applicant | Address of Applicant | Contact | Phone | Location of Project (city) |
  Project Units | LIHTC Units | Project Type | Project Status | Placed In Service | Allocated/Reserved (annual $)
  - "TC-yy-nn" = 9% competitive credit, "TE-yy-nn" = tax-exempt bond / 4% credit.
  - Rows with no allocation ("Unfunded", or "-" amount) are dropped, except projects shown with a placed-in-service
    date (e.g. a resyndication listed without an amount). "Additional Allocation" / "Forward Commitment" rows are
    separate awards to an existing TC number and are kept as their own rows (an additional allocation with no
    amount is dropped).
  - YR_ALLOC = the list's Year column (credit year; the annual round is usually held the year before).
  The text layer has overlapping glyphs in the Project Type / Status columns, so columns are cut by character x.

Secondary: the 2022-2025 "Annual Application Round - Applications Selected for Commitment" sheets (LIHTC 9 / LIHTC 4 /
HIF / HOME / HTF columns). Every LIHTC award on them is cross-checked against the master list; rows that do not match a
master-list award are added (CREDIT from the column), so nothing awarded is lost. HIF/HOME/HTF-only rows are dropped.
No project street address / ZIP in any ND file (the address column is the applicant's).
Usage: python tools/state_pdf/nd.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import urllib.request

import pdfplumber

PAGE = "https://www.ndhousing.nd.gov/development"
MASTER = "https://www.ndhousing.nd.gov/sites/default/files/documents/Development/MasterProjectList2026.pdf"
FUNDED = {y: f"https://www.ndhousing.nd.gov/sites/www/files/documents/Development/AllNDHFAFundedProjects{y}.pdf"
          for y in (2022, 2023, 2024, 2025)}  # 2020/2021 versions 404; covered by the master list
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
# master list column cuts (x of character's left edge, PDF points; stable across all 7 pages)
MCUTS = [("tc", 20), ("year", 52), ("name", 68), ("applicant", 188), ("address", 355), ("contact", 535),
         ("phone", 593), ("city", 636), ("units", 690), ("li", 725), ("type", 763), ("status", 812), ("pis", 862),
         ("amt", 905), ("_end", 990)]


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
    except Exception as e:
        print(f"SKIP {url}: {e}")
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def clean(s):
    s = (s or "").replace("�", "-").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def numval(s):
    s = re.sub(r"[^\d.]", "", s or "")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def col_text(chars, lo, hi):
    """Join chars whose x0 is in [lo, hi), inserting spaces at gaps."""
    cs = sorted((c for c in chars if lo <= c["x0"] < hi), key=lambda c: c["x0"])
    out, prev = "", None
    for c in cs:
        if prev is not None and c["x0"] - prev["x1"] > 1.2:
            out += " "
        out += c["text"]
        prev = c
    return clean(out)


def rows_by_line(chars, tol=2.5):
    lines = []
    for c in sorted(chars, key=lambda c: (c["top"], c["x0"])):
        if lines and abs(lines[-1][0] - c["top"]) <= tol:
            lines[-1][1].append(c)
        else:
            lines.append([c["top"], [c]])
    return lines


def parse_master(path):
    rows = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            for top, cs in rows_by_line(pg.chars):
                rec = {k: col_text(cs, lo, MCUTS[i + 1][1]) for i, (k, lo) in enumerate(MCUTS[:-1])}
                if not re.match(r"T[CE]-\d\d-\d+", rec["tc"]):
                    continue
                rows.append(rec)
    return rows


def parse_funded(path):
    """Annual round sheet: returns list of dicts name, applicant, city, units, l9, l4."""
    out = []
    with pdfplumber.open(path) as pdf:
        pg = pdf.pages[0]
        words = pg.extract_words()
        # header positions
        loc = next(w for w in words if w["text"] == "Location")
        units = next(w for w in words if w["text"] == "Units")
        lihtc = [w for w in words if w["text"] == "LIHTC"]
        hif = next(w for w in words if w["text"] == "HIF")
        req = next(w for w in words if w["text"] == "Request")
        setw = next(w for w in words if w["text"] == "Set")
        hdr_bottom = next(w["bottom"] for w in words if w["text"] == "Aside")
        lines = {}
        for w in words:
            if w["top"] <= hdr_bottom + 1:
                continue
            lines.setdefault(round(w["top"]), []).append(w)
        merged = []
        for t in sorted(lines):
            if merged and t - merged[-1][0] <= 3:
                merged[-1][1].extend(lines[t])
            else:
                merged.append([t, list(lines[t])])
        l9_hi = (lihtc[0]["x1"] + lihtc[1]["x0"]) / 2 + 8   # numbers are right-aligned under the header
        l4_hi = (lihtc[1]["x1"] + hif["x0"]) / 2 + 8
        for t, ws in merged:
            ws.sort(key=lambda w: w["x0"])
            txt = " ".join(w["text"] for w in ws)
            if re.match(r"(Total|Funding Remaining)", txt):
                break
            # money tokens right of Units; glue split fragments like "1 ,000,000"
            nums = []
            for w in ws:
                if not (re.fullmatch(r"[\d,.]+", w["text"]) and w["x0"] > units["x1"] + 5):
                    continue
                if nums and w["text"].startswith(",") and w["x0"] - nums[-1]["x1"] < 4:
                    nums[-1] = {"text": nums[-1]["text"] + w["text"], "x0": nums[-1]["x0"], "x1": w["x1"]}
                else:
                    nums.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"]})
            l9 = sum(numval(w["text"]) for w in nums if w["x1"] <= l9_hi)
            l4 = sum(numval(w["text"]) for w in nums if l9_hi < w["x1"] <= l4_hi)
            mid = [w for w in ws if loc["x0"] - 15 <= w["x0"] < units["x1"] + 5]
            u = " ".join(w["text"] for w in mid if re.fullmatch(r"\d+", w["text"]))
            city = " ".join(w["text"] for w in mid if not re.fullmatch(r"\d+", w["text"]))
            name = " ".join(w["text"] for w in ws if w["x0"] < req["x0"] - 2)
            appl = " ".join(w["text"] for w in ws if setw["x1"] + 3 <= w["x0"] < loc["x0"] - 15)
            out.append({"line": txt, "name": clean(name), "applicant": clean(appl), "city": clean(city),
                        "units": u, "l9": l9, "l4": l4})
    return out


# development renamed between the round sheet and the master list
ALIAS = {"Gardenette": "Riverside"}


def norm(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"\b(apartments?|apts?|the|phase|ph|townhomes|rehab)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--pdf-dir", default=None)
    a = ap.parse_args()
    pdf_dir = a.pdf_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "pdf", "nd")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    out = []
    mpath = os.path.join(pdf_dir, os.path.basename(MASTER))
    master = []
    if fetch(MASTER, mpath):
        master = parse_master(mpath)
        kept = dropped = 0
        for r in master:
            amt = numval(r["amt"])
            pis = re.search(r"\d\d/\d\d/\d{4}", r["pis"])
            unfunded = "unfunded" in r["status"].replace(" ", "").lower()
            addl = "additional" in r["status"].lower()
            if not (amt > 0 or (pis and not unfunded and not addl)):
                dropped += 1
                continue
            kept += 1
            out.append({
                "PROJECT": r["name"], "PROJ_ADD": "", "PROJ_CTY": r["city"], "PROJ_ZIP": "",
                "YR_ALLOC": r["year"], "CREDIT": "4% (bond)" if r["tc"].startswith("TE") else "9%",
                "N_UNITS": r["units"], "LI_UNITS": r["li"], "COMPANY": r["applicant"],
                "ALLOCAMT": int(amt) if amt else "", "STATE_ID": r["tc"],
                "SRC_LABEL": "North Dakota Housing Finance Agency Master LIHTC Project Listing (cumulative)",
                "SRC_URL": MASTER})
        print(f"master: {len(master)} TC lines, kept {kept}, dropped {dropped} (unfunded / no allocation)")
    funded_amts = {}
    for r in out:
        funded_amts.setdefault(int(numval(str(r["ALLOCAMT"]))), []).append(r)
    for y, url in FUNDED.items():
        p = os.path.join(pdf_dir, os.path.basename(url))
        if not fetch(url, p):
            continue
        n_l = n_match = n_unf = 0
        for f in parse_funded(p):
            for cr, amt in (("9%", f["l9"]), ("4% (bond)", f["l4"])):
                if amt <= 0:
                    continue
                n_l += 1
                amt = int(amt)
                hit = funded_amts.get(amt)
                nm = norm(ALIAS.get(f["name"].split(",")[0], f["name"].split(",")[0]) + "".join(f["name"].split(",")[1:]))
                pre = "TE" if cr.startswith("4") else "TC"
                same = [m for m in master if m["city"] == f["city"] and y - 1 <= int(m["year"]) <= y + 2 and norm(m["name"])
                        and (norm(m["name"]) in nm or nm in norm(m["name"])
                             or (m["units"] == f["units"] and m["tc"].startswith(pre)))]
                if not hit:  # same name + city in master in the round year or next credit year, any amount
                    hit = [m for m in same if numval(m["amt"]) > 0]
                if hit:
                    n_match += 1
                    continue
                if same:  # master shows this TC number as unfunded (commitment returned / not carried forward)
                    n_unf += 1
                    print(f"  {y} round: master list shows unfunded ({same[0]['tc']}) -> dropped: {f['line']}")
                    continue
                print(f"  {y} round: not in master list -> added: {f['line']}")
                out.append({
                    "PROJECT": f["name"], "PROJ_ADD": "", "PROJ_CTY": f["city"], "PROJ_ZIP": "", "YR_ALLOC": y,
                    "CREDIT": cr, "N_UNITS": f["units"], "LI_UNITS": "", "COMPANY": f["applicant"], "ALLOCAMT": amt,
                    "STATE_ID": "",
                    "SRC_LABEL": f"North Dakota Housing Finance Agency {y} annual application round - "
                                 f"applications selected for commitment", "SRC_URL": url})
        print(f"{y} round sheet: {n_l} LIHTC awards, {n_match} matched to master list, {n_unf} shown unfunded in master")
    path = os.path.join(a.out, "nd.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, COLS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows -> {path}")


if __name__ == "__main__":
    main()

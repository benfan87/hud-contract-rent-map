"""Alabama (AHFA) LIHTC award lists -> hud_src/lihtc/states/extracted/al.csv (standard columns, see README.md).

Sources (AHFA "Approved HOME/Housing Credit Applications", competitive 9% cycle, 2020-2026; 2023 is xlsx) plus the
"2025 Approved Multifamily Tax Exempt Bonds" table of AHFA's bond program status report (issued bonds with 4% credits).
Rows with no Housing Credit amount (HOME-only awards) are dropped. Pending / terminated bond applications are skipped.

Usage (from the repo root): python tools/state_pdf/al.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import sys
import urllib.error
import urllib.request

import openpyxl
import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
CDN = "https://ahfa.atl1.cdn.digitaloceanspaces.com/multifamily/allocation-and-application-info/"
# (year, url, kind)
FILES = [
    (2020, CDN + "archives/2020-home_hc_htf-funding-approvals_062520.pdf", "words"),
    (2021, CDN + "archives/2021-home_hc-approved-projects.pdf", "words"),
    (2022, CDN + "archives/publication_2022-award-list_120922.pdf", "table"),
    (2023, CDN + "archives/2023-funding-approvals.xlsx", "xlsx"),
    (2024, CDN + "2024-funded-application-list-(7-24-24).pdf", "table"),
    (2025, CDN + "2025-funded-applications-2.pdf", "table"),
    (2026, CDN + "2026-home_tc-applications-approved.pdf", "table"),
    (None, CDN + "mf-bond-program-status-report_publication-updated-9-15-26.pdf", "bond"),
]
# Unruled 2020/2021 PDFs: column left edges (x) taken from the data rows of each file.
WORD_COLS = {
    2020: [("name", 0), ("id", 120), ("addr", 160), ("city", 230), ("zip", 290), ("county", 322), ("owner", 362),
           ("units", 495), ("tenant", 528), ("ptype", 555), ("otype", 612), ("credits", 650), ("home", 710)],
    2021: [("name", 0), ("id", 110), ("addr", 150), ("city", 220), ("zip", 282), ("county", 311), ("owner", 352),
           ("units", 485), ("tenant", 517), ("ptype", 545), ("otype", 602), ("credits", 640), ("home", 700)],
}
HDR_KEYS = [("name", r"project name"), ("id", r"project (#|number)"), ("owner", r"owner (information|contact)"), ("addr", r"address"), ("city", r"city"),
            ("zip", r"zip"), ("county", r"county"), ("units", r"^(# ?(of )?)?units\b|^units:"),
            ("credits", r"housing credit"), ("home", r"^home"), ("status", r"^status"), ("date", r"issue date")]
DEFAULT_14 = ["name", "id", "addr", "city", "zip", "county", "owner", "units", "setaside", "tenant", "ptype", "otype",
              "credits", "home"]


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        print(f"  SKIP {url}: HTTP {e.code}", file=sys.stderr)
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def money(s):
    s = re.sub(r"[^\d.]", "", clean(s))
    return int(round(float(s))) if s and s != "." else None


def first_int(s):
    m = re.search(r"\d+", clean(s).replace(",", ""))
    return int(m.group()) if m else None


def clean_city(s):
    s = re.sub(r"\(.*?\)", "", clean(s)).strip()
    return "" if s.upper() in ("N/A", "NA", "NONE", "") or s.lower().startswith("unincorporated") else s


def clean_addr(s):
    s = clean(s)
    s = re.sub(r",\s*[A-Za-z .]+,?\s+AL(\s+\d{5})?,?$", "", s)  # "3200 Block of Lincoln Drive, Selma AL 36701"
    s = re.sub(r"^(approximately|approx\.?|appx\.?|~)\s*", "", s, flags=re.I)
    return s


def company(owner):
    """Owner entity = leading lines of the owner cell, up to its street / PO box line."""
    out = []
    for ln in [clean(x) for x in str(owner or "").split("\n") if clean(x)]:
        if out and re.match(r"^(\d|P\.?\s?O\.?\b|PO\b|One\s)", ln, re.I):
            break
        out.append(ln)
        if not re.search(r",$", ln):  # entity names that wrap end the first line with a comma
            break
    return " ".join(out)


def collapse_spaced(words):
    """'J a c k s o n' -> 'Jackson' (letter-spaced text in the 2021 PDF)."""
    out, run = [], []
    for w in words:
        if len(w) == 1 and w.isalpha():
            run.append(w)
            continue
        if run:
            out.append("".join(run) if len(run) > 1 else run[0])
            run = []
        out.append(w)
    if run:
        out.append("".join(run) if len(run) > 1 else run[0])
    return " ".join(out)


def parse_words(path, year):
    """2020/2021: unruled table; each record's cells are bottom-aligned on the line carrying the 7-digit project #."""
    cols = WORD_COLS[year]

    def col_of(x):
        k = cols[0][0]
        for name, x0 in cols:
            if x >= x0:
                k = name
        return k

    recs, totals = [], None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            hdr = [w for w in words if w["text"] == "Name" or w["text"] == "HOME"]
            if not hdr:
                continue
            top0 = max(w["bottom"] for w in hdr)
            words = [w for w in words if w["top"] > top0]
            for w in words:  # "20 Program Award Totals $14,650,088 $13,615,600"
                if w["text"] == "Totals":
                    line = sorted([v for v in words if abs(v["top"] - w["top"]) < 3], key=lambda v: v["x0"])
                    totals = (first_int(line[0]["text"]), [money(v["text"]) for v in line if "$" in v["text"]])
            anchors = sorted({round(w["top"], 1) for w in words
                              if re.fullmatch(r"20\d{5}", w["text"]) and col_of(w["x0"]) == "id"})
            prev = top0
            for a in anchors:
                band = [w for w in words if prev + 2 < w["top"] <= a + 2]
                prev = a + 2
                cells = {}
                for w in sorted(band, key=lambda w: (round(w["top"]), w["x0"])):
                    cells.setdefault(col_of(w["x0"]), []).append(w)
                rec = {}
                for k, ws in cells.items():
                    lines = {}
                    for w in ws:
                        lines.setdefault(round(w["top"]), []).append(w["text"])
                    rec[k] = "\n".join(collapse_spaced(lines[t]) for t in sorted(lines))
                recs.append(rec)
    return recs, totals


def parse_table(path):
    """Ruled PDFs (2022, 2024-2026): pdfplumber tables."""
    recs, totals, keys = [], None, None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables():  # header only on page 1 in some files: keys carry over
                for row in t:
                    cells = [str(c or "") for c in row]
                    flat = [clean(c).lower() for c in cells]
                    if any("project name" in c for c in flat):
                        if sum(1 for c in flat if c) >= 10:
                            keys = []
                            for c in flat:
                                k = next((k for k, rx in HDR_KEYS if c and re.search(rx, c)), None)
                                keys.append(k)
                        elif len(cells) == 14:
                            keys = DEFAULT_14
                        continue
                    if keys is None:
                        continue
                    if re.search(r"totals", " ".join(flat)):
                        totals = (None, [money(m) for m in re.findall(r"\$\s?[\d,]+", " ".join(cells))])
                        continue
                    if len(cells) != len(keys):
                        continue
                    rec = {k: c for k, c in zip(keys, cells) if k}
                    if not re.fullmatch(r"20\d{5}", clean(rec.get("id"))):
                        continue
                    recs.append(rec)
    return recs, totals


def parse_xlsx(path):
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    recs, keys = [], None
    for row in ws.iter_rows(values_only=True):
        cells = ["" if c is None else str(c) for c in row]
        flat = [clean(c).lower() for c in cells]
        if keys is None:
            if any(c == "project name" for c in flat):
                keys = [next((k for k, rx in HDR_KEYS if c and re.search(rx, c)), None) for c in flat]
            continue
        rec = {k: c for k, c in zip(keys, cells) if k}
        if re.fullmatch(r"20\d{5}", clean(rec.get("id"))):
            recs.append(rec)
    return recs, None


def bond_rows(path):
    """Bond status report: keep only the 'APPROVED MULTIFAMILY TAX EXEMPT BONDS' table (issued, with 4% credits)."""
    recs = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables():
                if not t or "APPROVED" not in clean(t[0][0]).upper():
                    continue
                keys = None
                for row in t:
                    cells = [str(c or "") for c in row]
                    flat = [clean(c).lower() for c in cells]
                    if "project name" in flat:
                        keys = [next((k for k, rx in HDR_KEYS if c and re.search(rx, c)), None) for c in flat]
                        # the bond-amount column also matches nothing; 'Housing Credits' is the last column
                        keys[-1] = "credits"
                        keys = [None if (k == "credits" and i != len(keys) - 1) else k for i, k in enumerate(keys)]
                        continue
                    if keys is None or flat[0].startswith("award totals") or not flat[0]:
                        continue
                    rec = {k: c for k, c in zip(keys, cells) if k}
                    if clean(rec.get("status")).lower() == "approved":
                        recs.append(rec)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--pdf-dir", default=None)
    a = ap.parse_args()
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pdir = a.pdf_dir or os.path.join(repo, "..", "hud_src", "lihtc", "states", "pdf", "al")
    os.makedirs(pdir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    out = []
    for year, url, kind in FILES:
        path = os.path.join(pdir, url.rsplit("/", 1)[1])
        if not fetch(url, path):
            continue
        if kind == "bond":
            for r in bond_rows(path):
                yr = re.search(r"(20\d\d)", clean(r.get("date")))
                out.append({"PROJECT": clean(r.get("name")), "PROJ_ADD": clean_addr(r.get("addr")),
                            "PROJ_CTY": clean_city(r.get("city")), "PROJ_ZIP": (re.findall(r"\d{5}", clean(r.get("zip"))) or [""])[0],
                            "YR_ALLOC": yr.group(1) if yr else "", "CREDIT": "4% (bond)", "N_UNITS": first_int(r.get("units")),
                            "LI_UNITS": "", "COMPANY": company(r.get("owner")), "ALLOCAMT": money(r.get("credits")),
                            "STATE_ID": "", "SRC_LABEL": "AHFA approved multifamily tax-exempt bonds (bond program status report 9/15/2026)",
                            "SRC_URL": url})
            print(f"  bond report: {sum(1 for o in out if o['SRC_URL'] == url)} approved bond rows")
            continue
        recs, totals = parse_words(path, year) if kind == "words" else parse_table(path) if kind == "table" else parse_xlsx(path)
        n_home_only = 0
        kept = 0
        for r in recs:
            amt = money(r.get("credits"))
            if not amt:
                n_home_only += 1
                continue
            kept += 1
            out.append({"PROJECT": clean(r.get("name")), "PROJ_ADD": clean_addr(r.get("addr")),
                        "PROJ_CTY": clean_city(r.get("city")), "PROJ_ZIP": (re.findall(r"\d{5}", clean(r.get("zip"))) or [""])[0],
                        "YR_ALLOC": str(year), "CREDIT": "9%", "N_UNITS": first_int(r.get("units")), "LI_UNITS": "",
                        "COMPANY": company(r.get("owner")), "ALLOCAMT": amt, "STATE_ID": clean(r.get("id")),
                        "SRC_LABEL": f"AHFA {year} approved HOME/Housing Credit applications", "SRC_URL": url})
        tsum = sum(money(r.get("credits")) or 0 for r in recs)
        print(f"  {year}: {len(recs)} records, {kept} with Housing Credits, {n_home_only} HOME-only dropped; "
              f"credit sum {tsum:,}; source totals {totals}")
    with open(os.path.join(a.out, "al.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for o in out:
            w.writerow({k: "" if o.get(k) is None else o.get(k) for k in COLS})
    print(f"wrote {len(out)} rows -> {os.path.join(a.out, 'al.csv')}")


if __name__ == "__main__":
    main()

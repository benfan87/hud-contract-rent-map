"""Wyoming Community Development Authority (WCDA) "Awards by Year" list (one PDF, 2017-2026) -> standard CSV.

Each award is a card, printed two (or three) cards per row:
    YEAR [Supplemental] / project name / developer (may wrap) / Tax Credit Allocation: $X / 9%, 4% or Both: X /
    HOME / NHTF / TCAP allocations / New Construction/Acq/Rehab: X / "N Units; N Buildings - Family" / bedroom mix /
    Location: street, City (may wrap) / Status: X
Column positions differ by page, so each page's card columns are found from the x of the year words. Words are read
with x/y positions (pdfplumber extract_words). No ZIP codes in the list.

Kept: award years 2020 on, with a tax credit amount > 0. Dropped (and printed): cards with no credit ($0 / None, e.g.
HOME/NHTF-only awards) and cards whose Status is Cancelled / Returned. CREDIT: "9%" / "4% (bond)" from the
"9%, 4% or Both" field; blank for "Both" (one combined amount). "Supplemental" awards are separate rows.

Usage: python tools/state_pdf/wy.py --out ../hud_src/lihtc/states/extracted   (run from the repo root)
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import urllib.request

import pdfplumber

ST = "WY"
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc", "states", "pdf", ST.lower()))
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
URL = "https://www.wyomingcda.com/wp-content/uploads/2026/05/Awards-by-Year-for-Website-5.18.26.pdf"
FILE = "wy_awards_by_year.pdf"
MIN_YEAR = 2020


def fetch(url, path):
    """Download url to path unless already there (curl / urllib with their default user agents). Returns ok."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    try:
        if shutil.which("curl"):
            code = subprocess.run(["curl", "-sL", "-o", tmp, "-w", "%{http_code}", url], capture_output=True,
                                  text=True, timeout=300).stdout.strip()
            if code != "200":
                raise IOError(f"HTTP {code}")
        else:
            with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as f:
                f.write(r.read())
        os.replace(tmp, path)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  SKIP {url}: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def lines_of(words, tol=3.0):
    out = []
    for w in sorted(words, key=lambda w: w["top"]):
        if out and abs(out[-1][0] - w["top"]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [" ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])).strip() for _, ws in out]


YEAR_LINE = re.compile(r"^((?:19|20)\d\d)(\s+Supplemental)?$")


def cards(pdf):
    """Yield each card's text lines, page by page, left column first."""
    for pg in pdf.pages:
        words = pg.extract_words(x_tolerance=1.5)
        yrs = sorted(w["x0"] for w in words if re.fullmatch(r"(19|20)\d\d", w["text"]))
        cols = []
        for x in yrs:  # cluster the year-word x positions into card columns
            if not cols or x - cols[-1] > 20:
                cols.append(x)
        if not cols:
            continue
        for i, cx in enumerate(cols):
            hi = cols[i + 1] - 5 if i + 1 < len(cols) else 1e9
            col = [w for w in words if cx - 5 <= w["x0"] < hi]
            card = []
            for s in lines_of(col):
                if YEAR_LINE.match(s):
                    if card:
                        yield card
                    card = [s]
                elif card:
                    card.append(s)
            if card:
                yield card


def field(lines, label):
    """Text after 'label' (and an optional ':' / '-' / dash) on the first line starting with it."""
    for s in lines:
        m = re.match(label + r"\s*[:\-–]?\s*(.*)$", s, re.I)
        if m:
            return m.group(1).strip()
    return None


def money(s):
    m = re.search(r"\$\s*([\d,]+)", s or "")
    return int(m.group(1).replace(",", "")) if m else 0


def parse_card(lines):
    m = YEAR_LINE.match(lines[0])
    year, supp = int(m.group(1)), bool(m.group(2))
    i_tc = next(i for i, s in enumerate(lines) if s.startswith("Tax Credit"))
    name, dev = lines[1], " ".join(lines[2:i_tc])
    amt = money(field(lines, r"Tax Credit Allocation"))
    kind = (field(lines, r"9%, 4% or Both") or "").strip()
    units = next((re.match(r"^(\d+)\s+Units?", s).group(1) for s in lines if re.match(r"^\d+\s+Units?", s)), "")
    i_loc = next(i for i, s in enumerate(lines) if s.startswith("Location"))
    i_st = next(i for i, s in enumerate(lines) if s.startswith("Status"))
    loc = " ".join(lines[i_loc:i_st])
    loc = re.sub(r"^Location\s*[:\-–]?\s*", "", loc).strip()
    status = field(lines, r"Status") or ""
    street, city = loc, ""
    if "," in loc:
        street, city = (x.strip() for x in loc.rsplit(",", 1))
    if re.match(r"^TBD\b", street, re.I):
        street = ""  # "TBD Pioneer Avenue" / "TBD Rd 8": no street number yet
    credit = {"9%": "9%", "4%": "4% (bond)"}.get(kind, "")
    return {"PROJECT": re.sub(r"\s+", " ", name), "PROJ_ADD": street, "PROJ_CTY": city, "PROJ_ZIP": "",
            "YR_ALLOC": year, "CREDIT": credit, "N_UNITS": units, "LI_UNITS": "", "COMPANY": dev,
            "ALLOCAMT": amt or "", "STATE_ID": "",
            "SRC_LABEL": f"Wyoming CDA Awards by Year ({year}{' supplemental' if supp else ''} awards, as of 5/18/2026)",
            "SRC_URL": URL}, kind, status


def parse(path):
    rows, dropped = [], []
    with pdfplumber.open(path) as pdf:
        for c in cards(pdf):
            r, kind, status = parse_card(c)
            if r["YR_ALLOC"] < MIN_YEAR:
                continue
            if not r["ALLOCAMT"] or re.match(r"(Cancel|Return)", status, re.I):
                dropped.append(f"{r['YR_ALLOC']} {r['PROJECT']} (credit {r['ALLOCAMT'] or 0}, {kind}, {status})")
                continue
            if kind not in ("9%", "4%"):
                print(f"  note: {r['YR_ALLOC']} {r['PROJECT']}: credit type '{kind}' -> CREDIT blank")
            rows.append(r)
    return rows, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc",
                                                                   "states", "extracted")))
    a = ap.parse_args()
    path = os.path.join(PDF_DIR, FILE)
    rows, dropped = parse(path) if fetch(URL, path) else ([], [])
    for d in dropped:
        print(f"  dropped: {d}")
    print(f"{FILE}: {len(rows)} rows ({sum(r['CREDIT'] == '9%' for r in rows)} 9%, "
          f"{sum(r['CREDIT'] == '4% (bond)' for r in rows)} 4%, {sum(not r['CREDIT'] for r in rows)} untyped); "
          f"dropped {len(dropped)}")
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, f"{ST.lower()}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()

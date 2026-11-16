"""Hawaii Housing Finance and Development Corp. (HHFDC) annual funding-round Awards Lists (PDF) -> standard CSV.

Page 1 of each file is the awards table (the remaining pages are 9% / 4% / RHRF criteria scores and are ignored).
Each award is a 3-line block: project name / street / "City, HI ZIP" on the left, applicant entity + address next to
it, and one line of numbers: dates, target population, affordability period, unit counts, then six money columns:
9% Volume Cap Federal (10 yr) & State (5 yr) annual credit, 4% Non-Volume Cap Federal & State, HMMF bonds, RHRF loan.
Words are read with x/y positions (pdfplumber extract_words).

CREDIT is "9%" when the 9% federal amount > 0, "4% (bond)" when the 4% federal amount > 0; ALLOCAMT = that annual
federal credit. Rows with no LIHTC at all (RHRF-only / RHRF Tier II awards) are dropped.

Usage: python tools/state_pdf/hi.py --out ../hud_src/lihtc/states/extracted   (run from the repo root)
"""
import argparse
import collections
import csv
import os
import re
import shutil
import subprocess
import urllib.request

import pdfplumber

ST = "HI"
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc", "states", "pdf", ST.lower()))
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
BASE = "https://dbedt.hawaii.gov/hhfdc/files/"
SOURCES = [  # (year, local file, url)
    (2020, "hi_2020.pdf", BASE + "2020/10/2020_Awards-List_2020-08-25.pdf"),
    (2021, "hi_2021.pdf", BASE + "2026/02/2021_Combined_awards_4_LIHTC_Scores.pdf"),
    (2022, "hi_2022.pdf", BASE + "2026/02/2022_Combined_Awards_4_LIHTC_Scores.pdf"),
    (2023, "hi_2023.pdf", BASE + "2026/02/2023_Combined_Awards_4_LIHTC_Scores.pdf"),
    (2024, "hi_2024.pdf", BASE + "2026/02/2024_Combined_Awards_4_LIHTC_Scores.pdf"),
    (2025, "hi_2025.pdf", BASE + "2026/02/2025_Combined_All_Four_Items_updated.pdf"),
]


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


def lines_of(words, tol=3.5):
    """Group words into lines by their top coordinate; each line's words sorted by x."""
    out = []
    for w in sorted(words, key=lambda w: w["top"]):
        if out and abs(out[-1][0] - w["top"]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(ws, key=lambda w: w["x0"])) for t, ws in out]


def text(ws):
    return " ".join(w["text"] for w in ws).strip()


CITY = re.compile(r"^(.*?),?\s+(?:HI|Hawaii),?\s+(\d{5})$")
MONEY = re.compile(r"^\$[\d,]+$")


def clean_name(s):
    s = re.sub(r"(\((?:4|9)%\))\s*\d$", r"\1", s.strip())  # footnote marker after the credit tag
    s = re.sub(r"\((?:4%|9%|RHRF only|[a-e])\)", " ", s)
    s = re.sub(r"\s*-\s*9%\**", " ", s)
    s = re.sub(r"\*+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" -")


def parse(year, path, url):
    with pdfplumber.open(path) as pdf:
        pg = pdf.pages[0]
        words = pg.extract_words(x_tolerance=1.5)
    hdr_top = min(w["top"] for w in words if w["text"] == "Applicant")
    sub = [w for w in words if re.match(r"\(10", w["text"]) and w["top"] > hdr_top - 40]
    body_top = (max(w["bottom"] for w in sub) if sub else hdr_top) + 2
    total = [w for w in words if w["text"].startswith("TOTAL") and w["top"] > body_top]
    body_bot = min(w["top"] for w in total) - 2
    hwords = {w["text"] for w in words if hdr_top - 40 < w["top"] < body_top}
    body = [w for w in words if body_top < w["top"] < body_bot]
    dates = [w["x0"] for w in body if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", w["text"])]
    # first column right of Applicant: application date (2020-2024) or "Type" (2025, centered header)
    x_date = min(dates) if dates else min(w["x0"] for w in words if w["text"] == "Type" and w["top"] < body_top) - 15
    alpha = [w for w in body if re.search(r"[A-Za-z]", w["text"]) and w["x0"] < x_date]
    name_left = min(w["x0"] for w in alpha)
    xs = collections.Counter(round(w["x0"]) for w in alpha if name_left + 60 < w["x0"] < x_date - 20)
    app_left = xs.most_common(1)[0][0] - 2
    namecol = [w for w in body if name_left - 1 <= w["x0"] < app_left]
    appcol = [w for w in body if app_left <= w["x0"] < x_date - 5]
    numcol = [w for w in body if w["x0"] >= x_date - 5]
    nlines = lines_of(namecol)
    alines = lines_of(appcol)
    rows, dropped = [], 0
    start = 0
    for i, (t, ws) in enumerate(nlines):
        m = CITY.match(text(ws))
        if not m:
            continue
        block = nlines[start:i]
        start = i + 1
        if not block:
            continue
        top, bot = block[0][0], t
        addr = text(block[-1][1]) if len(block) >= 2 else ""
        name = clean_name(" ".join(text(b[1]) for b in (block[:-1] if len(block) >= 2 else block)))
        if re.fullmatch(r"(Address\s+)?TBD\b[\s\-]*(Lot\s+\d+)?", addr, re.I):
            addr = ""
        nums = sorted([w for w in numcol if top - 4 <= w["top"] <= top + 4], key=lambda w: w["x0"])
        money = [int(w["text"].strip("$").replace(",", "")) for w in nums if MONEY.match(w["text"])]
        ints = [int(w["text"].replace(",", "")) for w in nums if re.fullmatch(r"[\d,]+", w["text"])]
        app = [text(a[1]) for a in alines if top - 4 <= a[0] < bot - 4 and not a[1][0]["text"].startswith("Contact")]
        company = app[0] if app else ""
        if "Market" in hwords:
            n_units, li_units = ints[-6], ints[-3]
        elif "Manager" in hwords:
            n_units, li_units = ints[-5], ints[-3]
        else:
            n_units, li_units = ints[-2], ints[-1]
        assert len(money) == 6, (year, name, money)
        f9, f4 = money[0], money[2]
        base = {"PROJECT": name, "PROJ_ADD": addr, "PROJ_CTY": m.group(1).strip(), "PROJ_ZIP": m.group(2),
                "YR_ALLOC": year, "N_UNITS": n_units, "LI_UNITS": li_units, "COMPANY": company, "STATE_ID": "",
                "SRC_URL": url}
        if not f9 and not f4:
            dropped += 1
            continue
        for amt, credit, kind in ((f9, "9%", "9% volume cap"), (f4, "4% (bond)", "4% non-volume cap")):
            if amt:
                rows.append(dict(base, CREDIT=credit, ALLOCAMT=amt,
                                 SRC_LABEL=f"Hawaii HHFDC {year} funding round awards list ({kind} LIHTC)"))
    return rows, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc",
                                                                   "states", "extracted")))
    a = ap.parse_args()
    allrows = []
    for year, fn, url in SOURCES:
        path = os.path.join(PDF_DIR, fn)
        if not fetch(url, path):
            continue
        rows, dropped = parse(year, path, url)
        print(f"{fn}: {len(rows)} rows ({sum(r['CREDIT'] == '9%' for r in rows)} 9%, "
              f"{sum(r['CREDIT'] != '9%' for r in rows)} 4%); dropped {dropped} non-LIHTC (RHRF-only) awards")
        allrows += rows
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, f"{ST.lower()}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(allrows)
    print(f"wrote {len(allrows)} rows -> {out}")


if __name__ == "__main__":
    main()

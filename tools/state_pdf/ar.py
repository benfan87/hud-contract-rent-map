"""Arkansas Development Finance Authority (ADFA) annual 9% LIHTC recipients / reservations lists (PDF) -> standard CSV.

One table per year, one numbered record per award, each a block of ~5 text lines per column:
    APPLICANT (owner entity / contact / address / phone) | DEVELOPER (same) |
    DEVELOPMENT (name / street, may wrap / "City, AR ZIP" / N/C or Acq/Rehab / set-aside / building type) |
    CONG. DIST. + COUNTY + TOTAL UNITS + LIHTC UNITS | money columns (FEDERAL / STATE credits, HOME, CHDO, NHTF;
    the order and set of money columns change by year).
Columns are taken from each page's vertical cell borders, labelled by the header words inside them. A record starts on
the line that holds its congressional district ("1st" .. "4th"); everything above the next one belongs to it. Lines
from "TOTALS" down are ignored. Words are read with x/y positions (pdfplumber extract_words).

ALLOCAMT = the annual FEDERAL credit; CREDIT = "9%" (ADFA posts no 4% bond list). "Approx." / "near" in front of a
street is dropped (the address is approximate). The 2022 file only contains 2 filled-in records (rows 3-8 are blank in
the PDF itself). Awards that a later list says were returned are dropped (see RETURNED).

Usage: python tools/state_pdf/ar.py --out ../hud_src/lihtc/states/extracted   (run from the repo root)
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import urllib.request

import pdfplumber

ST = "AR"
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc", "states", "pdf", ST.lower()))
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
BASE = "https://adfa.arkansas.gov/wp-content/uploads/"
SOURCES = [  # (year, local file, url, list title)
    (2020, "ar_2020.pdf", BASE + "2024/12/2020-LIHTC-Recipients.pdf", "9% tax credit recipients"),
    (2021, "ar_2021.pdf", BASE + "2024/12/2021-LIHTC-Recipients.pdf", "9% tax credit recipients"),
    (2022, "ar_2022.pdf", BASE + "2024/12/2022-LIHTC-Recipients.pdf", "9% tax credit recipients"),
    (2023, "ar_2023.pdf", BASE + "2024/12/2023-LIHTC-Recipients.pdf", "9% tax credit recipients"),
    (2024, "ar_2024.pdf", BASE + "2024/12/2024-9-LIHTC-Recipient.pdf", "9% tax credit recipients"),
    (2025, "ar_2025.pdf", BASE + "2025/07/2025-9-LIHTC-recipients.pdf", "9% LIHTC recipients"),
    (2026, "ar_2026.pdf", BASE + "2026/05/2026-9-LIHTC-Reservations-with-Riparian.pdf", "9% tax credit reservations"),
]
# (year, project) -> why it is dropped
RETURNED = {(2024, "Southern Heights"): "2025 list: 'Southern Heights returned allocation' ($937,500)"}
MONEY_HDR = ("FEDERAL", "STATE", "HOME", "CHDO", "NHTF", "CHDO/PRLF")


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


ORDINAL = re.compile(r"^\d(st|nd|rd|th)$")
CITY = re.compile(r"^(.*?),?\s+(?:AR|Arkansas)\.?,?\s*(\d{5})?(?:-\d{4})?$")
STREETY = re.compile(r"\d|^(Approx|near|TBD|Corner|Intersection|(North|South|East|West|NW|NE|SW|SE)\b)|"
                     r"\b(St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Blvd|Lane|Ln|Pike|Highway|Hwy|Parkway|Pkwy|Way|"
                     r"Circle|Ct|Court|Place|Trail)\b", re.I)
CONSTR = re.compile(r"^(N/C|New Construction|Acq|Rehab|Adaptive|Non-?Profit|For-?Profit)", re.I)
COMPANYISH = re.compile(r"\b(Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Development|Company|Group|Partners)\b")


def num(s):
    m = re.fullmatch(r"\$?([\d,]+)(\.\d+)?", s)
    return int(m.group(1).replace(",", "")) if m and m.group(1).replace(",", "") else None


def columns(pg, words):
    """Cell borders -> [(x0, x1, label)]: applicant, developer, development, middle, then money columns."""
    xs = sorted(e["x0"] for e in pg.edges if e["orientation"] == "v" and e["bottom"] - e["top"] > 5)
    v = []
    for x in xs:
        if not v or x - v[-1] > 3:
            v.append(x)
    bounds = list(zip(v, v[1:] + [pg.width]))
    hdr = [w for w in words if w["text"] in MONEY_HDR]
    cols = []
    for i, (a, b) in enumerate(bounds):
        if i < 4:
            cols.append((a, b, ("applicant", "developer", "development", "middle")[i]))
        else:
            lab = next((w["text"] for w in hdr if a - 2 <= w["x0"] < b), "")
            cols.append((a, b, lab))
    return cols


def street_city(lines):
    """development column lines -> name, street, city, zip"""
    i_city = next((i for i, s in enumerate(lines) if CITY.match(s) and i > 0), None)
    i_end = i_city if i_city is not None else next((i for i, s in enumerate(lines) if CONSTR.match(s)), len(lines))
    pre = [x.replace("�", "-") for x in lines[:i_end]]
    k = 1
    if i_city is None:  # scattered sites ("Forrest City/Wynne/ Helena/Sunset"): no single street / city
        while k < len(pre) and re.search(r"(&|\band)$", pre[k - 1]):
            k += 1
        return " ".join(pre[:k]), "", "", ""
    while k < len(pre) and (re.search(r"(&|/|\band)$", pre[k - 1]) or not STREETY.search(pre[k])):
        k += 1  # name continues on the next line
    name, street = " ".join(pre[:k]), " ".join(pre[k:])
    street = re.sub(r"^(Approx\.?|near)\s+", "", street, flags=re.I).strip()
    if re.match(r"^TBD\b", street, re.I):
        street = ""
    m = CITY.match(lines[i_city])
    return name, street, m.group(1).strip(), m.group(2) or ""


def parse(year, path, url, title):
    rows, dropped = [], []
    label = f"Arkansas ADFA {year} {title}"
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            words = pg.extract_words(x_tolerance=1.5)
            cols = columns(pg, words)

            def col(w):
                return next((c for c in cols if c[0] - 1 <= w["x0"] < c[1] - 1), None)

            mid = next(c for c in cols if c[2] == "middle")
            anchors = sorted(w["top"] for w in words if ORDINAL.match(w["text"]) and mid[0] <= w["x0"] < mid[1])
            stop = min([w["top"] for w in words if re.match(r"^TOTALS?$", w["text"])] + [pg.height]) - 2
            for j, top in enumerate(anchors):
                bot = min(anchors[j + 1] - 4 if j + 1 < len(anchors) else pg.height, stop)
                ws = [w for w in words if top - 4 <= w["top"] < bot]
                by = {}
                for w in ws:
                    c = col(w)
                    if c:
                        by.setdefault(c[2], []).append(w)
                dev = lines_of(by.get("development", []))
                name, street, city, zip_ = street_city(dev)
                ints = [int(w["text"]) for w in sorted(by.get("middle", []), key=lambda w: (round(w["top"]), w["x0"]))
                        if re.fullmatch(r"\d+", w["text"])]
                money = {}
                for lab in MONEY_HDR:
                    vals = [num(w["text"]) for w in by.get(lab, []) if num(w["text"]) is not None]
                    if vals:
                        money[lab] = vals[0]
                dl = lines_of(by.get("developer", []))
                company = dl[0] if dl else ""
                if len(dl) > 1 and COMPANYISH.search(dl[1]) and not re.search(r"\d|@", dl[1]):
                    company += " " + dl[1]
                r = {"PROJECT": name, "PROJ_ADD": street, "PROJ_CTY": city, "PROJ_ZIP": zip_, "YR_ALLOC": year,
                     "CREDIT": "9%", "N_UNITS": ints[0] if ints else "", "LI_UNITS": ints[1] if len(ints) > 1 else "",
                     "COMPANY": re.sub(r"\s+", " ", company), "ALLOCAMT": money.get("FEDERAL", ""), "STATE_ID": "",
                     "SRC_LABEL": label, "SRC_URL": url}
                why = RETURNED.get((year, name))
                if why:
                    dropped.append(f"{year} {name}: {why}")
                    continue
                rows.append(r)
    return rows, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc",
                                                                   "states", "extracted")))
    a = ap.parse_args()
    allrows = []
    for year, fn, url, title in SOURCES:
        path = os.path.join(PDF_DIR, fn)
        if not fetch(url, path):
            continue
        rows, dropped = parse(year, path, url, title)
        print(f"{fn}: {len(rows)} rows, federal credits ${sum(r['ALLOCAMT'] or 0 for r in rows):,}")
        for d in dropped:
            print(f"  dropped: {d}")
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

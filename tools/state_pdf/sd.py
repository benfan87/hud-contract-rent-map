"""South Dakota Housing (SDHDA) Housing Tax Credit cumulative reservation list (PDF, 1987-2025) -> standard CSV.

One section per reservation year ("YYYY Reservations - As of ..."), from 2009 on followed by a "YYYY Tax Exempt
Bonds" subsection. Each record is a block of ~5 lines: contact / owner / owner address / phone on the left; development
name / street / "City, SD ZIP" / "X County" in the middle; awarded annual credit $ (and, for bond deals, the bond
amount) next to it; units and construction type on the right. Blocks are split on vertical gaps between lines
(pdfplumber words with x/y positions).

ALLOCAMT: when a record splits its award across credit years ("2025 $373,981" / "2026 $121,792") the labelled parts
are summed (an unlabelled total under them is ignored); several unlabelled amounts are summed. In bond records only
the amounts labelled "HTCs" (or the first-line amount in the older layout) are credits, not "Bonds" / "Bond Amount" /
"Revenue Note". CREDIT: "9%" for the main sections and "4% (bond)" for the Tax Exempt Bonds subsections from 2009 on
(when the list starts separating them); blank before 2009. All years are kept.

Usage: python tools/state_pdf/sd.py --out ../hud_src/lihtc/states/extracted   (run from the repo root)
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import urllib.request

import pdfplumber

ST = "SD"
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc", "states", "pdf", ST.lower()))
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
URL = "https://www.sdhousing.org/s/HTCReservationsCumulativeWebsite123125.pdf"
FILE = "sd_cumulative.pdf"
LABEL = "South Dakota Housing HTC cumulative reservation list (as of 12/31/2025)"
X_DEV, X_AWD, X_UNITS = 210, 405, 515  # column left edges: development, awarded $, units/type
GAP = 15.5  # vertical gap (pt) that separates two records


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
    return [(t, sorted(ws, key=lambda w: w["x0"])) for t, ws in out]


def txt(ws):
    return " ".join(w["text"] for w in ws).strip()


SKIP = re.compile(r"^(SOUTH DAKOTA HOUSING|LOW INCOME HOUSING TAX|CONTACT PERSON|No\. Units|/Volumes/|\d+\.xlsx)")
CITY = re.compile(r"^(.+?),?\s+(?:SD|S\.D\.|South Dakota)\.?,?\s*(\d{2,5})?(?:-\d{4})?$|^(.+?),\s*(\d{5})$")
STREET_END = re.compile(r"^(.*\d.*\b(?:Ave|Avenue|St|Street|Dr|Drive|Rd|Road|Blvd|Way|Lane|Ln|Place|Pl|Circle|Ct|Court|"
                        r"Highway|Hwy|Pkwy|Parkway|Trail)\.?),?\s+([A-Z].*)$")
YEAR_LBL = re.compile(r"^\(?(19|20)\d\d\)?$")


def money(s):
    """'$ 2 84,069' / '$284,069' / '129581 (2015)' -> int (award column text only)."""
    m = re.match(r"^\$([\d,]+)|^(\d[\d,]{3,})(?:\(|$)", s.replace(" ", ""))
    v = (m.group(1) or m.group(2) or "").replace(",", "") if m else ""
    return int(v) if v else None


def has_units(ws):
    return any(525 <= w["x0"] < 560 and re.fullmatch(r"\d+\*?", w["text"]) for w in ws)


def parse_block(lines, year, bond):
    dev, awd, units, contact = [], [], None, []
    for t, ws in lines:
        d = [w for w in ws if X_DEV <= w["x0"] < X_AWD]
        lbl = [w for w in d if w["x0"] > 330 and YEAR_LBL.match(w["text"])]
        d = [w for w in d if w not in lbl]
        if d:
            dev.append(txt(d))
        a = [w for w in ws if X_AWD <= w["x0"] < X_UNITS]
        if a:  # a credit-year label sits left of the amount, or in parens after it
            awd.append((txt(a), bool(lbl) or bool(re.search(r"\((19|20)\d\d\)", txt(a)))))
        c = [w for w in ws if w["x0"] < X_DEV]
        if c:
            contact.append(txt(c))
        if units is None:
            u = [w for w in ws if 525 <= w["x0"] < 560 and re.fullmatch(r"\d+\*?", w["text"])]
            if u:
                units = u[0]["text"].rstrip("*")
    # credit amounts
    amts, labelled = [], []
    texts = [a for a, _ in awd]
    for i, (a, has_lbl) in enumerate(awd):
        v = money(a)
        if v is None and not re.match(r"^\$\s*-", a):
            continue
        nxt = next((x for x in texts[i + 1:] if money(x) is None and not x.startswith("$")), "")
        prv = next((x for x in reversed(texts[:i]) if money(x) is None and not x.startswith("$")), "")
        if bond or re.search(r"\bBonds?\b", " ".join(texts)):
            if re.match(r"^(Bonds|Revenue)\b", nxt):
                continue  # "$32,000,000 / Bonds", "$20,000,000 / Revenue Note"
            if re.match(r"^Bond( Amount)?:?$", prv):
                continue  # "Bond Amount: / $9,654,500"
        if v:
            (labelled if has_lbl else amts).append(v)
    vals = labelled or amts
    if len(vals) >= 3 and vals[-1] == sum(vals[:-1]):
        vals = vals[:-1]  # trailing total under split amounts
    amt = sum(vals)
    # development column: name / street ... / City, SD ZIP / X County
    name, street, city, zip_ = (dev[0] if dev else ""), [], "", ""
    for x in dev[1:]:
        m = CITY.match(x)
        if m and not city:
            city, zip_ = (m.group(1) or m.group(3)).strip(), (m.group(2) or m.group(4) or "")
            zip_ = zip_ if len(zip_) == 5 else ""
            sm = STREET_END.match(city)
            if sm:  # "2116 7th Ave. BelleFourche, SD 57717": street and city on one line
                street.append(sm.group(1))
                city = sm.group(2)
            break
        if re.search(r"\bCounty$", x):
            # some years print the city without ", SD": the line just above "X County" is the city
            if not city and len(street) >= 2 and not re.match(r"^(\d|TBD\b)", street[-1]):
                city = street.pop()
            break
        street.append(x)
    owner = ""
    for x in contact[1:2]:
        if not re.match(r"^(\d|P\.?\s?O\.?\b|Box\b|RR\b|\(?\d{3}\)?[\s-]|Citizens Building)", x, re.I) and \
                not re.search(r",\s*[A-Z]{2}\s*\d{5}", x):
            owner = x
    name = re.sub(r"\s+", " ", name).strip()
    if re.search(r"\bCount(y|ies)$", city):
        city = ""  # scattered-site records name a county instead of a city
    return {"PROJECT": name, "PROJ_ADD": " ".join(street), "PROJ_CTY": city, "PROJ_ZIP": zip_, "YR_ALLOC": year,
            "CREDIT": ("4% (bond)" if bond else "9%") if year >= 2009 else "",
            "N_UNITS": units if units and int(units) else "",
            "LI_UNITS": "", "COMPANY": owner, "ALLOCAMT": amt or "", "STATE_ID": "", "SRC_LABEL": LABEL,
            "SRC_URL": URL}


def parse(path):
    rows, year, bond = [], None, False
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            block, last = [], None

            def flush():
                if block and year:
                    r = parse_block(block, year, bond)
                    if r["PROJECT"]:
                        rows.append(r)
                block.clear()

            for t, ws in lines_of(pg.extract_words(x_tolerance=1.5)):
                s = txt(ws).replace("*", "")
                m = re.match(r"^(\d{4}) Reservations", s)
                if m:
                    flush()
                    year, bond = int(m.group(1)), False
                    continue
                if re.search(r"Tax[- ]Exempt Bonds", s, re.I) and ws[0]["x0"] < X_DEV:
                    flush()
                    m = re.match(r"^(\d{4})", s)
                    year, bond = (int(m.group(1)) if m else year), True
                    continue
                if SKIP.match(s) or re.match(r"^No tax exempt bonds", s, re.I):
                    continue
                if any(w["text"].startswith("Totals") for w in ws):
                    flush()
                    last = None
                    continue
                # a new record starts after a vertical gap, or (records printed close together) on a line that
                # carries both an award $ and a unit count while the current block already has its unit count
                starts = has_units(ws) and any(X_AWD <= w["x0"] < X_UNITS and w["text"].startswith("$") for w in ws)
                if last is not None and (t - last > GAP or (starts and any(has_units(b) for _, b in block))):
                    flush()
                block.append((t, ws))
                last = t
            flush()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc",
                                                                   "states", "extracted")))
    a = ap.parse_args()
    path = os.path.join(PDF_DIR, FILE)
    rows = parse(path) if fetch(URL, path) else []
    print(f"{FILE}: {len(rows)} rows ({sum(r['CREDIT'] == '9%' for r in rows)} 9%, "
          f"{sum(r['CREDIT'] == '4% (bond)' for r in rows)} 4%, {sum(not r['CREDIT'] for r in rows)} pre-2009 untyped)")
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, f"{ST.lower()}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()

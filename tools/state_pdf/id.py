"""Idaho Housing and Finance Association (IHFA) annual LIHTC allocation lists (PDF) -> standard CSV.

Each list has a competitive 9% table and (most years) a non-competitive 4% bond table, drawn with cell borders, so
pdfplumber's extract_tables() reads them cleanly. The "Development Name / Location" cell holds name / street /
(city, 2020-2022 only) / construction type; 2024+ lists have a separate City column; the 2023 list has no city at all.
No project ZIP in any list.

Split / forward awards: a list for year Y can show credits under several "YYYY LIHTC" columns (e.g. 2019 + 2020).
We emit one row per list with YR_ALLOC = Y and ALLOCAMT = the "Y LIHTC" column, so a project that got credits from
two credit years appears once in each year's list.

Usage: python tools/state_pdf/id.py --out ../hud_src/lihtc/states/extracted   (run from the repo root)
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import urllib.request

import pdfplumber

ST = "ID"
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc", "states", "pdf", ST.lower()))
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

SOURCES = [  # (year, local file, url)
    (2020, "id_2020.pdf", "https://www.idahohousing.com/documents/2020-lihtc-allocation-list.pdf"),
    (2021, "id_2021.pdf", "https://www.idahohousing.com/documents/2021-lihtc-allocation-list.pdf"),
    (2022, "id_2022.pdf", "https://www.idahohousing.com/documents/2022-lihtc-allocation-list.pdf"),
    (2023, "id_2023.pdf", "https://www.idahohousing.com/documents/2023-lihtc-allocation-list.pdf"),
    (2024, "id_2024.pdf", "https://www.idahohousing.com/documents/2024-lihtc-allocations.pdf"),
    (2025, "id_2025.pdf", "https://www.idahohousing.com/documents/2025-lihtc-allocations.pdf"),
    (2026, "id_2026.pdf", "https://www.idahohousing.com/documents/2026-lihtc-allocations.pdf"),
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


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def num(s):
    s = re.sub(r"[$,\s]", "", s or "")
    return s if re.fullmatch(r"\d+(\.\d+)?", s) else ""


CONSTR = re.compile(r"^\(|^(NEW CONSTRUCTION|ACQ|REHAB)|PROJECT RELIEF", re.I)
CO_WORDS = re.compile(r"LLC|Inc|Corp|Company|Co\.|Housing|Development|Communities|Group|Charities|Services|Trust|"
                      r"Partners|Affordable|Ventures|Capital|Consulting|Enterprises|SMRI|&", re.I)
PERSON = re.compile(r"^[A-Z][a-z]+(?: [A-Z]\.)?(?: [A-Z][a-zA-Z'\-]+){1,2}$")


def split_location(cell, has_city):
    lines = [clean(x) for x in (cell or "").split("\n") if clean(x)]
    lines = [x for x in lines if not CONSTR.search(x)]
    lines = [x for x in lines if not re.fullmatch(r"\(?[A-Za-z /\-]*Relief\)?", x)]
    city = ""
    if has_city and len(lines) >= 3:
        city = lines.pop()
    addr = lines.pop() if len(lines) >= 2 else ""
    name = " ".join(lines)
    name = re.sub(r"\s*\*+$", "", name)
    name = re.sub(r"\s*-?\s*[49]%$|\s+9$", "", name).strip(" -")
    return name, addr, city


def company(cell):
    lines = [clean(x) for x in (cell or "").split("\n") if clean(x)]
    lines = lines[1:]  # first line is the contact person
    while lines and (re.match(r"^(\d|P\.?\s?O\.?\s|PO Box)", lines[-1], re.I)
                     or re.search(r",\s*[A-Z]{2}\s+\d{5}", lines[-1])):
        lines.pop()
    out = []
    for x in lines:
        if PERSON.match(x) and not CO_WORDS.search(x):
            continue
        if out and (len(x.split()) == 1 or out[-1].endswith(("&", "/"))):
            out[-1] += " " + x
        else:
            out.append(x)
    return "; ".join(out)


def parse(year, path, url):
    rows = []
    label9 = f"Idaho Housing and Finance Assn. {year} LIHTC allocations (competitive 9%)"
    label4 = f"Idaho Housing and Finance Assn. {year} LIHTC allocations (non-competitive 4% bond)"
    with pdfplumber.open(path) as pdf:
        tables = [t for pg in pdf.pages for t in pg.extract_tables()]
    hdr = None
    for t in tables:
        for r in t:
            cells = [clean(c) for c in r]
            if "Developer Contact" in cells:
                hdr = cells
                continue
            if hdr is None or len(cells) != len(hdr):
                continue
            rec = dict(zip(hdr, cells))
            raw = dict(zip(hdr, r))
            if not rec.get("Developer Contact") and not rec.get("Development Name / Location"):
                continue  # totals / blank spacer rows
            has_city = "City" not in hdr and year <= 2022
            name, addr, city = split_location(raw.get("Development Name / Location"), has_city)
            if "City" in hdr:
                city = rec["City"]
            amt9 = num(rec.get(f"{year} LIHTC", ""))
            amt4 = next((num(v) for k, v in rec.items() if "4% LIHTC" in k), "")
            is_bond = not any(re.fullmatch(r"\d{4} LIHTC", k) for k in hdr)  # 4% bond tables have no credit-year cols
            is_bond = is_bond or bool(re.search(r"bond", rec.get("Set Aside", ""), re.I)) or (amt4 and not amt9)
            if "Development Name / Location" in rec and re.search(r"-\s*4%", clean(raw["Development Name / Location"])):
                is_bond = True
            rows.append({
                "PROJECT": name, "PROJ_ADD": addr, "PROJ_CTY": city, "PROJ_ZIP": "", "YR_ALLOC": year,
                "CREDIT": "4% (bond)" if is_bond else "9%",
                "N_UNITS": num(rec.get("Total Units")), "LI_UNITS": num(rec.get("Affordable Units")),
                "COMPANY": company(raw.get("Developer Contact")),
                "ALLOCAMT": amt4 if is_bond else amt9,
                "STATE_ID": rec.get("Project Number", ""),
                "SRC_LABEL": label4 if is_bond else label9, "SRC_URL": url})
    return rows


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
        rows = parse(year, path, url)
        print(f"{fn}: {len(rows)} rows ({sum(r['CREDIT'] == '9%' for r in rows)} 9%, "
              f"{sum(r['CREDIT'] != '9%' for r in rows)} 4%)")
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

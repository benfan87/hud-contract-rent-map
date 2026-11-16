"""Pennsylvania Housing Finance Agency (PHFA) 9% LIHTC award lists -> extracted/pa.csv.

One PDF per competitive round ("<year> Low Income Housing Tax Credit, PennHOMES, National Housing Trust Fund [and PA
Housing Tax Credit] Awards"). The PDFs are ruled tables, so pdfplumber's extract_tables() gives clean cells; columns
are mapped from each page's header row.
  2020, 2021: Development Name (name / street / "City, PA ZIP") | City | County | Sponsor (sponsor / contact / email,
              repeated for co-sponsors) | Units | NHTF | PennHOMES | LIHTC Award
  2022:       Development Name (name / "City, PA ZIP", no street) | County | Sponsor(s) | Type | LI Units |
              Total Units | PennHOMES | NHTF | PHTC | Federal LIHTC
  2024:       Development Name (name / street / "City, ZIP") | County | Type | LI Units | Total Units | ... | LIHTC
              (no sponsor column)
  2025:       Development Name (name / street / city, no ZIP) | County | Sponsor(s) | ... | LIHTC. The official
              2025 award PDF (phfa.org/.../2025/2025-lihtc-awards.pdf) has no text layer, so the text copy posted on
              annualreport.phfa.org is used; its header says "2024 ... Awards" but it is dated October 9, 2025 and
              lists the 2025 round.
Every listed development is an award; TOTALS rows and footnotes are dropped, as is any row without a federal LIHTC
amount (none so far). CREDIT 9% (PHFA posts only its competitive round), ALLOCAMT = annual federal LIHTC.
"*" after a name = conditional forward commitment (2020-2022) / conditional reservation (2024); it is removed from
PROJECT and noted in SRC_LABEL. Street lines "TBD", "Scattered Site(s)" and "multiple addresses" are left blank.
The ZIP is the one printed in the development's own address line (ZIP+4 cut to 5 digits).

Usage (from the repo root): python tools/state_pdf/pa.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

# (round year, url, award date / note)
FILES = [
    (2020, "https://www.phfa.org/forms/multifamily_news/news/2020/2020-lihtc-awrds.pdf", "awarded 8/13/2020"),
    (2021, "https://www.phfa.org/forms/multifamily_news/news/2021/2021-lihtc-awards.pdf", "awarded 10/14/2021"),
    (2022, "https://www.phfa.org/forms/multifamily_news/news/2022/2022-lihtc-awards.pdf", "awarded 11/10/2022"),
    (2024, "https://www.phfa.org/forms/multifamily_news/news/2024/2024-lihtc-awards.pdf", "awarded 7/11/2024"),
    (2025, "https://annualreport.phfa.org/wp-content/uploads/2026/03/2025-Final-Map-Doc-for-PPOS.pdf",
     "awarded 10/9/2025; text copy of the 2025 award list, header mislabeled 2024"),
]
STAR_NOTE = {2020: "conditional forward commitment", 2021: "conditional forward commitment",
             2022: "conditional forward commitment", 2024: "conditional reservation"}


def download(url, dest):
    """Plain urllib GET (default Python user agent). Returns None on success, else an error string."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except Exception as e:  # 403 / bot block / network: skip and report
        return f"{type(e).__name__}: {e}"
    if not data.startswith(b"%PDF"):
        return "response is not a PDF"
    dest.write_bytes(data)
    return None


def col_key(h):
    h = re.sub(r"\s+", " ", (h or "")).strip().lower()
    if h.startswith("development name"):
        return "name"
    if h == "city":
        return "city"
    if h == "county":
        return "county"
    if h.startswith("sponsor"):
        return "sponsor"
    if h == "units" or h == "total units":
        return "units"
    if h == "li units":
        return "li"
    if "lihtc" in h:
        return "lihtc"
    return h


CITY_RX = re.compile(r"^(?P<city>[^,]+?)\s*,\s*(?:PA\b\s*,?\s*)*(?P<zip>\d{5})?(?:-\d{4})?\s*$")
NOADDR_RX = re.compile(r"(?i)^(tbd|scat+ered sites?|multiple addresses)$")
SUFFIX_RX = re.compile(r"(?i)(LLC|L\.L\.C\.|Inc\.?|Corp\.?|Corporation|Group|CDC|Companies|Company|Authority|ARMDC|Hope|"
                       r"SeniorCare|Works|Services|LP|Partners|East|HOME|HACE|MSquared)$")


# obvious misspellings of the municipality in the source
CITY_FIX = {"Philadelaphia": "Philadelphia", "Belthlehem": "Bethlehem", "Scranton City": "Scranton"}
# (year, project) -> ZIP: 2022 list prints "Philadelphia, PA 18121" for Sharswood Phase 6a; Sharswood is 19121
# (as in the 2020/2021 Sharswood rows) and 18121 is not a Philadelphia ZIP
ZIP_FIX = {(2022, "Sharswood Phase 6a"): "19121"}


def money(s):
    s = re.sub(r"[^\d]", "", s or "")
    return int(s) if s else None


def split_name_cell(cell, yr):
    lines = [l.strip() for l in (cell or "").split("\n") if l.strip()]
    if not lines:
        return "", "", "", ""
    if yr == 2025:  # name / street (1+ lines) / city, no ZIP
        city_line, zp = lines[-1], ""
        city = city_line
    else:
        m = CITY_RX.match(lines[-1])
        city, zp = (m.group("city"), m.group("zip") or "") if m else (lines[-1], "")
    body = lines[:-1]
    if yr == 2022:  # no street line
        name_lines, street = body, []
    else:
        n = 1
        if len(body) > 2 and (body[1].startswith("(") or body[1] == "Preservation"):
            n = 2  # name wrapped onto a second line
        name_lines, street = body[:n], body[n:]
    name = " ".join(name_lines)
    addr = ""
    for l in street:  # a new line starting with a house number after a complete street = second address
        if addr and l[0].isdigit() and not re.search(r"([,;&/]|\band|\b[NSEW]\.)$", addr):
            addr += "; " + l
        else:
            addr = f"{addr} {l}".strip()
    addr = re.sub(r"\s+,", ",", addr)
    if NOADDR_RX.match(addr):
        addr = ""
    city = re.sub(r"^City of\s+", "", city.strip(" ,"))
    city = CITY_FIX.get(city, city)
    return name, addr, city, zp


def sponsor(cell, yr):
    lines = [l.strip() for l in (cell or "").split("\n")]
    if yr in (2020, 2021):  # sponsor / contact / email triples; a sponsor is the first line and any line after an email
        ents, prev_email = [], True
        for l in lines:
            if not l:
                continue
            if prev_email and "@" not in l:
                ents.append(l)
            prev_email = "@" in l
        return "; ".join(ents)
    ents, cur = [], ""
    for l in lines:
        sep = l.endswith("/")  # "Sponsor A /" + "Sponsor B" (2025)
        l = l.rstrip("/ ").strip()
        if not l:
            if cur:
                ents.append(cur)
            cur = ""
            continue
        if cur and SUFFIX_RX.search(cur):
            ents.append(cur)
            cur = l
        else:
            cur = f"{cur} {l}".strip()
        if sep:
            ents.append(cur)
            cur = ""
    if cur:
        ents.append(cur)
    return "; ".join(ents)


def parse(path, yr):
    pdf = pdfplumber.open(path)
    recs = []
    for page in pdf.pages:
        for t in page.extract_tables():
            keys = None
            for row in t:
                first = (row[0] or "").strip()
                if first.startswith("Development Name"):
                    keys = [col_key(h) for h in row]
                    continue
                if keys is None or not first or re.match(r"(?i)^(totals?\b|\*\s*(conditional|denotes))", first):
                    continue
                d = dict(zip(keys, row))
                recs.append(d)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "pa"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], []
    for yr, url, note in FILES:
        dest = pdir / url.rsplit("/", 1)[1]
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        recs = parse(dest, yr)
        n = Counter()
        for d in recs:
            amt = money(d.get("lihtc"))
            if not amt:
                n["no LIHTC"] += 1
                continue
            name, addr, city, zp = split_name_cell(d.get("name"), yr)
            star = bool(re.search(r"\*\s*$", name))
            name = re.sub(r"\s*[*+]\s*$", "", name).strip()
            zp = ZIP_FIX.get((yr, name), zp)
            if d.get("city"):
                city = re.sub(r"\s+", " ", d["city"]).strip()
            units = re.sub(r"\D", "", d.get("units") or "")
            li = re.sub(r"\D", "", d.get("li") or "")
            label = f"PHFA {yr} 9% LIHTC awards ({note})"
            if star:
                label += f" - {STAR_NOTE.get(yr, 'starred')}"
            rows.append({"PROJECT": name, "PROJ_ADD": addr, "PROJ_CTY": city, "PROJ_ZIP": zp, "YR_ALLOC": str(yr),
                         "CREDIT": "9%", "N_UNITS": units, "LI_UNITS": li,
                         "COMPANY": sponsor(d.get("sponsor"), yr), "ALLOCAMT": str(amt), "STATE_ID": "",
                         "SRC_LABEL": label, "SRC_URL": url})
            n["kept"] += 1
        print(f"{dest.name}: {len(recs)} table rows, {dict(n)}")
    with open(out / "pa.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'pa.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

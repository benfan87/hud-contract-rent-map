"""Iowa Finance Authority / Iowa Economic Development (opportunityiowa.gov) LIHTC award lists -> standard CSV.

Sources (2020+):
  * 9% award lists 2020-2025 (PDF, one landscape table per year).
  * 2026 9% awards: the agency's HTML award page (name, city, street, units, developer, credits), with project # and
    missing cities filled from the 2026 9% Combined Rankmaster xlsx.
  * 4% awards: historical 4% list PDF (2013-2023; rows from 2020 on are kept), 2025 4% award xlsx, and the 2026 4%
    Rankmaster xlsx (awarded section only; no street address).
  * "Active Projects" compliance inventory xlsx (all years; YR_ALLOC from the LIHTC # prefix, CREDIT blank).

PDF tables are drawn with cell borders but pdfplumber's extract_tables() drops some rows, so cells are rebuilt from
the border edges: rows = horizontal borders around each project-number cell, columns = vertical borders in the header
band; words are assigned to cells by position. Rows with no numeric credit award (returned / withdrawn / did not
accept, shown struck through) are dropped.

Usage: python tools/state_pdf/ia.py --out ../hud_src/lihtc/states/extracted   (run from the repo root)
"""
import argparse
import csv
import html
import os
import re
import shutil
import subprocess
import urllib.request

import openpyxl
import pdfplumber

ST = "IA"
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc", "states", "pdf", ST.lower()))
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
M = "https://opportunityiowa.gov/media/{}/download?inline"
PDF9 = [(2020, "ia_9pct_2020.pdf", M.format(5953)), (2021, "ia_9pct_2021.pdf", M.format(5763)),
        (2022, "ia_9pct_2022.pdf", M.format(5755)), (2023, "ia_9pct_2023.pdf", M.format(5739)),
        (2024, "ia_9pct_2024.pdf", M.format(5603)), (2025, "ia_9pct_2025.pdf", M.format(6512))]
PDF4_HIST = ("ia_4pct_hist.pdf", M.format(6236))
XLSX4_2025 = ("ia_4pct_2025.xlsx", M.format(7457))
XLSX4_2026 = ("ia_4pct_2026_rankmaster.xlsx", M.format(9011))
XLSX9_2026 = ("ia_9pct_2026_rankmaster.xlsx", M.format(8468))
HTML9_2026 = ("ia_9pct_2026_awards.html", "https://opportunityiowa.gov/federal-housing-tax-credit-9-awards")
ACTIVE = ("ia_active_projects.xlsx", M.format(6048))
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


def clean(s):
    return re.sub(r"\s+", " ", str(s if s is not None else "")).strip()


def num(s):
    if isinstance(s, (int, float)):
        return str(int(s)) if s else ""
    s = re.sub(r"[$,\s]", "", clean(s))
    return s if re.fullmatch(r"\d+", s) and int(s) > 0 else ""


def merge(vals, tol=2.5):
    out = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


ID_RE = re.compile(r"\d{2}-\d{2}(?:-\d{2,3})?")
FIELDS = [("STATE_ID", r"^(Proj(ect)?\s*(#|Number)|#)$"), ("PROJECT", r"^Project\s*Name"), ("PROJ_ADD", r"^Address"),
          ("PROJ_CTY", r"^City$"), ("LI_UNITS", r"\bLI(HTC)? Units|Low Income Units"), ("N_UNITS", r"^Total Units$"),
          ("AWARD", r"^Credit (Award|Amount Approved)$"), ("REQUEST", r"^Credit (Request|Amount Requested)$"),
          ("COMPANY", r"^Developer(\(s\))?( Name)?$")]


def grid_rows(path):
    """Rebuild bordered table cells from edges + words. Yields {field: text} per project row."""
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            words = pg.extract_words(x_tolerance=1.5)
            ids = [w for w in words if ID_RE.fullmatch(w["text"]) and w["x0"] < 80]
            if not ids:
                continue
            idx = min(w["x0"] for w in ids)
            # cell borders start left of the id text; strike-through lines start at the text itself
            hb = merge([e["top"] for e in pg.edges if e["orientation"] == "h" and e["x0"] <= idx - 0.5 <= e["x1"]])
            first = min(w["top"] for w in ids)
            b0 = max(b for b in hb if b <= first + 1)
            htop = max(b for b in hb if b < b0 - 10)
            vb = merge([e["x0"] for e in pg.edges if e["orientation"] == "v" and e["top"] < b0 - 2
                        and e["bottom"] > htop + 2])
            cols = list(zip(vb, vb[1:]))

            def cell(x0, x1, y0, y1):
                ws = [w for w in words if x0 <= (w["x0"] + w["x1"]) / 2 < x1 and y0 < (w["top"] + w["bottom"]) / 2 < y1]
                ws.sort(key=lambda w: (round(w["top"] / 3), w["x0"]))
                return clean(" ".join(w["text"] for w in ws))

            hdr = [cell(x0, x1, htop, b0) for x0, x1 in cols]
            fmap = {}
            for f, rx in FIELDS:
                j = next((j for j, h in enumerate(hdr) if re.search(rx, h, re.I)), None)
                if j is not None:
                    fmap[f] = j
            for w in ids:
                y0 = max(b for b in hb if b <= w["top"] + 1)
                y1 = min((b for b in hb if b > w["top"] + 1), default=w["top"] + 60)
                cells = [cell(x0, x1, y0, y1) for x0, x1 in cols]
                yield {f: cells[j] for f, j in fmap.items()}


def pdf_rows(year, path, url, credit, label):
    rows, dropped = [], []
    for r in grid_rows(path):
        sid = r.get("STATE_ID", "")
        yr = year or 2000 + int(sid[:2])
        if yr < MIN_YEAR:
            continue
        amt = num(r.get("AWARD", r.get("REQUEST", "")))
        name = re.sub(r"^\*|\*$", "", r.get("PROJECT", "")).strip()
        if not amt:
            dropped.append(f"{sid} {name}")
            continue
        rows.append({"PROJECT": name, "PROJ_ADD": r.get("PROJ_ADD", ""), "PROJ_CTY": r.get("PROJ_CTY", ""),
                     "PROJ_ZIP": "", "YR_ALLOC": yr, "CREDIT": credit, "N_UNITS": num(r.get("N_UNITS")),
                     "LI_UNITS": num(r.get("LI_UNITS")), "COMPANY": r.get("COMPANY", ""), "ALLOCAMT": amt,
                     "STATE_ID": sid, "SRC_LABEL": label.format(yr=yr), "SRC_URL": url})
    return rows, dropped


def xlsx_sections(path):
    """Yield (header, row) for every data row under a header row containing 'Project Name'; stops a section at
    a 'NO OFFER' / 'DID NOT MEET' heading (flagged by header None afterwards)."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        hdr, awarded = None, True
        for r in ws.iter_rows(values_only=True):
            cells = [clean(c) for c in r]
            first = cells[0] if cells else ""
            if re.match(r"(NO OFFER|DID NOT MEET)", first, re.I):
                awarded = False
            if "Project Name" in cells:
                hdr = cells
                continue
            if hdr and awarded and ID_RE.fullmatch(first):
                yield hdr, r


def col(hdr, row, rx):
    j = next((j for j, h in enumerate(hdr) if re.search(rx, h, re.I)), None)
    return row[j] if j is not None and j < len(row) else None


def xlsx_awards(path, url, year, label, has_addr=True):
    rows, dropped = [], []
    for hdr, r in xlsx_sections(path):
        amt = num(col(hdr, r, r"^Tax Credit\s*Award$|^Credit Award$"))
        name = clean(col(hdr, r, r"^Project Name$"))
        sid = clean(r[0])
        if not amt:
            dropped.append(f"{sid} {name}")
            continue
        rows.append({"PROJECT": name, "PROJ_ADD": clean(col(hdr, r, r"^Address$")) if has_addr else "",
                     "PROJ_CTY": clean(col(hdr, r, r"^City$")), "PROJ_ZIP": "", "YR_ALLOC": year,
                     "CREDIT": "4% (bond)", "N_UNITS": num(col(hdr, r, r"^Total Units$")),
                     "LI_UNITS": num(col(hdr, r, r"^(Total )?LI(HTC)? Units$")),
                     "COMPANY": clean(col(hdr, r, r"^Developer\(s\)$")), "ALLOCAMT": amt, "STATE_ID": sid,
                     "SRC_LABEL": label, "SRC_URL": url})
    return rows, dropped


def norm(s):
    s = re.sub(r"\b(apartments|apts|llc|lllp|lp)\b|\(2026\)", "", s.lower())
    return re.sub(r"[^a-z0-9]", "", s)


def html_2026(path, url, rank_path):
    """2026 9% award page: <h3>Name, City</h3><h4>street</h4> ... <li>N Units</li><li>Developer(s): ..</li>
    <li>Tax Credits: $..</li>. Project # / missing city / LIHTC units come from the Rankmaster."""
    rank = {}
    wb = openpyxl.load_workbook(rank_path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        hdr = None
        for r in ws.iter_rows(values_only=True):
            cells = [clean(c) for c in r]
            if "Project Name" in cells:
                hdr = cells
            elif hdr and cells and ID_RE.fullmatch(cells[0]):
                rank[norm(cells[1])] = {"id": cells[0], "city": clean(col(hdr, r, r"^City$")),
                                        "li": num(col(hdr, r, r"^Total LIHTC Units$"))}
    s = open(path, encoding="utf-8", errors="replace").read()
    s = s[s.find("Awarded Projects"):]
    s = s[:s.find("Secondary Navigation")]
    rows = []
    for blk in re.split(r"<h3[^>]*>", s)[1:]:
        h3 = clean(html.unescape(re.sub(r"<[^>]+>", " ", blk.split("</h3>")[0])))
        h4 = re.search(r"<h4[^>]*>(.*?)</h4>", blk, re.S)
        addr = clean(html.unescape(re.sub(r"<[^>]+>", " ", h4.group(1)))) if h4 else ""
        lis = [clean(html.unescape(re.sub(r"<[^>]+>", " ", x))) for x in re.findall(r"<li[^>]*>(.*?)</li>", blk, re.S)]
        name, _, city = h3.partition(", ")
        rk = rank.get(norm(name), {})
        units = next((re.match(r"(\d+)", x).group(1) for x in lis if re.fullmatch(r"\d+ Units?", x)), "")
        dev = next((x.split(":", 1)[1].strip() for x in lis if x.startswith("Developer")), "")
        amt = next((num(x.split(":", 1)[1]) for x in lis if x.startswith("Tax Credits")), "")
        if not amt:
            continue
        rows.append({"PROJECT": name.strip(), "PROJ_ADD": addr, "PROJ_CTY": city.strip() or rk.get("city", ""),
                     "PROJ_ZIP": "", "YR_ALLOC": 2026, "CREDIT": "9%", "N_UNITS": units, "LI_UNITS": rk.get("li", ""),
                     "COMPANY": dev, "ALLOCAMT": amt, "STATE_ID": rk.get("id", ""),
                     "SRC_LABEL": "Iowa Finance Authority 2026 9% Federal Housing Tax Credit awards", "SRC_URL": url})
    return rows


def active(path, url):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    rows = []
    for ws in wb.worksheets:
        hdr = None
        for r in ws.iter_rows(values_only=True):
            cells = [clean(c) for c in r]
            if "Project Name" in cells:
                hdr = cells
                continue
            if not hdr:
                continue
            sid = clean(col(hdr, r, r"^LIHTC #$"))
            m = re.match(r"(\d{2})-", sid)
            if not m or not clean(col(hdr, r, r"^Project Name$")):
                continue
            yy = int(m.group(1))
            rows.append({"PROJECT": clean(col(hdr, r, r"^Project Name$")), "PROJ_ADD": clean(col(hdr, r, r"^Address$")),
                         "PROJ_CTY": clean(col(hdr, r, r"^City$")).title(), "PROJ_ZIP": "",
                         "YR_ALLOC": (2000 if yy < 50 else 1900) + yy, "CREDIT": "", "N_UNITS": "", "LI_UNITS": "",
                         "COMPANY": clean(col(hdr, r, r"^Owner Name$")), "ALLOCAMT": "", "STATE_ID": sid,
                         "SRC_LABEL": "Iowa Finance Authority active LIHTC project list (as of 1/1/2026)",
                         "SRC_URL": url})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.normpath(os.path.join(HERE, "..", "..", "..", "hud_src", "lihtc",
                                                                   "states", "extracted")))
    a = ap.parse_args()
    p = lambda fn: os.path.join(PDF_DIR, fn)  # noqa: E731
    allrows = []

    def add(tag, rows, dropped=()):
        print(f"{tag}: {len(rows)} rows" + (f"; dropped (no credit award): {', '.join(dropped)}" if dropped else ""))
        allrows.extend(rows)

    for year, fn, url in PDF9:
        if fetch(url, p(fn)):
            add(fn, *pdf_rows(year, p(fn), url, "9%", "Iowa Finance Authority {yr} 9% Housing Tax Credit awards"))
    fn, url = HTML9_2026
    if fetch(url, p(fn)) and fetch(XLSX9_2026[1], p(XLSX9_2026[0])):
        add(fn, html_2026(p(fn), url, p(XLSX9_2026[0])))
    fn, url = PDF4_HIST
    if fetch(url, p(fn)):
        add(fn, *pdf_rows(None, p(fn), url, "4% (bond)", "Iowa Finance Authority historical 4% LIHTC awards ({yr})"))
    fn, url = XLSX4_2025
    if fetch(url, p(fn)):
        add(fn, *xlsx_awards(p(fn), url, 2025, "Iowa Finance Authority 2025 4% Federal Housing Tax Credit awards"))
    fn, url = XLSX4_2026
    if fetch(url, p(fn)):
        add(fn, *xlsx_awards(p(fn), url, 2026, "Iowa Finance Authority 2026 4% LIHTC Rankmaster (awarded)", False))
    fn, url = ACTIVE
    if fetch(url, p(fn)):
        add(fn, active(p(fn), url))
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, f"{ST.lower()}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(allrows)
    print(f"wrote {len(allrows)} rows -> {out}")


if __name__ == "__main__":
    main()

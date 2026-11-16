"""New Mexico (Housing New Mexico | MFA) housing tax credit awards, 2013 to date (the workbooks start in 2001): the 9% workbook and the 4% workbook.
One sheet per year; each project is stacked over several rows (name / street / "City, NM 87xxx" in the first column,
the award and units on the first row). Projects marked "RETURNED CREDITS" are dropped.
Usage: python tools/state_pdf/nm.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import collections
import csv
import os
import re
import subprocess

PAGE = "https://housingnm.org/developers/housing-tax-credits"
FILES = [("9%", "https://housingnm.org/uploads/documents/2001-2026_Housing_Tax_Credit_Awards_05.22.2026.xlsx", "nm_9pct_awards_2001_2026.xlsx"),
         ("4% (bond)", "https://housingnm.org/uploads/documents/2001-2026_4__LIHTC__Applications__Updated_08.28.2026.xls", "nm_4pct_2001_2026.xls")]
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY", "ALLOCAMT", "STATE_ID",
        "SRC_LABEL", "SRC_URL"]


def sheets(path):
    if path.endswith(".xls"):
        import xlrd
        wb = xlrd.open_workbook(path)
        for n in wb.sheet_names():
            s = wb.sheet_by_name(n)
            yield n, [s.row_values(i) for i in range(s.nrows)]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for n in wb.sheetnames:
            ws = wb[n]
            ws.reset_dimensions()
            yield n, [list(r) for r in ws.iter_rows(values_only=True)]


def cell(r, j):
    v = r[j] if j < len(r) else None
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""


def isnum(v):
    return isinstance(v, (int, float)) and v > 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src_dir = os.path.dirname(os.path.abspath(a.out))
    out = []
    for credit, url, fname in FILES:
        path = os.path.join(src_dir, fname)
        if not os.path.exists(path):
            subprocess.run(["curl", "-sS", "-L", "-o", path, url], check=True)
        for sheet, rows in sheets(path):
            year = re.search(r"(19|20)\d\d", sheet).group(0)
            if year < "2013":
                continue  # older sheets use other layouts; HUD's LIHTC database covers those years
            hdr = next((i for i, r in enumerate(rows[:12]) if cell(r, 1).startswith("Developer")), None)
            if hdr is None:
                continue
            # the credit-amount column: where project rows (name in column A) carry a dollar figure
            hits = collections.Counter(j for r in rows[hdr + 1:] if cell(r, 0) for j in (2, 3, 4) if j < len(r) and isnum(r[j]))
            if not hits:
                continue
            aw = hits.most_common(1)[0][0]
            starts = [i for i in range(hdr + 1, len(rows)) if cell(rows[i], 0) and isnum(rows[i][aw] if aw < len(rows[i]) else None)]
            for k, i in enumerate(starts):
                block = rows[i:starts[k + 1] if k + 1 < len(starts) else min(i + 8, len(rows))]
                if any("RETURNED" in cell(r, j).upper() for r in block for j in range(len(r))):
                    continue
                lines = [cell(r, 0) for r in block[1:] if cell(r, 0)]
                cz = next((n for n, t in enumerate(lines) if re.search(r",\s*NM\b", t)), None)
                street = city = zip5 = ""
                if cz is not None:
                    m = re.match(r"(.*?),\s*NM\.?\s*(\d{5})?", lines[cz])
                    city, zip5 = m.group(1).strip(), m.group(2) or ""
                    street = " ".join(lines[:cz]) if cz else ""
                    if street and not re.match(r"\d", street):
                        street = ""  # "SW quadrant of ...", "Scattered sites": not a street address
                r0 = block[0]
                out.append({"PROJECT": cell(r0, 0), "PROJ_ADD": street, "PROJ_CTY": city, "PROJ_ZIP": zip5, "YR_ALLOC": year,
                            "CREDIT": credit, "N_UNITS": cell(r0, aw + 2), "LI_UNITS": cell(r0, aw + 1),
                            "COMPANY": cell(r0, 2) if credit == "9%" else cell(block[1], 1) if len(block) > 1 else "",
                            "ALLOCAMT": r0[aw], "STATE_ID": "",
                            "SRC_LABEL": f"Housing New Mexico {credit} housing tax credit awards, {year}", "SRC_URL": PAGE})
    with open(os.path.join(a.out, "nm.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(out)

    print(len(out), "rows;", dict(collections.Counter(r["CREDIT"] for r in out)), "street:", sum(1 for r in out if r["PROJ_ADD"]),
          "zip:", sum(1 for r in out if r["PROJ_ZIP"]), "years 2020+:", dict(sorted(collections.Counter(r["YR_ALLOC"] for r in out if r["YR_ALLOC"] >= "2020").items())))


if __name__ == "__main__":
    main()

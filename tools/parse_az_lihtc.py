"""Parse Arizona Department of Housing's "LIHTC Tax Credit Projects - 1987 to Present" workbook
(9% awards and bond/4% deals) into the same row shape as HUD's LIHTC layer, for tools/match_lihtc.py.

Source page: https://housing.az.gov/documents-links/forms/rental-development-lihtc (file LIHTCandBond-Projects.xlsx).
The site sits behind a browser check, so download the file in a normal browser first.
Usage: python tools/parse_az_lihtc.py <LIHTCandBond-Projects.xlsx> <out.json> --published YYYY-MM
"""
import argparse
import json
import re

import openpyxl

URL = "https://housing.az.gov/sites/default/files/2026-04/LIHTCandBond-Projects.xlsx"
PAGE = "https://housing.az.gov/documents-links/forms/rental-development-lihtc"


def rows(wb, name):
    ws = wb[name]
    ws.reset_dimensions()
    return [tuple(r) + (None,) * (30 - len(r)) for r in ws.iter_rows(values_only=True)]


def txt(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("out")
    ap.add_argument("--published", required=True, help="month ADOH posted the file, e.g. 2026-04")
    a = ap.parse_args()
    wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
    out = []
    label9 = f"Arizona Dept. of Housing 9% LIHTC awards list (posted {a.published})"
    for r in rows(wb, "9% LIHTC Projects")[2:]:
        if not isinstance(r[0], int) or not r[2]:
            continue
        out.append({"HUD_ID": None, "STATE_ID": txt(r[1]), "PROJECT": txt(r[2]), "PROJ_ADD": txt(r[3]),
                    "PROJ_CTY": txt(r[4]), "PROJ_ST": "AZ", "PROJ_ZIP": txt(r[5])[:5], "YR_ALLOC": str(r[0]),
                    "YR_PIS": None, "CREDIT": "9%", "TYPE": None, "BOND": None, "ALLOCAMT": r[7],
                    "N_UNITS": r[13] if isinstance(r[13], (int, float)) else None, "LI_UNITS": r[10],
                    "COMPANY": None, "LAT": None, "LON": None, "_src": label9, "_url": PAGE})
    labelb = f"Arizona Dept. of Housing bond/4% LIHTC list (posted {a.published})"
    br = rows(wb, "Total Bonds to Date")
    for i, r in enumerate(br):
        if not (isinstance(r[1], int) and r[2] and str(r[2]).startswith("BD")):
            continue
        addr, cityline = txt(br[i + 1][3]) if i + 1 < len(br) else "", txt(br[i + 2][3]) if i + 2 < len(br) else ""
        m = re.match(r"(.*?),?\s+AZ\s+(\d{5})", cityline)
        out.append({"HUD_ID": None, "STATE_ID": txt(r[2]), "PROJECT": txt(r[3]), "PROJ_ADD": addr,
                    "PROJ_CTY": m.group(1).strip() if m else cityline, "PROJ_ST": "AZ",
                    "PROJ_ZIP": m.group(2) if m else "", "YR_ALLOC": str(r[1]), "YR_PIS": None,
                    "CREDIT": "4% (bond)", "TYPE": txt(r[10]), "BOND": "1", "ALLOCAMT": r[12],
                    "N_UNITS": r[6], "LI_UNITS": r[7], "COMPANY": txt(r[4]), "LAT": None, "LON": None,
                    "_src": labelb, "_url": PAGE})
    json.dump({"source": URL, "page": PAGE, "fetched": a.published, "rows": out}, open(a.out, "w", encoding="utf-8"))
    print(len(out), "records;", sum(1 for x in out if x["CREDIT"] == "9%"), "9%;",
          sum(1 for x in out if x["BOND"]), "bond; missing zip:", sum(1 for x in out if not x["PROJ_ZIP"]))


if __name__ == "__main__":
    main()

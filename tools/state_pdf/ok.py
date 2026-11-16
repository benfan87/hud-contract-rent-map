"""Oklahoma Housing Finance Agency (OHFA) housing tax credit award lists -> extracted/ok.csv.

OHFA posts one PDF per award round: 9% 1st round, 9% 2nd round (the 2021 2nd round also has a 4% column), and a 4%
(bond) list per year. Each is a wide table with one multi-line record per project:
  OHFA File No. | Development Name and Address (name / street / "City, OK ZIP") | County | Owner | Mgmt co | set-aside |
  family/elderly | resyndication | # bldgs | total units | LI units | bedroom mix | income targeting | construction |
  federal credits | state credits | [4% credits or MF bonds] | score
Records are anchored on the file number (e.g. 25-01-02) in the left column; the numbers and credit amounts sit on the
anchor line. Total lines and headers are dropped. Records stamped "CREDITS RETURNED" are dropped.
YR_ALLOC = the year of the award list. ALLOCAMT = federal (9% or 4%) annual credit amount awarded.

Usage (from the repo root): python tools/state_pdf/ok.py --out ../hud_src/lihtc/states/extracted
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

U = "https://www.ohfa.org/wp-content/uploads/"
# (award year, kind, url path, label)   kind: 9 = 9% round, 9+4 = 9% round with an extra 4% column, 4 = 4% list
FILES = [
    (2020, "9", "2020/10/2020-1st-Round-9-Percent-Awards.pdf", "2020 1st Round 9% Awards"),
    (2020, "9", "2022/01/2020-2nd-Round-Awards-1.11.2022.pdf", "2020 2nd Round Awards (rev. 1/11/2022)"),
    (2020, "4", "2023/03/2020-4-Percent-Tax-Credit-Awards-Revised-3-30-23.pdf", "2020 4% Tax Credit Awards (rev. 3/30/23)"),
    (2021, "9", "2021/10/2021-1st-Round-9-Percent-Awards.pdf", "2021 1st Round 9% Awards"),
    (2021, "9+4", "2022/11/2021-2nd-Round-Awards-Revised-11.4.2022.pdf", "2021 2nd Round Awards (rev. 11/4/2022)"),
    (2021, "4", "2021/11/2021-4-Percent-Tax-Credit-Awards-Nov-21.pdf", "2021 4% Tax Credit Awards (Nov 2021)"),
    (2022, "9", "2023/02/2022-1st-Round-Awards.pdf", "2022 1st Round 9% Awards"),
    (2022, "9", "2022/11/2022-2nd-Round-Awards.pdf", "2022 2nd Round 9% Awards"),
    (2022, "4", "2024/06/2022-4-Percent-Tax-Credit-Awards.pdf", "2022 4% Tax Credit Awards"),
    (2023, "9", "2023/05/2023-1st-Round-Awards.pdf", "2023 1st Round 9% Awards"),
    (2023, "9", "2023/11/2023-2nd-Round-Awards.pdf", "2023 2nd Round 9% Awards"),
    (2023, "4", "2023/11/2023-4-Percent-Tax-Credit-Awards.pdf", "2023 4% Tax Credit Awards"),
    (2024, "9", "2024/05/2024-1st-Round-9-Percent-Awards.pdf", "2024 1st Round 9% Awards"),
    (2024, "9", "2024/12/2024-2nd-Round-Awards-1.pdf", "2024 2nd Round 9% Awards"),
    (2024, "4", "2024/05/2024-4-Percent-Tax-Credit-Awards-May.pdf", "2024 4% Tax Credit Awards (May)"),
    (2025, "9", "2025/05/2025-1st-Round-Awards-2.pdf", "2025 1st Round 9% Awards"),
    (2025, "9", "2026/02/2025-2nd-Round-Awards.pdf", "2025 2nd Round 9% Awards"),
    (2025, "4", "2025/05/2025-4-Percent-Tax-Credit-Awards-1.pdf", "2025 4% Tax Credit Awards"),
    (2026, "9", "2026/05/2026-1st-Round-Awards.pdf", "2026 1st Round 9% Awards"),
    (2026, "4", "2026/05/2026-4-Percent-Tax-Credit-Awards.pdf", "2026 4% Tax Credit Awards"),
]

# The 2020 4% list (portrait, rev. 3/30/23) has overlapping text: the "Credits Returned" stamp is printed over the
# Pelican Hill record and the cells run together, so its name/location/owner cells are set here as read from the PDF
# page (units and credit amounts still come from the parser and match the PDF total of $3,635,000).
OVERRIDES = {
    (2020, "19-06-44"): {"PROJECT": "Oklahoma Central Region Portfolio (11 properties, files 19-06-44 to 19-06-54)",
                         "PROJ_ADD": "", "PROJ_CTY": "", "PROJ_ZIP": "", "COMPANY": "ADI Preservation OK Portfolio, LLC"},
    (2020, "20-01-27"): {"PROJECT": "Chisholm Springs Scattered Sites and Cities", "PROJ_ADD": "",
                         "PROJ_CTY": "Oklahoma City, Miami, Spencer", "PROJ_ZIP": "73128",
                         "COMPANY": "Chisholm Springs GBD, LLC"},
    (2020, "20-02-32"): {"PROJECT": "The Villages-A Path to Independence", "PROJ_ADD": "8535 N Memorial Dr",
                         "PROJ_CTY": "Owasso", "PROJ_ZIP": "74055", "COMPANY": "The Villages, LP"},
    (2020, "20-03-33"): {"PROJECT": "Pelican Hill", "PROJ_ADD": "4201 N Young Blvd", "PROJ_CTY": "Oklahoma City",
                         "PROJ_ZIP": "73112", "COMPANY": "Pelican Hill Limited Partnership, LLLP", "_returned": True},
}

COUNTIES = """Adair Alfalfa Atoka Beaver Beckham Blaine Bryan Caddo Canadian Carter Cherokee Choctaw Cimarron Cleveland
Coal Comanche Cotton Craig Creek Custer Delaware Dewey Ellis Garfield Garvin Grady Grant Greer Harmon Harper Haskell
Hughes Jackson Jefferson Johnston Kay Kingfisher Kiowa Latimer Le_Flore Lincoln Logan Love Major Marshall Mayes McClain
McCurtain McIntosh Murray Muskogee Noble Nowata Okfuskee Oklahoma Okmulgee Osage Ottawa Pawnee Payne Pittsburg
Pontotoc Pottawatomie Pushmataha Roger_Mills Rogers Seminole Sequoyah Stephens Texas Tillman Tulsa Wagoner Washington
Washita Woods Woodward Various""".replace("_", " ").split()
_C = "(?:%s)" % "|".join(sorted(COUNTIES, key=len, reverse=True))
COUNTY_RX = re.compile(r"(?<!\S)%s(?:\s*(?:,|and|&)\s*%s)*$" % (_C, _C))
FILE_RX = re.compile(r"^\d{2}-\d{2}-\d{2,3}$")
CITY_RX = re.compile(r"^(?P<city>.+?),?\s+(?:OK|Oklahoma|Okla\.?)\.?,?\s*(?:(?P<zip>\d{5})(?:-\d{4})?\b|$)")
MONEY_RX = re.compile(r"\$\s*(\d{1,3}(?: ?\d{1,2})?(?:,\d{3})+|\d+)(?:\.\d\d)?|\$\s*-|(?<!\S)-(?!\S)|(?<!\S)0(?!\S)")


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


def group_lines(objs, tol=2.5):
    out = []
    for w in sorted(objs, key=lambda w: (w["top"], w["x0"])):
        if out and abs(w["top"] - out[-1][0]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(l, key=lambda w: w["x0"])) for t, l in out]


def txt(ws):
    return " ".join(w["text"] for w in ws).strip()


def chars_text(page, top, x_lo, x_hi):
    """Text of the chars on the line at `top` whose x-center lies in [x_lo, x_hi) (splits glued cells)."""
    cs = [c for c in page.chars if abs(c["top"] - top) <= 2.5 and x_lo <= (c["x0"] + c["x1"]) / 2 < x_hi]
    if not cs:
        return ""
    sub = page.filter(lambda o: o.get("object_type") != "char" or o in cs)
    return txt(sub.extract_words())


def parse_pdf(path):
    recs, cur = [], None
    pdf = pdfplumber.open(path)
    for page in pdf.pages:
        ws = page.extract_words()
        lines = group_lines(ws)
        # running header = everything above the lowest header label in the top band of the page
        hdr_words = [w for w in ws if w["top"] < 140 and w["text"] in ("No.", "Score", "Awarded", "Units", "requested", "Bonds", "Credits")]
        hdr_bottom = max((w["bottom"] for w in hdr_words), default=0)
        hdr = [w for w in ws if w["top"] < hdr_bottom + 1]
        county_x = min(w["x0"] for w in hdr if w["text"] == "County") - 8
        body = [(t, l) for t, l in lines if t > hdr_bottom
                and not re.match(r"^\d+ of \d+\b", txt(l)) and not re.search(r"\d{1,2}/\d{1,2}/\d{4} at \d", txt(l))]
        # owner column = leftmost of the most common left edges right of the county column on body lines
        starts = Counter()
        for t, l in body:
            prev = None
            for w in l:
                if w["x0"] > county_x + 12 and (prev is None or w["x0"] - prev["x1"] > 6):
                    starts[round(w["x0"])] += 1
                prev = w
        common = [x for x, n in starts.most_common(6)]
        owner_x = min((x for x in common if x > county_x + 12), default=county_x + 40) - 2
        mgmt_x = min((x for x in common if x > owner_x + 40), default=owner_x + 120) - 2
        bld = [w for w in hdr if w["text"].startswith("Buildings")]
        bld_x = bld[0]["x0"] - 15 if bld else owner_x + 200
        unit_hdr = sorted((w["x0"] + w["x1"]) / 2 for w in hdr if bld and w["text"] in ("Buildings", "Units")
                          and bld[0]["x0"] - 2 <= w["x0"] < bld[0]["x0"] + 110)
        for t, l in body:
            s = txt(l)
            if re.match(r"^(Total|Totals)\b", s) or re.search(r"\bTotal Awarded\b|\bTotals\b", s):
                cur = None
                continue
            is_anchor = FILE_RX.match(l[0]["text"]) and any(w["text"].startswith("$") for w in l)
            if not is_anchor:
                if cur is None:
                    continue
                if re.search(r"CREDITS RETURNED|RETURNED CREDITS", s):
                    cur["returned"] = True
                    continue
                d = [w for w in l if w["x0"] >= cur["dev_x"] - 1 and w["x0"] < owner_x - 1]
                if d:
                    cur["seg"].append(txt(d))
                continue
            fileno = l[0]["text"]
            dev_x = l[1]["x0"] - 3 if len(l) > 1 else l[0]["x1"] + 2
            # name + county share the anchor line; split off the trailing county name(s) (cells can overflow/glue)
            cell = chars_text(page, t, l[0]["x1"] + 1, owner_x)
            m = COUNTY_RX.search(cell)
            if m and m.start() > 0:
                name, county_cell = cell[:m.start()].strip(), m.group(0)
            else:
                name, county_cell = chars_text(page, t, l[0]["x1"] + 1, county_x), chars_text(page, t, county_x, owner_x)
            owner = chars_text(page, t, owner_x, mgmt_x)
            # units: assign anchor-line integers to the nearest units header (bldgs, total, LI)
            right = [w for w in l if w["x0"] >= bld_x]
            ints = [w for w in right if re.fullmatch(r"\d+", w["text"])]
            tot = li = ""
            if len(unit_hdr) == 3:
                vals = {}
                for w in ints:
                    c = (w["x0"] + w["x1"]) / 2
                    k = min(range(3), key=lambda j: abs(unit_hdr[j] - c))
                    if abs(unit_hdr[k] - c) < 18 and k not in vals:
                        vals[k] = w["text"]
                tot, li = vals.get(1, ""), vals.get(2, "")
            if not tot and len(ints) >= 3:
                tot, li = ints[1]["text"], ints[2]["text"]
            # credit amounts in column order: fed, state, third (4% credits or MF bonds); drop the trailing score
            first_d = next((k for k, w in enumerate(right) if w["text"].startswith("$")), None)
            amt_txt = txt([w for w in right[first_d:] if not re.fullmatch(r"\d+\.\d{3,4}", w["text"])]) if first_d is not None else ""
            amts = [int(re.sub(r"[ ,]", "", mm.group(1))) if mm.group(1) else 0 for mm in MONEY_RX.finditer(amt_txt)]
            cur = {"fileno": fileno, "name": name, "county": county_cell, "owner": owner, "seg": [], "dev_x": dev_x,
                   "tot": tot, "li": li, "amts": amts, "returned": False, "page": page.page_number}
            recs.append(cur)
    return recs


def to_rows(r, yr, kind, label, url):
    seg = r["seg"]
    ci = next((i for i, s in enumerate(seg) if CITY_RX.match(s)), None)
    addr_lines = seg[:ci] if ci is not None else seg[:1]
    city = zp = ""
    if ci is not None:
        m = CITY_RX.match(seg[ci])
        city, zp = m.group("city").strip(" ,"), m.group("zip") or ""
    addr = ""
    for a in addr_lines:  # a wrapped line continues the address; a line starting with a number is another site
        addr = a if not addr else addr + ("; " if re.match(r"\d", a) else " ") + a
    if re.match(r"(?i)^(undefined|multiple addresses|scattered sites?|various|tbd)$", addr):
        addr = ""
    fed, st = (r["amts"] + [None, None])[:2]
    third = r["amts"][2] if len(r["amts"]) > 2 else 0
    base = {"PROJECT": r["name"], "PROJ_ADD": addr, "PROJ_CTY": city, "PROJ_ZIP": zp, "YR_ALLOC": str(yr),
            "N_UNITS": r["tot"], "LI_UNITS": r["li"], "COMPANY": r["owner"], "STATE_ID": r["fileno"], "SRC_URL": url}
    ov = OVERRIDES.get((yr, r["fileno"])) if kind == "4" else None
    if ov:
        base.update({k: v for k, v in ov.items() if not k.startswith("_")})
        r["returned"] = r["returned"] or ov.get("_returned", False)
    if r["returned"]:
        return []  # stamped CREDITS RETURNED: the award didn't go forward
    note = ""
    lab = f"Oklahoma Housing Finance Agency {label}"
    out = []
    if kind == "4":
        out.append(dict(base, CREDIT="4% (bond)", ALLOCAMT=str(fed or ""), SRC_LABEL=lab + note))
    else:
        if fed:
            out.append(dict(base, CREDIT="9%", ALLOCAMT=str(fed), SRC_LABEL=lab + note))
        if kind == "9+4" and third:
            out.append(dict(base, CREDIT="4% (bond)", ALLOCAMT=str(third), SRC_LABEL=lab + " (4% credit column)" + note))
        if not out:
            out.append(dict(base, CREDIT="9%", ALLOCAMT="", SRC_LABEL=lab + note))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "ok"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], []
    for yr, kind, path, label in FILES:
        url = U + path
        dest = pdir / path.split("/")[-1]
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        recs = parse_pdf(dest)
        n0 = len(rows)
        for r in recs:
            rows.extend(to_rows(r, yr, kind, label, url))
        print(f"{dest.name}: {len(recs)} records -> {len(rows) - n0} rows")
    with open(out / "ok.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'ok.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

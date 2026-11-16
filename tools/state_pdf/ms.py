"""Mississippi Home Corporation (MHC) Housing Tax Credit recipient lists -> extracted/ms.csv.

Each MHC "<year> HTC Recipient List" PDF is a one-page table of every competitive (9%) application in that year's
round, one line per application:
  2020:      Dev Num | Set Aside | Dev Type | Dev Name | Owner | Dev City | Units | Score | Credit Award | Comments
  2021-2022: Dev Num | Set Aside | Const Type | Dev Name | Owner | Dev County | Units | Score | Credit Amount | Comments
  2023-2026: Dev # | Development Name | [Zipcode (2024 only)] | LIHTC Type | Set-Aside | Owner | County | Units | Score |
             Credit Amount | Comments
The Comments column says whether the application was funded ("Funded from/with <year> ACA") or not ("Not enough
credits to fund", "Did not meet minimum score"). Only funded rows are kept. The trailing units / credit total line and
the code legend are dropped. YR_ALLOC = the list (round) year; the comment's ACA year (often the next year's credit
ceiling, i.e. a forward reservation) is kept in SRC_LABEL. PROJ_CTY is filled only for 2020 (the other years give a
county, not a city); PROJ_ZIP only for 2024. MHC publishes no 4%/bond list, so all rows are CREDIT 9%.

Words are assigned to columns by x position: the name and owner columns are left-aligned, so their left edges are the
most common word x0 values; the county/city column starts a little left of its header word.

Usage (from the repo root): python tools/state_pdf/ms.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
YEARS = range(2020, 2027)
URL = "https://archivemhc.com/htc/{y}/{y}%20RECIPIENT%20LIST.pdf"

DEV_RX = re.compile(r"^\d\d-\d-\d{3}$")
CODE_RX = re.compile(r"^(\d{5}|SW|SCA|NP|NC|R|AR|MF|SF|(AR|NC|R)/(MF|SF))$")
TAIL_RX = re.compile(r"^(?P<loc>.*?)\s*(?P<units>\d+)\s+(?P<score>\d+)\s+\$\s*(?P<amt>[\d ,]+(\.\d\d)?)\s+(?P<cmt>[A-Za-z].*)$")
MS_COUNTIES = set("""Adams Alcorn Amite Attala Benton Bolivar Calhoun Carroll Chickasaw Choctaw Claiborne Clarke Clay
Coahoma Copiah Covington DeSoto Desoto Forrest Franklin George Greene Grenada Hancock Harrison Hinds Holmes Humphreys
Issaquena Itawamba Jackson Jasper Jefferson Jones Kemper Lafayette Lamar Lauderdale Lawrence Leake Lee Leflore Lincoln
Lowndes Madison Marion Marshall Monroe Montgomery Neshoba Newton Noxubee Oktibbeha Panola Perry Pike Pontotoc Prentiss Quitman
Rankin Scott Sharkey Simpson Smith Stone Sunflower Tallahatchie Tate Tippah Tishomingo Tunica Union Walthall Warren
Washington Wayne Webster Wilkinson Winston Yalobusha Yazoo""".split()) | {"Jefferson Davis", "Pearl River"}


def download(url, dest):
    """Plain urllib GET (default user agent), curl (default user agent) as fallback. Returns None or an error."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    err = None
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except Exception as e:
        err, data = f"urllib {type(e).__name__}: {e}", b""
        try:
            data = subprocess.run(["curl", "-sfL", "--max-time", "90", url], capture_output=True, check=True).stdout
        except Exception as e2:
            return f"{err}; curl {type(e2).__name__}"
    if not data.startswith(b"%PDF"):
        return err or "response is not a PDF"
    dest.write_bytes(data)
    return None


def lines_of(page):
    ws = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
    out = []
    for w in ws:
        if out and abs(w["top"] - out[-1][0]) <= 3:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [sorted(l, key=lambda w: w["x0"]) for _, l in out]


def txt(ws):
    return " ".join(w["text"] for w in ws).strip()


def parse_pdf(path):
    """Return (rows, total_line_text). Each row: dict dev, name, owner, loc, zip, units, score, amt, cmt."""
    rows, totals = [], []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines = lines_of(page)
            recs = [l for l in lines if DEV_RX.match(l[0]["text"])]
            if not recs:
                continue
            hdr = [w for l in lines if l[0]["top"] < recs[0][0]["top"] for w in l]
            loc_hdr = [w for w in hdr if w["text"] in ("County", "City")]
            loc_x = min(w["x0"] for w in loc_hdr)
            dev = [w for w in hdr if w["text"] == "Dev" and w["x0"] < loc_x and loc_x - w["x0"] < 25]
            if dev:  # "Dev City" / "Dev County": the header starts at "Dev"
                loc_x = dev[0]["x0"]
            loc_x -= 16
            # left-aligned name / owner columns: the two most common x0 values between the dev # and the loc column
            xs = Counter()
            for l in recs:
                for w in l[1:]:
                    if w["x0"] < loc_x and not CODE_RX.match(w["text"]):
                        xs[round(w["x0"])] += 1
            edges = sorted(x for x, n in xs.most_common(2) if n >= 0.6 * len(recs))
            if len(edges) != 2:
                raise ValueError(f"{path.name}: cannot find name/owner column edges: {xs.most_common(4)}")
            name_x, owner_x = edges[0] - 2, edges[1] - 2
            for l in recs:
                name = [w for w in l[1:] if name_x <= w["x0"] < owner_x]
                zips = [w["text"] for w in name if re.match(r"^\d{5}$", w["text"])]
                while name and CODE_RX.match(name[-1]["text"]) and name[-1]["x0"] > name_x + 40:
                    name.pop()  # 2023+: LIHTC type / set-aside / zipcode codes sit right of the name
                owner = [w for w in l if owner_x <= w["x0"] < loc_x]
                tail = txt([w for w in l if w["x0"] >= loc_x])
                m = TAIL_RX.match(tail)
                if not m:
                    raise ValueError(f"{path.name}: cannot parse tail {tail!r} of {txt(l)!r}")
                rows.append({"dev": l[0]["text"], "name": txt(name), "owner": txt(owner), "loc": m["loc"].strip(),
                             "zip": zips[0] if zips else "", "units": int(m["units"]), "score": int(m["score"]),
                             "amt": round(float(re.sub(r"[ ,]", "", m["amt"]))), "cmt": m["cmt"].strip(),
                             "line": txt(l)})
            last = recs[-1][0]["top"]
            totals += [txt(l) for l in lines if l[0]["top"] > last and re.match(r"^[\d,]+\s+\$?[\d,]+(\.\d\d)?$", txt(l))]
    return rows, totals


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output directory (../hud_src/lihtc/states/extracted)")
    ap.add_argument("--pdf-dir", help="download directory (default: <out>/../pdf/ms)")
    a = ap.parse_args()
    out_dir = Path(a.out)
    pdf_dir = Path(a.pdf_dir) if a.pdf_dir else out_dir.parent / "pdf" / "ms"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    out, problems = [], []
    for y in YEARS:
        url = URL.format(y=y)
        dest = pdf_dir / f"ms_{y}_recipient_list.pdf"
        err = download(url, dest)
        if err:
            print(f"SKIP {y}: {err}", file=sys.stderr)
            continue
        rows, totals = parse_pdf(dest)
        # checks: every row's county is a MS county (2021+), units / credit sums equal the printed total line
        for r in rows:
            if y >= 2021 and r["loc"] not in MS_COUNTIES:
                problems.append(f"{y} {r['dev']}: county {r['loc']!r} not a MS county (as printed)")
        funded = [r for r in rows if re.match(r"(?i)^funded\b", r["cmt"])]
        su, sa = sum(r["units"] for r in funded), sum(r["amt"] for r in funded)  # the total line covers funded rows
        tot = totals[0] if totals else ""
        tu, ta = (lambda p: (int(p[0].replace(",", "")), round(float(re.sub(r"[$,]", "", p[1])))))(tot.split()) if tot else (None, None)
        ok = "= printed total" if (su, sa) == (tu, ta) else f"MISMATCH (printed {tu} units / ${ta})"
        other = Counter(r["cmt"] for r in rows if r not in funded)
        print(f"{y}: {len(rows)} applications; {len(funded)} funded ({su} units, ${sa:,} {ok}); dropped {dict(other)}")
        for r in funded:
            aca = re.search(r"\b(20\d\d)\s+ACA\b", r["cmt"])
            out.append({"PROJECT": r["name"], "PROJ_ADD": "", "PROJ_CTY": r["loc"] if y == 2020 else "",
                        "PROJ_ZIP": r["zip"], "YR_ALLOC": y, "CREDIT": "9%", "N_UNITS": r["units"], "LI_UNITS": "",
                        "COMPANY": r["owner"], "ALLOCAMT": r["amt"], "STATE_ID": r["dev"],
                        "SRC_LABEL": f"Mississippi Home Corp. {y} Housing Tax Credit recipient list"
                                     + (f" (funded from {aca[1]} ACA)" if aca else ""),
                        "SRC_URL": url})
    for p in problems:
        print("NOTE", p, file=sys.stderr)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "ms.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows -> {out_dir / 'ms.csv'}")


if __name__ == "__main__":
    main()

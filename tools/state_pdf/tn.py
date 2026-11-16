"""Tennessee Housing Development Agency (THDA) LIHTC award lists -> extracted/tn.csv.

thda.org answers plain HTTP clients with a bot challenge, so only the copies THDA serves from its CloudFront CDN
(dogvxws799i6n.cloudfront.net/wp-content/uploads/<file>) are used; files that return 403 there are skipped and
reported. Files:
  MF_2026-Competitive-Awards-Final-07.07.2026.pdf   2026 competitive (9%) awards, grouped by set-aside / priority:
      THDA # | Development Name | County | Pool / Priority | LIHTC Reserved | LIHTC Units | Score | Development Group
      (cells wrap onto 2-3 lines). The last page (National Housing Trust Fund awards, not LIHTC) is skipped.
  2026-MTBA-Round-1-Allocations-ADA.pdf              2026 tax-exempt bond round 1 (4%):
      THDA # | Group | Development Name | County | MTBA Allocated | 42m Awarded | PD Score | LIHTC Units | Dev. Group
      The withdrawn application ($0) is dropped; the supplemental allocation to an earlier deal (24-219) is kept.
  2024-MTBA-Listing-for-Website-Closing_Carryforward.pdf   2024 bond deals that closed (with 42(m) 4% credit
      reserved, street address, city, ZIP, total / LIHTC units), then "Carryforward Requests" (2024 bond authority
      carried forward, not yet closed; no credit amount). Supplemental-MTBA-only rows with no 42M credit ("$ -", for
      deals that closed earlier) are dropped.
The competitive and 2026 bond lists give a county, not a city, so PROJ_CTY is blank there. LI_UNITS = "LIHTC Units".

Cells are read by x position: each column is a fixed x band (checked against the header words) and a word belongs to
the band holding the midpoint of each of its characters, so glued text such as "37909Knox" or
"Kings HighwayMurfreesboro" splits at the column edge. A record runs from its THDA # (or name) line down to the next
record or heading.

Usage (from the repo root): python tools/state_pdf/tn.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
CDN = "https://dogvxws799i6n.cloudfront.net/wp-content/uploads/"
F_COMP = "MF_2026-Competitive-Awards-Final-07.07.2026.pdf"
F_MTBA26 = "2026-MTBA-Round-1-Allocations-ADA.pdf"
F_MTBA24 = "2024-MTBA-Listing-for-Website-Closing_Carryforward.pdf"
# other THDA lists known from the survey; all are on thda.org (bot check) and 403 on the CDN mirror -> tried, reported
OTHER = ["2025-MTBA-Round-One-Data-for-Website.pdf", "2024-Competitive-LIHTC-Listing.pdf",
         "2025-Preliminary-Ranking-for-Competitive-LIHTC-_NHTF.pdf"]

ID_RX = re.compile(r"^\d\d-\d{3}$")
STOP_RX = re.compile(r"Category|^THDA #|^Name Reserved|^Updated|^TOTAL|^Tax Credits Reserved|Totals|^Last Updated|"
                     r"Carryforward Requests|^Signature|^Allocated|^Awarded|^MTBA Amount|^Constr|^Per Section|"
                     r"Set-Aside \$|^MTBA Allocated|^Units$|^\d+$")  # last two: column-label / page-number footer lines


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
            return f"{err}; curl {type(e2).__name__} (exit {getattr(e2, 'returncode', '?')})"
    if not data.startswith(b"%PDF"):
        return err or "response is not a PDF (bot challenge?)"
    dest.write_bytes(data)
    return None


def lines(words, tol=3):
    out = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(w["top"] - out[-1][0]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(l, key=lambda w: w["x0"])) for t, l in out]


def txt(ws):
    return " ".join(w["text"] for w in ws).strip()


def band_words(page, x0, x1, top, bottom):
    """Words built from the chars whose midpoint lies in [x0, x1) x [top, bottom)."""
    sub = page.filter(lambda o: o.get("object_type") != "char" or
                      (x0 <= (o["x0"] + o["x1"]) / 2 < x1 and top <= o["top"] < bottom))
    return sub.extract_words()


def check_header(page, expect, top_max=None):
    """expect: {word: x0}; every word must be found on the page within 6pt of its x0."""
    ws = page.extract_words()
    for word, x in expect.items():
        if not any(w["text"] == word and abs(w["x0"] - x) < 6 and (top_max is None or w["top"] < top_max) for w in ws):
            raise ValueError(f"page {page.page_number}: header word {word!r} not at x={x}; layout changed?")


def records(page, cols, anchor_col, top=0, bottom=None, anchor_rx=ID_RX):
    """Split the page (between top and bottom) into records; return list of {col: text} (+ '_top')."""
    bottom = bottom or page.height
    allw = [w for w in page.extract_words() if top <= w["top"] < bottom]
    stops = [t for t, l in lines(allw) if STOP_RX.search(txt(l))]
    ax0, ax1 = cols[anchor_col]
    anchors = [t for t, l in lines(band_words(page, ax0, ax1, top, bottom)) if anchor_rx.match(txt(l))]
    recs = []
    for i, t in enumerate(anchors):
        end = min([a for a in anchors[i + 1:]] + [s for s in stops if s > t + 1] + [bottom]) - 1
        rec = {"_top": t}
        for c, (x0, x1) in cols.items():
            rec[c] = " ".join(txt(l) for _, l in lines(band_words(page, x0, x1, t - 3, end)))
        recs.append(rec)
    return recs


def money(s):
    s = re.sub(r"[$,\s]", "", s or "")
    return round(float(s)) if re.match(r"^\d+(\.\d+)?$", s) else None


def intval(s):
    s = re.sub(r"[,\s]", "", s or "")
    return int(s) if s.isdigit() else None


def parse_comp(path):
    """2026 competitive awards. Column bands from the header words of each section."""
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            ptxt = page.extract_text() or ""
            if "National Housing Trust Fund Awards" in ptxt or "THDA #" not in ptxt:
                continue
            ws = page.extract_words()
            hdrs = [(t, l) for t, l in lines(ws) if txt(l).startswith("THDA #")]
            for k, (ht, hl) in enumerate(hdrs):
                xs = {}
                for w in hl:
                    xs.setdefault(w["text"], []).append(w["x0"])
                d1, d2 = xs["Development"][0], xs["Development"][1]
                l1, l2 = xs["LIHTC"][0], xs["LIHTC"][1]
                cols = {"id": (0, d1 - 4), "name": (d1 - 4, xs["County"][0] - 4), "county": (xs["County"][0] - 4, xs["Pool"][0] - 4),
                        "pool": (xs["Pool"][0] - 4, l1 - 4), "amt": (l1 - 4, l2 - 4), "units": (l2 - 4, xs["Score"][0] - 4),
                        "score": (xs["Score"][0] - 4, d2 - 4), "group": (d2 - 4, page.width)}
                bottom = hdrs[k + 1][0] - 30 if k + 1 < len(hdrs) else page.height
                out += records(page, cols, "id", ht + 1, bottom)
    return out


MTBA26_COLS = {"id": (50, 120), "group": (120, 305), "name": (305, 445), "county": (445, 515), "mtba": (515, 590),
               "c42": (590, 665), "score": (665, 720), "units": (720, 765), "dev": (765, 1008)}
MTBA26_HDR = {"THDA": 58, "Group": 125, "County": 447, "42m": 593, "LIHTC": 724}

MTBA24_COLS = {"id": (15, 40), "prev": (40, 81), "name": (81, 168), "addr": (168, 233), "city": (233, 290),
               "zipcty": (290, 345), "supp": (345, 380), "mtba": (380, 465), "date": (465, 500), "c42": (500, 550),
               "total": (620, 700), "li": (700, 760)}
MTBA24_HDR = {"#Previous": 38, "Address": 205, "City": 235, "Zip": 278, "Supplemental": 350, "42M": 501, "LIHTC": 663}
CF24_COLS = {"id": (15, 40), "prev": (40, 81), "name": (81, 168), "addr": (168, 233), "city": (233, 290),
             "zipcty": (290, 345), "mtba": (345, 405), "total": (495, 555), "li": (555, 597)}
CF24_HDR = {"Carryforward": 350, "Total": 499, "LIHTC": 548}


def parse_mtba26(path):
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            check_header(page, MTBA26_HDR)
            out += records(page, MTBA26_COLS, "id")
    return out


def parse_mtba24(path):
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        cf_top = next(w["top"] for w in page.extract_words() if w["text"] == "Carryforward" and w["x0"] > 380)
        check_header(page, MTBA24_HDR, top_max=cf_top)
        hdr_top = min(w["top"] for w in page.extract_words() if w["text"] == "#Previous")
        # closing list: records anchored on the name column (the supplemental row for Whispering Oaks has no THDA #)
        closed = records(page, MTBA24_COLS, "name", hdr_top + 4, cf_top - 1, anchor_rx=re.compile(r"\S"))
        ws = page.extract_words()
        cf_hdr = max(w["bottom"] for w in ws if w["text"] in ("Amount", "Rehab") and w["top"] > cf_top)
        carry = records(page, CF24_COLS, "id", cf_hdr + 1)
        for r in (closed + carry):
            m = re.match(r"^(\d{5})\s*(.*)$", r["zipcty"])
            r["zip"], r["county"] = (m[1], m[2]) if m else ("", r["zipcty"])
        tot = [txt(l) for t, l in lines(ws) if "Totals" in txt(l)]
    return closed, carry, tot


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output directory (../hud_src/lihtc/states/extracted)")
    ap.add_argument("--pdf-dir", help="download directory (default: <out>/../pdf/tn)")
    a = ap.parse_args()
    out_dir = Path(a.out)
    pdf_dir = Path(a.pdf_dir) if a.pdf_dir else out_dir.parent / "pdf" / "tn"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    have = {}
    for f in [F_COMP, F_MTBA26, F_MTBA24] + OTHER:
        err = download(CDN + f, pdf_dir / f)
        if err:
            print(f"SKIP {f}: {err}", file=sys.stderr)
        else:
            have[f] = pdf_dir / f
    out = []

    if F_COMP in have:
        recs = parse_comp(have[F_COMP])
        url = CDN + F_COMP
        print(f"{F_COMP}: {len(recs)} awards, ${sum(money(r['amt']) or 0 for r in recs):,} / "
              f"{sum(intval(r['units']) or 0 for r in recs)} LIHTC units (printed TOTAL $21,789,055 / 1,072)")
        for r in recs:
            out.append({"PROJECT": r["name"], "PROJ_ADD": "", "PROJ_CTY": "", "PROJ_ZIP": "", "YR_ALLOC": 2026,
                        "CREDIT": "9%", "N_UNITS": "", "LI_UNITS": intval(r["units"]), "COMPANY": r["group"],
                        "ALLOCAMT": money(r["amt"]), "STATE_ID": r["id"],
                        "SRC_LABEL": "THDA 2026 competitive LIHTC awards (updated 7/7/2026)", "SRC_URL": url})

    if F_MTBA26 in have:
        recs = parse_mtba26(have[F_MTBA26])
        url = CDN + F_MTBA26
        print(f"{F_MTBA26}: {len(recs)} rows, MTBA ${sum(money(r['mtba']) or 0 for r in recs):,} / "
              f"{sum(intval(r['units']) or 0 for r in recs)} LIHTC units (printed TOTAL $342,924,567 / 2,877)")
        for r in recs:
            if not money(r["c42"]) or "Withdrawn" in r["group"]:
                print(f"  drop {r['id']} {r['name']}: {r['group']} / 42m {r['c42']}")
                continue
            supp = r["group"].startswith("8: Supplemental")
            out.append({"PROJECT": r["name"], "PROJ_ADD": "", "PROJ_CTY": "", "PROJ_ZIP": "", "YR_ALLOC": 2026,
                        "CREDIT": "4% (bond)", "N_UNITS": "", "LI_UNITS": intval(r["units"]), "COMPANY": r["dev"],
                        "ALLOCAMT": money(r["c42"]), "STATE_ID": r["id"],
                        "SRC_LABEL": "THDA 2026 tax-exempt bond round 1 noncompetitive allocations"
                                     + (" (supplemental allocation)" if supp else ""), "SRC_URL": url})

    if F_MTBA24 in have:
        closed, carry, tot = parse_mtba24(have[F_MTBA24])
        url = CDN + F_MTBA24
        print(f"{F_MTBA24}: {len(closed)} closing rows, MTBA ${sum(money(r['mtba']) or 0 for r in closed):,}, "
              f"42M ${sum(money(r['c42']) or 0 for r in closed):,}, units {sum(intval(r['total']) or 0 for r in closed)}"
              f"/{sum(intval(r['li']) or 0 for r in closed)}; {len(carry)} carryforward rows, "
              f"${sum(money(r['mtba']) or 0 for r in carry):,}, units {sum(intval(r['total']) or 0 for r in carry)}"
              f"/{sum(intval(r['li']) or 0 for r in carry)}  (printed: {' || '.join(tot)})")
        for r in closed:
            if not money(r["c42"]):
                print(f"  drop {r['id'] or '(no #)'} {r['name']}: supplemental MTBA {r['mtba']}, no 42M credit")
                continue
            out.append({"PROJECT": r["name"], "PROJ_ADD": r["addr"], "PROJ_CTY": r["city"], "PROJ_ZIP": r["zip"],
                        "YR_ALLOC": int(r["date"][-4:]) if re.search(r"20\d\d$", r["date"]) else 2024,
                        "CREDIT": "4% (bond)", "N_UNITS": intval(r["total"]), "LI_UNITS": intval(r["li"]),
                        "COMPANY": "", "ALLOCAMT": money(r["c42"]), "STATE_ID": r["id"],
                        "SRC_LABEL": "THDA 2024 multifamily tax-exempt bond authority closing listing", "SRC_URL": url})
        for r in carry:
            out.append({"PROJECT": r["name"], "PROJ_ADD": r["addr"], "PROJ_CTY": r["city"], "PROJ_ZIP": r["zip"],
                        "YR_ALLOC": 2024, "CREDIT": "4% (bond)", "N_UNITS": intval(r["total"]),
                        "LI_UNITS": intval(r["li"]), "COMPANY": "", "ALLOCAMT": "", "STATE_ID": r["id"],
                        "SRC_LABEL": "THDA 2024 multifamily tax-exempt bond authority carryforward requests "
                                     "(not closed in 2024; no credit amount listed)", "SRC_URL": url})

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "tn.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows -> {out_dir / 'tn.csv'}")


if __name__ == "__main__":
    main()

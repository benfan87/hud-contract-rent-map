"""New Hampshire Housing (NHHFA) multifamily development tables -> extracted/nh.csv.

NH Housing publishes no LIHTC award list with addresses; the best public project lists are the annual-report tables
"Multifamily Housing: Commitments & Under Construction" and "... Completed Developments":
  - FY2025 (July 2024-June 2025), "NH-Housing-FY25-Multifamily-Housing-Division.pdf": Development Name, Location (town),
    Developer, Units, Occupancy, Type, Funding Sources & PBVs. Funding names the credit explicitly ("9% LIHTC" or
    "Tax-Exempt Bonds, 4% LIHTC"); rows with neither (AHF / HTF / HOME-only supportive housing) are not LIHTC and dropped.
  - FY2024 annual report: same two tables but WITHOUT the funding column. A FY2024 row is kept only when its name
    carries the credit ("Monahan Manor 4%"); rows also in the FY2025 tables are covered there; the other FY2024 rows
    cannot be confirmed as LIHTC and are listed on stdout, not written.
No street address, ZIP, award amount or award year in the tables: PROJ_CTY = town, YR_ALLOC blank (the report fiscal
year and table are in SRC_LABEL). A project listed in both years / both tables is written once (first seen: FY2025).

Usage (from the repo root): python tools/state_pdf/nh.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

BASE = "https://www.nhhousing.org/wp-content/uploads/2026/05/"
FILES = [  # (fiscal year, file, has funding column)
    (2025, "NH-Housing-FY25-Multifamily-Housing-Division.pdf", True),
    (2024, "NH-Housing-FY24-Annual-Report.pdf", False),
]
FY = {2025: "July 2024-June 2025", 2024: "July 2023-June 2024"}


def curl(url, timeout=300):
    p = subprocess.run(["curl", "-sSfL", "--max-time", str(timeout), url], capture_output=True)
    if p.returncode:
        raise RuntimeError(f"curl exit {p.returncode}: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout


def download(url, dest):
    """Plain urllib GET (default Python user agent), falling back to plain curl on an HTTP 403.
    Returns None on success, else an error string."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    try:
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            data = curl(url)
    except Exception as e:  # 403 / bot block / network: skip and report
        return f"{type(e).__name__}: {e}"
    if not data.startswith(b"%PDF"):
        return "response is not a PDF"
    dest.write_bytes(data)
    return None


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("-\n", "-")).strip()


STOP = {"the", "at", "apartment", "apt", "phase", "senior", "residence", "village", "housing", "development"}


def norm(s):
    """Name key that survives the FY24/FY25 wording changes ("Avery Lane Phase I" = "Avery Lane Apartments Phase I")
    but keeps phase numbers and the 4%/9% tag apart."""
    s = re.sub(r"\(.*?\)", " ", (s or "").lower().replace("&", " and "))
    ws = [w.rstrip("s") if len(w) > 3 else w for w in re.findall(r"[a-z0-9]+%?", s)]
    return frozenset(w for w in ws if w not in STOP)


def section(text):
    t = text.upper()
    if "COMMITMENTS & UNDER CONSTRUCTION" in t:
        return "Commitments & Under Construction"
    if "COMPLETED DEVELOPMENTS" in t:
        return "Completed Developments"
    return None


def credit_of(funding):
    f = funding.upper()
    c9, c4 = "9% LIHTC" in f, "4% LIHTC" in f
    return "9%" if c9 and not c4 else "4% (bond)" if c4 and not c9 else ("both" if c9 else "")


def parse_fy25(path):
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            sec = section(page.extract_text() or "")
            if not sec:
                continue
            for t in page.extract_tables():
                if not t or not (t[0][0] or "").startswith("Development Name"):
                    continue
                for r in t[1:]:
                    c = [clean(x) for x in r]
                    if len(c) < 7 or not c[0] or c[0].lower().startswith("total") or not re.fullmatch(r"[\d,]+", c[3]):
                        continue
                    out.append({"name": c[0], "town": c[1], "dev": c[2], "units": c[3].replace(",", ""),
                                "occ": c[4], "type": c[5], "funding": c[6], "sec": sec})
    return out


def parse_fy24(path):
    """FY24 tables come out of pdfplumber as one cell per line, so split words into columns by header x positions."""
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            sec = section(page.extract_text() or "")
            if not sec:
                continue
            words = page.extract_words()
            hdr = [w for w in words if w["text"] in ("Development", "Location", "Developer", "Units", "Occupancy", "Type")]
            ys = sorted({round(w["top"]) for w in hdr if w["text"] == "Location"})
            if not ys:
                continue
            ytop = ys[0]
            xs = {}
            for w in hdr:
                if abs(round(w["top"]) - ytop) <= 2:
                    xs.setdefault(w["text"], w["x0"])
            if len(xs) < 6:
                continue
            edges = [xs["Location"], xs["Developer"], xs["Units"], xs["Occupancy"], xs["Type"]]
            body = [w for w in words if w["top"] > ytop + 5]
            lines = []
            for w in sorted(body, key=lambda w: (round(w["top"]), w["x0"])):
                if lines and abs(w["top"] - lines[-1][0]) <= 2.5:
                    lines[-1][1].append(w)
                else:
                    lines.append([w["top"], [w]])
            cur = None
            for _, ws in lines:
                cols = [[] for _ in range(6)]
                for w in ws:
                    i = sum(1 for e in edges if w["x0"] >= e - 2)
                    cols[i].append(w["text"])
                cols = [" ".join(c) for c in cols]
                if cols[0].upper().startswith("TOTAL"):
                    break
                if re.fullmatch(r"\d[\d,]*", cols[3].strip()):
                    cur = {"name": cols[0], "town": cols[1], "dev": cols[2], "units": cols[3].replace(",", ""),
                           "occ": cols[4], "type": cols[5], "funding": "", "sec": sec}
                    out.append(cur)
                elif cur and any(cols) and not cols[3]:
                    for k, i in (("name", 0), ("dev", 2), ("occ", 4), ("type", 5)):
                        if cols[i]:
                            cur[k] = (cur[k] + " " + cols[i]).strip()
                    if not cols[0] and not cols[2] and not cols[4] and not cols[5]:
                        cur = None  # caption text below the table
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "nh"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, seen, skipped, unconfirmed = [], {}, [], []
    for fy, fn, has_funding in FILES:
        url = BASE + fn
        dest = pdir / fn
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        recs = parse_fy25(dest) if has_funding else parse_fy24(dest)
        kept = dropped = dup = 0
        for r in recs:
            if has_funding:
                cr = credit_of(r["funding"])
                if cr == "both":
                    print(f"  {fn}: {r['name']} lists both 9% and 4% LIHTC - CREDIT left blank")
                    cr = ""
                elif not cr:
                    dropped += 1
                    seen.setdefault((frozenset(w for w in norm(r["name"]) if not w.endswith("%")),
                                     r["town"].lower()), set()).add("not LIHTC")
                    continue
            else:
                m = re.search(r"\b([49])%", r["name"])
                cr = ("9%" if m.group(1) == "9" else "4% (bond)") if m else None
            key = (frozenset(w for w in norm(r["name"]) if not w.endswith("%")), r["town"].lower())
            if key in seen and (cr is None or cr in seen[key]):
                dup += 1
                continue
            if cr is None:
                unconfirmed.append((fy, r["sec"], r["name"], r["town"], r["units"]))
                continue
            seen.setdefault(key, set()).add(cr)
            label = f"New Hampshire Housing FY{fy} ({FY[fy]}) Multifamily Housing: {r['sec']}"
            label += (f"; funding: {r['funding']}" if r["funding"] else "; no funding column, credit from project name")
            label += f"; {r['occ']}, {r['type']}; no award year given"
            rows.append({"PROJECT": r["name"], "PROJ_ADD": "", "PROJ_CTY": r["town"], "PROJ_ZIP": "", "YR_ALLOC": "",
                         "CREDIT": cr, "N_UNITS": r["units"], "LI_UNITS": "", "COMPANY": r["dev"], "ALLOCAMT": "",
                         "STATE_ID": "", "SRC_LABEL": label, "SRC_URL": url})
            kept += 1
        print(f"{fn}: {len(recs)} table rows, kept {kept}, not LIHTC {dropped}, already listed {dup}")
    with open(out / "nh.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'nh.csv'}")
    if unconfirmed:
        print(f"{len(unconfirmed)} FY2024 rows not written (no funding column, LIHTC not confirmed):")
        for u in unconfirmed:
            print("   ", u)
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

"""Connecticut Housing Finance Authority (CHFA) LIHTC award lists -> extracted/ct.csv.

9% lists ("Tax Credit Application Scoring - <year> Awards", 1 page each, 2020-2026): rows grouped by
"Classification:" with columns  Total Units | [*] Project Name | Town | Total Points | Credit Award | LIHTC Equity |
Developer - Contact.  The text has no delimiters, so columns are cut by word x-position (the layout is identical in all
seven files). '*' marks a non-profit developer. Sub Total / TOTALS lines are dropped. Every listed row is an award.
CREDIT 9%, ALLOCAMT = annual credit award. No street address or ZIP is published (town only). Project names and towns
are truncated by the report at a fixed width (e.g. "... Housing Redevelo", "Montville (Unca"); an unclosed
parenthetical in a town is dropped ("Montville (Unca" -> "Montville").

4% lists ("4% LIHTC Tax Credit Board Approval", by quarter): Project Name | Project Town | Project Units only.
CREDIT 4% (bond), YR_ALLOC = year of the board-approval quarter, no amount.

Usage (from the repo root): python tools/state_pdf/ct.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

# (year, kind, url)
FILES = [
    (2020, "9", "https://www.chfa.org/assets/1/6/2020_-_LIHTC_Award_List_-_9_1.pdf"),
    (2021, "9", "https://www.chfa.org/assets/1/6/2021_LIHTC_Award_List_-_9_.pdf"),
    (2022, "9", "https://www.chfa.org/assets/1/6/2022_-_LIHTC_Award_List_-_9_.pdf"),
    (2023, "9", "https://www.chfa.org/assets/1/6/2023_-_LIHTC_Award_List_-_9_.pdf"),
    (2024, "9", "https://www.chfa.org/assets/1/19/lihtcscoring.pdf"),
    (2025, "9", "https://www.chfa.org/assets/1/19/lihtcscoring1.pdf"),
    (2026, "9", "https://www.chfa.org/assets/1/19/2026_award_list.pdf"),
    (2023, "4", "https://www.chfa.org/assets/1/19/4_LIHTC_Board_Approval_Q4_2023.pdf"),
    (2024, "4", "https://www.chfa.org/assets/1/19/4_LIHTC_Board_Approvals_2024.pdf"),
]


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


def lines_of(page, tol=3.0):
    ws = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
    out = []
    for w in ws:
        if out and abs(w["top"] - out[-1][0]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [sorted(l, key=lambda w: w["x0"]) for t, l in out]


def txt(ws):
    return " ".join(w["text"] for w in ws).strip()


MONEY = re.compile(r"^\$[\d,]+$")


def clean_town(s):
    s = s.strip()
    if "(" in s and ")" not in s:  # truncated "(Uncasville" style village note
        s = s[: s.index("(")].strip()
    return s


def parse_9(path, yr):
    """Return (rows, header_year). Column cuts: name < 225 <= town < 300 <= points < 360 <= credit < 445 <= equity < 515
    <= developer."""
    pdf = pdfplumber.open(path)
    rows, hdr_year, cls = [], None, ""
    for page in pdf.pages:
        for ws in lines_of(page):
            s = txt(ws)
            m = re.match(r"^(\d{4}) Awards$", s)
            if m:
                hdr_year = int(m.group(1))
            if s.startswith("Classification:"):
                cls = s.split(":", 1)[1].strip()
                continue
            if "Sub Total" in s or "TOTALS" in s or not re.match(r"^\d+\b", s):
                continue
            money = [w for w in ws if MONEY.match(w["text"])]
            if len(money) < 2:
                continue
            units = ws[0]["text"]
            nonprofit = any(w["text"] == "*" and w["x0"] < 66 for w in ws)
            name = txt([w for w in ws[1:] if 60 <= w["x0"] < 225])
            town = clean_town(txt([w for w in ws if 225 <= w["x0"] < 300]))
            credit = next(w["text"] for w in ws if 360 <= w["x0"] < 445 and MONEY.match(w["text"]))
            dev = txt([w for w in ws if w["x0"] >= 515])
            company = re.split(r"\s+-(?:\s+|$)", dev, maxsplit=1)[0].strip()
            rows.append({"PROJECT": name, "PROJ_CTY": town, "N_UNITS": units, "COMPANY": company,
                         "ALLOCAMT": credit.replace("$", "").replace(",", ""), "_cls": cls, "_np": nonprofit})
    return rows, hdr_year


def parse_4(path):
    """Return list of (year, quarter, name, town, units)."""
    pdf = pdfplumber.open(path)
    out, yr, q, town_x, units_x = [], None, None, 280, 440
    for page in pdf.pages:
        for ws in lines_of(page):
            s = txt(ws)
            m = re.match(r"^Quarter (\d) (\d{4})$", s)
            if m:
                q, yr = int(m.group(1)), int(m.group(2))
                continue
            if s.startswith("Project Name"):
                pj = [w for w in ws if w["text"] == "Project"]
                if len(pj) >= 3:
                    town_x, units_x = pj[1]["x0"] - 5, pj[2]["x0"] - 5
                continue
            if "4% LIHTC" in s and "Board" in s:
                continue
            if yr is None or not re.match(r"^\d+$", ws[-1]["text"]):
                continue
            name = txt([w for w in ws if w["x0"] < town_x])
            town = txt([w for w in ws if town_x <= w["x0"] < units_x])
            out.append((yr, q, name, town, ws[-1]["text"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "ct"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], []
    for yr, kind, url in FILES:
        dest = pdir / url.rsplit("/", 1)[1]
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        if kind == "9":
            recs, hy = parse_9(dest, yr)
            if hy != yr:
                print(f"WARNING {dest.name}: header year {hy} != expected {yr}", file=sys.stderr)
            for r in recs:
                r.update({"YR_ALLOC": str(yr), "CREDIT": "9%", "SRC_URL": url,
                          "SRC_LABEL": f"CHFA {yr} 9% LIHTC awards (Tax Credit Application Scoring - {yr} Awards; "
                                       f"classification: {r['_cls']}"
                                       + ("; non-profit developer" if r["_np"] else "") + ")"})
                rows.append({k: r.get(k, "") for k in COLS})
            print(f"{dest.name}: {len(recs)} 9% awards")
        else:
            recs = parse_4(dest)
            for y, q, name, town, units in recs:
                rows.append({k: v for k, v in {
                    "PROJECT": name, "PROJ_CTY": town, "N_UNITS": units, "YR_ALLOC": str(y), "CREDIT": "4% (bond)",
                    "SRC_URL": url,
                    "SRC_LABEL": f"CHFA 4% LIHTC board approvals, Q{q} {y} (no credit amount listed)"}.items()})
            print(f"{dest.name}: {len(recs)} 4% approvals")
    rows = [{k: r.get(k, "") for k in COLS} for r in rows]
    with open(out / "ct.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'ct.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

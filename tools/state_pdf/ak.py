"""Alaska Housing Finance Corp. (AHFC) LIHTC reservation lists -> standard CSV.

Each yearly "LIHTC Reservation List" PDF is one block per project (not a table):
  Project #n - <Name>
  Developer Information (left column: Attn, entity, address, phone, email)
  Project Information   (right column: Project Type, Location (community), Unit Count / Type,
                         "9% LIHTCs Allocated: $x" or "4% LIHTCs Allocated: $x", subsidies)
No street address / ZIP for the project (the address in the block is the developer's).
Usage: python tools/state_pdf/ak.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import urllib.request

import pdfplumber

PAGE = "https://www.ahfc.us/pros/homelessness/development-grants/low-income-housing-tax-credit"
FILES = [  # (year, url)
    (2020, "https://www.ahfc.us/download_file/view/6242/551"),
    (2021, "https://www.ahfc.us/download_file/view/6792/551"),
    (2022, "https://www.ahfc.us/download_file/view/7387/551"),
    (2023, "https://www.ahfc.us/download_file/view/7913/551"),
    (2024, "https://www.ahfc.us/download_file/view/8436/551"),
    (2025, "https://www.ahfc.us/download_file/view/9277/551"),
    (2026, "https://www.ahfc.us/download_file/view/4077c883-c7fc-4115-9f8d-f35229d106d9/551"),
]
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
    except Exception as e:  # 403 / blocked / 404: skip and report
        print(f"SKIP {url}: {e}")
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def clean(s):
    s = (s or "").replace("�", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def lines_of(words, tol=3):
    """Group words into lines by 'top'; returns list of (top, [words sorted by x])."""
    out = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if out and abs(out[-1][0] - w["top"]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(ws, key=lambda w: w["x0"])) for t, ws in out]


def parse(path, year, url):
    rows = []
    with pdfplumber.open(path) as pdf:
        words = []
        for pi, pg in enumerate(pdf.pages):  # stack pages into one coordinate space
            for w in pg.extract_words():
                w = dict(w)
                w["top"] += pi * 10000
                words.append(w)
    lines = lines_of(words)
    # block starts: line beginning "Project #n"
    starts = [i for i, (t, ws) in enumerate(lines) if ws[0]["text"] == "Project" and re.match(r"#\d+", ws[1]["text"] if len(ws) > 1 else "")]
    for bi, s in enumerate(starts):
        e = starts[bi + 1] if bi + 1 < len(starts) else len(lines)
        hdr = " ".join(w["text"] for w in lines[s][1])
        m = re.match(r"Project #(\d+)\s*\S?\s*(.*)$", clean(hdr))
        num, name = m.group(1), clean(m.group(2)).lstrip("-–' ").strip()
        # column split at the 2nd "Project" (of "Project Information") on the following header line
        split = None
        for t, ws in lines[s + 1:e]:
            ps = [w for w in ws if w["text"] == "Project"]
            if ps and any(w["text"] == "Developer" for w in ws):
                split = ps[0]["x0"] - 2
                break
        left, right = [], []
        for t, ws in lines[s + 1:e]:
            lt = clean(" ".join(w["text"] for w in ws if w["x0"] < split))
            rt = clean(" ".join(w["text"] for w in ws if w["x0"] >= split))
            if lt:
                left.append(lt)
            if rt:
                right.append(rt)
        rtxt = " | ".join(right)
        loc = re.search(r"Location:\s*([^|]+)", rtxt)
        units = re.search(r"Unit Count / Type:\s*(\d+)\s*([^|]*)", rtxt)
        alloc = re.search(r"(9|4)% LIHTCs Allocated:\s*\$?([\d,]+)", rtxt)
        # developer entity: left lines after "Attn:" up to the street-address line
        comp = []
        for lt in left[1:]:
            if lt.startswith("Developer"):
                continue
            if lt.startswith("Attn:"):
                continue
            if re.match(r"(\d|P\.?\s*O\.?\s*Box|Phone:|Email:)", lt, re.I):
                break
            comp.append(lt)
        n_units = units.group(1) if units else ""
        utype = units.group(2).lower() if units else ""
        li = n_units if ("low-income" in utype and "mixed" not in utype) else ""
        rows.append({
            "PROJECT": name, "PROJ_ADD": "", "PROJ_CTY": clean(loc.group(1)) if loc else "", "PROJ_ZIP": "",
            "YR_ALLOC": year, "CREDIT": ("9%" if alloc.group(1) == "9" else "4% (bond)") if alloc else "",
            "N_UNITS": n_units, "LI_UNITS": li, "COMPANY": clean(" ".join(comp)),
            "ALLOCAMT": alloc.group(2).replace(",", "") if alloc else "", "STATE_ID": f"{year}-{num}",
            "SRC_LABEL": f"Alaska Housing Finance Corp. {year} LIHTC reservation list", "SRC_URL": url})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--pdf-dir", default=None)
    a = ap.parse_args()
    pdf_dir = a.pdf_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "pdf", "ak")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    allrows = []
    for year, url in FILES:
        fn = os.path.join(pdf_dir, "ak_" + url.rstrip("/").split("/")[-2] + ".pdf")
        if not fetch(url, fn):
            continue
        rows = parse(fn, year, url)
        print(f"{year}: {len(rows)} rows  ({os.path.basename(fn)})")
        allrows += rows
    out = os.path.join(a.out, "ak.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(allrows)
    print(f"wrote {len(allrows)} rows -> {out}")


if __name__ == "__main__":
    main()

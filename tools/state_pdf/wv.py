"""West Virginia (WVHDF) LIHTC credit allocation recipient lists -> hud_src/lihtc/states/extracted/wv.csv.

Standard columns per README.md. Each year's PDF lists 9% (state ceiling) awards, a totals line, then a
"Tax-Exempt Bond Financed Property" section (4% credits). Records are top-aligned on the line holding the credit
amount; column 1 stacks property name, street address and "City, WV ZIP". A multi-site (portfolio) award lists a
portfolio name followed by several name/address/city blocks: it is written as one row per site, with the award's
credit amount and unit count on the first site's row only (the source gives no per-site split).

Usage (from the repo root): python tools/state_pdf/wv.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import sys
import urllib.error
import urllib.request

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
U = "https://www.wvhdf.com/wp-content/uploads/2026/02/"
FILES = [
    (2020, U + "2020-CREDIT-ALLOCATION-RECIPIENTS-LIST-for-web.pdf"),
    (2021, U + "2021-CREDIT-ALLOCATION-RECIPIENTS-LIST-for-web.pdf"),
    (2022, U + "2022-LIHTCP-Credit-Allocation-Recipients.pdf"),
    (2023, U + "2023-LIHTCP-Credit-Allocation-Recipients.pdf"),
    (2024, U + "2024-Credit-Allocation-Recipients-List-1-1.pdf"),
    (2025, U + "2025-Credit-Allocation-Recipients.pdf"),
]
# column left edges (x, points) on the 792-wide landscape pages; same in every year
X_TYPE, X_AMT, X_UNITS, X_OWNER = 225, 325, 395, 470
CITY = re.compile(r"^(.*?),\s*WV\s+(\d{5})\s*$")


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        print(f"  SKIP {url}: HTTP {e.code}", file=sys.stderr)
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def lines_of(page):
    """Group words into lines; each line -> dict col -> text."""
    rows = {}
    for w in page.extract_words():
        rows.setdefault(round(w["top"]), []).append(w)
    keys = sorted(rows)
    merged, last = [], None
    for k in keys:  # merge tops within 2pt
        if last is not None and k - last <= 2:
            merged[-1][1].extend(rows[k])
        else:
            merged.append((k, list(rows[k])))
        last = k
    out = []
    for top, ws in merged:
        cols = {"name": [], "type": [], "amt": [], "units": [], "owner": []}
        for w in sorted(ws, key=lambda w: w["x0"]):
            x = w["x0"]
            c = "name" if x < X_TYPE else "type" if x < X_AMT else "amt" if x < X_UNITS else "units" if x < X_OWNER else "owner"
            cols[c].append(w["text"])
        out.append((top, {k: " ".join(v) for k, v in cols.items()}, " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]))))
    return out


def parse(path):
    """Returns list of awards: dict(credit, amt, units, owner, col1 lines)."""
    awards, cur, bond = [], None, False
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            body = False
            for top, c, full in lines_of(page):
                if full.startswith("ADDRESS") and "UNITS" in full:
                    body = True
                    continue
                if not body:
                    continue
                if full.startswith("Tax-Exempt Bond Financed"):
                    bond, cur = True, None
                    continue
                if full.startswith("*The credit amount") or re.match(r"^Page \d+ of \d+", full) or full.startswith("returned if"):
                    cur = None
                    continue
                if c["amt"].startswith("$"):
                    if not c["name"]:  # totals line: "$5,061,809 523"
                        cur = None
                        continue
                    cur = {"credit": "4% (bond)" if bond else "9%", "amt": int(re.sub(r"\D", "", c["amt"])),
                           "units": int(re.sub(r"\D", "", c["units"]) or 0) or None, "owner": [], "col1": []}
                    awards.append(cur)
                if cur is None:
                    continue
                if c["name"]:
                    cur["col1"].append(c["name"])
                if c["owner"]:
                    cur["owner"].append(c["owner"])
    return awards


def sites(col1):
    """Split column-1 lines into (name, address, city, zip) site blocks; returns (portfolio_name, [sites])."""
    blocks, b = [], []
    for ln in col1:
        b.append(ln)
        if CITY.match(ln):
            blocks.append(b)
            b = []
    if b:  # trailing lines without a city line
        blocks.append(b)
    portfolio = None
    out = []
    for i, blk in enumerate(blocks):
        m = CITY.match(blk[-1])
        city, zp = (m.group(1), m.group(2)) if m else ("", "")
        body = blk[:-1] if m else blk
        if i == 0 and len(blocks) > 1:  # portfolio: first line is the award name, then the first site's name
            portfolio, body = body[0], body[1:]
        name = body[0] if body else ""
        addr = [x for x in body[1:] if not re.match(r"^a\.?k\.?a\.?\b", x, re.I)]
        address = re.sub(r"^vicinity of\s+", "", " ".join(addr), flags=re.I)
        out.append((name, address, city, zp))
    return portfolio, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--pdf-dir", default=None)
    a = ap.parse_args()
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pdir = a.pdf_dir or os.path.join(repo, "..", "hud_src", "lihtc", "states", "pdf", "wv")
    os.makedirs(pdir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    out = []
    for year, url in FILES:
        path = os.path.join(pdir, url.rsplit("/", 1)[1])
        if not fetch(url, path):
            continue
        awards = parse(path)
        for aw in awards:
            portfolio, ss = sites(aw["col1"])
            for i, (name, addr, city, zp) in enumerate(ss):
                out.append({"PROJECT": f"{name} ({portfolio})" if portfolio else name, "PROJ_ADD": addr, "PROJ_CTY": city,
                            "PROJ_ZIP": zp, "YR_ALLOC": year, "CREDIT": aw["credit"],
                            "N_UNITS": aw["units"] if i == 0 else "", "LI_UNITS": "",
                            "COMPANY": aw["owner"][0] if aw["owner"] else "", "ALLOCAMT": aw["amt"] if i == 0 else "",
                            "STATE_ID": "", "SRC_LABEL": f"WVHDF {year} LIHTC credit allocation recipients list", "SRC_URL": url})
        n9 = [x for x in awards if x["credit"] == "9%"]
        n4 = [x for x in awards if x["credit"] != "9%"]
        print(f"  {year}: {len(awards)} awards ({len(n9)} 9%: ${sum(x['amt'] for x in n9):,} / {sum(x['units'] or 0 for x in n9)} units;"
              f" {len(n4)} bond: ${sum(x['amt'] for x in n4):,})")
    with open(os.path.join(a.out, "wv.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for o in out:
            w.writerow({k: "" if o.get(k) is None else o.get(k) for k in COLS})
    print(f"wrote {len(out)} rows -> {os.path.join(a.out, 'wv.csv')}")


if __name__ == "__main__":
    main()

"""Maryland DHCD (Community Development Administration) LIHTC lists -> extracted/md.csv.

1. Competitive Funding Round award PDFs ("applicant information, state bonus points and waivers"): Fall 2020 (awarded
   Jan 27 2021), Spring 2022 (Sep 27 2022), Fall/Winter 2023 (Apr 29 2024), Spring/Summer 2025 (Oct 9 2025).
   Each lists EVERY applicant, grouped by county with subtotal rows, then a TOTALS row and waiver pages. Columns:
   # | Project | Applicant/Sponsor | County/Address | Population | Units | Targeted Pop. Units | [Constr. type] |
   Community context | Total cost | Requested 9% LIHTC | Requested RHPF/PRHP/HOME | Approved 9% LIHTC | Approved ...
   Only applicants with a non-zero Approved 9% LIHTC amount are kept (CREDIT 9%, ALLOCAMT = approved annual credits).
   Cells are vertically centred and wrap, so every word is assigned to the nearest row anchor (the '#' number, a
   county subtotal row, a county heading or TOTALS) and to a column by the x-centre of its phrase; column bounds are
   set per file. YR_ALLOC = year of the award date in the PDF title (so the Fall 2020 round is 2021 and the
   Fall/Winter 2023 round is 2024). Address = street, city, ZIP parsed from the County/Address cell ("..., City, MD
   2xxxx"). "Targeted Population Units" are special-needs set-aside units, not low-income units, so LI_UNITS is blank.
   The Spring/Summer 2025 awards are cross-checked against DHCD's awards-only press-release list ("2026 LIHTC
   Awards"), which is not written out separately (it would duplicate those rows).
   The 2026 round-1 applicant list (media/4524) is skipped: it is applicants, not awards.

2. LIHTC property list ("Properties Subject to End of Year Data Uploads for Calendar Year 2025", sorted by name):
   statewide inventory of LIHTC properties in compliance. Columns: MD NUMBER | PROPERTY | AKA | PIS | ADDRESS |
   CITY/TOWN; rows are separated by ruled lines; each word goes to the row band holding its vertical middle and to the column
   holding its left edge. YR_ALLOC = PLACED-IN-
   SERVICE year (not an allocation year; said in SRC_LABEL). STATE_ID = MD number. CREDIT is set only when the name
   carries a 9% / 4% tag (e.g. "Woodyard Station FAMILY [9%] {Twin}"). No ZIP or unit counts in this list.

Usage (from the repo root): python tools/state_pdf/md.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

# Column layout per round PDF. Text columns: (project, applicant, address) bounds on the phrase x-centre.
# Numeric columns: x0 ranges for total units and Approved 9% LIHTC.
ROUNDS = [
    {"url": "https://dhcd.maryland.gov/media/929", "file": "round_fall2020.pdf", "round": "Fall 2020",
     "text": (62, 147, 247, 380), "units": (410, 432), "appr": (628, 664)},
    {"url": "https://dhcd.maryland.gov/media/927", "file": "round_spring2022.pdf", "round": "Spring 2022",
     "text": (62, 143, 234, 375), "units": (410, 432), "appr": (628, 664)},
    {"url": "https://dhcd.maryland.gov/media/990", "file": "round_fallwinter2023.pdf", "round": "Fall/Winter 2023",
     "text": (62, 131, 234, 383), "units": (410, 432), "appr": (755, 805)},
    {"url": "https://dhcd.maryland.gov/media/1048", "file": "round_springsummer2025.pdf",
     "round": "Spring/Summer 2025", "text": (62, 121, 184, 297), "units": (320, 345), "appr": (605, 642)},
]
PRESS_2025 = "https://news.maryland.gov/dhcd/wp-content/uploads/sites/16/2025/10/2026-LIHTC-Awards.pdf"
INVENTORY = "https://dhcd.maryland.gov/media/4306"

COUNTIES = {"Allegany", "Anne Arundel", "Baltimore City", "Baltimore", "Calvert", "Caroline", "Carroll", "Cecil",
            "Charles", "Dorchester", "Frederick", "Garrett", "Harford", "Howard", "Kent", "Montgomery",
            "Prince George's", "Queen Anne's", "St. Mary's", "Somerset", "Talbot", "Washington", "Wicomico",
            "Worcester", "Baltimore County"}

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def download(url, dest):
    """curl with its default user agent (dhcd.maryland.gov answers 403 to Python urllib's default agent; no browser
    user agent is sent). Returns None on success, else an error string."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    r = subprocess.run(["curl", "-s", "-L", "-o", str(dest), "-w", "%{http_code}", url], capture_output=True, text=True)
    code = r.stdout.strip()
    ok = r.returncode == 0 and code == "200" and dest.exists() and dest.read_bytes()[:4] == b"%PDF"
    if not ok:
        if dest.exists():
            dest.unlink()
        return f"curl exit {r.returncode}, HTTP {code}" + ("" if code != "200" else ", not a PDF")
    return None


def money(s):
    s = s.replace("$", "").replace(",", "").strip()
    return int(s) if s.isdigit() else 0


def phrases(ws, gap=4.0):
    """Split one visual line (words sorted by x) into phrases at horizontal gaps > gap."""
    out = []
    for w in ws:
        if out and w["x0"] - out[-1][-1]["x1"] <= gap:
            out[-1].append(w)
        else:
            out.append([w])
    return out


def group_lines(ws, tol=1.5):
    ws = sorted(ws, key=lambda w: (w["top"], w["x0"]))
    out = []
    for w in ws:
        if out and abs(w["top"] - out[-1][0]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [sorted(l, key=lambda w: w["x0"]) for _, l in out]


def mid(w):
    return (w["top"] + w["bottom"]) / 2


def parse_address(addr):
    """'421 Hammond Street, Westernport, MD 21562' -> (street, city, zip)."""
    a = re.sub(r"\s+", " ", addr).strip()
    a = re.sub(r"\s+,", ",", a)
    m = re.search(r"^(.*),\s*([^,]+?),?\s+MD\s*(\d{5})", a)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3)
    m = re.search(r"^(.*),\s*([^,]+?),?\s+MD\b", a)
    if m:
        return m.group(1).strip(), m.group(2).strip(), ""
    return a, "", ""


def parse_round(path, cfg):
    pdf = pdfplumber.open(path)
    t0 = pdf.pages[0].extract_text() or ""
    m = re.search(rf"ROUND\s*--\s*((?:{MONTHS.upper()}|{MONTHS})\s+\d+,\s*(\d{{4}}))", t0)
    award_date, award_year = (m.group(1), int(m.group(2))) if m else ("", None)
    px0, pa, pad, pend = cfg["text"]
    rows, n_listed, totals_seen = [], 0, False
    for page in pdf.pages:
        ws = page.extract_words()
        txt = page.extract_text() or ""
        hdr = [w for w in ws if w["text"] == "#" and w["x0"] < 62]
        if not hdr or totals_seen:
            continue  # waiver pages (no '#' column) or past the TOTALS row
        y0 = max(w["bottom"] for w in ws if w["text"] == "Served")  # end of the column header
        body = [w for w in ws if w["top"] > y0]
        # anchors: (y, kind, word)
        anchors = []
        for w in body:
            if w["x0"] < 62 and re.fullmatch(r"\d+", w["text"]):
                anchors.append((mid(w), "proj", w))
        for l in group_lines(body):
            s = " ".join(w["text"] for w in l)
            if s.startswith("TOTALS"):
                anchors.append((mid(l[0]), "total", None))
                totals_seen = True
            elif s in COUNTIES:
                anchors.append((mid(l[0]), "county", s))
            elif not any(w["x0"] < 62 for w in l) and any(
                    cfg["units"][0] <= w["x0"] < cfg["units"][1] and re.fullmatch(r"[\d,]+", w["text"]) for w in l):
                if not any(a[1] == "proj" and abs(a[0] - mid(l[0])) < 3 for a in anchors):
                    anchors.append((mid(l[0]), "subtotal", None))
        anchors.sort(key=lambda a: a[0])
        if not anchors:
            continue
        last_total = max((a[0] for a in anchors if a[1] == "total"), default=None)
        blocks = {id(a): [] for a in anchors}
        county = None
        for w in body:
            if last_total is not None and mid(w) > last_total + 4:
                continue
            a = min(anchors, key=lambda a: abs(a[0] - mid(w)))
            blocks[id(a)].append(w)
        for a in anchors:
            if a[1] == "county":
                county = a[2]
                continue
            if a[1] != "proj":
                continue
            n_listed += 1
            bw = [w for w in blocks[id(a)] if w is not a[2]]
            cols = {"proj": [], "app": [], "addr": []}
            for l in group_lines(bw):
                for ph in phrases([w for w in l if w["x0"] < pend]):
                    c = (ph[0]["x0"] + ph[-1]["x1"]) / 2
                    if px0 <= c < pa:
                        cols["proj"].append(ph)
                    elif pa <= c < pad:
                        cols["app"].append(ph)
                    elif pad <= c < pend:
                        cols["addr"].append(ph)
            text = {k: re.sub(r"\s+", " ", " ".join(w["text"] for ph in v for w in ph)).strip()
                    for k, v in cols.items()}
            units = next((w["text"] for w in bw if cfg["units"][0] <= w["x0"] < cfg["units"][1]
                          and re.fullmatch(r"\d+", w["text"])), "")
            appr = [w["text"] for w in bw if cfg["appr"][0] <= w["x0"] < cfg["appr"][1]
                    and re.search(r"\d", w["text"])]
            amt = sum(money(x) for x in appr)
            street, city, zipc = parse_address(text["addr"])
            rows.append({"num": a[2]["text"], "PROJECT": text["proj"], "COMPANY": text["app"], "addr": text["addr"],
                         "PROJ_ADD": street, "PROJ_CTY": city, "PROJ_ZIP": zipc, "N_UNITS": units,
                         "ALLOCAMT": str(amt) if amt else "", "county": county})
    return rows, n_listed, award_date, award_year


# ---------------------------------------------------------------- inventory
INV_COLS = [("md", 45, 165), ("prop", 165, 334), ("aka", 334, 505), ("pis", 505, 580), ("addr", 580, 850),
            ("city", 850, 960)]


def parse_inventory(path):
    pdf = pdfplumber.open(path)
    out = []
    for page in pdf.pages:
        ys = sorted({round(l["top"], 1) for l in page.lines if l["x1"] - l["x0"] > 500}
                    | {round(r["top"], 1) for r in page.rects if r["x1"] - r["x0"] > 500 and r["height"] < 2})
        ys = [y for i, y in enumerate(ys) if i == 0 or y - ys[i - 1] > 2]
        words = page.extract_words()
        hdr = next((w for w in words if w["text"] == "PIS"), None)
        if hdr is None:
            continue
        ys = [y for y in ys if y > hdr["bottom"]]
        for top, bot in zip(ys, ys[1:]):
            inband = sorted((w for w in words if top <= mid(w) < bot), key=lambda w: (round(w["top"]), w["x0"]))
            rec = {}
            for k, x0, x1 in INV_COLS:  # a word belongs to the column its left edge falls in
                rec[k] = " ".join(w["text"] for w in inband if x0 <= w["x0"] < x1).strip()
            if not re.search(r"\d\d/\d\d/\d{4}", rec["pis"]) and not rec["md"].startswith("MD"):
                continue
            out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "md"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], []

    awarded_2025 = []
    for cfg in ROUNDS:
        dest = pdir / cfg["file"]
        err = download(cfg["url"], dest)
        if err:
            skipped.append((cfg["url"], err))
            print(f"SKIP {cfg['url']}: {err}", file=sys.stderr)
            continue
        recs, n_listed, adate, ayear = parse_round(dest, cfg)
        won = [r for r in recs if r["ALLOCAMT"]]
        tot = sum(int(r["ALLOCAMT"]) for r in won)
        print(f"{dest.name}: {n_listed} applicants listed, {len(won)} with approved 9% LIHTC "
              f"(total ${tot:,}); award date {adate}")
        for r in won:
            if not r["PROJ_ZIP"]:
                print(f"  no ZIP parsed: #{r['num']} {r['PROJECT']} | {r['addr']}", file=sys.stderr)
            r.update({"YR_ALLOC": str(ayear), "CREDIT": "9%", "SRC_URL": cfg["url"],
                      "SRC_LABEL": f"Maryland DHCD {cfg['round']} Competitive Funding Round awards ({adate}; "
                                   f"applicant #{r['num']}, {r['county']}; approved 9% LIHTC)"})
            rows.append({k: r.get(k, "") for k in COLS})
        if cfg["round"].startswith("Spring/Summer 2025"):
            awarded_2025 = won

    # cross-check the 2025 round against the press-release awards list
    dest = pdir / "2026-LIHTC-Awards.pdf"
    err = download(PRESS_2025, dest)
    if err:
        skipped.append((PRESS_2025, err))
    elif awarded_2025:
        txt = " ".join((p.extract_text() or "") for p in pdfplumber.open(dest).pages)
        flat = re.sub(r"\s+", " ", txt)
        amts = [int(x) for x in re.findall(r"\b(1500000|[1-9]\d{5,6})\b", flat)]
        miss = [r["PROJECT"] for r in awarded_2025
                if not all(wd in flat for wd in r["PROJECT"].split()[:2])]
        print(f"2025 cross-check vs {dest.name}: {len(awarded_2025)} round awards; "
              f"names not found in press list: {miss or 'none'}")

    dest = pdir / "lihtc_property_list_cy2025.pdf"
    err = download(INVENTORY, dest)
    if err:
        skipped.append((INVENTORY, err))
        print(f"SKIP {INVENTORY}: {err}", file=sys.stderr)
    else:
        inv = parse_inventory(dest)
        n_ok = 0
        for r in inv:
            m = re.search(r"(\d\d)/(\d\d)/(\d{4})", r["pis"])
            pis_year = m.group(3) if m else ""
            name = r["prop"]
            credit = "9%" if "9%" in name else ("4% (bond)" if "4%" in name else "")
            n_ok += bool(pis_year)
            label = (f"Maryland DHCD LIHTC property list (properties subject to CY2025 end-of-year data uploads); "
                     f"YR_ALLOC is the placed-in-service year (PIS {r['pis']}), not an allocation year")
            if r["aka"]:
                label += f"; AKA {r['aka']}"
            rows.append({k: v for k, v in {
                "PROJECT": name, "PROJ_ADD": r["addr"], "PROJ_CTY": r["city"], "YR_ALLOC": pis_year,
                "CREDIT": credit, "STATE_ID": r["md"], "SRC_LABEL": label, "SRC_URL": INVENTORY}.items()})
        print(f"{dest.name}: {len(inv)} properties ({n_ok} with a PIS date)")

    rows = [{k: r.get(k, "") for k in COLS} for r in rows]
    with open(out / "md.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'md.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

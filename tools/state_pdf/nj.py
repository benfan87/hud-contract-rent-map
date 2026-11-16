"""New Jersey Housing & Mortgage Finance Agency (NJHMFA) LIHTC reservation lists -> extracted/nj.csv.

Sources: the 9% "Low Income Housing Tax Credit Reservation List" for each competitive round (2020, 2021, 2022, 2024,
2025 spring, 2025 fall), one report per cycle (Family / Senior / Supportive / Mixed Income ...), and the cumulative
4% "Bond (Volume Cap) Cycle" reservation list 1/1/2015 - 6/30/2025.
Skipped on purpose: the 7/2025 - 4/2026 4% file (4percent_through_April_30_2026.pdf) is an *applicant* list with
allocation *requests*, not reservations.

Layout ("Crystal Reports" style; text extraction scrambles the columns, so words are placed by x position):
  standard (2020, 2021, 2022, 2024, 2025 spring, 4% list): one block per project, top-aligned on the LITC # line:
    LITC # | Project (name / street lines / "Municipality County") | Developer (name / address / city ST ZIP) |
    F/S | Primary contact + phone | Affordable units | Total units | LIHTC type | reservation date | Allocation
    Column edges are fixed relative to the "LITC" and "Allocation" header words (2022 pages are shifted/scaled).
  2025 fall: LIHTC # | Project | Project Address (street above, "Municipality / County" on the # line) | Sponsor |
    F/S | contact | Aff | Total | type | date | Allocation, vertically centred on the # line.
The ZIP printed in these lists is the developer's mailing ZIP, never the project's, so PROJ_ZIP is always blank.
Project name vs street: the first project line is the name; following lines stay in the name until one looks like an
address (starts with a digit, "S/B", "Corner", "Intersection", ... or contains a street word).
PROJ_CTY = municipality as printed (e.g. "Newark City", "Gloucester Twp."), county dropped.
YR_ALLOC: 9% lists = the round year (2021 reservations run into 1/2022, the 2022 round into 3/2023 and the 2025 fall
round was reserved 2/25/2026); 4% list = year of each project's reservation date. Every listed project is a
reservation; GRAND TOTALS lines are dropped and checked against the parsed rows.
STATE_ID = NJHMFA LITC number. ALLOCAMT = annual credit reserved.

Usage (from the repo root): python tools/state_pdf/nj.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

B9 = "https://www.nj.gov/dca/hmfa/developers/docs/lihtc/awards/"
# (round year or None = use reservation date, credit, url, round label)
FILES = [
    (2020, "9%", B9 + "2020/2020_reservation_list.pdf", "2020 round"),
    (2021, "9%", B9 + "2021/2021_reservation_list.pdf", "2021 round"),
    (2022, "9%", B9 + "2022/2022_reservation_list.pdf", "2022 round"),
    (2024, "9%", B9 + "2024/2024_reservation_list.pdf", "2024 round"),
    (2025, "9%", B9 + "2025/2025_spring_reservation_list.pdf", "2025 spring round"),
    (2025, "9%", B9 + "2025/2025_fall_reservation_list.pdf", "2025 fall round"),
    (None, "4% (bond)", "https://www.nj.gov/dca/hmfa/developers/docs/lihtc/tax/awards/4percent_through_june3_2025.pdf",
     "cumulative 4% bond (volume cap) list 1/1/2015-6/30/2025"),
]

COUNTIES = ["Cape May", "Atlantic", "Bergen", "Burlington", "Camden", "Cumberland", "Essex", "Gloucester", "Hudson",
            "Hunterdon", "Mercer", "Middlesex", "Monmouth", "Morris", "Ocean", "Passaic", "Salem", "Somerset", "Sussex",
            "Union", "Warren"]
COUNTY_RX = re.compile(r"^(?P<muni>.*?)\s*(?P<county>" + "|".join(COUNTIES) + r")$")
STREET_WORDS = (r"Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Boulevard|Blvd|Lane|Ln|Way|Court|Ct|Place|Pl|Pike|Highway|"
                r"Hwy|Parkway|Pkwy|Route|Rt|Terrace|Trail|Circle|Plaza|Square|Block|Lot|Lots")
ADDR_START_RX = re.compile(r"(?i)^(\d|S/B\b|Corner\b|Intersection\b|Block\b|Lots?\b|Scattered\b|Various\b|Multiple\b|"
                           r"\w+\s*&\s*\w+)|\b(" + STREET_WORDS + r")\b\.?(,|$|\s|\d)|\d{2,}")
DEV_ADDR_RX = re.compile(r"(?i)^(\d|P\.?\s*O\.?\s*Box|c/o\b|One\s|Two\s|Three\s|Suite\b)")
NOADDR_RX = re.compile(r"(?i)^(scattered sites?|various( sites)?|tbd)$")
FOOT_RX = re.compile(r"^(Report Server Name|Run Date|User:|GRAND\b|TOTALS\b)")


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


def group_lines(words, tol=2.5):
    ws = sorted(words, key=lambda w: (w["top"], w["x0"]))
    out = []
    for w in ws:
        if out and abs(w["top"] - out[-1][0]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(l, key=lambda w: w["x0"])) for t, l in out]


def txt(ws):
    return re.sub(r"\s+", " ", " ".join(w["text"] for w in ws)).strip()


def money(s):
    s = re.sub(r"[^\d.]", "", s or "")
    return str(int(round(float(s)))) if s else ""


def split_name_street(lines):
    """lines: project-column text lines minus the municipality line -> (name, street)."""
    if not lines:
        return "", ""
    name, i = [lines[0]], 1
    while i < len(lines) and not ADDR_START_RX.search(lines[i]):
        name.append(lines[i])
        i += 1
    street = " ".join(lines[i:])
    street = re.sub(r"\s+,", ",", street)
    if not street and re.match(r"^\d", lines[0]) and ADDR_START_RX.search(lines[0][1:]):
        street = lines[0]  # project named by its address, e.g. "240 West State Street"
    if NOADDR_RX.match(street):
        street = ""
    return " ".join(name), street


def developer_name(lines):
    out = []
    for l in lines:
        if out and DEV_ADDR_RX.match(l):
            break
        out.append(l)
    return " ".join(out).strip(" ,")


# ---------------------------------------------------------------- standard layout
# column edges in the 2020 report's coordinates, where the "LITC" header word is at x=60 and "Allocation" at x=825
STD_EDGES = {"proj": 100, "dev": 236, "fs": 372, "contact": 400, "aff": 540, "tot": 600, "type": 650, "date": 760,
             "alloc": 850}


def parse_standard(pdf):
    recs, cur, cycle = [], None, ""
    for page in pdf.pages:
        words = page.extract_words()
        lines = group_lines(words)
        hdr = next(((t, ws) for t, ws in lines if ws[0]["text"] == "LITC"), None)
        if hdr is None:
            continue
        for t, ws in lines:
            m = re.match(r"^(.*Cycle)$", txt(ws))
            if m and t < hdr[0]:
                cycle = m.group(1)
        lx = hdr[1][0]["x0"]
        ax = next(w["x0"] for w in hdr[1] if w["text"] == "Allocation")
        sc = (ax - lx) / (825 - 60)
        E = {k: lx + (v - 60) * sc for k, v in STD_EDGES.items()}
        body_top = hdr[0] + 14  # skip the 2nd header line ("/Senior Phone units units")
        foot = min([t for t, ws in lines if FOOT_RX.match(txt(ws))] + [page.height])

        def col(x):
            for k in ("alloc", "date", "type", "tot", "aff", "contact", "fs", "dev", "proj"):
                if x >= E[k]:
                    return k
            return "id"

        for t, ws in lines:
            if t <= body_top or t >= foot - 1:
                continue
            first = ws[0]
            if col(first["x0"]) == "id" and re.match(r"^\d{3,5}[A-Z]{0,2}$", first["text"]):
                cur = {"id": first["text"], "cycle": cycle, "page": page.page_number, "cells": defaultdict(list)}
                recs.append(cur)
                ws = ws[1:]
            if cur is None:
                continue
            bycol = defaultdict(list)
            for w in ws:
                bycol[col(w["x0"])].append(w)
            for k, cw in bycol.items():
                cur["cells"][k].append(txt(cw))
    out = []
    for r in recs:
        c = r["cells"]
        proj = [l for l in c["proj"] if l]
        muni_i = max((i for i, l in enumerate(proj) if COUNTY_RX.match(l)), default=None)
        if muni_i is not None and muni_i > 0 and proj[muni_i] in COUNTIES:
            # county wrapped onto its own line: "Parsippany-Troy Hills Twp." / "Morris"
            proj = proj[:muni_i - 1] + [proj[muni_i - 1] + " " + proj[muni_i]] + proj[muni_i + 1:]
            muni_i -= 1
        if muni_i is None:
            muni, county, rest = "", "", proj
            print(f"WARNING LITC {r['id']}: no 'Municipality County' line in {proj}", file=sys.stderr)
        else:
            m = COUNTY_RX.match(proj[muni_i])
            muni, county = m.group("muni").strip(" ,"), m.group("county")
            rest = proj[:muni_i] + proj[muni_i + 1:]
        name, street = split_name_street(rest)
        out.append({"id": r["id"], "cycle": r["cycle"], "name": name, "street": street, "muni": muni,
                    "county": county, "dev": developer_name(c["dev"]), "aff": " ".join(c["aff"]),
                    "tot": " ".join(c["tot"]), "date": " ".join(c["date"]), "alloc": " ".join(c["alloc"]),
                    "type": " ".join(c["type"])})
    return out


# ---------------------------------------------------------------- 2025 fall layout
def segments(ws, gap=8):
    segs = []
    for w in ws:
        if segs and w["x0"] - segs[-1][-1]["x1"] <= gap:
            segs[-1].append(w)
        else:
            segs.append([w])
    return segs


def parse_fall(pdf):
    out = []
    for page in pdf.pages:
        lines = group_lines(page.extract_words())
        hdr = next(((t, ws) for t, ws in lines if ws[0]["text"] == "LIHTC" and len(ws) > 1 and ws[1]["text"] == "#"), None)
        if hdr is None:
            continue
        cycle = next((txt(ws) for t, ws in lines if txt(ws).endswith("Cycle") and t < hdr[0]), "")
        foot = min([t for t, ws in lines if FOOT_RX.match(txt(ws))] + [page.height])
        body = [(t, ws) for t, ws in lines if hdr[0] + 3 < t < foot - 1]
        anchors = [(t, ws) for t, ws in body if re.match(r"^\d{4}$", ws[0]["text"]) and ws[0]["x0"] < hdr[1][0]["x0"] + 40]
        prev = hdr[0] + 3
        for at, aws in anchors:
            segs = segments(aws)
            # id | name | muni / county | sponsor city | F/S | phone | aff | total | type | date | alloc
            sid, name = txt(segs[0]), txt(segs[1])
            mc = txt(segs[2])
            muni, _, county = mc.partition("/")
            nums = [txt(s) for s in segs[1:] if re.match(r"^\d+$", txt(s))]
            alloc = next(txt(s) for s in reversed(segs) if re.search(r"\d{1,3}(,\d{3})+", txt(s)))
            date = next(re.search(r"\d+/\d+/\d{4}", txt(s)).group(0) for s in segs if re.search(r"\d+/\d+/\d{4}", txt(s)))
            name_x, addr_x, spon_x, cont_x = segs[1][0]["x0"], segs[2][0]["x0"], segs[3][0]["x0"], segs[5][0]["x0"]
            street, spon, name_above = [], [], []
            for t, ws in body:
                if not (prev < t < at - 1):
                    continue
                for s in segments(ws):
                    x = s[0]["x0"]
                    if name_x - 5 <= x < addr_x - 5:
                        name_above.append(txt(s))
                    elif addr_x - 5 <= x < spon_x - 5:
                        street.append(txt(s))
                    elif spon_x - 5 <= x < cont_x - 40:
                        spon.append(txt(s))
            prev = at + 3
            name = " ".join(name_above + [name])
            out.append({"id": sid, "cycle": cycle, "name": name, "street": " ".join(street), "muni": muni.strip(),
                        "county": county.strip(), "dev": developer_name(spon), "aff": nums[0] if nums else "",
                        "tot": nums[1] if len(nums) > 1 else "", "date": date, "alloc": alloc, "type": ""})
    return out


def grand_totals(pdf):
    """[(projects, affordable, total, allocation)] from 'GRAND Projects: n a t $x' / 'TOTALS PROJECTS: n a t $x'."""
    out = []
    for page in pdf.pages:
        t = page.extract_text() or ""
        for m in re.finditer(r"(?:GRAND Projects|TOTALS PROJECTS):\s*(\d+)\s+(\d+)\s+(\d+)\s+\$\s*([\d,.]+)", t):
            out.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), money(m.group(4))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "nj"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], []
    for yr, credit, url, label in FILES:
        dest = pdir / url.rsplit("/", 1)[1]
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        pdf = pdfplumber.open(dest)
        recs = parse_fall(pdf) if "fall" in dest.name else parse_standard(pdf)
        gt = grand_totals(pdf)
        g = [sum(x[i] for x in gt) for i in range(3)] + [sum(int(x[3]) for x in gt)]
        p = [len(recs), sum(int(r["aff"] or 0) for r in recs), sum(int(r["tot"] or 0) for r in recs),
             sum(int(money(r["alloc"]) or 0) for r in recs)]
        flag = "OK" if g == p else "MISMATCH"
        print(f"{dest.name}: parsed projects/aff/total/alloc {p} vs GRAND TOTALS {g} -> {flag}")
        n = Counter()
        for r in recs:
            ry = yr or int(r["date"][-4:])
            lab = (f"NJHMFA {label} LIHTC reservation list - {r['cycle']}, reserved {r['date']}"
                   + (f" (LIHTC type: {r['type']})" if r["type"] else ""))
            if credit == "9%":
                lab = lab.replace("LIHTC reservation list", "9% LIHTC reservation list")
            rows.append({"PROJECT": r["name"], "PROJ_ADD": r["street"], "PROJ_CTY": r["muni"], "PROJ_ZIP": "",
                         "YR_ALLOC": str(ry), "CREDIT": credit, "N_UNITS": r["tot"], "LI_UNITS": r["aff"],
                         "COMPANY": r["dev"], "ALLOCAMT": money(r["alloc"]), "STATE_ID": r["id"],
                         "SRC_LABEL": lab, "SRC_URL": url})
            n[ry] += 1
        print(f"   by year: {dict(sorted(n.items()))}")
    with open(out / "nj.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'nj.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

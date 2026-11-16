"""Kansas Housing Resources Corporation (KHRC) LIHTC award lists -> extracted/ks.csv.

Sources:
  * 9% reservation / award postings, one per credit year 2020-2026 (posted the year before; YR_ALLOC = the credit
    year printed on the list, as for Utah). Card layout: name / street / "City, KS ZIP" (/ county) in column 1,
    developer + LIHTC amount in column 2, Type / Target / units in column 3. "HOME ONLY" sections are dropped, and so
    are cards with no LIHTC reservation (HOME/NHTF-only). The 2021 list's "TC Reservation 4% Allocation" card is 4%.
  * Private Activity Bond Allocation List (updated 11/13/2025): bond-financed (4%) deals with street / city / ZIP /
    units and an "Awarded" date; YR_ALLOC = year of the Awarded date, kept when >= 2020.
  * KAHTC annual reports to the Legislature (2023, 2024, 2025 awards): table of 9% and 4% awards with city, county,
    units. 4% rows not already on the PAB list are added (city only; YR_ALLOC = report year). 9% rows are not added
    (they repeat the next credit year's posting) but fill LI_UNITS on postings that print no unit counts.

Usage (from the repo root): python tools/state_pdf/ks.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import difflib
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
U = "https://kshousingcorp.org/wp-content/uploads/"
POSTINGS = [  # (credit year, url, title)
    (2020, U + "2019/09/2020ReservationList.pdf", "2020 Reservation List"),
    (2021, U + "2020/05/housing-dev-awards-2020.pdf", "2021 Reservation List"),
    (2022, U + "2022/10/2022-Award-List.pdf", "2022 LIHTC Award List"),
    (2023, U + "2022/08/2023-Awards-List-Updated-08102022.pdf", "2023 LIHTC Awards List (updated 8/10/2022)"),
    (2024, U + "2023/11/2024-LIHTC-Award-Posting.pdf", "2024 LIHTC Award Posting (posted 7/13/2023)"),
    (2025, U + "2024/07/2025-LIHTC-Award-List-pdf-v1.1.pdf", "2025 LIHTC Award List v1.1"),
    (2026, U + "2026/02/2026-LIHTC-Award-Posting-Correction-02.05.26.pdf", "2026 LIHTC Award Posting (corrected 2/5/26)"),
]
PAB = U + "2025/11/PAB-Allocation-List-11.14.2025.pdf"
LEG = [  # (award year, url, title)
    (2023, U + "2023/10/2023-Kansas-Affordable-Housing-Tax-Credit-Report.pdf", "2023 KAHTC report to the Legislature"),
    (2024, U + "2025/11/2024-Award-Report-Corrected.pdf", "2024 State Legislative Report (corrected)"),
    (2025, U + "2025/12/KAHTC-2025.pdf", "KAHTC 2025 report to the Legislature"),
]


def download(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        return None
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    if not data.startswith(b"%PDF"):
        return "response is not a PDF"
    dest.write_bytes(data)
    return None


def lines_of(page):
    ws = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
    out = []
    for w in ws:
        if out and abs(w["top"] - out[-1][0]) <= 2.5:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(l, key=lambda w: w["x0"])) for t, l in out]


def cells(ws, gap=10):
    """Split a line's words into cells wherever the horizontal gap exceeds `gap` points."""
    out = [[ws[0]]]
    for w in ws[1:]:
        if w["x0"] - out[-1][-1]["x1"] > gap:
            out.append([w])
        else:
            out[-1].append(w)
    return out


def txt(ws):
    return " ".join(w["text"] for w in ws).strip()


def nkey(s):
    s = re.sub(r"\(.*?\)|[*]", "", (s or "").lower())
    s = re.sub(r"\b(the|apartments?|apts|phase|townhomes|homes|llc|of|at|and)\b", " ", s)
    s = re.sub(r"\bii\b", "2", re.sub(r"\biii\b", "3", s))
    return re.sub(r"[^a-z0-9]", "", s)


def same(a, b):
    ka, kb = nkey(a), nkey(b)
    return bool(ka and kb) and (ka == kb or ka.startswith(kb) or kb.startswith(ka)
                                or difflib.SequenceMatcher(None, ka, kb).ratio() > 0.85)


SKIP_RX = re.compile(r"Kansas\s+Housing\s+Resources|Reservation\s+List$|LIHTC\s+AWARDS$|^Development\s+Developer|"
                     r"^Posted\s|Page \d+ of \d+|PRIVATE\s+ACTIVITY\s+BOND|National Housing Trust Fund or HOME recipient|"
                     r"^Updated\s|^(Monday|Tuesday|Wednesday|Thursday|Friday),")
CITY_RX = re.compile(r"^(?P<city>.+?),?\s+KS\.?(\s+(?P<zip>\d{5}))?(-\d{4})?\s*$")


def parse_cards(path):
    """KHRC card layout (postings and PAB list). Returns list of cards: sec, sec_year, c1 (col-1 lines), other."""
    pdf = pdfplumber.open(path)
    pages = [lines_of(p) for p in pdf.pages]
    allw = [w for ls in pages for t, ws in ls for w in ws]
    X3 = Counter(round(w["x0"]) for w in allw if w["text"] in ("Type", "Type:")).most_common(1)[0][0] - 3
    X1 = min(w["x0"] for w in allw)
    X2 = Counter(round(w["x0"]) for w in allw if X1 + 100 < w["x0"] < X3 - 60).most_common(1)[0][0] - 3
    cards, cur, pending, sec, sec_year = [], None, [], "9", None
    for ls in pages:
        for t, ws in ls:
            s = txt(ws)
            if SKIP_RX.search(s):
                continue
            m = re.match(r"^(9%|4%)\s+(AWARDS|APPLICATIONS)$", s)
            if m:
                sec, cur, pending = m.group(1)[0], None, []
                continue
            if re.match(r"^HOME\s+ONLY", s):
                sec, cur, pending = "drop", None, []
                continue
            m = re.match(r"^(\d{4})\s+ALLOCATIONS$", s)
            if m:
                sec, sec_year, cur, pending = "pab", int(m.group(1)), None, []
                continue
            if s.startswith("*") or sec == "drop":
                continue
            ti = next((i for i, w in enumerate(ws) if w["text"] in ("Type", "Type:") and w["x0"] >= X3 - 5), None)
            cl = cells(ws, gap=50)
            # column 1 is the first cell when it starts at the left margin; a word at the column-2 edge that
            # follows column-1 text with a normal word gap still belongs to column 2
            c1 = cl[0] if cl[0][0]["x0"] < X1 + 30 else []
            cut = next((i for i, w in enumerate(c1) if i and abs(w["x0"] - (X2 + 3)) <= 3), None)
            c1 = c1[:cut] if cut else c1
            rest = [w for w in ws if w not in c1]
            if ti is not None:
                first = " ".join(pending + ([txt(c1)] if c1 else []))
                cur = {"sec": sec, "sec_year": sec_year, "c1": [first] if first else [], "other": [],
                       "dev": txt([w for w in ws[:ti] if w not in c1])}
                pending = []
                cards.append(cur)
                cur["other"].append(txt(rest))
                continue
            if c1 and not rest and not re.search(r"County$", txt(c1)) and (
                    cur is None or any(CITY_RX.match(x) for x in cur["c1"][1:])):
                pending.append(txt(c1))  # name wrapped onto the line above its card's first line
                continue
            if cur is None:
                continue
            if c1:
                cur["c1"].append(txt(c1))
            if rest:
                cur["other"].append(txt(rest))
    return cards


def money(m):
    return int(m.replace("$", "").replace(",", "").strip()) if m else None


def card_row(c):
    segs = [re.sub(r"\s+", " ", x).strip() for x in c["c1"] if x.strip()]
    name = segs[0] if segs else ""
    ci = next((i for i, x in enumerate(segs[1:], 1) if CITY_RX.match(x)), None)
    addr = "; ".join(segs[1:ci]) if ci else ""
    city = zp = ""
    if ci:
        m = CITY_RX.match(segs[ci])
        city, zp = m.group("city").strip(" ,"), m.group("zip") or ""
    if ci is None and len(segs) > 1 and not re.match(r"\d", segs[1]):
        city = segs[1]  # e.g. "Oakley, Osborne, Hill City, Plainville" (multi-town scattered sites, no ", KS")
    if re.match(r"(?i)^scattered\s+sites?\.?$", addr):
        addr = ""
    o = " ".join(c["other"])
    amt = (re.search(r"LIHTC Award:\s*(\$[\d,]+)", o) or re.search(r"TC Reservation\s+(\$[\d,]+)", o)
           or re.search(r"(?<!HOME )(?<!NHTF )Reservation\s+(\$[\d,]+)", o))
    tc = re.search(r"(?:TC Units:|H/U|^Units|\bUnits)\s*(\d+)", o)
    mk = re.search(r"(?:M [Uu]nits:|M/U)\s*(\d+)", o)
    nu = re.search(r"Number of/?\s*Units:\s*(\d+)", o)
    aw = re.search(r"Awarded:\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", o)
    four = bool(re.search(r"TC Reservation\s+4%\s+Allocation", o))
    li = tc.group(1) if tc else ""
    tot = str(int(li) + int(mk.group(1))) if tc and mk else (nu.group(1) if nu else "")
    yr = None
    if aw:
        y = aw.group(3)
        yr = int(y) + 2000 if len(y) == 2 else int(y)
    return {"PROJECT": re.sub(r"\*+$", "", name).strip(), "PROJ_ADD": addr, "PROJ_CTY": city, "PROJ_ZIP": zp,
            "N_UNITS": tot, "LI_UNITS": li or (nu.group(1) if nu else ""), "COMPANY": c["dev"],
            "ALLOCAMT": str(money(amt.group(1))) if amt else "", "_four": four, "_aw": aw.group(0)[9:].strip() if aw else "",
            "_awyr": yr}


def parse_leg(path):
    """Legislative report award table: name | city | county | 4%/9% | ... | target pop | affordable units ..."""
    out = []
    for pg in pdfplumber.open(path).pages:
        ls = lines_of(pg)
        hdr = next(((t, ws) for t, ws in ls if re.search(r"\d{4} Awards", txt(ws)) and any(w["text"] == "City" for w in ws)), None)
        if not hdr:
            continue
        for t, ws in ls:
            if t <= hdr[0]:
                continue
            ci = next((i for i, w in enumerate(ws) if re.fullmatch(r"[49]%", w["text"])), None)
            if ci is None:
                continue
            cl = cells(ws[:ci])
            if len(cl) != 3:
                print(f"  WARN {path.name}: cannot split name/city/county: {txt(ws[:ci])}", file=sys.stderr)
            name, city = txt(cl[0]), (txt(cl[1]) if len(cl) > 1 else "")
            tail = txt(ws[ci + 1:])
            m = re.search(r"\b(55\+|General|Senior|Family|Elderly)\s+(\d[\d,]*)\b", tail)
            out.append({"PROJECT": name, "PROJ_CTY": city, "CREDIT": "4% (bond)" if ws[ci]["text"] == "4%" else "9%",
                        "LI_UNITS": m.group(2).replace(",", "") if m else ""})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "ks"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], []

    def get(url):
        dest = pdir / url.rsplit("/", 1)[1]
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            return None
        return dest

    leg = {}
    for yr, url, title in LEG:
        dest = get(url)
        if dest:
            leg[yr] = (parse_leg(dest), url, title)
            print(f"{dest.name}: {len(leg[yr][0])} award rows "
                  f"(9%: {sum(r['CREDIT'] == '9%' for r in leg[yr][0])}, 4%: {sum(r['CREDIT'] != '9%' for r in leg[yr][0])})")

    for yr, url, title in POSTINGS:
        dest = get(url)
        if not dest:
            continue
        cards = parse_cards(dest)
        n = Counter()
        for c in cards:
            r = card_row(c)
            if c["sec"] not in ("9", "4"):
                continue
            if r["_four"] or c["sec"] == "4":
                r["CREDIT"] = "4% (bond)"
            elif r["ALLOCAMT"]:
                r["CREDIT"] = "9%"
            else:
                n["no LIHTC"] += 1
                continue  # HOME / NHTF only
            r["YR_ALLOC"] = str(yr)
            r["SRC_LABEL"] = f"KHRC {title} (YR_ALLOC = credit year; awarded the year before)" + (
                " - 4% allocation, no 9% amount" if r["CREDIT"] != "9%" else "")
            r["SRC_URL"] = url
            if not r["LI_UNITS"] and yr - 1 in leg:
                m = next((x for x in leg[yr - 1][0] if x["CREDIT"] == "9%" and same(x["PROJECT"], r["PROJECT"])), None)
                if m and m["LI_UNITS"]:
                    r["LI_UNITS"] = m["LI_UNITS"]
                    r["SRC_LABEL"] += f"; LI_UNITS from {leg[yr - 1][2]}"
            n[r["CREDIT"]] += 1
            rows.append(r)
        print(f"{dest.name}: {len(cards)} cards -> {dict(n)}")

    dest = get(PAB)
    pab_rows = []
    if dest:
        cards = parse_cards(dest)
        for c in cards:
            r = card_row(c)
            if not r["_awyr"] or r["_awyr"] < 2020:
                continue
            r.update({"YR_ALLOC": str(r["_awyr"]), "CREDIT": "4% (bond)", "ALLOCAMT": "", "SRC_URL": PAB,
                      "SRC_LABEL": f"KHRC Private Activity Bond Allocation List (updated 11/13/2025) - "
                                   f"{c['sec_year']} allocation, awarded {r['_aw']} (YR_ALLOC = award year; bond deal, 4% credit)"})
            pab_rows.append(r)
        rows += pab_rows
        print(f"{dest.name}: {len(cards)} cards, {len(pab_rows)} awarded 2020 or later")

    for yr, (lr, url, title) in sorted(leg.items()):
        add = 0
        for x in lr:
            if x["CREDIT"] == "9%":
                continue
            if any(same(x["PROJECT"], p["PROJECT"]) and abs(int(p["YR_ALLOC"]) - yr) <= 1 for p in pab_rows):
                continue
            rows.append({**x, "YR_ALLOC": str(yr), "SRC_URL": url,
                         "SRC_LABEL": f"KHRC {title} - 4% award (state credit report; city only, not on the PAB list)"})
            add += 1
        print(f"{title}: {add} 4% rows not on the PAB list added")

    with open(out / "ks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in COLS} for r in rows)
    print(f"wrote {len(rows)} rows -> {out / 'ks.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

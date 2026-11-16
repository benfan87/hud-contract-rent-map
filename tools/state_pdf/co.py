"""Colorado Housing and Finance Authority (CHFA) housing tax credit award reports -> extracted/co.csv.

Sources (all ruled single-table PDFs, parsed with pdfplumber extract_tables and header-name column mapping):
  * Round One / Round Two award reports 2020-2026. Round One = competitive federal 9% (+ state credit); its
    "4% Non-Competitive Paired with ..." subsection (2020-2021) is 4%, its "9% ... Paired with 4%" subsection is 9%.
    Round Two = federal 4% + state credit (bond deals).
  * Federal 4% Housing Tax Credit Award Report (active 4% awards, no 8609 yet; cycle years 2021-2026) and the
    4% Completed Developments report (8609s issued; only cycle year >= 2020 kept). These cover the 4% bond deals
    that got no state credit. A 4% row already present from a Round report (same name or address, cycle year within
    1 of the round year) is not repeated; its ZIP fills the Round row's ZIP when that report has no ZIP column.
Dropped: TOTAL/subtotal rows, legend rows, and awards footnoted "Project did not proceed. Award returned by sponsor."
YR_ALLOC = the round year (Round reports) or the Cycle Year (4% reports).

Usage (from the repo root): python tools/state_pdf/co.py --out ../hud_src/lihtc/states/extracted
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
GA = "https://www.chfainfo.com/getContentAsset/"
L = "?language=en-US"
P = "50c2bc4c-a8ff-46ba-95c2-0e74752d147f/"
# (year, round label, url)
ROUNDS = [
    (2020, "Round 1", GA + "3cc9acfe-0e46-455d-ac37-a2167b823a9d/" + P + "2020-Round-1-Award-Report.pdf" + L),
    (2020, "Round 2", GA + "1891e481-b584-4155-962c-3f3bbff94357/" + P + "2020-Round-2-Award-Report.pdf" + L),
    (2021, "Round 1", GA + "73c04756-71db-42a0-a4fb-1d3a5f0ffb83/" + P + "2021-Round-1-Award-Report.pdf" + L),
    (2021, "Round 2", GA + "50dd8292-24b8-4ed9-b285-304b4401ae87/" + P + "2021-Round-2-Award-Report.pdf" + L),
    (2022, "Round 1", GA + "2faf4402-3d4d-4e15-8dc9-43d55c164c5a/" + P + "2022-Round-1-Award-Report.pdf" + L),
    (2022, "Round 2", GA + "5e11c07a-670e-42b2-b978-53f0a2db1635/" + P + "2022-Round-2-Award-Report.pdf" + L),
    (2023, "Round 1", GA + "037e65b5-e51c-4920-864a-41ac174b6558/" + P + "2023-Round-1-Housing-Tax-Credit-Award-Report.pdf" + L),
    (2023, "Round 2", GA + "752a4aa7-ed6c-4e6f-b279-f6a68cd7cd0f/" + P + "2023-Round-2-Housing-Tax-Credit-Award-Report.pdf" + L),
    (2024, "Round 1", GA + "a87d0b61-b330-44f7-9a73-382779f7ef11/" + P + "2024-Round-One-Housing-Tax-Credit-Award-Report.pdf" + L),
    (2024, "Round 2", GA + "c579304d-6db4-4e17-90ab-727158c22d13/" + P + "2024-Round-Two-Housing-Tax-Credit-Award-Report.pdf" + L),
    (2025, "Round 1", GA + "b90453bd-52f8-491f-be44-c7a431440afc/" + P + "2025-Round-One-Housing-Tax-Credit-Award-Report.pdf" + L),
    (2025, "Round 2", GA + "a9fca2aa-7fde-4400-8a97-b02340419c92/" + P + "2025-Round-Two-Award-Report.pdf" + L),
    (2026, "Round 1", GA + "307fc9f0-5255-4afa-a86d-301dd2be20fa/" + P + "2026-Round-One-Housing-Tax-Credit-Award-Report.pdf" + L),
    (2026, "Round 2", GA + "8211a644-1911-4044-a07f-5847fe1e283c/141d77fc-2e06-49eb-b14c-2ff58f5ce730/"
     "2026-Round-Two-Housing-Tax-Credit-Award-Report.pdf" + L),
]
FOUR_ACTIVE = GA + "34a30942-e08d-494a-8bc7-f236ebf01e98/" + P + "federal-4-housing-tax-credit-award-report.pdf" + L
FOUR_DONE = GA + "986a6057-8ac2-480e-87df-b3907b4af544/" + P + "4percenthousingtaxcreditcompleteddevelopments.pdf" + L

HDR = {  # field -> regex on the normalized header cell (first match per field wins)
    "name": r"^(property )?name$",
    "addr": r"^address$",
    "city": r"^city$",
    "zip": r"^zip( code)?$",
    "tot": r"^total units$",
    "li": r"^(total )?(li|tc|total tc) units$|^total li units$|^li units$",
    "fed": r"^(credit amount (requested|awarded)|federal credit( amount)?|federal [49]% credit (awarded|amount issued.*))$",
    "co": r"^(owner name|ownership|developer|sponsor( name)?)$",
    "yr": r"^cycle year$",
}


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


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("‐", "-").replace("‑", "-")).strip()


def hnorm(s):
    return re.sub(r"[^a-z0-9% ]", "", clean(s).lower()).strip()


def money(s):
    m = re.search(r"\$\s*([\d,]+)", s or "")
    return int(m.group(1).replace(",", "")) if m else None


def num(s):
    s = re.sub(r"\s", "", s or "")
    return s if re.fullmatch(r"\d[\d,]*", s) else ""


def key(s):
    s = re.sub(r"\(.*?\)", "", (s or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


def tables(path):
    """Yield (page_no, header_map, rows) per table, header_map: field -> column index."""
    pdf = pdfplumber.open(path)
    for pg in pdf.pages:
        for t in pg.extract_tables():
            if not t:
                continue
            hi = next((i for i, r in enumerate(t[:3]) if any(re.match(HDR["name"], hnorm(c)) for c in r if c)), None)
            if hi is None:
                continue
            hm = {}
            for j, c in enumerate(t[hi]):
                h = hnorm(c)
                for f, rx in HDR.items():
                    if f not in hm and re.match(rx, h):
                        hm[f] = j
            yield pg.page_number, hm, t[hi + 1:]


def parse_round(path, yr, rnd):
    pdf = pdfplumber.open(path)
    text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    head = clean(" ".join(text.split("\n")[:4]))
    base_credit = "4% (bond)" if re.search(r"4% Federal Credit|Federal 4%", head) else "9%"
    m = re.search(r"^\s*(\*+)\s*Project did not proceed", text, re.M)
    dead = m.group(1) if m else None
    out, dropped = [], []
    for pno, hm, rows in tables(path):
        credit, section = base_credit, ""
        for r in rows:
            cell = lambda f: clean(r[hm[f]]) if f in hm and hm[f] < len(r) and r[hm[f]] else ""
            first = clean(r[0])
            if re.search(r"Paired with", first, re.I) and not cell("fed"):
                section = first
                credit = "4% (bond)" if first.lstrip().startswith("4%") else "9%"
                continue
            name, fed = cell("name"), money(cell("fed"))
            if not name or fed is None or re.search(r"\bTotals?\b", name, re.I):
                continue
            if dead and re.search(re.escape(dead) + r"\s*(\(|$)", name) and not name.endswith(dead + "*"):
                dropped.append(name)
                continue
            name = re.sub(r"\s*\*+\s*", " ", name).strip()
            label = f"CHFA {yr} {rnd} Housing Tax Credit Award Report" + (f" - {section}" if section else "")
            out.append({"PROJECT": name, "PROJ_ADD": cell("addr"), "PROJ_CTY": cell("city"),
                        "PROJ_ZIP": (re.search(r"\d{5}", cell("zip")) or [""])[0], "YR_ALLOC": str(yr), "CREDIT": credit,
                        "N_UNITS": num(cell("tot")), "LI_UNITS": num(cell("li")), "COMPANY": cell("co"),
                        "ALLOCAMT": str(fed), "STATE_ID": "", "SRC_LABEL": label})
    return out, dropped


def parse_four(path, label, min_year=2020):
    """4% reports: odd pages hold the property table, even pages the sponsor/owner table (joined by name)."""
    props, owners = [], {}
    for pno, hm, rows in tables(path):
        for r in rows:
            cell = lambda f: clean(r[hm[f]]) if f in hm and hm[f] < len(r) and r[hm[f]] else ""
            if "yr" in hm:
                y = cell("yr")
                if re.fullmatch(r"\d{4}", y) and int(y) >= min_year and cell("name"):
                    props.append({"PROJECT": cell("name"), "PROJ_ADD": cell("addr"), "PROJ_CTY": cell("city"),
                                  "PROJ_ZIP": (re.search(r"\d{5}", cell("zip")) or [""])[0], "YR_ALLOC": y,
                                  "CREDIT": "4% (bond)", "N_UNITS": num(cell("tot")), "LI_UNITS": num(cell("li")),
                                  "COMPANY": "", "ALLOCAMT": str(money(cell("fed")) or ""), "STATE_ID": "",
                                  "SRC_LABEL": label})
            elif "co" in hm and cell("name"):
                owners.setdefault(key(cell("name")), cell("co"))
    for p in props:
        p["COMPANY"] = owners.get(key(p["PROJECT"]), "")
        # CHFA tags resyndications with the cycle year ("Windsor Court 2022"); drop that suffix from the name
        p["PROJECT"] = re.sub(r"\s+" + p["YR_ALLOC"] + r"$", "", p["PROJECT"])
    return props


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "co"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], []

    def get(url):
        dest = pdir / url.split("?")[0].rsplit("/", 1)[1]
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            return None
        return dest

    for yr, rnd, url in ROUNDS:
        dest = get(url)
        if not dest:
            continue
        rs, dropped = parse_round(dest, yr, rnd)
        for r in rs:
            r["SRC_URL"] = url
        rows += rs
        n9 = sum(r["CREDIT"] == "9%" for r in rs)
        print(f"{dest.name}: {len(rs)} rows (9%: {n9}, 4%: {len(rs) - n9})" + (f"; dropped not-proceeded: {dropped}" if dropped else ""))

    four_rows = [r for r in rows if r["CREDIT"].startswith("4")]
    for url, label, miny in [
        (FOUR_ACTIVE, "CHFA Federal 4% Housing Tax Credit Award Report (active awards, no 8609 yet; YR_ALLOC = cycle year)", 2020),
        (FOUR_DONE, "CHFA Federal 4% Housing Tax Credit Developments - 8609s issued (YR_ALLOC = cycle year)", 2020),
    ]:
        dest = get(url)
        if not dest:
            continue
        props = parse_four(dest, label, miny)
        new = dup = 0
        for p in props:
            y = int(p["YR_ALLOC"])
            m = next((r for r in four_rows if abs(int(r["YR_ALLOC"]) - y) <= 1 and (
                key(r["PROJECT"]) == key(p["PROJECT"]) or (p["PROJ_ADD"] and key(r["PROJ_ADD"]) == key(p["PROJ_ADD"])))), None)
            if m:
                dup += 1
                if not m["PROJ_ZIP"] and p["PROJ_ZIP"]:
                    m["PROJ_ZIP"] = p["PROJ_ZIP"]
                continue
            p["SRC_URL"] = url
            rows.append(p)
            four_rows.append(p)
            new += 1
        print(f"{dest.name}: {len(props)} rows with cycle year >= {miny}; {dup} already in a Round report, {new} added")

    with open(out / "co.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in COLS} for r in rows)
    print(f"wrote {len(rows)} rows -> {out / 'co.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

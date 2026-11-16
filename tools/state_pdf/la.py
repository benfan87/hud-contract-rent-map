"""Louisiana Housing Corporation (LHC) LIHTC award lists + pipeline reports -> standard CSV.

Sources (all ruled tables; parsed cell-by-cell from the table rules, text rebuilt from characters so overlapping /
wrapped lines inside a cell come out in order):
  * 9% competitive round "Final Rankings" / awards lists (2020, 2020-2021, 2022-2023, 2024, 2025). Rows under each
    pool are reservations (they sum to the pool's "Funds Reservations" line); the "Waiting List" pages are not awards
    and are dropped (exception: the 2020 list, whose "2019 Waiting List" section is itself funded with 2020 credits).
    These lists give parish only.
  * Board "Pipeline Reports" (Oct 2023 and Feb 2026): every awarded-but-not-yet-placed-in-service 9% and 4%/bond deal
    with Project #, funding round, award date, parish, city and ZIP. Used (a) to add city / ZIP / Project # to ranking
    rows (matched on name + parish), and (b) as the source of 4% (bond / PRIME) awards and of 9% awards from rounds
    whose ranking list is not online. A project # in both pipeline reports is kept once (latest report).
  * Not used for rows: the 4/13/22 version of the 2022-2023 list (superseded by the 4/19/22 final list) and the PRIME 3
    "9 Percent" awards list (CDBG-DR gap funding for projects already holding 9% awards - no new LIHTC award).
YR_ALLOC = funding-round year (pipeline "Funding Round" column, else the list's round year; the "2022-2023" round
counts as 2022). CREDIT from the pipeline "Credits Type" column; ranking-list rows are 9%. No street addresses.
Usage: python tools/state_pdf/la.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import urllib.parse
import urllib.request

import pdfplumber

LHC = "https://www.lhc.la.gov/hubfs/"
FILES = [
    # kind, round year, label, url
    ("pipe", None, "LHC Programs Report - pending LIHTC properties pipeline (Feb 2026 board materials)",
     "https://webapps3.lhc.la.gov/documents/BoardCommitteeMaterials/2026/March/BODM/LHC%20Programs%20Report.pdf"),
    ("pipe", None, "LHC 4% & 9% LIHTC pipeline report (Oct 2023 board materials)",
     "https://webapps3.lhc.la.gov/documents/BoardCommitteeMaterials/2023/November/BODM/FULL_Final_Pipeline_Report_10_2023.pdf"),
    ("rank", 2025, "LHC final 2025 QAP rankings (as of 10/15/25)",
     LHC + "Document%20Libraries/Housing%20Development/Funding%20Opportunities/LIHTC/Final%202025%20QAP%20Rankings%20as%20of%2010.15.25.pdf"),
    ("rank", 2024, "LHC 2024 LIHTC final rankings (as of 7/12/23)", LHC + "2024%20LIHTC%20Final%20Rankings-1.pdf"),
    ("rank", 2022, "LHC 2022-2023 LIHTC final awards list (as of 4/19/22)",
     LHC + "Document%20Libraries/Housing%20Development/Funding%20Opportunities/LIHTC/Final%202022%20Awards%20List%20and%20summary%20as%20of%20041922.pdf"),
    ("superseded", 2022, "LHC 2022-2023 final awards list and waiting list (as of 4/13/22)",
     LHC + "Document%20Libraries/Housing%20Development/Funding%20Opportunities/Funding%20Archives/Awards%20List/2022-2023%20Final%20Awards%20List%20and%20Waiting%20List.pdf"),
    ("rank", 2021, "LHC 2020-2021 LIHTC final awards list (as of 2/10/21)",
     LHC + "Document%20Libraries/Housing%20Development/Funding%20Opportunities/LIHTC/2021%20Final%20Awards%20List%20and%20Waiting%20List.pdf"),
    ("rank2020", 2020, "LHC 2020 LIHTC final rankings / awards (as of 4/28/20)",
     "https://webapps3.lhc.la.gov/documents/BoardCommitteeMaterials/2020/May/AwardsList2020Summary.pdf"),
    ("cdbg", 2024, "LHC PRIME 3 CDBG-DR 9% awards list round 1",
     LHC + "Document%20Libraries/Public%20Comments%20and%20Notices/Funding%20Announcements/PRIME-3%209%20Percent%20Awards%20List%20Round%201.pdf"),
]
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=180) as r:
            data = r.read()
    except Exception as e:
        print(f"SKIP {url}: {e}")
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def clean(s):
    s = (s or "").replace("‐", "-").replace("‑", "-").replace("–", "-").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def group_lines(items, tol):
    lines = []
    for c in sorted(items, key=lambda c: (c["top"], c["x0"])):
        if lines and abs(lines[-1][0] - c["top"]) <= tol:
            lines[-1][1].append(c)
        else:
            lines.append([c["top"], [c]])
    return [sorted(cs, key=lambda c: c["x0"]) for _, cs in lines]


def cell_text(chars):
    if not chars:
        return ""
    sz = sorted(c["size"] for c in chars)[len(chars) // 2]
    out = []
    for ln in group_lines(chars, tol=0.3 * sz):
        t, prev = "", None
        for c in ln:
            if prev is not None and c["x0"] - prev["x1"] > 0.2 * sz and not t.endswith(" "):
                t += " "
            t += c["text"]
            prev = c
        out.append(t)
    return clean(" ".join(out))


def merge_xs(xs, tol=2.0):
    out = []
    for x in sorted(xs):
        if not out or x - out[-1] > tol:
            out.append(x)
    return out


def grid_rows(pdf):
    """Yield (page_no, top, [(x0, x1, text), ...]) for every ruled row band that has text."""
    for pn, pg in enumerate(pdf.pages, 1):
        hs = merge_xs([e["top"] for e in pg.edges if e["orientation"] == "h" and e["width"] > 20], 1.5)
        vs = [e for e in pg.edges if e["orientation"] == "v" and e["height"] > 3]
        chars = [c for c in pg.chars if c["size"] < 30]  # drop giant "DRAFT" watermark glyphs
        for y0, y1 in zip(hs, hs[1:]):
            if y1 - y0 < 4:
                continue
            band = [c for c in chars if y0 < (c["top"] + c["bottom"]) / 2 < y1]
            if not any(c["text"].strip() for c in band):
                continue
            mid = (y0 + y1) / 2
            xs = merge_xs([e["x0"] for e in vs if e["top"] - 1 <= mid <= e["bottom"] + 1])
            if len(xs) < 2:
                xs = [0, pg.width]
            cells = []
            for lo, hi in zip(xs, xs[1:]):
                cc = [c for c in band if lo <= (c["x0"] + c["x1"]) / 2 < hi]
                t = cell_text(cc)
                if t:
                    cells.append((lo, hi, t))
            yield pn, y0, cells


def label_key(t):
    k = re.sub(r"[^a-z#%]", "", t.lower())
    for pat, key in ((r"^#$", "seq"), (r"projname|projectname", "name"), (r"projnum|project#", "projno"),
                     (r"parish", "parish"), (r"city", "city"), (r"zip", "zip"), (r"units", "units"),
                     (r"credits?type", "ctype"), (r"lihtcaward|lihtcrequest|award$|lihtcaward", "amount"),
                     (r"fund.*round|fundround|round", "round"), (r"finalscore|score", "score"),
                     (r"number", "projno"), (r"contact|taxpayer|developer", "contact"), (r"pool", "pool"),
                     (r"status", "status")):
        if re.search(pat, k):
            return key
    return None


def table_records(path):
    """Header-mapped records from every ruled table in the PDF, with the section title and page title attached."""
    recs = []
    with pdfplumber.open(path) as pdf:
        hdr, section, page_title, last_pn = None, "", "", 0
        for pn, top, cells in grid_rows(pdf):
            if pn != last_pn:
                pg = pdf.pages[pn - 1]
                page_title = clean(pg.crop((0, 0, pg.width, min(pg.height, 110))).extract_text() or "")
                last_pn = pn
            joined = " ".join(t for _, _, t in cells)
            keys = [label_key(t) for _, _, t in cells]
            if "name" in keys and ("parish" in keys or "units" in keys) and len(cells) >= 5:
                hdr = [(lo, hi, k) for (lo, hi, _), k in zip(cells, keys)]
                continue
            if len(cells) <= 2 and not re.search(r"\$|\d{2,}", joined):
                section = joined
            if hdr is None:
                continue
            rec = {"_page": pn, "_section": section, "_title": page_title, "_line": joined}
            for lo, hi, t in cells:
                best, ov = None, 0
                for hlo, hhi, k in hdr:
                    o = min(hi, hhi) - max(lo, hlo)
                    if o > ov:
                        best, ov = k, o
                if best:
                    rec[best] = (rec.get(best, "") + " " + t).strip()
            recs.append(rec)
    return recs


def money(s):
    m = re.search(r"\d[\d,]*(\.\d+)?", (s or "").replace(" ", ""))
    return round(float(m.group(0).replace(",", ""))) if m else 0


def norm(s):
    s = (s or "").lower().replace("&", "and")
    s = re.sub(r"\(.*?\)|\*+\d?|\bphase\b|\bph\b|\bapartments?\b|\bapts\b|\bthe\b|\bpart\b|-\s*reprocessing", " ", s)
    s = re.sub(r"\b(iv)\b", "4", s)
    s = re.sub(r"\b(iii)\b", "3", s)
    s = re.sub(r"\b(ii)\b", "2", s)
    s = re.sub(r"\b(i)\b", "1", s)
    return re.sub(r"[^a-z0-9]", "", s)


def parse_pipe(path, label, url):
    out = []
    for r in table_records(path):
        pno = re.sub(r"\s+", "", r.get("projno", "")).rstrip("*")
        if not re.match(r"^\d{4}-\d{3}", pno):
            continue
        ctype = r.get("ctype", "")
        if not ctype:  # Oct 2023 report: credit type from the page title
            ctype = "LIHTC (4%)" if "4%" in r["_title"] else "LIHTC (9%)" if "9%" in r["_title"] else ""
        rnd = re.search(r"(19|20)\d\d", r.get("round", ""))
        zipm = re.search(r"\b\d{5}\b", r.get("zip", ""))
        city = re.sub(r",$", "", r.get("city", "")).strip()
        city = re.sub(r"\s*\(.*?\)\s*", " ", city).strip() if "town" in city else city
        city = re.sub(r"\b([A-Z][a-z]{3,}) ([a-z]{1,3})\b", r"\1\2", city)  # word wrapped in a narrow cell
        name = re.sub(r"\s+R$", "", r.get("name", "")).strip()  # "R" = reprocessing flag in the 2023 report
        name = re.sub(r"\s*-\s*Reprocessing$", "", name, flags=re.I)
        out.append({
            "PROJECT": name, "PROJ_ADD": "", "PROJ_CTY": city, "PROJ_ZIP": zipm.group(0) if zipm else "",
            "YR_ALLOC": int(rnd.group(0)) if rnd else int(pno[:4]),
            "CREDIT": "4% (bond)" if "4%" in ctype else "9%" if "9%" in ctype else "",
            "N_UNITS": (re.search(r"\d+", r.get("units", "").replace(",", "")) or [""])[0],
            "LI_UNITS": "", "COMPANY": "", "ALLOCAMT": money(r.get("amount")), "STATE_ID": pno,
            "SRC_LABEL": label, "SRC_URL": url, "_parish": r.get("parish", ""), "_norm": norm(name)})
    return out


def parse_rank(path, year, label, url, keep_waiting=False):
    out = []
    for r in table_records(path):
        if not re.fullmatch(r"\d{1,3}", (r.get("seq") or r.get("score") or "").split(" ")[0] or "x") \
                and not re.match(r"^\d{1,3}\b", r["_line"]):
            continue
        if not keep_waiting and re.search(r"waiting list", r["_title"] + " " + r["_section"], re.I):
            continue
        name = r.get("name", "")
        if not name or re.search(r"funds|reservations|balance|total", name, re.I):
            continue
        amt = money(r.get("amount"))
        if not amt:
            continue
        name = re.sub(r"^\*+\d?\s*", "", name).strip()
        out.append({
            "PROJECT": name, "PROJ_ADD": "", "PROJ_CTY": "", "PROJ_ZIP": "", "YR_ALLOC": year, "CREDIT": "9%",
            "N_UNITS": (re.search(r"\d+", r.get("units", "")) or [""])[0], "LI_UNITS": "", "COMPANY": "",
            "ALLOCAMT": amt, "STATE_ID": re.sub(r"\s+", "", r.get("projno", "")),
            "SRC_LABEL": label, "SRC_URL": url, "_parish": r.get("parish", ""), "_norm": norm(name),
            "_section": r["_section"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--pdf-dir", default=None)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    pdf_dir = a.pdf_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "pdf", "la")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    pipe, ranks = [], []
    for kind, year, label, url in FILES:
        fn = os.path.join(pdf_dir, urllib.parse.unquote(url.split("/")[-1]).replace(" ", "_"))
        if not fetch(url, fn):
            continue
        if kind == "pipe":
            rows = parse_pipe(fn, label, url)
            seen = {r["STATE_ID"] for r in pipe}
            new = [r for r in rows if r["STATE_ID"] not in seen]
            print(f"{os.path.basename(fn)}: {len(rows)} pipeline rows "
                  f"({sum(r['CREDIT'] == '9%' for r in rows)} x 9%, {sum(r['CREDIT'] != '9%' for r in rows)} x 4%), "
                  f"{len(new)} not already in a later report")
            pipe += new
        elif kind in ("rank", "rank2020"):
            rows = parse_rank(fn, year, label, url, keep_waiting=(kind == "rank2020"))
            print(f"{os.path.basename(fn)}: {len(rows)} awarded rows")
            ranks += rows
        else:
            print(f"{os.path.basename(fn)}: not used for rows ({kind})")
    # enrich ranking rows from the pipeline (name + parish); matched pipeline rows are not output separately
    used = set()
    for r in ranks:
        ry = int(r["YR_ALLOC"])
        cands = [p for p in pipe if p["CREDIT"] == "9%"
                 and (not r["_parish"] or p["_parish"].lower() == r["_parish"].lower())
                 and (p["_norm"] == r["_norm"] or (len(r["_norm"]) > 6 and (r["_norm"] in p["_norm"] or p["_norm"] in r["_norm"])))
                 and abs(int(p["YR_ALLOC"]) - ry) <= 2 and p["STATE_ID"] not in used]
        cands.sort(key=lambda p: (p["_norm"] != r["_norm"], abs(int(p["YR_ALLOC"]) - ry)))
        if r["STATE_ID"]:  # the 2020 list carries Project Numbers (awards to existing projects)
            cands = [p for p in pipe if p["STATE_ID"] == r["STATE_ID"]] or cands
        if cands:
            p = cands[0]
            if abs(int(p["YR_ALLOC"]) - ry) <= 2:  # same award; otherwise an earlier award to the same project
                used.add(p["STATE_ID"])
            r.update(PROJ_CTY=p["PROJ_CTY"], PROJ_ZIP=p["PROJ_ZIP"])
            r["STATE_ID"] = r["STATE_ID"] or p["STATE_ID"]
            if not r["N_UNITS"]:
                r["N_UNITS"] = p["N_UNITS"]
            r["_match"] = p["PROJECT"] + " / " + p["STATE_ID"]
    extra = [p for p in pipe if p["STATE_ID"] not in used]
    print(f"ranking rows matched to pipeline: {sum(1 for r in ranks if r['PROJ_CTY'])}/{len(ranks)}; "
          f"pipeline-only rows added: {len(extra)} ({sum(p['CREDIT'] == '9%' for p in extra)} x 9%)")
    if a.debug:
        for p in extra:
            if p["CREDIT"] == "9%":
                print("  pipeline-only 9%:", p["STATE_ID"], p["PROJECT"], p["YR_ALLOC"])
        for r in ranks:
            print("  rank:", r["YR_ALLOC"], r["PROJECT"], "|", r["_parish"], "->", r.get("_match", "UNMATCHED"))
    rows = ranks + extra
    out = os.path.join(a.out, "la.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()

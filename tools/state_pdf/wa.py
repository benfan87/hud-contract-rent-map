"""Washington State Housing Finance Commission (WSHFC) LIHTC award lists + property inventory -> standard CSV.

Sources:
  * 9% Housing Tax Credit "Allocation List" PDFs, credit years 2021-2026 (ruled tables; one table per geographic pool).
    Rows in the pool tables are allocations (they sum to each pool's "Credit Allocated" line); rows in the
    "Waiting List" / "Wait List" / "Unranked (Noncompetitive or Awaiting Other Funding Commitments)" /
    "Non-Fully Funded - Unranked" sections are not awards and are dropped. YR_ALLOC = the list's credit year
    (= the TC# prefix; the round is held the year before, e.g. the 2021 list is dated 12/23/2020).
    ALLOCAMT = annual credit request of the allocated row. LI_UNITS = "Total Low-Income Units".
  * Bond / 4% credit allocation lists: Jan + June 2020, Feb + July 2021 (PDF), 2022 + 2023 (xlsx, "by Points" sheet),
    2024 + 2025 Balance of State (PDF), and the "King County Allocation List" tables (closed financings) printed in
    the 2025 and 2026 King County pre-allocation PDFs (2024, 2025 and 2026 King County awards). Only rows above
    "Awarded Subtotal" / in the allocated sections are kept: "Full allocation contingent on availability of Bond
    Cap", "Remaining/Not Allocated", "Applications not competitively ranked", "Waitlist", "Unranked Projects" and
    the King County "Invitation to Apply" tiers and "Pipeline List" are not awards. The amounts on these lists are
    tax-exempt bond requests, not credit, so ALLOCAMT is left blank. The 2024 King County invitation PDF has no
    allocation table (no rows).
  * "2025 TC Report Types by Property Name" xlsx: WSHFC's whole tax credit compliance portfolio (Project OID, name,
    city, review type, signer, manager, analyst). It has NO street address / ZIP / units / amounts, so nothing can be
    filled into the award rows from it except the TC number. Each property is output once (YR_ALLOC = the OID's
    2-digit allocation-year prefix) unless it matches an award row above (same TC# or same name + city within
    2 years), in which case the award row gets its OID as STATE_ID. CREDIT from the OID: number >= 100 or an "A"
    suffix = bond / 4%; a plain number < 100 = 9%; other letter suffixes (1990s portfolio buildings) = blank.
No WSHFC file gives a project street address or ZIP.
Usage: python tools/state_pdf/wa.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import urllib.parse
import urllib.request

import openpyxl
import pdfplumber

B = "https://wshfc.org/sites/default/files/"
NINE = {y: B + f"2026-05/{y}AllocationList.pdf" for y in range(2021, 2027)}
BOND_LINES = [  # unruled PDFs: (year, label, url, column cuts by character x)
    (2020, "WSHFC 2020 first-round bond/tax credit allocation list (1/10/2020)",
     B + "2026-05/2020BondAllocationList.pdf",
     [("name", 0), ("sponsor", 170), ("te", 380), ("tx", 440), ("county", 585), ("units", 640), ("cpu", 665),
      ("points", 700)]),
    (2020, "WSHFC 2020 second-round bond/tax credit allocation list (8/20/2020)",
     B + "2026-05/JuneRoundBondAllocation8202020.pdf",
     [("name", 0), ("sponsor", 168), ("te", 400), ("tx", 455), ("county", 595), ("units", 655), ("cpu", 695),
      ("points", 738)]),
    (2021, "WSHFC 2021 first-round bond/tax credit allocation list (2/23/2021)",
     B + "2026-05/2021BondAllocationList.pdf",
     [("name", 0), ("sponsor", 160), ("te", 380), ("tx", 440), ("city", 503), ("county", 595), ("units", 660),
      ("cpu", 690), ("points", 730)]),
    (2021, "WSHFC 2021 second-round bond allocation list (8/11/2021)",
     B + "2026-05/July2021RoundAllocationAnnouncement.pdf",  # ruled only around blocks, so cut by x as well
     [("name", 0), ("sponsor", 235), ("te", 415), ("tx", 510), ("units", 600), ("city", 645), ("county", 730),
      ("pool", 782), ("points", 832)]),
]
BOND_GRID = [  # ruled PDFs: (year or None = from table title, label, url)
    (2024, "WSHFC 2024 bond/tax credit Balance of State allocation list",
     B + "2026-05/2024BalanceofStateBondCapList.pdf"),
    (2025, "WSHFC 2025 bond/tax credit Balance of State allocation list",
     B + "2026-05/2025BalanceofStateBondCapList.pdf"),
    (None, "WSHFC {y} King County bond/tax credit allocation list (in the {f} King County pre-allocation list)",
     B + "2026-05/2024KingCountyInvitationtoApplyList.pdf"),
    (None, "WSHFC {y} King County bond/tax credit allocation list (in the {f} King County pre-allocation list)",
     B + "2026-05/2025KingCountyTierList.pdf"),
    (None, "WSHFC {y} King County bond/tax credit allocation list (in the {f} King County pre-allocation list)",
     B + "2026-06/2026KingCountyInvitationtoApplyList_0.pdf"),
]
BOND_XLSX = {2022: B + "2026-05/2022BondAllocationList.xlsx", 2023: B + "2026-05/2023BondAllocationList.xlsx"}
INVENTORY = B + "2026-04/2025%2520TC%2520ReportTypesbyPropertyName.xlsx"  # the server path itself contains "%20"
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
NOT_AWARDED = r"wait(?:ing)?\s*-?\s*list|waitlist|unranked|non-fully|not allocated|remaining|contingent|not compet|pipeline|" \
              r"invitation|tier \d"


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


def local_name(url):
    return urllib.parse.unquote(urllib.parse.unquote(url.split("/")[-1])).replace(" ", "_")


def clean(s):
    s = (s or "").replace("‐", "-").replace("‑", "-").replace("–", "-").replace("’", "'").replace("“", '"')
    s = s.replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def num(s):
    s = re.sub(r"[^\d.]", "", str(s or ""))
    try:
        return round(float(s)) if s else 0
    except ValueError:
        return 0


def group_lines(items, tol):
    lines = []
    for c in sorted(items, key=lambda c: (c["top"], c["x0"])):
        if lines and abs(lines[-1][0] - c["top"]) <= tol:
            lines[-1][1].append(c)
        else:
            lines.append([c["top"], [c]])
    return [(t, sorted(cs, key=lambda c: c["x0"])) for t, cs in lines]


def chars_text(chars, gap=0.2):
    if not chars:
        return ""
    sz = sorted(c["size"] for c in chars)[len(chars) // 2]
    out = []
    for _, ln in group_lines(chars, tol=0.3 * sz):
        t, prev = "", None
        for c in ln:
            if prev is not None and c["x0"] - prev["x1"] > gap * sz and not t.endswith(" "):
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
        chars = pg.chars
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
                t = chars_text([c for c in band if lo <= (c["x0"] + c["x1"]) / 2 < hi])
                if t:
                    cells.append((lo, hi, t))
            yield pn, y0, cells


def label_key(t):
    k = re.sub(r"[^a-z#/]", "", t.lower())
    for pat, key in ((r"^tc#$", "tc"), (r"status", "status"), (r"projectname|developmentname|^development$", "name"),
                     (r"sponsor|developer|applicant", "sponsor"), (r"community|^cbo$", "cbo"), (r"^city$", "city"),
                     (r"^county$", "county"), (r"points", "points"), (r"credit/unit", "cpu"),
                     (r"creditrequest", "amount"), (r"lowincomeunits|incomeunits|^totallow", "li"),
                     (r"bondamount|bondcap$|taxexempt|^bondrequest", "bond"), (r"taxable|recycled", "tx"),
                     (r"publicfunders", "funders"), (r"geographic|policy|priority", "pool"),
                     (r"units", "units"), (r"closed|closing", "closed")):
        if re.search(pat, k):
            return key
    return None


def table_records(path, sections_too=False):
    """Header-mapped records from the ruled tables, with the latest section label and the nearest
    'YYYY King County Allocation List' / list title above each header."""
    recs = []
    with pdfplumber.open(path) as pdf:
        hdr, section, title, prev, hdr_top, hdr_pn = None, "", "", None, -99, 0
        for pn, top, cells in grid_rows(pdf):
            p_prev, prev = prev, (pn, top, cells)
            joined = " ".join(t for _, _, t in cells)
            keys = [label_key(t) for _, _, t in cells]
            is_label = not re.search(r"\$\s*\d|\d{2,}", joined)
            if hdr is not None and pn == hdr_pn and 0 < top - hdr_top < 14 and is_label and len(cells) <= 3 \
                    and any(keys):  # header continued in a thin band below ("Bond Cap", "Amount")
                hdr += [(lo, hi, k) for (lo, hi, _), k in zip(cells, keys) if k]
                hdr_top = top
                continue
            if "name" in keys and len(set(keys) - {None}) >= 3 and len(cells) >= 3:
                hdr = [(lo, hi, k) for (lo, hi, _), k in zip(cells, keys) if k]
                if p_prev and p_prev[0] == pn and 0 < top - p_prev[1] < 14:  # header begun in a thin band above
                    hdr += [(lo, hi, label_key(t)) for lo, hi, t in p_prev[2] if label_key(t)]
                hdr_pn, hdr_top = pn, top
                pg = pdf.pages[pn - 1]
                above = [ln for t, ln in group_lines([c for c in pg.chars if c["bottom"] < top], 2)]
                titles = [chars_text(ln) for ln in above]
                title = next((t for t in reversed(titles) if re.search(r"(allocation|invitation|pipeline|tier)\b.*"
                                                                       r"list|list\s*-|^\d{4} .*list", t, re.I)), "")
                section = ""
                continue
            if hdr is None and not sections_too:
                continue
            if len(cells) <= 2 and not re.search(r"\$\s*\d|\d{2,}", joined):
                section = joined
                if not sections_too:
                    continue
            rec = {"_page": pn, "_section": section, "_title": title, "_line": joined}
            for lo, hi, t in cells:
                best, ov = None, 0
                for hlo, hhi, k in hdr or []:
                    o = min(hi, hhi) - max(lo, hlo)
                    if o > ov:
                        best, ov = k, o
                if best:
                    rec[best] = (rec.get(best, "") + " " + t).strip()
            recs.append(rec)
    return recs


def fix_city(s):
    s = re.sub(r"\b([A-Z]) ([a-z]{2,})", r"\1\2", clean(s))  # "R enton"
    return re.sub(r"\b([A-Z][a-z]{3,}) ([a-z]{1,3})\b", r"\1\2", s)


def row(name, city, year, credit, units, li, company, amt, sid, label, url):
    name = re.sub(r"\s*-?\s*\b[49]%$", "", clean(name).rstrip("*^# ").strip())  # "Eastgate PSH 9%" (hybrid tag)
    return {"PROJECT": name, "PROJ_ADD": "", "PROJ_CTY": fix_city(city),
            "PROJ_ZIP": "", "YR_ALLOC": year, "CREDIT": credit, "N_UNITS": units, "LI_UNITS": li,
            "COMPANY": clean(company), "ALLOCAMT": amt, "STATE_ID": sid, "SRC_LABEL": label, "SRC_URL": url}


def parse_nine(path, year, url):
    """Every band is read in order: pool / section labels switch 'awarded' on or off; TC# rows are kept while on.
    Each pool's kept credit is checked against the largest "Credit Allocated" line printed in that pool."""
    out, checks, awarded = [], [], True
    pool = {"name": "", "sum": 0, "listed": 0}

    def flush():
        if pool["name"]:
            checks.append((pool["name"], pool["listed"], pool["sum"]))

    for r in table_records(path, sections_too=True):
        line = r["_line"]
        tc = re.sub(r"\s+", "", r.get("tc", ""))
        if not re.fullmatch(r"\d\d-\d+", tc):
            # one band can hold the end of one section and the start of the next: read it segment by segment
            for seg in re.split(r"(?=\b(?:King County|Metro|Non-Metro) (?:Pool|New Production) \()", line):
                if re.match(r"(King County|Metro|Non-Metro) (Pool|New Production) \(", seg):
                    flush()
                    pool = {"name": seg.split(" (")[0], "sum": 0, "listed": 0}
                m = re.search(r"Credit Allocated:\s*\$\s*(\d{1,3}(?:\s?,\s?\d{3})+|\d+)", seg)
                if m:
                    pool["listed"] = max(pool["listed"], num(m.group(1)))
                # the last label in the segment wins ("King County Pool Unranked (...)" -> not awarded)
                marks = [(mm.start(), 1, False) for mm in re.finditer(NOT_AWARDED, seg, re.I)] + \
                        [(mm.start(), 0, True) for mm in re.finditer(r"Pool\b|New Production|Preservation", seg)]
                if marks:
                    awarded = max(marks)[2]
            continue
        if not awarded:
            continue
        amt = num(r.get("amount"))
        pool["sum"] += amt
        out.append(row(r.get("name", ""), r.get("city", ""), year, "9%", "", num(r.get("li")) or "",
                       r.get("sponsor", ""), amt, tc, f"WSHFC {year} 9% housing tax credit allocation list", url))
    flush()
    return out, checks


def parse_bond_lines(path, year, label, url, cuts):
    """Unruled bond lists: one line per project, cut into columns by character x."""
    with pdfplumber.open(path) as pdf:
        pg = pdf.pages[0]
        lines = group_lines(pg.chars, 2.5)
    recs, stop = [], False
    for top, cs in lines:
        txt = chars_text(cs)
        if re.search(r"Awarded Subtotal|^Subtotal", txt):
            stop = True
        if stop:
            break
        cols = {}
        for i, (k, lo) in enumerate(cuts):
            hi = cuts[i + 1][1] if i + 1 < len(cuts) else 9999
            cols[k] = chars_text([c for c in cs if lo <= c["x0"] < hi])
        if "city" not in cols:  # city is glued to the taxable amount: "$7,230,000Des Moines"
            m = re.match(r"\$?\s*[\d,]*\s*(.*)$", cols["tx"])
            cols["city"] = m.group(1) if m else ""
        recs.append((top, cols, txt))
    out, cur = [], None
    rows_ = [i for i, (_, c, _) in enumerate(recs) if re.match(r"\$\s*[\d,]{5,}", c["te"])]
    for i in rows_:
        top, c, _ = recs[i]
        # wrapped city / county / name lines without amounts belong to the nearest project line
        extra = [recs[j] for j in range(len(recs)) if j not in rows_ and not recs[j][1]["te"]
                 and abs(recs[j][0] - top) < 12 and min(rows_, key=lambda k: abs(recs[k][0] - recs[j][0])) == i
                 and not re.search(r"Project|Request|Allocation List|Tax-Exempt", recs[j][2])]
        for k in ("name", "sponsor", "city", "county"):
            parts = sorted([(t, cc[k]) for t, cc, _ in extra if cc.get(k)] + [(top, c[k])])
            c[k] = " ".join(p for _, p in parts if p)
        out.append(row(c["name"], c["city"], year, "4% (bond)", num(c["units"]) or "", "", c["sponsor"], "", "",
                       label, url))
    return out


def parse_bond_grid(path, year, label, url):
    out = []
    stopped = False
    for r in table_records(path):
        title = r["_title"]
        y = year
        if year is None:  # King County file: only the "YYYY King County Allocation List" tables are awards
            m = re.search(r"(\d{4}) King County Allocation List", title)
            if not m:
                continue
            y = int(m.group(1))
        if re.search(NOT_AWARDED, r["_section"], re.I):
            continue
        name = r.get("name", "")
        if not name or re.search(r"subtotal|^total", name, re.I):
            if re.search(r"subtotal", r["_line"], re.I) and "Second Round" in label + title:
                stopped = True
            continue
        if stopped and year == 2021:
            continue
        if not (num(r.get("bond")) or r.get("units")):
            continue
        fn = re.sub(r"\.pdf$", "", os.path.basename(path))
        lab = label.format(y=y, f=re.match(r"\d{4}", fn).group(0) if re.match(r"\d{4}", fn) else "")
        out.append(row(name, r.get("city", ""), y, "4% (bond)", num(r.get("units")) or "", "", r.get("sponsor", ""),
                       "", "", lab, url))
    return out


def parse_bond_xlsx(path, year, url):
    ws = next(w for w in openpyxl.load_workbook(path, data_only=True).worksheets if "oint" in w.title)
    out, hdr = [], None
    for vals in ws.iter_rows(values_only=True):
        vals = [clean(str(v)) if v is not None else "" for v in vals]
        if "Project Name" in vals:
            hdr = {v: i for i, v in enumerate(vals) if v}
            continue
        if hdr is None:
            continue
        if any("Awarded Subtotal" in v for v in vals):
            break
        g = lambda k: vals[next(i for h, i in hdr.items() if h.startswith(k))]
        if not g("Project Name") or not num(g("Tax-Exempt")):
            continue
        out.append(row(g("Project Name"), g("City"), year, "4% (bond)", "", num(g("Total Low-Income Units")) or "",
                       g("Project Sponsor"), "", "", f"WSHFC {year} bonds with 4% housing tax credit allocation list",
                       url))
    return out


STOP = {"the", "apartment", "apartments", "apts", "apt", "phase", "ph", "and", "at", "of", "homes", "llc", "lllp",
        "rehabilitation", "rehab", "project", "new", "construction"}


def tokens(s):
    """Name tokens for matching: lower case, no parentheses, no "9%"/"4%" tags, roman numerals as digits."""
    s = re.sub(r"\(.*?\)", " ", (s or "").lower().replace("&", " and ").replace("'", ""))
    s = re.sub(r"\b\d%", " ", s)
    t = [{"i": "1", "ii": "2", "iii": "3", "iv": "4"}.get(w, w) for w in re.findall(r"[a-z0-9]+", s)]
    return [w for w in t if w not in STOP]


def same_name(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # every token of the shorter name is in the longer one, and digits (phase numbers) agree
    return set(short) <= set(long_) and (len(short) >= 2 or short == long_) and \
        {w for w in ta if w.isdigit()} == {w for w in tb if w.isdigit()}


def parse_inventory(path, url):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    out = []
    rows_ = list(ws.iter_rows(values_only=True))
    hdr = [clean(str(v or "")) for v in rows_[0]]
    assert hdr[:3] == ["Project OID", "Project Name", "City"], hdr
    if any(re.search(r"address|zip|street", h, re.I) for h in hdr):
        print("NOTE: inventory has an address column:", hdr)
    for v in rows_[1:]:
        oid = clean(str(v[0] or ""))
        m = re.match(r"(\d\d)-(\d+)([A-Z]?)", oid)
        if not m:
            continue
        yy, n, suf = int(m.group(1)), int(m.group(2)), m.group(3)
        credit = "4% (bond)" if suf == "A" else "9%" if (not suf and n < 100) else ""
        out.append(row(v[1], v[2], (1900 if yy >= 80 else 2000) + yy, credit, "", "", v[4] or "", "", oid,
                       "WSHFC 2025 tax credit compliance portfolio (Report Types by Property Name)", url))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--pdf-dir", default=None)
    a = ap.parse_args()
    pdf_dir = a.pdf_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "pdf", "wa")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    awards = []
    for y, url in NINE.items():
        p = os.path.join(pdf_dir, local_name(url))
        if not fetch(url, p):
            continue
        rows, checks = parse_nine(p, y, url)
        bad = [c for c in checks if c[1] != c[2]]
        print(f"{y} 9% list: {len(rows)} allocated rows; pool totals checked {len(checks) - len(bad)}/{len(checks)}"
              + "".join(f"\n    MISMATCH {c[0]}: list {c[1]:,} vs rows {c[2]:,}" for c in bad))
        awards += rows
    for y, label, url, cuts in BOND_LINES:
        p = os.path.join(pdf_dir, local_name(url))
        if fetch(url, p):
            rows = parse_bond_lines(p, y, label, url, cuts)
            print(f"{os.path.basename(p)}: {len(rows)} awarded rows")
            awards += rows
    for y, url in BOND_XLSX.items():
        p = os.path.join(pdf_dir, local_name(url))
        if fetch(url, p):
            rows = parse_bond_xlsx(p, y, url)
            print(f"{os.path.basename(p)}: {len(rows)} awarded rows")
            awards += rows
    for y, label, url in BOND_GRID:
        p = os.path.join(pdf_dir, local_name(url))
        if fetch(url, p):
            rows = parse_bond_grid(p, y, label, url)
            print(f"{os.path.basename(p)}: {len(rows)} awarded rows")
            awards += rows
    # inventory: TC numbers for award rows; properties not on an award list become their own rows
    inv_rows = []
    p = os.path.join(pdf_dir, local_name(INVENTORY))
    if fetch(INVENTORY, p):
        inv = parse_inventory(p, INVENTORY)
        by_tc = {r["STATE_ID"]: r for r in awards if r["STATE_ID"]}
        matched, taken, hits = 0, set(), {}
        for iv in inv:  # pass 1: same TC number
            base = re.match(r"\d\d-\d+", iv["STATE_ID"]).group(0)
            hit = by_tc.get(iv["STATE_ID"]) or (by_tc.get(base) if iv["CREDIT"] == "9%" else None)
            if hit:
                hits[id(iv)] = hit
                taken.add(id(hit))
        for iv in inv:
            hit = hits.get(id(iv))
            if not hit:
                # pass 2, name + city: bond rows (no TC# on the bond lists), OIDs of unknown credit, and 9% OIDs
                # issued after the listed award (credit returned and re-awarded, e.g. Colville Family Haven 22-23
                # -> 23-95); an earlier 9% OID with a similar name is a different award
                cands = [r for r in awards if id(r) not in taken
                         and (r["CREDIT"] == iv["CREDIT"] == "4% (bond)" and not r["STATE_ID"] or not iv["CREDIT"]
                              or r["CREDIT"] == iv["CREDIT"] == "9%" and int(iv["YR_ALLOC"]) >= int(r["YR_ALLOC"]))
                         and same_name(r["PROJECT"], iv["PROJECT"])
                         and abs(int(r["YR_ALLOC"]) - int(iv["YR_ALLOC"])) <= 3
                         and (not r["PROJ_CTY"] or iv["PROJ_CTY"].lower() in r["PROJ_CTY"].lower().split(", ")
                              or r["PROJ_CTY"] == iv["PROJ_CTY"] == "Multiple")]
                cands.sort(key=lambda r: abs(int(r["YR_ALLOC"]) - int(iv["YR_ALLOC"])))
                hit = cands[0] if cands else None
            if hit:
                matched += 1
                taken.add(id(hit))
                if not hit["STATE_ID"]:
                    hit["STATE_ID"] = iv["STATE_ID"]
                if not hit["PROJ_CTY"]:
                    hit["PROJ_CTY"] = iv["PROJ_CTY"]
                continue
            inv_rows.append(iv)
        # King County allocation tables give no city: take it from another WSHFC row with the same name
        for r in awards:
            if not r["PROJ_CTY"] and len(tokens(r["PROJECT"])) >= 2:
                cities = {o["PROJ_CTY"] for o in awards + inv_rows if o is not r and o["PROJ_CTY"]
                          and o["PROJ_CTY"] != "Multiple" and same_name(o["PROJECT"], r["PROJECT"])}
                if len(cities) == 1:
                    r["PROJ_CTY"] = cities.pop()
        print(f"inventory: {len(inv)} properties, {matched} matched to award rows, {len(inv_rows)} added")
    rows = awards + inv_rows
    out = os.path.join(a.out, "wa.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()

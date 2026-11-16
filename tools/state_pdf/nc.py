"""North Carolina Housing Finance Agency (NCHFA) LIHTC awards -> extracted/nc.csv.

Base source: NCHFA "Find Awarded Projects" web table (Drupal view, all years 1987-2026, ~1,679 rows, 20 per page,
?page=0..N). Columns: Project Name | City | County | Total Units | Type | Target population | Owner Name | Contact |
Bond Deal (Yes/No) | Year. Every page is saved under pdf/nc/web/ and parsed; Bond Deal=Yes -> CREDIT "4% (bond)",
No -> "9%". YR_ALLOC = the table's Year (see below for bond deals). No street address, ZIP or credit amount in the table (city only).
Rows that are exact duplicates in every column (2 data-entry doubles in 2002) are dropped.

Enrichment: the "Housing Credit Awards" PDFs for 2022-2026 (one wide table per section: 9% competitive awards, then
"Tax-Exempt Bond" 4% deals, plus "Forward Commitment of <next year> Housing Credits" rows that are 9%). Columns are cut
by word x-position (name < city < county < first money column). Each PDF row is matched to a web row in the same
county (see main(): strong name match first, then same unit count + same city for renamed projects) and its annual
Housing Credits amount goes into ALLOCAMT (2023 and 2024 bond sections list only bond volume, so no amount for those).
The web table dates bond deals 1-2 years before the award list that announces them ("Awarded in February 2026" on
the 2026 list = Year 2025 in the table), so a matched bond deal takes YR_ALLOC from the list (old Year in
SRC_LABEL); unmatched rows keep the table's Year. PDF rows with no web match are added as their own rows.

The web table is fetched with curl (its default user agent): NCHFA's server returns 403 to Python urllib's default
agent, and no browser user agent is sent.

Usage (from the repo root): python tools/state_pdf/nc.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import difflib
import glob
import html
import re
import subprocess
import sys
import time
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

WEB_URL = "https://www.nchfa.com/rental-housing-partners/rental-developers/find-awarded-projects"

PDFS = [
    (2022, "https://www.nchfa.com/sites/default/files/forms_resources/QAP22-AwardsList.pdf"),
    (2023, "https://www.nchfa.com/sites/default/files/forms_resources/2023%20Housing%20Credit%20Awards.pdf"),
    (2024, "https://www.nchfa.com/sites/default/files/forms_resources/2024HousingCreditAwards.pdf"),
    (2025, "https://www.nchfa.com/sites/default/files/forms_resources/2025-08/2025%20Awards%20List.pdf"),
    (2026, "https://www.nchfa.com/sites/default/files/forms_resources/2026-08/17-rf/2026%20Awards%20List.pdf"),
]


def curl(url, dest):
    """curl with its default user agent. Returns None on success, else an error string."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    r = subprocess.run(["curl", "-s", "-L", "-o", str(dest), "-w", "%{http_code}", url], capture_output=True, text=True)
    code = r.stdout.strip()
    if r.returncode != 0 or code != "200":
        if dest.exists():
            dest.unlink()
        return f"curl exit {r.returncode}, HTTP {code}"
    return None


# ---------------------------------------------------------------- web table
def fetch_web(wdir):
    wdir.mkdir(parents=True, exist_ok=True)
    first = wdir / "page_00.html"
    err = curl(WEB_URL + "?page=0", first)
    if err:
        return err
    h = first.read_text(encoding="utf-8")
    m = re.search(r'pager__item--last">\s*<a href="\?page=(\d+)"', h)
    last = int(m.group(1)) if m else 0
    for i in range(1, last + 1):
        dest = wdir / f"page_{i:02d}.html"
        if not dest.exists():
            e = curl(f"{WEB_URL}?page={i}", dest)
            if e:
                return f"page {i}: {e}"
            time.sleep(0.5)
    return None


def cell(t):
    t = t.replace("<br />", " ; ")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def parse_web(wdir):
    rows, total = [], None
    for f in sorted(glob.glob(str(wdir / "page_*.html"))):
        h = Path(f).read_text(encoding="utf-8")
        m = re.search(r"([\d,]+) Results", h)
        if m:
            total = int(m.group(1).replace(",", ""))
        tb = h[h.find("<tbody>"): h.find("</tbody>")]
        for tr in re.findall(r"<tr>(.*?)</tr>", tb, re.S):
            tds = [cell(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) != 10:
                continue
            rows.append(dict(zip(["name", "city", "county", "units", "type", "pop", "owner", "contact", "bond",
                                  "year"], tds)))
    return rows, total


# ---------------------------------------------------------------- award PDFs
NUM = re.compile(r"^\$?[\d,]+$")


def lines_of(page, tol=2.5):
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


def money(s):
    return s.replace("$", "").replace(",", "")


def parse_pdf(path):
    """Yield dicts: section ('9','bond','fwd'), name, city, county, credits (or ''), units, flag ('^'/'+'/'*')."""
    out = []
    pdf = pdfplumber.open(path)
    section, cuts = "9", None
    for page in pdf.pages:
        for ws in lines_of(page):
            s = txt(ws)
            if "Tax-Exempt Bond" in s or s.startswith("Tax Exempt Bond"):
                section = "bond"
            if s.startswith("Forward Commitment"):
                section = "fwd"
                continue
            pj = [w for w in ws if w["text"].startswith("Project")]
            if len(pj) >= 2 and "County" in s:
                # header line: Project Name | Project City | Project County ...  (2025's bond header has no
                # "Tax-Exempt Bond" title, only a "Bond Volume" column)
                if "Volume" in s:
                    section = "bond"
                cuts = (pj[1]["x0"] - 10, pj[2]["x0"] - 10) if len(pj) >= 3 else (pj[0]["x0"] - 10, pj[1]["x0"] - 10)
                continue
            if cuts is None or s.startswith("Total") or re.match(r"^[\d,$]+ [\d,]+$", s):
                continue
            nums = [i for i, w in enumerate(ws) if NUM.match(w["text"]) and w["x0"] > cuts[1]]
            if not nums:
                continue
            k = nums[0]
            name = txt([w for w in ws[:k] if w["x0"] < cuts[0]])
            city = txt([w for w in ws[:k] if cuts[0] <= w["x0"] < cuts[1]])
            county = txt([w for w in ws[:k] if w["x0"] >= cuts[1]])
            if not name or not county or county == "Total" or name[0] in "^+*":
                continue
            # units = the last plain number before the Type word (New / Rehab / Ad. / Family/Senior when Type wraps)
            ti = next((i for i, w in enumerate(ws) if i > k and not NUM.match(w["text"])), None)
            numtoks = [w["text"] for w in ws[k:ti]]
            units = numtoks[-1] if numtoks else ""
            amounts = numtoks[:-1]
            flag = ""
            m = re.search(r"([\^+*])$", name)
            if m:
                flag, name = m.group(1), name[:-1].strip()
            # 9% rows: Housing Credits first, then loan amounts. Bond rows: [Housing Credits,] Bond Volume -- the 2023
            # and 2024 bond sections have no credits column, so a single amount is bond volume.
            credits = ""
            if section in ("9", "fwd") and amounts:
                credits = money(amounts[0])
            elif section == "bond" and len(amounts) >= 2:
                credits = money(amounts[0])
            out.append({"section": section, "name": name, "city": city, "county": county, "credits": credits,
                        "units": units, "flag": flag})
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "and"))


GENERIC = re.compile(r"\b(apartments?|apts?|the|at|of|and|phase|senior|seniors|homes|villas?)\b", re.I)


def sim(a, b):
    """Name similarity on the distinctive words (generic words like 'Apartments' / 'Senior' / 'Phase' removed)."""
    a, b = norm(GENERIC.sub(" ", a)) or norm(a), norm(GENERIC.sub(" ", b)) or norm(b)
    if not a or not b:
        return 0.0
    if a.startswith(b) or b.startswith(a):
        return 0.95
    return difflib.SequenceMatcher(None, a, b).ratio()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "nc"
    pdir.mkdir(parents=True, exist_ok=True)
    skipped = []

    err = fetch_web(pdir / "web")
    if err:
        skipped.append((WEB_URL, err))
        print(f"SKIP {WEB_URL}: {err}", file=sys.stderr)
    web, total = parse_web(pdir / "web")
    seen, dedup, ndup = set(), [], 0
    for r in web:
        key = tuple(r.values())
        if key in seen:
            ndup += 1
            continue
        seen.add(key)
        dedup.append(r)
    web = dedup
    print(f"web table: {len(web) + ndup} rows parsed (site says {total}); {ndup} exact duplicates dropped")
    for r in web:
        r["allocamt"], r["pdf"] = "", None

    # Parse every PDF first, then match in two passes over all PDF rows so a strong name match is never stolen by a
    # weaker one: pass 1 needs name similarity >= 0.8 (same county); pass 2 takes a same-county row with the same unit
    # count and the same city (or name similarity >= 0.5) (projects renamed between the award list and the database, e.g. "Dillard Street A" ->
    # "Stride A", and the 2022 list's overprinted names). Year window: 9% rows need web Year = list year (forward
    # commitments: list year or the next year; YR_ALLOC stays the list year, as in the web table); bond rows allow web Year in [list year - 2, list year + 1] because
    # the web table dates bond deals 1-2 years before the award list that announces them.
    precs = []
    for yr, url in PDFS:
        dest = pdir / f"{yr}_awards.pdf"
        e = curl(url, dest)
        if e:
            skipped.append((url, e))
            print(f"SKIP {url}: {e}", file=sys.stderr)
            continue
        recs = parse_pdf(dest)
        cnt = {"9": 0, "bond": 0, "fwd": 0}
        for p in recs:
            cnt[p["section"]] += 1
            p["yr"], p["url"], p["pyr"], p["web"] = yr, url, yr, None
            precs.append(p)
        print(f"{dest.name}: {cnt['9']} 9% + {cnt['fwd']} forward-commitment 9% + {cnt['bond']} bond rows")

    def candidates(p):
        for w in web:
            if w["pdf"] is not None or not w["year"].isdigit():
                continue
            lo, hi = {"bond": (p["pyr"] - 2, p["pyr"] + 1), "fwd": (p["pyr"], p["pyr"] + 1),
                      "9": (p["pyr"], p["pyr"])}[p["section"]]
            if not (lo <= int(w["year"]) <= hi) or norm(w["county"]) != norm(p["county"]):
                continue
            yield w, sim(w["name"], p["name"])

    for pass_no in (1, 2):
        for p in precs:
            if p["web"] is not None:
                continue
            best, bscore = None, -1.0
            for w, s in candidates(p):
                same_u = w["units"] == p["units"]
                ok = s >= 0.8 if pass_no == 1 else (same_u and (norm(w["city"]) == norm(p["city"]) or s >= 0.5))
                if not ok:
                    continue
                score = s + (0.5 if same_u else 0) + (0.1 if w["year"] == str(p["pyr"]) else 0)
                if score > bscore:
                    best, bscore = w, score
            if best is not None:
                best["pdf"], best["allocamt"], p["web"] = p, p["credits"], best

    extra = []
    for p in precs:
        w = p["web"]
        if w is None:
            print(f"  {p['yr']}: no web match for PDF row {p['name']} / {p['city']} / {p['county']} "
                  f"({p['section']}, {p['units']} units) -> added from PDF", file=sys.stderr)
            extra.append((p["yr"], p["url"], p))
            continue
        if (w["bond"] == "Yes") != (p["section"] == "bond"):
            print(f"  NOTE {p['yr']}: '{p['name']}' is in the PDF {p['section']} section but web Bond Deal="
                  f"{w['bond']}", file=sys.stderr)
        if sim(w["name"], p["name"]) < 0.8:
            print(f"  NOTE {p['yr']}: matched PDF '{p['name']}' ({p['units']} u) -> web '{w['name']}' "
                  f"({w['units']} u, {w['year']})", file=sys.stderr)
    nm = sum(1 for p in precs if p["web"] is not None)
    print(f"award PDFs: {len(precs)} rows, {nm} matched to web rows, {len(extra)} added as PDF-only rows")

    rows = []
    for w in web:
        credit = "4% (bond)" if w["bond"] == "Yes" else ("9%" if w["bond"] == "No" else "")
        label = (f"NCHFA Find Awarded Projects database, {w['year']} awards "
                 f"(Bond Deal={w['bond']}; {w['type']}; {w['pop']})")
        year = w["year"]
        if w["pdf"]:
            p = w["pdf"]
            yr, url = p["yr"], p["url"]
            if str(p["pyr"]) != w["year"]:
                # the award list is the dated announcement; the web table's Year runs 1-2 years early for bond deals
                year = str(p["pyr"])
                label += f"; YR_ALLOC {year} from the award list (web table Year {w['year']})"
            if sim(w["name"], p["name"]) < 0.8:
                label += f"; listed as '{p['name']}' in the award list"
            if w["allocamt"]:
                label += f"; annual credit amount from NCHFA {yr} Housing Credit Awards list ({url})"
            else:
                label += f"; listed in NCHFA {yr} Housing Credit Awards list (bond volume only, no credit amount)"
        rows.append({"PROJECT": w["name"], "PROJ_CTY": w["city"], "YR_ALLOC": year, "CREDIT": credit,
                     "N_UNITS": "" if w["units"] in ("0", "") else w["units"], "COMPANY": w["owner"], "ALLOCAMT": w["allocamt"],
                     "SRC_LABEL": label, "SRC_URL": WEB_URL})
    for yr, url, p in extra:
        pyr = yr  # forward commitments keep the year they were awarded (as the web table does)
        sect = {"9": "9% award", "fwd": f"forward commitment of {yr + 1} 9% credits",
                "bond": "tax-exempt bond (4%) award"}[p["section"]]
        rows.append({"PROJECT": p["name"], "PROJ_CTY": p["city"], "YR_ALLOC": str(pyr),
                     "CREDIT": "4% (bond)" if p["section"] == "bond" else "9%", "N_UNITS": p["units"],
                     "ALLOCAMT": p["credits"], "SRC_URL": url,
                     "SRC_LABEL": f"NCHFA {yr} Housing Credit Awards list ({sect}; county {p['county']}; "
                                  f"not in the Find Awarded Projects table)"})
    rows = [{k: r.get(k, "") for k in COLS} for r in rows]
    rows.sort(key=lambda r: (r["YR_ALLOC"], r["CREDIT"], r["PROJECT"]))
    with open(out / "nc.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader()
        wr.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'nc.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

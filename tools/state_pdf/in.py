"""Indiana (IHCDA) Rental Housing Tax Credit award lists -> standard CSV.

Source page: https://www.in.gov/ihcda/developers/rental-housing-tax-credits-rhtc/applications-and-awards/
Each awarded-list PDF is a set of one-page "Development Summary" sheets (PROJECT NAME, SITE LOCATION street +
"City, IN ZIP", units by set-aside, credit recommended, APPLICANT NUMBER, ...). The per-round applicant xlsx files
(and the noncompetitive bond Form C lists) are joined on application # / normalized name only to fill fields a
summary sheet lacks (street, city, ZIP, units).

Rounds: A-C / A-G = competitive 9%; A-B / B-C bond rounds and the noncompetitive bond lists = 4% (bond), often with
the state AWHTC credit (ALLOCAMT is the federal 4% credit only).
YR_ALLOC: the round's program (credit reservation) year, e.g. 2024A-C -> 2024 (IHCDA awards it in Nov of the prior
year); rows carrying an explicit "Award date" (noncompetitive bond lists, waitlist awards) use that date's year, so
the "2027 Noncompetitive" list awarded Jun/Aug 2026 -> 2026.
IHCDA posts no awarded list for the 2020-2022 bond rounds or the 2026 noncompetitive round (applicant lists only), so
those years have no 4% rows here.

Usage (repo root): python tools/state_pdf/in.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import subprocess
import urllib.request

import openpyxl
import pdfplumber

BASE = "https://www.in.gov/ihcda/files/"
PAGE = "https://www.in.gov/ihcda/developers/rental-housing-tax-credits-rhtc/applications-and-awards/"
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

# (file, round label, program year, credit, label)
AWARDS = [
    ("2020A-C-Round-Awarded-Applicants.pdf", "2020A-C", 2020, "9%", "IHCDA 2020A-C 9% RHTC awarded list"),
    ("2021A-C-Awarded-List.pdf", "2021A-C", 2021, "9%", "IHCDA 2021A-C 9% RHTC awarded list"),
    ("2022AC-All-Approved-Development-Summary-Sheet.pdf", "2022A-C", 2022, "9%", "IHCDA 2022A-C 9% RHTC awarded list"),
    ("2023A-C-Awarded-List_Feb-updated.pdf", "2023A-C", 2023, "9%", "IHCDA 2023A-C 9% RHTC awarded list (Feb 2023 update)"),
    ("2023A-B-Awarded-Listv2.pdf", "2023A-B", 2023, "4% (bond)", "IHCDA 2023A-B bond & state AWHTC awarded list"),
    ("2023A-B-Awarded-List-Feb2024.pdf", "2023A-B", 2023, "4% (bond)", "IHCDA 2023A-B bond & state AWHTC awarded list (Feb 2024)"),
    ("2023A-B-Waitlisted-Awarded-List.pdf", "2023A-B", 2023, "4% (bond)", "IHCDA 2023A-B bond & state AWHTC waitlisted awarded list"),
    ("2024-A-C-Awarded-List.pdf", "2024A-C", 2024, "9%", "IHCDA 2024A-C 9% RHTC awarded list"),
    ("2024A-G-Awarded-List.pdf", "2024A-G", 2024, "9%", "IHCDA 2024A-G general set-aside 9% RHTC awarded list"),
    ("2025A-C-Awarded-List.pdf", "2025A-C", 2025, "9%", "IHCDA 2025A-C 9% RHTC awarded list"),
    ("2025A-G-Awarded-List.pdf", "2025A-G", 2025, "9%", "IHCDA 2025A-G general set-aside 9% RHTC awarded list"),
    ("2025B-C-Awarded-List.pdf", "2025B-C", 2025, "4% (bond)", "IHCDA 2025B-C bond & state AWHTC awarded list"),
    ("2025B-C-Waitlist-Awarded-List.pdf", "2025B-C", 2025, "4% (bond)", "IHCDA 2025B-C bond & state AWHTC waitlist awarded list"),
    ("2025-Noncompetitive-Awarded-List-July-2025-Update.pdf", "2025NC", 2025, "4% (bond)", "IHCDA 2025 noncompetitive 4% bond awarded list (July 2025)"),
    ("2026A-C-Awarded-List.pdf", "2026A-C", 2026, "9%", "IHCDA 2026A-C 9% RHTC awarded list"),
    ("2026B-C-Awarded-List.pdf", "2026B-C", 2026, "4% (bond)", "IHCDA 2026B-C bond & state AWHTC awarded list"),
    ("2027-Noncompetitive-Awarded-Projects-9-1-2026.pdf", "2027NC", 2026, "4% (bond)", "IHCDA 2027 noncompetitive 4% bond awarded list (9/1/2026)"),
]
# join sources (applicant lists / Form C lists): street, city, county, ZIP, units by app # or name
JOIN = ["2020A-C-Applicant-List.xlsx", "2021A-C-Applicant-List_Revised-10-28-2020.xlsx",
        "2022A-C-Applicant-Lis-8-10-2021t.xlsx", "2023A-C-Applicant-List.xlsx",
        "2024A-C-Applicant-List_updated-8-11-23v2.xlsx", "2025AC-Round-tax-credits.xlsx",
        "2026A-C-Round-Applicant-List-rev.-1-8-2026.xlsx",
        "2023-Bond-and-State-Credit-Applicant-List_updated-7-17-23v2.xlsx", "2025B-C-Applicant-List-bonds.xlsx",
        "2026B-C-Applicant-List-8-11-25.xlsx", "2025-Noncompetitive-Bond-Applicant-List.xlsx",
        "2027-Noncompetitive-Bond-Applicant-List-9-1-26.xlsx", "2025-Noncompetitive-Form-C-Listv4.xlsx",
        "2027-Noncompetitive-Form-C-List-6-29-2026.xlsx"]


def download(fn, d):
    path = os.path.join(d, fn)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    try:
        with urllib.request.urlopen(BASE + fn, timeout=60) as r:
            data = r.read()
    except Exception as e:  # urllib's default UA is sometimes refused; fall back to curl's default UA
        print(f"  urllib failed for {fn}: {e}; trying curl")
        res = subprocess.run(["curl", "-sfL", "-o", path, BASE + fn])
        if res.returncode != 0 or not os.path.exists(path):
            print(f"  SKIP {fn}: download failed")
            return None
        return path
    with open(path, "wb") as f:
        f.write(data)
    return path


def norm(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"\b(apartments?|apts|homes|the|phase|lp|llc)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def money(s):
    m = re.search(r"\$?\s*([\d,]*\.?\d*)", s or "")
    v = (m.group(1) if m else "").replace(",", "")
    return str(int(round(float(v)))) if v and v != "." else ""


def field(block, label):
    m = re.search(r"^" + label + r"\s*:?\s*(.*)$", block, re.M | re.I)
    return m.group(1).strip() if m else ""


def app_id(block):
    """IHCDA application # (e.g. 2024A-C-004); some sheets put it on the BIN NUMBER line or drop a hyphen."""
    i = block.find("APPLICANT NUMBER")
    m = re.search(r"\b(\d{4})\s*([A-Z])\s*-\s*([A-Z])\s*-?\s*(\d{3})\b", block[i:] if i >= 0 else block)
    return f"{m.group(1)}{m.group(2)}-{m.group(3)}-{m.group(4)}" if m else ""


def parse_pdf(path):
    with pdfplumber.open(path) as pdf:
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    text = text.replace(chr(0xFFFD), "-")
    blocks = re.split(r"^(?=PROJECT NAME\s*:)", text, flags=re.M)[1:]
    out = []
    for b in blocks:
        name = field(b, r"PROJECT NAME")
        loc = re.search(r"^SITE LOCATION\s*:?\s*(.*?)^PROJECT TYPE", b, re.M | re.S)
        lines = [x.strip() for x in (loc.group(1) if loc else "").splitlines() if x.strip()]
        street, city, zp = "", "", ""
        cityrx = r"(.*?),?\s*(?:IN|Indiana)\.?,?\s*I?(\d{5})?(?:[/-]\d{4,5})*\s*$"  # "City, IN 46202", "City, IN,47904"
        ci = next((i for i in range(len(lines) - 1, -1, -1) if re.match(cityrx, lines[i])), None)
        if ci is not None:
            m = re.match(cityrx, lines[ci])
            city, zp = m.group(1).strip(" ,"), m.group(2) or ""
            street = " ".join(lines[:ci])
            if re.search(r"\d", city):  # "and 164 E. 25th Street Indianapolis, IN 46205": street tail + city
                head, _, city = city.rpartition(" ")
                street = (street + " " + head).strip()
        else:
            street = " ".join(lines)
        if re.search(r"scat+er+ed", street, re.I):
            # scattered sites: use the first address listed on the exhibit page(s) that follow the sheet, if text
            ex = re.search(r"^\W*(\d+[\w/-]*(?:[ ,&]+(?:and )?\d+[\w/-]*)*\s+(?:[NSEW]\.?\s+)?[A-Z0-9][\w.' ]*?"
                           r"\b(?:Street|St|Avenue|Ave|Drive|Dr|Road|Rd|Lane|Ln|Court|Ct|Place|Pl|Boulevard|Blvd|Way|"
                           r"Parkway|Pkwy|Trail|Circle)\b\.?)", b.split("{0", 1)[1] if "{0" in b else "", re.M)
            street = ex.group(1).strip() if ex else ""
        if re.search(r"scat+er+ed", city, re.I):
            city = ""
        tot = re.search(r"Total units\s*:?\s*(\d+)", b, re.I)
        mkt = re.search(r"Market Rate\s*:?\s*(\d+)", b, re.I)
        cred = ""
        for lab in (r"4% CREDITS? RECOMMENDED", r"CREDITS? RECOMMENDED"):
            v = field(b, lab)
            if v:
                cred = money(v)
                break
        award = re.search(r"Award date\s*:?\s*([A-Za-z]+ \d{1,2}, (\d{4}))", b, re.I)
        n = int(tot.group(1)) if tot else None
        out.append({"PROJECT": re.sub(r"\s+", " ", name), "PROJ_ADD": street, "PROJ_CTY": city, "PROJ_ZIP": zp,
                    "N_UNITS": n, "LI_UNITS": (n - int(mkt.group(1))) if (n is not None and mkt) else None,
                    "COMPANY": field(b, r"APPLICANT(?! NUMBER)") or field(b, r"DEVELOPER"), "ALLOCAMT": cred,
                    "STATE_ID": app_id(b),
                    "_award_year": int(award.group(2)) if award else None})
    return out


def txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def read_join(path):
    """Rows of an applicant / Form C list as dicts with id, name, street, city, zip, units."""
    rows = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        data = list(ws.iter_rows(values_only=True))
        hi = next((i for i, r in enumerate(data[:15]) if any(txt(c).lower() == "development name" for c in r)), None)
        if hi is None:
            continue
        h = [txt(c).lower() for c in data[hi]]

        def col(*pats):
            return next((j for j, c in enumerate(h) if any(re.fullmatch(p, c) for p in pats)), None)
        ix = {"id": col(r"applica(nt|tion) #"), "name": col(r"development name"), "street": col(r"street address"),
              "city": col(r"(development )?city"), "zip": col(r"zip"), "tc": col(r"tax credit units|total program units"),
              "tot": col(r"total units|number of units"), "mkt": col(r"market units|total market rate")}
        for r in data[hi + 1:]:
            g = {k: (txt(r[j]) if j is not None and j < len(r) else "") for k, j in ix.items()}
            if g["name"]:
                rows.append(g)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--pdf-dir", default=None)
    a = ap.parse_args()
    pdf_dir = a.pdf_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "pdf", "in")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)

    by_id, by_name = {}, {}
    for fn in JOIN:
        p = download(fn, pdf_dir)
        if not p:
            continue
        for g in read_join(p):
            if re.match(r"\d{4}[A-Z]-[A-Z]-\d+", g["id"].replace(" ", "")):
                by_id.setdefault(g["id"].replace(" ", ""), g)
            by_name.setdefault(norm(g["name"]), []).append(g)

    rows, seen = [], set()
    for fn, rnd, year, credit, label in AWARDS:
        p = download(fn, pdf_dir)
        if not p:
            continue
        recs = parse_pdf(p)
        kept = 0
        for r in recs:
            key = r["STATE_ID"] or (rnd + "|" + norm(r["PROJECT"]))
            if key in seen:  # same award repeated in an updated / waitlist list of the same round
                continue
            seen.add(key)
            j = by_id.get(r["STATE_ID"])
            if not j:
                cands = [g for g in by_name.get(norm(r["PROJECT"]), [])
                         if not r["PROJ_CTY"] or not g["city"] or g["city"].lower() == r["PROJ_CTY"].lower()]
                j = cands[-1] if cands else None
            if j:
                r["PROJ_ADD"] = r["PROJ_ADD"] or j["street"]
                r["PROJ_CTY"] = r["PROJ_CTY"] or j["city"]
                r["PROJ_ZIP"] = r["PROJ_ZIP"] or (re.search(r"\d{5}", j["zip"]) or [""])[0]
                if r["N_UNITS"] is None and j["tot"].isdigit():
                    r["N_UNITS"] = int(j["tot"])
                if r["LI_UNITS"] is None and j["tc"].isdigit():
                    r["LI_UNITS"] = int(j["tc"])
            for k in ("PROJ_ADD", "PROJ_CTY"):  # "Scattered sites - see Exhibit A" is not an address / city
                if re.search(r"scat+er+ed", r[k], re.I):
                    r[k] = ""
            if r["ALLOCAMT"] == "0":  # sheet shows $0 recommended (listed as awarded, amount not stated)
                r["ALLOCAMT"] = ""
            r["YR_ALLOC"] = r.pop("_award_year") or year
            r.update(CREDIT=credit, SRC_LABEL=label, SRC_URL=BASE + fn)
            rows.append(r)
            kept += 1
        print(f"{fn}: {len(recs)} summary sheets, {kept} rows kept")

    out = os.path.join(a.out, "in.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLS})
    print(f"wrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()

"""Delaware State Housing Authority (DSHA) LIHTC preliminary awards -> extracted/de.csv.

Sources: DSHA "LIHTC Applications / Preliminary Project Award Rankings" PDFs, 2020-2026, plus the special 4% /
SLFRF round of 11/16/2023. Each lists every applicant. The 9% applicants are split into a "PRELIMINARY PROJECT
AWARD RANKINGS" (2025: "PRELIMINARY ALLOCATION") table and a "PRELIMINARY PROJECT RANKINGS - CREDITS NOT
AVAILABLE" table; only the first is kept (2020's first page has no award heading but its second page is the
credits-not-available table). 4% applicants: those that "Did not meet threshold" are dropped; the rest are kept as
CREDIT "4% (bond)" because DSHA's stated policy is that threshold-compliant 4% applicants receive an allocation
subject to bond volume (2021, 2022, 2024 and 2025 4% tables carry no explicit award heading -- see SRC_LABEL).

The cells (site name/address, applicant contact block, type, units, request, score) wrap and interleave, and there
are only 3-8 deals a year, so the award rows are a hand-checked table (AWARDS below) transcribed from the PDFs.
The script downloads every PDF and verifies, for each row, that the project name, street, ZIP, unit count and
amount occur in that PDF's text; any mismatch is reported.

Fields: YR_ALLOC = the list's year (preliminary awards; DSHA posts no final list). ALLOCAMT = the LIHTC request of
a preliminary 9% awardee (annual credits); for 4% rows only the 2026 list gives a request amount. "51 LIHTC / 23
Market" units -> LI_UNITS 51, N_UNITS 74; a single "# of LIHTC units" figure fills both (no market units listed).
2025: DSHA posts the same chart twice (2025/09/2025-Preliminary-Award-Chart-FINAL.pdf and
2026/06/2025-LIHTC-Preliminary-Awards.pdf, identical text); the one linked from the LIHTC page is used.

Usage (from the repo root): python tools/state_pdf/de.py --out ../hud_src/lihtc/states/extracted
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

U = "https://www.destatehousing.com/wp-content/uploads/"
FILES = {
    "2020": U + "2024/02/2020-dsha_taxcreditpreliminaryranking.pdf",
    "2021": U + "2024/02/2021-dsha-taxcreditpreliminaryranking.pdf",
    "2022": U + "2024/02/2022-dsha-taxcreditpreliminaryranking.pdf",
    "2023": U + "2024/02/2023-dsha-taxcreditpreliminaryranking.pdf",
    "2023s4": U + "2024/02/2023-4percent-special-taxcreditpreliminaryranking.pdf",
    "2024": U + "2024/07/2024-LIHTC-Preliminary-Award-Chart-FINAL.pdf",
    "2025": U + "2026/06/2025-LIHTC-Preliminary-Awards.pdf",
    "2026": U + "2026/07/2026-Preliminary-Award-Chart-FINAL.pdf",
}
LABEL = {
    "2020": "DSHA 2020 LIHTC applications as of 08/05/2020 (9% applicants, first page; the next page is "
            "'credits not available')",
    "2021": "DSHA 2021 LIHTC applications as of 07/08/2021",
    "2022": "DSHA 2022 LIHTC applications as of 07/05/2022",
    "2023": "DSHA 2023 LIHTC applications as of 07/06/2023",
    "2023s4": "DSHA special 4% LIHTC / SLFRF applications as of 11/16/2023 (preliminary project award rankings)",
    "2024": "DSHA 2024 LIHTC applications as of 7/10/2024",
    "2025": "DSHA 2025 LIHTC application ranking",
    "2026": "DSHA 2026 LIHTC application ranking",
}

# (file key, credit, project, street, city, zip, li_units, total_units, amount, applicant, note)
AWARDS = [
    ("2020", "9", "Willows at Millsboro", "Union Street and Old Landing Road", "Millsboro", "19966", 42, 60,
     1000000, "MBID of Delaware, LLC", ""),
    ("2020", "9", "Riverside Redevelopment-Phase II", "2910 Rosemont Avenue", "Wilmington", "19802", 50, 67,
     1000000, "Pennrose, LLC", ""),
    ("2020", "9", "Diamond Court II", "32 Diamond Court", "Harrington", "19952", 32, 32, 608080,
     "Greenstreet Housing, LLC", ""),
    ("2020", "9", "The Flats, Phase IV", "600 Ferris Street and Bayard Ave", "Wilmington", "19805", 52, 52,
     1000000, "HDC MidAtlantic/Todmorden Foundation", ""),
    ("2021", "9", "Diamond Court I", "32 Diamond Court", "Harrington", "19952", 34, 34, 767632,
     "Greenstreet Housing, LLC", ""),
    ("2021", "9", "Betts Commons", "29509 Millsboro Hwy", "Millsboro", "19966", 39, 46, 1000000,
     "MBID of Delaware, LLC", ""),
    ("2021", "9", "Maxwell Fields (aka West Street Manor & West Street Manor Annex)", "700 Mason Avenue",
     "Harrington", "19952", 60, 60, 949061, "MHDC", ""),
    ("2021", "4", "Frazier Apartments", "200 Goldsborough Way", "Smyrna", "19977", 54, 54, None,
     "Severn Development Company, LLC", "4% applicant, preliminary score 110"),
    ("2022", "9", "Villa Maria", "55 Race Street", "Wilmington", "19812", 51, 74, 1000000,
     "Ministry of Caring, Inc./NCALL Research, Inc.", ""),
    ("2022", "9", "Dunbarton Station II Apartments", "900 - 1108 Dunbarton Apts.", "Georgetown", "19947", 24, 24,
     808468, "Severn Development Company", ""),
    ("2022", "9", "The Reese Apartments", "8093 S DuPont Hwy", "Felton", "19943", 36, 48, 999013,
     "Carson Development LLC / Reese Associates, LLC", ""),
    ("2022", "9", "The Flats, Phase V", "401 Bayard Avenue", "Wilmington", "19801", 53, 53, 1000000,
     "HDC / Todmorden Foundation", ""),
    ("2022", "4", "Owens/Queens Manor", "426 New St. / 411 S. Queen St.", "Dover", "19901", 110, 110, None,
     "LNWA / Dover Housing Authority", "4% applicant, preliminary score 143"),
    ("2022", "4", "Carolyn Center", "25 Kiwanis Drive", "Wilmington", "19802", 60, 60, None,
     "Delaware Center for Homeless Veterans / Delaware Valley Development Company",
     "4% applicant, preliminary score 103"),
    ("2023", "9", "Chapel Branch Apartments", "Rt. 24 and Dorman Road", "Lewes", "19958", 35, 42, 1000000,
     "Commonwealth Development Corporation of America", ""),
    ("2023", "9", "George Read Village", "313 E. Main Street", "Newark", "19711", 72, 72, 1000000,
     "MBID of Delaware, LLC", ""),
    ("2023", "9", "Gateway East", "20520 Sand Hill Road", "Georgetown", "19947", 59, 59, 1000000,
     "Delaware Valley Development Group, LLC / CHEER, Inc.", ""),
    ("2023s4", "4", "The MEWS at 6060", "6042 & 6060 Limestone Road", "Hockessin", "19707", 80, 80, None,
     "Delaware Valley Development Group, LLC", "preliminary score 157"),
    ("2023s4", "4", "Imani Village, Phase III (fka Riverside, Phase III)", "1500 E 27th Street", "Wilmington",
     "19802", 124, 184, None, "Pennrose, LLC", "preliminary score 152"),
    ("2023s4", "4", "Mispillion Station II Apartments", "600-900 Mispillion Apartments", "Milford", "19963", 48, 48,
     None, "Severn Development Company, LLC & Searfoss Development, LLC", "preliminary score 126"),
    ("2023s4", "4", "Compton Apartments", "650 North Walnut Street", "Wilmington", "19801", 55, 55, None,
     "Leon N. Weiner & Associates, Inc.", "preliminary score 100"),
    ("2024", "9", "Elizabeth Cornish Landing", "10 Elizabeth Cornish Landing", "Bridgeville", "19933", 62, 62,
     1000000, "Homes for America, Inc.", ""),
    ("2024", "9", "Imani Village, Phase V", "2501 Rosemont Avenue", "Wilmington", "19802", 48, 72, 1000000,
     "Pennrose LLC", ""),
    ("2024", "9", "Georgetown Apartments II", "700 Ingramtown Road", "Georgetown", "19947", 51, 62, 1000000,
     "Leon N. Weiner & Associates, Inc.", ""),
    ("2024", "9", "Park Royal Apartments", "501 Palmer Street", "Milton", "19968", 32, 32, 688447,
     "Milford Housing Development Corporation", "forward reservation of 2025 credits"),
    ("2024", "4", "Imani Village, Phase IV", "26th & Bowers Street", "Wilmington", "", 57, 84, None,
     "Pennrose LLC", "4% application, preliminary score 137"),
    ("2024", "4", "Church Street Station I", "201 Allen Way", "Milford", "19960", 80, 80, None,
     "Severn Development Company, LLC / Searfoss Development, LLC", "4% application, preliminary score 102"),
    ("2025", "9", "Willows at Northstar", "Route 9 and Old Vine Blvd.", "Lewes", "19958", 46, 46, 1000000,
     "MBID of Delaware, LLC", ""),
    ("2025", "9", "Georgetown Apartments I", "200 Ingramtown Road", "Georgetown", "19947", 76, 76, 1000000,
     "Leon N. Weiner & Associates, Inc.", ""),
    ("2025", "9", "Village of Francis and Clare", "905-909 Jefferson Street", "Wilmington", "19801", 51, 59,
     1000000, "Ministry of Caring, Inc", ""),
    ("2025", "4", "Mispillion Station III Apartments", "1000-1400 Mispillion Apartments", "Milford", "19963", 40, 40,
     None, "Severn Development Company, LLC / Searfoss Development, LLC", "4% application, preliminary score 102"),
    ("2026", "9", "Willows at Northstar, Phase II", "Route 9 and Old Vine Blvd.", "Lewes", "19958", 47, 47, 1000000,
     "MRK Partners/Ingerman", ""),
    ("2026", "9", "Mispillion Station I", "100-500 Mispillion Apartments", "Milford", "19963", 40, 40, 1000000,
     "Severn Development Company, LLC / Searfoss Development, LLC", ""),
    ("2026", "4", "Bethel Villa Apartments", "506 E. 5th Street", "Wilmington", "19801", 150, 150, 1770889,
     "American Community Developers, Inc.", "4% application, preliminary score 131; amount = 2026 LIHTC request"),
    ("2026", "4", "The Vistas at Saint Francis", "1600 West 8th Street", "Wilmington", "19805", 57, 57, 1126510,
     "Delaware Valley Development Co. & Cornerstone West CDC",
     "4% application, preliminary score 110; amount = 2026 LIHTC request"),
]

# applicants seen in each PDF that are NOT kept (for the row-count check): credits not available / failed threshold
NOT_AWARDED = {
    "2020": ["Maxwell Fields", "Owens Manor Ridge", "Villa Maria"],
    "2021": ["Mispillion Station II", "Villa Maria", "West Court", "Christiana Village"],
    "2022": ["Chapel Branch Apartments", "Jamestowne Center"],
    "2023": ["The MEWS at 6060", "Imani Village, Phase III"],
    "2023s4": [],
    "2024": ["Jamestowne Center", "Willows at Northstar"],
    "2025": ["120 S. Governors", "Chapel Branch Apts., Phase II", "Franklin Terrace", "Imani Village, Phase VI",
             "Laurel Glen", "Cheltenham Village", "Clayton Court", "Mifflin Meadows"],
    "2026": ["Smyrna II", "Imani Village, Phase VII"],
}


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


def flat(s):
    s = s.replace("–", "-").replace("�", "-")
    return re.sub(r"[^a-z0-9$]+", " ", s.lower()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "de"
    pdir.mkdir(parents=True, exist_ok=True)
    texts, skipped = {}, []
    for k, url in FILES.items():
        dest = pdir / url.rsplit("/", 1)[1]
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        texts[k] = flat(" ".join((p.extract_text() or "") for p in pdfplumber.open(dest).pages))

    rows, problems = [], 0
    for k, cr, name, street, city, zipc, li, tot, amt, app, note in AWARDS:
        if k not in texts:
            continue
        t = texts[k]
        checks = {"name": name.split(" (")[0], "street": street, "city": city, "zip": zipc,
                  "units": str(li), "amount": f"{amt:,}" if amt else ""}
        for what, val in checks.items():
            if val and flat(val) not in t:
                if what in ("name", "street") and all(f" {wd} " in f" {t} " for wd in flat(val).split()):
                    continue  # cell wraps onto two lines with other columns' text in between; every word is there
                problems += 1
                print(f"  CHECK {k} {name}: {what} '{val}' not found in the PDF text", file=sys.stderr)
        label = LABEL[k] + (" - 9% preliminary project award rankings" if cr == "9" and k not in ("2020",) else "")
        if cr == "4" and k != "2023s4":
            label += " - 4% applicants; threshold-compliant (DSHA allocates 4% credits to threshold-compliant " \
                     "applicants subject to bond volume; no explicit award heading)" \
                if k in ("2021", "2022", "2024", "2025") else " - 4% preliminary project award rankings"
        if note:
            label += f"; {note}"
        if cr == "9":
            label += "; ALLOCAMT = LIHTC request of a preliminary awardee"
        rows.append({"PROJECT": name, "PROJ_ADD": street, "PROJ_CTY": city, "PROJ_ZIP": zipc,
                     "YR_ALLOC": k[:4], "CREDIT": "9%" if cr == "9" else "4% (bond)", "N_UNITS": str(tot),
                     "LI_UNITS": str(li), "COMPANY": app, "ALLOCAMT": str(amt) if amt else "",
                     "SRC_LABEL": label, "SRC_URL": FILES[k]})
    for k, names in NOT_AWARDED.items():
        if k not in texts:
            continue
        for n in names:
            if flat(n) not in texts[k]:
                problems += 1
                print(f"  CHECK {k}: expected non-awarded applicant '{n}' not found", file=sys.stderr)
        kept = sum(1 for r in AWARDS if r[0] == k)
        print(f"{FILES[k].rsplit('/', 1)[1]}: {kept} kept ({sum(1 for r in AWARDS if r[0] == k and r[1] == '9')} "
              f"9%, {sum(1 for r in AWARDS if r[0] == k and r[1] == '4')} 4%), {len(names)} not awarded")
    with open(out / "de.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'de.csv'}; {problems} text-check problems")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

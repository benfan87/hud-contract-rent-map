"""Wisconsin (WHEDA) LIHTC award lists -> standard CSV (see README.md in this folder).

Sources (all public; downloaded with curl, default User-Agent):
  - 2020 federal 9% and federal 4% + state award lists (xlsx)
  - 2021-2024 federal 9% and state/federal 4% award lists (one-page wide PDFs)
  - 2025-2026 9% and 4% award lists (HTML pages; the "Ineligible"/"Withdrawn" tables are skipped)
  - WHEDA "Monitored HTC Projects" HTML inventory (street address, ZIP, units, placed-in-service date).
    Used to fill PROJ_ADD / PROJ_ZIP on award rows (match on normalized name + city), and also emitted as its
    own rows with YR_ALLOC = placed-in-service year and CREDIT blank.

Only rows with status "Award" are kept (on-hold / ineligible / withdrawn applications and subtotal rows dropped).
CREDIT: 9% lists -> "9%"; 4%/state lists -> "4% (bond)" when a federal 4% credit was awarded, blank when the award
is Wisconsin state credit only. ALLOCAMT is the federal annual credit award (blank for state-only awards).

Usage: python tools/state_pdf/wi.py --out ../hud_src/lihtc/states/extracted   (run from the repo root)
"""
import argparse
import csv
import html
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

G = "https://www.wheda.com/globalassets/documents/tax-credits/htc/"
H = "https://www.wheda.com/developers-and-property-managers/tax-credits/htc/allocating/"
INVENTORY_URL = "https://www.wheda.com/developers-and-property-managers/tax-credits/monitored-htc-projects"

# PDF column layouts: (field, left x cut).  A character belongs to the last column whose cut is <= its x-center.
# Cuts were set from the header words and the gaps between data columns of each file.
L21_9 = [("id", 0), ("name", 25), ("status", 275), ("city", 322), ("county", 400), ("units", 460), ("li", 498),
         ("hh", 529), ("fed_req", 600), ("fed", 660), ("constr", 713), ("company", 800), ("contact", 1025),
         ("phone", 1125)]
L21_4 = [("id", 0), ("name", 22), ("status", 248), ("city", 286), ("county", 355), ("units", 430), ("li", 466),
         ("hh", 492), ("st_req", 550), ("st", 608), ("fed_req", 660), ("fed", 712), ("constr", 759),
         ("company", 830), ("contact", 1040), ("phone", 1128)]
L22_9 = [("id", 0), ("name", 29), ("status", 186), ("city", 230), ("county", 293), ("units", 340), ("li", 395),
         ("hh", 435), ("fed_req", 480), ("fed", 545), ("constr", 609), ("company", 677), ("contact", 816),
         ("phone", 890)]
L22_4 = [("id", 0), ("name", 26), ("status", 176), ("city", 214), ("county", 262), ("units", 300), ("li", 320),
         ("hh", 341), ("fed_req", 388), ("fed", 435), ("st_req", 476), ("st", 515), ("st_post", 558),
         ("constr", 598), ("company", 673), ("contact", 855), ("phone", 918)]
L23_9 = [("id", 0), ("name", 40.5), ("status", 153), ("city", 189), ("county", 231), ("units", 285), ("li", 315),
         ("hh", 334.5), ("fed", 365), ("constr", 404), ("company", 495), ("contact", 664), ("phone", 728)]
L23_4 = [("id", 0), ("name", 25.5), ("status", 138), ("city", 175), ("county", 233), ("units", 285), ("li", 310),
         ("hh", 324.0), ("fed", 360), ("st", 398), ("constr", 430), ("company", 506), ("contact", 667),
         ("phone", 713)]
L24_9 = [("id", 0), ("name", 75), ("status", 193), ("city", 232), ("county", 267), ("units", 325), ("li", 350),
         ("hh", 365.5), ("fed", 393), ("constr", 432), ("company", 519), ("contact", 682), ("rest", 736)]
L24_4 = [("id", 0), ("name", 68), ("status", 165), ("city", 186), ("county", 212), ("units", 248), ("li", 272),
         ("hh", 285.5), ("fed", 306), ("st", 335), ("constr", 357), ("company", 420), ("contact", 540),
         ("rest", 574)]

# (year, credit kind '9' or '4', url, local filename, format, list title, pdf layout)
SOURCES = [
    (2020, "9", G + "2020/2020-federal-9-award-list-12.28.2020.xlsx", None, "xlsx", "2020 Federal 9% HTC award list", None),
    (2020, "4", G + "2020/2020-fed-4--state-4-htc-awards-list-1.xlsx", None, "xlsx", "2020 Federal 4% & State HTC award list", None),
    (2021, "9", "https://wheda.com/globalassets/documents/tax-credits/htc/2021/award-list/2021-fed-9-htc-award-list.pdf", None, "pdf", "2021 Federal 9% HTC award list", L21_9),
    (2021, "4", "https://wheda.com/globalassets/documents/tax-credits/htc/2021/award-list/2021-state-4-htc-award-list.pdf", None, "pdf", "2021 Federal 4% & State HTC award list", L21_4),
    (2022, "9", G + "2022/2022-award-list---9-htc.pdf", None, "pdf", "2022 Federal 9% HTC award list", L22_9),
    (2022, "4", G + "2022/2022-state-htc-award-list.pdf", None, "pdf", "2022 State 4% HTC award list", L22_4),
    (2023, "9", G + "2023/2023-award-list---9-htc.pdf", None, "pdf", "2023 Federal 9% HTC award list", L23_9),
    (2023, "4", G + "2023/2023-award-list-state-htc.pdf", None, "pdf", "2023 State/Federal 4% HTC award list", L23_4),
    (2024, "9", G + "2024/2024-award-list-9-percent-htc.pdf", None, "pdf", "2024 Federal 9% HTC award list", L24_9),
    (2024, "4", G + "2024/2024-award-list-state-htc.pdf", None, "pdf", "2024 State/Federal 4% HTC award list", L24_4),
    (2025, "9", H + "2025/9-percent-htc-awards", "2025_9-percent-htc-awards.html", "html", "2025 9% HTC award list", None),
    (2025, "4", H + "2025/4-percent-htc-awards", "2025_4-percent-htc-awards.html", "html", "2025 State and 4% HTC award list", None),
    (2026, "9", H + "2026/9-percent-htc-awards", "2026_9-percent-htc-awards.html", "html", "2026 9% HTC award list", None),
    (2026, "4", H + "2026/4-percent-htc-awards", "2026_4-percent-htc-awards.html", "html", "2026 State and 4% HTC award list", None),
]


def txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", html.unescape(str(v))).strip()


def num(v):
    """Integer from '$1,029,073', '5 4', '1 ,137,999', 47.0 ...; None if no digits."""
    if isinstance(v, (int, float)):
        return int(round(v))
    s = re.sub(r"[^\d.]", "", txt(v))
    s = s.split(".")[0]
    return int(s) if s else None


def download(url, path, problems):
    """Fetch url -> path (skipped if already there) with curl's default User-Agent (WHEDA answers Python-urllib's
    default UA with 403); falls back to urllib when curl is not installed. Blocked files are reported, not retried."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    tmp = path + ".part"
    if shutil.which("curl"):
        r = subprocess.run(["curl", "-sS", "-L", "-o", tmp, "-w", "%{http_code}", url], capture_output=True, text=True)
        code = r.stdout.strip()
        if r.returncode != 0 or code != "200":
            problems.append(f"{url}: HTTP {code or r.stderr.strip()} (skipped)")
            if os.path.exists(tmp):
                os.remove(tmp)
            return False
    else:
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            problems.append(f"{url}: HTTP {e.code} (skipped)")
            return False
        except Exception as e:  # network errors
            problems.append(f"{url}: {e} (skipped)")
            return False
        with open(tmp, "wb") as f:
            f.write(data)
    os.replace(tmp, path)
    return True


def award_row(year, kind, label, url, sid, name, city, units, li, company, fed, state=None):
    fed = fed or None
    if kind == "9":
        credit = "9%"
    else:
        credit = "4% (bond)" if fed else ""
    return {"PROJECT": txt(name).lstrip("`'").strip(), "PROJ_ADD": "", "PROJ_CTY": txt(city).title() if txt(city).isupper() else txt(city),
            "PROJ_ZIP": "", "YR_ALLOC": str(year), "CREDIT": credit, "N_UNITS": units, "LI_UNITS": li,
            "COMPANY": txt(company), "ALLOCAMT": fed, "STATE_ID": txt(sid), "SRC_LABEL": "WHEDA " + label, "SRC_URL": url,
            "_county": txt(county_clean(None))}


def county_clean(c):
    return re.sub(r"\s+county$", "", txt(c), flags=re.I).upper()


# ---------------------------------------------------------------- xlsx (2020)
def parse_xlsx(path, year, kind, label, url):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    hi = next(i for i, r in enumerate(rows) if r and txt(r[0]).lower().startswith("app"))
    hdr = [txt(c).lower() for c in rows[hi]]

    def col(rx):
        return next(j for j, h in enumerate(hdr) if re.search(rx, h))
    c_id, c_name, c_st, c_city, c_cty = col(r"^app"), col(r"name"), col(r"status"), col(r"location|city"), col(r"county")
    c_u, c_li = col(r"total units"), col(r"afford")
    c_fed = col(r"federal credit award") if kind == "4" else col(r"credit awarded")
    c_co = col(r"applicant|organization")
    out = []
    for r in rows[hi + 1:]:
        if not r or not re.fullmatch(r"\d{3,5}", txt(r[c_id])):
            continue
        if not txt(r[c_st]).lower().startswith("award"):
            continue
        a = award_row(year, kind, label, url, r[c_id], r[c_name], r[c_city], num(r[c_u]), num(r[c_li]), r[c_co], num(r[c_fed]))
        a["_county"] = county_clean(r[c_cty])
        out.append(a)
    return out


# ---------------------------------------------------------------- PDF (2021-2024)
def cell_text(chars):
    """Join chars (already one cell) into text: line by line, space where there is a visible gap."""
    chars = sorted(chars, key=lambda c: (c["top"], c["x0"]))
    lines = []
    for c in chars:
        if lines and abs(c["top"] - lines[-1][0]["top"]) <= 2.5:
            lines[-1].append(c)
        else:
            lines.append([c])
    parts = []
    for ln in lines:
        ln.sort(key=lambda c: c["x0"])
        s, prev = "", None
        for c in ln:
            if c["text"] == " " or c["text"] == " ":
                s += " "
            else:
                if prev is not None and c["x0"] - prev["x1"] > 0.22 * c["size"] and not s.endswith(" "):
                    s += " "
                s += c["text"]
            prev = c
        parts.append(s.strip())
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def pdf_rows(path, layout):
    """Yield dicts field -> text, one per application row (4-digit application number in the id column)."""
    import pdfplumber
    cuts = [x for _, x in layout]
    keys = [k for k, _ in layout]

    def colof(c):
        xc = (c["x0"] + c["x1"]) / 2
        j = 0
        for i, x in enumerate(cuts):
            if xc >= x:
                j = i
        return keys[j]

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chars = list(page.chars)
            chars.sort(key=lambda c: c["top"])
            lines = []  # [top, [chars]]
            for c in chars:
                if lines and c["top"] - lines[-1][0] <= 2.0:
                    lines[-1][1].append(c)
                else:
                    lines.append([c["top"], [c]])
            anchors, others = [], []
            for top, cs in lines:
                idt = cell_text([c for c in cs if colof(c) == "id"])
                full = cell_text(cs)
                if re.fullmatch(r"\d{4}", idt):
                    anchors.append([top, list(cs)])
                elif not re.search(r"subtotal|total", full, re.I):
                    others.append((top, cs))
            if not anchors:
                continue
            first = anchors[0][0]
            for top, cs in others:
                if top < first - 3:
                    continue  # page/table headings
                best = min(anchors, key=lambda a: abs(a[0] - top))
                if abs(best[0] - top) <= 6.5:
                    best[1].extend(cs)
            for top, cs in anchors:
                cells = {}
                for c in cs:
                    cells.setdefault(colof(c), []).append(c)
                yield {k: cell_text(v) for k, v in cells.items()}


def parse_pdf(path, year, kind, label, url, layout):
    out = []
    for r in pdf_rows(path, layout):
        if not r.get("status", "").lower().startswith("award"):
            continue
        fed = num(r.get("fed"))
        a = award_row(year, kind, label, url, r["id"], r.get("name"), r.get("city"), num(r.get("units")),
                      num(r.get("li")), r.get("company"), fed)
        a["_county"] = county_clean(r.get("county"))
        out.append(a)
    return out


# ---------------------------------------------------------------- HTML award pages (2025-2026)
def tag_text(s):
    return txt(re.sub(r"<[^>]+>", " ", s))


def parse_html_awards(path, year, kind, label, url):
    s = open(path, encoding="utf-8", errors="replace").read()
    start = s.find("<h1")
    # the awarded table ends at the first "Ineligible ..." / "Withdrawn ..." heading
    m = re.search(r"<h[1-6][^>]*>[^<]*(Ineligible|Withdrawn|Insufficient)[^<]*</h[1-6]>", s[start:], re.I)
    body = s[start: start + m.start()] if m else s[start:]
    thead = re.search(r"<thead>(.*?)</thead>", body, re.S).group(1)
    hdr = [tag_text(h).lower() for h in re.findall(r"<th[^>]*>(.*?)</th>", thead, re.S)]
    out = []
    for m in re.finditer(r'<tr class="top-row[^"]*">(.*?)</tr>\s*<tr class="sub-row[^"]*">(.*?)(?=<tr class="top-row|</tbody>\s*</table>\s*$|$)', body, re.S):
        tds = [tag_text(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
        rec = dict(zip(hdr, tds))
        dev = re.search(r'data-label="Developer">(.*?)</td>', m.group(2), re.S)
        fed = num(rec.get("federal credit award"))
        a = award_row(year, kind, label, url, rec.get("project id"), rec.get("project name"), rec.get("project city"),
                      num(rec.get("total units")), num(rec.get("affordable units") or rec.get("li units")),
                      tag_text(dev.group(1)) if dev else "", fed)
        a["_county"] = county_clean(rec.get("project county"))
        out.append(a)
    return out


# ---------------------------------------------------------------- Monitored HTC Projects inventory
def parse_inventory(path):
    s = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for sec in re.finditer(r'<section id="county-[^"]*"[^>]*>(.*?)</section>', s, re.S):
        sh = sec.group(1)
        county = county_clean(tag_text((re.search(r"<h2[^>]*>(.*?)</h2>", sh, re.S) or [None, ""])[1]))
        for art in re.finditer(r'<article class="project-card"[^>]*>(.*?)</article>', sh, re.S):
            a = art.group(1)
            pid = re.search(r"ID #\s*(\d+)", a)
            name = tag_text(re.search(r'<h3 class="project-name">(.*?)</h3>', a, re.S).group(1))
            adr = re.search(r'<address[^>]*>(.*?)</address>', a, re.S)
            street = city = zipc = ""
            if adr:
                parts = [tag_text(p) for p in re.split(r"<br\s*/?>", adr.group(1))]
                last = parts[-1] if parts else ""
                mm = re.match(r"(.*?),\s*WI\s*(\d{5})?", last)
                if mm:
                    city, zipc = mm.group(1).strip(), mm.group(2) or ""
                    street = ", ".join(p for p in parts[:-1] if p)
                # else: WHEDA's record is garbled (street lines interleaved with the manager's address, or an
                # out-of-state address) -> leave street/city/ZIP blank rather than emit a wrong address
            stats = dict((tag_text(l).lower(), tag_text(v)) for v, l in
                         re.findall(r'<span class="stat-val">(.*?)</span><span class="stat-lbl"[^>]*>(.*?)</span>', a, re.S))
            pis = re.search(r"Placed in Service</strong>\s*<time[^>]*>([^<]*)</time>", a)
            yr = re.search(r"(\d{4})", pis.group(1)).group(1) if pis and re.search(r"\d{4}", pis.group(1)) else ""
            out.append({"PROJECT": name, "PROJ_ADD": street, "PROJ_CTY": city.title(), "PROJ_ZIP": zipc, "YR_ALLOC": yr,
                        "CREDIT": "", "N_UNITS": num(stats.get("total units")), "LI_UNITS": num(stats.get("li units")),
                        "COMPANY": "", "ALLOCAMT": None, "STATE_ID": pid.group(1) if pid else "",
                        "SRC_LABEL": "WHEDA Monitored HTC Projects inventory", "SRC_URL": INVENTORY_URL, "_county": county})
    return out


# ---------------------------------------------------------------- name matching
DROP = {"LLC", "LP", "INC", "THE", "APARTMENTS", "APARTMENT", "APTS", "APT", "OF", "AT", "ON", "AND"}
NUMWORD = {"1": "I", "2": "II", "3": "III", "4": "IV", "5": "V", "6": "VI", "7": "VII", "ONE": "I", "TWO": "II", "THREE": "III"}


def norm_name(n):
    n = txt(n).upper().replace("&", " AND ")
    n = re.sub(r"\(.*?\)", " ", n)                                  # (add'l credit), (MLKEDC) ...
    n = re.sub(r"\s-\s*(STATE\s*)?(4|9)%.*$|\s(STATE\s)?4%( STATE)?$|\s-\s*(PARTIAL AWARD|ADDITIONAL CREDIT).*$", " ", n)
    n = re.sub(r"\bPHASE\b|\bPH\b", " ", n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    toks = [NUMWORD.get(t, t) for t in n.split() if t not in DROP]
    toks = [t[:-1] if len(t) > 3 and t.endswith("S") else t for t in toks]   # COTTAGES ~ COTTAGE
    return " ".join(toks)


def name_keys(n):
    """Normalized names for an inventory property ('X FKA Y' -> both X and Y)."""
    parts = re.split(r"\b(?:FKA|AKA|F/K/A)\b", txt(n).upper())
    return {k for k in (norm_name(x) for x in parts) if k}


def norm_city(c):
    c = txt(c).upper().replace(".", "")
    c = re.sub(r"^SAINT\b", "ST", c)
    return re.sub(r"[^A-Z ]", "", c).replace(" ", "")


PHASE_TOK = re.compile(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X|\d+|[A-Z]\d*)$")


def prefix_ok(a, b):
    """a is a string prefix of b (or vice versa) and the leftover is not a phase number (II, 2, B ...)."""
    if len(a) > len(b):
        a, b = b, a
    if len(a) < 8 or not b.startswith(a):
        return False
    rest = b[len(a):].split()
    return not (rest and PHASE_TOK.match(rest[0]))


def fill_addresses(awards, inv):
    by_nc, by_n = {}, {}
    for p in inv:
        if not p["PROJ_ADD"]:
            continue
        for k in name_keys(p["PROJECT"]):
            by_nc.setdefault((k, norm_city(p["PROJ_CTY"])), []).append(p)
            by_n.setdefault(k, []).append(p)
    stats = {"exact": 0, "county": 0, "prefix": 0, "none": 0}
    for a in awards:
        nn, nc = norm_name(a["PROJECT"]), norm_city(a["PROJ_CTY"])
        hit, how = by_nc.get((nn, nc)), "exact"
        if not hit:  # same name, same county (award city may be the municipality, inventory the mailing city)
            hit, how = [p for p in by_n.get(nn, []) if p["_county"] == a["_county"]], "county"
        if not hit and nn:  # one name is a prefix of the other (not differing by a phase number), same city
            # loose match: the shorter name needs 2+ words and the property must have been placed in service
            # no earlier than the year before the award (avoids older same-name properties)
            hit, how = [p for (n2, c2), ps in by_nc.items() if c2 == nc and prefix_ok(nn, n2)
                        and min(len(nn.split()), len(n2.split())) >= 2 for p in ps
                        if p["YR_ALLOC"] and int(p["YR_ALLOC"]) >= int(a["YR_ALLOC"]) - 1], "prefix"
        if hit and len({(p["PROJ_ADD"], p["PROJ_ZIP"]) for p in hit}) == 1:
            p = hit[0]
            a["PROJ_ADD"], a["PROJ_ZIP"] = p["PROJ_ADD"], p["PROJ_ZIP"]
            a["_match"] = (how, p["PROJECT"])
            stats[how] += 1
        else:
            stats["none"] += 1
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--src", default=None, help="download dir (default: <out>/../pdf/wi)")
    args = ap.parse_args()
    src = args.src or os.path.join(os.path.dirname(os.path.abspath(args.out)), "pdf", "wi")
    os.makedirs(src, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    problems, awards = [], []
    for year, kind, url, fname, fmt, label, layout in SOURCES:
        path = os.path.join(src, fname or url.rsplit("/", 1)[1])
        if not download(url, path, problems):
            continue
        if fmt == "xlsx":
            rows = parse_xlsx(path, year, kind, label, url)
        elif fmt == "pdf":
            rows = parse_pdf(path, year, kind, label, url, layout)
        else:
            rows = parse_html_awards(path, year, kind, label, url)
        print(f"{year} {kind}% {os.path.basename(path)}: {len(rows)} awarded rows")
        awards += rows
    inv = []
    ipath = os.path.join(src, "monitored-htc-projects.html")
    if download(INVENTORY_URL, ipath, problems):
        inv = parse_inventory(ipath)
        print(f"inventory: {len(inv)} properties")
        st = fill_addresses(awards, inv)
        print("address fill from inventory:", st)
    rows = awards + inv
    outp = os.path.join(args.out, "wi.csv")
    with open(outp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLS})
    print(f"wrote {outp}: {len(rows)} rows ({len(awards)} award, {len(inv)} inventory)")
    for p in problems:
        print("PROBLEM:", p, file=sys.stderr)


if __name__ == "__main__":
    main()

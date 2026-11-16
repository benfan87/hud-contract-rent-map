"""Kentucky Housing Corporation (KHC) housing credit awards -> extracted/ky.csv.

KHC posts no per-year 9% award lists. Its public "Multifamily Funding Awards: Past and Present" report (an SSRS
ReportViewer page, wapps.kyhousing.org/KHC_Webforms/Reports.aspx?rpt=/External_Report/Multifamily_Internet_Project_Listing,
linked from kyhousing.org/page/multifamily-development) is the source. Its export handler is not installed (404), so
the script fills the report's parameter form with plain HTTP POSTs (default user agent, no browser emulation) the way
the page's own buttons do, then pages through the rendered HTML (about 7 records per page):
  Source = Federal Tax Credit, Non-Competitive HC;  Year = 2020..2027;  County = all;  Group by County = No.
Each rendered page is saved under pdf/ky/ (khc_awards_pNNN.html) and reused on later runs.
Report row ("Approved Rental Project Report"): Project Name + street + "City, KY ZIP" | County | District |
Developer/Recipient (+ address, phone, contact) | Consultant | Rehab Unit Count | New Unit Count | Total Units |
Funding Status | Award Number | Funding Program Year | Agency Source | Amount.
  Federal Tax Credit  -> CREDIT 9%           Non-Competitive HC -> CREDIT 4% (bond)
YR_ALLOC = Funding Program Year (KHC's credit year; "FY-2025" -> 2025). ALLOCAMT = Amount (annual credit).
STATE_ID = Award Number. Only rows with Funding Status "Approved" are kept ("Pending App" rows are dropped), and a
row with no award number that repeats a numbered row (same project, source, amount) is dropped as a duplicate.

Also parsed: "2026 Tax-Exempt Bond Applications Funded" (kyhousing.org PDF, 4% / bond NOFA). Its projects are output
only when the report has no Non-Competitive HC row for the same project (matched on normalized name + ZIP or name +
city), so a deal is not counted twice.

Usage (from the repo root): python tools/state_pdf/ky.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import html
import http.cookiejar
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
RPT = "https://wapps.kyhousing.org/KHC_Webforms/Reports.aspx?rpt=/External_Report/Multifamily_Internet_Project_Listing"
TEB_URL = "https://www.kyhousing.org/sites/default/files/2026-07/2026%20Tax-Exempt%20Bond%20Applications%20Funded.pdf"
SOURCES = {"Federal Tax Credit": "9%", "Non-Competitive HC": "4% (bond)"}
YEARS = [str(y) for y in range(2020, 2028)]
P = "ctl00$ContentBody$rvReport$"
RV_LABEL = "KHC Multifamily Funding Awards report ({src}, program year {y})"


# ----------------------------------------------------------------------------------------------- report fetching
def form_fields(s):
    form = {}
    for m in re.finditer(r"<input[^>]*>", s):
        t = m.group(0)
        n, v, ty = (re.search(r'%s="([^"]*)"' % a, t) for a in ("name", "value", "type"))
        if n and (ty.group(1) if ty else "text") in ("hidden", "text") and "disabled" not in t:
            form[html.unescape(n.group(1))] = html.unescape(v.group(1)) if v else ""
    for m in re.finditer(r'<select name="([^"]+)"[^>]*>(.*?)</select>', s, re.S):
        sel = re.search(r'<option selected="selected" value="([^"]*)"', m.group(2))
        if sel and "disabled" not in m.group(0)[:200]:
            form[html.unescape(m.group(1))] = sel.group(1)
    return form


def valid_values(s, ctl):
    labs = re.findall(r'<label for="ctl00_ContentBody_rvReport_ctl04_%s_divDropDown_ctl\d+">([^<]*)' % ctl, s)
    return [html.unescape(x).replace("\xa0", " ") for x in labs][1:]  # [0] is "(Select All)"


def page_info(s):
    m = re.search(r"'CurrentPage':(\d+),'TotalPages':(\d+),'IsEstimatePageCount':(\w+)", s)
    return (int(m[1]), int(m[2]), m[3] == "true") if m else (None, None, None)


def fetch_report(dest_dir, max_pages=400):
    """Run the report and save every rendered page. Returns the list of page files."""
    done = dest_dir / "khc_awards_COMPLETE.txt"
    if done.exists():
        return sorted(dest_dir.glob("khc_awards_p*.html"))
    for f in dest_dir.glob("khc_awards_p*.html"):
        f.unlink()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def post(form):
        req = urllib.request.Request(RPT, data=urllib.parse.urlencode(form).encode())
        return op.open(req, timeout=180).read().decode("utf-8", "replace")

    s = op.open(RPT, timeout=60).read().decode("utf-8", "replace")
    src = valid_values(s, "ctl03")
    si = [i for i, v in enumerate(src) if v in SOURCES]
    if len(si) != len(SOURCES):
        raise RuntimeError(f"report Source values changed: {src}")
    # 1) pick the sources (the year / county lists depend on it)
    f = form_fields(s)
    f[P + "ctl04$ctl03$divDropDown$ctl01$HiddenIndices"] = ",".join(map(str, si))
    f[P + "ctl04$ctl03$txtValue"] = ", ".join(src[i] for i in si)
    f["__EVENTTARGET"], f["__EVENTARGUMENT"] = P + "ctl04$ctl03", ""
    s = post(f)
    # 2) years 2020-2027, all counties, no grouping; View Report
    yrs, cty = valid_values(s, "ctl05"), valid_values(s, "ctl07")
    yi = [i for i, v in enumerate(yrs) if v in YEARS]
    f = form_fields(s)
    f[P + "ctl04$ctl03$divDropDown$ctl01$HiddenIndices"] = ",".join(map(str, si))
    f[P + "ctl04$ctl05$divDropDown$ctl01$HiddenIndices"] = ",".join(map(str, yi))
    f[P + "ctl04$ctl05$txtValue"] = ", ".join(yrs[i] for i in yi)
    f[P + "ctl04$ctl07$divDropDown$ctl01$HiddenIndices"] = ",".join(map(str, range(len(cty))))
    f[P + "ctl04$ctl07$txtValue"] = ", ".join(cty)
    f[P + "ctl04$ctl09$ddValue"] = "2"  # Group by County? = No
    f.pop("__EVENTTARGET", None), f.pop("__EVENTARGUMENT", None)
    f[P + "ctl04$ctl00"] = "View Report"
    s = post(f)
    # 3) the report body loads in a follow-up postback (async rendering)
    f = form_fields(s)
    f["__EVENTTARGET"], f["__EVENTARGUMENT"] = P + "ctl09$Reserved_AsyncLoadTarget", ""
    s = post(f)
    files = []
    for n in range(1, max_pages + 1):
        cur, tot, est = page_info(s)
        if cur != n:
            raise RuntimeError(f"expected report page {n}, got {cur}")
        fn = dest_dir / f"khc_awards_p{n:03d}.html"
        fn.write_text(s, encoding="utf-8")
        files.append(fn)
        if cur >= tot and not est:
            break
        f = form_fields(s)
        f["__EVENTTARGET"], f["__EVENTARGUMENT"] = P + "ctl03", ""
        f[P + "ctl03$ctl00"], f[P + "ctl03$ctl01"] = "PageNav", str(n + 1)
        s = post(f)
        c2, _, _ = page_info(s)
        if c2 != n + 1:  # asked past the last page
            break
    done.write_text(f"{len(files)} pages\n", encoding="utf-8")
    return files


# ----------------------------------------------------------------------------------------------- report parsing
VOID = {"br", "img", "input", "meta", "link", "hr", "col", "area", "base", "wbr"}


class Node:
    __slots__ = ("tag", "children", "parent")

    def __init__(self, tag, parent):
        self.tag, self.children, self.parent = tag, [], parent


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = Node("root", None)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, self.cur)
        self.cur.children.append(n)
        if tag in VOID:
            if tag == "br":
                n.children.append("\n")
        else:
            self.cur = n

    def handle_endtag(self, tag):
        c = self.cur
        while c is not None and c.tag != tag:
            c = c.parent
        if c is not None and c.parent is not None:
            self.cur = c.parent

    def handle_data(self, d):
        self.cur.children.append(d)


def text(n):
    if isinstance(n, str):
        return n
    t = "".join(text(c) for c in n.children)
    return t + "\n" if n.tag in ("div", "tr", "p") else t


def lines_of(n):
    return [re.sub(r"\s+", " ", l).strip() for l in text(n).replace("\xa0", " ").split("\n") if l.strip()]


def walk(n):
    yield n
    for c in n.children:
        if not isinstance(c, str):
            yield from walk(c)


def parse_report_page(s):
    i = s.find("VisibleReportContent")
    t = Tree()
    t.feed(s[i:] if i >= 0 else s)
    out = []
    for tr in walk(t.root):
        if tr.tag != "tr":
            continue
        tds = [c for c in tr.children if not isinstance(c, str) and c.tag == "td"]
        if len(tds) < 12:
            continue
        cells = [lines_of(td) for td in tds]
        flat = [" ".join(c) for c in cells]
        if flat[-2] not in SOURCES or not re.match(r"^[\d,]+(\.\d+)?$", flat[-1]):
            continue
        out.append({"proj": cells[0], "county": flat[1], "district": flat[2], "dev": cells[3],
                    "rehab": flat[-8], "new": flat[-7], "total": flat[-6], "status": flat[-5], "award": flat[-4],
                    "year": flat[-3], "source": flat[-2], "amount": flat[-1]})
    return out


CITY_RX = re.compile(r"^(?P<city>.*?),?\s+(KY|Kentucky)\.?\s+(?P<zip>\d{5})(-\d{4})?$", re.I)


def split_proj(lines):
    """[name, street..., 'City, KY 40203'] -> name, street, city, zip."""
    name = lines[0] if lines else ""
    rest, street, city, zp = lines[1:], [], "", ""
    for l in rest:
        m = CITY_RX.match(l)
        if m and not city:
            city, zp = m["city"].strip(), m["zip"]
        elif not city and not re.match(r"(?i)^(various addresses|scattered sites?)$", l):
            street.append(l)
    return name, " ".join(street).strip(" ,"), city, zp


def norm(s):
    s = re.sub(r"\b(apartments?|apts?|homes|the|phase|ph|llc|lp)\b", " ", s.lower())
    return re.sub(r"[^a-z0-9]", "", s)


# ----------------------------------------------------------------------------------------------- TEB PDF
# column x bands of the 2026 TEB list (checked against the header words)
TEB_COLS = {"name": (45, 230), "dev": (230, 430), "codev": (430, 600), "county": (600, 660), "district": (660, 690),
            "units": (690, 725), "bonds": (725, 815), "credit": (815, 895), "equity": (895, 990), "aside": (990, 1224)}
TEB_HDR = {"Developer": 307, "County": 605, "Units": 695, "Tax-Exempt": 729, "4%": 824}


def download(url, dest):
    """Plain urllib GET (default user agent). Returns None or an error string."""
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


def parse_teb(path):
    """2026 TEB funded list -> (projects, printed GRAND TOTAL line). A project row has a county and a 4% credit;
    its next two name-column lines are the street and 'City, KY ZIP'. Portfolio / total lines have no county."""
    recs, grand = [], ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            ws = page.extract_words()
            if any(w["text"] == "Project" for w in ws):
                for word, x in TEB_HDR.items():
                    if not any(w["text"] == word and abs(w["x0"] - x) < 6 for w in ws):
                        raise ValueError(f"TEB page {page.page_number}: header {word!r} not at x={x}")
            lines = []
            for w in sorted(ws, key=lambda w: (w["top"], w["x0"])):
                if lines and abs(w["top"] - lines[-1][0]) <= 3:
                    lines[-1][1].append(w)
                else:
                    lines.append([w["top"], [w]])
            cells = [{c: " ".join(w["text"] for w in l if x0 <= (w["x0"] + w["x1"]) / 2 < x1)
                      for c, (x0, x1) in TEB_COLS.items()} for _, l in lines]
            for i, c in enumerate(cells):
                full = " ".join(v for v in c.values() if v)
                if full.startswith("GRAND TOTAL"):
                    grand = full
                if not (c["county"] and c["name"] and "$" in c["credit"] and c["units"].isdigit()):
                    continue
                nxt = [cells[j]["name"] for j in range(i + 1, min(i + 3, len(cells)))]
                street = nxt[0] if nxt and not CITY_RX.match(nxt[0]) else ""
                cm = next((CITY_RX.match(x) for x in nxt if CITY_RX.match(x)), None)
                recs.append({"name": c["name"], "dev": c["dev"], "county": c["county"], "units": int(c["units"]),
                             "bonds": money(c["bonds"]), "credit": money(c["credit"]), "street": street,
                             "city": cm["city"].strip() if cm else "", "zip": cm["zip"] if cm else ""})
    return recs, grand


def money(s):
    s = re.sub(r"[$,\s]", "", s or "")
    return round(float(s)) if re.match(r"^\d+(\.\d+)?$", s) else None


def year4(s):
    m = re.search(r"(19|20)\d\d", s or "")
    return m.group(0) if m else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output directory (../hud_src/lihtc/states/extracted)")
    ap.add_argument("--pdf-dir", help="download directory (default: <out>/../pdf/ky)")
    a = ap.parse_args()
    out_dir = Path(a.out)
    src_dir = Path(a.pdf_dir) if a.pdf_dir else out_dir.parent / "pdf" / "ky"
    src_dir.mkdir(parents=True, exist_ok=True)
    out = []
    try:
        pages = fetch_report(src_dir)
    except Exception as e:
        print(f"SKIP KHC report: {type(e).__name__}: {e}", file=sys.stderr)
        pages = []
    rows, seen = [], set()
    for p in pages:
        for r in parse_report_page(p.read_text(encoding="utf-8")):
            key = (r["award"], r["source"], r["year"], r["amount"], r["proj"][0] if r["proj"] else "")
            if key in seen:  # a record split across a page break renders on both pages
                continue
            seen.add(key)
            rows.append(r)
    print(f"KHC report: {len(pages)} pages, {len(rows)} award rows")
    # a row without an award number that repeats a numbered row (same project, source, amount) is a duplicate entry
    numbered = {(r["proj"][0], r["source"], r["amount"]) for r in rows if r["award"] and r["proj"]}
    for r in rows:
        if r["status"] != "Approved":
            print(f"  drop {r['award'] or '(no award #)'} {r['proj'][0]}: status {r['status']!r}")
            continue
        if not r["award"] and (r["proj"][0], r["source"], r["amount"]) in numbered:
            print(f"  drop duplicate (no award #) {r['proj'][0]} {r['year']} {r['amount']}")
            continue
        name, street, city, zp = split_proj(r["proj"])
        tot = int(r["total"].replace(",", "")) if r["total"].replace(",", "").isdigit() else ""
        out.append({"PROJECT": name, "PROJ_ADD": street, "PROJ_CTY": city, "PROJ_ZIP": zp, "YR_ALLOC": year4(r["year"]),
                    "CREDIT": SOURCES[r["source"]], "N_UNITS": tot, "LI_UNITS": "",
                    "COMPANY": r["dev"][0] if r["dev"] else "", "ALLOCAMT": money(r["amount"]),
                    "STATE_ID": r["award"], "SRC_LABEL": RV_LABEL.format(src=r["source"], y=r["year"]), "SRC_URL": RPT})

    teb = src_dir / "2026_TEB_Applications_Funded.pdf"
    err = download(TEB_URL, teb)
    if err:
        print(f"SKIP {TEB_URL}: {err}", file=sys.stderr)
    else:
        recs, grand = parse_teb(teb)
        print(f"2026 TEB list: {len(recs)} projects, {sum(r['units'] for r in recs):,} units, "
              f"bonds ${sum(r['bonds'] or 0 for r in recs):,}, 4% credits ${sum(r['credit'] or 0 for r in recs):,} "
              f"(printed: {grand})")
        four = [o for o in out if o["CREDIT"].startswith("4")]
        have = {(norm(o["PROJECT"]), o["PROJ_ZIP"]) for o in four} | {(norm(o["PROJECT"]), o["PROJ_CTY"].lower()) for o in four}
        for r in recs:
            if (norm(r["name"]), r["zip"]) in have or (norm(r["name"]), r["city"].lower()) in have:
                print(f"  TEB {r['name']}: already in the report (Non-Competitive HC), not repeated")
                continue
            out.append({"PROJECT": r["name"], "PROJ_ADD": r["street"], "PROJ_CTY": r["city"], "PROJ_ZIP": r["zip"],
                        "YR_ALLOC": 2026, "CREDIT": "4% (bond)", "N_UNITS": r["units"], "LI_UNITS": "",
                        "COMPANY": r["dev"], "ALLOCAMT": r["credit"], "STATE_ID": "",
                        "SRC_LABEL": "KHC 2026 Tax-Exempt Bond Only NOFA applications funded", "SRC_URL": TEB_URL})
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "ky.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows -> {out_dir / 'ky.csv'}")


if __name__ == "__main__":
    main()

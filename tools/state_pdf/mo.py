"""Missouri Housing Development Commission (MHDC) multifamily approvals -> standard CSV.

MHDC posts one PDF per funding cycle ("Rental Production Applications Approvals", 9% + 4% + state credits + HOME etc.)
plus separate 4%-only ("rolling" / "ongoing") approval sheets. All are approval lists (no rejected applications).
Layouts differ by year (column order, multi-line headers, cells that wrap above/below the Dev # line, cells centred
under their header), so the parser is header-driven:
  - a row anchor is a line whose Dev./Project # cell matches yy-nnn; wrapped text lines attach to the nearest anchor
    between the same pair of section headers;
  - a line's words are grouped into cells by horizontal gaps, and each cell is assigned to the header column whose
    centre is nearest;
  - money: Federal 4% / Federal 9% tax-credit columns (state credits, HOME, funds and bonds are ignored).
A row with Federal 9% > 0 becomes a "9%" row, Federal 4% > 0 a "4% (bond)" row (both if both). Rows with no federal
LIHTC (HOME / fund only) are dropped. YR_ALLOC = 2000 + the Dev # prefix (funding year; FY2023/24 was one cycle
numbered 24-). City only - MHDC lists have no street address / ZIP / low-income unit count.
Usage: python tools/state_pdf/mo.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import urllib.request

import pdfplumber

PAGE = "https://mhdc.com/about-us/nofa-approvals/multifamily/"
FILES = [  # (label, url)
    ("FY2026 multifamily rental production approvals (9%/4%/state)",
     "https://mhdc.com/media/sifa3rqg/multifamily-rental-production-applications_approvals.pdf"),
    ("FY2026 federal 4% LIHTC approvals", "https://mhdc.com/media/li3laq4v/federal-4-lihtc-applications_approvals_september-2026.pdf"),
    ("FY2025 multifamily rental production approvals", "https://mhdc.com/media/0o2afpgt/2025-multifamily-rental-production-approvals.pdf"),
    ("FY2025 federal 4% LIHTC approvals", "https://mhdc.com/media/20zdy2hq/federal-4-lihtc_approvals_2025.pdf"),
    ("FY2023/2024 9% and 4% approvals", "https://mhdc.com/media/obekdl0h/9-and-4-application-approvals.pdf"),
    ("FY2023/2024 4% LIHTC-only ongoing approvals", "https://mhdc.com/media/qz2d0fxf/4-lihtc-only_ongoing-application-approvals.pdf"),
    ("FY2022 approved applications", "https://mhdc.com/media/k40ndzcq/fy2022-approved-applications.pdf"),
    ("FY2022 4% rolling approved applications", "https://mhdc.com/media/vlonnea3/2022-4-rolling-approved-applications.pdf"),
    ("FY2021 round 1 approved applications", "https://mhdc.com/media/ccgjpsom/fy2021-round-1-approved-applications.pdf"),
    ("FY2021 4% rolling (tax-exempt bond) approvals", "https://mhdc.com/media/rhth3pdm/4-approved-commission-web-2162023.pdf"),
    ("FY2020 4% & 9% rental production approved applications",
     "https://mhdc.com/media/djleeqxz/2020-4-9-rental-production-approved-applications.pdf"),
    ("FY2020 round two 4% LIHTC approvals",
     "https://mhdc.com/media/rfshxlwc/approved-2020-round-two-4-low-income-housing-tax-credits.pdf"),
]
COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
DEVNO = re.compile(r"^\d\d-\d{3}[A-Z]?$")
CITIES = r"(St\. Louis|Kansas City|St\. Joseph|St\. Charles|Springfield|Columbia|Independence|Joplin)"


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
    except Exception as e:
        print(f"SKIP {url}: {e}")
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def clean(s):
    s = (s or "").replace("�", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def group_lines(words, tol):
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1]["top"] - w["top"]) <= tol:
            lines[-1]["ws"].append(w)
        else:
            lines.append({"top": w["top"], "ws": [w]})
    for ln in lines:
        ln["ws"].sort(key=lambda w: w["x0"])
    return lines


def cells_of(ws, gap):
    """Split a line's words into cells at horizontal gaps > gap. '$' joins the following number."""
    cells = []
    for w in ws:
        if cells and (w["x0"] - cells[-1]["x1"] <= gap or cells[-1]["text"] == "$"
                      or (re.match(r"^[\d,]", w["text"]) and re.fullmatch(r"\$?\s?\d{1,2}", cells[-1]["text"])
                          and w["x0"] - cells[-1]["x1"] < gap * 1.5)):
            c = cells[-1]
            sep = "" if w["x0"] - c["x1"] < 0.5 and re.match(r"^[\d,]", w["text"]) else " "
            c["text"] += sep + w["text"]
            c["x1"] = max(c["x1"], w["x1"])
        else:
            cells.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"], "top": w["top"]})
    return cells


def money(s):
    s = (s or "").replace(" ", "")
    m = re.search(r"\d[\d,]*", s)
    return int(m.group(0).replace(",", "")) if m else 0


def header_columns(lines, hi, gap):
    """Columns from header line `hi` (bottom header line) plus label words from lines up to ~4 lines above."""
    hl = lines[hi]
    h = hl["ws"][0]["bottom"] - hl["ws"][0]["top"]
    band = [w for ln in lines[max(0, hi - 5):hi] if hl["top"] - ln["top"] < 5.5 * h for w in ln["ws"]]
    cols = []
    for c in cells_of(hl["ws"], gap):
        cols.append({"x0": c["x0"], "x1": c["x1"], "bottom": c["text"], "above": []})
    # header cells on upper lines with nothing beneath them on the bottom line become their own columns
    for ln in lines[max(0, hi - 5):hi]:
        if hl["top"] - ln["top"] >= 5.5 * h:
            continue
        for c in cells_of(ln["ws"], gap):
            if not any(col["x0"] - h <= (c["x0"] + c["x1"]) / 2 <= col["x1"] + h for col in cols):
                cols.append({"x0": c["x0"], "x1": c["x1"], "bottom": "", "above": []})
    for w in band:  # attach upper header words to the bottom cell under their centre (nearest centre)
        cx = (w["x0"] + w["x1"]) / 2
        best = min(cols, key=lambda c: abs((c["x0"] + c["x1"]) / 2 - cx))
        if best["x0"] - 3 * h <= cx <= best["x1"] + 3 * h:
            best["above"].append(w)
    for c in cols:
        c["label"] = clean(" ".join(w["text"] for w in sorted(c["above"], key=lambda w: (round(w["top"]), w["x0"])))
                           + " " + c["bottom"])
        c["cx"] = (c["x0"] + c["x1"]) / 2
    return cols


def classify(label, bottom):
    L = label.lower()
    b = bottom.lower()
    if re.match(r"(dev\.|development|project) ?#", b):
        return "devno"
    if b in ("development name",) or b.endswith("development name"):
        return "name"
    if b == "developer":
        return "developer"
    if b == "city":
        return "city"
    if b == "units":
        return "units"
    if "federal 4%" in L:
        return "fed4"
    if "federal 9%" in L:
        return "fed9"
    return "other:" + label


KEEP = ("devno", "name", "developer", "city", "units", "fed4", "fed9")


def text_from_chars(chars, fh):
    """Chars of one table cell -> text, line by line (interleaved overlapping lines are separated by 'top')."""
    out = []
    for ln in group_lines([c for c in chars if c["text"].strip() or c["x1"] - c["x0"] > 0.05], tol=0.3 * fh):
        t, prev = "", None
        for c in ln["ws"]:
            if prev is not None and c["x0"] - prev["x1"] > 0.22 * fh:
                t += " "
            t += c["text"]
            prev = c
        out.append(t)
    return clean(" ".join(out))


def grid_row(pg, sect, j, cols, fh, hedges, vedges):
    """One data row: the band between the table rules around the Dev # line, cut into cells by the vertical
    rules that cross it; each cell takes the kind of the header column whose centre lies inside it."""
    anc = sect[j]["ws"][0]
    y0 = max([y for y in hedges if y <= anc["top"] + 0.5], default=None)
    y1 = min([y for y in hedges if y >= anc["bottom"] - 0.5], default=None)
    if y0 is None or y1 is None:  # no rules: fall back to the Dev # line alone
        y0, y1 = anc["top"] - 0.5, anc["bottom"] + 0.5
    mid = (y0 + y1) / 2
    xs = sorted(e["x0"] for e in vedges if e["top"] <= mid <= e["bottom"])
    merged = []
    for x in xs:
        if not merged or x - merged[-1] > 2:
            merged.append(x)
    if len(merged) < 4:  # no usable vertical rules: midpoints between header centres
        cx = sorted(c["cx"] for c in cols)
        merged = [-1e9] + [(a + b) / 2 for a, b in zip(cx, cx[1:])] + [1e9]
    rec = {}
    chars = [c for c in pg.chars if y0 < (c["top"] + c["bottom"]) / 2 < y1]  # keep space glyphs
    for lo, hi in zip(merged, merged[1:]):
        inside = [c for c in cols if lo <= c["cx"] < hi]
        kinds = [c["kind"] for c in inside if c["kind"] in KEEP] or [c["kind"] for c in inside]
        if not kinds:
            continue
        cc = [c for c in chars if lo <= (c["x0"] + c["x1"]) / 2 < hi]
        if any(c["text"].strip() for c in cc):
            rec.setdefault(kinds[0], text_from_chars(cc, fh))
    return rec


def parse_file(path):
    out = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            words = pg.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
            if not words:
                continue
            fh = sorted(w["bottom"] - w["top"] for w in words)[len(words) // 2]  # median font height
            gap = 0.55 * fh
            lines = group_lines(words, tol=0.25 * fh)
            hedges = sorted({round(e["top"], 1) for e in pg.edges if e["orientation"] == "h" and e["width"] > 20})
            vedges = [e for e in pg.edges if e["orientation"] == "v" and e["height"] > 3]
            hdr_idx = [i for i, ln in enumerate(lines)
                       if any(re.match(r"^(Dev\.|Development|Project)$", w["text"]) for w in ln["ws"][:2])
                       and any(w["text"] == "#" for w in ln["ws"][:3])
                       and any(w["text"] in ("City", "Developer") for w in ln["ws"])]
            for k, hi in enumerate(hdr_idx):
                cols = header_columns(lines, hi, gap)
                for c in cols:
                    c["kind"] = classify(c["label"], c["bottom"])
                end = len(lines)
                if k + 1 < len(hdr_idx):  # stop above the next header block (contiguous label lines)
                    end = hdr_idx[k + 1]
                    while end - 1 > hi and lines[end]["top"] - lines[end - 1]["top"] < 1.9 * fh \
                            and not DEVNO.match(lines[end - 1]["ws"][0]["text"]):
                        end -= 1
                sect = lines[hi + 1:end]
                anchors = [j for j, ln in enumerate(sect) if DEVNO.match(ln["ws"][0]["text"])]
                for j in anchors:
                    out.append(grid_row(pg, sect, j, cols, fh, hedges, vedges))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--pdf-dir", default=None)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    pdf_dir = a.pdf_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "pdf", "mo")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    allrows = []
    for label, url in FILES:
        fn = os.path.join(pdf_dir, url.rstrip("/").split("/")[-1])
        if not fetch(url, fn):
            continue
        recs = parse_file(fn)
        n9 = n4 = nd = 0
        for r in recs:
            if a.debug:
                print(r)
            devno = r.get("devno", "").split()[0]
            name, dev, city = r.get("name", ""), r.get("developer", ""), r.get("city", "")
            if not city:  # developer and city glued together ("...Corp.St. Louis")
                m = re.match(r"(.*?)\s*" + CITIES + r"$", dev)
                if m:
                    dev, city = m.group(1), m.group(2)
            units = re.search(r"\d+", r.get("units", ""))
            f9, f4 = money(r.get("fed9")), money(r.get("fed4"))
            if not (f9 or f4):
                nd += 1
                continue
            for cr, amt in (("9%", f9), ("4% (bond)", f4)):
                if not amt:
                    continue
                n9 += cr == "9%"
                n4 += cr != "9%"
                allrows.append({
                    "PROJECT": name.rstrip(" *"), "PROJ_ADD": "", "PROJ_CTY": city, "PROJ_ZIP": "",
                    "YR_ALLOC": 2000 + int(devno[:2]), "CREDIT": cr, "N_UNITS": units.group(0) if units else "",
                    "LI_UNITS": "", "COMPANY": dev, "ALLOCAMT": amt, "STATE_ID": devno,
                    "SRC_LABEL": f"Missouri Housing Development Commission {label}", "SRC_URL": url})
        print(f"{os.path.basename(fn)}: {len(recs)} dev rows -> {n9} x 9%, {n4} x 4%, {nd} dropped (no federal LIHTC)")
    out = os.path.join(a.out, "mo.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(allrows)
    print(f"wrote {len(allrows)} rows -> {out}")


if __name__ == "__main__":
    main()

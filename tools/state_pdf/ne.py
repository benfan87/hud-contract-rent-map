"""Nebraska Investment Finance Authority (NIFA) LIHTC lists -> extracted/ne.csv.

Sources (all PDFs on https://www.nifa.org/developers-property-managers/forms-docs):
  * 9% LIHTC/AHTC Reservation Lists, 2020-2027 (CREDIT 9%, ALLOCAMT = LIHTC reserved/requested)
  * 4% Conditional Allocation Lists, 2021-2026 (CREDIT 4% (bond); ALLOCAMT = LIHTC requested; the 2021 and 2022
    4% lists show only the bond volume cap requested, so ALLOCAMT is blank there)
The "2025_4_with_AHTC" / "2025_4_only" files on the same page are full-application lists, not awards: not used.

Two layouts:
  * card layout (9% 2020-2025, 4% 2021-2024): NIFA # | development name + street + "City, NE ZIP" | applicant |
    county | units | ... | amounts, each record several lines tall. Parsed by x columns found from the data.
  * one-row table layout (9% 2026, 2027; 4% 2025, 2026): cells centred and wrapped above/below the row;
    no ZIP. Parsed with per-file column x ranges; each word goes to the row whose centre line is nearest.
Kept: every listed reservation, including supplemental and forward-commitment entries (noted in SRC_LABEL).
Dropped: total/subtotal/heading lines, and entries marked "Credits not accepted".
YR_ALLOC = the list's reservation / allocation year. STATE_ID = NIFA project number.

Usage (from the repo root): python tools/state_pdf/ne.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]
S3 = "https://www-nifa-org-files.s3.amazonaws.com/"
# (year, credit, file, title, layout)
FILES = [
    (2020, "9%", "a97a-06383867-Reservation_List_2020.pdf", "2020 9% LIHTC/AHTC Reservation List", "card"),
    (2021, "9%", "c916-46383867-Reservation_List_2021.pdf", "2021 9% LIHTC/AHTC Reservation List", "card"),
    (2022, "9%", "2ba6-25660967-reservation_list_2022.pdf", "2022 9% LIHTC/AHTC Reservation List", "card"),
    (2023, "9%", "14fd-21913967-2023_Reservation_List_10.14.2022.pdf", "2023 9% LIHTC/AHTC Reservation List (10/14/2022)", "card"),
    (2024, "9%", "22dc-95727177-2024_Reservation_List_6.9.2025.pdf", "2024 9% LIHTC/AHTC Reservation List (6/9/2025)", "card"),
    (2025, "9%", "248b-75577177-2025_Reservation_List_12.17.2025.pdf", "2025 9% LIHTC/AHTC Reservation List (12/17/2025)", "card"),
    (2026, "9%", "0bdf-27408177-2026_Reservation_List_7.23.26.pdf", "2026 9% LIHTC/AHTC Reservation List (7/23/2026)", "t2026"),
    (2027, "9%", "2615-70618177-NIFA_2027_Reservation_List_-_Accessible_Version.pdf", "2027 9% LIHTC/AHTC Reservation List (8/28/2026)", "t2027"),
    (2021, "4% (bond)", "9317-85089077-2021_4_Conditional_Allocation_List_Final_9-23.pdf", "2021 4% Conditional Allocation List", "card"),
    (2022, "4% (bond)", "d3b4-91631967-2022_4_Conditional_Allocation_List_6.15.2022.pdf", "2022 4% Conditional Allocation List (6/15/2022)", "card"),
    (2023, "4% (bond)", "0914-35417177-2023_4__Conditional_Allocation_List_9.23.2024.pdf", "2023 4% Conditional Allocation List (9/23/2024)", "card"),
    (2024, "4% (bond)", "0826-00117177-2024_4__Conditional_Allocation_List_4.9.2025.pdf", "2024 4% Conditional Allocation List (4/9/2025)", "card"),
    (2025, "4% (bond)", "99f4-83007177-2025_4_Percent_Cond_Alloc_2.28.25.pdf", "2025 4% Conditional Allocation List (2/28/2025)", "t4_2025"),
    (2026, "4% (bond)", "c7f6-27128177-2026_4_Percent_Cond_Alloc_List_7.24.2026.pdf", "2026 4% Conditional Allocation List (7/24/2026)", "t4_2026"),
]

COUNTIES = """Adams Antelope Arthur Banner Blaine Boone Box_Butte Boyd Brown Buffalo Burt Butler Cass Cedar Chase Cherry
Cheyenne Clay Colfax Cuming Custer Dakota Dawes Dawson Deuel Dixon Dodge Douglas Dougals Dundy Fillmore Franklin
Frontier Furnas Gage Garden Garfield Gosper Grant Greeley Hall Hamilton Harlan Hayes Hitchcock Holt Hooker Howard
Jefferson Johnson Kearney Keith Keya_Paha Kimball Knox Lancaster Lincoln Logan Loup McPherson Madison Merrick Morrill
Nance Nemaha Nuckolls Otoe Pawnee Perkins Phelps Pierce Platte Polk Red_Willow Richardson Rock Saline Sarpy Saunders
Scotts_Bluff Scottsbluff Seward Sheridan Sherman Sioux Stanton Thayer Thomas Thurston Valley Washington Wayne Webster
Wheeler York""".split()
COUNTIES = sorted((c.replace("_", " ") for c in COUNTIES), key=lambda c: -len(c))
CITY_RX = re.compile(r"^(?P<city>.+?),?\s+N[Ee]\.?(\s+(?P<zip>\d{5})(-?\d{4})?)?\s*$")
ADDR_START = re.compile(r"^(\d|TBD|Approx|Scattered|Various|various|NEC|NWC|SEC|SWC|NE |NW |SE |SW |N of|S of|E of|W of|"
                        r"North of|South of|East of|West of|Corner|Lot|Hwy|Highway)")


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


def group_lines(words, tol=2.5):
    out = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(w["top"] - out[-1][0]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(ws, key=lambda w: w["x0"])) for t, ws in out]


def txt(ws):
    return re.sub(r"\s+", " ", " ".join(w["text"] for w in ws)).strip()


def col_words(page, lo, hi):
    """Words built only from chars whose left edge lies in [lo, hi) (splits text that runs across a column edge)."""
    sub = page.filter(lambda o: o.get("object_type") != "char" or lo <= o["x0"] < hi)
    return sub.extract_words()


def struck(page, w):
    """True when a hairline rect/line runs through the middle of word w (NIFA strikes out returned/withdrawn awards)."""
    for o in page.rects + page.lines:
        if abs(o["bottom"] - o["top"]) < 1.5 and o["x1"] - o["x0"] > 3 and o["x0"] < w["x1"] - 2 and o["x1"] > w["x0"] + 2                 and w["top"] + 2 < o["top"] < w["bottom"] - 1:
            return True
    return False


def money(s):
    d = re.sub(r"[^\d.]", "", s)
    d = d.split(".")[0]
    return int(d) if d else None


def money_clusters(ws, xmin):
    """Group money-ish tokens ("$", "7", "33,789") right of xmin into clusters -> [(center, value)]."""
    toks = [w for w in ws if w["x0"] >= xmin and re.fullmatch(r"\$?[\d,.\-]*", w["text"]) and w["text"]]
    out = []
    for w in toks:
        if out and w["x0"] - out[-1][-1]["x1"] < 7:
            out[-1].append(w)
        else:
            out.append([w])
    res = []
    for c in out:
        s = "".join(w["text"] for w in c)
        if "$" not in s and not re.search(r"\d{1,3},\d{3}", s):
            continue
        res.append(((c[0]["x0"] + c[-1]["x1"]) / 2, money(s)))
    return res


def split_city(s):
    m = CITY_RX.match(s.strip())
    if not m:
        return None
    return m.group("city").strip(" ,"), (m.group("zip") or "")


def strip_county(s):
    for c in COUNTIES:
        if s == c:
            return ""
        if s.endswith(" " + c):
            return s[: -len(c) - 1].strip()
    return s


# ---------------------------------------------------------------- card layout
def parse_card(path, credit):
    pdf = pdfplumber.open(path)
    anchor_rx = re.compile(r"^\d-\d{4}$" if credit == "9%" else r"^6\d{4}$")
    recs = []
    pages = []
    for page in pdf.pages:
        ws = page.extract_words()
        lines = group_lines(ws)
        hdr = next((l for t, l in lines if any(w["text"] == "COUNTY" for w in l) and any(w["text"] == "UNITS" for w in l)), None)
        hdr1 = next((l for t, l in lines if any(w["text"] == "ESTIMATED" for w in l)), [])
        anchors = [(t, l[0]) for t, l in lines if anchor_rx.match(l[0]["text"]) and l[0]["x0"] < 45]
        pages.append((page, lines, hdr, hdr1, anchors))
    # column edges from the data
    nx, ax = Counter(), Counter()
    for page, lines, hdr, hdr1, anchors in pages:
        units_x = min(w["x0"] for w in hdr if w["text"] == "UNITS")
        for t, l in lines:
            mid = [w for w in l if 44 < w["x0"] < units_x - 25]
            if l[0]["x0"] < 45 and anchor_rx.match(l[0]["text"]) and len(l) > 1:
                nx[round(l[1]["x0"])] += 1
            gaps = [(mid[i + 1]["x0"] - mid[i]["x1"], mid[i + 1]["x0"]) for i in range(len(mid) - 1)]
            gaps = [g for g in gaps if g[0] >= 6]
            if gaps:
                ax[round(max(gaps)[1])] += 1
    # boundaries just left of the columns' left edges (chars are assigned by their left edge)
    N0 = nx.most_common(1)[0][0] - 0.6
    A0 = max((x for x, c in ax.items() if c >= 3 and x > N0 + 40), key=lambda x: ax[x]) - 0.6
    for page, lines, hdr, hdr1, anchors in pages:
        hx = lambda w: (w["x0"] + w["x1"]) / 2
        units = [hx(w) for w in hdr if w["text"] in ("UNITS", "BLDGS")][:4]
        cost_i = next(i for i, w in enumerate(hdr) if w["text"] == "COST")
        has_vol = any(w["text"] == "VOLUME" for w in hdr1)
        labels = (["vol", "lihtc", "ahtc"] if has_vol else ["lihtc", "ahtc"])
        mcols = [("cost", hx(hdr[cost_i]))] + list(zip(labels, [hx(w) for w in hdr[cost_i + 1:]]))
        xmin = hdr[cost_i]["x0"] - 35
        units_x0 = min(w["x0"] for w in hdr if w["text"] == "UNITS")
        name_ws = group_lines(col_words(page, N0, A0))
        app_ws = group_lines(col_words(page, A0, units_x0 - 3))
        lab_ws = group_lines(col_words(page, 0, N0))
        tot = next((t for t, l in lines if l[0]["text"].upper() == "TOTAL"), page.height)
        hdr_bot = max(w["top"] for w in hdr) + 4
        if recs and anchors:  # lines above the first record continue the last record of the previous page
            cont = lambda L: [txt(l) for tt, l in L if hdr_bot < tt < anchors[0][0] - 3 and txt(l)]
            recs[-1]["segs"] += cont(name_ws)
            recs[-1]["app"] += cont(app_ws)
        for i, (t, aw) in enumerate(anchors):
            t1 = anchors[i + 1][0] - 3 if i + 1 < len(anchors) else tot - 3
            t0 = t - 3
            band = lambda L: [(tt, l) for tt, l in L if t0 <= tt < t1]
            seg = [txt(l) for tt, l in band(name_ws)]
            seg = [re.sub(r"\s*\($", "", s) for s in seg]
            seg = [s for s in seg if s]
            app = [txt(l) for tt, l in band(app_ws)]
            lab = " ".join(txt(l) for tt, l in band(lab_ws)).replace(aw["text"], "").strip()
            full = " ".join(txt(l) for tt, l in band(lines))
            aline = [l for tt, l in lines if abs(tt - t) <= 2.5][0]
            # units / amounts on the anchor line
            u = {}
            for w in aline:
                if re.fullmatch(r"\d{1,4}", w["text"]) and w["x0"] > units_x0 - 20 and w["x0"] < xmin:
                    j = min(range(len(units)), key=lambda k: abs(units[k] - hx(w)))
                    if abs(units[j] - hx(w)) < 18:
                        u[j] = int(w["text"])
            m = {}
            for c, v in money_clusters(aline, xmin):
                k = min(mcols, key=lambda kv: abs(kv[1] - c))
                m[k[0]] = v
            recs.append({"id": aw["text"], "struck": struck(page, aw), "segs": seg, "app": app, "label": lab, "full": full,
                         "total": u.get(0), "li": u.get(1), "lihtc": m.get("lihtc"), "ahtc": m.get("ahtc"),
                         "vol": m.get("vol")})
    return recs


def card_fields(r):
    segs = list(r["segs"])
    ci = max((i for i, s in enumerate(segs) if i > 0 and split_city(s)), default=None)
    city = zp = ""
    if ci is not None:
        city, zp = split_city(segs[ci])
        segs = segs[:ci]
    elif len(segs) >= 3 and not re.search(r"\d", segs[-1]) and len(segs[-1].split()) <= 3:
        city, segs = segs[-1], segs[:-1]  # bare city name without ", NE"
    if len(segs) >= 3 and not ADDR_START.match(segs[1]) and ADDR_START.match(segs[2]):
        name, addr = " ".join(segs[:2]), " ".join(segs[2:])
    else:
        name, addr = (segs[0] if segs else ""), " ".join(segs[1:])
    if re.match(r"(?i)^(scattered sites?|various addresses|TBD)$", addr):
        addr = ""
    addr = re.sub(r"^(TBD|Scattered Sites)\s+", "", addr)
    app = strip_county(r["app"][0]) if r["app"] else ""
    return name, addr, city, zp, app


# ---------------------------------------------------------------- one-row table layouts
# column x ranges (word x0) per layout, from the files' word positions
TCOLS = {
    "t2026": dict(anchor=(0, 75), name=(75, 155), addr=(155, 232), city=(232, 266), app=(295, 382),
                  total=(465, 485), li=(485, 505), alloc=(580, 615)),
    "t2027": dict(anchor=(0, 120), name=(120, 220), addr=(220, 315), city=(315, 410), total=(540, 640),
                  li=(640, 730), alloc=(920, 1000)),
    "t4_2025": dict(anchor=(0, 55), name=(55, 132), addr=(132, 195), city=(195, 225), app=(255, 355),
                    li=(535, 555), total=(555, 580), alloc=(630, 675)),
    "t4_2026": dict(anchor=(0, 60), name=(60, 138), addr=(138, 200), city=(200, 226), app=(255, 345),
                    li=(455, 480), total=(480, 505), alloc=(550, 590)),
}


def rows_by_center(lines, centers):
    """Assign each line to the row whose centre is nearest (only lines within 13pt of some centre)."""
    out = {c: [] for c in centers}
    for t, l in lines:
        if re.search(r"(?i)\btotals?\b|^\* Has|^(METRO|NON-METRO)$|Projects$", txt(l)):
            continue
        c = min(centers, key=lambda c: abs(c - t))
        if abs(c - t) <= 13:
            out[c].append((t, l))
    return out


def parse_table(path, layout, credit):
    cfg = TCOLS[layout]
    pdf = pdfplumber.open(path)
    anchor_rx = re.compile(r"^\d-\d{4}$" if credit == "9%" else r"^6\d{4}$")
    recs = []
    apps = {}
    for pno, page in enumerate(pdf.pages):
        ws = [w for w in page.extract_words() if w["text"] != "✓"]
        if layout == "t2027" and pno == 1:  # applicant & contact page
            lines = group_lines(ws)
            anc = [(t, l[0]["text"]) for t, l in lines if anchor_rx.match(l[0]["text"])]
            byc = rows_by_center(lines, [t for t, _ in anc])
            for t, pid in anc:
                aw = [w for tt, l in byc[t] for w in l if 405 <= w["x0"] < 600]
                apps[pid] = txt(sorted(aw, key=lambda w: (round(w["top"]), w["x0"])))
            continue
        if layout == "t2027" and pno > 1:
            continue
        lines = group_lines(ws)
        a_lo, a_hi = cfg["anchor"]
        aws = [w for w in ws if anchor_rx.match(w["text"]) and w["x0"] < a_hi]
        anchors = [(w["top"], w["text"]) for w in aws]
        lo, hi = cfg["alloc"]
        amts = [w for w in ws if lo <= w["x0"] < hi and w["text"].startswith("$")]
        centers = []
        for t, pid in anchors:  # row centre = the amount nearest the project number
            near = [w["top"] for w in amts if abs(w["top"] - t) < 13]
            centers.append(min(near, key=lambda x: abs(x - t)) if near else t)
        byc = rows_by_center(lines, centers)
        for (t, pid), c, aw in zip(anchors, centers, aws):
            rw = [w for tt, l in byc[c] for w in l]

            def field(k, rw=rw):
                lo, hi = cfg[k]
                sel = [w for w in rw if lo <= w["x0"] < hi]
                return txt(sorted(sel, key=lambda w: (round(w["top"]), w["x0"])))
            lab = field("anchor").replace(pid, "").strip()
            num = lambda k: (int(re.sub(r"\D", "", field(k))) if re.sub(r"\D", "", field(k)) else None)
            recs.append({"id": pid, "struck": struck(page, aw), "name": field("name"), "addr": field("addr"), "city": field("city"),
                         "app": field("app") if "app" in cfg else "", "label": lab, "full": txt(rw),
                         "total": num("total"), "li": num("li"), "lihtc": money(field("alloc")) if field("alloc") else None})
    for r in recs:
        if not r["app"]:
            r["app"] = apps.get(r["id"], "")
    return recs


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "ne"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped, dropped = [], [], []
    for yr, credit, fn, title, layout in FILES:
        url = S3 + fn
        dest = pdir / fn
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        base = f"NIFA {title}"
        n = 0
        if layout == "card":
            recs = parse_card(dest, credit)
        else:
            recs = parse_table(dest, layout, credit)
        for r in recs:
            if re.search(r"(?i)credits\s+not\s+accepted", r["label"] + " " + r["full"]):
                dropped.append(f"{yr} {credit} {r['id']} (credits not accepted)")
                continue
            if r["struck"]:
                dropped.append(f"{yr} {credit} {r['id']} (struck through)")
                continue
            if layout == "card":
                name, addr, city, zp, app = card_fields(r)
            else:
                name, addr, city, zp, app = r["name"], r["addr"], r["city"], "", r["app"]
                if re.match(r"(?i)^(scattered sites?|various addresses|TBD)$", addr):
                    addr = ""
            notes = []
            lab = re.sub(r"[()]", " ", r["label"])
            for k, v in [("Supplemental", "supplemental reservation"), ("Forward", "forward commitment"),
                         ("CRANE", "CRANE"), ("Round 1", "round 1"), ("Round 2", "round 2")]:
                if k.lower() in lab.lower():
                    notes.append(v)
            mret = re.search(r"Returned Credits(?: in \d{4})?", r["full"])
            if mret:
                notes.append(mret.group(0).lower())
            amt = r["lihtc"]
            if credit != "9%" and amt is None:
                notes.append(f"LIHTC amount not listed; bond volume cap requested ${r['vol']:,}" if r.get("vol") else "LIHTC amount not listed")
            name = name.rstrip("* ").strip()
            rows.append({"PROJECT": name, "PROJ_ADD": addr, "PROJ_CTY": city, "PROJ_ZIP": zp[:5], "YR_ALLOC": str(yr),
                         "CREDIT": credit, "N_UNITS": r["total"] if r["total"] is not None else "",
                         "LI_UNITS": r["li"] if r["li"] is not None else "", "COMPANY": app,
                         "ALLOCAMT": amt if amt is not None else "", "STATE_ID": r["id"],
                         "SRC_LABEL": base + (f" ({'; '.join(notes)})" if notes else ""), "SRC_URL": url})
            n += 1
        print(f"{fn}: {len(recs)} listed, kept {n}")
    with open(out / "ne.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'ne.csv'}")
    for d in dropped:
        print("dropped", d)
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

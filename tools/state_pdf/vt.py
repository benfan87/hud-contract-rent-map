"""Vermont Housing Finance Agency (VHFA) housing tax credit allocations -> extracted/vt.csv.

Source 1 (awards): VHFA "Housing Tax Credit Allocations and Reservations" cumulative CSV export, 1987-present.
  Columns: Project Name, City, Total Housing Units, Local partners, Sponsor, Tax Credit units, Unit type,
  Allocation amount, Allocation type (Federal / Tax Exempt Bonds / State), Allocation year.
  - Federal           -> CREDIT 9%, ALLOCAMT = amount
  - Tax Exempt Bonds  -> CREDIT 4% (bond), ALLOCAMT = amount
  - State (Vermont affordable housing tax credit): folded into the label of the same project's federal / bond row
    of the same year; otherwise written as its own row with CREDIT blank and ALLOCAMT blank (state credit only).
  Several lines for the same project + year + type are summed into one row. Lines with no project name are dropped.
Source 2 (addresses): HousingData.org Directory of Affordable Rental Housing (run by VHFA). The directory map page
  (/directory/map) embeds every mapped property with name, street, town and lat/lon; VHFA projects are matched by
  name + town. ZIP codes come from the matched properties' own directory pages (one GET each, cached; --no-zip skips).
  Matching is by name, so a project renamed since its award may be left with town only.

Usage (from the repo root): python tools/state_pdf/vt.py --out ../hud_src/lihtc/states/extracted [--no-zip]
"""
import argparse
import csv
import html
import io
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL", "LAT", "LON"]

CSV_URL = "https://vhfa.org/developers/lihtc/reservations-and-allocations/csv-export?page&_format=csv"
HD = "https://housingdata.org"
MAP_URL = HD + "/directory/map"
TYPE = {"Federal": "9%", "Tax Exempt Bonds": "4% (bond)", "State": ""}


def get(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def curl(url, timeout=60):
    """curl with its own default user agent (vhfa.org answers 403 to Python-urllib but serves curl)."""
    p = subprocess.run(["curl", "-sSfL", "--max-time", str(timeout), url], capture_output=True)
    if p.returncode:
        raise RuntimeError(f"curl exit {p.returncode}: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout


def download(url, dest, check=None):
    """Plain urllib GET (default Python user agent), falling back to plain curl on an HTTP 403; cached.
    Returns None on success, else an error string."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    try:
        try:
            data = get(url)
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
            data = curl(url)
    except Exception as e:  # 403 / bot block / network: skip and report
        return f"{type(e).__name__}: {e}"
    if check and not check(data):
        return "unexpected response content"
    dest.write_bytes(data)
    return None


ABBR = {"street": "st", "saint": "st", "streets": "sts", "place": "pl", "terrace": "ter", "lane": "ln", "court": "ct",
        "avenue": "ave", "road": "rd", "drive": "dr", "center": "ctr", "centre": "ctr", "square": "sq",
        "building": "bldg", "mount": "mt", "north": "n", "south": "s", "east": "e", "west": "w", "no": "n", "so": "s",
        "apts": "apartments", "apt": "apartments", "hsg": "housing", "sr": "senior", "elderly": "senior"}
STOPW = {"the", "apartments", "housing", "homes", "home", "senior", "phase", "i", "ii", "iii", "iv", "v", "at", "of",
         "and", "lp", "llc", "inc", "limited", "partnership", "rental", "rentals", "project", "family", "redevelopment",
         "rehab", "rehabilitation", "allocated", "a", "an", "mf", "living"}
VILLAGE = {"whiteriverjunction": "hartford", "wilder": "hartford", "quechee": "hartford", "bellowsfalls": "rockingham",
           "saxtonsriver": "rockingham", "wellsriver": "newbury", "waterburycenter": "waterbury", "westdover": "dover",
           "morrisville": "morristown", "proctorsville": "cavendish", "derbyline": "derby", "lyndonville": "lyndon",
           "essexjunction": "essex", "enosburgfalls": "enosburgh", "enosburg": "enosburgh", "alburg": "alburgh",
           "westburke": "burke", "grandisle": "grandisle"}


def toks(s):
    s = html.unescape(s or "").lower().replace("&", " and ")
    s = re.sub(r"\bco-?op(erative)?\b", "coop", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s.replace("'", ""))
    return {ABBR.get(w, w) for w in s.split()} - STOPW


def alt_names(s):
    out = [s, re.sub(r"\(.*?\)", " ", s)]
    out += re.findall(r"\((?:aka|fka|formerly|f/k/a|a/k/a)?\s*([^)]*)\)", s, re.I)
    return [x for x in out if toks(x)]


def town(c):
    c = re.sub(r"\s+(city|town)$", "", (c or "").strip().lower())
    c = re.sub(r"[^a-z]", "", c.replace("saint", "st"))
    return VILLAGE.get(c, c)


def best_match(name, city, dirs):
    """Directory entry for a VHFA project: same town (villages folded into towns) and token Jaccard >= 0.6,
    or an identical name anywhere when that name is unique statewide. Names reduced to the town name alone don't match."""
    tc = town(city)
    ctoks = toks(city)
    cands = []
    for d in dirs:
        same = town(d["city"]) == tc
        for a in alt_names(name):
            A, B = toks(a), toks(d["name"])
            if not A or not B or A <= ctoks:
                continue
            j = len(A & B) / len(A | B)
            if same and j >= 0.6:
                cands.append((j, d))
            elif j == 1 and not same:
                cands.append((0.5, d))
    if not cands:
        return None, 0
    cands.sort(key=lambda x: -x[0])
    top = [c for c in cands if c[0] == cands[0][0] and c[1]["slug"] != cands[0][1]["slug"]]
    if top:  # tie between different properties
        return None, 0
    if cands[0][0] == 0.5 and sum(1 for d in dirs if toks(d["name"]) == toks(cands[0][1]["name"])) > 1:
        return None, 0
    return cands[0][1], cands[0][0]


def money(s):
    s = (s or "").replace("$", "").replace(",", "").strip()
    return int(float(s)) if re.fullmatch(r"\d+(\.\d+)?", s) else 0


def num(s):
    s = (s or "").replace(",", "").strip()
    return s if re.fullmatch(r"\d+", s) else ""


def parse_map(path):
    """-> list of {slug, name, street, city, lat, lon} from the Leaflet settings JSON in the directory map page."""
    t = path.read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>', t, re.S)
    if not m:
        return []
    out = []
    for lm in json.loads(m.group(1)).get("leaflet", {}).values():
        for f in lm.get("features", []):
            pop = (f.get("popup") or {}).get("value", "")
            a = re.search(r'<a href="/directory/([^"]+)"[^>]*>(.*?)</a>(.*)', pop, re.S)
            if not a:
                continue
            lines = [html.unescape(l).strip() for l in re.sub(r"<[^>]+>", "\n", a.group(3)).split("\n") if l.strip()]
            street = lines[0] if len(lines) >= 2 else ""
            city = re.sub(r",?\s*VT\s*$", "", lines[-1]).strip() if lines else ""
            out.append({"slug": a.group(1), "name": html.unescape(a.group(2)).strip(), "street": street, "city": city,
                        "lat": f.get("lat"), "lon": f.get("lon")})
    return out


def page_zip(path):
    """ZIP from a directory property page: the address line under the title ends with ', 05xxx'."""
    t = re.sub(r"<[^>]+>", "\n", path.read_text(encoding="utf-8", errors="replace"))
    for l in t.split("\n"):
        m = re.search(r",\s*(0[5-9]\d{3})\s*$", html.unescape(l).strip())
        if m:
            return m.group(1)
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--no-zip", action="store_true", help="do not fetch directory property pages for ZIP codes")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "vt"
    pdir.mkdir(parents=True, exist_ok=True)
    skipped = []

    dest = pdir / "vhfa_allocations.csv"
    err = download(CSV_URL, dest, check=lambda b: b"Allocation year" in b[:500])
    if err:
        print(f"SKIP {CSV_URL}: {err}", file=sys.stderr)
        sys.exit(1)
    raw = list(csv.DictReader(io.StringIO(dest.read_text(encoding="utf-8-sig"))))
    noname = sum(1 for r in raw if not r["Project Name"].strip())

    # group lines -> (project, city, year) -> type -> summed amount + first line
    g = defaultdict(lambda: defaultdict(list))
    order = []
    for r in raw:
        nm = r["Project Name"].strip()
        if not nm:
            continue
        k = (nm, r["City"].strip(), r["Allocation year"].strip())
        if k not in g:
            order.append(k)
        g[k][r["Allocation type"].strip()].append(r)

    # directory addresses
    dirs = []
    mp = pdir / "housingdata_directory_map.html"
    err = download(MAP_URL, mp, check=lambda b: b"leaflet" in b)
    if err:
        skipped.append((MAP_URL, err))
    else:
        dirs = parse_map(mp)
    print(f"directory map: {len(dirs)} properties")
    match = {}
    for nm, city, _ in order:
        if (nm, city) not in match:
            match[(nm, city)] = best_match(nm, city, dirs)[0]
    rows, n_lines = [], 0
    for k in order:
        nm, city, yr = k
        types = g[k]
        st = sum(money(r["Allocation amount"]) for r in types.get("State", []))
        main_types = [t for t in ("Federal", "Tax Exempt Bonds") if t in types]
        unknown = [t for t in types if t not in TYPE]
        if unknown:
            print(f"  unknown allocation type {unknown} for {k}", file=sys.stderr)
        for t in main_types or ["State"]:
            ls = types[t]
            n_lines += len(ls)
            r0 = ls[0]
            amt = sum(money(r["Allocation amount"]) for r in ls)
            base = f"VHFA housing tax credit allocations & reservations {yr}"
            if t == "Federal":
                lab = base + " - federal (9%) credit"
            elif t == "Tax Exempt Bonds":
                lab = base + " - tax-exempt bond (4%) credit"
            else:
                lab = base + f" - Vermont state housing tax credit only (${amt:,}; not a federal LIHTC award this year)"
            if t != "State" and st and t == main_types[0]:
                lab += f" (+ Vermont state credit ${st:,})"
                n_lines += len(types["State"])
            if len(ls) > 1:
                lab += f"; {len(ls)} allocation lines summed"
            d = match.get((nm, city))
            if d:
                lab += f"; address from HousingData.org directory entry '{d['name']}' ({d['city']}), matched by name + town"
            comp = " / ".join(dict.fromkeys(x for x in (r0["Local partners"].strip(), r0["Sponsor"].strip()) if x))
            rows.append({"PROJECT": nm, "PROJ_ADD": d["street"] if d else "", "PROJ_CTY": city,
                         "PROJ_ZIP": "", "YR_ALLOC": yr, "CREDIT": TYPE.get(t, ""), "N_UNITS": num(r0["Total Housing Units"]),
                         "LI_UNITS": num(r0["Tax Credit units"]), "COMPANY": comp,
                         "ALLOCAMT": str(amt) if t != "State" and amt else "", "STATE_ID": "", "SRC_LABEL": lab,
                         "SRC_URL": CSV_URL, "LAT": f"{d['lat']:.6f}" if d and d.get("lat") else "",
                         "LON": f"{d['lon']:.6f}" if d and d.get("lon") else "", "_slug": d["slug"] if d else ""})

    # ZIPs from the matched directory pages
    if not a.no_zip:
        hdir = pdir / "housingdata"
        hdir.mkdir(exist_ok=True)
        zips, nfail = {}, 0
        for slug in sorted({r["_slug"] for r in rows if r["_slug"]}):
            p = hdir / (re.sub(r"[^a-z0-9-]", "_", slug) + ".html")
            fresh = not p.exists()
            err = download(f"{HD}/directory/{slug}", p, check=lambda b: b"<html" in b[:2000].lower())
            if err:
                nfail += 1
                if nfail <= 5:
                    skipped.append((f"{HD}/directory/{slug}", err))
                continue
            zips[slug] = page_zip(p)
            if fresh:
                time.sleep(0.5)
        for r in rows:
            r["PROJ_ZIP"] = zips.get(r["_slug"], "")
        print(f"directory pages: {len(zips)} read, {nfail} failed, {sum(1 for z in zips.values() if z)} with ZIP")

    with open(out / "vt.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(raw)} CSV lines ({noname} without project name dropped); {n_lines} lines -> {len(rows)} rows "
          f"({sum(1 for r in rows if r['PROJ_ADD'])} with directory address) -> {out / 'vt.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

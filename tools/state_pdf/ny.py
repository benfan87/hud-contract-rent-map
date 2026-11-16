"""New York LIHTC projects (NYS HCR + NYC HPD) -> extracted/ny.csv.

Sources (all public, plain HTTP GET with the default Python user agent):
  1. NYS HCR 9% RFP award PDFs, 2020-2025 rounds (hcr.ny.gov). One table per file: Project ID (8-digit SHARS id),
     REDC, Developer/Awardee & Project Name, County & Municipality, 9% LIHTC $, other subsidies, Residential Units.
     No street address -> filled from the HCR asset-map layers below by Project ID, else by name + municipality/county.
     YR_ALLOC = year the award list was published (e.g. the "Fall 2022" round was announced in 2023).
  2. NYS HCR Multifamily Asset Map (ArcGIS Online, webmap f2fa91e2eead40fabb41be2aa696eff8). The layer services are
     renamed every quarter (dhcr_YYYYqN_public ...), so the current URLs are read from the webmap's JSON config.
       - "9% LIHTC and Housing Trust Fund Assets (DHCR)": building-level. Kept: buildings funded with LIHC (federal
         9% credit -> CREDIT 9%) or LIHB (credit with bonds -> CREDIT 4% (bond)); HTF/HOME/SLIC-only buildings are
         dropped. Collapsed to one row per proj_id. YR_ALLOC = earliest building placed-in-service year.
       - "... (DHCR) - Under Construction": building-level pipeline, collapsed per SHARS id. Layer gives no funding
         type, so CREDIT is blank unless the project is a PDF award (then the PDF row is used). YR_ALLOC = year of
         DT_1ST_PROG_COMPET (first program commitment).
       - "4% LIHTC and Bond Financed Assets (HFA)": building-level, collapsed per HFANumber. CREDIT 4% (bond).
         YR_ALLOC = earliest placed-in-service year (blank for in-progress deals, which have no PIS date). The HFA
         "Under Construction" layer is the inprogress=Y subset of this layer, so it is not downloaded.
     A map project that matches a PDF award (by id or name) is not written again; its address/ZIP/coords go to the
     award row. A DHCR pipeline project is dropped when it is already in the DHCR built layer or the HFA layer
     (same name + city), when an award PDF lists it with no 9% credit, or when it has 0 residential units.
  3. NYC HPD "Low Income Housing Tax Credits Awarded by HPD" (NYC Open Data, Socrata JSON API):
       frre-6z6q project-level 9% + kmtx-45c9 building-level 9%; p8i7-ix2s project-level 4% + h9ws-rfd9 building 4%.
     Building addresses joined on project name + application_year (first building = PROJ_ADD). In p8i7-ix2s the
     column "latitude" holds the applicant (developer) name. The tables' latitude/longitude/bbl and postcode describe
     the APPLICANT's address, not the project, so no ZIP or coordinates are written for HPD rows.
     YR_ALLOC = year of the CRA (9%) / DOCE (4%) date, else application_year.

Optional LAT/LON columns (decimal degrees) come from the HCR map layers.

Usage (from the repo root): python tools/state_pdf/ny.py --out ../hud_src/lihtc/states/extracted [--refresh]
"""
import argparse
import csv
import datetime
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL", "LAT", "LON"]

HCR = "https://hcr.ny.gov/system/files/documents/"
# (round name, year the award list was published = YR_ALLOC, path under HCR)
AWARD_PDFS = [
    ("Summer 2020", 2020, "2020/11/summer-2020-multifamily-project-awards.pdf"),
    ("Fall 2020", 2021, "2021/04/fall-2020-9-percent-multifamily-awards_0.pdf"),
    ("Summer 2021", 2021, "2021/12/summer-2021-9-percent-awards-web-version.pdf"),
    ("Winter 2022", 2022, "2022/07/winter-2022-9-percent-awards-web-version.pdf"),
    ("Fall 2022", 2023, "2023/05/fall-2022-9-percent-awards.pdf"),
    ("Fall 2023", 2024, "2024/03/fall-2023-9pct-rfp-awards.pdf"),
    ("2024", 2025, "2025/03/2024-9pct-rfp-project-awards.pdf"),
    ("2025", 2026, "2026/02/2025-9pct-rfp-project-awards.pdf"),
]
# Cells where pdfplumber lost the line break between developer and project name: Project ID -> project name.
NAME_FIX = {"20210043": "MacKenzie Overlook"}

WEBMAP = "https://nyshcr.maps.arcgis.com/sharing/rest/content/items/f2fa91e2eead40fabb41be2aa696eff8/data?f=json"
WEBMAP_PAGE = "https://hcr.ny.gov/hcr-multifamily-asset-map"
LAYERS = {  # key -> regex on the webmap layer title
    "dhcr": re.compile(r"^9% LIHTC and Housing Trust Fund Assets \(DHCR\)$"),
    "dhcr_ip": re.compile(r"^9% LIHTC and Housing Trust Fund Assets \(DHCR\) - Under Construction$"),
    "hfa": re.compile(r"^4% LIHTC and Bond Financed Assets \(HFA\)$"),
}

SOCRATA = "https://data.cityofnewyork.us/resource/{}.json?$limit=50000"
HPD = [  # project table, building table, credit, amount col, date col, developer col, label
    ("frre-6z6q", "kmtx-45c9", "9%", "cra_amount", "cra_date", "applicant_name",
     "NYC HPD LIHTC awards, project-level 9% (frre-6z6q; addresses from kmtx-45c9)"),
    ("p8i7-ix2s", "h9ws-rfd9", "4% (bond)", "doce_amount", "doce_date", "latitude",
     "NYC HPD LIHTC awards, project-level 4% (p8i7-ix2s; addresses from h9ws-rfd9)"),
]
BORO = {"manhattan": "New York", "new york": "New York", "bronx": "Bronx", "brooklyn": "Brooklyn", "kings": "Brooklyn",
        "queens": "Queens", "staten island": "Staten Island", "richmond": "Staten Island"}


def get(url, timeout=120):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def curl(url, timeout=120):
    """curl with its own default user agent (hcr.ny.gov answers 403 to Python-urllib but serves curl)."""
    p = subprocess.run(["curl", "-sSfL", "--max-time", str(timeout), url], capture_output=True)
    if p.returncode:
        raise RuntimeError(f"curl exit {p.returncode}: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout


def download(url, dest, refresh=False, check=None):
    """Plain urllib GET (default Python user agent), falling back to plain curl on an HTTP 403.
    Returns None on success, else an error string."""
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
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


def fetch_layer(url, dest, refresh=False):
    """Page through an ArcGIS FeatureServer layer (2,000 rows/page); cache {url, features} as JSON."""
    if dest.exists() and not refresh:
        return json.loads(dest.read_text(encoding="utf-8"))["features"]
    feats, off = [], 0
    while True:
        q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "returnGeometry": "false", "f": "json",
                                    "orderByFields": "OBJECTID", "resultOffset": off, "resultRecordCount": 2000})
        d = json.loads(get(url + "/query?" + q))
        if "error" in d:
            raise RuntimeError(f"{url}: {d['error']}")
        fs = [f["attributes"] for f in d.get("features", [])]
        feats += fs
        off += len(fs)
        if not fs or (not d.get("exceededTransferLimit") and len(fs) < 2000):
            break
        time.sleep(0.5)
    dest.write_text(json.dumps({"url": url, "fetched": datetime.date.today().isoformat(), "features": feats}),
                    encoding="utf-8")
    return feats


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


STOP = r"\b(the|apartments?|apts?|homes?|housing|residences?|senior|seniors|phase|ph|i{1,3}|iv|llc|inc|lp|at|of|and)\b"


def loose(s):
    s = re.sub(r"&", " and ", (s or "").lower())
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"[^a-z0-9]", "", re.sub(STOP, " ", s))


def year_of(ms):
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).year


def money(s):
    s = (s or "").replace("$", "").replace(",", "").strip()
    return int(float(s)) if re.fullmatch(r"\d+(\.\d+)?", s) else None


def num(s):
    s = str(s if s is not None else "").replace(",", "").strip()
    return s if re.fullmatch(r"\d+", s) else ""


def title(s):
    """Upper-case map text -> Title Case (keeps ordinals like 4TH -> 4th)."""
    if not s:
        return ""
    if s != s.upper():
        return s.strip()
    s = re.sub(r"\b(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), s.strip().title())
    return re.sub(r"'S\b", "'s", s)


def city_fix(c):
    """NYC county names used as a city in the map layers -> borough / USPS city."""
    return {"kings": "Brooklyn", "richmond": "Staten Island", "manhattan": "New York"}.get((c or "").strip().lower(), c or "")


def split_addr1(a):
    """'street[, BUILDING n], city, zip' -> (street, city, zip)."""
    parts = [p.strip() for p in (a or "").split(",") if p.strip()]
    zp = parts.pop()[:5] if parts and re.fullmatch(r"\d{5}(-\d{4})?", parts[-1]) else ""
    city = parts.pop() if len(parts) >= 2 else ""
    parts = [p for p in parts if not re.match(r"(?i)^(building|bldg)\b", p)]
    return ", ".join(parts), city, zp


# ---------------------------------------------------------------- HCR award PDFs
def parse_award_pdf(path, map_names=None):
    pdf = pdfplumber.open(path)
    hdr, out = None, []
    for page in pdf.pages:
        for t in page.extract_tables():
            for r in t:
                cells = [(c or "").strip() for c in r]
                if not cells:
                    continue
                if cells[0] == "Project ID":
                    hdr = [re.sub(r"\s+", " ", c) for c in cells]
                    continue
                if not re.fullmatch(r"\d{8}", cells[0]):
                    continue  # totals row etc.
                if hdr is None or len(cells) != len(hdr):
                    raise RuntimeError(f"{path.name}: row {cells[0]} has {len(cells)} cells, header {hdr}")
                out.append(dict(zip(hdr, cells)))
    pdf.close()
    if not out:
        return out
    h = list(out[0].keys())
    c_dev = next(k for k in h if "Developer" in k or "Awardee" in k)
    c_mun = next(k for k in h if "Municipality" in k)
    c_9 = next(k for k in h if "9%" in k)
    c_un = next(k for k in h if "Residential Units" in k)
    recs = []
    for r in out:
        pid = r["Project ID"]
        lines = [l.strip() for l in r[c_dev].split("\n") if l.strip()]
        if pid in NAME_FIX:
            name = NAME_FIX[pid]
            dev = r[c_dev].replace("\n", " ").replace(name, "").strip()
        else:
            name, dev = lines[-1], " ".join(lines[:-1])
            # a project name that wrapped onto two lines ("Sennett Meadows Senior" / "Apartments"): if the map
            # layer's name for this id ends the cell, split there; else join a lone generic last word
            full = " ".join(lines)
            mn = re.sub(r"\s+", " ", (map_names or {}).get(pid, "")).strip()
            if mn and len(name) < len(mn) < len(full) and full.lower().endswith(mn.lower()):
                name, dev = full[-len(mn):], full[:-len(mn)].strip()
            elif len(lines) >= 3 and re.fullmatch(r"(?i)(apartments|apts\.?|residences?|homes|commons|lofts|"
                                                  r"village|manor|housing|phase \w+)", name):
                name, dev = lines[-2] + " " + name, " ".join(lines[:-2])
        m = re.match(r"^(.*?)\s*((?:City|Town|Village) of .*)$", r[c_mun].replace("-\n", "-").replace("\n", " ").strip())
        county, muni = (m.group(1).strip(), m.group(2).strip()) if m else (r[c_mun].split("\n")[0], "")
        city = re.sub(r"^(City|Town|Village) of\s+", "", muni)
        if norm(city) == "newyork":
            city = BORO.get(county.lower(), "New York")
        recs.append({"pid": pid, "name": name, "dev": dev, "county": county, "muni": muni, "city": city_fix(city),
                     "amt9": money(r[c_9]), "units": num(r[c_un])})
    return recs


# ---------------------------------------------------------------- HCR map layers -> project records
def collapse_dhcr(feats):
    by = defaultdict(list)
    for f in feats:
        fund = f.get("samis_bldg_funding") or ""
        if re.search(r"\bLIH[CB]\b", fund):
            by[f["proj_id"]].append(f)
    projs = []
    for pid, bs in by.items():
        bs.sort(key=lambda f: f["OBJECTID"])
        b = bs[0]
        funds = {c.strip() for f in bs for c in (f.get("samis_bldg_funding") or "").split(",")}
        yrs = [y for y in (year_of(f.get("dt_in_service")) for f in bs) if y]
        projs.append({"src": "dhcr", "key": pid, "sid8": pid[:8], "name": title(b["proj_name"]),
                      "addr": title(b["bldg_address"]), "city": city_fix(title(b["bldg_city"])),
                      "zip": str(b["bldg_zip"]).zfill(5) if b.get("bldg_zip") else "", "county": title(b["county_name"]),
                      "lat": b.get("latitude"), "lon": b.get("longitude"), "units": num(b.get("proj_tot_res_units")),
                      "owner": b.get("ownr_name") or "", "year": min(yrs) if yrs else None, "nb": len(bs),
                      "credit": "9%" if "LIHC" in funds else "4% (bond)", "funds": ", ".join(sorted(funds - {""}))})
    return projs


def collapse_dhcr_ip(feats):
    by = defaultdict(list)
    for f in feats:
        by[str(f["SHARS_txt"])].append(f)
    projs = []
    for sid, bs in by.items():
        bs.sort(key=lambda f: f["OBJECTID"])
        b = bs[0]
        street, city, zp = split_addr1(b.get("Addr1Line"))
        yrs = [y for y in (year_of(f.get("DT_1ST_PROG_COMPET")) for f in bs) if y]
        projs.append({"src": "dhcr_ip", "key": sid, "sid8": sid[:8], "name": b["MC_NAME"].strip(), "addr": title(street),
                      "city": city_fix(title(city or b.get("MUNICIPALITY"))), "zip": zp, "county": title(b.get("COUNTY")),
                      "lat": b.get("LATITUDE"), "lon": b.get("LONGITUDE"), "units": num(b.get("RES_UNITS")),
                      "owner": "", "year": min(yrs) if yrs else None, "nb": len(bs), "credit": "",
                      "status": b.get("CURRENT_STAT") or ""})
    return projs


def collapse_hfa(feats):
    by = defaultdict(list)
    for f in feats:
        by[str(f["HFANumber"])].append(f)
    projs = []
    for hid, bs in by.items():
        bs.sort(key=lambda f: f["OBJECTID"])
        b = bs[0]
        street, city, zp = split_addr1(b.get("addr1line"))
        yrs = [y for y in (year_of(f.get("PIS_Date")) for f in bs) if y]
        projs.append({"src": "hfa", "key": hid, "sid8": None, "name": b["PropertyName"].strip(), "addr": street,
                      "city": city_fix(city), "zip": zp, "county": b.get("county") or "", "lat": b.get("latitude"),
                      "lon": b.get("longitude"), "units": num(b.get("PropTotalUnits")), "owner": b.get("OwnerName") or "",
                      "year": min(yrs) if yrs else None, "nb": len(bs), "credit": "4% (bond)",
                      "inprog": b.get("inprogress") == "Y"})
    return projs


class MapIndex:
    def __init__(self, projs):
        self.by_id = defaultdict(list)
        self.by_name = defaultdict(list)
        for p in projs:
            if p["sid8"]:
                self.by_id[p["sid8"]].append(p)
            for f in (norm, loose):
                k = f(p["name"])
                if k:
                    self.by_name[(k, norm(p["city"]))].append(p)
                    self.by_name[(k, "county:" + norm(p["county"]))].append(p)

    def find(self, sid, name, city, county):
        if sid and self.by_id.get(sid):
            return self.by_id[sid], "id"
        for f in (norm, loose):
            k = f(name)
            if not k:
                continue
            for key in ((k, norm(city)), (k, "county:" + norm(county))):
                if self.by_name.get(key):
                    return self.by_name[key], "name"
        return [], None


def best(cands):
    """Prefer the DHCR built layer, then the pipeline layer, then HFA; within a layer the first record."""
    order = {"dhcr": 0, "dhcr_ip": 1, "hfa": 2}
    return sorted(cands, key=lambda p: order[p["src"]])[0]


def coord(v):
    return f"{float(v):.6f}" if isinstance(v, (int, float)) and v else ""


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    ap.add_argument("--refresh", action="store_true", help="re-download cached map layers / open-data tables")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "ny"
    pdir.mkdir(parents=True, exist_ok=True)
    skipped, rows = [], []

    # --- HCR map layers
    layer_url, projs = {}, {"dhcr": [], "dhcr_ip": [], "hfa": []}
    wm = pdir / "hcr_webmap.json"
    err = download(WEBMAP, wm, a.refresh, check=lambda b: b.lstrip().startswith(b"{"))
    if err:
        skipped.append((WEBMAP, err))
    else:
        def walk(ls):
            for l in ls:
                yield l
                yield from walk(l.get("layers", []))
        for l in walk(json.loads(wm.read_text(encoding="utf-8")).get("operationalLayers", [])):
            for k, rx in LAYERS.items():
                if rx.match((l.get("title") or "").strip()) and l.get("url"):
                    layer_url[k] = l["url"]
        for k in LAYERS:
            if k not in layer_url:
                skipped.append((WEBMAP, f"layer '{k}' not found in webmap config"))
                continue
            try:
                feats = fetch_layer(layer_url[k], pdir / f"hcr_layer_{k}.json", a.refresh)
            except Exception as e:
                skipped.append((layer_url[k], f"{type(e).__name__}: {e}"))
                continue
            projs[k] = {"dhcr": collapse_dhcr, "dhcr_ip": collapse_dhcr_ip, "hfa": collapse_hfa}[k](feats)
            print(f"map layer {k}: {len(feats)} buildings -> {len(projs[k])} projects ({layer_url[k]})")
    allmap = projs["dhcr"] + projs["dhcr_ip"] + projs["hfa"]
    idx = MapIndex(allmap)
    map_names = {p["sid8"]: p["name"] for p in projs["dhcr_ip"] + projs["dhcr"] if p["sid8"]}
    used = set()  # id(project) of map projects absorbed into another row

    hfa_names = defaultdict(list)
    for p in projs["hfa"]:
        hfa_names[(loose(p["name"]), norm(p["city"]))].append(p)

    # --- HCR 9% award PDFs
    n_match, no9 = Counter(), set()
    for rnd, yr, path in AWARD_PDFS:
        url = HCR + path
        dest = pdir / Path(path).name
        err = download(url, dest, check=lambda b: b.startswith(b"%PDF"))
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        recs = parse_award_pdf(dest, map_names)
        kept = 0
        for r in recs:
            if not r["amt9"]:
                print(f"  {dest.name}: {r['pid']} {r['name']} has no 9% LIHTC amount - dropped")
                no9.add(r["pid"])
                continue
            cands, how = idx.find(r["pid"], r["name"], r["city"], r["county"])
            m = best(cands) if cands else None
            n_match[how or "none"] += 1
            for c in cands:
                used.add(id(c))
            # the same deal often also sits in the HFA layer (HFA subsidy loan on a 9% project)
            for c in list(cands) + ([m] if m else []) + [{"name": r["name"], "city": r["city"]}]:
                for h in hfa_names.get((loose(c["name"]), norm(c["city"])), []):
                    used.add(id(h))
            label = (f"NYS HCR {rnd} 9% RFP project awards (list published {yr}; YR_ALLOC = publication year)")
            if m:
                label += f"; address from HCR asset map layer {m['src']} (matched by {'project id' if how == 'id' else 'name + municipality'})"
            rows.append({"PROJECT": r["name"], "PROJ_ADD": m["addr"] if m else "",
                         "PROJ_CTY": (m["city"] if m and m["city"] else r["city"]), "PROJ_ZIP": m["zip"] if m else "",
                         "YR_ALLOC": str(yr), "CREDIT": "9%", "N_UNITS": r["units"], "LI_UNITS": "",
                         "COMPANY": r["dev"], "ALLOCAMT": str(r["amt9"]), "STATE_ID": r["pid"], "SRC_LABEL": label,
                         "SRC_URL": url, "LAT": coord(m["lat"]) if m else "", "LON": coord(m["lon"]) if m else ""})
            kept += 1
        print(f"{dest.name}: {len(recs)} projects, kept {kept}")
    print(f"award PDF -> map matches: {dict(n_match)}")

    # --- map projects not absorbed by an award row
    dhcr_ids = {p["sid8"] for p in projs["dhcr"]}
    drop = Counter()
    for p in allmap:
        if id(p) in used:
            drop[p["src"] + " (in award PDF)"] += 1
            continue
        if p["src"] == "dhcr_ip":
            if p["sid8"] in dhcr_ids:
                drop["dhcr_ip (in DHCR built layer)"] += 1
                continue
            if hfa_names.get((loose(p["name"]), norm(p["city"]))):
                drop["dhcr_ip (in HFA 4% layer)"] += 1
                continue
            if p["sid8"] in no9:
                drop["dhcr_ip (award PDF shows no 9% credit)"] += 1
                continue
            if not p["units"] or p["units"] == "0":
                drop["dhcr_ip (0 residential units: commercial/CIF)"] += 1
                continue
        if p["src"] == "dhcr":
            label = ("NYS HCR asset map, 9% LIHTC & HTF assets (DHCR), building layer collapsed to project; "
                     f"funding {p['funds']}; YR_ALLOC = first building placed-in-service year (no award year in layer)")
        elif p["src"] == "dhcr_ip":
            label = ("NYS HCR asset map, 9% LIHTC & HTF assets (DHCR) under construction/pipeline, collapsed to "
                     f"project; status {p['status']}; credit type not given (9% LIHTC or HTF only); "
                     "YR_ALLOC = year of first program commitment")
        else:
            label = ("NYS HCR asset map, 4% LIHTC & bond financed assets (HFA), building layer collapsed to project; "
                     + ("in progress, no placed-in-service date" if p.get("inprog") or not p["year"]
                        else "YR_ALLOC = first placed-in-service year (no award year in layer)"))
        rows.append({"PROJECT": p["name"], "PROJ_ADD": p["addr"], "PROJ_CTY": p["city"], "PROJ_ZIP": p["zip"],
                     "YR_ALLOC": str(p["year"]) if p["year"] else "", "CREDIT": p["credit"], "N_UNITS": p["units"],
                     "LI_UNITS": "", "COMPANY": p["owner"], "ALLOCAMT": "", "STATE_ID": p["key"], "SRC_LABEL": label,
                     "SRC_URL": layer_url[p["src"]], "LAT": coord(p["lat"]), "LON": coord(p["lon"])})
    print(f"map projects not written separately: {dict(drop)}")

    # --- NYC HPD
    for ptab, btab, credit, amtc, datec, devc, label in HPD:
        data = {}
        for tid in (ptab, btab):
            url = SOCRATA.format(tid)
            dest = pdir / f"nyc_hpd_{tid}.json"
            err = download(url, dest, a.refresh, check=lambda b: b.lstrip().startswith(b"["))
            if err:
                skipped.append((url, err))
                print(f"SKIP {url}: {err}", file=sys.stderr)
                continue
            data[tid] = json.loads(dest.read_text(encoding="utf-8"))
        if ptab not in data:
            continue
        addrs = defaultdict(list)
        for b in data.get(btab, []):
            ad = (b.get("project_address_es") or "").strip()
            if ad:
                addrs[(norm(b.get("project_name")), b.get("application_year"))].append(ad)
        # one row per project + award: lines with the same name and application_year (supplementary CRAs), and
        # lines of one project split over two application years under the same award year, are combined
        by_ay = defaultdict(list)
        for r in data[ptab]:
            by_ay[(norm(r.get("project_name")), r.get("application_year"))].append(r)
        groups = defaultdict(list)
        for (nk, ay), rs in by_ay.items():
            dts = sorted(x.get(datec) for x in rs if x.get(datec))
            groups[(nk, dts[0][:4] if dts else ay or "")] += rs
        n_addr = 0
        for (nk, yr), rs in groups.items():
            r = rs[0]
            amts = [money(x.get(amtc)) for x in rs]
            amt = sum(x for x in amts if x) or None
            dts = sorted(x.get(datec) for x in rs if x.get(datec))
            ad = [a for ay in sorted({x.get("application_year") for x in rs}) for a in addrs.get((nk, ay), [])]
            n_addr += bool(ad)
            lab = label + ("; YR_ALLOC = year of " + ("CRA" if credit == "9%" else "DOCE") + " date" if dts
                           else "; YR_ALLOC = application_year (no CRA/DOCE date)")
            if len(rs) > 1:
                lab += f"; {len(rs)} rows for this project/year combined (amount summed)"
            rows.append({"PROJECT": r.get("project_name", "").strip(), "PROJ_ADD": title(ad[0]) if ad else "",
                         "PROJ_CTY": BORO.get((r.get("project_borough") or "").strip().lower(), r.get("project_borough", "")),
                         "PROJ_ZIP": "", "YR_ALLOC": yr, "CREDIT": credit, "N_UNITS": num(r.get("total_units")),
                         "LI_UNITS": num(r.get("total_tax_credit_units")), "COMPANY": (r.get(devc) or "").strip(),
                         "ALLOCAMT": str(amt) if amt else "", "STATE_ID": "", "SRC_LABEL": lab,
                         "SRC_URL": SOCRATA.format(ptab), "LAT": "", "LON": ""})
        print(f"HPD {ptab}: {len(data[ptab])} rows -> {len(groups)} projects, {n_addr} with building address")

    with open(out / "ny.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'ny.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

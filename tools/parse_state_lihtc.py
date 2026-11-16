"""Parse state housing-agency LIHTC award / property lists into the row shape of HUD's LIHTC layer, for
tools/match_lihtc.py and tools/build_lihtc_all.py. One config entry per source file (tools/state_lihtc_sources.json).

Config entry:
  st, label, page, url, fetched     state code; source label shown on the site; agency page; file URL; date posted/fetched
  file                              local copy (relative to --src-dir)
  sheets                            sheet names (xlsx/xls), "*" = every sheet; ignored for csv/pdf
  cols                              {FIELD: header regex}. FIELD is one of PROJECT, PROJ_ADD, PROJ_CTY, PROJ_ZIP, YR_ALLOC,
                                    YR_PIS, N_UNITS, LI_UNITS, CREDIT, BOND, TYPE, COMPANY, ALLOCAMT, STATE_ID, LAT, LON.
                                    Two fields may share a column (e.g. YR_ALLOC from an ID like CA-2024-123).
  const                             {FIELD: value} for fields the file doesn't have (e.g. CREDIT "9%", YR_ALLOC from sheet)
  year_from_sheet                   true: YR_ALLOC = the 4-digit year in the sheet name (per-year workbooks)
  header_rows                       rows to scan for the header (default 15); header = first row matching cols.PROJECT
  skip                              regex: rows whose PROJECT matches are dropped (totals, section titles)
  drop                              {header regex: value regex}: rows whose cell matches are dropped (e.g. "No Award")
  require_any                       [header regex, ...]: keep only rows where one of these cells is a number > 0
  year_fallback                     header regex of a date column used when YR_ALLOC is empty (e.g. application date)
  csv_std                           true: file is a tools/state_pdf extraction CSV (standard columns; cols not needed)
  credit_map                        [[regex, value], ...]: CREDIT text -> "9%" / "4% (bond)" (first match wins)
Supported files: xlsx/xlsm, xls, csv, pdf (pdfplumber tables), ArcGIS REST query JSON (f=json).
Usage: python tools/parse_state_lihtc.py tools/state_lihtc_sources.json --src-dir ../hud_src/lihtc/states --out-dir ../hud_src/lihtc/states [ST ...]
Writes <out-dir>/<st>_lihtc.json per state (all of that state's sources combined).
"""
import argparse
import collections
import csv
import json
import os
import re

STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
             "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI".split())


def txt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def num(v):
    if isinstance(v, (int, float)):
        return v
    s = re.sub(r"[,$\s]", "", txt(v))
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def yr(v):
    if hasattr(v, "year"):
        return str(v.year)
    if isinstance(v, (int, float)) and v > 1e11:  # ArcGIS epoch milliseconds
        import datetime as dt
        return str(dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc).year)
    m = re.search(r"\b(19[89]\d|20[0-3]\d)\b", txt(v))
    return m.group(1) if m else None


def table_rows(path, sheets):
    """Yield (sheet_name, [row tuples]) for each table in the file."""
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "csv":
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            yield "", [tuple(r) for r in csv.reader(f)]
    elif ext == "xlsx" or ext == "xlsm":
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for name in wb.sheetnames if sheets in (None, "*") else sheets:
            ws = wb[name]
            ws.reset_dimensions()
            yield name, [tuple(r) for r in ws.iter_rows(values_only=True)]
    elif ext == "xls":
        import xlrd
        wb = xlrd.open_workbook(path)
        for name in wb.sheet_names() if sheets in (None, "*") else sheets:
            ws = wb.sheet_by_name(name)
            yield name, [tuple(ws.row_values(i)) for i in range(ws.nrows)]
    elif ext == "json":
        d = json.load(open(path, encoding="utf-8"))
        A = [f["attributes"] for f in d["features"]]
        keys = list(A[0]) if A else []
        yield "", [tuple(keys)] + [tuple(None if a.get(k) == "NULL" else a.get(k) for k in keys) for a in A]
    elif ext == "pdf":
        import pdfplumber
        rows = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for t in page.extract_tables():
                    rows.extend(tuple(c for c in r) for r in t)
        yield "", rows
    else:
        raise ValueError(f"unsupported file type: {path}")


def split_addr(a, st):
    """'123 Main St, Springfield, IL 62701' -> (street, city, zip)."""
    m = re.match(rf"^(.*?),\s*([^,]+?),?\s+{st}\.?\s*(\d{{5}})?(?:-\d{{4}})?\s*$", a, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip(), m.group(3) or ""
    m = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", a)
    return (a[:m.start()].rstrip(" ,"), "", m.group(1)) if m else (a, "", "")


def parse_source(src, src_dir):
    path = os.path.join(src_dir, src["file"])
    if src.get("csv_std"):  # tools/state_pdf/<st>.py output: standard columns, source label/URL per row
        out = []
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if not (r.get("PROJECT") or "").strip():
                    continue
                cr = (r.get("CREDIT") or "").strip() or None
                out.append({"HUD_ID": None, "STATE_ID": (r.get("STATE_ID") or "").strip() or None, "PROJECT": txt(r["PROJECT"]),
                            "PROJ_ADD": txt(r.get("PROJ_ADD")), "PROJ_CTY": txt(r.get("PROJ_CTY")), "PROJ_ST": src["st"],
                            "PROJ_ZIP": (re.search(r"\d{5}", r.get("PROJ_ZIP") or "") or [""])[0], "YR_ALLOC": yr(r.get("YR_ALLOC")),
                            "YR_PIS": None, "CREDIT": cr, "TYPE": None, "BOND": "1" if cr and cr.startswith("4") else None,
                            "ALLOCAMT": num(r.get("ALLOCAMT")), "N_UNITS": num(r.get("N_UNITS")), "LI_UNITS": num(r.get("LI_UNITS")),
                            "COMPANY": txt(r.get("COMPANY")) or None, "LAT": None, "LON": None,
                            "_src": txt(r.get("SRC_LABEL")) or src["label"], "_url": txt(r.get("SRC_URL")) or src["page"]})
                la, lo = num(r.get("LAT")), num(r.get("LON"))
                if isinstance(la, (int, float)) and isinstance(lo, (int, float)) and 17 < la < 72 and -180 < lo < -60:
                    out[-1].update(LAT=round(la, 6), LON=round(lo, 6), GEO="state")
        return out, collections.Counter()
    cols = {k: re.compile(v, re.I) for k, v in src["cols"].items()}
    skip = re.compile(src.get("skip") or r"^(total|subtotal|grand total|\d{4} total)\b", re.I)
    out, stats = [], collections.Counter()
    for sheet, rows in table_rows(path, src.get("sheets", "*")):
        hdr_i, idx = None, {}
        for i, r in enumerate(rows[:src.get("header_rows", 15)]):
            cells = [txt(c) for c in r]
            if any(cols["PROJECT"].search(c) for c in cells if c):
                hdr_i = i
                for k, rx in cols.items():
                    j = next((j for j, c in enumerate(cells) if c and rx.search(c)), None)
                    if j is not None:
                        idx[k] = j
                break
        if hdr_i is None:
            stats["sheets without a header"] += 1
            continue
        sheet_year = yr(sheet) if src.get("year_from_sheet") else None
        hdr = [txt(c) for c in rows[hdr_i]]
        hcol = lambda rx: [j for j, c in enumerate(hdr) if c and re.search(rx, c, re.I)][:1]
        drop = [(hcol(h), re.compile(v, re.I)) for h, v in src.get("drop", {}).items()]
        req = [j for h in src.get("require_any", []) for j in hcol(h)]
        yf = hcol(src["year_fallback"]) if src.get("year_fallback") else []
        cmap = [(re.compile(rx, re.I), v) for rx, v in src.get("credit_map", [])]
        for r in rows[hdr_i + 1:]:
            g = lambda k: r[idx[k]] if k in idx and idx[k] < len(r) else None
            name = txt(g("PROJECT"))
            if not name or skip.search(name) or cols["PROJECT"].search(name):
                stats["skipped rows"] += 1
                continue
            if any(j and j[0] < len(r) and rx.search(txt(r[j[0]])) for j, rx in drop):
                stats["dropped (status)"] += 1
                continue
            if req and not any(j < len(r) and (num(r[j]) or 0) > 0 for j in req):
                stats["dropped (no LIHTC)"] += 1
                continue
            rec = {"HUD_ID": None, "STATE_ID": txt(g("STATE_ID")) or None, "PROJECT": name,
                   "PROJ_ADD": txt(g("PROJ_ADD")), "PROJ_CTY": txt(g("PROJ_CTY")), "PROJ_ST": src["st"],
                   "PROJ_ZIP": (re.search(r"\d{5}", txt(g("PROJ_ZIP"))) or [""])[0],
                   "YR_ALLOC": yr(g("YR_ALLOC")) or sheet_year or (yr(r[yf[0]]) if yf and yf[0] < len(r) else None),
                   "YR_PIS": yr(g("YR_PIS")),
                   "CREDIT": txt(g("CREDIT")) or None, "TYPE": txt(g("TYPE")) or None, "BOND": txt(g("BOND")) or None,
                   "ALLOCAMT": num(g("ALLOCAMT")), "N_UNITS": num(g("N_UNITS")), "LI_UNITS": num(g("LI_UNITS")),
                   "COMPANY": txt(g("COMPANY")) or None, "LAT": None, "LON": None,
                   "_src": src["label"], "_url": src["page"]}
            for k, v in src.get("const", {}).items():
                if not rec.get(k):
                    rec[k] = v
            lat, lon = num(g("LAT")), num(g("LON"))
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and 17 < lat < 72 and -180 < lon < -60:
                rec["LAT"], rec["LON"], rec["GEO"] = round(lat, 6), round(lon, 6), "state"
            if rec["PROJ_ADD"]:
                a, c, z = split_addr(rec["PROJ_ADD"], src["st"])
                rec["PROJ_ADD"] = a
                rec["PROJ_CTY"] = rec["PROJ_CTY"] or c
                rec["PROJ_ZIP"] = rec["PROJ_ZIP"] or z
            if cmap and rec["CREDIT"]:
                rec["CREDIT"] = next((v for rx, v in cmap if rx.search(rec["CREDIT"])), rec["CREDIT"])
            c = (rec["CREDIT"] or "").lower()
            if c:
                rec["CREDIT"] = "4% (bond)" if re.search(r"(?<![\d.])(4\s*%|0?\.04\b)|bond|tax.?exempt|\bteb\b|non-?capped", c)                     else "9%" if re.search(r"(?<![\d.])(9\s*%|0?\.09\b)|competitive", c) else rec["CREDIT"]
                if rec["CREDIT"] == "4% (bond)":
                    rec["BOND"] = "1"
            if not rec["YR_ALLOC"] and not rec["YR_PIS"]:
                stats["no year"] += 1
            out.append(rec)
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("states", nargs="*")
    ap.add_argument("--src-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    by_st = collections.defaultdict(list)
    for src in cfg["sources"]:
        if not a.states or src["st"] in a.states:
            by_st[src["st"]].append(src)
    for st, srcs in sorted(by_st.items()):
        rows, meta, seen = [], [], set()
        for src in srcs:
            r, stats = parse_source(src, a.src_dir)
            n0 = len(r)
            r = [x for x in r if not x["PROJECT"].startswith("*")]  # a footnote under the table, not a project
            if len(r) < n0:
                stats["footnotes"] = n0 - len(r)
            k0 = len(r)
            # the same award listed in two files (e.g. a 5-year file and a historical file) is kept once
            r = [x for x in r if (k := (x["PROJECT"].upper(), x["PROJ_ADD"].upper(), x["YR_ALLOC"], x["CREDIT"])) not in seen and not seen.add(k)]
            if len(r) < k0:
                stats["duplicates of earlier files"] = k0 - len(r)
            rows += r
            meta.append({"label": src["label"], "url": src["url"], "page": src["page"], "fetched": src["fetched"], "rows": len(r)})
            print(f"{st} {src['file']}: {len(r)} rows; addr {sum(1 for x in r if x['PROJ_ADD'])}, zip {sum(1 for x in r if x['PROJ_ZIP'])}, "
                  f"year {sum(1 for x in r if x['YR_ALLOC'])}, units {sum(1 for x in r if x['N_UNITS'])} {dict(stats)}")
        json.dump({"source": "; ".join(m["url"] for m in meta), "page": srcs[0]["page"],
                   "fetched": max(m["fetched"] for m in meta), "sources": meta, "rows": rows},
                  open(os.path.join(a.out_dir, f"{st.lower()}_lihtc.json"), "w", encoding="utf-8"))


if __name__ == "__main__":
    main()

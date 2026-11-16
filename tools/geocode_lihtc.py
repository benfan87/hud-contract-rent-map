"""Geocode state LIHTC award-list rows that have a street address but no coordinates, with the U.S. Census
Bureau batch geocoder (free, public, no key: https://geocoding.geo.census.gov/geocoder/).

Rows get LAT/LON plus GEO = "census" (and PROJ_ZIP from the matched address when the list has none).
Results are cached in --cache, so reruns only send new addresses. The files are updated in place.
Usage: python tools/geocode_lihtc.py <state_lihtc.json> [...] [--cache ../hud_src/lihtc/geocode_cache.json]
"""
import argparse
import csv
import io
import json
import os
import re
import subprocess
import tempfile
import time

URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BATCH = 1000


def key(r):
    a = re.sub(r"\s+", " ", (r.get("PROJ_ADD") or "")).strip()
    if not re.search(r"\d", a):
        return None  # no street number: "Scattered sites", "TBD", a corner description...
    return "|".join([a.upper(), (r.get("PROJ_CTY") or "").upper().strip(), (r.get("PROJ_ST") or "").upper(),
                     (r.get("PROJ_ZIP") or "")[:5]])


def first_addr(a):
    # "123 Main St & 456 Oak Ave" / "123-131 Main St" / "123 Main St; Scattered" -> the first plain address
    a = re.split(r"\s*(?:&|;|/|\band\b|\(|,\s*(?=\d))\s*", a, maxsplit=1)[0]
    return re.sub(r"^(\d+)\s*-\s*\d+\b", r"\1", a).strip()


def run_batch(items):
    buf = io.StringIO()
    w = csv.writer(buf)
    for i, k in items:
        a, c, s, z = k.split("|")
        w.writerow([i, first_addr(a), c, s, z])
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
        path = f.name
    try:
        for attempt in range(3):
            p = subprocess.run(["curl", "-s", "-m", "600", "-F", f"addressFile=@{path}", "-F",
                                "benchmark=Public_AR_Current", URL], capture_output=True, text=True, encoding="utf-8")
            if p.returncode == 0 and p.stdout.strip():
                return list(csv.reader(io.StringIO(p.stdout)))
            time.sleep(10 * (attempt + 1))
        raise RuntimeError(f"Census geocoder failed: {p.returncode} {p.stderr[:200]}")
    finally:
        os.unlink(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--cache", default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "hud_src", "lihtc", "geocode_cache.json"))
    a = ap.parse_args()
    cache = json.load(open(a.cache, encoding="utf-8")) if os.path.exists(a.cache) else {}
    docs = [(f, json.load(open(f, encoding="utf-8"))) for f in a.files]
    todo = sorted({k for _, d in docs for r in d["rows"] if r.get("LAT") is None and (k := key(r)) and k not in cache})
    print(f"{len(todo)} new addresses to geocode ({len(cache)} cached)")
    for s in range(0, len(todo), BATCH):
        chunk = list(enumerate(todo[s:s + BATCH]))
        got = {}
        for row in run_batch(chunk):
            if len(row) >= 6 and row[2] == "Match":
                lon, lat = map(float, row[5].split(","))
                z = re.search(r"(\d{5})\s*$", row[4])
                got[int(row[0])] = [round(lat, 6), round(lon, 6), z.group(1) if z else None, row[3]]
        for i, k in chunk:
            cache[k] = got.get(i)  # None = no match (kept so it isn't retried)
        json.dump(cache, open(a.cache, "w", encoding="utf-8"))
        print(f"  {s + len(chunk)}/{len(todo)}: {len(got)} of {len(chunk)} matched")
    for f, d in docs:
        n = m = 0
        for r in d["rows"]:
            if r.get("LAT") is not None:
                continue
            k = key(r)
            if not k:
                continue
            n += 1
            g = cache.get(k)
            if g:
                m += 1
                r["LAT"], r["LON"], r["GEO"] = g[0], g[1], "census"
                if not r.get("PROJ_ZIP") and g[2]:
                    r["PROJ_ZIP"] = g[2]
        json.dump(d, open(f, "w", encoding="utf-8"))
        print(f"{os.path.basename(f)}: {m} of {n} addressed rows geocoded; {len(d['rows']) - n} rows without a street address")


if __name__ == "__main__":
    main()

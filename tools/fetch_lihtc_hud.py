"""Download HUD's LIHTC property layer (HUD eGIS, ArcGIS FeatureServer) to JSON.
Usage: python tools/fetch_lihtc_hud.py <out.json>"""
import json, sys, time, urllib.parse, urllib.request
URL = "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/LIHTC/FeatureServer/0"
FIELDS = ["OBJECTID", "HUD_ID", "PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ST", "PROJ_ZIP", "STATE_ID", "COMPANY",
          "ALLOCAMT", "N_UNITS", "LI_UNITS", "YR_PIS", "YR_ALLOC", "NON_PROF", "BOND", "MFF_RA", "FMHA_515", "FHA",
          "HOME", "RENTASSIST", "TYPE", "CREDIT", "NONPROG", "DATANOTE", "LAT", "LON", "STD_ADDR", "STD_CITY",
          "STD_ST", "STD_ZIP5", "QCT", "DDA"]
def get(params):
    q = urllib.parse.urlencode(params)
    for i in range(4):
        try:
            return json.load(urllib.request.urlopen(f"{URL}/query?{q}", timeout=120))
        except Exception:
            time.sleep(3 * (i + 1))
    raise SystemExit("query failed")
meta = json.load(urllib.request.urlopen(f"{URL}?f=json"))
ids = sorted(get({"where": "1=1", "returnIdsOnly": "true", "f": "json"})["objectIds"])
rows = []
for i in range(0, len(ids), 1000):
    chunk = ids[i:i + 1000]
    d = get({"where": f"OBJECTID>={chunk[0]} AND OBJECTID<={chunk[-1]}", "outFields": ",".join(FIELDS),
             "returnGeometry": "false", "f": "json"})
    rows += [f["attributes"] for f in d["features"]]
json.dump({"source": URL, "layer_modified": meta.get("editingInfo", {}).get("lastEditDate"),
           "fetched": time.strftime("%Y-%m-%d"), "rows": rows}, open(sys.argv[1], "w", encoding="utf-8"))
print(len(ids), "ids;", len(rows), "rows; lastEditDate", meta.get("editingInfo", {}).get("lastEditDate"))

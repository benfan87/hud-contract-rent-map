"""Add matched LIHTC records (tools/match_lihtc.py output) to assets/hud_data.js.

Writes:
  H.LI  one row per LIHTC record: see meta.lihtc.li_cols
  H.PL  one row per matched property: see meta.lihtc.pl_cols
Summary rules (high/medium matches only; "possible" matches are listed but not used):
  Year 15        latest PIS + 14. If the latest allocation is newer than the latest PIS (a later deal whose PIS
                 isn't published yet), allocation + 16 instead (PIS is usually 1-3 years after allocation), marked est.
  Resyndication  a later allocation at least 5 years after the property's earlier allocation/PIS years
                 (HUD and state lists often record the same deal a year apart, so smaller gaps are ignored).
Usage: python tools/merge_lihtc.py <matches.json>
"""
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "hud_data.js"
HUD_CREDIT = {"1": "4% (30% PV)", "2": "9% (70% PV)", "3": "4% and 9%", "4": "TCEP only"}
HUD_TYPE = {"1": "New construction", "2": "Acquisition & rehab", "3": "New construction & A/R", "4": "Existing"}
TIER = {"high": 0, "medium": 1, "low": 2}
LI_COLS = ["project", "addr", "city", "st", "zip", "id", "hudId", "alloc", "pis", "credit", "bond", "type", "units",
           "liUnits", "src", "company"]
PL_COLS = ["p", "links [[li, tier, why]]", "bestTier", "lastAlloc", "lastPis", "y15", "y15est", "resynd", "firstYear"]


def main():
    mt = json.load(open(sys.argv[1], encoding="utf-8"))
    s = DATA.read_text(encoding="utf-8")
    d = json.loads(s[s.index("=") + 1:].rstrip().rstrip(";"))
    P, D, meta = d["P"], d["dict"], d["meta"]
    pidx = {p[0]: i for i, p in enumerate(P)}
    D["lsrc"], D["lsrcUrl"] = [], []
    LI, key2i, PL = [], {}, []

    def src(label, url):
        if label not in D["lsrc"]:
            D["lsrc"].append(label)
            D["lsrcUrl"].append(url)
        return D["lsrc"].index(label)

    for pid, ms in mt["matches"].items():
        links = []
        for m in ms:
            k = (m["source"], m["hud_id"], m["state_id"], m["project"], m["addr"])
            if k not in key2i:
                hud = m["source"].startswith("HUD")
                bond = m["bond"]
                key2i[k] = len(LI)
                LI.append([m["project"], m["addr"], m["city"], m["st"], (m["zip"] or "")[:5],
                           m["state_id"] or m["hud_id"], m["hud_id"], m["yr_alloc"], m["yr_pis"],
                           HUD_CREDIT.get(m["credit"], m["credit"]) if hud else m["credit"],
                           1 if bond in ("1", 1) else 0 if bond in ("2", 2) else None,
                           HUD_TYPE.get(m["type"], m["type"]) if hud else (m["type"] or None),
                           m["units"], m["li_units"], src(m["source"], m["url"]), m["company"] or None])
            links.append([key2i[k], TIER[m["tier"]], m["why"]])
        good = [LI[i] for i, t, _ in links if t < 2]
        allocs = sorted({r[7] for r in good if r[7]})
        piss = sorted({r[8] for r in good if r[8]})
        last_a, last_p = (allocs[-1] if allocs else None), (piss[-1] if piss else None)
        if last_p and (last_a is None or last_a <= last_p + 1):
            y15, est = last_p + 14, 0
        elif last_a:
            y15, est = last_a + 16, 1
        else:
            y15, est = None, 0
        years = sorted(set(allocs) | {y - 1 for y in piss})
        resynd = None
        for a, b in zip(years, years[1:]):
            if b - a >= 5:
                resynd = b
        PL.append([pidx[pid], links, min(t for _, t, _ in links), last_a, last_p, y15, est, resynd,
                   years[0] if years else None])

    d["LI"], d["PL"] = LI, PL
    meta["lihtc"] = {"li_cols": LI_COLS, "pl_cols": PL_COLS, "sources": mt["sources"],
                     "built": dt.date.today().isoformat(), "records": len(LI), "properties": len(PL),
                     "by_tier": {t: sum(1 for r in PL if r[2] == i) for t, i in TIER.items()},
                     "resyndicated": sum(1 for r in PL if r[7]), "rules": __doc__.split("Usage:")[0].strip()}
    DATA.write_text("window.HUD_DATA=" + json.dumps(d, separators=(",", ":"), ensure_ascii=False) + ";",
                    encoding="utf-8")
    print({k: v for k, v in meta["lihtc"].items() if k not in ("rules", "li_cols", "pl_cols")})


if __name__ == "__main__":
    main()

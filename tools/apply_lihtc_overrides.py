"""Apply tools/lihtc_link_overrides.json to the built data in place (no need to rerun the full LIHTC match):
  assets/hud_data.js   rejected links -> tier 2 ("possible", not used) with the reason; that property's LIHTC
                       summary (bestTier, lastAlloc, lastPis, y15, y15est, resynd, firstYear) is recomputed with the
                       tools/merge_lihtc.py rules
  assets/lihtc_all.js  "lihtc_only" projects are added as LIHTC-only projects (records taken from hud_data.js)
Idempotent. A full rebuild (match_lihtc.py -> merge_lihtc.py -> build_lihtc_all.py) applies the same overrides itself.
Then run tools/build_screener_layers.py.
Usage: python tools/apply_lihtc_overrides.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lihtc_overrides import lihtc_only, rec_ids, rejected  # noqa: E402
from build_lihtc_all import title  # noqa: E402

TIER = {"high": 0, "medium": 1, "low": 2}


def load(path):
    s = path.read_text(encoding="utf-8")
    i = s.index("=")
    return s[:i + 1], json.loads(s[i + 1:].rstrip().rstrip(";"))


def save(path, pre, d):
    path.write_text(pre + json.dumps(d, separators=(",", ":"), ensure_ascii=False) + ";", encoding="utf-8")


def summary(recs):  # tools/merge_lihtc.py rules; recs = LI rows of the high/medium links
    allocs = sorted({r[7] for r in recs if r[7]})
    piss = sorted({r[8] for r in recs if r[8]})
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
    return [last_a, last_p, y15, est, resynd, years[0] if years else None]


def main():
    hpath, xpath = ROOT / "assets" / "hud_data.js", ROOT / "assets" / "lihtc_all.js"
    hpre, H = load(hpath)
    P, LI = H["P"], H["LI"]
    changed = []
    for pl in H["PL"]:
        pid = P[pl[0]][0]
        rej = rejected(pid)
        if not rej:
            continue
        for link in pl[1]:
            r = LI[link[0]]
            hit = next((rej[i] for i in rec_ids(r[5], r[6]) if i in rej), None)
            if hit and link[1] < 2:
                link[1], link[2] = 2, f"rejected on manual review: {hit}; {link[2]}"
                changed.append((pid, P[pl[0]][1], r[0], r[5]))
        pl[2] = min(t for _, t, _ in pl[1])
        pl[3:9] = summary([LI[i] for i, t, _ in pl[1] if t < 2])
    m = H["meta"]["lihtc"]
    m["by_tier"] = {t: sum(1 for r in H["PL"] if r[2] == i) for t, i in TIER.items()}
    m["overrides"] = "tools/lihtc_link_overrides.json (applied by tools/apply_lihtc_overrides.py)"
    save(hpath, hpre, H)
    for c in changed:
        print("rejected link:", c)

    # LIHTC-only projects freed by a rejected link
    xpre, X = load(xpath)
    have = {p[0] for p in X["P"]}
    lsrc_h = H["dict"]["lsrc"]
    added = 0
    for o in lihtc_only():
        if o["id"] in have:
            continue
        ids = set(o["record_ids"])
        recs = [r for r in LI if rec_ids(r[5], r[6]) & ids]
        assert recs, o["id"]
        recs.sort(key=lambda r: (r[7] or (r[8] or 0) - 1, r[8] or 0))
        hud = [r for r in recs if lsrc_h[r[14]].startswith("HUD")]
        lead = (hud or recs)[-1]
        name, addr, city, st, z = title(lead[0]), lead[1], title(lead[2]), lead[3], o.get("zip") or lead[4]

        def code(tab, v):
            if v is None:
                return None
            if v not in tab:
                tab.append(v)
            return tab.index(v)

        def src(i):
            lab = lsrc_h[i]
            j = next((k for k, s in enumerate(X["lsrc"]) if s[0] == lab), None)
            if j is None:
                X["lsrc"].append([lab, H["dict"]["lsrcUrl"][i]])
                j = len(X["lsrc"]) - 1
            return j

        for r in recs:
            X["LI"].append([None if title(r[0]) == name else title(r[0]), None if r[1] == addr else r[1],
                            None if title(r[2]) == city else title(r[2]), None if r[3] == st else r[3],
                            None if (r[4] or None) == z else r[4], r[5], None if r[6] == r[5] else r[6], r[7], r[8],
                            code(X["cr"], r[9]), r[10], code(X["ty"], r[11]), r[12], r[13], src(r[14]), r[15]])
        units = max([r[12] or 0 for r in recs]) or None
        j = len(X["P"])
        X["P"].append([o["id"], name, addr, city, st, z, o["lat"], o["lon"], o["loc"], units, len(recs)] + summary(recs))
        X["F"].append(o.get("flags", 0))
        if o.get("qct2027"):
            X["zq"].append(j)
        if o.get("dda2027"):
            X["zd"].append(j)
        mx = X["meta"]
        mx["records_on_hud_properties"] -= len(recs)
        mx["records_added"] += len(recs)
        mx["projects"] += 1
        mx["located_lihtc" if o["loc"] == "L" else "located_census" if o["loc"] == "G" else "located_zip"] += 1
        mx["overrides"] = "tools/lihtc_link_overrides.json (applied by tools/apply_lihtc_overrides.py)"
        added += 1
        print("added LIHTC-only project:", X["P"][-1])
    if added:
        save(xpath, xpre, X)
    print(f"{len(changed)} links rejected, {added} LIHTC-only projects added")


if __name__ == "__main__":
    main()

"""Utah Housing Corp. (UHC) federal & state housing credit award summaries -> extracted/ut.csv.

Each UHC PDF is one credit year ("Summary of Federal and State Housing Credit Awards"), laid out as 4-line project
cards in columns: Applicant | Name / Location | General Data | Eligible Category | Credits | Comments.
Sections kept:
  COMPETITIVE FEDERAL TAX CREDIT AWARDS              -> CREDIT 9%, ALLOCAMT = federal credit (FTC)
  STATE OF UTAH TAX CREDIT AWARD(S) / REQUESTS,
  STAND ALONE STATE OF UTAH TAX CREDIT AWARDS        -> state-credit (STC) awards; a project already in the 9% section of
                                                        the same file is not repeated. Others: CREDIT 4% (bond) when the
                                                        card says "Bond Project: Yes", else blank (bond status not shown); state-credit-only (non-bond) awards are dropped.
Sections dropped: PROJECTS NOT RECEIVING FEDERAL HOUSING CREDITS / ... STATE TAX CREDITS, and all Total lines.
YR_ALLOC = the file's credit year (UHC awards credits a year ahead, e.g. the 2025 file = June 2024 round).

Usage (from the repo root): python tools/state_pdf/ut.py --out ../hud_src/lihtc/states/extracted
"""
import argparse
import csv
import os
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pdfplumber

COLS = ["PROJECT", "PROJ_ADD", "PROJ_CTY", "PROJ_ZIP", "YR_ALLOC", "CREDIT", "N_UNITS", "LI_UNITS", "COMPANY",
        "ALLOCAMT", "STATE_ID", "SRC_LABEL", "SRC_URL"]

BASE = "https://utahhousingcorp.org/pdf/"
# (credit year, file name, label detail)
FILES = [
    (2020, "federal_and_state_credit_awards_2020.pdf", "credit year 2020"),
    (2021, "federal_and_state_credit_awards_2021.pdf", "credit year 2021"),
    (2021, "disaster_round_credit_awards_2021.pdf", "2021 disaster-credit round"),
    (2022, "federal_and_state_credit_awards_2022.pdf", "credit year 2022"),
    (2023, "federal_and_state_credit_awards_2023.pdf", "credit year 2023; June 2022 round"),
    (2024, "federal_and_state_credit_awards_2024.pdf", "credit year 2024; September 2023 round"),
    (2025, "federal_and_state_credit_awards_2025.pdf", "credit year 2025; June 2024 round awarded 9/5/2024"),
    (2026, "2026_Credit_Awards.pdf", "credit year 2026; April 2025 round awarded 7/31/2025"),
    (2027, "2027_Federal___State_Credit_Awards.pdf", "credit year 2027; June 2026 round awarded 9/24/2026"),
]


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


SEC_RX = [
    (re.compile(r"PROJECTS NOT RECEIVING"), "drop"),
    (re.compile(r"COMPETITIVE FEDERAL TAX CREDIT AWARDS"), "fed"),
    (re.compile(r"STATE OF UTAH TAX CREDIT"), "state"),  # also matches "STAND ALONE STATE OF UTAH ..."
]
GEN_RX = re.compile(r"^(Affordable|Market:|Bldgs?\b)|Bldg|^\d+-\d+-\d+")
HDR_RX = re.compile(r"^((Applicant Name|Eligible|Category|Requested|Awarded|CREDITS|Credits|Comments|Project Description"
                    r"|General Data|Name / Location)\s*)+$")
TITLE_RX = re.compile(r"Utah\s+Low-Income|Summary\s+of\s+Federal|\bRound\b|^\d{4}$|^Applicant Name")
CITY_RX = re.compile(r"^(?P<city>.*?),?\s*(UT|Utah)\b\.?\s*(?P<zip>\d{5}(-\d{4})?)?\s*$")


def lines_of(page):
    """Group words into lines by 'top' (words within 2.5pt share a line)."""
    ws = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
    out = []
    for w in ws:
        if out and abs(w["top"] - out[-1][0]) <= 2.5:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [(t, sorted(l, key=lambda w: w["x0"])) for t, l in out]


def txt(ws):
    return " ".join(w["text"] for w in ws).strip()


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_pdf(path):
    """Return list of card dicts: section, company, segs (name-column lines), general text, credit text."""
    pdf = pdfplumber.open(path)
    cards, sec, cur = [], None, None
    pages = [(pg.page_number, lines_of(pg)) for pg in pdf.pages]
    # column x positions (file-wide): general-data column starts a bit left of the "Affordable:" words; the name
    # column is the most common left edge of word runs between the applicant and general-data columns
    G = min(w["x0"] for _, ls in pages for t, ws in ls for w in ws if w["text"].startswith("Affordable:") and w["x0"] > 300) - 12
    xs = Counter()
    for _, ls in pages:
        for t, ws in ls:
            mid = [w for w in ws if 150 < w["x0"] < G - 40]
            if mid:
                xs[round(mid[0]["x0"])] += 1
    N = xs.most_common(1)[0][0] - 3
    for pno, lines in pages:
        # skip the running page header (title, round, column headings); a card cut by the page break continues below it
        k = 0
        while k < len(lines) and (HDR_RX.match(txt(lines[k][1])) or TITLE_RX.search(txt(lines[k][1]))):
            k += 1
        for t, ws in lines[k:]:
            s = txt(ws)
            hit = next((v for rx, v in SEC_RX if rx.search(s)), None)
            if hit:
                sec, cur = hit, None
                continue
            if s.startswith("Total ") or " Total " in s or re.match(r"^(General Data\*|Unit Types|SRO/Studio)", s):
                cur = None
                if re.match(r"^(General Data\*|Unit Types|SRO/Studio)", s):
                    sec = None
                continue
            if sec is None or HDR_RX.match(s):
                continue
            app = [w for w in ws if w["x0"] < N]
            rest = [w for w in ws if w["x0"] >= N]
            # split rest into name column and general/credit columns
            cut = len(rest)
            for i, w in enumerate(rest):
                nxt = rest[i + 1]["text"] if i + 1 < len(rest) else ""
                if w["x0"] >= G - 3 or (w["x0"] >= G - 70 and (GEN_RX.search(w["text"]) or (w["text"].isdigit() and "Bldg" in nxt))):
                    cut = i
                    break
            namec, other = rest[:cut], rest[cut:]
            is_start = any(w["text"].startswith("Affordable") for w in other)
            if is_start:
                cur = {"sec": sec, "company": txt(app), "segs": [], "gen": [], "page": pno}
                cards.append(cur)
            if cur is None:
                continue
            if namec:
                cur["segs"].append(txt(namec))
            cur["gen"].append(txt(other))
    return cards


def money(s):
    return int(s.replace("$", "").replace(",", ""))


def card_to_row(c, yr, label, url):
    segs = c["segs"]
    name = segs[0] if segs else ""
    city_i = next((i for i, s in enumerate(segs[1:], 1) if CITY_RX.match(s)), None)
    county_i = next((i for i, s in enumerate(segs[1:], 1) if re.search(r"\bCounty$", s)), None)
    if city_i is None and county_i and county_i >= 2:
        city_i = county_i - 1
    addr = " ".join(segs[1:city_i]) if city_i else (segs[1] if len(segs) > 1 else "")
    city = zp = ""
    if city_i:
        m = CITY_RX.match(segs[city_i])
        if m:
            city, zp = m.group("city").strip(" ,"), (m.group("zip") or "")[:5]
        else:
            city = segs[city_i].strip(" ,")
    if re.match(r"(?i)^scattered\s+sites?$", addr):
        addr = ""
    gen = " ".join(c["gen"])
    li = re.search(r"Affordable:\s*(\d+)", gen)
    tot = re.search(r"Bldgs?\.?/\s*(\d+)\s*Units", gen)
    ftc = re.search(r"FTC:\s*(\$[\d,]+)", gen)
    stc = re.search(r"STC:\s*(\$[\d,]+)", gen)
    plain = [m for m in re.findall(r"(?<!FTC: )(?<!STC: )(\$[\d,]+)", gen)]
    bond = re.search(r"Bond Project:\s*(Yes|No)", gen)
    if ftc or stc:
        fed = money(ftc.group(1)) if ftc else None
        st = money(stc.group(1)) if stc else None
    else:  # pre-2025 layout: one amount, federal in the 9% section and state in the state section
        amt = money(plain[0]) if plain else None
        fed, st = (amt, None) if c["sec"] == "fed" else (None, amt)
    return {"PROJECT": name, "PROJ_ADD": addr, "PROJ_CTY": city, "PROJ_ZIP": zp, "YR_ALLOC": str(yr),
            "N_UNITS": tot.group(1) if tot else "", "LI_UNITS": li.group(1) if li else "", "COMPANY": c["company"],
            "_fed": fed, "_st": st, "_bond": bond.group(1) if bond else "", "_sec": c["sec"], "_label": label,
            "SRC_URL": url, "STATE_ID": ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../hud_src/lihtc/states/extracted")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pdir = out.parent / "pdf" / "ut"
    pdir.mkdir(parents=True, exist_ok=True)
    rows, skipped = [], []
    for yr, fn, detail in FILES:
        url = BASE + fn
        dest = pdir / fn
        err = download(url, dest)
        if err:
            skipped.append((url, err))
            print(f"SKIP {url}: {err}", file=sys.stderr)
            continue
        cards = parse_pdf(dest)
        recs = [card_to_row(c, yr, detail, url) for c in cards if c["sec"] in ("fed", "state")]
        fed_names = {norm(r["PROJECT"]) for r in recs if r["_sec"] == "fed"}
        fed_names |= {norm(r["PROJ_ADD"] + r["PROJ_CTY"]) for r in recs if r["_sec"] == "fed" and r["PROJ_ADD"]}
        base = f"Utah Housing Corp. {yr} federal & state credit awards ({detail}; YR_ALLOC = credit year)"
        n = Counter()
        for r in recs:
            if r["_sec"] == "fed":
                if not r["_fed"]:
                    continue  # no federal credit shown: not an award
                r["CREDIT"], r["ALLOCAMT"] = "9%", str(r["_fed"])
                r["SRC_LABEL"] = base + " - competitive 9% federal award" + (f" (+ state credit ${r['_st']:,})" if r["_st"] else "")
            else:
                if norm(r["PROJECT"]) in fed_names or norm(r["PROJ_ADD"] + r["PROJ_CTY"]) in fed_names or not r["_st"]:
                    continue  # state credit on a 9% deal already listed, or $0 state award
                if r["_bond"] == "No":
                    continue  # Utah state credit only, no federal LIHTC
                r["CREDIT"] = "4% (bond)" if r["_bond"] == "Yes" else ""
                r["ALLOCAMT"] = ""
                kind = "state credit to a 4% bond project" if r["_bond"] == "Yes" else (
                    "state credit only, not a bond project" if r["_bond"] == "No" else "state credit award (bond status not shown)")
                r["SRC_LABEL"] = base + f" - {kind} (state credit ${r['_st']:,}" + (
                    "; federal 4% amount not listed)" if r["_bond"] == "Yes" else ")")
            n[r["CREDIT"] or "blank"] += 1
            rows.append({k: r.get(k, "") for k in COLS})
        print(f"{fn}: {len(cards)} cards, kept {sum(n.values())} {dict(n)}")
    with open(out / "ut.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out / 'ut.csv'}")
    for u, e in skipped:
        print(f"skipped {u}: {e}")


if __name__ == "__main__":
    main()

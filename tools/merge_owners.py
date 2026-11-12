"""Add owner and management-agent contacts, and sponsor groups, to assets/hud_data.js.

Input (HUD, public): MF-Properties-with-Assistance-Sec8-Contracts1.xlsx
    https://www.hud.gov/hud-partners/multifamily-assist-section8-database

Writes:
  H.OW            one row per property: [p, owner idx into dict.own, agent idx into dict.mga]
  H.dict.own      [participant id, name, company type, address, city, st, zip, phone, email, sponsor idx]
  H.dict.mga      [participant id, name, company type, address, city, st, zip, phone, email]
  H.dict.spon     [label, kind, owner-entity count, property count]
  meta.owners
Sponsor groups: owner entities are usually single-asset LLCs/LPs. Entities are grouped by their owner-contact email
domain when it is an organization's (free and ISP mail domains are ignored), otherwise by owner mailing
address. This is a lead for who controls the owner, not proof: the contact can be a sponsor, an accountant or
a management company, so confirm with state entity records.

Usage: python tools/merge_owners.py <folder with the xlsx>
"""
import collections
import datetime as dt
import json
import pathlib
import re
import sys

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "hud_data.js"
FILE = "MF-Properties-with-Assistance-Sec8-Contracts1.xlsx"
FREE_MAIL = set("""gmail.com yahoo.com aol.com hotmail.com outlook.com live.com msn.com icloud.com me.com mac.com ymail.com
mail.com protonmail.com comcast.net att.net sbcglobal.net bellsouth.net cox.net verizon.net charter.net earthlink.net juno.com
q.com frontier.com frontiernet.net windstream.net centurylink.net centurytel.net embarqmail.com rr.com optonline.net
optimum.net netzero.net netzero.com prodigy.net suddenlink.net mchsi.com twc.com roadrunner.com tds.net knology.net
rocketmail.com aim.com gmx.com zoho.com cableone.net wowway.com ptd.net epix.net hughes.net""".split())
ADDR_NORM = [(r"\bSTREET\b", "ST"), (r"\bAVENUE\b", "AVE"), (r"\bSUITE\b", "STE"), (r"\bROAD\b", "RD"),
             (r"\bDRIVE\b", "DR"), (r"\bBOULEVARD\b", "BLVD"), (r"\bNORTH\b", "N"), (r"\bSOUTH\b", "S"),
             (r"\bEAST\b", "E"), (r"\bWEST\b", "W"), (r"[.,#]", " "), (r"\s+", " ")]


def s(v):
    v = str(v).strip() if v is not None else ""
    return "" if v in ("None",) else v


def addr_key(line, city, st):
    a = line.upper()
    if not a:
        return None
    for pat, rep in ADDR_NORM:
        a = re.sub(pat, rep, a)
    return f"{a.strip()}|{city.upper().strip()}|{st.upper().strip()}"


def main():
    folder = pathlib.Path(sys.argv[1])
    wb = openpyxl.load_workbook(folder / FILE, read_only=True)
    ws = wb.active
    ws.reset_dimensions()  # HUD's files report a wrong sheet size
    it = ws.iter_rows(values_only=True)
    hdr = [s(h) for h in next(it)]
    rows = {}
    for r in it:
        r = dict(zip(hdr, r))
        if r.get("property_id"):
            rows[str(int(r["property_id"]))] = r

    txt = DATA.read_text(encoding="utf-8")
    d = json.loads(txt[txt.index("=") + 1:].rstrip().rstrip(";"))
    P, D = d["P"], d["dict"]
    pidx = {p[0]: i for i, p in enumerate(P)}

    def person(r, pre, org, full, extra):
        name = s(r.get(org)) or s(r.get(full))
        return [s(r.get(pre + "participant_id")).split(".")[0], name, s(r.get(pre + "company_type")),
                " ".join(x for x in (s(r.get(extra[0])), s(r.get(extra[1]))) if x), s(r.get(extra[2])),
                s(r.get(extra[3])), s(r.get(extra[4]))[:5], s(r.get(extra[5])), s(r.get(extra[6])).lower()]

    own, mga, oi, mi, OW = [], [], {}, {}, []
    for pid, r in rows.items():
        if pid not in pidx:
            continue
        o = person(r, "owner_", "owner_organization_name", "owner_individual_full_name",
                   ["owner_address_line1", "owner_address_line2", "owner_city_name", "owner_state_code",
                    "owner_zip_code", "owner_main_phone_number_text", "owner_contact_email_text"])
        m = person(r, "mgmt_agent_", "mgmt_agent_org_name", "mgmt_agent_full_name",
                   ["mgmt_agent_address_line1", "mgmt_agent_address_line2", "mgmt_agent_city_name",
                    "mgmt_agent_state_code", "mgmt_agent_zip_code", "mgmt_agent_main_phone_number",
                    "mgmt_contact_email_text"])
        res = []
        for rec, lst, ix in ((o, own, oi), (m, mga, mi)):
            if not rec[1] and not rec[3]:
                res.append(-1)
                continue
            k = tuple(rec)
            if k not in ix:
                ix[k] = len(lst)
                lst.append(rec)
            res.append(ix[k])
        OW.append([pidx[pid], res[0], res[1]])

    # sponsor groups: one key per owner entity (org email domain, else mailing address); no chaining,
    # because linking domains through shared addresses merges unrelated owners
    keyof = []
    for o in own:
        dom = o[8].split("@")[-1] if "@" in o[8] else ""
        keyof.append("@" + dom if dom and dom not in FREE_MAIL and "." in dom else addr_key(o[3], o[4], o[5]))
    nprops = collections.Counter(r[1] for r in OW if r[1] >= 0)
    groups = collections.defaultdict(list)
    for i, k in enumerate(keyof):
        groups[k or ("#", i)].append(i)
    spon = []
    for members in groups.values():
        n_ent = len({own[i][0] or own[i][1] for i in members})
        n_p = sum(nprops[i] for i in members)
        if n_p < 2:
            for i in members:
                own[i].append(-1)
            continue
        doms = collections.Counter(own[i][8].split("@")[-1] for i in members
                                   if "@" in own[i][8] and own[i][8].split("@")[-1] not in FREE_MAIL)
        addrs = collections.Counter((own[i][3], own[i][4], own[i][5]) for i in members if own[i][3])
        if doms:
            label, kind = doms.most_common(1)[0][0], "email"
        else:
            a = addrs.most_common(1)[0][0]
            label, kind = f"{a[0]}, {a[1]} {a[2]}", "address"
        for i in members:
            own[i].append(len(spon))
        spon.append([label, kind, n_ent, n_p])

    D["own"], D["mga"], D["spon"], d["OW"] = own, mga, spon, OW
    big = sorted(spon, key=lambda x: -x[3])
    d["meta"]["owners"] = {
        "source": "https://www.hud.gov/hud-partners/multifamily-assist-section8-database", "file": FILE,
        "built": dt.date.today().isoformat(), "properties": len(OW), "owner_entities": len(own),
        "agents": len(mga), "sponsor_groups": len(spon),
        "properties_in_groups": sum(x[3] for x in spon), "rules": __doc__.split("Usage:")[0].strip(),
    }
    DATA.write_text("window.HUD_DATA=" + json.dumps(d, separators=(",", ":"), ensure_ascii=False) + ";",
                    encoding="utf-8")
    print({k: v for k, v in d["meta"]["owners"].items() if k != "rules"})
    for x in big[:25]:
        print(x)


if __name__ == "__main__":
    main()

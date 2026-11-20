"""Load tools/lihtc_link_overrides.json (manual corrections to the HUD property <-> LIHTC matching).

  rejected(pid)    {record id: reason} for links to reject on HUD property pid
  not_lihtc_ids()  record ids that are not tax-credit projects (never shown as LIHTC)
  lihtc_only()     LIHTC projects to show on their own after their (wrong) HUD link is rejected
Record ids are the LIHTC record's state id or HUD id.
"""
import json
import pathlib

FILE = pathlib.Path(__file__).resolve().parent / "lihtc_link_overrides.json"
_D = None


def data():
    global _D
    if _D is None:
        _D = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    return _D


def rejected(pid):
    out = {}
    for o in data().get("reject_links", []):
        if o["hud_property_id"] == pid:
            for i in o["record_ids"]:
                out[i] = o["reason"]
    return out


def not_lihtc_ids():
    return {i for o in data().get("not_lihtc", []) for i in o["record_ids"]}


def lihtc_only():
    return data().get("lihtc_only", [])


def rec_ids(*ids):
    return {i for i in ids if i}

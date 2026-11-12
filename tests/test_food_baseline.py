"""Food must not change. Compares today's food output with the output saved on 12 Nov 2026 (commit 0fb6f5f), before the
vertical switch was added: checklists, tool cards, interview fields, the landing chat prompt and a sample TEM workspace.
No AI calls: everything here builds text or reads data. To refresh after a deliberate food change, run
`python3 -m tests.test_food_baseline --write` and review the diff."""
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ.pop("ANTHROPIC_API_KEY", None)
from vialibera import app, db, fields, landing_chat, lane_requests, requirements, tems, tools

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
FOOD = os.path.join(FIX, "food_baseline.json.gz")
TEM = os.path.join(FIX, "tem_baseline.json.gz")


def _norm(obj):
    return json.loads(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str))


def build_food():
    cats = sorted(requirements.PRODUCTS)
    names = {}
    for k, v in requirements.DESTINATIONS.items():
        names.setdefault(v, k)
    out = {"required": {}, "covers": {}, "tools": {}, "fields": {},
           "covered_products": list(lane_requests.COVERED_PRODUCTS),
           "covered_countries": list(lane_requests.COVERED_COUNTRIES), "start_categories": list(app.START_CATEGORIES)}
    for c in cats:
        for code in sorted(names):
            key = f"{c}|{code}"
            out["covers"][key] = requirements.covers(c, names[code])
            out["required"][key] = requirements.required(c, names[code], set())
            out["tools"][key] = tools.for_case(c, names[code])
    for c in list(app.START_CATEGORIES) + [None, ""]:
        case = {"company": {}, "product": {"category": c} if c is not None else {}, "market": {}}
        out["fields"][str(c)] = [list(x) for x in fields.applicable(case)]
    out["landing_prompt"] = landing_chat.SYSTEM
    out["landing_prompt_sha256"] = hashlib.sha256(landing_chat.SYSTEM.encode()).hexdigest()
    return _norm(out)


def _accept(vat, name):
    return {"vat": vat, "legal_name": name, "signatory_name": "Mario Rossi", "signatory_role": "Legale rappresentante",
            "email": "m@example.it", "accept_scope": True, "accept_core": True, "accept_terms": True, "authorised": True}


def build_tem():
    admin = {"user": "admin", "org": None, "roles": ["veripura_superadmin"]}
    lead = {"user": "lead", "org": None, "roles": []}
    member = {"user": "mem", "org": None, "roles": []}
    con = db.connect()
    _, f = tems.create_firm(con, admin, "Export Partners Srl")
    tems.join(con, lead, f["lead_token"])
    _, inv = tems.invite_member(con, lead)
    tems.join(con, member, inv["token"])
    cos = []
    for sub, vat, name in (("ca", "IT00743110157", "Alfa Srl"), ("cb", "IT01765920051", "Beta Srl")):
        _, link = tems.engage_link(con, lead)
        _, acc = tems.engage_accept(con, {"user": sub, "org": None, "roles": []}, link["token"], _accept(vat, name), "v1")
        cos.append(acc["company"])
    a, b = cos
    made = [tems.new_project(con, lead, co, cat, ctry, nm) for co, cat, ctry, nm in
            [(a, "pasta", "UK", "Penne"), (a, "wine", "USA", "Chianti"), (a, "cheese and dairy", "Germany", "Pecorino"),
             (b, "olive oil", "Switzerland", "Extra vergine"), (b, "spirits", "France", "Grappa"), (b, None, None, None)]]
    res = {"overview_lead": tems.overview(con, lead), "overview_member": tems.overview(con, member),
           "new_project_status": [m[0] for m in made],
           "projects": [tems.project(con, lead, m[1].get("id") or m[1].get("case_id") or (m[1].get("project") or {}).get("id"))
                        for m in made]}
    txt = json.dumps(res, sort_keys=True, ensure_ascii=False, default=str)
    txt = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", txt)
    txt = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?", "<ts>", txt)
    txt = re.sub(r'"(token|lead_token)": "[^"]+"', r'"\1": "<tok>"', txt)
    txt = re.sub(r"engagement_[0-9a-f]{8}\.txt", "engagement_<id>.txt", txt)
    return json.loads(txt)


def first_diff(a, b, path=""):
    if type(a) != type(b):
        return f"{path}: type {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}/{k}: only in {'saved' if k in a else 'now'}"
            d = first_diff(a[k], b[k], f"{path}/{k}")
            if d:
                return d
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
    elif a != b:
        return f"{path}: {str(a)[:80]!r} vs {str(b)[:80]!r}"
    return None


def _load(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


class FoodBaseline(unittest.TestCase):
    def test_food_checklists_tools_fields_and_prompt_unchanged(self):
        d = first_diff(_load(FOOD), build_food())
        self.assertIsNone(d, "food output changed: " + str(d))

    def test_tem_workspace_unchanged(self):
        d = first_diff(_load(TEM), build_tem())
        self.assertIsNone(d, "TEM workspace output changed: " + str(d))


if __name__ == "__main__":
    if "--write" in sys.argv:
        for path, data in ((FOOD, build_food()), (TEM, build_tem())):
            with gzip.GzipFile(path, "wb", mtime=0) as fh:
                fh.write(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        print("written", FOOD, TEM)
    else:
        unittest.main()

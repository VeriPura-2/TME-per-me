"""Researched importers of Italian food and wine, company level only.

The list comes from data/importers.json (built from the Vero Italiano importer workbook, 11 Oct 2026). It holds no
names, emails or phone numbers of people. Everyone may browse it; the website link is for paid plans (and superadmin).
Contacting an importer is not done here: that goes through VeriPura Connect, which is not connected yet.
"""
import json
import os

from . import plans, requirements

_PATH = os.path.join(os.path.dirname(__file__), "data", "importers.json")
_CACHE = {}
WINE = {"wine"}


def _load():
    if "d" not in _CACHE:
        with open(_PATH, encoding="utf-8") as f:
            _CACHE["d"] = json.load(f)
    return _CACHE["d"]


def _wanted(category):
    """Which importer segments fit the project's product. None means show all."""
    p = requirements.PRODUCTS.get((category or "").strip().lower())
    if p == "wine":
        return {"wine", "both"}
    if p:
        return {"food", "both"}
    return None


def countries():
    return sorted({i["country"] for i in _load()["importers"]})


def for_project(category, country, plan_id, superadmin=False, paid_via_tem=False):
    """The list for one destination and product. Websites only for paid plans, a TEM's clients, and superadmin."""
    dest = requirements.DESTINATIONS.get((country or "").strip().lower())
    data = _load()
    want = _wanted(category)
    show_site = bool(superadmin or paid_via_tem or plans.get(plan_id)["rank"] >= 1)
    rows = [i for i in data["importers"] if i["country"] == dest and (want is None or i["segment"] in want)]
    out = []
    for i in rows:
        r = {k: i[k] for k in ("company", "country", "city", "segment", "focus")}
        if show_site and i["website"]:
            r["website"] = i["website"]
        out.append(r)
    return {"country": dest, "listed": dest in countries(), "count": len(out), "importers": out,
            "websites": show_site, "updated": data["updated"]}

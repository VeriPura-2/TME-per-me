"""Tariff adapters: UK Trade Tariff and USITC HTS.

STATUS: parsers written against real live responses (27 Oct 2026) and covered by
offline fixtures in tests/fixtures/. Mode stays stub until a human signs off the
live known-answer run (scripts/run_known_answers.py).
"""
import json
import re
import urllib.error
import urllib.request

from .base import Adapter, AdapterError


def http_get(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AdapterError("unavailable", f"{url}: {e}")


def parse_uk(doc):
    """Pull duty and import VAT from a UK Trade Tariff commodity document (JSON:API).

    Works on a response fetched with filter[geographical_area_id]=<origin>, where the
    API returns only measures that apply to that origin. Duty is the tariff preference
    (measure type 142/143/145) if there is one, else the third country duty (103).
    VAT is measure type 305. Returns None for a field if it is not in the document.
    """
    inc = doc.get("included") or []
    types = {i["id"]: i["attributes"].get("description", "") for i in inc if i["type"] == "measure_type"}
    exprs = {i["id"]: i["attributes"].get("base", "") for i in inc if i["type"] == "duty_expression"}
    found = {}
    for m in inc:
        if m["type"] != "measure":
            continue
        rel = m.get("relationships") or {}
        try:
            mt = rel["measure_type"]["data"]["id"]
            base = exprs[rel["duty_expression"]["data"]["id"]]
        except KeyError:
            continue
        if m["attributes"].get("import") is False or m["attributes"].get("effective_end_date"):
            continue
        found.setdefault(mt, []).append(base)
    pref = next((found[t] for t in ("142", "143", "145") if t in found), None)
    duty = (pref or found.get("103") or [None])[0]
    vat = (found.get("305") or [None])[0]
    return {"duty_expression": duty, "duty_pct": _pct(duty), "duty_is_simple_pct": _simple_pct(duty),
            "import_vat_expression": vat, "import_vat_pct": _pct(vat),
            "duty_basis": "preference" if pref else ("third_country" if "103" in found else None),
            "measure_types_seen": {t: types.get(t) for t in sorted(found)}}


def _pct(expr):
    m = re.match(r"\s*([0-9.]+)\s*%", expr or "")
    return float(m.group(1)) if m else None


def _simple_pct(expr):
    return bool(expr) and re.fullmatch(r"\s*[0-9.]+\s*%\s*", expr) is not None


def parse_usitc(results, code):
    """Find the exact HTS line in a USITC search result and return its duty text."""
    if not isinstance(results, list):
        return None
    for row in results:
        if row.get("htsno") == code:
            general = row.get("general") or ""
            m = re.match(r"\s*([0-9.]+)\s*¢/kg", general)
            return {"htsno": code, "description": row.get("description"), "general": general,
                    "special": row.get("special"), "other": row.get("other"),
                    "cents_per_kg": float(m.group(1)) if m else None}
    return None


class UKTradeTariff(Adapter):
    BASE = "https://www.trade-tariff.service.gov.uk/api/v2"

    def __init__(self, http=http_get):
        super().__init__(id="uk_trade_tariff", name="UK Trade Tariff", kind="tariff", mode="stub")
        self._http = http

    def _fetch(self, con, case_id, commodity_code, origin=None):
        code = str(commodity_code).replace(".", "").replace(" ", "")
        if not (code.isdigit() and len(code) == 10):
            raise AdapterError("invalid_input", "UK commodity code must be 10 digits")
        url = f"{self.BASE}/commodities/{code}"
        if origin:
            url += f"?filter%5Bgeographical_area_id%5D={origin}"
        body = self._http(url)
        try:
            doc = json.loads(body)
        except ValueError:
            raise AdapterError("unavailable", "non-JSON response")
        parsed = parse_uk(doc) if isinstance(doc, dict) else None
        return self.envelope(con, url, {"commodity_code": code, "origin": origin, "parsed": parsed,
                                        "document": doc}, body)


class USITCHts(Adapter):
    BASE = "https://hts.usitc.gov/reststop/search?keyword="

    def __init__(self, http=http_get):
        super().__init__(id="usitc_hts", name="USITC Harmonized Tariff Schedule", kind="tariff", mode="stub")
        self._http = http

    def _fetch(self, con, case_id, code):
        url = f"{self.BASE}{code}"
        body = self._http(url)
        try:
            doc = json.loads(body)
        except ValueError:
            raise AdapterError("unavailable", "non-JSON response")
        return self.envelope(con, url, {"keyword": code, "parsed": parse_usitc(doc, code),
                                        "results": doc}, body)

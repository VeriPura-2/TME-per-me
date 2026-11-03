"""Tariff adapters: UK Trade Tariff and USITC HTS.

STATUS (1 Nov 2026): fetch and parsers verified against live responses. The known-answer
pack passes live (python -m vialibera.check_tariffs), so both adapters are in mode live.
Run the check again after any parser change; tests use real responses saved that day.

Limits, shown to the user with every answer:
- USITC "general" is the column 1 (MFN) rate only. Additional US duties under HTS chapter 99
  (for example measures on EU goods) and antidumping or countervailing duties are NOT included.
- UK: the preferential rate needs proof of EU origin (origin statement on the invoice).
"""
import re
import json
import urllib.error
import urllib.request

from .. import db
from .base import Adapter, AdapterError


def http_get(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with db.outside_call(), urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AdapterError("unavailable", f"{url}: {e}")


class UKTradeTariff(Adapter):
    BASE = "https://www.trade-tariff.service.gov.uk/api/v2"

    def __init__(self, http=None):
        super().__init__(id="uk_trade_tariff", name="UK Trade Tariff", kind="tariff", mode="live")
        self._http = http or (lambda url: http_get(url))  # looked up at call time, so tests can switch the network off

    def _fetch(self, con, case_id, commodity_code):
        code = str(commodity_code).replace(".", "").replace(" ", "")
        if not (code.isdigit() and len(code) == 10):
            raise AdapterError("invalid_input", "UK commodity code must be 10 digits")
        url = f"{self.BASE}/commodities/{code}"
        body = self._http(url)
        try:
            doc = json.loads(body)
        except ValueError:
            raise AdapterError("unavailable", "non-JSON response")
        return self.envelope(con, url, {"commodity_code": code, "document": doc}, body)


class USITCHts(Adapter):
    BASE = "https://hts.usitc.gov/reststop/search?keyword="

    def __init__(self, http=None):
        super().__init__(id="usitc_hts", name="USITC Harmonized Tariff Schedule", kind="tariff", mode="live")
        self._http = http or (lambda url: http_get(url))  # looked up at call time, so tests can switch the network off

    def _fetch(self, con, case_id, code):
        url = f"{self.BASE}{code}"
        body = self._http(url)
        try:
            doc = json.loads(body)
        except ValueError:
            raise AdapterError("unavailable", "non-JSON response")
        return self.envelope(con, url, {"keyword": code, "results": doc}, body)


# parsers (pure functions, tested on saved live responses) --------------------------------

UK_EU = "1013"          # European Union
UK_ALL = "1011"         # ERGA OMNES, all third countries
UK_VAT_AREA = "1400"    # areas subject to VAT or excise


def uk_duties(doc):
    """UK commodity document -> duties for goods of EU origin.

    Returns preferential (EU-UK TCA) duty, third-country duty (no proof of origin),
    any autonomous suspension, and import VAT, each as the verbose text from the tariff.
    """
    inc = {(i["type"], i["id"]): i for i in doc.get("included", [])}

    def expr(m):
        d = (m["relationships"].get("duty_expression") or {}).get("data")
        return inc.get(("duty_expression", d["id"]), {}).get("attributes", {}).get("verbose_duty") if d else None

    out = {"preferential_eu": None, "third_country": None, "suspension": None, "vat": None}
    for m in doc.get("included", []):
        if m["type"] != "measure":
            continue
        mt = m["relationships"]["measure_type"]["data"]["id"]
        ga = m["relationships"]["geographical_area"]["data"]["id"]
        if mt == "142" and ga == UK_EU:
            out["preferential_eu"] = expr(m)
        elif mt == "103" and ga == UK_ALL:
            out["third_country"] = expr(m)
        elif mt == "112" and ga == UK_ALL:
            out["suspension"] = expr(m)
        elif mt == "305" and ga == UK_VAT_AREA:
            out["vat"] = expr(m)
    out["description"] = doc.get("data", {}).get("attributes", {}).get("description_plain")
    return out


def pct(text):
    """'0.00%' -> 0.0; None when the text is not a plain percentage."""
    m = re.fullmatch(r"\s*([\d.]+)\s*%\s*", text or "")
    return float(m.group(1)) if m else None


def us_general(results, code):
    """USITC search results -> column 1 general rate for the exact HTS number, normalised."""
    row = next((r for r in results if r.get("htsno") == code), None)
    if row is None:
        return None
    general = (row.get("general") or "").strip()
    norm = general.replace("\u00a2", " cents").replace(" on contents and container", "").strip()
    norm = re.sub(r"\s+", " ", norm)
    return {"htsno": code, "description": row.get("description"), "general": general, "normalised": norm,
            "column2": row.get("other"), "additional_duties": row.get("additionalDuties")}

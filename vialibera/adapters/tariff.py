"""Tariff adapters: UK Trade Tariff and USITC HTS.

STATUS: parsers were written against LIVE responses fetched on 27 Oct 2026 and
are replayed offline in tests/test_tariff_parsers.py. Adapters stay in mode stub
until scripts/run_known_answers.py has been reviewed by a human.
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


def _pct_of(expr):
    """Pull the leading percent figure out of a duty expression like '6.00 % + 17.00 GBP / 100 kg'."""
    m = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)\s*%", expr or "")
    return float(m.group(1)) if m else None


def parse_uk_commodity(doc, origin="IT"):
    """Read duty and import VAT for one origin country from a UK Trade Tariff commodity document.

    Live structure (JSON:API): data.relationships.import_measures lists measure ids; each
    included 'measure' has a measure_type (103 third country duty, 142 tariff preference,
    305 VAT), a geographical_area (a country code or a group such as 1013 European Union
    or 1011 ERGA OMNES) and a duty_expression with a 'base' string.
    """
    inc = {(i["type"], i["id"]): i for i in doc.get("included", [])}

    def area_ids(geo_id):
        """Geo ids that cover the origin: itself, plus groups that list it as a child."""
        g = inc.get(("geographical_area", geo_id))
        kids = {c["id"] for c in ((g or {}).get("relationships", {})
                                  .get("children_geographical_areas", {}).get("data", []))}
        return kids | {geo_id}

    found = {"preference": [], "third_country": [], "vat": []}
    for ref in doc["data"]["relationships"]["import_measures"]["data"]:
        m = inc.get(("measure", ref["id"]))
        if not m:
            continue
        rel = m["relationships"]
        mtype = rel["measure_type"]["data"]["id"]
        geo = rel["geographical_area"]["data"]["id"]
        covers = origin in area_ids(geo)
        excluded = {e["id"] for e in rel.get("excluded_countries", {}).get("data", [])}
        if mtype not in ("103", "142", "305") or not covers or origin in excluded:
            continue
        if m["attributes"].get("effective_end_date"):
            continue
        base = inc[("duty_expression", rel["duty_expression"]["data"]["id"])]["attributes"]["base"]
        row = {"measure_id": m["id"], "measure_type": mtype, "geo": geo, "expression": base,
               "pct": _pct_of(base), "has_specific_part": "+" in base or "/" in base,
               "has_conditions": bool(rel["measure_conditions"]["data"])}
        key = {"103": "third_country", "142": "preference", "305": "vat"}[mtype]
        found[key].append(row)

    # Prefer a country-specific row over a group row (an exact country match is more specific).
    def best(rows):
        return sorted(rows, key=lambda r: (r["geo"] != origin, r["geo"] in ("1011", "1400")))[0] if rows else None

    pref, third, vat = best(found["preference"]), best(found["third_country"]), best(found["vat"])
    applied = pref or third
    return {
        "origin": origin,
        "duty_pct": applied["pct"] if applied else None,
        "duty_expression": applied["expression"] if applied else None,
        "duty_basis": ("preference" if pref else "third_country") if applied else None,
        "duty_measure_id": applied["measure_id"] if applied else None,
        "duty_has_specific_part": applied["has_specific_part"] if applied else None,
        "third_country_expression": third["expression"] if third else None,
        "import_vat_pct": vat["pct"] if vat else None,
        "import_vat_expression": vat["expression"] if vat else None,
        "preference_needs_origin_proof": bool(pref),
    }


def parse_usitc_rows(rows, code):
    """Find the row whose htsno equals code and return the general (MFN) duty line.

    Live structure: a JSON list of rows with htsno, description, general, special, other.
    'general' is the column 1 duty (what Italy pays, it has no special programme).
    """
    row = next((r for r in rows if r.get("htsno") == code), None)
    if row is None:
        return None
    general = (row.get("general") or "").strip()
    out = {"htsno": code, "description": row.get("description"), "general": general,
           "special": row.get("special"), "other": row.get("other"),
           "cents_per_kg": None, "pct": None, "free": general.lower().startswith("free")}
    m = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*\u00a2\s*/\s*kg", general)
    if m:
        out["cents_per_kg"] = float(m.group(1))
    m = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*%", general)
    if m:
        out["pct"] = float(m.group(1))
    return out


class UKTradeTariff(Adapter):
    BASE = "https://www.trade-tariff.service.gov.uk/api/v2"

    def __init__(self, http=http_get):
        super().__init__(id="uk_trade_tariff", name="UK Trade Tariff", kind="tariff", mode="stub")
        self._http = http

    def _fetch(self, con, case_id, commodity_code, origin="IT"):
        code = str(commodity_code).replace(".", "").replace(" ", "")
        if not (code.isdigit() and len(code) == 10):
            raise AdapterError("invalid_input", "UK commodity code must be 10 digits")
        url = f"{self.BASE}/commodities/{code}"
        body = self._http(url)
        try:
            doc = json.loads(body)
        except ValueError:
            raise AdapterError("unavailable", "non-JSON response")
        try:
            parsed = parse_uk_commodity(doc, origin)
        except (KeyError, TypeError, IndexError):
            raise AdapterError("unavailable", "unexpected UK Trade Tariff structure")
        return self.envelope(con, url, {"commodity_code": code, "parsed": parsed}, body)


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
        if not isinstance(doc, list):
            raise AdapterError("unavailable", "unexpected USITC structure")
        return self.envelope(con, url, {"keyword": code, "parsed": parse_usitc_rows(doc, code)}, body)


CBSA_CH4 = "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/2026/html/00/ch04-eng.html"


def parse_cbsa_rows(page_html, tariff_item):
    """Read Canada customs tariff table rows whose tariff item starts with tariff_item (e.g. 0406.90.93).

    Live structure: an HTML table with columns Tariff Item, SS, Description, Unit, MFN Tariff,
    Applicable Preferential Tariffs. The EU CETA code is CEUT. The page does NOT carry the
    CETA tariff rate quota volume or import permit rules, so those stay unverified.
    """
    import html as _html
    out = []
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", page_html, re.S):
        cells = [_html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) >= 6 and cells[0].startswith(tariff_item):
            pref = cells[5]
            ceta_free = bool(re.search(r"\bCEUT\b", pref.split(":")[0])) and pref.rstrip().endswith("Free")
            out.append({"item": cells[0], "ss": cells[1], "description": cells[2], "unit": cells[3],
                        "mfn": cells[4], "preferential": pref, "ceta_in_preference_list": ceta_free})
    return out

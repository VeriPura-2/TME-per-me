"""Tariff adapters: UK Trade Tariff and USITC HTS.

STATUS: the fetch layer is written, the parsers are NOT yet verified against live
responses (the build workspace could not reach these hosts on 23 Oct 2026).
Until the known-answer pack passes live, these adapters stay in mode stub.
"""
import json
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


class UKTradeTariff(Adapter):
    BASE = "https://www.trade-tariff.service.gov.uk/api/v2"

    def __init__(self, http=http_get):
        super().__init__(id="uk_trade_tariff", name="UK Trade Tariff", kind="tariff", mode="stub")
        self._http = http

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
        return self.envelope(con, url, {"keyword": code, "results": doc}, body)

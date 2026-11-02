"""VeriPura Core Partner API adapter.

Reference: veripura-core2 docs/api-database/PARTNER_API_REFERENCE.md (checked 1 Nov 2026).
  POST /v1/documents                 submit one document (creates a consignment when none is given)
  GET  /v1/consignments/:id/status   consignment roadmap and per-document status
Auth: x-api-key header. Base URL per environment (dev, qa, demo, prod), from CORE_API_URL.

Mode: "live" only when both CORE_API_URL and CORE_API_KEY are set; otherwise "stub", which returns
sample responses in the documented shapes, marked simulated. No secret is ever logged.

Core has no idempotency key: a retried submission can create a duplicate. This adapter never retries
a submission. When the outcome of a send is unknown (timeout, connection drop), the caller records it
as unknown and staff check status before sending again.
"""
import json
import os
import urllib.error
import urllib.request

from .base import Adapter, AdapterError

COUNTRY = {"UK": "United Kingdom", "US": "United States", "CA": "Canada", "DE": "Germany", "FR": "France", "ES": "Spain", "NL": "Netherlands",
           "BE": "Belgium", "AT": "Austria"}
HS = {"pasta": "1902", "wine": "2204", "oil": "1509", "cheese": "0406"}
PRODUCT = {"pasta": "Dried pasta", "wine": "Wine", "oil": "Olive oil", "cheese": "Cheese"}
# MioTEM document type -> Core docType. Anything else is left out and Core infers it from the file name.
DOC_TYPE = {"invoice": "Commercial Invoice", "packing_list": "Packing List", "origin": "Certificate of Origin",
            "lab_analysis": "Certificate of Analysis"}

STATUSES = ("Pending", "Uploaded", "Validated", "Rejected", "Pending Review")


def outcome(status, level=None, requires_review=False):
    """Core result -> what MioTEM shows. Core never approves a shipment, so neither do we."""
    if status == "Rejected" or level == "RED":
        return "flagged_critical"
    if requires_review or status == "Pending Review" or level == "YELLOW":
        return "flagged"
    if status == "Validated" and level in (None, "GREEN"):
        return "matched"
    return "not_checked"


def _config():
    return os.environ.get("CORE_API_URL", "").rstrip("/"), os.environ.get("CORE_API_KEY", "")


def _http(method, url, key, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AdapterError("unavailable", f"{type(e).__name__}")


def _error(code, text):
    try:
        err = json.loads(text).get("error", {})
    except ValueError:
        err = {}
    kind = {400: "invalid_input", 404: "invalid_input", 401: "unavailable"}.get(code, "unavailable")
    raise AdapterError(kind, f"HTTP {code} {err.get('code', '')}: {err.get('message', '')}"[:300])


class VeriPuraCore(Adapter):
    def __init__(self, http=_http):
        url, key = _config()
        super().__init__(id="veripura_core", name="VeriPura Core", kind="compliance",
                         mode="live" if url and key else "stub", auth="api key (x-api-key)",
                         data_location="VeriPura Core hosting (US)", metering_unit="document",
                         provider_version="partner-api v1")
        self._http = http
        self._url, self._key = url, key

    # submit: one document
    def _submit(self, con, case_id, file_name, content_type, file_b64, consignment_id=None, shipment=None, doc_type=None):
        body = {"fileName": file_name, "contentType": content_type, "fileBase64": file_b64}
        if doc_type:
            body["docType"] = doc_type
        if consignment_id:
            body["consignmentId"] = consignment_id
        elif shipment:
            body["shipment"] = shipment
        else:
            raise AdapterError("invalid_input", "shipment is required for a new consignment")
        if self.mode != "live":
            sample = {"consignmentId": consignment_id or "SIM-" + (case_id or "x")[:8], "docType": doc_type or "Commercial Invoice",
                      "status": "Pending Review", "validationLevel": "YELLOW", "requiresHumanReview": True,
                      "alerts": [{"severity": "warning", "message": "Simulated response. Core was not called."}]}
            return self.envelope(con, "stub:" + "/v1/documents", sample, {"simulated": True, "response": sample}, confidence="simulated")
        code, text = self._http("POST", self._url + "/v1/documents", self._key, body)
        if code != 200:
            _error(code, text)
        return self.envelope(con, "/v1/documents", json.loads(text), text, confidence="provider_result")

    # status: whole consignment
    def _status(self, con, case_id, consignment_id):
        if self.mode != "live":
            sample = {"status": "COMPLETED", "consignmentStatus": "In Progress",
                      "roadmap": {"Commercial Invoice": {"required": True, "status": "Pending Review", "validationLevel": "YELLOW"},
                                  "Packing List": {"required": True, "status": "Pending"}}}
            return self.envelope(con, "stub:/v1/consignments/status", sample, {"simulated": True, "response": sample},
                                 confidence="simulated")
        code, text = self._http("GET", f"{self._url}/v1/consignments/{consignment_id}/status", self._key)
        if code != 200:
            _error(code, text)
        return self.envelope(con, "/v1/consignments/:id/status", json.loads(text), text, confidence="provider_result")

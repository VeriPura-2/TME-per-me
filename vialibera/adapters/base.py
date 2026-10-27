"""Provider adapter contract (spec section 2).

Every adapter has the same tools: quote, submit, status, fetch, cancel.
A tool may return not_supported. Every response carries source, retrieved_at,
provider_version, confidence and raw_ref. Every call writes a usage event and
an evidence record entry.
"""
import json
import uuid
from dataclasses import dataclass, field

from ..db import log_event, now


class AdapterError(Exception):
    """Typed error. kind is one of: unavailable, invalid_input, not_supported, needs_human."""

    KINDS = ("unavailable", "invalid_input", "not_supported", "needs_human")

    def __init__(self, kind, message=""):
        assert kind in self.KINDS
        self.kind = kind
        super().__init__(f"{kind}: {message}")


@dataclass
class Adapter:
    id: str
    name: str
    kind: str              # compliance, tariff, lab, certifier, forwarder, tem, payment
    mode: str              # live, manual, stub
    auth: str = "none"
    data_location: str = "n/a (public data)"
    metering_unit: str = "call"
    provider_version: str = "unversioned"
    cross_check_only: bool = False
    tools: dict = field(default_factory=dict)

    def call(self, con, tool, case_id=None, **kwargs):
        if tool not in ("quote", "submit", "status", "fetch", "cancel"):
            raise AdapterError("invalid_input", f"unknown tool {tool}")
        fn = getattr(self, f"_{tool}", None)
        if fn is None:
            log_event(con, case_id, f"adapter:{self.id}", "adapter_not_supported", {"tool": tool})
            raise AdapterError("not_supported", f"{self.id} does not support {tool}")
        try:
            out = fn(con, case_id, **kwargs)
        except AdapterError as e:
            log_event(con, case_id, f"adapter:{self.id}", "adapter_error", {"tool": tool, "error": str(e)})
            raise
        con.execute("INSERT INTO usage_events(case_id, at, provider, units) VALUES (?,?,?,?)",
                    (case_id, now(), self.id, 1))
        log_event(con, case_id, f"adapter:{self.id}", "adapter_call",
                  {"tool": tool, "source": out.get("source"), "raw_ref": out.get("raw_ref")})
        return out

    def envelope(self, con, source, data, raw_body, confidence="official_source"):
        """Wrap a result with the mandatory provenance fields and store the raw response."""
        ref = str(uuid.uuid4())
        con.execute("INSERT INTO raw_responses(ref, at, provider, body) VALUES (?,?,?,?)",
                    (ref, now(), self.id, raw_body if isinstance(raw_body, str) else json.dumps(raw_body)))
        con.commit()
        return {"data": data, "source": source, "retrieved_at": now(),
                "provider_version": self.provider_version, "confidence": confidence,
                "raw_ref": ref, "cross_check_only": self.cross_check_only}

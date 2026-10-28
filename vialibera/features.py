"""Feature registry. One line per feature: phase and mode.

mode: live (real), sim (simulated, labelled as such), manual (staff does it).
To replace a simulation: build the real adapter, set mode to "live", delete the
file named in `sim_file`. The tests list every simulation still active.
Phase 1 essential, phase 2 key value added, phase 3 nice additions.
"""

FEATURES = {
    # phase 1
    "interview":        {"phase": 1, "mode": "live"},
    "documents":        {"phase": 1, "mode": "live"},
    "required_docs":    {"phase": 1, "mode": "sim", "sim_file": "sim/required_docs.py"},
    "tariff_lookup":    {"phase": 1, "mode": "sim", "sim_file": "sim/tariff.py"},
    "options_packet":   {"phase": 1, "mode": "sim", "sim_file": "sim/packet.py"},
    "price_menu":       {"phase": 1, "mode": "sim", "sim_file": "sim/prices.py"},
    "payment":          {"phase": 1, "mode": "sim", "sim_file": "sim/payment.py"},
    "deliverables":     {"phase": 1, "mode": "sim", "sim_file": "sim/deliverables.py"},
    "staff_help":       {"phase": 1, "mode": "manual"},
    # phase 2
    "document_check":   {"phase": 2, "mode": "sim", "sim_file": "sim/document_check.py"},
    "landed_cost":      {"phase": 2, "mode": "sim", "sim_file": "sim/landed_cost.py"},
    "importer_search":  {"phase": 2, "mode": "sim", "sim_file": "sim/importers.py"},
    "export_documents": {"phase": 2, "mode": "sim", "sim_file": "sim/export_docs.py"},
    "label_check":      {"phase": 2, "mode": "sim", "sim_file": "sim/label_check.py"},
    "lab_cert":         {"phase": 2, "mode": "sim", "sim_file": "sim/lab_cert.py"},
    "forwarder_quotes": {"phase": 2, "mode": "sim", "sim_file": "sim/forwarders.py"},
    "alerts":           {"phase": 2, "mode": "sim", "sim_file": "sim/alerts.py"},
    # phase 3
    "tracking":         {"phase": 3, "mode": "sim", "sim_file": "sim/tracking.py"},
    "campaigns":        {"phase": 3, "mode": "sim", "sim_file": "sim/campaigns.py"},
    "voice":            {"phase": 3, "mode": "sim", "sim_file": "sim/voice.py"},
    "reminders":        {"phase": 3, "mode": "sim", "sim_file": "sim/reminders.py"},
    "team_roles":       {"phase": 3, "mode": "sim", "sim_file": "sim/team.py"},
    "reports":          {"phase": 3, "mode": "sim", "sim_file": "sim/reports.py"},
}


def mode(feature):
    return FEATURES[feature]["mode"]


def is_sim(feature):
    return mode(feature) == "sim"


def public():
    """What the browser may see: mode and phase only."""
    return {k: {"phase": v["phase"], "mode": v["mode"]} for k, v in FEATURES.items()}


def active_simulations():
    """The removal checklist: every simulation still switched on."""
    return sorted((k, v["sim_file"]) for k, v in FEATURES.items() if v["mode"] == "sim")

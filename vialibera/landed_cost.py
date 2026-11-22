"""Landed cost estimate (B3, 22 Nov 2026).

The exporter's own numbers (goods value, freight, insurance, other costs, units) plus the duty from the official tariff
(duties.py, read weekly by tariff_watch). Only a duty given as a percentage of value is applied, and only to the goods
value: countries value goods for duty in different ways, and that basis is not sourced per country yet. A duty in any
other form (for example cents per kg) is shown as it is and the exporter adds it under other costs. Import VAT, sales tax
and excise are not calculated. Nothing is stored: it is an estimate on the page, not a quote.
"""
import re

PCT = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*%\s*$")


def duty_rate(value):
    """A percentage for a plain ad valorem value or Free, else None."""
    v = str(value or "").strip()
    if v.lower() in ("free", "0", "esente"):
        return 0.0
    m = PCT.match(v)
    return float(m.group(1).replace(",", ".")) if m else None


def _num(v):
    try:
        x = float(str(v if v not in (None, "") else 0).replace(",", "."))
    except ValueError:
        return None
    return x if 0 <= x <= 1e9 else None


def choices(du):
    """The duty lines the exporter can pick, as 'group:line', with label and value. Import VAT lines are not duties."""
    from .duties import LABELS
    out = []
    if not du or du.get("eu") or du.get("pending") or du.get("unavailable"):
        return out
    for gi, g in enumerate(du["groups"]):
        for li, line in enumerate(g["lines"]):
            if line["label"] == LABELS["vat"]:
                continue
            out.append({"id": f"{gi}:{li}", "code": g["code"], "description": g["description"], "label": line["label"],
                        "value": line["value"], "rate": duty_rate(line["value"])})
    return out


def estimate(du, body):
    goods, freight, ins, other, units = (_num(body.get(k)) for k in ("goods", "freight", "insurance", "other", "units"))
    if None in (goods, freight, ins, other, units) or not goods:
        return 400, {"error": "bad numbers"}
    duty, rate, pick, mode = 0.0, None, None, "none"
    if du and du.get("eu"):
        mode = "eu"
    else:
        ch = {c["id"]: c for c in choices(du)}
        pick = ch.get(str(body.get("line") or "")) or (next(iter(ch.values())) if ch else None)
        if pick is None:
            mode = "unavailable"
        elif pick["rate"] is None:
            mode = "not_percent"
        else:
            rate, mode = pick["rate"], "percent"
            duty = round(goods * rate / 100, 2)
    total = round(goods + freight + ins + other + duty, 2)
    per_unit = round(total / units, 2) if units else None
    return 200, {"goods": goods, "freight": freight, "insurance": ins, "other": other, "duty": duty, "rate": rate,
                 "duty_mode": mode, "line": pick, "total": total, "per_unit": per_unit,
                 "limit": du.get("limit") if du and not du.get("eu") else None}

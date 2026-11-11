"""A landing visitor asks to be told when a route MioTEM does not cover yet is ready.

Public endpoint, so it is small and guarded like the TEM form: an email check, a hidden trap field, a consent
flag, one request per email per day and an hourly cap. The product and country come from the visitor's saved
chat answers (their own words), never from the request body.
"""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from . import db, notify

HOURLY_CAP = 30
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
VISITOR = re.compile(r"^[a-f0-9]{16,64}$")


def row_role_is_tem(con, visitor):
    r = con.execute("SELECT role FROM anon_chats WHERE visitor_id=?", (visitor,)).fetchone()
    return bool(r and r["role"] == "tem")


def record(con, data):
    """Returns (status, body). A filled trap field looks like success so bots learn nothing."""
    if str(data.get("website") or "").strip():
        return 200, {"ok": True}
    email = str(data.get("email") or "").strip().lower()[:254]
    name = str(data.get("name") or "").strip()[:150]
    visitor = str(data.get("visitor") or "")
    lang = "it" if data.get("lang") == "it" else "en"
    if not EMAIL.match(email) or data.get("consent") is not True:
        return 400, {"error": "email_and_consent_required"}
    product = country = None
    if VISITOR.match(visitor):
        row = con.execute("SELECT answers FROM anon_chats WHERE visitor_id=?", (visitor,)).fetchone()
        if row:
            a = json.loads(row["answers"])
            product = (a.get("product") or [None])[0] if isinstance(a.get("product"), list) else a.get("product")
            country = (a.get("destination") or [None])[0] if isinstance(a.get("destination"), list) else a.get("destination")
            if a.get("uncovered"):
                country = a["uncovered"][0]  # a TEM (or exporter) named countries without a list: keep their words
            if not product and row_role_is_tem(con, visitor):
                product = "TEM clients"
    product = str(product or "")[:150] or None
    country = str(country or "")[:150] or None
    now = datetime.now(timezone.utc)
    hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    day_ago = (now - timedelta(days=1)).isoformat(timespec="seconds")
    if con.execute("SELECT COUNT(*) AS n FROM route_interest WHERE created_at>?", (hour_ago,)).fetchone()["n"] >= HOURLY_CAP:
        return 429, {"error": "busy"}
    if con.execute("SELECT 1 FROM route_interest WHERE email=? AND created_at>?", (email, day_ago)).fetchone():
        return 200, {"ok": True}  # already received today
    con.execute("INSERT INTO route_interest(id, visitor_id, product, country, email, name, lang, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), visitor if VISITOR.match(visitor) else None, product, country, email, name or None, lang, db.now()))
    con.commit()
    notify.send("MioTEM: route request " + (product or "?") + " to " + (country or "?"),
                f"A visitor asked to be told when this route is covered.\nProduct: {product}\nCountry: {country}\nEmail: {email}\nName: {name}\nLanguage: {lang}\n")
    return 200, {"ok": True}


def listing(con):
    rows = [dict(r) for r in con.execute(
        "SELECT product, country, email, name, lang, created_at FROM route_interest ORDER BY created_at DESC LIMIT 200").fetchall()]
    return {"total": len(rows), "requests": rows}

"""TEM interest from the public landing page: a firm asks to join, staff create the firm and send the invite.

The endpoint is public (no sign-in), so it is small and guarded: field limits, an email check, a hidden
trap field for bots, one request per email per day and a cap on requests per hour overall.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from . import db

HOURLY_CAP = 30
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


def record(con, data):
    """Returns (status, body). A filled trap field looks like success so bots learn nothing."""
    if str(data.get("website") or "").strip():
        return 200, {"ok": True}
    firm = str(data.get("firm_name") or "").strip()[:150]
    email = str(data.get("email") or "").strip().lower()[:254]
    clients = str(data.get("clients") or "").strip()[:40]
    lang = "it" if data.get("lang") == "it" else "en"
    if not firm or not EMAIL.match(email):
        return 400, {"error": "firm_and_email_required"}
    now = datetime.now(timezone.utc)
    hour_ago = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    day_ago = (now - timedelta(days=1)).isoformat(timespec="seconds")
    if con.execute("SELECT COUNT(*) AS n FROM tem_interest WHERE created_at>?", (hour_ago,)).fetchone()["n"] >= HOURLY_CAP:
        return 429, {"error": "busy"}
    if con.execute("SELECT 1 FROM tem_interest WHERE email=? AND created_at>?", (email, day_ago)).fetchone():
        return 200, {"ok": True}  # already received today
    con.execute("INSERT INTO tem_interest(id, firm_name, email, clients, lang, created_at) VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), firm, email, clients, lang, db.now()))
    return 200, {"ok": True}


def listing(con):
    rows = [dict(r) for r in con.execute(
        "SELECT firm_name, email, clients, lang, created_at FROM tem_interest ORDER BY created_at DESC LIMIT 200").fetchall()]
    return {"total": len(rows), "requests": rows}

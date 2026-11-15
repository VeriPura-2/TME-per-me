"""Staff notices by email. Off until the SMTP settings exist in the environment, then it sends.

Settings (set by the operator in the service environment, never in chat or in the repository):
NOTIFY_SMTP_HOST, NOTIFY_SMTP_PORT (default 587), NOTIFY_SMTP_USER, NOTIFY_SMTP_PASSWORD, NOTIFY_FROM, NOTIFY_TO (comma separated).
Best effort: a failure never breaks the request that caused the notice.

send_to() sends one message to a named person (for example a team invitation). It needs only the SMTP host and
NOTIFY_FROM, not NOTIFY_TO. Resend works through its SMTP service with these same settings.
"""
import os
import smtplib
from email.message import EmailMessage


def enabled():
    return bool(os.environ.get("NOTIFY_SMTP_HOST") and os.environ.get("NOTIFY_FROM") and os.environ.get("NOTIFY_TO"))


def can_send():
    """True when a message to a named person can be sent (SMTP host and sender set)."""
    return bool(os.environ.get("NOTIFY_SMTP_HOST") and os.environ.get("NOTIFY_FROM"))


def _deliver(msg):
    with smtplib.SMTP(os.environ["NOTIFY_SMTP_HOST"], int(os.environ.get("NOTIFY_SMTP_PORT", "587")), timeout=10) as smtp:
        smtp.starttls()
        if os.environ.get("NOTIFY_SMTP_USER"):
            smtp.login(os.environ["NOTIFY_SMTP_USER"], os.environ.get("NOTIFY_SMTP_PASSWORD", ""))
        smtp.send_message(msg)


def send_to(to, subject, body):
    """One plain-text message to one address. True if handed to the mail server, False if off or failed."""
    if not can_send():
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = str(subject)[:200]
        msg["From"] = os.environ["NOTIFY_FROM"]
        msg["To"] = str(to)
        msg.set_content(str(body)[:4000])
        _deliver(msg)
        return True
    except Exception:
        return False


def send(subject, body):
    """Returns True if a message was handed to the mail server, False if notices are off or the send failed."""
    if not enabled():
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = str(subject)[:200]
        msg["From"] = os.environ["NOTIFY_FROM"]
        msg["To"] = os.environ["NOTIFY_TO"]
        msg.set_content(str(body)[:4000])
        with smtplib.SMTP(os.environ["NOTIFY_SMTP_HOST"], int(os.environ.get("NOTIFY_SMTP_PORT", "587")), timeout=10) as smtp:
            smtp.starttls()
            if os.environ.get("NOTIFY_SMTP_USER"):
                smtp.login(os.environ["NOTIFY_SMTP_USER"], os.environ.get("NOTIFY_SMTP_PASSWORD", ""))
            smtp.send_message(msg)
        return True
    except Exception:
        return False

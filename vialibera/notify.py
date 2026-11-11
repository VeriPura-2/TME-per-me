"""Staff notices by email. Off until the SMTP settings exist in the environment, then it sends.

Settings (set by the operator in the service environment, never in chat or in the repository):
NOTIFY_SMTP_HOST, NOTIFY_SMTP_PORT (default 587), NOTIFY_SMTP_USER, NOTIFY_SMTP_PASSWORD, NOTIFY_FROM, NOTIFY_TO (comma separated).
Best effort: a failure never breaks the request that caused the notice.
"""
import os
import smtplib
from email.message import EmailMessage


def enabled():
    return bool(os.environ.get("NOTIFY_SMTP_HOST") and os.environ.get("NOTIFY_FROM") and os.environ.get("NOTIFY_TO"))


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

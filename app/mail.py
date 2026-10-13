"""Outgoing mail: login links and notifications. The mail to planning is never sent from here."""

import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from app.config import Settings

log = logging.getLogger("ruilingen.mail")

# Tests and the console backend append here so sent mail can be inspected.
outbox: list[EmailMessage] = []


def build(settings: Settings, to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="ruilingen.app")
    # Tells auto-responders ("out of office") not to answer.
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    return msg


def send(settings: Settings, to: str, subject: str, body: str) -> None:
    """Send one mail. Errors are logged, never raised: a failed notification must not
    break the action that triggered it."""
    msg = build(settings, to, subject, body)
    try:
        if settings.mail_backend == "smtp":
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(msg)
        else:
            outbox.append(msg)
            log.info("mail to %s: %s\n%s", to, subject, body)
    except Exception:
        log.exception("sending mail to %s failed", to)

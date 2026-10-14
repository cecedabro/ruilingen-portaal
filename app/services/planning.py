"""The email to planning for a completed swap.

The app doesn't send it: one of the two colleagues sends it from their own mail app (a
mailto: link, or copy/paste), so planning gets it from a colleague as before. Admins can edit
the template on Beheer. Placeholders are replaced with a plain lookup (no `str.format`, which
would let a template reach into object attributes); unknown placeholders are left as typed.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import Settings
from app.services import appdata
from app.services.listings import Deal
from app.shifts import fmt_date, fmt_date_long

SUBJECT_KEY, BODY_KEY = "mail_subject", "mail_body"
MAX_SUBJECT, MAX_BODY = 200, 4000

DEFAULT_SUBJECT = "Dienstruil {datum} · {soort} {tijd}"
DEFAULT_BODY = """Beste planning,

{nemer} neemt de volgende dienst over van {gever}:

{details}

Wij hebben dit allebei bevestigd.

Met vriendelijke groet,
{gever} en {nemer}"""

# Shown on Beheer next to the template editor.
PLACEHOLDERS = {
    "gever": "wie de dienst weggeeft",
    "nemer": "wie de dienst overneemt",
    "datum": "za 17 okt",
    "datum_lang": "zaterdag 17 oktober",
    "datum_iso": "2026-10-17",
    "soort": "HG",
    "tijd": "19:10–22:30",
    "zaal": "zaal (leeg als niet ingevuld)",
    "werkplek": "werkplek (leeg als niet ingevuld)",
    "details": "blok met datum, soort, tijd, zaal, werkplek (alleen wat ingevuld is)",
}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass
class PlanningMail:
    to: str
    cc: list[str]
    subject: str
    body: str

    @property
    def mailto(self) -> str:
        cc = f"cc={quote(','.join(self.cc))}&" if self.cc else ""
        return f"mailto:{quote(self.to)}?{cc}subject={quote(self.subject)}&body={quote(self.body)}"

    @property
    def as_text(self) -> str:
        """For the copy button: a complete mail including the recipients."""
        cc = f"Cc: {', '.join(self.cc)}\n" if self.cc else ""
        return f"Aan: {self.to}\n{cc}Onderwerp: {self.subject}\n\n{self.body}"


def template(db: Session) -> tuple[str, str]:
    """(subject, body) as admins set them, or the defaults."""
    return (
        appdata.get_value(db, SUBJECT_KEY) or DEFAULT_SUBJECT,
        appdata.get_value(db, BODY_KEY) or DEFAULT_BODY,
    )


def save_template(db: Session, subject: str, body: str) -> None:
    subject = " ".join(subject.split())[:MAX_SUBJECT]
    body = body.replace("\r\n", "\n").strip()[:MAX_BODY]
    appdata.set_value(db, SUBJECT_KEY, subject if subject and subject != DEFAULT_SUBJECT else None)
    appdata.set_value(db, BODY_KEY, body if body and body != DEFAULT_BODY else None)


def reset_template(db: Session) -> None:
    appdata.set_value(db, SUBJECT_KEY, None)
    appdata.set_value(db, BODY_KEY, None)


def fill(text: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def _values(deal: Deal) -> dict[str, str]:
    shift = deal.shift
    lines = [
        f"  Datum:    {fmt_date_long(shift.day)} ({shift.day.isoformat()})",
        f"  Soort:    {shift.code}",
    ]
    if shift.when:
        lines.append(f"  Tijd:     {shift.when}")
    if shift.hall:
        lines.append(f"  Zaal:     {shift.hall}")
    if shift.workplace:
        lines.append(f"  Werkplek: {shift.workplace}")
    return {
        "gever": deal.giver.name,
        "nemer": deal.taker.name,
        "datum": fmt_date(shift.day),
        "datum_lang": fmt_date_long(shift.day),
        "datum_iso": shift.day.isoformat(),
        "soort": shift.code,
        "tijd": shift.when,
        "zaal": shift.hall or "",
        "werkplek": shift.workplace or "",
        "details": "\n".join(lines),
    }


def compose(db: Session, settings: Settings, deal: Deal) -> PlanningMail:
    subject_tpl, body_tpl = template(db)
    values = _values(deal)
    return PlanningMail(
        to=settings.planning_email,
        cc=[e for e in (deal.giver.email, deal.taker.email) if e],
        subject=" ".join(fill(subject_tpl, values).split()),  # no double spaces if empty
        body=fill(body_tpl, values),
    )

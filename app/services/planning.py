"""The email to planning for a completed swap.

The app doesn't send it: one of the two colleagues sends it from their own mail app (a
mailto: link, or copy/paste), so planning gets it from a colleague as before. Admins can edit
the templates on Beheer: one for a shift given away, one for a real swap (ruil, two shifts).
Placeholders are replaced with a plain lookup (no `str.format`, which would let a template
reach into object attributes); unknown placeholders are left as typed.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import Settings
from app.services import appdata
from app.services.listings import Deal
from app.shifts import ShiftInfo, fmt_date, fmt_date_long

SUBJECT_KEY, BODY_KEY = "mail_subject", "mail_body"
TRADE_SUBJECT_KEY, TRADE_BODY_KEY = "mail_trade_subject", "mail_trade_body"
MAX_SUBJECT, MAX_BODY = 200, 4000

DEFAULT_SUBJECT = "Dienstruil {datum} · {soort} {tijd}"
DEFAULT_BODY = """Beste planning,

{nemer} neemt de volgende dienst over van {gever}:

{details}

Wij hebben dit allebei bevestigd.

Met vriendelijke groet,
{gever} en {nemer}"""

DEFAULT_TRADE_SUBJECT = "Dienstruil {datum} {soort} ↔ {datum_terug} {soort_terug}"
DEFAULT_TRADE_BODY = """Beste planning,

{gever} en {nemer} ruilen de volgende diensten:

{nemer} neemt over van {gever}:
{details}

{gever} neemt over van {nemer}:
{details_terug}

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
    "datum_terug": "ruil: datum van de dienst die terug gaat",
    "soort_terug": "ruil: soort van de dienst die terug gaat",
    "tijd_terug": "ruil: tijd van de dienst die terug gaat",
    "details_terug": "ruil: blok met de dienst die terug gaat",
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


def template(db: Session, trade: bool = False) -> tuple[str, str]:
    """(subject, body) as admins set them, or the defaults. `trade`: the template for a swap."""
    if trade:
        return (
            appdata.get_value(db, TRADE_SUBJECT_KEY) or DEFAULT_TRADE_SUBJECT,
            appdata.get_value(db, TRADE_BODY_KEY) or DEFAULT_TRADE_BODY,
        )
    return (
        appdata.get_value(db, SUBJECT_KEY) or DEFAULT_SUBJECT,
        appdata.get_value(db, BODY_KEY) or DEFAULT_BODY,
    )


def save_template(db: Session, subject: str, body: str, trade: bool = False) -> None:
    """Store an edited template; text equal to the default is stored as "no override"."""
    subject = " ".join(subject.split())[:MAX_SUBJECT]
    body = body.replace("\r\n", "\n").strip()[:MAX_BODY]
    d_subject, d_body = (
        (DEFAULT_TRADE_SUBJECT, DEFAULT_TRADE_BODY) if trade else (DEFAULT_SUBJECT, DEFAULT_BODY)
    )
    s_key, b_key = (TRADE_SUBJECT_KEY, TRADE_BODY_KEY) if trade else (SUBJECT_KEY, BODY_KEY)
    appdata.set_value(db, s_key, subject if subject and subject != d_subject else None)
    appdata.set_value(db, b_key, body if body and body != d_body else None)


def reset_templates(db: Session) -> None:
    for key in (SUBJECT_KEY, BODY_KEY, TRADE_SUBJECT_KEY, TRADE_BODY_KEY):
        appdata.set_value(db, key, None)


def fill(text: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def _details(shift: ShiftInfo) -> str:
    """The datum/soort/tijd/zaal/werkplek lines of one shift, only what was filled in."""
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
    return "\n".join(lines)


def _values(deal: Deal) -> dict[str, str]:
    shift, back = deal.shift, deal.return_shift
    values = {
        "gever": deal.giver.name,
        "nemer": deal.taker.name,
        "datum": fmt_date(shift.day),
        "datum_lang": fmt_date_long(shift.day),
        "datum_iso": shift.day.isoformat(),
        "soort": shift.code,
        "tijd": shift.when,
        "zaal": shift.hall or "",
        "werkplek": shift.workplace or "",
        "details": _details(shift),
    }
    if back is not None:
        values.update(
            datum_terug=fmt_date(back.day),
            soort_terug=back.code,
            tijd_terug=back.when,
            details_terug=_details(back),
        )
    return values


def compose(db: Session, settings: Settings, deal: Deal) -> PlanningMail:
    subject_tpl, body_tpl = template(db, trade=deal.return_shift is not None)
    values = _values(deal)
    return PlanningMail(
        to=settings.planning_email,
        cc=[e for e in (deal.giver.email, deal.taker.email) if e],
        subject=" ".join(fill(subject_tpl, values).split()),  # no double spaces if empty
        body=fill(body_tpl, values),
    )

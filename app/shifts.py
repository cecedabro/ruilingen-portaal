"""Shift types, Dutch date formatting and the email to planning."""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote

# Letters in the order they happen within the shift: HG = bar first, cloakroom after the break.
PARTS = {
    "H": "Horeca (bar)",
    "G": "Garderobe",
    "C": "Champagnebar",
    "P": "Programma's verkopen",
    "R": "Receptie",
    "I": "Inwerkdienst",
}
SHIFT_TYPES = ["H", "HG", "GH", "G", "CGH", "CHG", "CH", "R", "PH", "PHG", "PGH", "I"]

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

DAYS = ["ma", "di", "wo", "do", "vr", "za", "zo"]
DAYS_LONG = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
MONTHS_LONG = [
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
]


def is_shift_type(code: str) -> bool:
    return code in SHIFT_TYPES


def is_time(value: str) -> bool:
    return bool(_TIME.match(value or ""))


def explain(code: str) -> str:
    return " → ".join(PARTS.get(c, c) for c in code)


def fmt_date(d: date) -> str:
    """'za 18 okt'"""
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def fmt_date_long(d: date) -> str:
    """'zaterdag 18 oktober'"""
    return f"{DAYS_LONG[d.weekday()]} {d.day} {MONTHS_LONG[d.month - 1]}"


def fmt_stamp(dt: datetime, now: datetime) -> str:
    """Posting time as people read it: 'vandaag 14:05', 'gisteren 09:12', 'di 7 okt 18:30'.

    Both arguments must already be in local time.
    """
    hm = dt.strftime("%H:%M")
    if dt.date() == now.date():
        return f"vandaag {hm}"
    if dt.date() == now.date() - timedelta(days=1):
        return f"gisteren {hm}"
    return f"{fmt_date(dt.date())} {hm}"


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
        cc = f"Cc: {', '.join(self.cc)}\n" if self.cc else ""
        return f"Aan: {self.to}\n{cc}Onderwerp: {self.subject}\n\n{self.body}"


def planning_mail(
    *,
    planning: str,
    giver_name: str,
    giver_email: str | None,
    taker_name: str,
    taker_email: str | None,
    day: date,
    start: str,
    end: str,
    code: str,
) -> PlanningMail:
    body = (
        "Beste planning,\n\n"
        f"{taker_name} neemt de volgende dienst over van {giver_name}:\n\n"
        f"  Datum:  {fmt_date_long(day)} ({day.isoformat()})\n"
        f"  Tijd:   {start}–{end}\n"
        f"  Soort:  {code} ({explain(code)})\n\n"
        "Wij hebben dit allebei bevestigd.\n\n"
        "Met vriendelijke groet,\n"
        f"{giver_name} en {taker_name}"
    )
    return PlanningMail(
        to=planning,
        cc=[e for e in (giver_email, taker_email) if e],
        subject=f"Dienstruil {fmt_date(day)} · {code} {start}–{end}",
        body=body,
    )

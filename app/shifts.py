"""Shift types and Dutch date/time formatting. Pure functions: no database, no web."""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Letters in the order they happen within the shift: HG = bar first, cloakroom after the break.
PARTS = {
    "H": "Horeca (bar)",
    "G": "Garderobe",
    "C": "Champagnebar",
    "P": "Programma's verkopen",
    "R": "Receptie",
    "I": "Inwerkdienst",
}
SHIFT_TYPES = ["H", "HG", "GH", "G", "CGH", "CHG", "CH", "R", "PH", "PHG", "PGH", "Inwerk"]

# Part of the day, for when the exact time doesn't matter or isn't known yet.
DAYPARTS = ["ochtend", "middag", "avond"]

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
    if code == "Inwerk":
        return PARTS["I"]
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
class ShiftInfo:
    """One shift's what/when/where, whichever optional parts were filled in."""

    code: str
    day: date
    start: str | None = None
    end: str | None = None
    daypart: str | None = None
    hall: str | None = None
    workplace: str | None = None

    @property
    def when(self) -> str:
        """'19:10–22:30', 'avond' or ''."""
        if self.start and self.end:
            return f"{self.start}–{self.end}"
        return self.daypart or ""

    @property
    def part_of_day(self) -> str | None:
        """The given dagdeel, or the one the start time falls in."""
        if self.start:
            hour = int(self.start[:2])
            return "ochtend" if hour < 12 else "middag" if hour < 17 else "avond"
        return self.daypart

    @property
    def sort_key(self) -> str:
        """Within a day: by start time; a bare dagdeel sorts at its usual start."""
        return self.start or {"ochtend": "09:00", "middag": "13:00", "avond": "18:00"}.get(
            self.daypart or "", "99:99"
        )

    @property
    def where(self) -> str:
        """'Grote Zaal · Foyer 1', one of them, or ''."""
        return " · ".join(p for p in (self.hall, self.workplace) if p)

"""Shift types and Dutch date/time formatting. Pure functions: no database, no web."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

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

# An end time before the begin time means the shift runs past midnight (22:30 – 01:00). Longer
# than this it's almost certainly a typo (16:12 – 15:12 would be 23 hours), so it's refused.
MAX_OVERNIGHT_HOURS = 12
# Where a bare dagdeel (no times) starts, for sorting and for when it leaves the board.
DAYPART_START = {"ochtend": "09:00", "middag": "13:00", "avond": "18:00"}

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


def shift_minutes(start: str, end: str) -> int:
    """Length of a shift in minutes; an end before the begin is on the next day."""
    minutes = (int(end[:2]) * 60 + int(end[3:])) - (int(start[:2]) * 60 + int(start[3:]))
    return minutes if minutes > 0 else minutes + 24 * 60


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
    def overnight(self) -> bool:
        """Ends after midnight, on the day after `day`."""
        return bool(self.start and self.end and self.end < self.start)

    @property
    def when(self) -> str:
        """'19:10–22:30', '22:30–01:00 (+1)', 'avond' or ''."""
        if self.start and self.end:
            return f"{self.start}–{self.end}" + (" (+1)" if self.overnight else "")
        return self.daypart or ""

    @property
    def starts_at(self) -> datetime:
        """Local start; a bare dagdeel at its usual start, nothing at all at the end of the day."""
        if is_time(self.sort_key):
            return datetime.combine(self.day, time.fromisoformat(self.sort_key))
        return datetime.combine(self.day + timedelta(days=1), time())

    @property
    def ends_at(self) -> datetime:
        """Local end (the next day for an overnight shift); without times, the end of the day."""
        if self.start and self.end:
            end_day = self.day + timedelta(days=1) if self.overnight else self.day
            return datetime.combine(end_day, time.fromisoformat(self.end))
        return datetime.combine(self.day + timedelta(days=1), time())

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
        return self.start or DAYPART_START.get(self.daypart or "", "99:99")

    @property
    def where(self) -> str:
        """'Grote Zaal · Foyer 1', one of them, or ''."""
        return " · ".join(p for p in (self.hall, self.workplace) if p)

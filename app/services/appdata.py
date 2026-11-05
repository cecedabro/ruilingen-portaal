"""Settings admins change at runtime, stored as key/value rows in `app_settings`.

The zaal/werkplek lists and the planning mail template live in the database rather than in
code: the real room names identify the employer and this repository is public. Until an
admin sets them, generic defaults are used.
"""

from sqlalchemy.orm import Session

from app.models import AppSetting
from app.shifts import DAYPARTS, is_time

DEFAULT_LISTS = {
    "halls": ["Grote Zaal", "Kleine Zaal", "Overig"],
    "workplaces": ["Foyer 1", "Foyer 2", "Bar", "Overig"],
}
# Typical shift times per dagdeel: only a starting point that the post form fills in (and
# the poster can change). Admins can set their own on Beheer.
DEFAULT_DAYPART_TIMES = {
    "ochtend": ("09:00", "13:00"),
    "middag": ("13:00", "17:30"),
    "avond": ("18:00", "23:00"),
}
MAX_LIST_ITEMS = 40
MAX_ITEM_LENGTH = 60


def get_value(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row is not None else None


def set_value(db: Session, key: str, value: str | None) -> None:
    """Store a value; `None` removes it (back to the default)."""
    row = db.get(AppSetting, key)
    if value is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def get_list(db: Session, key: str) -> list[str]:
    value = get_value(db, key)
    if value is None:
        return list(DEFAULT_LISTS[key])
    return [line for line in value.splitlines() if line.strip()]


def set_list(db: Session, key: str, values: list[str]) -> list[str]:
    """Save a list: whitespace tidied, duplicates and empty lines dropped."""
    if key not in DEFAULT_LISTS:
        raise KeyError(key)
    cleaned = (" ".join(v.split())[:MAX_ITEM_LENGTH] for v in values if v.strip())
    unique = list(dict.fromkeys(cleaned))[:MAX_LIST_ITEMS]
    set_value(db, key, "\n".join(unique))
    return unique


def _parse_daypart_lines(text: str) -> dict[str, tuple[str, str]]:
    """Lines like 'avond 18:00-23:00' -> {'avond': ('18:00', '23:00')}; bad lines are skipped."""
    found = {}
    for line in text.splitlines():
        name, _, span = line.strip().partition(" ")
        start, _, end = (part.strip() for part in span.partition("-"))
        if name in DAYPARTS and is_time(start) and is_time(end):
            found[name] = (start, end)
    return found


def daypart_times(db: Session) -> dict[str, tuple[str, str]]:
    """Typical times per dagdeel: the admin's lines, with the default for any that are missing."""
    return {**DEFAULT_DAYPART_TIMES, **_parse_daypart_lines(get_value(db, "daypart_times") or "")}


def set_daypart_times(db: Session, text: str) -> None:
    """Save the admin's lines (key `daypart_times`); anything that doesn't parse is dropped."""
    parsed = _parse_daypart_lines(text)
    set_value(db, "daypart_times", "\n".join(f"{n} {s}-{e}" for n, (s, e) in parsed.items()))

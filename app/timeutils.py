"""
Everything is stored in the database as UTC. IST (UTC+05:30, no DST) is only
used at the edges: interpreting the time typed into the schedule form, and
displaying times to the user.

IST is a fixed offset, so no tz database is needed (zoneinfo on Windows
needs the separate `tzdata` package; this avoids that dependency).
"""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def utc_now_naive() -> datetime:
    """Current UTC as a naive datetime — the form SQLite stores and compares."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ist_to_utc_naive(local_ist: datetime) -> datetime:
    """A wall-clock time typed by the user (IST) -> naive UTC for storage."""
    if local_ist.tzinfo is None:
        local_ist = local_ist.replace(tzinfo=IST)
    return local_ist.astimezone(timezone.utc).replace(tzinfo=None)


def utc_to_ist(utc_dt: datetime) -> datetime:
    """A stored UTC datetime (naive or aware) -> aware IST datetime."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(IST)


def format_ist(utc_dt, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Jinja filter: `{{ job.scheduled_at | ist }}` -> '05 Jan 2030, 03:00 PM IST'."""
    if not utc_dt:
        return "—"
    return utc_to_ist(utc_dt).strftime(fmt) + " IST"

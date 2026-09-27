"""Upcoming leg occurrences (AGENTS.md › Routines): local wall-clock times in the routine's timezone,
so 09:30 stays 09:30 across DST. For a window leg the departure is the window start."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.db.models import leg_days

DEFAULT_TZ = "America/New_York"


@dataclass(frozen=True)
class Occurrence:
    routine_id: str
    leg: int
    local_date: date
    departure_at: datetime  # tz-aware, routine timezone
    heads_up_at: datetime
    window: tuple[datetime, datetime] | None = None
    demo: bool = False


def _at(day: date, clock: str, zone: ZoneInfo) -> datetime:
    hour, minute = map(int, clock.split(":"))
    # A wall-clock time in the zone. Round-tripping through UTC normalises a time that doesn't
    # exist on a spring-forward day (02:30 → 03:30); an ambiguous fall-back time takes fold=0.
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone).astimezone(timezone.utc).astimezone(zone)


def leg_occurrences(routine: dict, leg_index: int, now: datetime, days: int) -> list[Occurrence]:
    """Occurrences of one leg over the next `days` local dates whose departure is still ahead."""
    zone = ZoneInfo(routine.get("tz") or DEFAULT_TZ)
    leg = routine["legs"][leg_index]
    heads_up = timedelta(minutes=routine.get("heads_up_minutes", 30))
    weekdays = set(leg_days(routine, leg))
    today = now.astimezone(zone).date()
    found = []
    for offset in range(days + 1):
        day = today + timedelta(days=offset)
        if day.strftime("%a").lower() not in weekdays:
            continue
        when = leg["when"]
        if when["kind"] == "at":
            departure, window = _at(day, when["time"], zone), None
        else:
            departure = _at(day, when["start"], zone)
            window = (departure, _at(day, when["end"], zone))
        if departure <= now:
            continue
        found.append(Occurrence(routine["_id"], leg_index, day, departure, departure - heads_up, window))
    return found


def demo_occurrence(routine: dict, override: dict) -> Occurrence | None:
    """A "fire heads-up now" override: the leg departs at the override's time, heads-up starts now."""
    leg_index = override["leg"]
    if not 0 <= leg_index < len(routine.get("legs", [])):
        return None
    zone = ZoneInfo(routine.get("tz") or DEFAULT_TZ)
    departure = override["departure_at"]
    if departure.tzinfo is None:  # Mongo returns naive UTC datetimes
        departure = departure.replace(tzinfo=timezone.utc)
    departure = departure.astimezone(zone)
    heads_up = timedelta(minutes=routine.get("heads_up_minutes", 30))
    return Occurrence(routine["_id"], leg_index, departure.date(), departure, departure - heads_up, demo=True)


def upcoming(routines: list[dict], overrides: list[dict], now: datetime, days: int = 7) -> list[Occurrence]:
    """Soonest first, over every active routine; a demo override comes first for its leg."""
    items = []
    by_id = {r["_id"]: r for r in routines if r.get("active", True)}
    for override in overrides:
        routine = by_id.get(override["routine_id"])
        occurrence = demo_occurrence(routine, override) if routine else None
        if occurrence and occurrence.departure_at > now:
            items.append(occurrence)
    for routine in by_id.values():
        for leg_index in range(len(routine.get("legs", []))):
            items.extend(leg_occurrences(routine, leg_index, now, days))
    return sorted(items, key=lambda o: (o.departure_at, not o.demo, o.routine_id, o.leg))

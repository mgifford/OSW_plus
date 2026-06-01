from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

TIMEFRAME_MAP = {
    "The Runway (Weekend Before: June 20-21)": "runway",
    "Weekday Breakfast (7:30 AM - 9:00 AM)": "weekday_breakfast",
    "Weekday Daytime (9:00 AM - 5:30 PM)": "weekday_daytime",
    "Weekday After-Hours (5:30 PM Onward)": "weekday_evening",
    "The Aftermath (Weekend After: June 27-28)": "aftermath",
}

TIME_RANGES = {
    "runway": ("10:00", "18:00"),
    "weekday_breakfast": ("07:30", "09:00"),
    "weekday_daytime": ("09:00", "17:30"),
    "weekday_evening": ("17:30", "21:30"),
    "aftermath": ("10:00", "16:00"),
}

# Calendar dates that belong exclusively to each non-weekday section.
# These are used to override a mismatched user-supplied timeframe.
_RUNWAY_DATES: frozenset[str] = frozenset({"2026-06-20", "2026-06-21"})
_AFTERMATH_DATES: frozenset[str] = frozenset({"2026-06-27", "2026-06-28"})
_CORE_WEEK_DATES: frozenset[str] = frozenset({
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
})


def load_events(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
        if not isinstance(data, list):
            raise ValueError("events.json must contain a JSON array")
        return data


def save_events(path: str | Path, events: list[dict[str, Any]]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as file:
        json.dump(sorted(events, key=lambda item: (item.get("event_date", ""), item.get("start_time", ""))), file, indent=2)
        file.write("\n")


def parse_issue_form_markdown(markdown: str) -> dict[str, str]:
    sections = {}
    matches = list(re.finditer(r"^###\s+(.*?)\s*$", markdown, flags=re.MULTILINE))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        key = match.group(1).strip().lower()
        value = markdown[start:end].strip()
        if value and value != "_No response_":
            sections[key] = value
    return sections


def normalize_timeframe(value: str) -> str:
    return TIMEFRAME_MAP.get(value.strip(), "weekday_evening")


def next_event_id(events: list[dict[str, Any]], year: int) -> str:
    prefix = f"evt-{year}-"
    last_number = 0
    for event in events:
        event_id = str(event.get("id", ""))
        if event_id.startswith(prefix):
            try:
                last_number = max(last_number, int(event_id.rsplit("-", maxsplit=1)[-1]))
            except ValueError:
                continue
    return f"{prefix}{last_number + 1:03d}"


def _reconcile_timeframe(timeframe: str, date_str: str) -> str:
    """Return the correct timeframe for *date_str*, overriding *timeframe* where needed.

    Weekend dates (Runway / Aftermath) are authoritative: if the calendar date
    falls on a runway or aftermath weekend, the timeframe is forced to the
    matching value regardless of what the submitter chose.  Conversely, if the
    date is a Core Week weekday (June 22–26) but the submitter picked "runway"
    or "aftermath", the timeframe is corrected to "weekday_evening" so the
    event does not appear in the wrong section of the site.
    """
    if date_str in _RUNWAY_DATES:
        return "runway"
    if date_str in _AFTERMATH_DATES:
        return "aftermath"
    if date_str in _CORE_WEEK_DATES and timeframe in ("runway", "aftermath"):
        # Core-week date was incorrectly tagged as a weekend section.
        return "weekday_evening"
    return timeframe


_INVITE_ONLY_PATTERN = re.compile(
    r"\b(?:invite[- ]only|invitation[- ]only|by invitation|invitees? only)\b",
    re.IGNORECASE,
)
_REGISTRATION_REQUIRED_PATTERN = re.compile(
    r"\b(?:registration required|rsvp required|tickets? required)\b",
    re.IGNORECASE,
)


def detect_access_level(text: str) -> str:
    """Return ``'invite_only'``, ``'registration_required'``, or ``'public'``.

    Scans *text* for common phrases that indicate restricted access.  The
    detection is intentionally conservative: if no phrase is matched the event
    is assumed to be public so that legitimate public events are never hidden.
    """
    if _INVITE_ONLY_PATTERN.search(text):
        return "invite_only"
    if _REGISTRATION_REQUIRED_PATTERN.search(text):
        return "registration_required"
    return "public"


def build_event_from_submission(fields: dict[str, str], issue_number: int, existing_events: list[dict[str, Any]]) -> dict[str, Any]:
    date_value = datetime.strptime(fields["exact date"], "%Y-%m-%d").date()
    timeframe = normalize_timeframe(fields["when is it happening?"])
    timeframe = _reconcile_timeframe(timeframe, date_value.isoformat())
    start_time, end_time = TIME_RANGES[timeframe]

    access = (fields.get("access level") or "public").strip().lower().replace(" ", "_")
    if access not in {"public", "invite_only", "registration_required"}:
        access = "public"

    return {
        "id": next_event_id(existing_events, date_value.year),
        "title": fields["event title"],
        "organizer": fields.get("organizer / community", "Community Submission"),
        "timeframe": timeframe,
        "event_date": date_value.isoformat(),
        "start_time": start_time,
        "end_time": end_time,
        "timezone": "America/New_York",
        "location": {
            "name": fields.get("venue name (optional)", fields.get("address (optional)", "TBD")),
            "neighborhood": fields.get("neighborhood (optional)", "TBD"),
            "address": fields.get("address (optional)", "TBD"),
        },
        "summary": fields["brief event summary"],
        "access": access,
        "original_source_url": fields["original event link (rsvp page)"],
        "submission_source": f"github_issue_{issue_number}",
    }


def event_exists(events: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    for event in events:
        if (
            event.get("title") == candidate.get("title")
            and event.get("event_date") == candidate.get("event_date")
            and event.get("original_source_url") == candidate.get("original_source_url")
        ):
            return True
    return False

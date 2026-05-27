from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

TIMEFRAME_MAP = {
    "The Runway (Weekend Before: June 20-21)": "runway",
    "Weekday Breakfast (7:30 AM - 9:00 AM)": "weekday_breakfast",
    "Weekday After-Hours (5:30 PM Onward)": "weekday_evening",
    "The Aftermath (Weekend After: June 27-28)": "aftermath",
}

TIME_RANGES = {
    "runway": ("10:00", "18:00"),
    "weekday_breakfast": ("07:30", "09:00"),
    "weekday_evening": ("17:30", "21:30"),
    "aftermath": ("10:00", "16:00"),
}


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


def build_event_from_submission(fields: dict[str, str], issue_number: int, existing_events: list[dict[str, Any]]) -> dict[str, Any]:
    date_value = datetime.strptime(fields["exact date"], "%Y-%m-%d").date()
    timeframe = normalize_timeframe(fields["when is it happening?"])
    start_time, end_time = TIME_RANGES[timeframe]

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

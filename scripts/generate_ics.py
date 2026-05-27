#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from event_utils import load_events


def to_ics_dt(date_value: str, time_value: str) -> str:
    dt = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
    return dt.strftime("%Y%m%dT%H%M%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate /calendar.ics from events.json")
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--output-file", required=True)
    args = parser.parse_args()

    events = load_events(args.events_file)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OSWeek Plus NYC//Community Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for event in events:
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event['id']}@osweekplus.nyc",
                f"SUMMARY:{event['title']}",
                f"DTSTART;TZID={event.get('timezone', 'America/New_York')}:{to_ics_dt(event['event_date'], event['start_time'])}",
                f"DTEND;TZID={event.get('timezone', 'America/New_York')}:{to_ics_dt(event['event_date'], event['end_time'])}",
                f"DESCRIPTION:{event.get('summary', '').replace('\n', ' ')}\\nRSVP: {event.get('original_source_url', '')}",
                f"LOCATION:{event.get('location', {}).get('address', 'New York, NY')}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse
from datetime import datetime

from event_utils import TIME_RANGES, event_exists, load_events, next_event_id, save_events

# Expected source line format: YYYY-MM-DD | Event Title | https://event-url.example
LINE_PATTERN = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s*[|,-]\s*(?P<title>[^|]+?)\s*[|,-]\s*(?P<url>https?://\S+)")


def fetch_text(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"Unsupported source URL: {url}")

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        raise RuntimeError(f"Failed to fetch source URL {url}") from error


def infer_timeframe(text_line: str) -> str:
    line = text_line.lower()
    if "breakfast" in line or "coffee" in line:
        return "weekday_breakfast"
    if "runway" in line or "weekend before" in line:
        return "runway"
    if "aftermath" in line or "weekend after" in line:
        return "aftermath"
    return "weekday_evening"


def parse_events(raw_text: str, existing_events: list[dict], source_name: str) -> list[dict]:
    parsed = []
    for line in raw_text.splitlines():
        match = LINE_PATTERN.search(line)
        if not match:
            continue

        event_date = datetime.strptime(match.group("date"), "%Y-%m-%d").date().isoformat()
        timeframe = infer_timeframe(line)
        start_time, end_time = TIME_RANGES[timeframe]
        candidate = {
            "id": next_event_id(existing_events + parsed, 2026),
            "title": match.group("title").strip(),
            "organizer": "External Community Listing",
            "timeframe": timeframe,
            "event_date": event_date,
            "start_time": start_time,
            "end_time": end_time,
            "timezone": "America/New_York",
            "location": {
                "name": "TBD",
                "neighborhood": "TBD",
                "address": "New York, NY",
            },
            "summary": "Imported from community sync pad.",
            "original_source_url": match.group("url").strip(),
            "submission_source": source_name,
        }
        if not event_exists(existing_events + parsed, candidate):
            parsed.append(candidate)
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape HackMD schedule pads and ingest missing events")
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--api-file", required=True)
    parser.add_argument("--source", action="append", default=[])
    args = parser.parse_args()

    events = load_events(args.events_file)
    for source in args.source:
        raw_text = fetch_text(source)
        events.extend(parse_events(raw_text, events, source_name=f"hackmd:{source}"))

    save_events(args.events_file, events)
    save_events(args.api_file, events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

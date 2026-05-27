#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from event_utils import build_event_from_submission, event_exists, load_events, parse_issue_form_markdown, save_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert issue-form submissions to events.json entries")
    parser.add_argument("--issue-body-file", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--api-file", required=True)
    args = parser.parse_args()

    issue_body = Path(args.issue_body_file).read_text(encoding="utf-8")
    fields = parse_issue_form_markdown(issue_body)

    required_fields = [
        "event title",
        "when is it happening?",
        "exact date",
        "original event link (rsvp page)",
        "brief event summary",
    ]
    missing = [field for field in required_fields if field not in fields]
    if missing:
        raise ValueError(f"Submission is missing required fields: {', '.join(missing)}")

    events = load_events(args.events_file)
    candidate = build_event_from_submission(fields, args.issue_number, events)
    if not event_exists(events, candidate):
        events.append(candidate)

    save_events(args.events_file, events)
    save_events(args.api_file, events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

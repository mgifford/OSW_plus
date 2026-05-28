#!/usr/bin/env python3
"""Scrape HackMD schedule pads and ingest missing events.

Two parsing strategies are supported:

1. **Simple line format** (legacy / generic pads):
   Each line must match: ``YYYY-MM-DD | Event Title | https://event-url.example``

2. **DPGA agenda format** (https://hackmd.io/@dpga/Sk05Nc21Me):
   Markdown with day-section headings and pipe-delimited tables::

       ## Section Name — Weekday DD Month

       | Event | Location | Time |
       | --- | --- | --- |
       | Event Title | Venue | 10:00 - 18:00 |

   Date is inferred from the ``DD Month`` in the heading (year defaults to
   2026).  The ``original_source_url`` for each event is set to the HackMD
   page URL with an anchor pointing to its day section.

Usage::

    # Generic / simple-line pad
    python scripts/scrape_hackmd.py \\
        --events-file data/2026/events.json \\
        --api-file    api/2026/events.json \\
        --source      "https://hackmd.io/some-pad/download"

    # DPGA agenda pad
    python scripts/scrape_hackmd.py \\
        --events-file data/2026/events.json \\
        --api-file    api/2026/events.json \\
        --dpga-source "https://hackmd.io/@dpga/Sk05Nc21Me/download" \\
        --dpga-page   "https://hackmd.io/@dpga/Sk05Nc21Me"
"""
from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse
from datetime import datetime

from event_utils import TIME_RANGES, event_exists, load_events, next_event_id, save_events

# ---------------------------------------------------------------------------
# Strategy 1: simple line format  YYYY-MM-DD | Title | URL
# ---------------------------------------------------------------------------

LINE_PATTERN = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s*[|,-]\s*(?P<title>[^|]+?)\s*[|,-]\s*(?P<url>https?://\S+)")

# ---------------------------------------------------------------------------
# Strategy 2: DPGA agenda format
# ---------------------------------------------------------------------------

# Matches headings like "## UN Tech Over — Monday 22 June"
# or "## Digital Public Goods — Tuesday 23 June 2026"
_SECTION_HEADING = re.compile(
    r"^#{1,3}\s+(?P<heading>.+?)\s*—\s*"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)"
    r"(?:\s+(?P<year>\d{4}))?",
    re.IGNORECASE,
)

_MONTH_NUMS: dict[str, str] = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}

# Time range in cell: "10:00 - 18:00" or "10:00–18:00" or "10:00 – 18:00"
_TIME_RANGE = re.compile(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})")

# Pipe-delimited table row (at least two cells)
_TABLE_ROW = re.compile(r"^\|(.+)\|$")

# Characters stripped from the end of a title extracted from an inline text line.
_TITLE_TRAILING_CHARS = "\u2013\u2014-|,\t "


def _is_table_separator_row(line: str) -> bool:
    """Return True if *line* is a markdown table separator like ``| --- | --- |``."""
    return (
        line.startswith("|")
        and set(line.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")) == set()
    )


def _heading_to_anchor(heading_text: str) -> str:
    """Convert a markdown heading text to a HackMD URL anchor fragment.

    HackMD slugifies heading text by replacing spaces with hyphens and
    percent-encoding non-ASCII characters (keeping the original casing).
    """
    slug = heading_text.replace(" ", "-")
    return urllib.parse.quote(slug, safe="-_.~")


def _infer_timeframe_from_times(start: str, end: str) -> str:
    """Return the closest timeframe key based on extracted start/end times."""
    try:
        start_h, start_m = (int(x) for x in start.split(":"))
    except ValueError:
        return "weekday_evening"
    start_minutes = start_h * 60 + start_m
    if start_minutes < 12 * 60:   # before noon → morning / runway
        return "runway"
    if start_minutes < 15 * 60:   # 12:00–14:59 → daytime, treat as runway
        return "runway"
    return "weekday_evening"


def parse_dpga_events(
    raw_markdown: str,
    page_url: str,
    existing_events: list[dict],
    source_name: str,
    default_year: int = 2026,
) -> list[dict]:
    """Parse DPGA-style agenda markdown and return new event dicts.

    Each event's ``original_source_url`` is set to ``page_url`` with an
    anchor fragment derived from the day-section heading so reviewers can
    navigate directly to the correct section.

    Args:
        raw_markdown: Raw markdown text downloaded from HackMD.
        page_url: Public (non-download) URL of the HackMD page, used as the
            base for anchor links (e.g. ``https://hackmd.io/@dpga/Sk05Nc21Me``).
        existing_events: Already-known events used for deduplication.
        source_name: Value for the ``submission_source`` field.
        default_year: Year to use when the heading omits the year (default 2026).
    """
    parsed: list[dict] = []
    current_date: str | None = None
    current_anchor: str | None = None
    in_table = False

    for line in raw_markdown.splitlines():
        # Check for a day-section heading
        heading_match = _SECTION_HEADING.match(line)
        if heading_match:
            current_date = None
            current_anchor = None
            in_table = False
            day = heading_match.group("day").zfill(2)
            month = _MONTH_NUMS.get(heading_match.group("month").lower())
            year = heading_match.group("year") or str(default_year)
            if month:
                current_date = f"{year}-{month}-{day}"
                # Build the full heading text to derive the anchor
                # Reconstruct the original heading by stripping the leading #
                raw_heading = line.lstrip("#").strip()
                current_anchor = _heading_to_anchor(raw_heading)
            continue

        if current_date is None:
            continue

        # Detect start / end of a pipe table
        stripped = line.strip()
        if _is_table_separator_row(stripped):
            # Separator row like "| --- | --- |"
            in_table = True
            continue

        row_match = _TABLE_ROW.match(stripped)
        if row_match:
            cells = [c.strip() for c in row_match.group(1).split("|")]
            if not cells:
                continue

            # Detect header row (contains no time pattern)
            has_time = any(_TIME_RANGE.search(c) for c in cells)
            if not has_time and not in_table:
                in_table = True  # first row = header row
                continue
            if not has_time:
                # Still a header / separator row
                continue

            title = cells[0].strip()
            if not title or title.lower() in {"event", "title", "name", "session"}:
                continue

            # Extract time from any cell
            start_time: str | None = None
            end_time: str | None = None
            for cell in cells:
                tm = _TIME_RANGE.search(cell)
                if tm:
                    start_time = tm.group(1)
                    end_time = tm.group(2)
                    break

            if start_time is None:
                start_time, end_time = TIME_RANGES["weekday_evening"]

            timeframe = _infer_timeframe_from_times(start_time, end_time or "")

            # Location is the cell that contains neither a time range nor the title
            location_name = "TBD"
            for cell in cells[1:]:
                if cell and not _TIME_RANGE.search(cell) and cell.lower() not in {"tbd", "tbc", ""}:
                    location_name = cell
                    break

            section_url = f"{page_url}#{current_anchor}" if current_anchor else page_url

            candidate: dict = {
                "id": next_event_id(existing_events + parsed, default_year),
                "title": title,
                "organizer": "Digital Public Goods Alliance",
                "timeframe": timeframe,
                "event_date": current_date,
                "start_time": start_time,
                "end_time": end_time or TIME_RANGES[timeframe][1],
                "timezone": "America/New_York",
                "location": {
                    "name": location_name,
                    "neighborhood": "TBD",
                    "address": "New York, NY",
                },
                "summary": f"Imported from the DPGA UN Open Source Week schedule. See {section_url} for details.",
                "original_source_url": section_url,
                "submission_source": source_name,
            }
            if not event_exists(existing_events + parsed, candidate):
                parsed.append(candidate)
        else:
            # Outside a table: look for a time pattern on the line itself to
            # handle bulleted lists or plain-text event rows.
            tm = _TIME_RANGE.search(stripped)
            if not tm:
                continue
            # Try to extract a title from the same line (text before the time)
            title = stripped[: tm.start()].strip().rstrip(_TITLE_TRAILING_CHARS)
            if not title:
                continue

            start_time = tm.group(1)
            end_time = tm.group(2)
            timeframe = _infer_timeframe_from_times(start_time, end_time)
            section_url = f"{page_url}#{current_anchor}" if current_anchor else page_url

            candidate = {
                "id": next_event_id(existing_events + parsed, default_year),
                "title": title,
                "organizer": "Digital Public Goods Alliance",
                "timeframe": timeframe,
                "event_date": current_date,
                "start_time": start_time,
                "end_time": end_time,
                "timezone": "America/New_York",
                "location": {
                    "name": "TBD",
                    "neighborhood": "TBD",
                    "address": "New York, NY",
                },
                "summary": f"Imported from the DPGA UN Open Source Week schedule. See {section_url} for details.",
                "original_source_url": section_url,
                "submission_source": source_name,
            }
            if not event_exists(existing_events + parsed, candidate):
                parsed.append(candidate)

    return parsed


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
    """Parse the legacy simple-line format: ``YYYY-MM-DD | Title | URL``."""
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape HackMD schedule pads and ingest missing events")
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--api-file", required=True)
    parser.add_argument(
        "--source", action="append", default=[],
        metavar="URL",
        help="Simple-line-format pad download URL (repeatable)",
    )
    parser.add_argument(
        "--dpga-source", action="append", default=[],
        metavar="DOWNLOAD_URL",
        help="DPGA agenda pad raw/download URL (repeatable)",
    )
    parser.add_argument(
        "--dpga-page", action="append", default=[],
        metavar="PAGE_URL",
        help=(
            "Public HackMD page URL corresponding to each --dpga-source, "
            "used to build anchor links. Provide in the same order as --dpga-source."
        ),
    )
    args = parser.parse_args()

    events = load_events(args.events_file)

    for source in args.source:
        raw_text = fetch_text(source)
        events.extend(parse_events(raw_text, events, source_name=f"hackmd:{source}"))

    dpga_pages = args.dpga_page or []
    for idx, dpga_source in enumerate(args.dpga_source):
        page_url = dpga_pages[idx] if idx < len(dpga_pages) else dpga_source.replace("/download", "")
        raw_text = fetch_text(dpga_source)
        new_events = parse_dpga_events(raw_text, page_url, events, source_name=f"hackmd-dpga:{dpga_source}")
        print(f"[scrape_hackmd] DPGA strategy: found {len(new_events)} new event(s) from {dpga_source}")
        events.extend(new_events)

    save_events(args.events_file, events)
    save_events(args.api_file, events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

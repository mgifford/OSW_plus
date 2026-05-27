#!/usr/bin/env python3
"""Scrape external event agenda pages (HTML) and ingest missing events.

Strategies tried in order:
  1. JSON-LD ``schema.org/Event`` objects embedded in ``<script>`` tags.
  2. Regex-based HTML-block scanning for any block that contains a 2026-06
     date and a plausible event title.

Only events whose date falls in June 2026 are imported.  Every imported
event carries ``original_source_url`` pointing back to the authoritative
source so the site stays a summary, not a duplicate.

Usage::

    python scripts/scrape_agenda.py \\
        --events-file data/2026/events.json \\
        --api-file    api/2026/events.json \\
        --source      "https://www.unopensource.org/agenda"

Add ``--dry-run`` to print candidates without writing any files.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from datetime import datetime
from typing import Any

from event_utils import TIME_RANGES, event_exists, load_events, next_event_id, save_events

# ---------------------------------------------------------------------------
# Date normalisation helpers
# ---------------------------------------------------------------------------

_MONTH_MAP: dict[str, str] = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# Patterns that can appear in raw HTML/text for a 2026 date
_DATE_PATTERNS: list[re.Pattern[str]] = [
    # ISO: 2026-06-23
    re.compile(r"\b(2026-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))\b"),
    # US long: June 23, 2026  /  June 23 2026
    re.compile(
        r"\b((?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+2026)\b",
        re.IGNORECASE,
    ),
    # Short: Jun 23, 2026
    re.compile(
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+2026)\b",
        re.IGNORECASE,
    ),
]

_STRPTIME_FORMATS = (
    "%B %d %Y", "%B %d, %Y",
    "%b %d %Y", "%b %d, %Y", "%b. %d %Y", "%b. %d, %Y",
)


def normalize_date(raw: str) -> str | None:
    """Return an ISO ``YYYY-MM-DD`` string, or ``None`` if the date cannot be parsed."""
    raw = raw.strip().rstrip(",")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    # Named-month splitting
    parts = re.split(r"[\s,]+", raw)
    if len(parts) >= 3:
        try:
            year = parts[-1]
            day = parts[-2].lstrip("0") or "1"
            month_key = parts[-3].lower().rstrip(".")
            month = _MONTH_MAP.get(month_key)
            if month and len(year) == 4 and year.isdigit():
                return f"{year}-{month}-{day.zfill(2)}"
        except (IndexError, ValueError):
            pass
    for fmt in _STRPTIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# JSON-LD extractor
# ---------------------------------------------------------------------------

class _JsonLdExtractor(HTMLParser):
    """Collects all ``<script type="application/ld+json">`` payloads."""

    def __init__(self) -> None:
        super().__init__()
        self._in_jsonld = False
        self._buffer: list[str] = []
        self.results: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._in_jsonld = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            raw = "".join(self._buffer).strip()
            if raw:
                try:
                    self.results.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "OSW+ Event Monitor/1.0 "
            "(https://github.com/mgifford/OSW_plus; community event sync bot)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc


# ---------------------------------------------------------------------------
# Strategy 1: JSON-LD
# ---------------------------------------------------------------------------

def _events_from_jsonld_item(
    item: Any,
    source_url: str,
    existing: list[dict],
    source_name: str,
) -> list[dict]:
    """Recursively extract Event objects from a single JSON-LD item."""
    events: list[dict] = []
    if not isinstance(item, dict):
        return events

    # Recurse into @graph arrays
    if "@graph" in item:
        for sub in item["@graph"] if isinstance(item["@graph"], list) else [item["@graph"]]:
            events.extend(_events_from_jsonld_item(sub, source_url, existing + events, source_name))
        return events

    schema_type = item.get("@type", "")
    types = schema_type if isinstance(schema_type, list) else [schema_type]
    if not any("Event" in str(t) for t in types):
        return events

    # Date
    raw_date = item.get("startDate") or item.get("startdate") or ""
    event_date = raw_date[:10] if len(raw_date) >= 10 else None
    if not event_date or not event_date.startswith("2026-06"):
        return events

    title = (item.get("name") or item.get("headline") or "").strip()
    if not title:
        return events

    event_url = item.get("url") or item.get("sameAs") or source_url
    if isinstance(event_url, list):
        event_url = event_url[0] if event_url else source_url

    description = (item.get("description") or "").strip()

    location_data = item.get("location") or {}
    if isinstance(location_data, dict):
        loc_name = location_data.get("name") or "TBD"
        loc_address = location_data.get("address") or {}
        if isinstance(loc_address, dict):
            street = loc_address.get("streetAddress") or ""
            city = loc_address.get("addressLocality") or "New York, NY"
            address_str = f"{street}, {city}".lstrip(", ")
        else:
            address_str = str(loc_address) or "New York, NY"
    else:
        loc_name = "TBD"
        address_str = "New York, NY"

    organizer = item.get("organizer") or {}
    if isinstance(organizer, dict):
        organizer_name = organizer.get("name") or "UN Open Source Week"
    elif isinstance(organizer, list) and organizer and isinstance(organizer[0], dict):
        organizer_name = organizer[0].get("name") or "UN Open Source Week"
    else:
        organizer_name = "UN Open Source Week"

    candidate: dict = {
        "id": next_event_id(existing + events, 2026),
        "title": title[:200],
        "organizer": organizer_name,
        "timeframe": "weekday_evening",
        "event_date": event_date,
        "start_time": TIME_RANGES["weekday_evening"][0],
        "end_time": TIME_RANGES["weekday_evening"][1],
        "timezone": "America/New_York",
        "location": {
            "name": loc_name,
            "neighborhood": "TBD",
            "address": address_str,
        },
        "summary": (description[:500] if description else f"See {source_url} for full details."),
        "original_source_url": str(event_url),
        "submission_source": source_name,
    }
    if not event_exists(existing + events, candidate):
        events.append(candidate)
    return events


def events_from_jsonld(
    html: str,
    source_url: str,
    existing: list[dict],
    source_name: str,
) -> list[dict]:
    extractor = _JsonLdExtractor()
    extractor.feed(html)
    events: list[dict] = []
    for ld in extractor.results:
        items = ld if isinstance(ld, list) else [ld]
        for item in items:
            events.extend(
                _events_from_jsonld_item(item, source_url, existing + events, source_name)
            )
    return events


# ---------------------------------------------------------------------------
# Strategy 2: HTML block pattern matching
# ---------------------------------------------------------------------------

_STRIP_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_HREF = re.compile(r'href=["\']?(https?://[^\s"\'<>]+)["\']?', re.IGNORECASE)
_DIGITS_AND_PUNCT = re.compile(r'^[\d\s,/:–—-]+$')


def events_from_html_patterns(
    html: str,
    source_url: str,
    existing: list[dict],
    source_name: str,
) -> list[dict]:
    """Scan HTML blocks for 2026-06 dates and extract minimal event stubs."""
    events: list[dict] = []
    # Split at any block-level element open tag
    blocks = re.split(r'<(?:div|li|article|section|tr|p|h[1-6])[^>]*>', html, flags=re.IGNORECASE)
    for block in blocks:
        text = _WHITESPACE.sub(" ", _STRIP_TAGS.sub(" ", block)).strip()
        if len(text) < 15:
            continue

        date_str: str | None = None
        for pattern in _DATE_PATTERNS:
            m = pattern.search(text)
            if m:
                candidate_date = normalize_date(m.group(1))
                if candidate_date and candidate_date.startswith("2026-06"):
                    date_str = candidate_date
                    break

        if not date_str:
            continue

        hrefs = _HREF.findall(block)
        event_url = hrefs[0] if hrefs else source_url

        # Use the longest non-date text fragment as a title candidate
        sentences = [s.strip() for s in re.split(r'[|\n]', text) if len(s.strip()) > 8]
        title_candidate = ""
        for sent in sentences:
            if not _DIGITS_AND_PUNCT.match(sent) and len(sent) > len(title_candidate):
                title_candidate = sent
        if not title_candidate:
            title_candidate = f"Event on {date_str}"

        candidate: dict = {
            "id": next_event_id(existing + events, 2026),
            "title": title_candidate[:200],
            "organizer": "UN Open Source Week",
            "timeframe": "weekday_evening",
            "event_date": date_str,
            "start_time": TIME_RANGES["weekday_evening"][0],
            "end_time": TIME_RANGES["weekday_evening"][1],
            "timezone": "America/New_York",
            "location": {
                "name": "TBD",
                "neighborhood": "TBD",
                "address": "New York, NY",
            },
            "summary": f"Imported from {source_url}. See the original page for full details.",
            "original_source_url": event_url,
            "submission_source": source_name,
        }
        if not event_exists(existing + events, candidate):
            events.append(candidate)

    return events


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def parse_events_from_page(
    html: str,
    source_url: str,
    existing: list[dict],
    source_name: str,
) -> list[dict]:
    """Try JSON-LD first, then fall back to HTML pattern matching."""
    events = events_from_jsonld(html, source_url, existing, source_name)
    if events:
        print(f"[scrape_agenda] JSON-LD strategy: found {len(events)} new event(s) from {source_url}")
        return events

    events = events_from_html_patterns(html, source_url, existing, source_name)
    if events:
        print(f"[scrape_agenda] HTML-pattern strategy: found {len(events)} new event(s) from {source_url}")
    else:
        print(
            f"[scrape_agenda] WARNING: no events found at {source_url}. "
            "The page may require JavaScript rendering or use an unsupported structure. "
            "Consider inspecting the page source and extending the parser.",
            file=sys.stderr,
        )
    return events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape HTML agenda pages and ingest missing June 2026 events."
    )
    parser.add_argument("--events-file", required=True, help="Path to data/2026/events.json")
    parser.add_argument("--api-file", required=True, help="Path to api/2026/events.json")
    parser.add_argument(
        "--source", action="append", default=[],
        metavar="URL", help="Agenda page URL (repeatable)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print candidates without writing files",
    )
    args = parser.parse_args()

    events = load_events(args.events_file)
    new_total = 0

    for source in args.source:
        html = fetch_html(source)
        new_events = parse_events_from_page(
            html, source, events, source_name=f"scrape:{source}"
        )
        if args.dry_run:
            for evt in new_events:
                print(json.dumps(evt, indent=2))
        else:
            events.extend(new_events)
        new_total += len(new_events)

    if not args.dry_run:
        save_events(args.events_file, events)
        save_events(args.api_file, events)
        print(f"[scrape_agenda] Done — {new_total} new event(s) ingested.")
    else:
        print(f"[scrape_agenda] Dry-run complete — {new_total} candidate(s) found (not written).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Scrape external event agenda pages (HTML) and ingest missing events.

Strategies tried in order:
  1. JSON-LD ``schema.org/Event`` objects embedded in ``<script>`` tags.
  2. Raw Webflow tab-panel parsing for the agenda's day tabs and nested
      event cards.
  3. Regex-based HTML-block scanning for any remaining blocks that contain a
      2026-06 date and a plausible event title.

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
import html as _html
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from datetime import datetime
from typing import Any

from event_utils import TIME_RANGES, detect_access_level, event_exists, load_events, next_event_id, save_events

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
_SCRIPT_BLOCKS = re.compile(r"<(?:script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)>", re.IGNORECASE | re.DOTALL)
_MD_LINK_TRAILING = re.compile(r"\s*\(\[[^\]]+\]\(https?://[^)]+\)\)\.?$")
_BRACKETED_LINK = re.compile(r"\[([^\]]+)\]\(https?://[^)]+\)")
_TOP_DAY_TAB = re.compile(
    r'<a\b(?=[^>]*\bdata-w-tab=["\'](?P<tab>Tab \d+)["\'])[^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_DAY_PANE_START = re.compile(
    r'<div\b(?=[^>]*\bdata-w-tab=["\'](?P<tab>Tab \d+)["\'])(?=[^>]*\bclass=["\'][^"\']*w-tab-pane[^"\']*["\'])[^>]*>',
    re.IGNORECASE,
)
_EVENT_CARD_START = re.compile(
    r'<div\b(?=[^>]*\bclass=["\'][^"\']*eventcardlink-local-w[^"\']*["\'])[^>]*>',
    re.IGNORECASE,
)
_TITLE_BLOCK = re.compile(
    r'<h2\b[^>]*class=["\'][^"\']*title-local[^"\']*["\'][^>]*>(.*?)</h2>',
    re.IGNORECASE | re.DOTALL,
)
_SCHEDULE_TEXT = re.compile(
    r'<div\b[^>]*class=["\'][^"\']*event-schedule-text[^"\']*["\'][^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_LOCATION_TEXT = re.compile(
    r'<div\b[^>]*class=["\'][^"\']*event-adr-text-b[^"\']*["\'][^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_DESCRIPTION_TEXT = re.compile(
    r'<div\b[^>]*class=["\'][^"\']*member-designation[^"\']*["\'][^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)


def _clean_event_title(raw_title: str) -> str:
    text = _html.unescape(raw_title or "")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _MD_LINK_TRAILING.sub("", text)
    text = _BRACKETED_LINK.sub(r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .-–—\t")


def _text_from_html(raw_html: str) -> str:
    text = _html.unescape(raw_html or "")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .-–—\t")


def _date_from_day_label(label_html: str) -> str | None:
    label = _text_from_html(label_html)
    match = re.search(r"(?P<day>\d{1,2})\s+June", label, flags=re.IGNORECASE)
    if not match:
        return None
    day = match.group("day").zfill(2)
    return f"2026-06-{day}"


def _consume_div_block(html: str, start: int) -> int:
    depth = 0
    for match in re.finditer(r"</?div\b[^>]*>", html[start:], flags=re.IGNORECASE):
        token = match.group(0)
        if token.startswith("</"):
            depth -= 1
            if depth == 0:
                return start + match.end()
        else:
            depth += 1
    return len(html)


def _extract_day_panels(html: str) -> list[tuple[str, str]]:
    tabs: list[tuple[str, str]] = []
    for match in _TOP_DAY_TAB.finditer(html):
        tab = match.group("tab")
        date = _date_from_day_label(match.group("body"))
        if date:
            tabs.append((tab, date))

    schedule_start = html.find('schedule-tabs-content w-tab-content')
    if schedule_start == -1:
        return []

    panels: list[tuple[str, str]] = []
    cursor = schedule_start
    ordered_tabs = sorted(tabs, key=lambda item: int(item[0].split()[1]))
    for _tab, date in ordered_tabs:
        pane_match = _DAY_PANE_START.search(html, cursor)
        if not pane_match:
            break
        start = pane_match.start()
        end = _consume_div_block(html, start)
        panels.append((date, html[start:end]))
        cursor = end
    return panels


def _event_cards_from_panel(panel_html: str) -> list[str]:
    cards: list[str] = []
    cursor = 0
    while True:
        match = _EVENT_CARD_START.search(panel_html, cursor)
        if not match:
            break
        start = match.start()
        end = _consume_div_block(panel_html, start)
        cards.append(panel_html[start:end])
        cursor = end
    return cards


def _candidate_from_event_card(
    card_html: str,
    event_date: str,
    source_url: str,
    existing: list[dict],
    source_name: str,
) -> dict | None:
    title_match = _TITLE_BLOCK.search(card_html)
    title = _clean_event_title(_text_from_html(title_match.group(1))) if title_match else ""
    if not title:
        return None

    schedule_texts = [_text_from_html(match.group(1)) for match in _SCHEDULE_TEXT.finditer(card_html)]
    schedule_texts = [text for text in schedule_texts if text and text != "-"]
    if len(schedule_texts) >= 2:
        start_time, end_time = schedule_texts[0], schedule_texts[1]
    elif len(schedule_texts) == 1:
        start_time = schedule_texts[0]
        end_time = TIME_RANGES["weekday_evening"][1]
    else:
        start_time, end_time = TIME_RANGES["weekday_evening"]

    location_match = _LOCATION_TEXT.search(card_html)
    location_name = _text_from_html(location_match.group(1)) if location_match else "TBD"

    descriptions = [
        _text_from_html(match.group(1))
        for match in _DESCRIPTION_TEXT.finditer(card_html)
    ]
    descriptions = [text for text in descriptions if text and text != title]
    summary = " ".join(dict.fromkeys(descriptions)).strip()
    if not summary:
        summary = f"Imported from {source_url}. See the original page for full details."

    candidate: dict = {
        "id": next_event_id(existing, 2026),
        "title": title[:200],
        "organizer": "UN Open Source Week",
        "timeframe": "weekday_evening",
        "event_date": event_date,
        "start_time": start_time,
        "end_time": end_time,
        "timezone": "America/New_York",
        "location": {
            "name": location_name,
            "neighborhood": "TBD",
            "address": "New York, NY",
        },
        "summary": summary[:500],
        "access": detect_access_level(_text_from_html(card_html)),
        "original_source_url": source_url,
        "submission_source": source_name,
    }
    return candidate if not event_exists(existing, candidate) else None


def events_from_agenda_tabpanels(
    html: str,
    source_url: str,
    existing: list[dict],
    source_name: str,
) -> list[dict]:
    events: list[dict] = []
    html = _SCRIPT_BLOCKS.sub(" ", html)
    for event_date, panel_html in _extract_day_panels(html):
        for card_html in _event_cards_from_panel(panel_html):
            candidate = _candidate_from_event_card(
                card_html,
                event_date,
                source_url,
                existing + events,
                source_name,
            )
            if candidate:
                events.append(candidate)
    return events


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
            "(https://github.com/mgifford/unosw.plus; community event sync bot)"
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
    inherited_context: dict[str, Any] | None = None,
) -> list[dict]:
    """Recursively extract Event objects from a single JSON-LD item."""
    events: list[dict] = []
    inherited_context = inherited_context or {}

    def _event_from_value(value: Any, fallback: str) -> str:
        if isinstance(value, dict):
            return (value.get("name") or fallback).strip() or fallback
        if isinstance(value, list):
            names = []
            for entry in value:
                if isinstance(entry, dict) and entry.get("name"):
                    names.append(str(entry["name"]).strip())
                elif isinstance(entry, str) and entry.strip():
                    names.append(entry.strip())
            return ", ".join(names) if names else fallback
        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    def _location_from_value(value: Any) -> tuple[str, str]:
        if isinstance(value, dict):
            loc_name = (value.get("name") or "TBD").strip() or "TBD"
            loc_address = value.get("address") or {}
            if isinstance(loc_address, dict):
                street = (loc_address.get("streetAddress") or "").strip()
                city = (loc_address.get("addressLocality") or "New York, NY").strip() or "New York, NY"
                address_str = f"{street}, {city}".lstrip(", ")
            else:
                address_str = str(loc_address).strip() or "New York, NY"
            return loc_name, address_str
        return "TBD", "New York, NY"

    if isinstance(item, list):
        for sub in item:
            events.extend(_events_from_jsonld_item(sub, source_url, existing + events, source_name, inherited_context))
        return events
    if not isinstance(item, dict):
        return events

    schema_type = item.get("@type", "")
    types = schema_type if isinstance(schema_type, list) else [schema_type]
    is_event = any("Event" in str(t) for t in types)

    raw_start = str(item.get("startDate") or item.get("startdate") or "").strip()
    raw_end = str(item.get("endDate") or item.get("enddate") or "").strip()

    nested_values: list[Any] = []
    for key in ("@graph", "about", "subEvent", "event", "mainEntity", "mainEntityOfPage", "hasPart", "subjectOf"):
        value = item.get(key)
        if value:
            nested_values.append(value)

    if is_event:
        event_date = raw_start[:10] if len(raw_start) >= 10 else None
        title = (item.get("name") or item.get("headline") or "").strip()
        is_container_event = bool(item.get("subEvent")) and raw_start[:10] and raw_end[:10] and raw_start[:10] != raw_end[:10]
        if event_date and event_date.startswith("2026-06") and title and not is_container_event:
            event_url = item.get("url") or item.get("sameAs") or source_url
            if isinstance(event_url, list):
                event_url = event_url[0] if event_url else source_url

            description = (item.get("description") or "").strip()
            loc_name, address_str = _location_from_value(item.get("location") or inherited_context.get("location"))
            organizer_name = _event_from_value(item.get("organizer") or inherited_context.get("organizer"), "UN Open Source Week")

            if "T" in raw_start:
                start_time = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).strftime("%H:%M")
                timeframe = "weekday_evening" if start_time >= TIME_RANGES["weekday_evening"][0] else "weekday_daytime"
            else:
                timeframe = "weekday_daytime"
                start_time = TIME_RANGES[timeframe][0]

            if raw_end and "T" in raw_end:
                end_time = datetime.fromisoformat(raw_end.replace("Z", "+00:00")).strftime("%H:%M")
            else:
                end_time = TIME_RANGES[timeframe][1]

            candidate: dict = {
                "id": next_event_id(existing + events, 2026),
                "title": title[:200],
                "organizer": organizer_name,
                "timeframe": timeframe,
                "event_date": event_date,
                "start_time": start_time,
                "end_time": end_time,
                "timezone": "America/New_York",
                "location": {
                    "name": loc_name,
                    "neighborhood": "TBD",
                    "address": address_str,
                },
                "summary": (description[:500] if description else f"See {source_url} for full details."),
                "access": detect_access_level(f"{title} {description}"),
                "original_source_url": str(event_url),
                "submission_source": source_name,
            }
            if not event_exists(existing + events, candidate):
                events.append(candidate)

    next_context = {
        "organizer": item.get("organizer") or inherited_context.get("organizer"),
        "location": item.get("location") or inherited_context.get("location"),
    }
    for nested in nested_values:
        events.extend(
            _events_from_jsonld_item(nested, source_url, existing + events, source_name, next_context)
        )
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
    html = _SCRIPT_BLOCKS.sub(" ", html)
    blocks = re.split(r'<(?:div|li|article|section|tr|p|h[1-6])[^>]*>', html, flags=re.IGNORECASE)
    texts = [_WHITESPACE.sub(" ", _STRIP_TAGS.sub(" ", b)).strip() for b in blocks]

    for idx, (block, text) in enumerate(zip(blocks, texts)):
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
            cleaned_sent = _clean_event_title(sent)
            if not cleaned_sent:
                continue
            if not _DIGITS_AND_PUNCT.match(cleaned_sent) and len(cleaned_sent) > len(title_candidate):
                title_candidate = cleaned_sent
        if not title_candidate:
            title_candidate = f"Event on {date_str}"

        # Check access level using the current block plus adjacent blocks for
        # context — invite-only/registration notices are often in a sibling
        # paragraph rather than the paragraph that contains the date itself.
        _CONTEXT_WINDOW = 3
        context_texts = texts[max(0, idx - _CONTEXT_WINDOW):idx + _CONTEXT_WINDOW + 1]
        access_context = " ".join(t for t in context_texts if t)

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
            "access": detect_access_level(access_context),
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
    """Try JSON-LD first, then Webflow tab panels, then HTML pattern matching."""
    events = events_from_jsonld(html, source_url, existing, source_name)
    if events:
        print(f"[scrape_agenda] JSON-LD strategy: found {len(events)} new event(s) from {source_url}")
        return events

    events = events_from_agenda_tabpanels(html, source_url, existing, source_name)
    if events:
        print(f"[scrape_agenda] tabpanel strategy: found {len(events)} new event(s) from {source_url}")
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

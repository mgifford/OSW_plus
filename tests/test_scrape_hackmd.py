"""Tests for scripts/scrape_hackmd.py — DPGA agenda parser."""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from scrape_hackmd import (  # noqa: E402
    _heading_to_anchor,
    parse_dpga_events,
    parse_events,
)

BASE_URL = "https://hackmd.io/@dpga/Sk05Nc21Me"

# ---------------------------------------------------------------------------
# _heading_to_anchor
# ---------------------------------------------------------------------------

class HeadingToAnchorTests(unittest.TestCase):
    def test_simple_ascii(self):
        self.assertEqual(_heading_to_anchor("Hello World"), "Hello-World")

    def test_em_dash_encoded(self):
        # "UN Tech Over — Monday 22 June" → spaces→dashes, em-dash percent-encoded
        heading = "UN Tech Over — Monday 22 June"
        anchor = _heading_to_anchor(heading)
        self.assertIn("%E2%80%94", anchor)
        self.assertEqual(anchor, "UN-Tech-Over-%E2%80%94-Monday-22-June")

    def test_already_ascii_no_spaces(self):
        self.assertEqual(_heading_to_anchor("NoSpaces"), "NoSpaces")


# ---------------------------------------------------------------------------
# parse_dpga_events — table format
# ---------------------------------------------------------------------------

_TABLE_MARKDOWN = """\
# UN Open Source Week — Fringe Events

## UN Tech Over — Monday 22 June

| Event | Location | Time |
| --- | --- | --- |
| UN Tech Over Hack-A-Thon, Edit-A-Thon, and Maintain-A-Thon | UN Conference Room A | 10:00 - 18:00 |
| Open Data Forum | UNDP HQ | 14:00 - 17:00 |

## Digital Futures — Tuesday 23 June

| Event | Location | Time |
| --- | --- | --- |
| Open Source AI Panel | Brookfield Place | 09:00 - 12:00 |
| Evening Social | TBD | 18:00 - 21:00 |
"""

class ParseDpgaEventsTableTests(unittest.TestCase):
    def setUp(self):
        self.events = parse_dpga_events(_TABLE_MARKDOWN, BASE_URL, [], "test")

    def test_extracts_correct_count(self):
        self.assertEqual(len(self.events), 4)

    def test_first_event_title(self):
        titles = [e["title"] for e in self.events]
        self.assertIn("UN Tech Over Hack-A-Thon, Edit-A-Thon, and Maintain-A-Thon", titles)

    def test_first_event_date(self):
        evt = next(e for e in self.events if "Hack-A-Thon" in e["title"])
        self.assertEqual(evt["event_date"], "2026-06-22")

    def test_first_event_times(self):
        evt = next(e for e in self.events if "Hack-A-Thon" in e["title"])
        self.assertEqual(evt["start_time"], "10:00")
        self.assertEqual(evt["end_time"], "18:00")

    def test_anchor_url_for_june22(self):
        evt = next(e for e in self.events if "Hack-A-Thon" in e["title"])
        self.assertEqual(
            evt["original_source_url"],
            f"{BASE_URL}#UN-Tech-Over-%E2%80%94-Monday-22-June",
        )

    def test_second_day_date(self):
        evt = next(e for e in self.events if "AI Panel" in e["title"])
        self.assertEqual(evt["event_date"], "2026-06-23")

    def test_second_day_anchor(self):
        evt = next(e for e in self.events if "AI Panel" in e["title"])
        self.assertIn("Digital-Futures", evt["original_source_url"])

    def test_location_extracted(self):
        evt = next(e for e in self.events if "Hack-A-Thon" in e["title"])
        self.assertEqual(evt["location"]["name"], "UN Conference Room A")

    def test_organizer_is_dpga(self):
        for evt in self.events:
            self.assertEqual(evt["organizer"], "Digital Public Goods Alliance")

    def test_submission_source(self):
        for evt in self.events:
            self.assertEqual(evt["submission_source"], "test")

    def test_deduplication(self):
        existing = self.events
        duplicates = parse_dpga_events(_TABLE_MARKDOWN, BASE_URL, existing, "test")
        self.assertEqual(len(duplicates), 0)

    def test_unique_ids(self):
        ids = [e["id"] for e in self.events]
        self.assertEqual(len(ids), len(set(ids)))


# ---------------------------------------------------------------------------
# parse_dpga_events — plain-text / inline-time format
# ---------------------------------------------------------------------------

_PLAINTEXT_MARKDOWN = """\
## Evening Meetup — Wednesday 24 June

- Open Source Drinks 18:00 - 21:00
- Hackathon Kick-off 19:00 - 22:00
"""

class ParseDpgaEventsPlainTextTests(unittest.TestCase):
    def test_extracts_inline_time_events(self):
        events = parse_dpga_events(_PLAINTEXT_MARKDOWN, BASE_URL, [], "test")
        self.assertGreaterEqual(len(events), 1)
        titles = [e["title"] for e in events]
        self.assertTrue(any("Open Source Drinks" in t for t in titles))

    def test_correct_date(self):
        events = parse_dpga_events(_PLAINTEXT_MARKDOWN, BASE_URL, [], "test")
        for evt in events:
            self.assertEqual(evt["event_date"], "2026-06-24")


# ---------------------------------------------------------------------------
# parse_dpga_events — year in heading
# ---------------------------------------------------------------------------

_WITH_YEAR_MARKDOWN = """\
## Summit — Friday 26 June 2026

| Event | Location | Time |
| --- | --- | --- |
| Closing Ceremony | Main Hall | 15:00 - 17:00 |
"""

class ParseDpgaEventsYearInHeadingTests(unittest.TestCase):
    def test_year_extracted_from_heading(self):
        events = parse_dpga_events(_WITH_YEAR_MARKDOWN, BASE_URL, [], "test")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_date"], "2026-06-26")


# ---------------------------------------------------------------------------
# parse_dpga_events — ignores non-June sections
# ---------------------------------------------------------------------------

_NON_JUNE_MARKDOWN = """\
## Prep Meeting — Monday 4 May

| Event | Location | Time |
| --- | --- | --- |
| Planning Session | Remote | 10:00 - 11:00 |
"""

class ParseDpgaEventsNonJuneTests(unittest.TestCase):
    def test_may_section_still_extracted(self):
        # The parser imports all dates; callers filter by year/month as needed.
        # But since default_year=2026, a May date should still be parsed.
        events = parse_dpga_events(_NON_JUNE_MARKDOWN, BASE_URL, [], "test")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_date"], "2026-05-04")


# ---------------------------------------------------------------------------
# Legacy parse_events (simple line format) unchanged
# ---------------------------------------------------------------------------

class ParseEventsLegacyTests(unittest.TestCase):
    def test_simple_line_still_works(self):
        text = "2026-06-23 | Open Source Summit | https://example.org/summit"
        events = parse_events(text, [], "test")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Open Source Summit")
        self.assertEqual(events[0]["event_date"], "2026-06-23")
        self.assertEqual(events[0]["original_source_url"], "https://example.org/summit")


# ---------------------------------------------------------------------------
# parse_dpga_events — tab-separated format (actual DPGA agenda style)
# ---------------------------------------------------------------------------

# Mirrors the format used in https://hackmd.io/@dpga/Sk05Nc21Me, with:
#   - Comma after weekday in the heading ("Monday, 22 June")
#   - Tab-separated rows instead of pipe tables
#   - Multi-line events: title on its own line, then "(location)\ttime"
#   - HTML entities (&amp;) in event names
#   - Single times without an end ("10:00")
#   - TBC/TBA times that should be skipped

_DPGA_ACTUAL_FORMAT = (
    "## UN Tech Over \u2014 Monday, 22 June\n"
    "Activity\tTime\n"
    "UN Tech Over Hack-A-Thon, Edit-A-Thon, and Maintain-A-Thon\n"
    "\n"
    "(location details)\t10:00 - 18:00\n"
    "Octane Side Event: Sustainable Open Source Funding Infrastructure.\n"
    "\n"
    "Location: Michael J Fox Foundation Offices, 111 W34th St.\t12:00 \u2013 17:00\n"
    "\n"
    "## AI Day \u2014 Tuesday, 23 June\n"
    "Activity\tTime\n"
    "UNGA81 Event\t10:00\n"
    "AI Potential &amp; Sustainability (UNICEF &amp; DPGA)\tTBC\n"
    "DPGA + UNICC AI Collection\tTBC\n"
    "\n"
    "## DPI Day \u2014 Wednesday, 24 June\n"
    "Activity\tTime\n"
    "DPGA Breakfast\tTBC\n"
    "Advancing Population-Scale Innovation with Safe &amp; Inclusive DPI\t12:00 - 13:00 &amp; 15:00 - 16:00\n"
    "\n"
    "## Community Day \u2014 Friday, 26 June\n"
    "Activity\tTime\n"
    "DPG Showcase &amp; Networking \u2013 Community Event (More details TBA)\n"
    "\n"
    "Growing Inclusive Digital Commons: Open Solutions, Communities, and AI in Practice\t14:20 - 15:20\n"
)


class ParseDpgaEventsTabSeparatedTests(unittest.TestCase):
    def setUp(self):
        self.events = parse_dpga_events(_DPGA_ACTUAL_FORMAT, BASE_URL, [], "test")

    def test_multiline_event_title_extracted(self):
        titles = [e["title"] for e in self.events]
        self.assertIn(
            "UN Tech Over Hack-A-Thon, Edit-A-Thon, and Maintain-A-Thon", titles
        )

    def test_multiline_event_with_location_prefix(self):
        titles = [e["title"] for e in self.events]
        self.assertIn(
            "Octane Side Event: Sustainable Open Source Funding Infrastructure.", titles
        )

    def test_multiline_event_date(self):
        evt = next(
            e for e in self.events if "Hack-A-Thon" in e["title"]
        )
        self.assertEqual(evt["event_date"], "2026-06-22")

    def test_multiline_event_times(self):
        evt = next(
            e for e in self.events if "Hack-A-Thon" in e["title"]
        )
        self.assertEqual(evt["start_time"], "10:00")
        self.assertEqual(evt["end_time"], "18:00")

    def test_single_time_event_included(self):
        titles = [e["title"] for e in self.events]
        self.assertIn("UNGA81 Event", titles)

    def test_single_time_event_date(self):
        evt = next(e for e in self.events if e["title"] == "UNGA81 Event")
        self.assertEqual(evt["event_date"], "2026-06-23")
        self.assertEqual(evt["start_time"], "10:00")

    def test_tbc_events_skipped(self):
        titles = [e["title"] for e in self.events]
        self.assertNotIn("AI Potential & Sustainability (UNICEF & DPGA)", titles)
        self.assertNotIn("DPGA + UNICC AI Collection", titles)
        self.assertNotIn("DPGA Breakfast", titles)

    def test_tba_event_skipped(self):
        titles = [e["title"] for e in self.events]
        self.assertFalse(any("DPG Showcase" in t for t in titles))

    def test_html_entities_decoded_in_titles(self):
        for evt in self.events:
            self.assertNotIn("&amp;", evt["title"])

    def test_ampersand_entity_decoded(self):
        # "Advancing Population-Scale Innovation with Safe &amp; Inclusive DPI"
        # should appear as "… Safe & Inclusive DPI"
        titles = [e["title"] for e in self.events]
        self.assertTrue(any("Safe & Inclusive DPI" in t for t in titles))

    def test_multiple_time_ranges_uses_first(self):
        # "12:00 - 13:00 & 15:00 - 16:00" → start 12:00 end 13:00
        evt = next(
            e for e in self.events if "Safe & Inclusive DPI" in e["title"]
        )
        self.assertEqual(evt["start_time"], "12:00")
        self.assertEqual(evt["end_time"], "13:00")

    def test_community_day_event_extracted(self):
        titles = [e["title"] for e in self.events]
        self.assertIn(
            "Growing Inclusive Digital Commons: Open Solutions, Communities, and AI in Practice",
            titles,
        )

    def test_organizer_is_dpga(self):
        for evt in self.events:
            self.assertEqual(evt["organizer"], "Digital Public Goods Alliance")

    def test_unique_ids(self):
        ids = [e["id"] for e in self.events]
        self.assertEqual(len(ids), len(set(ids)))

    def test_comma_heading_date_parsed(self):
        # Headings use "Monday, 22 June" (comma after weekday).
        dates = {e["event_date"] for e in self.events}
        self.assertIn("2026-06-22", dates)
        self.assertIn("2026-06-23", dates)


if __name__ == "__main__":
    unittest.main()

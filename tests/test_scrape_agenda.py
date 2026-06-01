import sys
import os
import unittest

# Allow importing scrape_agenda (and event_utils) as if running from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from scrape_agenda import (  # noqa: E402  (import after sys.path manipulation)
    events_from_html_patterns,
    events_from_jsonld,
    normalize_date,
)


class NormalizeDateTests(unittest.TestCase):
    def test_iso_passthrough(self):
        self.assertEqual(normalize_date("2026-06-23"), "2026-06-23")

    def test_us_long_form(self):
        self.assertEqual(normalize_date("June 23, 2026"), "2026-06-23")

    def test_us_long_no_comma(self):
        self.assertEqual(normalize_date("June 23 2026"), "2026-06-23")

    def test_short_month_with_dot(self):
        self.assertEqual(normalize_date("Jun. 24, 2026"), "2026-06-24")

    def test_short_month_no_dot(self):
        self.assertEqual(normalize_date("Jun 25 2026"), "2026-06-25")

    def test_trailing_comma_stripped(self):
        self.assertEqual(normalize_date("June 23, 2026,"), "2026-06-23")

    def test_normalizes_any_year(self):
        # normalize_date parses any year; callers are responsible for filtering
        self.assertEqual(normalize_date("June 23, 2025"), "2025-06-23")

    def test_garbage_returns_none(self):
        self.assertIsNone(normalize_date("not a date"))


class EventsFromJsonLdTests(unittest.TestCase):
    _JSONLD_PAGE = """<!doctype html><html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Event",
  "name": "Open Source Summit",
  "startDate": "2026-06-24T18:00:00-04:00",
  "url": "https://example.org/summit",
  "location": {
    "@type": "Place",
    "name": "Brookfield Place",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "200 Vesey St",
      "addressLocality": "New York, NY"
    }
  },
  "description": "Evening summit for open-source enthusiasts.",
  "organizer": { "@type": "Organization", "name": "Open Source Collective" }
}
</script>
</head><body></body></html>"""

    def test_extracts_single_event(self):
        events = events_from_jsonld(self._JSONLD_PAGE, "https://example.org", [], "test")
        self.assertEqual(len(events), 1)
        evt = events[0]
        self.assertEqual(evt["title"], "Open Source Summit")
        self.assertEqual(evt["event_date"], "2026-06-24")
        self.assertEqual(evt["organizer"], "Open Source Collective")
        self.assertEqual(evt["location"]["name"], "Brookfield Place")
        self.assertEqual(evt["original_source_url"], "https://example.org/summit")
        self.assertEqual(evt["submission_source"], "test")

    def test_skips_non_june_events(self):
        page = self._JSONLD_PAGE.replace("2026-06-24", "2026-05-10")
        events = events_from_jsonld(page, "https://example.org", [], "test")
        self.assertEqual(len(events), 0)

    def test_skips_non_event_types(self):
        page = self._JSONLD_PAGE.replace('"Event"', '"Organization"')
        events = events_from_jsonld(page, "https://example.org", [], "test")
        self.assertEqual(len(events), 0)

    def test_deduplicates(self):
        existing = events_from_jsonld(self._JSONLD_PAGE, "https://example.org", [], "test")
        duplicates = events_from_jsonld(self._JSONLD_PAGE, "https://example.org", existing, "test")
        self.assertEqual(len(duplicates), 0)

    def test_graph_container(self):
        page = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"Event","name":"Graph Event","startDate":"2026-06-25","url":"https://example.org/g"}
]}</script></head><body></body></html>"""
        events = events_from_jsonld(page, "https://example.org", [], "test")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Graph Event")

    def test_jsonld_array(self):
        page = """<html><head><script type="application/ld+json">
[{"@type":"Event","name":"Array Event","startDate":"2026-06-26","url":"https://example.org/a"}]
</script></head><body></body></html>"""
        events = events_from_jsonld(page, "https://example.org", [], "test")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Array Event")


class EventsFromHtmlPatternsTests(unittest.TestCase):
    def test_extracts_iso_date_block(self):
        html = """<html><body>
<div class="event">
  <h3>Community Hackathon</h3>
  <p>Date: 2026-06-22</p>
  <a href="https://example.org/hackathon">Register</a>
</div>
</body></html>"""
        events = events_from_html_patterns(html, "https://example.org", [], "test")
        self.assertTrue(len(events) >= 1)
        self.assertEqual(events[0]["event_date"], "2026-06-22")
        self.assertEqual(events[0]["original_source_url"], "https://example.org/hackathon")

    def test_extracts_long_date_form(self):
        html = """<html><body>
<li>Open Data Forum — June 27, 2026 — <a href="https://example.org/forum">Details</a></li>
</body></html>"""
        events = events_from_html_patterns(html, "https://example.org", [], "test")
        dates = [e["event_date"] for e in events]
        self.assertIn("2026-06-27", dates)

    def test_ignores_non_june_blocks(self):
        html = """<html><body>
<div>Conference — 2026-07-15 — <a href="https://example.org/conf">Link</a></div>
</body></html>"""
        events = events_from_html_patterns(html, "https://example.org", [], "test")
        self.assertEqual(len(events), 0)

    def test_deduplicates(self):
        html = """<html><body>
<div>Hackathon — 2026-06-22 — <a href="https://example.org/h">Link</a></div>
</body></html>"""
        first = events_from_html_patterns(html, "https://example.org", [], "test")
        second = events_from_html_patterns(html, "https://example.org", first, "test")
        self.assertEqual(len(second), 0)

    def test_html_invite_only_sets_access(self):
        html = """<html><body>
<div class="event">
  <h3>LinkedIn Side Event</h3>
  <p>Date: 2026-06-22</p>
  <p>This invite-only event is hosted in collaboration with LinkedIn.</p>
  <a href="https://example.org/linkedin">Details</a>
</div>
</body></html>"""
        events = events_from_html_patterns(html, "https://example.org", [], "test")
        self.assertTrue(events)
        self.assertEqual(events[0]["access"], "invite_only")

    def test_html_public_event_access(self):
        html = """<html><body>
<div class="event">
  <h3>Open Hackathon</h3>
  <p>Date: 2026-06-23</p>
  <p>Open to all community members.</p>
  <a href="https://example.org/hack">Join</a>
</div>
</body></html>"""
        events = events_from_html_patterns(html, "https://example.org", [], "test")
        self.assertTrue(events)
        self.assertEqual(events[0]["access"], "public")


class EventsFromJsonLdAccessTests(unittest.TestCase):
    def _make_page(self, name: str, description: str) -> str:
        return f"""<!doctype html><html><head>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Event",
  "name": "{name}",
  "startDate": "2026-06-22T18:00:00-04:00",
  "url": "https://example.org/event",
  "description": "{description}"
}}
</script>
</head><body></body></html>"""

    def test_jsonld_invite_only_description(self):
        page = self._make_page("LinkedIn Side Event", "This invite-only event is at LinkedIn Office.")
        events = events_from_jsonld(page, "https://example.org", [], "test")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["access"], "invite_only")

    def test_jsonld_public_event(self):
        page = self._make_page("Open Summit", "Join us for an open summit.")
        events = events_from_jsonld(page, "https://example.org", [], "test")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["access"], "public")

    def test_jsonld_invite_only_in_title(self):
        page = self._make_page("Invitation-Only Workshop", "Details TBD.")
        events = events_from_jsonld(page, "https://example.org", [], "test")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["access"], "invite_only")


if __name__ == "__main__":
    unittest.main()

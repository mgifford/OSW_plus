import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.event_utils import build_event_from_submission, parse_issue_form_markdown


class EventUtilsTests(unittest.TestCase):
    def test_parse_issue_form_markdown_extracts_sections(self):
        body = """### Event Title\nDrupal NYC Evening Social & Slices\n\n### When is it happening?\nWeekday After-Hours (5:30 PM Onward)\n\n### Exact Date\n2026-06-23\n\n### Original Event Link (RSVP Page)\nhttps://example.org/event\n\n### Brief Event Summary\nCommunity meetup\n"""
        fields = parse_issue_form_markdown(body)
        self.assertEqual(fields["event title"], "Drupal NYC Evening Social & Slices")
        self.assertEqual(fields["exact date"], "2026-06-23")

    def test_build_event_from_submission_maps_timeframe(self):
        fields = {
            "event title": "Breakfast",
            "when is it happening?": "Weekday Breakfast (7:30 AM - 9:00 AM)",
            "exact date": "2026-06-24",
            "original event link (rsvp page)": "https://example.org/breakfast",
            "brief event summary": "Morning meetup",
        }
        event = build_event_from_submission(fields, issue_number=5, existing_events=[])
        self.assertEqual(event["timeframe"], "weekday_breakfast")
        self.assertEqual(event["start_time"], "07:30")

    def _base_fields(self, timeframe: str, date: str) -> dict:
        return {
            "event title": "Test Event",
            "when is it happening?": timeframe,
            "exact date": date,
            "original event link (rsvp page)": "https://example.org/event",
            "brief event summary": "Summary",
        }

    def test_runway_timeframe_corrected_for_core_week_date(self):
        """An event with a Core Week date must not end up in the Runway section."""
        for core_date in ("2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"):
            with self.subTest(date=core_date):
                event = build_event_from_submission(
                    self._base_fields("The Runway (Weekend Before: June 20-21)", core_date),
                    issue_number=1,
                    existing_events=[],
                )
                self.assertNotEqual(event["timeframe"], "runway",
                    f"Event on {core_date} should not have timeframe 'runway'")
                self.assertTrue(event["timeframe"].startswith("weekday_"),
                    f"Event on {core_date} should have a weekday timeframe, got {event['timeframe']!r}")

    def test_aftermath_timeframe_corrected_for_core_week_date(self):
        """An event with a Core Week date must not end up in the Aftermath section."""
        event = build_event_from_submission(
            self._base_fields("The Aftermath (Weekend After: June 27-28)", "2026-06-25"),
            issue_number=2,
            existing_events=[],
        )
        self.assertNotEqual(event["timeframe"], "aftermath")
        self.assertTrue(event["timeframe"].startswith("weekday_"))

    def test_runway_date_forces_runway_timeframe(self):
        """A date on June 20-21 is always classified as runway, whatever the submitter chose."""
        for runway_date in ("2026-06-20", "2026-06-21"):
            with self.subTest(date=runway_date):
                event = build_event_from_submission(
                    self._base_fields("Weekday After-Hours (5:30 PM Onward)", runway_date),
                    issue_number=3,
                    existing_events=[],
                )
                self.assertEqual(event["timeframe"], "runway")

    def test_aftermath_date_forces_aftermath_timeframe(self):
        """A date on June 27-28 is always classified as aftermath, whatever the submitter chose."""
        for aftermath_date in ("2026-06-27", "2026-06-28"):
            with self.subTest(date=aftermath_date):
                event = build_event_from_submission(
                    self._base_fields("Weekday After-Hours (5:30 PM Onward)", aftermath_date),
                    issue_number=4,
                    existing_events=[],
                )
                self.assertEqual(event["timeframe"], "aftermath")

    def test_process_issue_submission_appends_event_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            events_path = Path(temp_dir) / "events.json"
            api_path = Path(temp_dir) / "api.json"
            issue_path = Path(temp_dir) / "issue.md"

            events_path.write_text("[]\n", encoding="utf-8")
            issue_path.write_text(
                """### Event Title\nTest Event\n\n### When is it happening?\nWeekday After-Hours (5:30 PM Onward)\n\n### Exact Date\n2026-06-24\n\n### Original Event Link (RSVP Page)\nhttps://example.org/event\n\n### Brief Event Summary\nSummary\n""",
                encoding="utf-8",
            )

            command = [
                "python",
                "scripts/process_issue_submission.py",
                "--issue-body-file",
                str(issue_path),
                "--issue-number",
                "42",
                "--events-file",
                str(events_path),
                "--api-file",
                str(api_path),
            ]
            subprocess.run(command, check=True)
            subprocess.run(command, check=True)

            self.assertTrue(api_path.exists())
            events = events_path.read_text(encoding="utf-8")
            self.assertEqual(events.count("Test Event"), 1)


if __name__ == "__main__":
    unittest.main()

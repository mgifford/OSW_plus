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

import subprocess
import tempfile
import unittest
import json
import sys
from pathlib import Path

from scripts.event_utils import build_event_from_submission, detect_access_level, event_exists, parse_issue_form_markdown, save_events


class DetectAccessLevelTests(unittest.TestCase):
    def test_invite_only_hyphen(self):
        self.assertEqual(detect_access_level("invite-only event"), "invite_only")

    def test_invite_only_space(self):
        self.assertEqual(detect_access_level("invite only event"), "invite_only")

    def test_invitation_only(self):
        self.assertEqual(detect_access_level("invitation only gathering"), "invite_only")

    def test_by_invitation(self):
        self.assertEqual(detect_access_level("by invitation"), "invite_only")

    def test_invitees_only(self):
        self.assertEqual(detect_access_level("invitees only"), "invite_only")

    def test_registration_required(self):
        self.assertEqual(detect_access_level("registration required to attend"), "registration_required")

    def test_rsvp_required(self):
        self.assertEqual(detect_access_level("RSVP required"), "registration_required")

    def test_tickets_required(self):
        self.assertEqual(detect_access_level("tickets required"), "registration_required")

    def test_public_event(self):
        self.assertEqual(detect_access_level("Open to all community members"), "public")

    def test_empty_string(self):
        self.assertEqual(detect_access_level(""), "public")

    def test_case_insensitive(self):
        self.assertEqual(detect_access_level("INVITE-ONLY"), "invite_only")


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

    def test_build_event_defaults_access_to_public(self):
        fields = {
            "event title": "Open Meetup",
            "when is it happening?": "Weekday After-Hours (5:30 PM Onward)",
            "exact date": "2026-06-23",
            "original event link (rsvp page)": "https://example.org/open",
            "brief event summary": "Anyone welcome",
        }
        event = build_event_from_submission(fields, issue_number=6, existing_events=[])
        self.assertEqual(event["access"], "public")

    def test_build_event_invite_only_access(self):
        fields = {
            "event title": "Invite Only Dinner",
            "when is it happening?": "Weekday After-Hours (5:30 PM Onward)",
            "exact date": "2026-06-23",
            "original event link (rsvp page)": "https://example.org/dinner",
            "brief event summary": "Private dinner",
            "access level": "Invite Only",
        }
        event = build_event_from_submission(fields, issue_number=7, existing_events=[])
        self.assertEqual(event["access"], "invite_only")

    def test_build_event_registration_required_access(self):
        fields = {
            "event title": "Workshop",
            "when is it happening?": "Weekday Daytime (9:00 AM - 5:30 PM)",
            "exact date": "2026-06-24",
            "original event link (rsvp page)": "https://example.org/workshop",
            "brief event summary": "Technical workshop",
            "access level": "Registration Required",
        }
        event = build_event_from_submission(fields, issue_number=8, existing_events=[])
        self.assertEqual(event["access"], "registration_required")

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
                sys.executable,
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

    def test_event_exists_ignores_source_url_for_same_logical_event(self):
        existing = [
            {
                "title": "Open Source Summit",
                "event_date": "2026-06-24",
                "start_time": "18:00",
                "end_time": "21:30",
                "timeframe": "weekday_evening",
                "original_source_url": "https://www.unopensource.org/agenda",
            }
        ]
        candidate = {
            "title": "Open Source Summit",
            "event_date": "2026-06-24",
            "start_time": "18:00",
            "end_time": "21:30",
            "timeframe": "weekday_evening",
            "original_source_url": "https://hackmd.io/@dpga/Sk05Nc21Me#Open-Source-Summit",
        }
        self.assertTrue(event_exists(existing, candidate))

    def test_save_events_prefers_un_agenda_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            events_path = Path(temp_dir) / "events.json"
            events = [
                {
                    "id": "evt-2026-002",
                    "title": "Open Source Summit",
                    "event_date": "2026-06-24",
                    "start_time": "18:00",
                    "end_time": "21:30",
                    "timeframe": "weekday_evening",
                    "original_source_url": "https://hackmd.io/@dpga/Sk05Nc21Me#Open-Source-Summit",
                    "submission_source": "hackmd-dpga:https://hackmd.io/@dpga/Sk05Nc21Me/download",
                },
                {
                    "id": "evt-2026-001",
                    "title": "Open Source Summit",
                    "event_date": "2026-06-24",
                    "start_time": "18:00",
                    "end_time": "21:30",
                    "timeframe": "weekday_evening",
                    "original_source_url": "https://www.unopensource.org/agenda",
                    "submission_source": "scrape:https://www.unopensource.org/agenda",
                },
            ]

            save_events(events_path, events)
            saved = json.loads(events_path.read_text(encoding="utf-8"))

            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["original_source_url"], "https://www.unopensource.org/agenda")
            self.assertEqual(saved[0]["submission_source"], "scrape:https://www.unopensource.org/agenda")

    def test_save_events_keeps_same_title_different_location(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            events_path = Path(temp_dir) / "events.json"
            events = [
                {
                    "id": "evt-2026-001",
                    "title": "Open Source Summit",
                    "event_date": "2026-06-24",
                    "start_time": "18:00",
                    "end_time": "21:30",
                    "timeframe": "weekday_evening",
                    "location": {"name": "Room A", "address": "1 Main St"},
                    "original_source_url": "https://www.unopensource.org/agenda",
                    "submission_source": "scrape:https://www.unopensource.org/agenda",
                },
                {
                    "id": "evt-2026-002",
                    "title": "Open Source Summit",
                    "event_date": "2026-06-24",
                    "start_time": "18:00",
                    "end_time": "21:30",
                    "timeframe": "weekday_evening",
                    "location": {"name": "Room B", "address": "1 Main St"},
                    "original_source_url": "https://hackmd.io/@dpga/Sk05Nc21Me#Open-Source-Summit",
                    "submission_source": "hackmd-dpga:https://hackmd.io/@dpga/Sk05Nc21Me/download",
                },
            ]

            save_events(events_path, events)
            saved = json.loads(events_path.read_text(encoding="utf-8"))

            self.assertEqual(len(saved), 2)


if __name__ == "__main__":
    unittest.main()

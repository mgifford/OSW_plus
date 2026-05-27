# OSW_plus

OS Week Plus (OSW+) NYC is an open-source, community-driven fringe calendar and directory for events around UN Open Source Week.

## Project layout

- `.github/ISSUE_TEMPLATE/submit-event.yml` — browser-native event submission form.
- `.github/workflows/process-submission.yml` — issue-to-JSON ingestion pipeline.
- `.github/workflows/scheduled-scraper.yml` — daily HackMD scraper pipeline.
- `data/2026/events.json` — canonical event ledger.
- `api/2026/events.json` — public API endpoint source.
- `src/pages/index.html` + `public/index.html` — frontend calendar UI.
- `scripts/generate_ics.py` — generates `public/calendar.ics`.

## Local commands

```bash
python scripts/generate_ics.py --events-file data/2026/events.json --output-file public/calendar.ics
python -m unittest discover -s tests -v
```

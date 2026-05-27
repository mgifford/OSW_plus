# OSW_plus

OS Week Plus (OSW+) NYC is an open-source, community-driven fringe calendar and directory for events around UN Open Source Week.

## Project layout

- `.github/ISSUE_TEMPLATE/submit-event.yml` — browser-native event submission form.
- `.github/ISSUE_TEMPLATE/submit-place.yml` — form to suggest a coffee/food/park venue near the UN.
- `.github/workflows/process-submission.yml` — issue-to-JSON ingestion pipeline.
- `.github/workflows/scheduled-scraper.yml` — daily HackMD scraper pipeline.
- `data/2026/events.json` — canonical event ledger.
- `data/places.csv` — curated list of coffee, food, park, and bar spots near the UN.
- `data/places_with_coords.csv` — same list with lat/lon for the interactive map.
- `data/places/` — individual Markdown files for each venue.
- `api/2026/events.json` — public API endpoint source.
- `src/pages/index.html` + `public/index.html` — frontend calendar UI.
- `public/places-map.html` — interactive Leaflet map of venues near the UN.
- `scripts/generate_ics.py` — generates `public/calendar.ics`.
- `scripts/geocode_places.py` — auto-fills coordinates in `places_with_coords.csv` via Nominatim.

## Places to Meet

Inspired by [Food-W3C-Kobe](https://github.com/mgifford/Food-W3C-Kobe), OSW+ NYC also maintains a community-curated guide to spots near the UN where attendees can grab coffee, find affordable food, or meet up in the evening.

- **[Interactive map](public/places-map.html)** — color-coded Leaflet map of all venues.
- **[Contributing guide](CONTRIBUTING-places.md)** — how to add or suggest a place.
- **[Suggest a place](https://github.com/mgifford/OSW_plus/issues/new?template=submit-place.yml)** — quick GitHub Issue form.

## Local commands

```bash
python scripts/generate_ics.py --events-file data/2026/events.json --output-file public/calendar.ics
python -m unittest discover -s tests -v
```

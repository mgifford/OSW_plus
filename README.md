# OSW_plus

OS Week Plus (OSW+) NYC is an open-source, community-driven fringe calendar and directory for events around UN Open Source Week.

## Project layout

- `.github/ISSUE_TEMPLATE/submit-event.yml` — browser-native event submission form.
- `.github/ISSUE_TEMPLATE/submit-place.yml` — form to suggest a coffee/food/park venue near the UN.
- `.github/workflows/process-submission.yml` — issue-to-JSON ingestion pipeline.
- `.github/workflows/process-place-submission.yml` — place-suggestion ingestion pipeline.
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

### Knowledge platform

Alongside the side-event calendar, the repository hosts the **Open UN Open Source
Week Knowledge Platform** — an open, AI-ready index of public information about UN
Open Source Week that links back to authoritative sources (never an archive of
copyrighted media). See [ROADMAP.md](ROADMAP.md) for the full vision and status.

- `conferences/unosw.json` — conference config (canonical URL, official sources, topic vocabulary).
- `schema/*.schema.json` — JSON Schema for each dataset plus a shared provenance object.
- `data/unosw/2025/*.json` — curated, fully provenanced datasets (sessions, speakers, organizations, projects, topics, quotes, references) extracted from the CC BY 4.0 UN Open Source Week 2025 Conference Report.
- `scripts/knowledge_utils.py` — slugify, schema validation, derived indexes, knowledge-graph builder.
- `scripts/generate_knowledge_site.py` — conference-agnostic generator that emits profile/index pages, `api/<conf>/<year>/*.json`, `api/knowledge-graph.json`, and the sitemap into `_site` at build time.

## Project policies

- [AGENTS.md](AGENTS.md) — instructions for AI agents working in this repository.
- [GOVERNANCE.md](GOVERNANCE.md) — contribution, editorial, attribution, licensing, and AI-provenance rules for the knowledge platform.
- [ROADMAP.md](ROADMAP.md) — the 17-phase knowledge-platform vision and current status.
- [ACCESSIBILITY.md](ACCESSIBILITY.md) — accessibility target, guardrails, and test expectations.
- [SUSTAINABILITY.md](SUSTAINABILITY.md) — sustainability commitments and review cadence.

## Places to Meet

Inspired by [Food-W3C-Kobe](https://github.com/mgifford/Food-W3C-Kobe), OSW+ NYC also maintains a community-curated guide to spots near the UN where attendees can grab coffee, find affordable food, or meet up in the evening.

- **[Interactive map](public/places-map.html)** — color-coded Leaflet map of all venues.
- **[Contributing guide](CONTRIBUTING-places.md)** — how to add or suggest a place.
- **[Suggest a place](https://github.com/mgifford/OSW_plus/issues/new?template=submit-place.yml)** — quick GitHub Issue form.

### GitHub Actions intake

Suggestions are incorporated in two phases: a maintainer reviews the issue, adds the `approved` label when it is ready to ingest, and then the matching GitHub Actions workflow turns it into site data.

- `Process Side Event Submission` ingests one approved issue, a newly approved issue, or all open approved side-event submissions.
- `Process Place Suggestion` does the same for place suggestions.

For backlog processing, use the workflow dispatch form and either enter a specific issue number or choose the option to process all open issues with the suggestion and `approved` labels.

Maintainer checklist:

1. Review the issue for completeness and fit.
1. Add the `approved` label when you want the suggestion ingested.
1. Run the matching Actions workflow for the approved backlog, or let the labeled issue trigger it on the next run.
1. Review the generated PR and merge it when the data looks correct.

## Local commands

```bash
python scripts/generate_ics.py --events-file data/2026/events.json --output-file public/calendar.ics
python -m unittest discover -s tests -v

# Knowledge platform
pip install -r requirements-dev.txt                              # test-only deps (jsonschema)
python scripts/import_agenda.py --year 2026                      # (re)build data/unosw/2026 from the agenda
python scripts/generate_knowledge_site.py --year 2025 --out _site   # build 2025 pages + datasets
python scripts/generate_knowledge_site.py --year 2026 --out _site   # build 2026 (coexists under /unosw/<year>/)
```

Generated pages live under `/unosw/<year>/` with a cross-year hub at `/explore.html`.

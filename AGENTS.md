# AGENTS.md

This repository is a static site and data project for OSW+ NYC. Make the smallest change that fixes the issue, and keep generated files in sync with the source data that produced them.

## Repository map

- `public/` - deployed site files.
- `src/` - source templates.
- `data/` - canonical event and place data, plus curated knowledge datasets under `data/<conference>/<year>/`.
- `conferences/` - per-conference config for the knowledge platform.
- `schema/` - JSON Schema for the knowledge datasets + shared provenance object.
- `api/` - public JSON mirrors.
- `scripts/` - generation and ingestion scripts (incl. `generate_knowledge_site.py`, `knowledge_utils.py`).
- `tests/` - Playwright and Python checks.

For the knowledge platform specifically, follow [GOVERNANCE.md](GOVERNANCE.md):
edit the curated JSON in `data/<conference>/<year>/`, never the generated HTML;
every record needs provenance; never invent facts; link to authoritative sources.

## Working rules

- Prefer editing source data or templates over generated output when both exist.
- Keep semantic HTML, keyboard support, visible focus, and descriptive link text intact.
- Do not add dependencies unless they solve a clear problem.
- If a change touches generated artifacts, update the corresponding source file or script in the same change.

## Validation

- `npm run test:a11y`
- `python -m unittest discover -s tests -v`
- `pip install -r requirements-dev.txt` then `python scripts/generate_knowledge_site.py --out _site` when knowledge data or the generator changes
- `python scripts/generate_ics.py --events-file data/2026/events.json --output-file public/calendar.ics` when event data changes
- `python scripts/geocode_places.py` when place coordinates need regeneration

## Review checklist

- Public pages still work without JavaScript where practical.
- Map and calendar pages still have readable fallback content.
- Accessibility and sustainability docs stay aligned with implemented behavior.
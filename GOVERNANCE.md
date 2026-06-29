# Governance

This document defines how the Open UN Open Source Week Knowledge Platform is
maintained: contribution guidelines, editorial standards, attribution and
licensing expectations, and the rules for AI-assisted contributions. It applies
to the knowledge platform (`conferences/`, `schema/`, `data/<conference>/`,
`scripts/generate_knowledge_site.py`, `scripts/knowledge_utils.py`) and is meant
to keep the project aligned with the open source values it documents.

## What this project is — and is not

The platform is an **open research index and knowledge graph**. It stores
*metadata, structured facts, citations, and short attributed quotations* drawn
from **public, verifiable sources**, and links back to those sources. It is
**not** an archive of copyrighted media: we do not host videos, slide decks, or
full copyrighted text. When in doubt, store a reference and a link, not a copy.

## Core principles

1. **Provenance always.** Every record and every AI-generated field carries a
   `provenance` object (see `schema/provenance.schema.json`): where the fact
   came from, the licence, and how it was obtained. No provenance, no merge.
2. **Never invent facts.** Only record information present in a cited source.
   If a source does not state it, the field stays empty.
3. **Link to authoritative sources.** Prefer the canonical/official URL; add a
   Wayback or archive URL for durability where relevant.
4. **Public sources only.** Never ingest private, paywalled, or
   access-restricted content, and never scrape private social content.
5. **Reproducible from source.** The published site must be regenerable from the
   committed JSON datasets with `scripts/generate_knowledge_site.py`.

## Contribution guidelines

- **Edit source, not generated output.** Curated data lives in
  `data/<conference>/<year>/*.json`; pages are generated into `_site` at build
  time and are not committed. Fix the data or the generator, never hand-edit
  generated HTML.
- **Validate before you open a PR.** Run:
  ```bash
  pip install -r requirements-dev.txt
  python -m unittest discover -s tests -v
  python scripts/generate_knowledge_site.py --out _site
  ```
  New or changed records must pass schema validation, cross-reference checks,
  and the provenance test in `tests/test_knowledge_datasets.py`.
- **One concern per PR.** Keep data changes, generator changes, and design
  changes separate so they stay reviewable.
- **Accessibility is non-negotiable.** Generated and existing pages must pass
  the WCAG 2.2 AA checks in `tests/a11y.spec.js` (`npm run test:a11y`).
- **Be a good citizen of external services.** Any automated ingestion must
  throttle politely (low concurrency, backoff on 429/5xx, a per-run cap). See
  the ingestion guidance in [ROADMAP.md](ROADMAP.md).

## Editorial standards

- Records describe what a source says, neutrally. No promotion, no editorializing.
- Identifiers (`slug`, `id`) are stable and lowercase-hyphenated; renaming a slug
  is a breaking change to URLs and should be avoided.
- A person, organization, or project has exactly one canonical record; reference
  it by slug everywhere else.
- Quotations are verbatim and short, attributed to a speaker and a session, and
  only used when the source licence permits redistribution.

## Attribution & licensing

- **Content** (the curated datasets and the prose derived from sources) inherits
  the obligations of its source. The 2025 corpus comes from the *UN Open Source
  Week 2025 Conference Report* (RISE 2026:04), licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); its `provenance`
  records the required attribution (Sachiko Muto, RISE / OpenForum Europe). Only
  sources under a redistributable licence (CC BY, CC BY-SA, CC0, or public
  domain) may have their text/quotations stored; otherwise store metadata and a
  link only.
- **Factual event metadata** (a session's title, date, time, organizer, room —
  who/what/when/where, as in the 2026 agenda import) records facts, which are not
  copyrightable. Such records are marked `license: public-domain` with
  `method: automated-ingestion` and always link to the authoritative agenda/event
  URL. Do **not** use this basis to store substantial copyrighted prose; for that,
  store metadata and a link only, per the rule above.
- **Code** (scripts, schemas, generator) is covered by the repository
  [LICENSE](LICENSE).
- Contributors license their contributions under those same terms and confirm
  they have the right to contribute the material.

## AI provenance rules

AI assistance is welcome for drafting, extraction, and summarization, under
these rules:

- Any field produced or materially shaped by an AI system must set its
  `provenance.method` to `llm-generation` and still cite the underlying
  `source_url` the model worked from.
- AI must not introduce facts absent from the cited source. Treat model output
  as a draft to be verified against the source, not as a source itself.
- Human-curated extraction uses `provenance.method` `manual-extraction`;
  automated ingestion uses `automated-ingestion`. Keep the method honest so
  consumers can weight records appropriately.
- AI-generated summaries and classifications are clearly derived data, kept
  separate from the verbatim facts they summarize.

## Maintainers & decisions

Maintainers review PRs for provenance, accuracy, licensing, and accessibility
before merging. Data disputes are resolved by checking the cited source; if the
source is ambiguous, the record is softened or removed rather than guessed.
Changes to schemas or governance are themselves PRs and follow the same review.

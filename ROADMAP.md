# Roadmap — Open UN Open Source Week Knowledge Platform

The long-term goal is to evolve `unosw.plus` from an event directory into an
open, AI-ready knowledge platform for UN Open Source Week — and, eventually, a
reusable platform for other open-source / digital-public-infrastructure
conferences — built entirely from public, verifiable sources with provenance and
links back to authoritative origins. This roadmap tracks the full 17-phase
vision and what has shipped so far.

Status legend: ✅ shipped · 🟡 partial · ⬜ planned.

## Delivered: 2025 vertical slice

A working end-to-end slice proves the architecture, using the CC BY 4.0
*UN Open Source Week 2025 Conference Report* as the seed corpus:

- Conference-config-driven namespace: `conferences/unosw.json`, JSON Schemas in
  `schema/`, curated datasets in `data/unosw/2025/`.
- A second data-year, **2026**, imported programmatically from the agenda via
  `scripts/import_agenda.py` into `data/unosw/2026/` (sessions tagged official vs
  side-event). Generated output is namespaced by conference/year
  (`/unosw/2025/…`, `/unosw/2026/…`) with a cross-year hub at `/explore.html`.
- Python generator (`scripts/generate_knowledge_site.py`,
  `scripts/knowledge_utils.py`) → profile + index pages, AI-ready `api/` datasets,
  a derived knowledge graph, and a regenerated sitemap, built into `_site` by the
  GitHub Pages workflow. No database; no new runtime dependencies.
- Governance ([GOVERNANCE.md](GOVERNANCE.md)) and these practices established
  from the start.

## Phase status

| # | Phase | Status | Notes |
|---|-------|--------|-------|
| 1 | Improve the existing site | 🟡 | Canonical/OpenGraph/Twitter meta + homepage JSON-LD; sitemap/robots realigned to the canonical host; cross-year "Knowledge" nav. Session pages carry agenda/speakers/orgs/summary/topics/references and a recording/links section; the 2025 resources page links the four authoritative UN Web TV day recordings. Transcripts land with Phase 13. |
| 2 | Ingestion pipeline | 🟡 | `scripts/import_agenda.py` ingests the 2026 agenda (`data/2026/events.json`) into normalized, provenanced datasets — a first, deterministic importer. A full throttled/idempotent pipeline for UN Web TV, transcripts.un.org, speaker pages, PDFs, and GitHub is still to come (see "Ingestion guidance"). |
| 3 | Normalize everything | ✅ | Consistent schemas for sessions/speakers/organizations/projects (plus topics/quotes/references) in `schema/`; 2025 data normalized in `data/unosw/2025/`. |
| 4 | Knowledge graph | ✅ | `knowledge_utils.build_graph()` emits `api/knowledge-graph.json` (people/orgs/projects/topics/sessions/countries + relationships). Importable into a graph DB later. |
| 5 | AI enrichment | 🟡 | Provenance structure supports `llm-generation` with citations; this pass uses facts-from-the-report only (`manual-extraction`). Wiring a throttled LLM step in CI is deferred. |
| 6 | Theme extraction | 🟡 | 19-theme vocabulary in config + `topics.json`; sessions/quotes classified by hand. Automatic per-paragraph multi-label classification is deferred. |
| 7 | Timeline | ⬜ | Yearly and cross-year timelines (first appearance, key quotes, announcements). Needs a second year of data. |
| 8 | Speaker profiles | ✅ | Permanent page per speaker with role, org, sessions, quotes, derived topics, and (when present) social links. |
| 9 | Organization profiles | ✅ | Page per organization with type, country, website, sessions, people, projects, topics. |
| 10 | Project pages | ✅ | Page per project with description, website, license, organizations, sessions. |
| 11 | Search | 🟡 | Existing client-side search covers events/places; extending it across the static datasets (people/orgs/topics/standards/years) is planned. |
| 12 | Social layer | ⬜ | Collect only public posts (Mastodon, Bluesky, public LinkedIn, blogs, GitHub) with URL/author/date/mentions. Throttled; no private content. |
| 13 | Preservation | ⬜ | Store canonical + transcript + Wayback URLs and Archive.org status; submit to Save Page Now when missing. No video stored. Throttled. |
| 14 | Static datasets | ✅ | `api/<conf>/<year>/{sessions,speakers,organizations,projects,topics,quotes,references}.json` + `index.json` manifest + `knowledge-graph.json`, usable directly by LLMs. |
| 15 | Research outputs | ⬜ | Generated annual/daily/session/topic/org/speaker reports, reading lists, repository and standards indexes. |
| 16 | WebMCP | ⬜ | Expose structured resources so AI systems retrieve sessions/topics/quotes/people/orgs/repos without reading every transcript. |
| 17 | Generalize the platform | 🟡 | Generator is already conference-agnostic (`--conference`/`--year`, config + data dir). Adding W3C TPAC / FOSDEM / Open Source Summit / DrupalCon / State of Open / DPGA / GovStack is config + data, not code. Splitting an ingestion framework package is deferred. |

## Ingestion guidance (Phases 2, 5, 12, 13)

When the automated ingestion/enrichment/preservation phases are built, they must:

- **Throttle.** Low concurrency, exponential backoff on 429/5xx, a polite delay
  between calls, and a hard per-run cap on requests to any single service
  (UN Web TV, transcripts.un.org, GitHub, Mastodon/Bluesky, Wayback Save Page
  Now, any LLM endpoint).
- **Be idempotent and resumable.** Re-running skips already-processed items and
  records what was done, so a paused run resumes cleanly.
- **Preserve provenance.** Every ingested or generated field records its source,
  licence, retrieval time, and method per [GOVERNANCE.md](GOVERNANCE.md).
- **Stay within licence.** Store redistributable text/quotes only; otherwise
  keep metadata + a link.

## Adding another conference (Phase 17)

1. Add `conferences/<id>.json` (name, `site_base_url`, official URLs, topic vocabulary).
2. Add curated data under `data/<id>/<year>/` following `schema/*.schema.json`.
3. Run `python scripts/generate_knowledge_site.py --conference <id> --year <year> --out _site`.

No generator code changes are required.

## Out of scope for now

Migrating the legacy 2026 side-event calendar (`data/2026/events.json`) into the
new conference namespace is intentionally deferred to avoid disrupting the live
calendar; the two coexist until a planned migration.

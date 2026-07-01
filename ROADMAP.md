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
| 1 | Improve the existing site | 🟡 | Canonical/OpenGraph/Twitter meta + homepage JSON-LD; sitemap/robots realigned to the canonical host; cross-year "Knowledge" nav. Session pages carry agenda/speakers/orgs/summary/topics/references and a recording/links section linking the authoritative UN Web TV recording and the community draft transcript; the 2025 resources page maps the two plenary days (OSPOs for Good, DPI Day) to their morning/afternoon recordings and draft transcripts. |
| 2 | Ingestion pipeline | 🟡 | `scripts/import_agenda.py` ingests the 2026 agenda (`data/2026/events.json`) into normalized, provenanced datasets — a first, deterministic importer. A full throttled/idempotent pipeline for UN Web TV, transcripts.un.org, speaker pages, PDFs, and GitHub is still to come (see "Ingestion guidance"). |
| 3 | Normalize everything | ✅ | Consistent schemas for sessions/speakers/organizations/projects (plus topics/quotes/references) in `schema/`; 2025 data normalized in `data/unosw/2025/`. |
| 4 | Knowledge graph | ✅ | `knowledge_utils.build_graph()` emits `api/knowledge-graph.json` (people/orgs/projects/topics/sessions/countries + relationships). Surfaced on the pages as "connections" blocks — theme pages link the people who spoke and organizations active on them; speaker pages link connected speakers and the organizations in their sessions; organization pages link related organizations — plus a per-theme cross-year link into the timeline. A standalone **relationship map** at `/graph.html` renders the whole graph merged across years as a static, clickable SVG (deterministic build-time force layout) with type/year filters and a focus search, backed by `/api/graph.json`; shared themes and recurring organizations bridge the years. The SVG is a decorative visual with an equivalent accessible "relationship index" list. Importable into a graph DB later. |
| 5 | AI enrichment | 🟡 | Provenance structure supports `llm-generation` with citations; this pass uses facts-from-the-report only (`manual-extraction`). Wiring a throttled LLM step in CI is deferred. |
| 6 | Theme extraction | 🟡 | 19-theme vocabulary in config + `topics.json`; sessions/quotes classified by hand. Automatic per-paragraph multi-label classification is deferred. |
| 7 | Timeline | 🟡 | Cross-year timeline at `/timeline.html` — a "themes across years" table (sessions per theme per year, first-seen) plus per-year cards, derived from the generated datasets across 2024–2026. Yearly per-day timelines and key-announcement annotations are still to come. |
| 8 | Speaker profiles | ✅ | Permanent page per speaker with role, org, sessions, quotes, derived topics, connected speakers, and (when present) an official-profile link plus social links. 2025 speakers are curated from the report (session-linked); the 2026 roster is imported from the captured official Speakers page via `import_speakers.py`, each with a confirmed `official_url` (the source page carries no LinkedIn/social links, so none are added, and per-session speaker mapping awaits published data). |
| 9 | Organization profiles | ✅ | Page per organization with type, country, website, sessions, people, projects, topics. |
| 10 | Project pages | ✅ | Page per project with description, website, license, organizations, sessions. |
| 11 | Search | 🟡 | Client-side knowledge search at `/knowledge-search.html` over a combined `/api/search-index.json`, faceted by **category** (events: sessions/speakers/organizations/projects/themes — and history: recordings, draft transcripts, reports/documents, and archived page snapshots) and **year** (2023–2026), with `?q=`/`?category=`/`?year=` deep links. History records link out to UN Web TV and the GitHub-hosted `conferences/` corpus. Runs entirely in the browser; no server. Ranking/typo-tolerance and the legacy events/places search remain separate. |
| 12 | Social layer | ⬜ | Collect only public posts (Mastodon, Bluesky, public LinkedIn, blogs, GitHub) with URL/author/date/mentions, indexed as a distinct third-party "social" search category (never treated as authoritative fact). Throttled; no private content. **Hashtag variants to match:** `#unosw`, `#UNOpenSourceWeek`, `#OpenSourceWeek`, per-year `#unosw2025`/`#unosw2026`, the predecessor `#OSPOsForGood`, and the phrase "UN Open Source Week". **Blocked in CI/agent sandboxes:** the default network policy denies egress to social APIs (e.g. `public.api.bsky.app`, Mastodon instances return `403 CONNECT`), so this must run where outbound access to those hosts is permitted. |
| 13 | Preservation | 🟡 | Community draft transcripts (cleaned auto-captions, no inferred speaker attribution) for the recorded plenary sessions are stored under `conferences/<year>/` and linked from the matching session pages, each beside its authoritative UN Web TV recording. Wayback/Archive.org status and a Save-Page-Now submitter are still to come. No video stored. Throttled. |
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

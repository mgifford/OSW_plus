"""Shared helpers for the UN Open Source Week knowledge platform.

Pure standard library at runtime, except :func:`validate_datasets`, which uses
``jsonschema`` (a test/CI-only dependency declared in requirements-dev.txt). The
site generator does not call validation, so the published build needs no extra
packages.

The data model treats *sessions* as the primary records: they hold forward
links to speakers, organizations, projects, topics and references. Everything
else (which sessions a speaker appeared in, an organization's people, the
knowledge graph) is *derived* here so the curated JSON never has to be kept in
sync by hand.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

# The seven curated datasets and the schema each validates against.
DATASETS = [
    "sessions",
    "speakers",
    "organizations",
    "projects",
    "topics",
    "quotes",
    "references",
]


def slugify(text: str) -> str:
    """Return a lowercase, ASCII, hyphenated slug for *text*.

    Accents are folded (``García`` -> ``garcia``) so slugs stay URL-safe and
    stable. Mirrors the spirit of the id helpers in ``event_utils.py``.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-")


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_conference(conferences_dir: str | Path, conference_id: str) -> dict[str, Any]:
    return load_json(Path(conferences_dir) / f"{conference_id}.json")


def load_datasets(data_dir: str | Path) -> dict[str, Any]:
    """Load every curated dataset for one conference-year directory."""
    base = Path(data_dir)
    return {name: load_json(base / f"{name}.json") for name in DATASETS}


# ──────────────────────────────────────────────────────────────────────────
# Schema validation (jsonschema, test/CI only)
# ──────────────────────────────────────────────────────────────────────────

def _schema_registry(schema_dir: Path):
    """Build a referencing registry of all schemas keyed by ``$id``.

    Lets cross-file ``$ref`` (e.g. the shared provenance schema) resolve.
    """
    from referencing import Registry, Resource

    resources = []
    for schema_file in schema_dir.glob("*.schema.json"):
        doc = load_json(schema_file)
        if "$id" in doc:
            resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


def validate_datasets(datasets: dict[str, Any], schema_dir: str | Path) -> list[str]:
    """Validate each dataset against its schema. Return a list of error strings.

    An empty list means everything is valid. Raising is left to the caller so
    this can back both a hard CI check and a soft report.
    """
    from jsonschema import Draft202012Validator

    schema_dir = Path(schema_dir)
    registry = _schema_registry(schema_dir)
    errors: list[str] = []
    for name, data in datasets.items():
        schema = load_json(schema_dir / f"{name}.schema.json")
        validator = Draft202012Validator(schema, registry=registry)
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            errors.append(f"{name}: {list(error.path)}: {error.message}")
    return errors


def check_cross_references(datasets: dict[str, Any]) -> list[str]:
    """Return a list of dangling-reference problems across the datasets."""
    org_slugs = {o["slug"] for o in datasets["organizations"]}
    speaker_slugs = {s["slug"] for s in datasets["speakers"]}
    project_slugs = {p["slug"] for p in datasets["projects"]}
    topic_slugs = {t["slug"] for t in datasets["topics"]}
    reference_ids = {r["id"] for r in datasets["references"]}
    session_ids = {s["id"] for s in datasets["sessions"]}

    problems: list[str] = []

    def want(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    for speaker in datasets["speakers"]:
        slug = speaker.get("organization_slug")
        if slug:
            want(slug in org_slugs, f"speaker {speaker['slug']} -> unknown org_slug {slug}")

    for project in datasets["projects"]:
        for org in project.get("organizations", []):
            want(org in org_slugs, f"project {project['slug']} -> unknown org {org}")

    for session in datasets["sessions"]:
        sid = session["id"]
        for sp in session.get("speakers", []):
            want(sp in speaker_slugs, f"session {sid} -> unknown speaker {sp}")
        for org in session.get("organizations", []):
            want(org in org_slugs, f"session {sid} -> unknown org {org}")
        for pr in session.get("projects", []):
            want(pr in project_slugs, f"session {sid} -> unknown project {pr}")
        for tp in session.get("topics", []):
            want(tp in topic_slugs, f"session {sid} -> unknown topic {tp}")
        for rf in session.get("references", []):
            want(rf in reference_ids, f"session {sid} -> unknown reference {rf}")

    for quote in datasets["quotes"]:
        if quote.get("speaker"):
            want(quote["speaker"] in speaker_slugs, f"quote {quote['id']} -> unknown speaker {quote['speaker']}")
        if quote.get("session"):
            want(quote["session"] in session_ids, f"quote {quote['id']} -> unknown session {quote['session']}")
        for tp in quote.get("topics", []):
            want(tp in topic_slugs, f"quote {quote['id']} -> unknown topic {tp}")

    return problems


# ──────────────────────────────────────────────────────────────────────────
# Derived indexes (back-references)
# ──────────────────────────────────────────────────────────────────────────

def _session_sort_key(session: dict[str, Any]) -> tuple[str, str]:
    return (str(session.get("date", "")), str(session.get("title", "")))


def build_indexes(datasets: dict[str, Any]) -> dict[str, Any]:
    """Compute back-references so pages never depend on hand-maintained links."""
    sessions = sorted(datasets["sessions"], key=_session_sort_key)

    sessions_by_speaker: dict[str, list] = defaultdict(list)
    sessions_by_org: dict[str, list] = defaultdict(list)
    sessions_by_project: dict[str, list] = defaultdict(list)
    sessions_by_topic: dict[str, list] = defaultdict(list)
    sessions_by_reference: dict[str, list] = defaultdict(list)

    for session in sessions:
        for sp in session.get("speakers", []):
            sessions_by_speaker[sp].append(session)
        for org in session.get("organizations", []):
            sessions_by_org[org].append(session)
        for pr in session.get("projects", []):
            sessions_by_project[pr].append(session)
        for tp in session.get("topics", []):
            sessions_by_topic[tp].append(session)
        for rf in session.get("references", []):
            sessions_by_reference[rf].append(session)

    quotes_by_speaker: dict[str, list] = defaultdict(list)
    quotes_by_session: dict[str, list] = defaultdict(list)
    quotes_by_topic: dict[str, list] = defaultdict(list)
    for quote in datasets["quotes"]:
        if quote.get("speaker"):
            quotes_by_speaker[quote["speaker"]].append(quote)
        if quote.get("session"):
            quotes_by_session[quote["session"]].append(quote)
        for tp in quote.get("topics", []):
            quotes_by_topic[tp].append(quote)

    speakers_by_org: dict[str, list] = defaultdict(list)
    for speaker in sorted(datasets["speakers"], key=lambda s: s["name"]):
        if speaker.get("organization_slug"):
            speakers_by_org[speaker["organization_slug"]].append(speaker)

    projects_by_org: dict[str, list] = defaultdict(list)
    for project in datasets["projects"]:
        for org in project.get("organizations", []):
            projects_by_org[org].append(project)

    return {
        "sessions_sorted": sessions,
        "sessions_by_speaker": sessions_by_speaker,
        "sessions_by_org": sessions_by_org,
        "sessions_by_project": sessions_by_project,
        "sessions_by_topic": sessions_by_topic,
        "sessions_by_reference": sessions_by_reference,
        "quotes_by_speaker": quotes_by_speaker,
        "quotes_by_session": quotes_by_session,
        "quotes_by_topic": quotes_by_topic,
        "speakers_by_org": speakers_by_org,
        "projects_by_org": projects_by_org,
        "speakers_by_slug": {s["slug"]: s for s in datasets["speakers"]},
        "orgs_by_slug": {o["slug"]: o for o in datasets["organizations"]},
        "projects_by_slug": {p["slug"]: p for p in datasets["projects"]},
        "topics_by_slug": {t["slug"]: t for t in datasets["topics"]},
        "references_by_id": {r["id"]: r for r in datasets["references"]},
        "sessions_by_id": {s["id"]: s for s in datasets["sessions"]},
    }


# ──────────────────────────────────────────────────────────────────────────
# Knowledge graph (Phase 4)
# ──────────────────────────────────────────────────────────────────────────

def build_graph(
    conference_id: str,
    year: int,
    datasets: dict[str, Any],
    base_url: str,
    generated_at: str,
) -> dict[str, Any]:
    """Derive a nodes/edges knowledge graph from the curated datasets.

    Node ids are ``type:slug`` (e.g. ``person:sachiko-muto``). Pure JSON, ready
    to import into a graph database later — no database is used here.
    """
    base = base_url.rstrip("/")
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_node(node_type: str, ident: str, label: str, url: str | None = None) -> str:
        node_id = f"{node_type}:{ident}"
        if node_id not in nodes:
            node = {"id": node_id, "type": node_type, "label": label}
            if url:
                node["url"] = url
            nodes[node_id] = node
        return node_id

    def add_edge(source: str, target: str, edge_type: str) -> None:
        key = (source, target, edge_type)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"source": source, "target": target, "type": edge_type})

    def country_node(name: str) -> str:
        return add_node("country", slugify(name), name)

    for org in datasets["organizations"]:
        add_node("organization", org["slug"], org["name"], f"{base}/organizations/{org['slug']}.html")
        if org.get("country"):
            add_edge(f"organization:{org['slug']}", country_node(org["country"]), "from_country")

    for project in datasets["projects"]:
        pid = add_node("project", project["slug"], project["name"], f"{base}/projects/{project['slug']}.html")
        for org in project.get("organizations", []):
            add_edge(f"organization:{org}", pid, "organized")

    for topic in datasets["topics"]:
        add_node("topic", topic["slug"], topic["name"], f"{base}/topics/{topic['slug']}.html")

    for speaker in datasets["speakers"]:
        pid = add_node("person", speaker["slug"], speaker["name"], f"{base}/speakers/{speaker['slug']}.html")
        if speaker.get("organization_slug"):
            add_edge(pid, f"organization:{speaker['organization_slug']}", "affiliated_with")
        if speaker.get("country"):
            add_edge(pid, country_node(speaker["country"]), "from_country")

    for session in datasets["sessions"]:
        sid = add_node("session", session["id"], session["title"], f"{base}/sessions/{session['id']}.html")
        for sp in session.get("speakers", []):
            add_edge(f"person:{sp}", sid, "spoke_at")
        for org in session.get("organizations", []):
            add_edge(f"organization:{org}", sid, "organized")
        for pr in session.get("projects", []):
            add_edge(sid, f"project:{pr}", "mentioned_project")
        for tp in session.get("topics", []):
            add_edge(sid, f"topic:{tp}", "discussed_topic")

    return {
        "generated_at": generated_at,
        "conference": conference_id,
        "year": year,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def html_escape(text: Any) -> str:
    """Escape text for safe HTML interpolation."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

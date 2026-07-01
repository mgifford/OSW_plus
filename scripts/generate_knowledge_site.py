#!/usr/bin/env python3
"""Generate the static knowledge-platform pages and datasets for a conference.

Reads a conference config (``conferences/<id>.json``) and the curated datasets
(``data/<id>/<year>/*.json``) and emits, into an output directory (default
``_site``):

  * profile pages: sessions/, speakers/, organizations/, projects/, topics/
  * an index page per type plus an ``explore.html`` hub
  * aggregated public datasets under ``api/<id>/<year>/``
  * a derived ``api/knowledge-graph.json``
  * a regenerated ``sitemap.xml`` covering every page in the output

The generator is conference-agnostic: pass ``--conference`` / ``--year``. It
uses only the Python standard library, so it can run inside the GitHub Pages
build with no extra packages. Re-running is idempotent (output is overwritten).
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
import math
from urllib.parse import quote, urlsplit

import knowledge_utils as ku
from knowledge_utils import html_escape as esc

REPO_ROOT = Path(__file__).resolve().parent.parent

TYPE_LABELS = {
    "plenary": "Plenary",
    "keynote": "Keynote",
    "panel": "Panel",
    "breakout": "Breakout",
    "hackathon": "Hackathon",
    "edit-a-thon": "Edit-A-Thon",
    "maintain-a-thon": "Maintain-A-Thon",
    "side-event": "Side Event",
    "ceremony": "Ceremony",
    "workshop": "Workshop",
}

ORG_TYPE_LABELS = {
    "un-agency": "UN agency",
    "government": "Government",
    "foundation": "Foundation",
    "company": "Company",
    "community": "Community",
    "academia": "Academia",
    "ngo": "NGO",
    "multilateral": "Multilateral",
    "other": "Organization",
}


class SiteGenerator:
    def __init__(self, conference: dict[str, Any], year: int, datasets: dict[str, Any], out_dir: Path):
        self.conf = conference
        self.year = year
        self.datasets = datasets
        self.out = out_dir
        self.base = str(conference["site_base_url"]).rstrip("/")
        self.site_name = conference["name"]
        self.generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.idx = ku.build_indexes(datasets)
        # All generated pages/datasets for this conference-year live under this
        # path prefix (e.g. "unosw/2025"), so multiple years/conferences coexist.
        self.base_path = f"{conference['id']}/{year}"
        self.prefix = f"/{self.base_path}"

    def base_crumbs(self) -> list[tuple[str, str | None]]:
        """Leading breadcrumb trail shared by every page in this conference-year."""
        return [("Home", "/"), ("Knowledge", "/explore.html"),
                (f"{self.site_name} {self.year}", f"{self.prefix}/explore.html")]

    # ── small link helpers ────────────────────────────────────────────────
    def speaker_link(self, slug: str) -> str:
        sp = self.idx["speakers_by_slug"].get(slug)
        name = sp["name"] if sp else slug
        return f'<a href="{self.prefix}/speakers/{esc(slug)}.html">{esc(name)}</a>'

    def org_link(self, slug: str) -> str:
        org = self.idx["orgs_by_slug"].get(slug)
        name = org["name"] if org else slug
        return f'<a href="{self.prefix}/organizations/{esc(slug)}.html">{esc(name)}</a>'

    def project_link(self, slug: str) -> str:
        pr = self.idx["projects_by_slug"].get(slug)
        name = pr["name"] if pr else slug
        return f'<a href="{self.prefix}/projects/{esc(slug)}.html">{esc(name)}</a>'

    def topic_tag(self, slug: str) -> str:
        tp = self.idx["topics_by_slug"].get(slug)
        name = tp["name"] if tp else slug
        return f'<a class="kp-tag" href="{self.prefix}/topics/{esc(slug)}.html">{esc(name)}</a>'

    def session_link(self, session_id: str) -> str:
        s = self.idx["sessions_by_id"].get(session_id)
        title = s["title"] if s else session_id
        return f'<a href="{self.prefix}/sessions/{esc(session_id)}.html">{esc(title)}</a>'

    # ── relationship / "connections" helpers ──────────────────────────────
    def distinct_people_for(self, sessions: list[dict[str, Any]], exclude: str | None = None) -> list[str]:
        """Distinct speaker slugs appearing across the given sessions (order preserved)."""
        out: list[str] = []
        seen: set[str] = set()
        for s in sessions:
            for sp in s.get("speakers", []):
                if sp != exclude and sp not in seen and sp in self.idx["speakers_by_slug"]:
                    seen.add(sp)
                    out.append(sp)
        return out

    def distinct_orgs_for(self, sessions: list[dict[str, Any]], exclude: str | None = None) -> list[str]:
        """Distinct organization slugs appearing across the given sessions."""
        out: list[str] = []
        seen: set[str] = set()
        for s in sessions:
            for o in s.get("organizations", []):
                if o != exclude and o not in seen and o in self.idx["orgs_by_slug"]:
                    seen.add(o)
                    out.append(o)
        return out

    def related_section(self, heading: str, links: list[str]) -> str:
        """A 'Related/Connections' block: a wrapped list of entity links, or '' if empty."""
        if not links:
            return ""
        items = "".join(f"<li>{a}</li>" for a in links)
        return (f'<section class="kp-section"><h2>{esc(heading)}</h2>'
                f'<ul class="kp-related">{items}</ul></section>')

    def reference_chip(self, ref_id: str) -> str:
        ref = self.idx["references_by_id"].get(ref_id)
        if not ref:
            return esc(ref_id)
        if ref.get("url"):
            return (f'<a href="{esc(ref["url"])}" rel="noopener noreferrer">{esc(ref["title"])}</a>'
                    f' <span class="kp-meta">({esc(ref.get("type", "reference"))})</span>')
        return f'{esc(ref["title"])} <span class="kp-meta">({esc(ref.get("type", "reference"))})</span>'

    # ── provenance ────────────────────────────────────────────────────────
    def provenance_block(self, prov: dict[str, Any]) -> str:
        if not prov:
            return ""
        bits = [
            f'Source: <a href="{esc(prov["source_url"])}" rel="noopener noreferrer">{esc(prov["source_title"])}</a>',
            f'licensed {esc(prov.get("license", ""))}',
        ]
        if prov.get("attribution"):
            bits.append(f'by {esc(prov["attribution"])}')
        if prov.get("locator"):
            bits.append(f'(reference: {esc(prov["locator"])})')
        meta = []
        if prov.get("method"):
            meta.append(esc(prov["method"]))
        if prov.get("retrieved"):
            meta.append(f'retrieved {esc(prov["retrieved"])}')
        meta_html = f'<br><span class="kp-meta">Provenance: {", ".join(meta)}.</span>' if meta else ""
        return (
            '<aside class="kp-provenance">'
            '<strong>Provenance &amp; attribution.</strong> ' + ". ".join(bits) + "."
            + meta_html +
            "</aside>"
        )

    # ── page shell ────────────────────────────────────────────────────────
    def page(self, rel_path: str, title: str, description: str, header_html: str,
             body_html: str, breadcrumbs: list[tuple[str, str | None]],
             jsonld: dict[str, Any] | None = None) -> str:
        canonical = f"{self.base}{self.prefix}/{rel_path}"
        crumbs = "".join(
            (f'<li><a href="{esc(href)}">{esc(label)}</a></li>' if href
             else f'<li aria-current="page">{esc(label)}</li>')
            for label, href in breadcrumbs
        )
        jsonld_html = ""
        if jsonld is not None:
            # Neutralize <, >, & so a field value can never break out of the
            # <script> element (e.g. a "</script>" or "<!--" in scraped data).
            # These are valid JSON string escapes, so the block still parses.
            payload = (json.dumps(jsonld, ensure_ascii=False)
                       .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
            jsonld_html = f'<script type="application/ld+json">{payload}</script>'
        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{esc(title)}</title>
    <meta name="description" content="{esc(description)}" />
    <link rel="canonical" href="{esc(canonical)}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="{esc(self.site_name)} — Knowledge Platform" />
    <meta property="og:title" content="{esc(title)}" />
    <meta property="og:description" content="{esc(description)}" />
    <meta property="og:url" content="{esc(canonical)}" />
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:title" content="{esc(title)}" />
    <meta name="twitter:description" content="{esc(description)}" />
    <link rel="stylesheet" href="/shared.css" />
    <link rel="stylesheet" href="/knowledge.css" />
    {jsonld_html}
  </head>
  <body>
    <a class="skip-link" href="#main-content">Skip to main content</a>
    <header class="kp-header">
      <div class="kp-header-inner">
{header_html}
      </div>
    </header>
    <nav class="kp-breadcrumb" aria-label="Breadcrumb">
      <ol>{crumbs}</ol>
    </nav>
    <main id="main-content" class="kp-main">
{body_html}
    </main>
    <footer class="kp-footer">
      <p>Part of the {esc(self.site_name)} knowledge platform — an open, AI-ready index of
        public information that links back to authoritative sources. Page generated
        {esc(self.generated_at)}.</p>
    </footer>
    <script src="/nav.js" defer></script>
  </body>
</html>
"""

    def write(self, rel_path: str, html: str) -> None:
        target = self.out / self.base_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")

    # ── sections shared by detail pages ───────────────────────────────────
    def session_list_section(self, heading: str, sessions: list[dict[str, Any]]) -> str:
        if not sessions:
            return ""
        items = "".join(
            f'<li class="kp-card"><h3>{self.session_link(s["id"])}</h3>'
            f'<p><span class="kp-badge">{esc(TYPE_LABELS.get(s.get("type", ""), s.get("type", "")))}</span> '
            f'{esc(s.get("day", ""))}{(" · " + esc(s["date"])) if s.get("date") else ""}</p></li>'
            for s in sessions
        )
        return (f'<section class="kp-section"><h2>{esc(heading)} '
                f'<span class="kp-meta">({len(sessions)})</span></h2>'
                f'<ul class="kp-grid">{items}</ul></section>')

    def topics_from_sessions(self, sessions: list[dict[str, Any]]) -> list[str]:
        seen: list[str] = []
        for s in sessions:
            for tp in s.get("topics", []):
                if tp not in seen:
                    seen.append(tp)
        return seen

    # ── detail page builders ──────────────────────────────────────────────
    def render_session(self, session: dict[str, Any]) -> None:
        sid = session["id"]
        title = session["title"]
        type_label = TYPE_LABELS.get(session.get("type", ""), session.get("type", ""))
        header = (
            f'        <p class="kp-eyebrow">{esc(session.get("track", "Session"))}</p>\n'
            f'        <h1>{esc(title)}</h1>\n'
            f'        <p>{esc(session.get("day", ""))}'
            f'{(" · " + esc(session["date"])) if session.get("date") else ""}'
            f'{(" · " + esc(session["room"])) if session.get("room") else ""}</p>'
        )
        parts: list[str] = []
        parts.append(f'<p><span class="kp-badge">{esc(type_label)}</span></p>')
        if session.get("summary"):
            parts.append(f'<section class="kp-section"><p>{esc(session["summary"])}</p></section>')
        if session.get("agenda"):
            agenda = "".join(f"<li>{esc(a)}</li>" for a in session["agenda"])
            parts.append(f'<section class="kp-section"><h2>Agenda</h2><ul>{agenda}</ul></section>')
        media = []
        if session.get("video_url"):
            media.append(f'<a href="{esc(session["video_url"])}" rel="noopener noreferrer">▶ Official recording (UN Web TV)</a>')
        if session.get("transcript_url"):
            media.append(f'<a href="{esc(session["transcript_url"])}" rel="noopener noreferrer">📄 Draft transcript</a>')
        if session.get("official_url"):
            media.append(f'<a href="{esc(session["official_url"])}" rel="noopener noreferrer">🌐 Official page</a>')
        if media:
            items = "".join(f"<li>{m}</li>" for m in media)
            parts.append(f'<section class="kp-section"><h2>Recording &amp; links</h2><ul>{items}</ul></section>')
        if session.get("speakers"):
            people = "".join(
                f'<li class="kp-card"><h3>{self.speaker_link(sp)}</h3>'
                f'<p>{esc(self.idx["speakers_by_slug"].get(sp, {}).get("role", ""))}</p></li>'
                for sp in session["speakers"]
            )
            parts.append(f'<section class="kp-section"><h2>Speakers</h2><ul class="kp-grid">{people}</ul></section>')
        if session.get("organizations"):
            orgs = " ".join(self.org_link(o) for o in session["organizations"])
            parts.append(f'<section class="kp-section"><h2>Organizations</h2><p>{orgs}</p></section>')
        if session.get("projects"):
            projs = " ".join(self.project_link(p) for p in session["projects"])
            parts.append(f'<section class="kp-section"><h2>Referenced projects</h2><p>{projs}</p></section>')
        if session.get("topics"):
            tags = "".join(self.topic_tag(t) for t in session["topics"])
            parts.append(f'<section class="kp-section"><h2>Topics</h2><div class="kp-tags">{tags}</div></section>')
        if session.get("references"):
            refs = "".join(f"<li>{self.reference_chip(r)}</li>" for r in session["references"])
            parts.append(f'<section class="kp-section"><h2>Referenced standards &amp; reports</h2><ul>{refs}</ul></section>')
        quotes = self.idx["quotes_by_session"].get(sid, [])
        if quotes:
            parts.append(self.quotes_section(quotes))
        parts.append(self.provenance_block(session.get("provenance", {})))

        jsonld = {
            "@context": "https://schema.org",
            "@type": "Event",
            "name": title,
            "description": session.get("summary", ""),
            "url": f"{self.base}/sessions/{sid}.html",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "location": {"@type": "Place", "name": session.get("room") or "United Nations, New York"},
        }
        if session.get("date"):
            jsonld["startDate"] = session["date"]
        if session.get("organizations"):
            jsonld["organizer"] = [
                {"@type": "Organization", "name": self.idx["orgs_by_slug"].get(o, {}).get("name", o)}
                for o in session["organizations"]
            ]
        description = (session.get("summary") or title)[:200]
        breadcrumbs = self.base_crumbs() + [
            ("Sessions", f"{self.prefix}/sessions/index.html"), (title, None)]
        self.write(f"sessions/{sid}.html",
                   self.page(f"sessions/{sid}.html", f"{title} · {self.site_name} {self.year}",
                             description, header, "\n".join(parts), breadcrumbs, jsonld))

    def quotes_section(self, quotes: list[dict[str, Any]]) -> str:
        blocks = []
        for q in quotes:
            who = q.get("speaker_name") or (
                self.idx["speakers_by_slug"].get(q.get("speaker", ""), {}).get("name", ""))
            cite = ""
            if who:
                if q.get("speaker"):
                    who_html = self.speaker_link(q["speaker"])
                else:
                    who_html = esc(who)
                where = self.session_link(q["session"]) if q.get("session") else ""
                cite = f'<cite>— {who_html}{(", " + where) if where else ""}</cite>'
            blocks.append(f'<figure class="kp-quote"><blockquote>{esc(q["text"])}</blockquote>{cite}</figure>')
        return f'<section class="kp-section"><h2>Quotes</h2>{"".join(blocks)}</section>'

    def render_speaker(self, speaker: dict[str, Any]) -> None:
        slug = speaker["slug"]
        name = speaker["name"]
        sessions = self.idx["sessions_by_speaker"].get(slug, [])
        quotes = self.idx["quotes_by_speaker"].get(slug, [])
        role = speaker.get("role", "")
        org_slug = speaker.get("organization_slug")
        org_display = speaker.get("organization", "")
        header = (
            f'        <p class="kp-eyebrow">Speaker · {esc(self.site_name)} {self.year}</p>\n'
            f'        <h1>{esc(name)}</h1>\n'
            f'        <p class="kp-role">{esc(role)}{(" · " + esc(org_display)) if org_display else ""}</p>'
        )
        parts: list[str] = []
        dl = []
        if org_slug:
            dl.append(f"<dt>Organization</dt><dd>{self.org_link(org_slug)}</dd>")
        elif org_display:
            dl.append(f"<dt>Organization</dt><dd>{esc(org_display)}</dd>")
        if speaker.get("country"):
            dl.append(f"<dt>Country</dt><dd>{esc(speaker['country'])}</dd>")
        for field, label in [("github", "GitHub"), ("mastodon", "Mastodon"),
                             ("bluesky", "Bluesky"), ("linkedin", "LinkedIn"), ("website", "Website")]:
            if speaker.get(field):
                dl.append(f'<dt>{label}</dt><dd><a href="{esc(speaker[field])}" rel="noopener noreferrer">{esc(speaker[field])}</a></dd>')
        if dl:
            parts.append(f'<section class="kp-section"><dl class="kp-detail">{"".join(dl)}</dl></section>')
        if speaker.get("biography"):
            parts.append(f'<section class="kp-section"><h2>Biography</h2><p>{esc(speaker["biography"])}</p></section>')
        topics = self.topics_from_sessions(sessions)
        if topics:
            tags = "".join(self.topic_tag(t) for t in topics)
            parts.append(f'<section class="kp-section"><h2>Topics discussed</h2><div class="kp-tags">{tags}</div></section>')
        parts.append(self.session_list_section("Sessions", sessions))
        peers = self.distinct_people_for(sessions, exclude=slug)
        parts.append(self.related_section("Connected speakers (shared a session)",
                                          [self.speaker_link(s) for s in peers]))
        related_orgs = self.distinct_orgs_for(sessions, exclude=org_slug)
        parts.append(self.related_section("Organizations in their sessions",
                                          [self.org_link(o) for o in related_orgs]))
        if quotes:
            parts.append(self.quotes_section(quotes))
        parts.append(self.provenance_block(speaker.get("provenance", {})))

        jsonld = {
            "@context": "https://schema.org",
            "@type": "Person",
            "name": name,
            "url": f"{self.base}/speakers/{slug}.html",
        }
        if role:
            jsonld["jobTitle"] = role
        if org_display:
            jsonld["affiliation"] = {"@type": "Organization", "name": org_display}
        if speaker.get("country"):
            jsonld["nationality"] = speaker["country"]
        description = f"{name}{(' — ' + role) if role else ''}{(' at ' + org_display) if org_display else ''}. Sessions and quotes from {self.site_name} {self.year}."
        breadcrumbs = self.base_crumbs() + [
            ("Speakers", f"{self.prefix}/speakers/index.html"), (name, None)]
        self.write(f"speakers/{slug}.html",
                   self.page(f"speakers/{slug}.html", f"{name} · {self.site_name} {self.year}",
                             description[:200], header, "\n".join(parts), breadcrumbs, jsonld))

    def render_organization(self, org: dict[str, Any]) -> None:
        slug = org["slug"]
        name = org["name"]
        sessions = self.idx["sessions_by_org"].get(slug, [])
        people = self.idx["speakers_by_org"].get(slug, [])
        projects = self.idx["projects_by_org"].get(slug, [])
        type_label = ORG_TYPE_LABELS.get(org.get("type", ""), "Organization")
        header = (
            f'        <p class="kp-eyebrow">{esc(type_label)} · {esc(self.site_name)} {self.year}</p>\n'
            f'        <h1>{esc(name)}</h1>'
        )
        parts: list[str] = []
        dl = [f"<dt>Type</dt><dd>{esc(type_label)}</dd>"]
        if org.get("country"):
            dl.append(f"<dt>Country</dt><dd>{esc(org['country'])}</dd>")
        if org.get("website"):
            dl.append(f'<dt>Website</dt><dd><a href="{esc(org["website"])}" rel="noopener noreferrer">{esc(org["website"])}</a></dd>')
        parts.append(f'<section class="kp-section"><dl class="kp-detail">{"".join(dl)}</dl></section>')
        if people:
            ppl = "".join(
                f'<li class="kp-card"><h3>{self.speaker_link(p["slug"])}</h3>'
                f'<p>{esc(p.get("role", ""))}</p></li>' for p in people)
            parts.append(f'<section class="kp-section"><h2>People <span class="kp-meta">({len(people)})</span></h2><ul class="kp-grid">{ppl}</ul></section>')
        if projects:
            pr = "".join(
                f'<li class="kp-card"><h3>{self.project_link(p["slug"])}</h3>'
                f'<p>{esc((p.get("description", "") or "")[:120])}</p></li>' for p in projects)
            parts.append(f'<section class="kp-section"><h2>Projects</h2><ul class="kp-grid">{pr}</ul></section>')
        topics = self.topics_from_sessions(sessions)
        if topics:
            tags = "".join(self.topic_tag(t) for t in topics)
            parts.append(f'<section class="kp-section"><h2>Topics</h2><div class="kp-tags">{tags}</div></section>')
        parts.append(self.session_list_section("Sessions", sessions))
        related = self.distinct_orgs_for(sessions, exclude=slug)
        parts.append(self.related_section("Related organizations (shared a session)",
                                          [self.org_link(o) for o in related]))
        parts.append(self.provenance_block(org.get("provenance", {})))

        jsonld = {"@context": "https://schema.org", "@type": "Organization", "name": name,
                  "url": f"{self.base}/organizations/{slug}.html"}
        if org.get("website"):
            jsonld["sameAs"] = org["website"]
        description = f"{name} — {type_label} at {self.site_name} {self.year}: sessions, people, and projects."
        breadcrumbs = self.base_crumbs() + [
            ("Organizations", f"{self.prefix}/organizations/index.html"), (name, None)]
        self.write(f"organizations/{slug}.html",
                   self.page(f"organizations/{slug}.html", f"{name} · {self.site_name} {self.year}",
                             description[:200], header, "\n".join(parts), breadcrumbs, jsonld))

    def render_project(self, project: dict[str, Any]) -> None:
        slug = project["slug"]
        name = project["name"]
        sessions = self.idx["sessions_by_project"].get(slug, [])
        header = (
            f'        <p class="kp-eyebrow">Project · {esc(self.site_name)} {self.year}</p>\n'
            f'        <h1>{esc(name)}</h1>'
        )
        parts: list[str] = []
        if project.get("description"):
            parts.append(f'<section class="kp-section"><p>{esc(project["description"])}</p></section>')
        dl = []
        if project.get("website"):
            dl.append(f'<dt>Website</dt><dd><a href="{esc(project["website"])}" rel="noopener noreferrer">{esc(project["website"])}</a></dd>')
        if project.get("license"):
            dl.append(f"<dt>License</dt><dd>{esc(project['license'])}</dd>")
        if project.get("organizations"):
            orgs = " ".join(self.org_link(o) for o in project["organizations"])
            dl.append(f"<dt>Organizations</dt><dd>{orgs}</dd>")
        if dl:
            parts.append(f'<section class="kp-section"><dl class="kp-detail">{"".join(dl)}</dl></section>')
        parts.append(self.session_list_section("Sessions", sessions))
        parts.append(self.provenance_block(project.get("provenance", {})))

        description = (project.get("description") or name)[:200]
        breadcrumbs = self.base_crumbs() + [
            ("Projects", f"{self.prefix}/projects/index.html"), (name, None)]
        self.write(f"projects/{slug}.html",
                   self.page(f"projects/{slug}.html", f"{name} · {self.site_name} {self.year}",
                             description, header, "\n".join(parts), breadcrumbs))

    def render_topic(self, topic: dict[str, Any]) -> None:
        slug = topic["slug"]
        name = topic["name"]
        sessions = self.idx["sessions_by_topic"].get(slug, [])
        quotes = self.idx["quotes_by_topic"].get(slug, [])
        header = (
            f'        <p class="kp-eyebrow">Topic · {esc(self.site_name)} {self.year}</p>\n'
            f'        <h1>{esc(name)}</h1>\n'
            f'        <p>{esc(topic.get("description", ""))}</p>'
        )
        parts: list[str] = []
        parts.append(self.session_list_section("Sessions on this topic", sessions))
        people = self.distinct_people_for(sessions)
        parts.append(self.related_section("People who spoke on this theme",
                                          [self.speaker_link(s) for s in people]))
        orgs = self.distinct_orgs_for(sessions)
        parts.append(self.related_section("Organizations active on this theme",
                                          [self.org_link(o) for o in orgs]))
        parts.append(
            f'<section class="kp-section"><h2>Across years</h2>'
            f'<p><a href="/timeline.html#theme-{esc(slug)}">'
            f'See how “{esc(name)}” recurs across UN Open Source Week years →</a></p></section>')
        if quotes:
            parts.append(self.quotes_section(quotes))
        note = {
            "source_url": self.conf["official_urls"][0] if self.conf.get("official_urls") else self.base,
            "source_title": f"{self.site_name} programme",
            "license": "CC-BY-4.0",
            "method": "manual-extraction",
            "locator": "Topic vocabulary defined in conferences/" + self.conf["id"] + ".json",
        }
        parts.append(self.provenance_block(note))
        description = f"{name}: {topic.get('description', '')}"[:200]
        breadcrumbs = self.base_crumbs() + [
            ("Topics", f"{self.prefix}/topics/index.html"), (name, None)]
        self.write(f"topics/{slug}.html",
                   self.page(f"topics/{slug}.html", f"{name} · {self.site_name} {self.year} topics",
                             description, header, "\n".join(parts), breadcrumbs))

    # ── index pages ───────────────────────────────────────────────────────
    def render_index(self, rel: str, eyebrow: str, title: str, intro: str,
                     body: str, crumb_label: str) -> None:
        header = (f'        <p class="kp-eyebrow">{esc(eyebrow)}</p>\n'
                  f'        <h1>{esc(title)}</h1>\n        <p>{esc(intro)}</p>')
        breadcrumbs = self.base_crumbs() + [(crumb_label, None)]
        self.write(rel, self.page(rel, f"{title} · {self.site_name} {self.year}",
                                  intro[:200], header, body, breadcrumbs))

    def render_sessions_index(self) -> None:
        by_day: dict[str, list] = {}
        for s in self.idx["sessions_sorted"]:
            by_day.setdefault(s.get("day", "Sessions"), []).append(s)
        sections = []
        for day, sess in by_day.items():
            cards = "".join(
                f'<li class="kp-card"><h3>{self.session_link(s["id"])}</h3>'
                f'<p><span class="kp-badge">{esc(TYPE_LABELS.get(s.get("type", ""), s.get("type", "")))}</span>'
                f'{(" · " + str(len(s.get("speakers", []))) + " speakers") if s.get("speakers") else ""}</p></li>'
                for s in sess)
            sections.append(f'<section class="kp-section"><h2>{esc(day)}</h2><ul class="kp-grid">{cards}</ul></section>')
        self.render_index("sessions/index.html", f"{self.site_name} {self.year}", "Sessions",
                          f"All {len(self.idx['sessions_sorted'])} indexed sessions across the week.",
                          "\n".join(sections), "Sessions")

    def render_speakers_index(self) -> None:
        speakers = sorted(self.datasets["speakers"], key=lambda s: s["name"])
        cards = "".join(
            f'<li class="kp-card"><h3>{self.speaker_link(s["slug"])}</h3>'
            f'<p>{esc(s.get("role", ""))}{(" · " + esc(s["organization"])) if s.get("organization") else ""}'
            f'{(" · " + esc(s["country"])) if s.get("country") else ""}</p></li>'
            for s in speakers)
        body = (f'<section class="kp-section"><h2>All speakers '
                f'<span class="kp-meta">({len(speakers)})</span></h2>'
                f'<ul class="kp-grid">{cards}</ul></section>')
        self.render_index("speakers/index.html", f"{self.site_name} {self.year}", "Speakers",
                          f"{len(speakers)} speakers indexed from the programme.", body, "Speakers")

    def render_organizations_index(self) -> None:
        by_type: dict[str, list] = {}
        for o in sorted(self.datasets["organizations"], key=lambda o: o["name"]):
            by_type.setdefault(o.get("type", "other"), []).append(o)
        sections = []
        for otype, orgs in sorted(by_type.items(), key=lambda kv: ORG_TYPE_LABELS.get(kv[0], kv[0])):
            cards = "".join(
                f'<li class="kp-card"><h3>{self.org_link(o["slug"])}</h3>'
                f'<p>{(esc(o["country"]) + " · ") if o.get("country") else ""}'
                f'{len(self.idx["sessions_by_org"].get(o["slug"], []))} sessions</p></li>'
                for o in orgs)
            sections.append(f'<section class="kp-section"><h2>{esc(ORG_TYPE_LABELS.get(otype, otype))}</h2><ul class="kp-grid">{cards}</ul></section>')
        self.render_index("organizations/index.html", f"{self.site_name} {self.year}", "Organizations",
                          f"{len(self.datasets['organizations'])} organizations referenced across the week.",
                          "\n".join(sections), "Organizations")

    def render_projects_index(self) -> None:
        cards = "".join(
            f'<li class="kp-card"><h3>{self.project_link(p["slug"])}</h3>'
            f'<p>{esc((p.get("description", "") or "")[:130])}</p></li>'
            for p in sorted(self.datasets["projects"], key=lambda p: p["name"]))
        body = (f'<section class="kp-section"><h2>All projects '
                f'<span class="kp-meta">({len(self.datasets["projects"])})</span></h2>'
                f'<ul class="kp-grid">{cards}</ul></section>')
        self.render_index("projects/index.html", f"{self.site_name} {self.year}", "Projects",
                          f"{len(self.datasets['projects'])} open source projects discussed during the week.",
                          body, "Projects")

    def render_topics_index(self) -> None:
        cards = "".join(
            f'<li class="kp-card"><h3>{self.topic_tag(t["slug"])}</h3>'
            f'<p>{esc(t.get("description", ""))}</p>'
            f'<p class="kp-meta">{len(self.idx["sessions_by_topic"].get(t["slug"], []))} sessions</p></li>'
            for t in self.datasets["topics"])
        body = (f'<section class="kp-section"><h2>All themes '
                f'<span class="kp-meta">({len(self.datasets["topics"])})</span></h2>'
                f'<ul class="kp-grid">{cards}</ul></section>')
        self.render_index("topics/index.html", f"{self.site_name} {self.year}", "Topics",
                          f"{len(self.datasets['topics'])} themes used to classify the programme.",
                          body, "Topics")

    def render_hub(self) -> None:
        counts = {name: len(self.datasets[name]) for name in ku.DATASETS}
        stats = "".join(
            f'<li class="kp-stat"><span class="kp-stat-num">{counts[n]}</span>'
            f'<span class="kp-stat-label">{label}</span></li>'
            for n, label in [("sessions", "Sessions"), ("speakers", "Speakers"),
                             ("organizations", "Organizations"), ("projects", "Projects"),
                             ("topics", "Topics"), ("quotes", "Quotes")])
        browse = "".join(
            f'<li class="kp-card"><h3><a href="{self.prefix}{href}">{esc(label)}</a></h3><p>{esc(desc)}</p></li>'
            for label, href, desc in [
                ("Sessions", "/sessions/index.html", "Every indexed session, by day."),
                ("Speakers", "/speakers/index.html", "Profiles for each speaker."),
                ("Organizations", "/organizations/index.html", "UN agencies, governments, foundations, companies, communities."),
                ("Projects", "/projects/index.html", "Open source projects discussed."),
                ("Topics", "/topics/index.html", "Themes across the programme."),
            ])
        api_base = f"{self.prefix}/api"
        datasets_links = "".join(
            f'<li><a href="{api_base}/{n}.json"><code>{n}.json</code></a></li>' for n in ku.DATASETS)
        # Provenance shown on the hub is taken from the data itself, so it is
        # correct per year (the 2025 report vs the 2026 agenda).
        sample_prov = next((s["provenance"] for s in self.datasets["sessions"] if s.get("provenance")), None)
        body = f"""<section class="kp-section">
  <p>An open, AI-ready index of public information about {esc(self.site_name)} {self.year}.
     Everything here is derived from public sources and links back to the authoritative
     origin. Nothing is invented; every record carries provenance.</p>
  <ul class="kp-stats">{stats}</ul>
</section>
<section class="kp-section"><h2>Browse</h2><ul class="kp-grid">{browse}</ul></section>
<section class="kp-section">
  <h2>AI-ready datasets</h2>
  <p>Structured JSON for direct consumption by tools and language models:</p>
  <ul>{datasets_links}
    <li><a href="{api_base}/knowledge-graph.json"><code>knowledge-graph.json</code></a> — nodes &amp; edges</li>
  </ul>
</section>
{self.provenance_block(sample_prov) if sample_prov else ""}"""
        header = (f'        <p class="kp-eyebrow">Knowledge Platform</p>\n'
                  f'        <h1>Explore {esc(self.site_name)} {self.year}</h1>\n'
                  f'        <p>Sessions, speakers, organizations, projects, and themes — '
                  f'cross-linked and traceable to public sources.</p>')
        breadcrumbs = [("Home", "/"), ("Knowledge", "/explore.html"),
                       (f"{self.site_name} {self.year}", None)]
        intro = f"Open knowledge platform for {self.site_name} {self.year}."
        self.write("explore.html",
                   self.page("explore.html", f"Explore {self.site_name} {self.year}",
                             intro, header, body, breadcrumbs))

    # ── datasets + graph (per conference-year, under the path prefix) ─────
    def write_datasets(self) -> None:
        api_dir = self.out / self.base_path / "api"
        api_dir.mkdir(parents=True, exist_ok=True)
        for name in ku.DATASETS:
            (api_dir / f"{name}.json").write_text(
                json.dumps(self.datasets[name], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sample_prov = next((s["provenance"] for s in self.datasets["sessions"] if s.get("provenance")), {})
        manifest = {
            "conference": self.conf["id"],
            "name": self.site_name,
            "year": self.year,
            "generated_at": self.generated_at,
            "base_path": self.base_path,
            "explore_url": f"{self.prefix}/explore.html",
            "license": sample_prov.get("license", ""),
            "source": sample_prov.get("source_url", ""),
            "datasets": {name: len(self.datasets[name]) for name in ku.DATASETS},
            "knowledge_graph": f"{self.prefix}/api/knowledge-graph.json",
        }
        (api_dir / "index.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        graph = ku.build_graph(self.conf["id"], self.year, self.datasets,
                               f"{self.base}{self.prefix}", self.generated_at)
        (api_dir / "knowledge-graph.json").write_text(
            json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def generate(self) -> dict[str, int]:
        self.render_hub()
        self.render_sessions_index()
        self.render_speakers_index()
        self.render_organizations_index()
        self.render_projects_index()
        self.render_topics_index()
        for s in self.datasets["sessions"]:
            self.render_session(s)
        for sp in self.datasets["speakers"]:
            self.render_speaker(sp)
        for o in self.datasets["organizations"]:
            self.render_organization(o)
        for p in self.datasets["projects"]:
            self.render_project(p)
        for t in self.datasets["topics"]:
            self.render_topic(t)
        self.write_datasets()
        return {
            "sessions": len(self.datasets["sessions"]),
            "speakers": len(self.datasets["speakers"]),
            "organizations": len(self.datasets["organizations"]),
            "projects": len(self.datasets["projects"]),
            "topics": len(self.datasets["topics"]),
        }


def rebuild_top_level(out_dir: Path, base_url: str, repo_root: Path | None = None) -> list[dict[str, Any]]:
    """(Re)build the cross-year hub (/explore.html) and the merged sitemap.

    Scans the output for every conference-year manifest (``<conf>/<year>/api/
    index.json``) and every ``*.html`` file, so running the generator for
    multiple years accumulates instead of clobbering. Idempotent.
    """
    out = Path(out_dir)
    base = base_url.rstrip("/")
    manifests = []
    for index_file in sorted(out.glob("*/*/api/index.json")):
        try:
            manifests.append(json.loads(index_file.read_text()))
        except (json.JSONDecodeError, OSError):
            continue

    _write_search_index(out, manifests, repo_root)
    _write_search_page(out, base)
    _write_graph_page(out, base, manifests)
    _write_top_hub(out, manifests)
    _write_sitemap(out, base)
    _write_platform_manifest(out, base, manifests)
    _write_llms_txt(out, base, manifests)
    return manifests


def _write_platform_manifest(out: Path, base: str, manifests: list[dict[str, Any]]) -> None:
    """Machine-readable discovery entrypoint at /api/index.json (WebMCP, Phase 16).

    A single JSON document an AI system can fetch to discover every
    conference-year and its datasets without crawling any HTML.
    """
    entries = []
    for m in sorted(manifests, key=lambda m: (m.get("conference", ""), -int(m.get("year", 0)))):
        api_base = f"/{m['base_path']}/api"
        entries.append({
            "conference": m.get("conference"),
            "name": m.get("name"),
            "year": m.get("year"),
            "explore_url": m.get("explore_url"),
            "api_base": api_base,
            "datasets": {n: f"{api_base}/{n}.json" for n in ku.DATASETS},
            "knowledge_graph": f"{api_base}/knowledge-graph.json",
            "counts": m.get("datasets", {}),
            "license": m.get("license", ""),
            "source": m.get("source", ""),
        })
    manifest = {
        "name": "UN Open Source Week Knowledge Platform",
        "description": "Open, AI-ready index of public information about UN Open Source Week, "
                       "with provenance and links back to authoritative sources.",
        "base_url": base,
        "search_index": "/api/search-index.json",
        "conference_years": entries,
    }
    (out / "api").mkdir(parents=True, exist_ok=True)
    (out / "api" / "index.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_llms_txt(out: Path, base: str, manifests: list[dict[str, Any]]) -> None:
    """Write /llms.txt (the llms.txt convention) pointing AI agents at the data."""
    lines = [
        "# UN Open Source Week — Knowledge Platform",
        "",
        "> Open, AI-ready index of public information about UN Open Source Week. Every record "
        "carries provenance and links back to an authoritative source; no copyrighted media is hosted.",
        "",
        f"Machine-readable discovery entrypoint: {base}/api/index.json",
        f"Combined search index (all years): {base}/api/search-index.json",
        "",
        "## Conference years",
    ]
    for m in sorted(manifests, key=lambda m: (m.get("conference", ""), -int(m.get("year", 0)))):
        api_base = f"{base}/{m['base_path']}/api"
        d = m.get("datasets", {})
        counts = ", ".join(f"{d.get(k, 0)} {k}" for k in ku.DATASETS if d.get(k))
        lines.append(f"- {m.get('name')} {m.get('year')} ({counts}) — "
                     f"explore: {base}{m.get('explore_url')}")
        for n in ku.DATASETS:
            lines.append(f"  - [{n}]({api_base}/{n}.json)")
        lines.append(f"  - [knowledge-graph]({api_base}/knowledge-graph.json)")
    (out / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_search_index(out: Path, manifests: list[dict[str, Any]], repo_root: Path | None = None) -> None:
    """Build /api/search-index.json across every conference-year (Phase 11).

    A single flat list of lightweight records — each tagged ``category``
    ("events" for the program: sessions/speakers/orgs/projects/themes; "history"
    for the archive: recordings, transcripts, reports/documents) and ``year`` so
    the static search page can facet by category and year and filter the text
    client-side. No server, no runtime deps. Idempotent.

    Event records are read from the per-year api datasets already written.
    History records are derived from those datasets' recordings/transcripts
    (correct year) and from the ``conferences/<year>/`` document corpus.
    """
    records: list[dict[str, Any]] = []

    def push(category: str, type_: str, title: str, url: str, year: int | None,
             meta: str, *extra: str, transcript_url: str = "") -> None:
        blob = " ".join(p for p in (title, meta, type_, *extra) if p).lower()
        rec = {"category": category, "type": type_, "title": title, "url": url,
               "year": year, "meta": meta, "text": blob}
        if transcript_url:
            rec["transcript_url"] = transcript_url
        records.append(rec)

    for m in manifests:
        base_path = m.get("base_path")
        year = m.get("year")
        if not base_path:
            continue
        api_dir = out / base_path / "api"

        def load(name: str) -> list:
            try:
                return json.loads((api_dir / f"{name}.json").read_text())
            except (json.JSONDecodeError, OSError):
                return []

        topic_name = {t["slug"]: t["name"] for t in load("topics")}
        sessions = load("sessions")

        for s in sessions:
            topics = " ".join(topic_name.get(t, t) for t in s.get("topics", []))
            meta = " · ".join(p for p in (s.get("day", ""), TYPE_LABELS.get(s.get("type", ""), "")) if p)
            push("events", "session", s.get("title", ""), f"/{base_path}/sessions/{s['id']}.html",
                 year, meta, s.get("summary", ""), topics)
        for sp in load("speakers"):
            meta = " · ".join(p for p in (sp.get("role", ""), sp.get("organization", "")) if p)
            push("events", "speaker", sp.get("name", ""), f"/{base_path}/speakers/{sp['slug']}.html",
                 year, meta, sp.get("country", ""))
        for o in load("organizations"):
            push("events", "organization", o.get("name", ""), f"/{base_path}/organizations/{o['slug']}.html",
                 year, ORG_TYPE_LABELS.get(o.get("type", ""), "Organization"))
        for p in load("projects"):
            push("events", "project", p.get("name", ""), f"/{base_path}/projects/{p['slug']}.html",
                 year, "Project", p.get("description", ""))
        for t in load("topics"):
            push("events", "topic", t.get("name", ""), f"/{base_path}/topics/{t['slug']}.html",
                 year, "Theme", t.get("description", ""))

        # History — recordings/transcripts, one per distinct recording, derived
        # from the (correctly year-mapped) session data so it never mis-attributes.
        seen: dict[str, dict[str, Any]] = {}
        for s in sessions:
            vid = s.get("video_url") or s.get("transcript_url")
            if not vid or vid in seen:
                if vid:
                    seen[vid]["times"].append(s.get("start_time", ""))
                continue
            seen[vid] = {"day": s.get("day", ""), "video": s.get("video_url", ""),
                         "transcript": s.get("transcript_url", ""), "times": [s.get("start_time", "")]}
        for info in seen.values():
            times = [t for t in info["times"] if t]
            part = ""
            if times:
                part = "Part 1 (morning)" if min(times) < "13:00" else "Part 2 (afternoon)"
            title = " · ".join(p for p in (info["day"], part) if p) or f"Recording {year}"
            url = info["video"] or info["transcript"]
            push("history", "recording", title, url, year,
                 "Recording & draft transcript", "video transcript webtv",
                 transcript_url=info["transcript"])

    # History — documents and archived page snapshots from the corpus:
    # PDF reports/concept notes, and saved official event pages (.mhtml/.html).
    if repo_root is not None:
        conf_dir = Path(repo_root) / "conferences"
        doc_kinds = [("*.pdf", "document", "Document (PDF)"),
                     ("*.mhtml", "page", "Archived page snapshot"),
                     ("*.html", "page", "Archived page snapshot")]
        for year_dir in sorted(conf_dir.glob("*")):
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue
            doc_year = int(year_dir.name)
            for pattern, type_, label in doc_kinds:
                for f in sorted(year_dir.glob(pattern)):
                    url = ("https://github.com/mgifford/unosw.plus/blob/main/conferences/"
                           f"{year_dir.name}/{quote(f.name)}")
                    push("history", type_, _humanize_doc(f.stem), url, doc_year, label)

    cat_order = {"events": 0, "history": 1}
    records.sort(key=lambda r: (cat_order.get(r["category"], 9), r["type"],
                                -(r.get("year") or 0), r["title"].lower()))
    (out / "api").mkdir(parents=True, exist_ok=True)
    (out / "api" / "search-index.json").write_text(
        json.dumps({"records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _humanize_doc(stem: str) -> str:
    """Turn a document filename stem into a readable title."""
    text = stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(text.split())


# ── relationship graph map (Phase 4 visual) ───────────────────────────────────
GRAPH_TYPE_META = [  # ordered; (type, label, colour)
    ("topic", "Theme", "#015d86"),
    ("organization", "Organization", "#b45309"),
    ("person", "Person", "#6d28d9"),
    ("project", "Project", "#0f766e"),
    ("country", "Country", "#be185d"),
    ("session", "Session", "#475569"),
]
GRAPH_COLOR = {t: c for t, _, c in GRAPH_TYPE_META}
GRAPH_LABEL = {t: l for t, l, _ in GRAPH_TYPE_META}


def _build_combined_graph(out: Path, manifests: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Merge every year's knowledge-graph.json into one graph (Phase 4).

    Nodes are deduped by id, so a shared theme or a recurring organization
    becomes a single node bridging the years it appears in — a genuine
    cross-year relationship graph. Node urls are made root-relative.
    """
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple, dict[str, Any]] = {}
    for m in manifests:
        base_path, year = m.get("base_path"), m.get("year")
        if not base_path:
            continue
        try:
            g = json.loads((out / base_path / "api" / "knowledge-graph.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for n in g.get("nodes", []):
            rec = nodes.get(n["id"])
            path = urlsplit(n["url"]).path if n.get("url") else ""
            if rec is None:
                nodes[n["id"]] = {"id": n["id"], "type": n.get("type", ""),
                                  "label": n.get("label", n["id"]), "url": path,
                                  "years": {year} if year else set()}
            else:
                if year:
                    rec["years"].add(year)
                if path and not rec["url"]:
                    rec["url"] = path
        for e in g.get("edges", []):
            key = (e["source"], e["target"], e["type"])
            rec = edges.get(key)
            if rec is None:
                edges[key] = {"source": e["source"], "target": e["target"],
                              "type": e["type"], "years": {year} if year else set()}
            elif year:
                rec["years"].add(year)

        # Derive direct person↔theme and organization↔theme edges (through the
        # sessions that connect them) so a people/themes/organizations view is
        # connected on its own, without the session nodes.
        ntype = {n["id"]: n.get("type") for n in g.get("nodes", [])}
        s_people: dict[str, list] = {}
        s_orgs: dict[str, list] = {}
        s_topics: dict[str, list] = {}
        for e in g.get("edges", []):
            s, t, ty = e["source"], e["target"], e["type"]
            if ty == "spoke_at" and ntype.get(t) == "session":
                s_people.setdefault(t, []).append(s)
            elif ty == "organized" and ntype.get(t) == "session":
                s_orgs.setdefault(t, []).append(s)
            elif ty == "discussed_topic" and ntype.get(s) == "session":
                s_topics.setdefault(s, []).append(t)

        def _derive(a: str, b: str, ty: str) -> None:
            rec = edges.get((a, b, ty))
            if rec is None:
                edges[(a, b, ty)] = {"source": a, "target": b, "type": ty,
                                     "years": {year} if year else set()}
            elif year:
                rec["years"].add(year)

        for sid, topics in s_topics.items():
            for tp in topics:
                for p in s_people.get(sid, ()):
                    _derive(p, tp, "spoke_on_theme")
                for o in s_orgs.get(sid, ()):
                    _derive(o, tp, "active_on_theme")

    node_ids = set(nodes)
    edge_list = [e for e in edges.values() if e["source"] in node_ids and e["target"] in node_ids]
    deg = {nid: 0 for nid in nodes}
    for e in edge_list:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    for nid, n in nodes.items():
        n["degree"] = deg[nid]
        n["years"] = sorted(n["years"])
    for e in edge_list:
        e["years"] = sorted(e["years"])
    return list(nodes.values()), edge_list


def _layout_graph(nodes: list[dict], edges: list[dict], width: float, height: float,
                  iterations: int = 160) -> dict[str, list[float]]:
    """Deterministic Fruchterman–Reingold layout (pure Python, build-time)."""
    ids = [n["id"] for n in nodes]
    idx = {nid: i for i, nid in enumerate(ids)}
    n = len(ids)
    if n == 0:
        return {}
    ga = math.pi * (3 - math.sqrt(5))          # golden angle → stable spiral seed
    radius = 0.45 * min(width, height)
    pos = []
    for i in range(n):
        r = radius * math.sqrt((i + 0.5) / n)
        a = i * ga
        pos.append([width / 2 + r * math.cos(a), height / 2 + r * math.sin(a)])
    k = math.sqrt((width * height) / n)         # ideal edge length
    elist = [(idx[e["source"]], idx[e["target"]]) for e in edges]
    t = width / 10.0
    cool = t / (iterations + 1)
    disp = [[0.0, 0.0] for _ in range(n)]
    for _ in range(iterations):
        for d in disp:
            d[0] = d[1] = 0.0
        for i in range(n):
            xi, yi = pos[i]
            for j in range(i + 1, n):
                dx = xi - pos[j][0]
                dy = yi - pos[j][1]
                dist2 = dx * dx + dy * dy
                if dist2 < 0.01:
                    dx, dy, dist2 = 0.1 + (i - j) * 0.01, 0.1, 0.02
                dist = math.sqrt(dist2)
                force = k * k / dist
                fx, fy = dx / dist * force, dy / dist * force
                disp[i][0] += fx
                disp[i][1] += fy
                disp[j][0] -= fx
                disp[j][1] -= fy
        for a, b in elist:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            dist = math.sqrt(dx * dx + dy * dy) or 0.01
            force = dist * dist / k
            fx, fy = dx / dist * force, dy / dist * force
            disp[a][0] -= fx
            disp[a][1] -= fy
            disp[b][0] += fx
            disp[b][1] += fy
        for i in range(n):
            dx, dy = disp[i]
            d = math.sqrt(dx * dx + dy * dy) or 0.01
            pos[i][0] = min(width - 24, max(24, pos[i][0] + dx / d * min(d, t)))
            pos[i][1] = min(height - 24, max(24, pos[i][1] + dy / d * min(d, t)))
        t = max(t - cool, 1.0)
    return {ids[i]: [round(pos[i][0], 1), round(pos[i][1], 1)] for i in range(n)}


def _write_graph_page(out: Path, base: str, manifests: list[dict[str, Any]]) -> None:
    """Write /graph.html — a static, clickable SVG map of the whole knowledge graph,
    with an equivalent accessible relationship index, plus /api/graph.json (Phase 4).

    The SVG is rendered at build time (works with no JavaScript and is fully
    linkable); JavaScript only adds type/year filtering and text focus on top.
    """
    nodes, edges = _build_combined_graph(out, manifests)
    if not nodes:
        return
    W, H = 1600.0, 1100.0
    pos = _layout_graph(nodes, edges, W, H)
    by_id = {n["id"]: n for n in nodes}

    # Machine-readable graph with positions.
    payload = {"nodes": [{**{k: n[k] for k in ("id", "type", "label", "url", "years", "degree")},
                          "x": pos[n["id"]][0], "y": pos[n["id"]][1]} for n in nodes],
               "edges": [{"source": e["source"], "target": e["target"],
                          "type": e["type"], "years": e["years"]} for e in edges]}
    (out / "api").mkdir(parents=True, exist_ok=True)
    (out / "api" / "graph.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    svg_edges = "".join(
        f'<line x1="{pos[e["source"]][0]}" y1="{pos[e["source"]][1]}" '
        f'x2="{pos[e["target"]][0]}" y2="{pos[e["target"]][1]}" class="kpg-edge" '
        f'data-st="{by_id[e["source"]]["type"]}" data-tt="{by_id[e["target"]]["type"]}" '
        f'data-yr="{" ".join(str(y) for y in e["years"])}" />'
        for e in edges)

    svg_nodes = []
    for n in sorted(nodes, key=lambda n: n["degree"]):  # hubs drawn last (on top)
        x, y = pos[n["id"]]
        color = GRAPH_COLOR.get(n["type"], "#475569")
        r = round(3 + min(9.0, n["degree"] * 0.7), 1)
        yrs = " ".join(str(y2) for y2 in n["years"])
        title = f'{esc(n["label"])} — {GRAPH_LABEL.get(n["type"], "Node")}'
        inner = (f'<circle r="{r}" cx="{x}" cy="{y}" fill="{color}" stroke="#fff" '
                 f'stroke-width="1.2"><title>{title}</title></circle>')
        if n["type"] == "topic" or (n["type"] in ("organization", "project", "country") and n["degree"] >= 3):
            inner += (f'<text x="{x + r + 2}" y="{y + 3.5}" class="kpg-label">'
                      f'{esc(n["label"][:30])}</text>')
        if n.get("url"):
            # tabindex=-1: the SVG is a decorative visual (see aria-hidden on the
            # canvas); the "Relationship index" list below is the accessible,
            # keyboard-navigable equivalent. Mouse users can still click nodes.
            svg_nodes.append(f'<a href="{esc(n["url"])}" tabindex="-1" class="kpg-node" data-type="{n["type"]}" '
                             f'data-yr="{yrs}" data-label="{esc(n["label"].lower())}">{inner}</a>')
        else:
            svg_nodes.append(f'<g class="kpg-node" data-type="{n["type"]}" data-yr="{yrs}" '
                             f'data-label="{esc(n["label"].lower())}">{inner}</g>')

    legend = "".join(f'<li><span class="kpg-dot" style="background:{c}"></span>{esc(l)}</li>'
                     for _, l, c in GRAPH_TYPE_META)
    # People, themes and organizations are shown by default; sessions, projects
    # and countries start hidden so the opening view is the people↔themes↔orgs graph.
    default_off = {"session", "country", "project"}
    type_boxes = "".join(
        f'<label class="kpg-check"><input type="checkbox" class="kpg-type" value="{t}"'
        f'{"" if t in default_off else " checked"} /> {esc(l)}</label>'
        for t, l, _ in GRAPH_TYPE_META)
    years = sorted({y for n in nodes for y in n["years"]}, reverse=True)
    year_opts = ('<option value="">All years</option>'
                 + "".join(f'<option value="{y}">{y}</option>' for y in years))

    groups = ""
    for t, label, _ in GRAPH_TYPE_META:
        members = sorted([n for n in nodes if n["type"] == t],
                         key=lambda n: (-n["degree"], n["label"].lower()))
        if not members:
            continue
        items = ""
        for n in members:
            yrs = " ".join(str(y) for y in n["years"])
            link = (f'<a href="{esc(n["url"])}">{esc(n["label"])}</a>' if n.get("url")
                    else esc(n["label"]))
            items += (f'<li class="kpg-item" data-type="{t}" data-yr="{yrs}" '
                      f'data-label="{esc(n["label"].lower())}">{link} '
                      f'<span class="kp-meta">· {n["degree"]} connections · {yrs}</span></li>')
        groups += (f'<section class="kpg-group" data-type="{t}"><h3>{esc(label)}s '
                   f'<span class="kp-meta">({len(members)})</span></h3>'
                   f'<ul class="kpg-list">{items}</ul></section>')

    aria = (f"Relationship map of {len(nodes)} people, organizations, themes, projects and "
            f"sessions across UN Open Source Week, with {len(edges)} connections. "
            f"An equivalent, fully linked relationship index follows below.")

    html = _GRAPH_TEMPLATE
    for token, value in (("__BASE__", esc(base)), ("__ARIA__", esc(aria)),
                         ("__LEGEND__", legend), ("__TYPES__", type_boxes),
                         ("__YEAROPTS__", year_opts), ("__EDGES__", svg_edges),
                         ("__NODES__", "".join(svg_nodes)), ("__GROUPS__", groups),
                         ("__NODECOUNT__", str(len(nodes))), ("__EDGECOUNT__", str(len(edges)))):
        html = html.replace(token, value)
    (out / "graph.html").write_text(html, encoding="utf-8")


_GRAPH_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Relationship map · UN Open Source Week Knowledge Platform</title>
    <meta name="description" content="A relationship map of the people, organizations, themes, projects and sessions of UN Open Source Week and how they connect across years." />
    <link rel="canonical" href="__BASE__/graph.html" />
    <link rel="stylesheet" href="/shared.css" />
    <link rel="stylesheet" href="/knowledge.css" />
  </head>
  <body>
    <a class="skip-link" href="#main-content">Skip to main content</a>
    <header class="kp-header"><div class="kp-header-inner">
      <p class="kp-eyebrow">Knowledge Platform</p>
      <h1>Relationship map</h1>
      <p>How the people, organizations and themes of UN Open Source Week connect — across years.
         People and organizations link through the themes they work on; add sessions or countries
         with the filters below. Themes and recurring organizations bridge the years.</p>
    </div></header>
    <nav class="kp-breadcrumb" aria-label="Breadcrumb"><ol>
      <li><a href="/">Home</a></li><li><a href="/explore.html">Knowledge</a></li>
      <li aria-current="page">Relationship map</li>
    </ol></nav>
    <main id="main-content" class="kp-main">
      <section class="kp-section">
        <form id="kpg-controls" class="kpg-controls" aria-label="Filter the map">
          <fieldset class="kpg-fieldset"><legend>Show</legend>__TYPES__</fieldset>
          <div class="kpg-row">
            <label for="kpg-year"><strong>Year</strong></label>
            <select id="kpg-year" style="padding:0.4rem 0.6rem;border:1px solid var(--border);border-radius:0.4rem;">__YEAROPTS__</select>
            <label for="kpg-focus"><strong>Focus</strong></label>
            <input id="kpg-focus" type="search" placeholder="highlight by name…" autocomplete="off"
                   style="padding:0.4rem 0.6rem;border:1px solid var(--border);border-radius:0.4rem;" />
          </div>
        </form>
        <ul class="kpg-legend">__LEGEND__</ul>
        <p class="visually-hidden">__ARIA__</p>
        <div class="kpg-canvas" aria-hidden="true">
          <svg id="kpg-svg" viewBox="0 0 1600 1100" preserveAspectRatio="xMidYMid meet">
            <g id="kpg-edges">__EDGES__</g>
            <g id="kpg-nodes">__NODES__</g>
          </svg>
        </div>
        <p class="kp-meta">__NODECOUNT__ nodes · __EDGECOUNT__ connections. The map is generated from the
           published <a href="/api/graph.json"><code>graph.json</code></a>; click any node to open its page,
           or use the fully linked index below.</p>
      </section>
      <section class="kp-section">
        <h2>Relationship index</h2>
        <p class="kp-meta">Every node in the map, grouped by kind and ordered by how connected it is —
           a fully linked, accessible equivalent of the diagram above.</p>
        <div id="kpg-index">__GROUPS__</div>
      </section>
    </main>
    <footer class="kp-footer"><p>Generated from the knowledge-platform datasets · provenance on every record.</p></footer>
    <script src="/nav.js" defer></script>
    <script>
      (function () {
        var svg = document.getElementById("kpg-svg");
        var year = document.getElementById("kpg-year");
        var focus = document.getElementById("kpg-focus");
        var typeBoxes = Array.prototype.slice.call(document.querySelectorAll(".kpg-type"));
        function enabledTypes() {
          var s = {};
          typeBoxes.forEach(function (b) { if (b.checked) s[b.value] = true; });
          return s;
        }
        function yrOk(data, y) { return !y || (" " + data + " ").indexOf(" " + y + " ") !== -1; }
        function apply() {
          var types = enabledTypes(), y = year.value, q = focus.value.trim().toLowerCase();
          document.querySelectorAll(".kpg-node").forEach(function (el) {
            var ok = types[el.getAttribute("data-type")] && yrOk(el.getAttribute("data-yr"), y);
            el.style.display = ok ? "" : "none";
            var hit = ok && q && el.getAttribute("data-label").indexOf(q) !== -1;
            el.classList.toggle("kpg-hit", !!hit);
            if (q) el.style.opacity = (ok && (!q || el.getAttribute("data-label").indexOf(q) !== -1)) ? "1" : "0.15";
            else el.style.opacity = "";
          });
          document.querySelectorAll(".kpg-edge").forEach(function (el) {
            var ok = types[el.getAttribute("data-st")] && types[el.getAttribute("data-tt")]
                     && yrOk(el.getAttribute("data-yr"), y);
            el.style.display = ok ? "" : "none";
          });
          document.querySelectorAll(".kpg-item").forEach(function (el) {
            var ok = types[el.getAttribute("data-type")] && yrOk(el.getAttribute("data-yr"), y)
                     && (!q || el.getAttribute("data-label").indexOf(q) !== -1);
            el.style.display = ok ? "" : "none";
          });
          document.querySelectorAll(".kpg-group").forEach(function (g) {
            var any = g.querySelectorAll(".kpg-item:not([style*='none'])").length;
            g.style.display = any ? "" : "none";
          });
        }
        typeBoxes.forEach(function (b) { b.addEventListener("change", apply); });
        year.addEventListener("change", apply);
        focus.addEventListener("input", apply);
        apply();  // honour the default filters (sessions/countries start hidden)
      })();
    </script>
  </body>
</html>
"""


def _write_search_page(out: Path, base: str) -> None:
    """Write /knowledge-search.html — accessible client-side search (Phase 11).

    Distinct from the legacy /search.html (side-event calendar). Loads
    /api/search-index.json and filters in the browser by free text plus two
    facets — category (events vs history) and year — with ?q=/?category=/?year=
    deep links. No server, no runtime deps.
    """
    select_style = ("padding:0.5rem 0.7rem;border:1px solid var(--border);"
                    "border-radius:0.4rem;font-size:1rem;")
    html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Search · UN Open Source Week Knowledge Platform</title>
    <meta name="description" content="Search the UN Open Source Week knowledge platform — events (sessions, speakers, organizations, projects, themes) and history (recordings, draft transcripts, reports) across every year." />
    <link rel="canonical" href="__BASE__/knowledge-search.html" />
    <link rel="stylesheet" href="/shared.css" />
    <link rel="stylesheet" href="/knowledge.css" />
  </head>
  <body>
    <a class="skip-link" href="#main-content">Skip to main content</a>
    <header class="kp-header"><div class="kp-header-inner">
      <p class="kp-eyebrow">Knowledge Platform</p>
      <h1>Search the knowledge platform</h1>
      <p>One search across the whole platform — the <strong>events</strong> (sessions, speakers,
         organizations, projects, themes) and the <strong>history</strong> (recordings, draft
         transcripts, and reports). Filter by category and year.</p>
    </div></header>
    <nav class="kp-breadcrumb" aria-label="Breadcrumb"><ol>
      <li><a href="/">Home</a></li><li><a href="/explore.html">Knowledge</a></li>
      <li aria-current="page">Search</li>
    </ol></nav>
    <main id="main-content" class="kp-main">
      <section class="kp-section">
        <form id="kp-search-form" role="search" action="/knowledge-search.html" method="get">
          <label for="kp-q"><strong>Search</strong></label>
          <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin:0.4rem 0;">
            <input id="kp-q" name="q" type="search" autocomplete="off"
                   placeholder="e.g. accessibility, MOSIP, DPI Day recording"
                   style="flex:1 1 16rem;padding:0.5rem 0.7rem;border:1px solid var(--border);border-radius:0.4rem;font-size:1rem;" />
            <label for="kp-category" class="visually-hidden">Filter by category</label>
            <select id="kp-category" name="category" style="__SEL__">
              <option value="">All categories</option>
              <option value="events">Events</option>
              <option value="history">History</option>
            </select>
            <label for="kp-year" class="visually-hidden">Filter by year</label>
            <select id="kp-year" name="year" style="__SEL__">
              <option value="">All years</option>
            </select>
          </div>
        </form>
        <p id="kp-status" class="kp-meta" role="status" aria-live="polite">Loading the search index…</p>
        <ul id="kp-results" class="kp-grid"></ul>
      </section>
    </main>
    <footer class="kp-footer"><p>Search runs in your browser over the published datasets · provenance on every record.</p></footer>
    <script src="/nav.js" defer></script>
    <script>
      (function () {
        var LABELS = {session:"Session", speaker:"Speaker", organization:"Organization",
                      project:"Project", topic:"Theme", recording:"Recording",
                      document:"Document", page:"Page"};
        var input = document.getElementById("kp-q");
        var catSel = document.getElementById("kp-category");
        var yearSel = document.getElementById("kp-year");
        var status = document.getElementById("kp-status");
        var list = document.getElementById("kp-results");
        var form = document.getElementById("kp-search-form");
        var records = [];
        form.addEventListener("submit", function (e) { e.preventDefault(); render(); });

        function esc(s) {
          return String(s).replace(/[&<>"']/g, function (c) {
            return {"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c];
          });
        }
        function params() {
          var p = new URLSearchParams(window.location.search);
          return {q: p.get("q") || "", category: p.get("category") || "", year: p.get("year") || ""};
        }
        function render() {
          var q = input.value.trim().toLowerCase();
          var cat = catSel.value, year = yearSel.value;
          var terms = q.split(/\\s+/).filter(Boolean);
          var url = new URL(window.location.href);
          ["q", "category", "year"].forEach(function (k) { url.searchParams.delete(k); });
          if (input.value.trim()) url.searchParams.set("q", input.value.trim());
          if (cat) url.searchParams.set("category", cat);
          if (year) url.searchParams.set("year", year);
          window.history.replaceState(null, "", url);
          var matches = records.filter(function (r) {
            if (cat && r.category !== cat) return false;
            if (year && String(r.year) !== year) return false;
            return terms.every(function (t) { return r.text.indexOf(t) !== -1; });
          });
          list.innerHTML = "";
          if (!q && !cat && !year) {
            status.textContent = records.length + " records indexed (events + history). Search or filter to begin.";
            return;
          }
          status.textContent = matches.length + (matches.length === 1 ? " result" : " results");
          matches.slice(0, 300).forEach(function (r) {
            var li = document.createElement("li");
            li.className = "kp-card";
            var extra = "";
            if (r.transcript_url) {
              extra = ' · <a href="' + esc(r.transcript_url) + '" rel="noopener noreferrer">draft transcript</a>';
            }
            li.innerHTML =
              '<h3><a href="' + esc(r.url) + '" rel="noopener noreferrer">' + esc(r.title) + '</a></h3>' +
              '<p class="kp-meta"><span class="kp-badge">' + esc(LABELS[r.type] || r.type) + '</span> ' +
              esc(r.year || "") + (r.meta ? ' · ' + esc(r.meta) : '') + extra + '</p>';
            list.appendChild(li);
          });
        }
        function fillYears() {
          var years = {};
          records.forEach(function (r) { if (r.year) years[r.year] = true; });
          Object.keys(years).map(Number).sort(function (a, b) { return b - a; }).forEach(function (y) {
            var opt = document.createElement("option");
            opt.value = String(y); opt.textContent = String(y);
            yearSel.appendChild(opt);
          });
        }
        fetch("/api/search-index.json").then(function (res) {
          if (!res.ok) throw new Error("index unavailable");
          return res.json();
        }).then(function (data) {
          records = (data && data.records) || [];
          fillYears();
          var init = params();
          if (init.q) input.value = init.q;
          if (init.category) catSel.value = init.category;
          if (init.year) yearSel.value = init.year;
          input.addEventListener("input", render);
          catSel.addEventListener("change", render);
          yearSel.addEventListener("change", render);
          render();
          input.focus();
        }).catch(function () {
          status.textContent = "Sorry — the search index could not be loaded.";
        });
      })();
    </script>
  </body>
</html>
"""
    html = html.replace("__SEL__", select_style).replace("__BASE__", esc(base))
    (out / "knowledge-search.html").write_text(html, encoding="utf-8")


def _write_top_hub(out: Path, manifests: list[dict[str, Any]]) -> None:
    cards = ""
    for m in sorted(manifests, key=lambda m: (m.get("conference", ""), -int(m.get("year", 0)))):
        d = m.get("datasets", {})
        meta = " · ".join(f"{d.get(k, 0)} {k}" for k in ("sessions", "speakers", "organizations") if d.get(k))
        cards += (f'<li class="kp-card"><h3><a href="{esc(m["explore_url"])}">'
                  f'{esc(m["name"])} {esc(m["year"])}</a></h3>'
                  f'<p class="kp-meta">{esc(meta)}</p></li>')
    if not cards:
        cards = '<li class="kp-card"><p>No conference years generated yet.</p></li>'
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Knowledge Platform · Explore by year</title>
    <meta name="description" content="Open, AI-ready knowledge platform indexing UN Open Source Week by year, with provenance and links back to authoritative sources." />
    <link rel="stylesheet" href="/shared.css" />
    <link rel="stylesheet" href="/knowledge.css" />
  </head>
  <body>
    <a class="skip-link" href="#main-content">Skip to main content</a>
    <header class="kp-header">
      <div class="kp-header-inner">
        <p class="kp-eyebrow">Knowledge Platform</p>
        <h1>Explore UN Open Source Week</h1>
        <p>An open, AI-ready index of public information about UN Open Source Week,
           linking back to authoritative sources. Choose a year.</p>
      </div>
    </header>
    <main id="main-content" class="kp-main">
      <section class="kp-section"><h2>Conference years</h2>
        <ul class="kp-grid">{cards}</ul>
      </section>
      <section class="kp-section"><h2>Across years</h2>
        <p><a href="/knowledge-search.html">Search the knowledge platform</a> — sessions,
           speakers, organizations, projects, and themes across every year.</p>
        <p><a href="/graph.html">Relationship map</a> — how people, organizations, and themes connect.</p>
        <p><a href="/timeline.html">Timeline — themes across years</a></p>
      </section>
      <section class="kp-section"><h2>For AI &amp; developers</h2>
        <p>Machine-readable discovery: <a href="/api/index.json"><code>/api/index.json</code></a>
           and <a href="/llms.txt"><code>/llms.txt</code></a> — every dataset and knowledge graph,
           linked back to authoritative sources.</p>
      </section>
    </main>
    <footer class="kp-footer"><p>Generated knowledge platform · provenance on every record.</p></footer>
    <script src="/nav.js" defer></script>
  </body>
</html>
"""
    (out / "explore.html").write_text(html, encoding="utf-8")


def _write_sitemap(out: Path, base: str) -> None:
    urls: list[str] = []
    for path in sorted(out.rglob("*.html")):
        rel = path.relative_to(out).as_posix()
        urls.append(f"{base}/" if rel == "index.html" else f"{base}/{rel}")
    for extra in ["calendar.ics", "api/2026/events.json"]:
        if (out / extra).exists():
            urls.append(f"{base}/{extra}")
    body = "\n".join(f"  <url><loc>{esc(u)}</loc></url>" for u in dict.fromkeys(urls))
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               f"{body}\n</urlset>\n")
    (out / "sitemap.xml").write_text(sitemap, encoding="utf-8")


def write_timeline(out_dir: Path, conference: dict[str, Any], base_url: str) -> None:
    """Write a cross-year timeline at /timeline.html (Phase 7).

    Themes are the reliable cross-year axis — they share one vocabulary, so a
    topic's slug matches across years (organization slugs do not). Reads the
    generated per-year api/sessions.json for whichever years are present in the
    output, so it is consistent with what was built. Idempotent.
    """
    out = Path(out_dir)
    cid = conference["id"]
    years = sorted(y for y in conference.get("data_years", [])
                   if (out / cid / str(y) / "explore.html").exists())
    if not years:
        return

    sessions_by_year: dict[int, list] = {}
    for y in years:
        try:
            sessions_by_year[y] = json.loads((out / cid / str(y) / "api" / "sessions.json").read_text())
        except (json.JSONDecodeError, OSError):
            sessions_by_year[y] = []

    rows = []
    for topic in conference.get("topic_vocabulary", []):
        slug, name = topic["slug"], topic["name"]
        counts = {y: sum(1 for s in sessions_by_year[y] if slug in s.get("topics", [])) for y in years}
        if not any(counts.values()):
            continue
        first = min(y for y in years if counts[y] > 0)
        latest = max(y for y in years if counts[y] > 0)
        rows.append((name, slug, counts, first, latest))
    rows.sort(key=lambda r: (r[3], -sum(r[2].values())))

    head_cells = "".join(f'<th scope="col">{y}</th>' for y in years)
    body_rows = ""
    for name, slug, counts, first, latest in rows:
        cells = "".join(f"<td>{counts[y] or '·'}</td>" for y in years)
        body_rows += (f'<tr id="theme-{esc(slug)}"><th scope="row">'
                      f'<a href="/{cid}/{latest}/topics/{esc(slug)}.html">{esc(name)}</a></th>'
                      f"{cells}<td>{first}</td></tr>")
    table = (f'<table class="kp-table"><caption class="visually-hidden">'
             f'Sessions per theme by year</caption><thead><tr>'
             f'<th scope="col">Theme</th>{head_cells}<th scope="col">First seen</th>'
             f"</tr></thead><tbody>{body_rows}</tbody></table>")

    year_cards = ""
    for y in sorted(years, reverse=True):
        n = len(sessions_by_year[y])
        year_cards += (f'<li class="kp-card"><h3><a href="/{cid}/{y}/explore.html">'
                       f'{esc(conference["name"])} {y}</a></h3>'
                       f'<p class="kp-meta">{n} sessions</p></li>')

    body = (f'<section class="kp-section">'
            f'<p>How themes recur across UN Open Source Week, by year. Counts are sessions '
            f'tagged with each theme; the table is derived from the published datasets.</p>'
            f'<ul class="kp-grid">{year_cards}</ul></section>'
            f'<section class="kp-section"><h2>Themes across years</h2>{table}</section>')

    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Timeline · {esc(conference['name'])} Knowledge Platform</title>
    <meta name="description" content="Cross-year timeline of themes across UN Open Source Week, derived from the knowledge-platform datasets." />
    <link rel="canonical" href="{esc(base_url.rstrip('/'))}/timeline.html" />
    <link rel="stylesheet" href="/shared.css" />
    <link rel="stylesheet" href="/knowledge.css" />
  </head>
  <body>
    <a class="skip-link" href="#main-content">Skip to main content</a>
    <header class="kp-header"><div class="kp-header-inner">
      <p class="kp-eyebrow">Knowledge Platform</p>
      <h1>Timeline — themes across years</h1>
      <p>Which topics recur across UN Open Source Week, and when each first appears.</p>
    </div></header>
    <nav class="kp-breadcrumb" aria-label="Breadcrumb"><ol>
      <li><a href="/">Home</a></li><li><a href="/explore.html">Knowledge</a></li>
      <li aria-current="page">Timeline</li>
    </ol></nav>
    <main id="main-content" class="kp-main">
{body}
    </main>
    <footer class="kp-footer"><p>Generated from the knowledge-platform datasets · provenance on every record.</p></footer>
    <script src="/nav.js" defer></script>
  </body>
</html>
"""
    (out / "timeline.html").write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the conference knowledge-platform site.")
    parser.add_argument("--conference", default="unosw", help="Conference id (matches conferences/<id>.json).")
    parser.add_argument("--year", type=int, default=2025, help="Conference year (matches data/<id>/<year>/).")
    parser.add_argument("--out", default="_site", help="Output directory (default: _site).")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Repository root.")
    args = parser.parse_args()

    root = Path(args.repo_root)
    conference = ku.load_conference(root / "conferences", args.conference)
    datasets = ku.load_datasets(root / "data" / args.conference / str(args.year))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    generator = SiteGenerator(conference, args.year, datasets, out_dir)
    counts = generator.generate()
    # Rebuild the cross-year hub + merged sitemap (covers every year present).
    manifests = rebuild_top_level(out_dir, conference["site_base_url"], root)
    write_timeline(out_dir, conference, conference["site_base_url"])
    total_pages = (counts["sessions"] + counts["speakers"] + counts["organizations"]
                   + counts["projects"] + counts["topics"] + 6)
    print(f"Generated {total_pages} pages under {out_dir}/{generator.base_path} "
          f"for {conference['name']} {args.year}:")
    for key, value in counts.items():
        print(f"  {value:>3} {key}")
    print(f"  datasets + knowledge-graph under {out_dir}/{generator.base_path}/api")
    print(f"  top-level hub + sitemap rebuilt ({len(manifests)} conference-year(s) present)")


if __name__ == "__main__":
    main()

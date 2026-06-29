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
            media.append(f'<a href="{esc(session["transcript_url"])}" rel="noopener noreferrer">📄 Transcript</a>')
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


def rebuild_top_level(out_dir: Path, base_url: str) -> list[dict[str, Any]]:
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

    _write_top_hub(out, manifests)
    _write_sitemap(out, base)
    return manifests


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
    manifests = rebuild_top_level(out_dir, conference["site_base_url"])
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

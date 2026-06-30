#!/usr/bin/env python3
"""Import a year's scraped agenda into the knowledge-platform datasets.

Reads the project's own event ledger (``data/<year>/events.json``) and writes
normalized, provenanced knowledge datasets to ``data/<conference>/<year>/``:
sessions (tagged ``official`` vs ``side-event``), organizations (one per
distinct organizer string), and the shared topic vocabulary. Speakers,
projects, quotes and references are written as empty arrays — the agenda has no
speaker data; those land via later enrichment.

Provenance: the agenda gives factual public event listings (who/what/when/
where). Facts are not copyrightable, so records are recorded with
``license: public-domain`` and ``method: automated-ingestion``, always linking
to the authoritative event/agenda URL. See GOVERNANCE.md.

Re-running is idempotent (output is overwritten). Programmatic, deterministic,
no network access.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import knowledge_utils as ku

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_TITLE_OFFICIAL = "UN Open Source Week {year} — official agenda"
SOURCE_TITLE_SIDE = "UN Open Source Week {year} — community side events"

# Substring -> topic slug. Checked against title + summary + organizer (lower).
# Every value must exist in the conference topic vocabulary.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "ai": ["ai ", " ai", "artificial intelligence", "machine learning", "llm", "genai"],
    "digital-public-infrastructure": ["dpi", "digital public infrastructure", "digital id", "payments"],
    "digital-public-goods": ["dpg", "digital public good"],
    "open-standards": ["open standard", "open data"],
    "procurement": ["procurement", "purchasing"],
    "climate": ["climate", "weather", "disaster", "environment"],
    "sustainability": ["sustainab", "maintain", "maintenance"],
    "government": ["government", "public sector", "ministry", "policy", "national", "civic"],
    "health": ["health", "medical", "unicef"],
    "education": ["education", "academ", "skills", "learning", "student", "university", "edit-a-thon"],
    "security": ["security", "supply chain", "safeguard", "privacy", "risk", "vulnerab"],
    "licensing": ["licens"],
    "community": ["community", "contributor", "maintainer", "chaoss", "curioss"],
    "funding": ["funding", "sponsor", "grant"],
    "ospo": ["ospo", "open source program"],
    "interoperability": ["interoperab"],
    "digital-sovereignty": ["sovereign"],
    "accessibility": ["accessib", "a11y", "wcag"],
    "open-source": ["open source", "open-source", "foss", "oss "],
}

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# Recorded plenary sessions, mapped (date, part) -> UN Web TV asset id from the
# authoritative conferences/<year>/README.md. Only the live-streamed main hall is
# attached; parallel breakouts in other rooms were not on these streams, so we do
# not claim they were. The transcript filename and UN Web TV URL both derive from
# the asset id (e.g. "k14ej1ucqu" -> "k14/k14ej1ucqu", "k14-k14ej1ucqu-English").
PLENARY_HALLS = {"ECOSOC Chamber"}
PLENARY_AFTERNOON_FROM = "13:00"  # sessions at/after this local time are "Part 2"
RECORDINGS: dict[int, dict[tuple[str, str], str]] = {
    2026: {
        ("2026-06-23", "am"): "k14ej1ucqu",  # Open Source for AI & Emerging Tech, Part 1
        ("2026-06-23", "pm"): "k1b443e64t",  # Open Source for AI & Emerging Tech, Part 2
        ("2026-06-24", "am"): "k1cqj3jcdx",  # DPI Day, Part 1
        ("2026-06-24", "pm"): "k136ks9z9x",  # DPI Day, Part 2
        ("2026-06-25", "am"): "k12620x8tm",  # OSPOs for Good, Part 1
        ("2026-06-25", "pm"): "k1i4m11zkv",  # OSPOs for Good, Part 2
    },
}
TRANSCRIPT_REPO_BASE = "https://github.com/mgifford/unosw.plus/blob/main"


def recording_for(year: int, date_str: str, room: str, start_time: str) -> tuple[str, str] | None:
    """Return (video_url, transcript_url) for a recorded main-hall plenary session, else None."""
    if room not in PLENARY_HALLS or not start_time:
        return None
    part = "am" if start_time < PLENARY_AFTERNOON_FROM else "pm"
    asset = RECORDINGS.get(year, {}).get((date_str, part))
    if not asset:
        return None
    prefix = asset[:3]
    video_url = f"https://webtv.un.org/en/asset/{prefix}/{asset}"
    transcript_url = f"{TRANSCRIPT_REPO_BASE}/conferences/{year}/{prefix}-{asset}-English.transcript.md"
    return video_url, transcript_url


def classify_topics(text: str) -> list[str]:
    text = text.lower()
    matched = [slug for slug, kws in TOPIC_KEYWORDS.items() if any(k in text for k in kws)]
    return matched or ["open-source"]


def infer_type(title: str, kind: str) -> str | None:
    t = title.lower()
    if "hack" in t:
        return "hackathon"
    if "edit-a-thon" in t or "editathon" in t or "edit a thon" in t:
        return "edit-a-thon"
    if "maintain" in t:
        return "maintain-a-thon"
    if "keynote" in t:
        return "keynote"
    if "panel" in t:
        return "panel"
    if "workshop" in t:
        return "workshop"
    if "closing" in t or "opening" in t or "ceremony" in t:
        return "ceremony"
    return "side-event" if kind == "side-event" else None


def classify_org_type(name: str) -> str:
    n = name.lower()
    if "united nations" in n or "odet" in n or "oict" in n or n.startswith("un ") or "un open source" in n:
        return "un-agency"
    if "digital public goods alliance" in n or n.strip() == "dpga":
        return "multilateral"
    if "github" in n:
        return "company"
    if "chaoss" in n:
        return "community"
    return "other"


def human_day(date_str: str, year: int) -> str:
    try:
        d = date.fromisoformat(date_str)
        return f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month]} {year}"
    except (ValueError, IndexError):
        return date_str


def http_url(value: str) -> str:
    """Return value if it is an http(s) URL, else empty (e.g. drops "N/A")."""
    return value if str(value).startswith(("http://", "https://")) else ""


def provenance(source_url: str, source_title: str, locator: str, fallback_url: str) -> dict[str, Any]:
    return {
        "source_url": http_url(source_url) or fallback_url,
        "source_title": source_title,
        "license": "public-domain",
        "method": "automated-ingestion",
        "retrieved": "2026-06-29",
        "locator": locator,
    }


def build(events: list[dict[str, Any]], conference: dict[str, Any], year: int) -> dict[str, list]:
    fallback_url = conference["official_urls"][0] if conference.get("official_urls") else conference["site_base_url"]

    organizations: dict[str, dict[str, Any]] = {}
    sessions: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for event in sorted(events, key=lambda e: (e.get("event_date", ""), e.get("start_time", ""), e.get("id", ""))):
        submission_source = str(event.get("submission_source", ""))
        kind = "official" if submission_source.startswith("scrape:") else "side-event"
        source_title = (SOURCE_TITLE_OFFICIAL if kind == "official" else SOURCE_TITLE_SIDE).format(year=year)

        event_id = str(event.get("id", ""))
        sid = "sess-" + (event_id[len("evt-"):] if event_id.startswith("evt-") else ku.slugify(event_id))
        # The upstream ledger can contain duplicate event ids; keep every
        # session by disambiguating collisions so no page overwrites another.
        base_sid = sid
        suffix = 2
        while sid in used_ids:
            sid = f"{base_sid}-{suffix}"
            suffix += 1
        used_ids.add(sid)

        organizer = str(event.get("organizer", "")).strip() or "Unknown organizer"
        org_slug = ku.slugify(organizer)
        if org_slug and org_slug not in organizations:
            organizations[org_slug] = {
                "slug": org_slug,
                "name": organizer,
                "type": classify_org_type(organizer),
                "provenance": provenance(fallback_url, f"UN Open Source Week {year} agenda",
                                         f"organizer: {organizer}", fallback_url),
            }

        location = event.get("location") if isinstance(event.get("location"), dict) else {}
        room = str(location.get("name", "")).strip()
        summary = str(event.get("summary", "")).strip()
        title = str(event.get("title", "")).strip()
        topics = classify_topics(" ".join([title, summary, organizer]))
        stype = infer_type(title, kind)

        session = {
            "id": sid,
            "title": title or sid,
            "year": year,
            "date": event.get("event_date", ""),
            "day": human_day(str(event.get("event_date", "")), year),
            "track": "Official agenda" if kind == "official" else "Community side events",
            "kind": kind,
            "organizations": [org_slug] if org_slug else [],
            "topics": topics,
            "speakers": [],
            "projects": [],
            "references": [],
            "provenance": provenance(str(event.get("original_source_url", "")), source_title,
                                     event_id, fallback_url),
        }
        if stype:
            session["type"] = stype
        if event.get("start_time"):
            session["start_time"] = event["start_time"]
        if event.get("end_time"):
            session["end_time"] = event["end_time"]
        if event.get("timezone"):
            session["timezone"] = event["timezone"]
        if room and room != "TBD":
            session["room"] = room
        if summary:
            session["summary"] = summary
        if http_url(event.get("original_source_url", "")):
            session["official_url"] = event["original_source_url"]
        rec = recording_for(year, str(event.get("event_date", "")), room, str(event.get("start_time", "")))
        if rec:
            session["video_url"], session["transcript_url"] = rec
        sessions.append(session)

    return {
        "sessions": sessions,
        "organizations": sorted(organizations.values(), key=lambda o: o["name"]),
        "speakers": [],
        "projects": [],
        "quotes": [],
        "references": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a scraped agenda into knowledge datasets.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--conference", default="unosw")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args()

    root = Path(args.repo_root)
    conference = ku.load_conference(root / "conferences", args.conference)
    events = ku.load_json(root / "data" / str(args.year) / "events.json")
    out_dir = root / "data" / args.conference / str(args.year)
    out_dir.mkdir(parents=True, exist_ok=True)

    built = build(events, conference, args.year)

    # Shared topic vocabulary: reuse the curated topics from the first data year.
    topics_src = root / "data" / args.conference / str(conference["data_years"][0]) / "topics.json"
    built["topics"] = ku.load_json(topics_src)

    for name in ["sessions", "speakers", "organizations", "projects", "topics", "quotes", "references"]:
        (out_dir / f"{name}.json").write_text(
            json.dumps(built[name], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = {k: len(v) for k, v in built.items()}
    official = sum(1 for s in built["sessions"] if s.get("kind") == "official")
    print(f"Imported {args.conference} {args.year} from data/{args.year}/events.json:")
    print(f"  {counts['sessions']} sessions ({official} official, {counts['sessions'] - official} side-event)")
    print(f"  {counts['organizations']} organizations · {counts['topics']} topics")
    print(f"  written to {out_dir}")


if __name__ == "__main__":
    main()

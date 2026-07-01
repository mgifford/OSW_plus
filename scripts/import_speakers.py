#!/usr/bin/env python3
"""Import a conference's speaker roster from its captured official Speakers page.

Reads the archived ``conferences/<year>/…Speakers….mhtml`` (or .html) snapshot of
the official Speakers page and writes ``data/<conference>/<year>/speakers.json``:
each speaker's name, role/title, and the confirmed official profile URL on the
conference site. Nothing is invented — only what the official page states.

Provenance: the roster is factual public information (who is speaking), recorded
with ``license: public-domain`` and ``method: automated-ingestion``, always
linking back to the authoritative speakers page. See GOVERNANCE.md.

Note: the captured page contains only the speaker cards present in the saved
HTML (the live site may paginate more via JavaScript). No social/LinkedIn links
are present in the capture, so none are added.

Re-running is idempotent (output is overwritten). Deterministic, no network.
"""

from __future__ import annotations

import argparse
import email
import html as htmlmod
import json
import re
from pathlib import Path
from typing import Any

import knowledge_utils as ku

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEAKER_URL_RE = re.compile(
    r'href="(https://www\.unopensource\.org/speaker/[^"]+)"[^>]*'
    r'class="item-speakers-content[^>]*>(.*?)</a>', re.S)
NAME_RE = re.compile(r'class="title speaker-page-name">(.*?)</h2>', re.S)
ROLE_RE = re.compile(r'class="work-text speaker-page">(.*?)</div>', re.S)


def _clean(fragment: str) -> str:
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _load_html(path: Path) -> str:
    """Return the text/html body of an .mhtml (or plain .html) snapshot."""
    data = path.read_bytes()
    if path.suffix.lower() == ".mhtml":
        msg = email.message_from_bytes(data)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return data.decode("utf-8", "replace")


def _find_snapshot(conf_dir: Path) -> Path | None:
    for pattern in ("*Speakers*.mhtml", "*Speakers*.html", "*speakers*.mhtml", "*speakers*.html"):
        matches = sorted(conf_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def build_speakers(html: str, year: int, source_url: str) -> list[dict[str, Any]]:
    speakers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in SPEAKER_URL_RE.finditer(html):
        official_url, inner = match.group(1), match.group(2)
        name_m = NAME_RE.search(inner)
        if not name_m:
            continue
        name = _clean(name_m.group(1))
        if not name:
            continue
        slug = ku.slugify(name)
        if slug in seen:
            continue
        seen.add(slug)
        role_m = ROLE_RE.search(inner)
        record: dict[str, Any] = {"slug": slug, "name": name}
        role = _clean(role_m.group(1)) if role_m else ""
        if role:
            record["role"] = role
        record["official_url"] = official_url
        record["provenance"] = {
            "source_url": source_url,
            "source_title": f"UN Open Source Week {year} — Speakers",
            "license": "public-domain",
            "method": "automated-ingestion",
            "retrieved": "2026-07-01",
            "locator": "Official speakers page",
        }
        speakers.append(record)
    speakers.sort(key=lambda s: s["name"].lower())
    return speakers


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a speaker roster from the captured Speakers page.")
    parser.add_argument("--conference", default="unosw")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args()

    root = Path(args.repo_root)
    conf_dir = root / "conferences" / str(args.year)
    snapshot = _find_snapshot(conf_dir)
    if not snapshot:
        raise SystemExit(f"No Speakers snapshot found under {conf_dir}")
    html = _load_html(snapshot)
    speakers = build_speakers(html, args.year, "https://www.unopensource.org/speakers")
    if not speakers:
        raise SystemExit(f"No speakers parsed from {snapshot.name}")

    out = root / "data" / args.conference / str(args.year) / "speakers.json"
    out.write_text(json.dumps(speakers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(speakers)} speakers to {out} (source: {snapshot.name})")


if __name__ == "__main__":
    main()

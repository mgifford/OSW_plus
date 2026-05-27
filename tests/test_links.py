"""
Check that all HTTP/HTTPS links in Markdown files return non-404 responses.

Requests are made with a HEAD (falling back to GET) and a short timeout so
the suite stays fast.  Network errors (connection refused, DNS failure, etc.)
are treated as a skip rather than a failure to avoid flaky CI when an
external service is temporarily unreachable.
"""

import re
import unittest
import urllib.request
import urllib.error
from pathlib import Path

# Repository root is one level above this file's directory.
REPO_ROOT = Path(__file__).parent.parent

# Markdown files to scan for links.
MD_GLOBS = ["**/*.md"]

# Patterns to skip: Google Maps (redirects make HEAD unreliable), GitHub
# internal anchors (e.g. #section), and bare localhost addresses.
SKIP_PATTERNS = [
    re.compile(r"^https://maps\.google\.com"),
    re.compile(r"^https://github\.com/.+/issues/new"),  # parameterised templates
]

LINK_RE = re.compile(r'\bhttps?://[^\s\)\"\'<>]+')

REQUEST_TIMEOUT = 10  # seconds


def _collect_links() -> list[tuple[str, str]]:
    """Return [(url, source_file), ...] for every unique HTTP link found."""
    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    for glob in MD_GLOBS:
        for md_file in sorted(REPO_ROOT.glob(glob)):
            text = md_file.read_text(encoding="utf-8")
            for url in LINK_RE.findall(text):
                # Strip trailing punctuation that isn't part of the URL.
                # Only strip ')' when it has no matching '(' inside the URL
                # (e.g. markdown "](url)" syntax), so that URLs containing
                # balanced parentheses like /page_(disambiguation) are kept.
                url = re.sub(r"[.,;:!?]+$", "", url)
                if url.endswith(")") and "(" not in url:
                    url = url[:-1]
                if url in seen:
                    continue
                if any(p.search(url) for p in SKIP_PATTERNS):
                    continue
                seen.add(url)
                results.append((url, str(md_file.relative_to(REPO_ROOT))))
    return results


def _check_url(url: str) -> tuple[int | None, str]:
    """
    Return (status_code, error_message).
    Uses HEAD first; falls back to GET if the server rejects HEAD.
    """
    headers = {"User-Agent": "OSW_plus-link-checker/1.0 (CI test)"}
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.status, ""
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in (405, 403):
                # Server rejected HEAD — try GET.
                continue
            return exc.code, str(exc)
        except urllib.error.URLError as exc:
            return None, str(exc)
        except OSError as exc:
            return None, str(exc)
    return None, "Both HEAD and GET failed"


class MarkdownLinksTest(unittest.TestCase):
    """Verify that every HTTP(S) link in Markdown files is reachable."""

    def test_no_404_links(self):
        links = _collect_links()
        self.assertTrue(links, "No links found — check REPO_ROOT or MD_GLOBS.")

        failures: list[str] = []
        skipped: list[str] = []

        for url, source in links:
            status, err = _check_url(url)
            if status is None:
                # Network-level failure — skip rather than fail.
                skipped.append(f"  SKIP  {url}  ({source}): {err}")
            elif status == 404:
                failures.append(f"  404   {url}  (found in {source})")
            # Any other 4xx/5xx is not treated as a hard failure here because
            # some servers return 403/401 for bots even though the page exists.

        if skipped:
            print(f"\n{len(skipped)} link(s) skipped due to network errors:")
            for msg in skipped:
                print(msg)

        self.assertEqual(
            failures,
            [],
            "The following links returned 404:\n" + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()

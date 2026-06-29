"""Smoke test for the knowledge-platform site generator.

Runs ``scripts/generate_knowledge_site.py`` into a temporary directory (the
real entry point, no copied legacy assets) and asserts the expected pages and
datasets are produced, that internal cross-links between generated pages
resolve, that embedded JSON-LD parses, and that the sitemap uses the canonical
host. Idempotency is checked by running twice.
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate_knowledge_site.py"
BASE_HOST = "unosw.plus"
# Directories of generated pages whose internal links must resolve.
GENERATED_PREFIXES = ("sessions/", "speakers/", "organizations/", "projects/", "topics/")


def run_generator(out_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--conference", "unosw", "--year", "2025", "--out", str(out_dir)],
        capture_output=True, text=True, check=True,
    )


class GenerateKnowledgeSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        run_generator(cls.out)
        run_generator(cls.out)  # second run: must be idempotent (no error)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_core_pages_exist(self):
        for rel in ["explore.html", "sessions/index.html", "speakers/index.html",
                    "organizations/index.html", "projects/index.html", "topics/index.html",
                    "sessions/sess-opening-plenary.html", "speakers/sachiko-muto.html",
                    "organizations/un-odet.html", "projects/drupal.html", "topics/ai.html"]:
            self.assertTrue((self.out / rel).exists(), f"missing generated page {rel}")

    def test_datasets_and_graph_written(self):
        for rel in ["api/unosw/2025/sessions.json", "api/unosw/2025/speakers.json",
                    "api/unosw/2025/index.json", "api/knowledge-graph.json", "sitemap.xml"]:
            self.assertTrue((self.out / rel).exists(), f"missing generated artifact {rel}")
        graph = json.loads((self.out / "api/knowledge-graph.json").read_text())
        self.assertGreater(len(graph["nodes"]), 0)
        self.assertGreater(len(graph["edges"]), 0)

    def test_sitemap_uses_canonical_host(self):
        sitemap = (self.out / "sitemap.xml").read_text()
        self.assertIn(BASE_HOST, sitemap)
        self.assertNotIn("osweekplus.nyc", sitemap)

    def test_embedded_jsonld_parses(self):
        for html_file in self.out.rglob("*.html"):
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                                    html_file.read_text(), re.S):
                try:
                    json.loads(block)
                except json.JSONDecodeError as exc:
                    self.fail(f"invalid JSON-LD in {html_file.name}: {exc}")

    def test_internal_links_resolve(self):
        broken = []
        for html_file in self.out.rglob("*.html"):
            html = html_file.read_text()
            for href in re.findall(r'href="(/[^"#?]+\.html)"', html):
                rel = href.lstrip("/")
                if rel.startswith(GENERATED_PREFIXES) or rel == "explore.html":
                    if not (self.out / rel).exists():
                        broken.append(f"{html_file.name} -> {href}")
        self.assertEqual(broken, [], "broken internal links:\n" + "\n".join(broken))


if __name__ == "__main__":
    unittest.main()

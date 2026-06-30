"""Smoke test for the knowledge-platform site generator.

Runs ``scripts/generate_knowledge_site.py`` into a temporary directory (the
real entry point, no copied legacy assets) and asserts the expected pages and
datasets are produced under the ``<conference>/<year>/`` namespace, that the
cross-year hub and sitemap are built, that internal cross-links resolve, that
embedded JSON-LD parses, and that the sitemap uses the canonical host.
Idempotency is checked by running twice.
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
PREFIX = "unosw/2025"


def run_generator(out_dir: Path, year: int = 2025) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--conference", "unosw", "--year", str(year), "--out", str(out_dir)],
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
        for rel in [f"{PREFIX}/explore.html", f"{PREFIX}/sessions/index.html",
                    f"{PREFIX}/speakers/index.html", f"{PREFIX}/organizations/index.html",
                    f"{PREFIX}/projects/index.html", f"{PREFIX}/topics/index.html",
                    f"{PREFIX}/sessions/sess-opening-plenary.html",
                    f"{PREFIX}/speakers/sachiko-muto.html",
                    f"{PREFIX}/organizations/un-odet.html",
                    f"{PREFIX}/projects/drupal.html", f"{PREFIX}/topics/ai.html"]:
            self.assertTrue((self.out / rel).exists(), f"missing generated page {rel}")

    def test_top_level_hub_lists_the_year(self):
        hub = self.out / "explore.html"
        self.assertTrue(hub.exists(), "missing top-level /explore.html hub")
        self.assertIn(f"/{PREFIX}/explore.html", hub.read_text())

    def test_datasets_and_graph_written(self):
        for rel in [f"{PREFIX}/api/sessions.json", f"{PREFIX}/api/speakers.json",
                    f"{PREFIX}/api/index.json", f"{PREFIX}/api/knowledge-graph.json", "sitemap.xml"]:
            self.assertTrue((self.out / rel).exists(), f"missing generated artifact {rel}")
        graph = json.loads((self.out / f"{PREFIX}/api/knowledge-graph.json").read_text())
        self.assertGreater(len(graph["nodes"]), 0)
        self.assertGreater(len(graph["edges"]), 0)
        node_ids = {n["id"] for n in graph["nodes"]}
        dangling = [e for e in graph["edges"] if e["source"] not in node_ids or e["target"] not in node_ids]
        self.assertEqual(dangling, [], "knowledge graph has dangling edges")

    def test_discovery_endpoints(self):
        manifest_path = self.out / "api" / "index.json"
        self.assertTrue(manifest_path.exists(), "missing /api/index.json discovery manifest")
        manifest = json.loads(manifest_path.read_text())
        years = {e["year"] for e in manifest["conference_years"]}
        self.assertIn(2025, years)
        for entry in manifest["conference_years"]:
            self.assertIn("sessions", entry["datasets"])
            self.assertTrue(entry["knowledge_graph"].endswith("knowledge-graph.json"))
        llms = self.out / "llms.txt"
        self.assertTrue(llms.exists(), "missing /llms.txt")
        self.assertIn("/api/index.json", llms.read_text())

    def test_timeline_page(self):
        timeline = self.out / "timeline.html"
        self.assertTrue(timeline.exists(), "missing /timeline.html")
        html = timeline.read_text()
        self.assertIn("Themes across years", html)
        self.assertIn(f"/{PREFIX}/topics/", html)  # links to a topic page for a present year

    def test_search_index_and_page(self):
        page = self.out / "knowledge-search.html"
        self.assertTrue(page.exists(), "missing /knowledge-search.html")
        self.assertIn("/api/search-index.json", page.read_text())
        index_path = self.out / "api" / "search-index.json"
        self.assertTrue(index_path.exists(), "missing /api/search-index.json")
        records = json.loads(index_path.read_text())["records"]
        self.assertGreater(len(records), 0)
        types = {r["type"] for r in records}
        self.assertTrue({"session", "speaker", "organization", "topic"} <= types)
        for r in records:  # every record links into a generated page that exists
            self.assertTrue(r["url"].startswith("/"))
            self.assertTrue((self.out / r["url"].lstrip("/")).exists(), f"dangling search url {r['url']}")
        manifest = json.loads((self.out / "api" / "index.json").read_text())
        self.assertEqual(manifest.get("search_index"), "/api/search-index.json")

    def test_sitemap_uses_canonical_host(self):
        sitemap = (self.out / "sitemap.xml").read_text()
        self.assertIn(BASE_HOST, sitemap)
        self.assertIn(f"/{PREFIX}/", sitemap)
        self.assertNotIn("osweekplus.nyc", sitemap)

    def test_embedded_jsonld_parses(self):
        for html_file in self.out.rglob("*.html"):
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                                    html_file.read_text(), re.S):
                try:
                    json.loads(block)
                except json.JSONDecodeError as exc:
                    self.fail(f"invalid JSON-LD in {html_file}: {exc}")

    def test_internal_links_resolve(self):
        broken = []
        for html_file in self.out.rglob("*.html"):
            for href in re.findall(r'href="(/(?:unosw/\d+/[^"#?]+|explore)\.html)"', html_file.read_text()):
                if not (self.out / href.lstrip("/")).exists():
                    broken.append(f"{html_file} -> {href}")
        self.assertEqual(broken, [], "broken internal links:\n" + "\n".join(broken))


if __name__ == "__main__":
    unittest.main()

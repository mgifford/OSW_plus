"""Validate the curated knowledge-platform datasets.

Runs as part of ``python -m unittest discover -s tests``. For every conference
data-year, confirms each dataset matches its JSON Schema, every record carries
provenance with an allowed licence and an http(s) source, session ids are
unique, all cross-references resolve, every speaker appears in a session, the
topic vocabulary matches the conference config, and the derived knowledge graph
is internally consistent and schema-valid.
"""

import unittest
from pathlib import Path

from scripts import knowledge_utils as ku

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = REPO_ROOT / "schema"
CONFERENCE = "unosw"

ALLOWED_LICENSES = {"CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "public-domain"}
# Datasets whose records must each carry a provenance object.
PROVENANCED = ["sessions", "speakers", "organizations", "projects", "quotes", "references"]


class KnowledgeDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conference = ku.load_conference(REPO_ROOT / "conferences", CONFERENCE)
        cls.years = cls.conference["data_years"]
        cls.config_topics = {t["slug"] for t in cls.conference["topic_vocabulary"]}
        cls.datasets = {
            year: ku.load_datasets(REPO_ROOT / "data" / CONFERENCE / str(year))
            for year in cls.years
        }

    def test_datasets_match_schema(self):
        for year, datasets in self.datasets.items():
            with self.subTest(year=year):
                errors = ku.validate_datasets(datasets, SCHEMA_DIR)
                self.assertEqual(errors, [], f"{year} schema errors:\n" + "\n".join(errors))

    def test_cross_references_resolve(self):
        for year, datasets in self.datasets.items():
            with self.subTest(year=year):
                problems = ku.check_cross_references(datasets)
                self.assertEqual(problems, [], f"{year} dangling references:\n" + "\n".join(problems))

    def test_session_ids_are_unique(self):
        for year, datasets in self.datasets.items():
            with self.subTest(year=year):
                ids = [s["id"] for s in datasets["sessions"]]
                dupes = {i for i in ids if ids.count(i) > 1}
                self.assertEqual(dupes, set(), f"{year} duplicate session ids: {sorted(dupes)}")

    def test_every_record_has_valid_provenance(self):
        for year, datasets in self.datasets.items():
            for name in PROVENANCED:
                for record in datasets[name]:
                    ident = f"{year}:{name}:{record.get('id') or record.get('slug')}"
                    with self.subTest(record=ident):
                        prov = record.get("provenance")
                        self.assertIsNotNone(prov, f"{ident} missing provenance")
                        self.assertIn(prov.get("license"), ALLOWED_LICENSES,
                                      f"{ident} disallowed license {prov.get('license')}")
                        self.assertTrue(str(prov.get("source_url", "")).startswith(("http://", "https://")),
                                        f"{ident} source_url is not http(s)")
                        self.assertTrue(prov.get("source_title"), f"{ident} missing source_title")

    def test_topics_match_config_vocabulary(self):
        for year, datasets in self.datasets.items():
            with self.subTest(year=year):
                dataset_topics = {t["slug"] for t in datasets["topics"]}
                self.assertEqual(dataset_topics, self.config_topics,
                                 f"{year} topic mismatch: {dataset_topics ^ self.config_topics}")

    def test_every_speaker_appears_in_a_session(self):
        for year, datasets in self.datasets.items():
            with self.subTest(year=year):
                referenced = {sp for s in datasets["sessions"] for sp in s.get("speakers", [])}
                # Roster-imported speakers (from the official Speakers page, marked by
                # an official_url) need not be mapped to a session yet — the published
                # agenda carries no per-session speaker data. Curated speakers must be.
                orphans = {s["slug"] for s in datasets["speakers"]
                           if not s.get("official_url")} - referenced
                self.assertEqual(orphans, set(),
                                 f"{year} curated speakers not in any session: {sorted(orphans)}")

    def test_knowledge_graph_is_consistent_and_valid(self):
        for year, datasets in self.datasets.items():
            with self.subTest(year=year):
                graph = ku.build_graph(CONFERENCE, year, datasets,
                                       self.conference["site_base_url"], "2026-06-29T00:00:00Z")
                node_ids = {n["id"] for n in graph["nodes"]}
                dangling = [(e["source"], e["target"]) for e in graph["edges"]
                            if e["source"] not in node_ids or e["target"] not in node_ids]
                self.assertEqual(dangling, [], f"{year} graph dangling edges: {dangling[:5]}")
                errors = ku.validate_datasets({"knowledge-graph": graph}, SCHEMA_DIR)
                self.assertEqual(errors, [], f"{year} knowledge-graph schema errors:\n" + "\n".join(errors))


if __name__ == "__main__":
    unittest.main()

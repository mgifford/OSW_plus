"""Validate the curated knowledge-platform datasets.

Runs as part of ``python -m unittest discover -s tests``. Confirms every
dataset matches its JSON Schema, every record carries provenance with an
allowed licence and an http(s) source, all cross-references resolve, the topic
vocabulary matches the conference config, and the derived knowledge graph is
internally consistent and schema-valid.
"""

import json
import unittest
from pathlib import Path

from scripts import knowledge_utils as ku

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = REPO_ROOT / "schema"
CONFERENCE = "unosw"
YEAR = 2025
DATA_DIR = REPO_ROOT / "data" / CONFERENCE / str(YEAR)

ALLOWED_LICENSES = {"CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "public-domain"}
# Datasets whose records must each carry a provenance object.
PROVENANCED = ["sessions", "speakers", "organizations", "projects", "quotes", "references"]


class KnowledgeDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conference = ku.load_conference(REPO_ROOT / "conferences", CONFERENCE)
        cls.datasets = ku.load_datasets(DATA_DIR)

    def test_datasets_match_schema(self):
        errors = ku.validate_datasets(self.datasets, SCHEMA_DIR)
        self.assertEqual(errors, [], "Schema validation errors:\n" + "\n".join(errors))

    def test_cross_references_resolve(self):
        problems = ku.check_cross_references(self.datasets)
        self.assertEqual(problems, [], "Dangling references:\n" + "\n".join(problems))

    def test_every_record_has_valid_provenance(self):
        for name in PROVENANCED:
            for record in self.datasets[name]:
                ident = record.get("id") or record.get("slug")
                prov = record.get("provenance")
                self.assertIsNotNone(prov, f"{name}:{ident} missing provenance")
                self.assertIn(prov.get("license"), ALLOWED_LICENSES,
                              f"{name}:{ident} has disallowed license {prov.get('license')}")
                self.assertTrue(str(prov.get("source_url", "")).startswith(("http://", "https://")),
                                f"{name}:{ident} provenance.source_url is not an http(s) URL")
                self.assertTrue(prov.get("source_title"), f"{name}:{ident} missing provenance.source_title")

    def test_topics_match_config_vocabulary(self):
        config_topics = {t["slug"] for t in self.conference["topic_vocabulary"]}
        dataset_topics = {t["slug"] for t in self.datasets["topics"]}
        self.assertEqual(dataset_topics, config_topics,
                         f"topic mismatch: {dataset_topics ^ config_topics}")

    def test_every_speaker_appears_in_a_session(self):
        referenced = {sp for s in self.datasets["sessions"] for sp in s.get("speakers", [])}
        all_speakers = {s["slug"] for s in self.datasets["speakers"]}
        orphans = all_speakers - referenced
        self.assertEqual(orphans, set(), f"speakers not referenced by any session: {sorted(orphans)}")

    def test_knowledge_graph_is_consistent_and_valid(self):
        graph = ku.build_graph(CONFERENCE, YEAR, self.datasets,
                               self.conference["site_base_url"], "2026-06-29T00:00:00Z")
        node_ids = {n["id"] for n in graph["nodes"]}
        dangling = [(e["source"], e["target"]) for e in graph["edges"]
                    if e["source"] not in node_ids or e["target"] not in node_ids]
        self.assertEqual(dangling, [], f"graph has dangling edges: {dangling[:5]}")

        errors = ku.validate_datasets({"knowledge-graph": graph}, SCHEMA_DIR)
        self.assertEqual(errors, [], "knowledge-graph schema errors:\n" + "\n".join(errors))


if __name__ == "__main__":
    unittest.main()

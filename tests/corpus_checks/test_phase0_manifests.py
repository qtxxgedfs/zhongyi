from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]


def load_json(relative: str):
    return json.loads((PROJECT_DIR / relative).read_text(encoding="utf-8"))


class PhaseZeroManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        candidates = load_json("sources/source-candidates.json")
        cls.candidates = {work["id"]: work for work in candidates["works"]}
        cls.selection = load_json("sources/source-selection.json")
        audit = load_json("sources/wikisource-audit.json")
        cls.audit = {work["id"]: work for work in audit["works"]}

    def test_candidate_ids_are_unique(self) -> None:
        raw = load_json("sources/source-candidates.json")["works"]
        self.assertEqual(len(raw), len({work["id"] for work in raw}))

    def test_selected_and_excluded_ids_exist(self) -> None:
        for source_id in self.selection["selected_candidate_ids"]:
            self.assertIn(source_id, self.candidates)
        for item in self.selection["excluded_or_deferred"]:
            self.assertIn(item["id"], self.candidates)

    def test_no_selected_item_is_excluded(self) -> None:
        selected = set(self.selection["selected_candidate_ids"])
        excluded = {item["id"] for item in self.selection["excluded_or_deferred"]}
        self.assertFalse(selected & excluded)

    def test_all_six_core_works_are_selected(self) -> None:
        selected_works = set()
        for source_id in self.selection["selected_candidate_ids"]:
            work = self.candidates[source_id]
            if work["layer"] == "core":
                selected_works.update(work["target_works"])
        self.assertEqual(
            selected_works,
            {"suwen", "lingshu", "shanghanlun", "jingui", "nanjing", "wenbingtiaobian"},
        )

    def test_each_core_has_one_to_five_commentary_works(self) -> None:
        counts = {
            work_id: 0
            for work_id in ("suwen", "lingshu", "shanghanlun", "jingui", "nanjing", "wenbingtiaobian")
        }
        for source_id in self.selection["selected_candidate_ids"]:
            work = self.candidates[source_id]
            if work["layer"] == "commentary":
                for target in work["target_works"]:
                    counts[target] += 1
        for work in self.selection["added_replacements"]:
            if work["layer"] == "commentary":
                for target in work["target_works"]:
                    counts[target] += 1
        self.assertTrue(all(1 <= count <= 5 for count in counts.values()), counts)

    def test_selected_wikisource_candidates_were_discovered(self) -> None:
        for source_id in self.selection["selected_candidate_ids"]:
            audit = self.audit[source_id]
            self.assertNotEqual(audit["status"], "not-found", source_id)
            self.assertIsNotNone(audit.get("selected_candidate"), source_id)
            self.assertFalse(audit.get("page_info", {}).get("missing", False), source_id)

    def test_replacement_ids_and_pages_are_unique(self) -> None:
        replacements = self.selection["added_replacements"]
        ids = [item["id"] for item in replacements]
        pages = [item["page_title"] for item in replacements]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pages), len(set(pages)))
        self.assertFalse(set(ids) & set(self.candidates))

    def test_declared_counts_match(self) -> None:
        selected = self.selection["selected_candidate_ids"]
        replacements = self.selection["added_replacements"]
        core = sum(self.candidates[item]["layer"] == "core" for item in selected)
        total = len(selected) + len(replacements)
        self.assertEqual(core, self.selection["selection_count"]["core"])
        self.assertEqual(total, self.selection["selection_count"]["total_unique_works"])
        self.assertEqual(total - core, self.selection["selection_count"]["unique_extension_works"])

    def test_sqlite_schema_builds_with_fts5(self) -> None:
        sql = (PROJECT_DIR / "schemas" / "classics.sql").read_text(encoding="utf-8")
        connection = sqlite3.connect(":memory:")
        try:
            connection.executescript(sql)
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertTrue({"works", "sources", "passages", "passage_fts"} <= tables)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()

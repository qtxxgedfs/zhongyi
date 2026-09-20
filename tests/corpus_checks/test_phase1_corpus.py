from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

import jsonschema

PROJECT_DIR = Path(__file__).resolve().parents[2]
SOURCES_DIR = PROJECT_DIR / "sources"
PUA_RE = re.compile(r"[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]")
FORBIDDEN_RE = re.compile(r"�|\{\{|\}\}|</?(?:篇名|目[录錄]|noinclude|onlyinclude|poem|ref)\b")
UNRESOLVED_RE = re.compile(
    r"〔(?:未识别字\d+|原文缺字(?::[^〕]+)?|四库缺字\d+)〕|"
    r"(?<![A-Za-z])(?:HT|KT)(?![A-Za-z])|滚动条|滾動條"
)


def load_json(relative: str):
    return json.loads((PROJECT_DIR / relative).read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class PhaseOneCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = load_json("sources/source-inventory.json")
        cls.quality = load_json("sources/quality-report.json")
        cls.processed = load_json("sources/processed/summary.json")
        cls.lock = load_json("sources/source-lock.candidate.json")

    def test_all_26_sources_have_fixed_pages_and_processed_text(self) -> None:
        self.assertEqual(26, len(self.inventory["sources"]))
        self.assertEqual(26, len(self.processed["sources"]))
        self.assertEqual(
            {item["id"] for item in self.inventory["sources"]},
            {item["source_id"] for item in self.processed["sources"]},
        )
        self.assertTrue(all(item["passage_count"] > 0 for item in self.processed["sources"]))

    def test_all_snapshot_hashes_match(self) -> None:
        pages = [page for source in self.inventory["sources"] for page in source["pages"]]
        self.assertEqual(973, len(pages))
        self.assertEqual(938, sum(page["include_in_corpus"] for page in pages))
        for page in pages:
            self.assertEqual(page["raw_sha256"], sha256_file(PROJECT_DIR / page["raw_wikitext_path"]))

    def test_completeness_and_cleanup_gates_are_explicit(self) -> None:
        overall = self.quality["overall"]
        self.assertEqual("pass", overall["raw_integrity_status"])
        self.assertEqual("pass", overall["structural_status"])
        self.assertEqual("pass-with-quarantine", overall["cleanup_status"])
        self.assertEqual("pass", overall["citable_corpus_status"])
        self.assertEqual("blocked", overall["release_gate_status"])
        self.assertGreater(len(self.quality["blocking_release_reasons"]), 0)

    def test_candidate_lock_cannot_masquerade_as_final(self) -> None:
        jsonschema.Draft202012Validator(load_json("schemas/source-lock.schema.json")).validate(self.lock)
        self.assertEqual(2, self.lock["schema_version"])
        self.assertEqual("candidate-blocked", self.lock["lock_status"])
        self.assertEqual("blocked", self.lock["quality_report"]["release_gate_status"])
        self.assertFalse((SOURCES_DIR / "source-lock.json").exists())
        self.assertEqual(26, len(self.lock["sources"]))
        self.assertEqual(
            self.lock["quality_report"]["sha256"], sha256_file(SOURCES_DIR / "quality-report.json")
        )

    def test_source_manifest_has_page_level_attribution(self) -> None:
        manifest = load_json("sources/source-manifest.json")
        self.assertEqual("candidate-blocked", manifest["manifest_status"])
        self.assertEqual(973, manifest["snapshot_page_count"])
        self.assertEqual(938, manifest["included_page_count"])
        pages = [page for source in manifest["sources"] for page in source["pages"]]
        self.assertTrue(all("oldid=" in page["fixed_revision_url"] for page in pages))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", page["raw_sha256"]) for page in pages))

    def test_processed_passages_are_clean_linked_and_bounded(self) -> None:
        allowed_speaker_types = {
            "core_text", "dialogue", "quoted_core", "commentary", "textual_collation",
            "lineage", "mixed", "preface", "unknown",
        }
        total = 0
        citable_total = 0
        quarantine_total = 0
        for summary in self.processed["sources"]:
            path = PROJECT_DIR / summary["processed_path"]
            previous_id = None
            previous_record = None
            seen: set[str] = set()
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    record = json.loads(line)
                    total += 1
                    self.assertNotIn(record["id"], seen)
                    seen.add(record["id"])
                    self.assertEqual(previous_id, record["previous_id"])
                    if previous_record is not None:
                        self.assertEqual(record["id"], previous_record["next_id"])
                    self.assertLessEqual(len(record["text_simplified"]), 700)
                    self.assertTrue(record["text_simplified"])
                    self.assertIn(record["speaker_type"], allowed_speaker_types)
                    self.assertIsNone(FORBIDDEN_RE.search(record["text_simplified"]))
                    self.assertIsNone(PUA_RE.search(record["text_simplified"]))
                    self.assertIsNone(PUA_RE.search(record["text_traditional"]))
                    self.assertRegex(record["content_sha256"], r"^[0-9a-f]{64}$")
                    if record["citation_allowed"]:
                        citable_total += 1
                        self.assertTrue(record["search_allowed"])
                        self.assertEqual("clean", record["quality_status"])
                        self.assertIsNone(UNRESOLVED_RE.search(record["text_simplified"]))
                    else:
                        quarantine_total += 1
                        self.assertFalse(record["search_allowed"])
                        self.assertEqual("quarantined", record["quality_status"])
                        self.assertEqual("", record["text_search"])
                        self.assertTrue(record["quality_flags"])
                    previous_id = record["id"]
                    previous_record = record
            if previous_record is not None:
                self.assertIsNone(previous_record["next_id"])
            self.assertEqual(summary["passage_count"], len(seen))
        self.assertEqual(self.quality["overall"]["passage_count"], total)
        self.assertEqual(self.quality["overall"]["citable_passage_count"], citable_total)
        self.assertEqual(self.quality["overall"]["quarantined_passage_count"], quarantine_total)

    def test_quarantine_manifest_is_complete_and_non_citable(self) -> None:
        exclusions = load_json("sources/corpus-exclusions.json")
        quarantine = load_json("sources/quarantine/summary.json")
        self.assertEqual(288, exclusions["quarantined_passage_count"])
        self.assertEqual(exclusions["quarantined_passage_count"], quarantine["passage_count"])
        self.assertEqual(35, exclusions["issue_occurrences"]["explicit-missing-glyph"])
        self.assertEqual(340, exclusions["issue_occurrences"]["legacy-glyph-placeholder-ht-kt"])
        self.assertEqual(1, exclusions["issue_occurrences"]["known-ui-text-intrusion"])
        self.assertTrue(exclusions["policy"]["raw_snapshots_unchanged"])
        self.assertFalse(exclusions["policy"]["unresolved_glyphs_allowed_in_citable_corpus"])
        self.assertTrue(all(not item["citation_allowed"] for item in exclusions["exclusions"]))
        self.assertTrue(all(not item["search_allowed"] for item in exclusions["exclusions"]))

    def test_manual_pua_repairs_are_present(self) -> None:
        jingui = (SOURCES_DIR / "processed" / "core-jingui" / "passages.jsonl").read_text(encoding="utf-8")
        nanjing = (SOURCES_DIR / "processed" / "core-nanjing" / "passages.jsonl").read_text(encoding="utf-8")
        self.assertIn("㽲", jingui)
        self.assertIn("啘", nanjing)

    def test_image_confirmed_wenbingtiaobian_corrections_are_citable(self) -> None:
        corrections = load_json("sources/normalization/passage-text-corrections.json")
        self.assertEqual(
            {"WBTB-000004", "WBTB-000209"},
            {item["passage_id"] for item in corrections["corrections"]},
        )
        records = {}
        path = SOURCES_DIR / "processed" / "core-wenbingtiaobian" / "passages.jsonl"
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record["id"] in {"WBTB-000004", "WBTB-000209"}:
                    records[record["id"]] = record
        self.assertEqual({"WBTB-000004", "WBTB-000209"}, set(records))
        self.assertIn("韩祗和", records["WBTB-000004"]["text_simplified"])
        self.assertIn("屈伸之象", records["WBTB-000209"]["text_simplified"])
        for record in records.values():
            self.assertTrue(record["citation_allowed"])
            self.assertTrue(record["search_allowed"])
            self.assertEqual("clean", record["quality_status"])
            self.assertTrue(record["correction_ids"])

    def test_medical_xie_display_conversion(self) -> None:
        simplified = []
        path = SOURCES_DIR / "processed" / "core-suwen" / "passages.jsonl"
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                simplified.append(json.loads(line)["text_simplified"])
        text = "".join(simplified)
        self.assertIn("精气溢泻", text)
        self.assertNotIn("精气溢写", text)
        self.assertIn("盛则泻之", text)


if __name__ == "__main__":
    unittest.main()

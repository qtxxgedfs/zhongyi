from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_DIR / "build" / "classics.sqlite"
QUALITY_PATH = PROJECT_DIR / "sources" / "quality-report.json"
EXCLUSIONS_PATH = PROJECT_DIR / "sources" / "corpus-exclusions.json"
SEARCH_SCRIPT = PROJECT_DIR / "skill" / "tcm-classics-study" / "scripts" / "search.py"
INDEX_MANIFEST = PROJECT_DIR / "build" / "classics-index-manifest.json"


@unittest.skipUnless(DB_PATH.exists(), "candidate SQLite index has not been built")
class PhaseTwoIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        cls.connection.row_factory = sqlite3.Row
        cls.quality = json.loads(QUALITY_PATH.read_text(encoding="utf-8"))
        cls.exclusions = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.connection.close()

    def test_index_contains_only_citable_passages(self) -> None:
        metadata = dict(self.connection.execute("SELECT key, value FROM schema_info"))
        expected = self.quality["overall"]["citable_passage_count"]
        self.assertEqual(int(metadata["passage_count"]), expected)
        self.assertEqual(
            int(metadata["quarantined_passages_excluded"]),
            self.quality["overall"]["quarantined_passage_count"],
        )
        self.assertEqual(self.connection.execute("SELECT count(*) FROM passages").fetchone()[0], expected)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM passage_fts").fetchone()[0], expected)
        quarantined_ids = {item["passage_id"] for item in self.exclusions["exclusions"]}
        placeholders = ",".join("?" for _ in quarantined_ids)
        leaked = self.connection.execute(
            f"SELECT count(*) FROM passages WHERE id IN ({placeholders})", tuple(quarantined_ids)
        ).fetchone()[0]
        self.assertEqual(leaked, 0)

    def test_sqlite_integrity_and_fixed_page_traceability(self) -> None:
        self.assertEqual(self.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        manifest = json.loads(INDEX_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(DB_PATH.read_bytes()).hexdigest(), manifest["database_sha256"])
        self.assertEqual(manifest["status"], "candidate")
        page_count = self.connection.execute("SELECT count(*) FROM source_pages").fetchone()[0]
        self.assertEqual(page_count, self.quality["overall"]["snapshot_page_count"])
        missing = self.connection.execute(
            """
            SELECT count(*) FROM passages p
            LEFT JOIN source_pages sp ON sp.id=p.source_page_id
            WHERE sp.id IS NULL OR length(sp.raw_sha256) != 32
            """
        ).fetchone()[0]
        self.assertEqual(missing, 0)

    def test_bigram_fts_finds_known_core_text(self) -> None:
        rows = self.connection.execute(
            """
            SELECT p.id FROM passage_fts
            JOIN passages p ON p.rowid=passage_fts.rowid
            WHERE passage_fts MATCH '\"治未\" AND \"未病\"'
            LIMIT 100
            """
        ).fetchall()
        self.assertIn("SW-000004", {row["id"] for row in rows})

    def test_search_cli_routes_and_returns_simplified_citations(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SEARCH_SCRIPT),
                "--db",
                str(DB_PATH),
                "search",
                "--query",
                "《伤寒论》桂枝汤原文",
                "--terms",
                "桂枝汤",
                "--limit-total",
                "4",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["database_build_status"], "candidate")
        self.assertEqual(payload["quarantined_passages_excluded"], 290)
        self.assertTrue(payload["results"])
        self.assertTrue(all("text_simplified" in item for item in payload["results"]))
        self.assertTrue(all("text_search" not in item for item in payload["results"]))
        core_result = next(item for item in payload["results"] if item["work_id"] == "core-shanghanlun")
        self.assertNotIn("傷寒論", core_result["source_page_title"])
        self.assertTrue(all("shanghanlun" in payload["route"]["target_works"] for _ in [0]))
        self.assertLess(payload["elapsed_ms"], 1000)


if __name__ == "__main__":
    unittest.main()

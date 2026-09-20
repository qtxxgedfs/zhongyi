from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_DIR / "skill" / "tcm-classics-study"
DB_PATH = SKILL_DIR / "data" / "evidence-cache.sqlite"
MANIFEST_PATH = SKILL_DIR / "data" / "evidence-cache.manifest.json"
SCRIPT_PATH = SKILL_DIR / "scripts" / "modern_evidence.py"
SELF_CHECK_PATH = SKILL_DIR / "scripts" / "self_check.py"
RUNTIME_MANIFEST_PATH = SKILL_DIR / "data" / "runtime-candidate-manifest.json"


def run_cli(command: str, query: str | None = None, *extra: str) -> dict:
    arguments = [sys.executable, str(SCRIPT_PATH), command]
    if query is not None:
        arguments.extend(["--query", query])
    arguments.extend(extra)
    completed = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


class PhaseThreeModernEvidenceTests(unittest.TestCase):
    def test_curated_cache_hash_integrity_and_counts(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(DB_PATH.read_bytes()).hexdigest(), manifest["database_sha256"])
        self.assertEqual(25, manifest["topic_count"])
        self.assertEqual(6, manifest["verified_record_count"])
        status = run_cli("status", None, "--as-of", "2026-09-18")
        self.assertEqual("ok", status["integrity_check"])
        self.assertEqual(6, status["records"]["fresh"])

    def test_staged_candidate_is_runnable_and_explicitly_not_final(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SELF_CHECK_PATH)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(completed.stdout)
        runtime = json.loads(RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual("pass", payload["status"])
        version = (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(version, payload["project_version"])
        self.assertEqual(version, runtime["project_version"])
        self.assertEqual("candidate-runnable", runtime["status"])
        self.assertEqual("blocked", runtime["release_gate_status"])
        self.assertEqual(288, payload["quarantined_passages_excluded"])
        self.assertTrue(payload["study_packet_smoke"])
        self.assertTrue(payload["markdown_render_smoke"])
        self.assertTrue(payload["m3_classic_retrieval_deferred"])
        runtime_paths = {item["path"] for item in runtime["files"]}
        self.assertIn("scripts/study.py", runtime_paths)
        self.assertIn("scripts/render.py", runtime_paths)
        self.assertIn("data/query-rules.json", runtime_paths)
        self.assertIn("USER_GUIDE.md", runtime_paths)
        guide = (SKILL_DIR / "USER_GUIDE.md").read_text(encoding="utf-8")
        for title in ("《素问》", "《灵枢》", "《伤寒论》", "《金匮要略》", "《难经》", "《温病条辨》"):
            self.assertIn(title, guide)
        self.assertIn("急症提示应当先于古籍检索", guide)

    def test_m0_pure_textual_question_does_not_force_modern_layer(self) -> None:
        payload = run_cli("assess", "《素问》治未病原文在哪一篇")
        self.assertEqual("M0", payload["classification"]["level"])
        self.assertFalse(payload["classification"]["modern_layer_required"])
        self.assertFalse(payload["online_search_plan"]["required"])

    def test_m1_concept_comparison(self) -> None:
        payload = run_cli("assess", "阴阳和现代医学概念能直接对应吗")
        self.assertEqual("M1", payload["classification"]["level"])
        self.assertIn(
            "classical-concept-boundaries",
            {item["id"] for item in payload["classification"]["matched_topics"]},
        )
        self.assertTrue(payload["online_search_plan"]["required"])

    def test_m2_uses_fresh_curated_acupuncture_cache(self) -> None:
        payload = run_cli("assess", "针灸对腰痛有效吗，有什么副作用")
        self.assertEqual("M2", payload["classification"]["level"])
        self.assertGreaterEqual(payload["cache"]["fresh_record_count"], 2)
        self.assertTrue(all(item["citation_recommended"] for item in payload["cache"]["records"]))
        self.assertTrue(all(item["limitations_zh"] for item in payload["cache"]["records"]))
        self.assertFalse(payload["online_search_plan"]["required"])

    def test_latest_request_forces_online_refresh(self) -> None:
        payload = run_cli("assess", "针灸治疗腰痛最新研究怎么说")
        self.assertEqual("M2", payload["classification"]["level"])
        self.assertTrue(payload["classification"]["latest_evidence_requested"])
        self.assertTrue(payload["online_search_plan"]["required"])

    def test_m3_stroke_risk_puts_safety_before_tools(self) -> None:
        payload = run_cli("assess", "我父亲突然说话不清楚，一侧手脚没力怎么办")
        classification = payload["classification"]
        self.assertEqual("M3", classification["level"])
        self.assertTrue(classification["safety_must_precede_retrieval"])
        self.assertIn("立即联系", classification["safety_message"])
        self.assertTrue(payload["cache"]["records"])
        self.assertTrue(payload["online_search_plan"]["must_not_delay_safety_message"])

    def test_m3_without_cache_degrades_to_online_plan(self) -> None:
        payload = run_cli("assess", "我现在胸口有压迫感，喘不过气怎么办")
        self.assertEqual("M3", payload["classification"]["level"])
        self.assertTrue(payload["online_search_plan"]["required"])
        self.assertTrue(payload["online_search_plan"]["queries"])
        self.assertNotIn("我现在", json.dumps(payload["online_search_plan"], ensure_ascii=False))

    def test_academic_emergency_term_does_not_claim_active_emergency(self) -> None:
        payload = run_cli("classify", "《伤寒论》胸痛原文在哪一篇")
        self.assertEqual("M0", payload["level"])
        self.assertFalse(payload["safety_must_precede_retrieval"])

    def test_stale_cache_is_not_recommended_for_direct_citation(self) -> None:
        payload = run_cli("assess", "针灸有什么副作用", "--as-of", "2028-01-01", "--include-stale")
        self.assertGreater(payload["cache"]["stale_record_count"], 0)
        self.assertTrue(all(not item["citation_recommended"] for item in payload["cache"]["records"]))
        self.assertTrue(payload["online_search_plan"]["required"])

    def test_source_registry_rejects_unknown_or_insecure_domains(self) -> None:
        approved = run_cli("source-check", None, "--url", "https://www.cdc.gov/stroke/signs-symptoms/index.html")
        unknown = run_cli("source-check", None, "--url", "https://example.com/claim")
        insecure = run_cli("source-check", None, "--url", "http://www.cdc.gov/stroke/")
        self.assertTrue(approved["approved"])
        self.assertFalse(unknown["approved"])
        self.assertFalse(insecure["approved"])


if __name__ == "__main__":
    unittest.main()

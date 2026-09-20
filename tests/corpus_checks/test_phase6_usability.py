from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_DIR / "skill" / "tcm-classics-study"
SEARCH = SKILL_DIR / "scripts" / "search.py"
STUDY = SKILL_DIR / "scripts" / "study.py"
RENDER = SKILL_DIR / "scripts" / "render.py"
QUESTIONS = PROJECT_DIR / "tests" / "natural" / "questions.jsonl"
CONVERSATIONS = PROJECT_DIR / "tests" / "natural" / "conversations.jsonl"
RULES = SKILL_DIR / "data" / "query-rules.json"


def run_json(script: Path, *arguments: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(script), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def run_search(query: str) -> dict:
    return run_json(SEARCH, "search", "--query", query)


class PhaseSixUsabilityTests(unittest.TestCase):
    def test_reader_like_fixtures_are_fixed_and_do_not_supply_terms(self) -> None:
        questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line]
        conversations = [json.loads(line) for line in CONVERSATIONS.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(60, len(questions))
        self.assertEqual(10, len(conversations))
        self.assertTrue(all("terms" not in item for item in questions))
        self.assertEqual(1, json.loads(RULES.read_text(encoding="utf-8"))["schema_version"])

    def test_remembered_wording_prioritizes_exact_core_source(self) -> None:
        payload = run_search("我记得病了才治就像口渴才挖井，那句原话是什么")
        self.assertEqual("SW-000004", payload["results"][0]["id"])
        self.assertEqual("A", payload["results"][0]["match"]["tier"])
        self.assertIn("渴而穿井", payload["terms"])
        self.assertFalse(payload["needs_clarification"]["required"])

    def test_misremembered_work_uses_disclosed_soft_fallback(self) -> None:
        payload = run_search("《难经》里是不是有口渴才挖井的比喻")
        self.assertEqual("SW-000004", payload["results"][0]["id"])
        self.assertTrue(payload["route_resolution"]["conflict_detected"])
        self.assertEqual("relaxed-fallback", payload["route_resolution"]["mode"])
        self.assertTrue(payload["route_resolution"]["message"])

    def test_short_fragments_are_not_displayed_and_long_passages_use_core_quote(self) -> None:
        payload = run_search("桂枝汤那段到底讲啥，简单说说")
        self.assertEqual("SHL-000054", payload["results"][0]["id"])
        self.assertTrue(payload["results"][0]["full_text_available"])
        self.assertLessEqual(len(payload["results"][0]["core_quote"]), 320)
        self.assertIn(payload["results"][0]["core_quote"], payload["results"][0]["text_simplified"])
        self.assertTrue(
            all(item["match"]["standalone_quality"] == "usable" for item in payload["results"])
        )
        self.assertFalse(any(item["text_simplified"] in {"三两", "二两", "十枚"} for item in payload["results"]))

    def test_broad_question_returns_one_representative_item_and_scope_prompt(self) -> None:
        payload = run_search("阴阳到底怎么理解")
        self.assertTrue(payload["needs_clarification"]["required"])
        self.assertEqual("scope-too-broad", payload["needs_clarification"]["reason"])
        self.assertEqual(1, len(payload["results"]))
        self.assertEqual("SW-000011", payload["results"][0]["id"])

    def test_packet_has_one_standard_protocol_and_explicit_follow_up_anchor(self) -> None:
        packet = run_json(STUDY, "--query", "我记得病了才治就像口渴才挖井")
        self.assertEqual(2, packet["schema_version"])
        self.assertTrue(packet["standard_study_only"])
        self.assertEqual("standard", packet["answer_contract"]["mode"])
        self.assertEqual("宁缺毋滥", packet["interaction_principle"])
        self.assertEqual("SW-000004", packet["answer_contract"]["primary_passage_id"])
        self.assertGreaterEqual(len(packet["answer_contract"]["standard_protocol"]), 6)
        self.assertNotIn("depth", packet["answer_contract"])

    def test_explicit_anchor_expands_context_without_hidden_state(self) -> None:
        packet = run_json(
            STUDY,
            "--query",
            "展开上一条的前后文",
            "--anchor-id",
            "SW-000004",
        )
        ids = [item["id"] for item in packet["A_core"]]
        self.assertEqual(["SW-000003", "SW-000004", "SW-000005"], ids)
        self.assertEqual("anchored-context", packet["classic_search"]["route_resolution"]["mode"])
        self.assertEqual("none", packet["answer_contract"]["follow_up"]["state_storage"])
        self.assertEqual("SW-000004", packet["answer_contract"]["primary_passage_id"])

    def test_html_collapses_full_passage_while_markdown_keeps_core_quote(self) -> None:
        packet = run_json(STUDY, "--query", "桂枝汤那段讲什么")
        self.assertTrue(packet["A_core"][0]["full_text_available"])
        with tempfile.TemporaryDirectory() as directory:
            packet_path = Path(directory) / "packet.json"
            packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
            html_output = subprocess.run(
                [sys.executable, str(RENDER), "--input", str(packet_path), "--format", "html"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout
            markdown_output = subprocess.run(
                [sys.executable, str(RENDER), "--input", str(packet_path), "--format", "markdown"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout
        self.assertIn("<details>", html_output)
        self.assertIn(packet["A_core"][0]["text_simplified"], html_output)
        self.assertIn(packet["A_core"][0]["core_quote"], markdown_output)
        self.assertIn("默认未展开", markdown_output)

    def test_budget_never_accepts_an_oversized_first_result(self) -> None:
        packet = run_json(
            STUDY,
            "--query",
            "阴阳者天地之道原文",
            "--terms",
            "阴阳者天地之道",
            "--character-budget",
            "500",
        )
        self.assertLessEqual(packet["context_budget"]["selected_characters"], 500)


if __name__ == "__main__":
    unittest.main()

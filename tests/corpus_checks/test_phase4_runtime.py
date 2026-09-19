from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_DIR / "skill" / "tcm-classics-study"
STUDY = SKILL_DIR / "scripts" / "study.py"
RENDER = SKILL_DIR / "scripts" / "render.py"


def run_study(query: str, terms: str | None = None) -> dict:
    command = [sys.executable, str(STUDY), "--query", query]
    if terms:
        command.extend(["--terms", terms])
    completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(completed.stdout)


class PhaseFourRuntimeTests(unittest.TestCase):
    def test_one_call_packet_contains_layered_classics_and_modern_plan(self) -> None:
        packet = run_study("《素问》治未病在说什么，和现代预防有什么区别", "治未病")
        self.assertEqual("M1", packet["classification"]["level"])
        self.assertTrue(packet["A_core"])
        self.assertTrue(packet["B_physicians"])
        self.assertTrue(packet["C_modern"]["required"])
        self.assertLessEqual(packet["context_budget"]["selected_characters"], 2500)
        self.assertTrue(all(item["layer"] == "core" for item in packet["A_core"]))
        self.assertTrue(all(item["layer"] != "core" for item in packet["B_physicians"]))
        self.assertTrue(all("oldid=" in item["fixed_source_url"] for item in packet["A_core"]))

    def test_m3_packet_defers_classic_retrieval(self) -> None:
        packet = run_study("我父亲突然说话不清楚，一侧手脚没力怎么办")
        self.assertEqual("M3", packet["classification"]["level"])
        self.assertTrue(packet["safety_first"]["required"])
        self.assertTrue(packet["safety_first"]["classic_retrieval_deferred"])
        self.assertEqual([], packet["A_core"])
        self.assertEqual([], packet["B_physicians"])
        self.assertIn("不要等待古籍解释", packet["safety_first"]["message"])

    def test_markdown_renderer_uses_fixed_layers_and_database_quotes(self) -> None:
        packet = run_study("《伤寒论》桂枝汤原文", "桂枝汤")
        with tempfile.TemporaryDirectory() as directory:
            packet_path = Path(directory) / "packet.json"
            output_path = Path(directory) / "answer.md"
            packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(RENDER), "--input", str(packet_path), "--format", "markdown", "--output", str(output_path)],
                check=True,
            )
            rendered = output_path.read_text(encoding="utf-8")
        self.assertIn("## 🟩 A｜原典", rendered)
        self.assertIn("## 🟧 B｜历代医家", rendered)
        self.assertNotIn("## 🟦 C｜现代医学", rendered)
        self.assertIn(packet["A_core"][0]["text_simplified"], rendered)
        self.assertIn(packet["A_core"][0]["id"], rendered)

    def test_html_renderer_is_accessible_self_contained_and_escapes_query(self) -> None:
        packet = run_study("《素问》治未病原文<script>alert(1)</script>", "治未病")
        with tempfile.TemporaryDirectory() as directory:
            packet_path = Path(directory) / "packet.json"
            output_path = Path(directory) / "answer.html"
            packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(RENDER), "--input", str(packet_path), "--format", "html", "--output", str(output_path)],
                check=True,
            )
            rendered = output_path.read_text(encoding="utf-8")
        self.assertIn('lang="zh-CN"', rendered)
        self.assertIn("font-size:18px", rendered)
        self.assertIn("line-height:1.75", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertNotIn("@import", rendered)
        self.assertNotIn("linear-gradient", rendered)

    def test_m2_renderer_shows_evidence_labels_and_limitations(self) -> None:
        packet = run_study("针灸对腰痛有效吗，有什么副作用", "针灸,腰痛")
        with tempfile.TemporaryDirectory() as directory:
            packet_path = Path(directory) / "packet.json"
            packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(RENDER), "--input", str(packet_path), "--format", "markdown"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertIn("## 🟦 C｜现代医学", completed.stdout)
        self.assertIn("**对应直接性：**", completed.stdout)
        self.assertIn("**主要限制：**", completed.stdout)
        self.assertIn("NCCIH", completed.stdout)


if __name__ == "__main__":
    unittest.main()

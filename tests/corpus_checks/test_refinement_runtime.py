"""1.1.1 regressions: real natural questions through search, packet and render."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT / "skill" / "tcm-classics-study" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import search
import study
import render


class RefinementRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = search.connect(search.DEFAULT_DB)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def search(self, query, *options):
        return search.search(self.connection, search.parser().parse_args(["search", "--query", query, *options]))

    def packet(self, query, *options):
        return study.prepare(study.build_parser().parse_args(["--query", query, *options]))

    def assert_packet_consistent(self, packet):
        main = packet["A_core"] + packet["B_physicians"]
        all_items = main + packet["source_alternatives"]
        ids = {item["id"] for item in all_items}
        self.assertEqual(ids, set(packet["answer_contract"]["classic_quote_ids"]))
        primary = packet["answer_contract"]["primary_passage_id"]
        if primary:
            self.assertIn(primary, {item["id"] for item in main})
        size = sum(len(item["text_simplified"]) for item in all_items)
        self.assertEqual(size, packet["context_budget"]["selected_characters"])
        self.assertLessEqual(size, packet["context_budget"]["maximum_characters"])
        self.assertEqual(len(main), packet["classic_search"]["quality_policy"]["displayed_results"])
        for item in all_items:
            stored = search.get_passage(self.connection, item["id"])
            self.assertEqual(stored["text_simplified"], item["text_simplified"])
            self.assertIn(item["core_quote"], stored["text_simplified"])
            start, end = item["core_quote_start"], item["core_quote_end"]
            self.assertEqual(item["core_quote"], stored["text_simplified"][start:end])

    def test_named_author_and_cli_filter_are_equivalent(self):
        query = "成无己如何解释桂枝汤"
        natural = self.search(query)
        explicit = self.search(query, "--author", "成无己")
        self.assertEqual([i["id"] for i in natural["results"]], [i["id"] for i in explicit["results"]])
        self.assertEqual("COMMENTARY-SHANGHAN-CHENGWUJI-000118", natural["results"][0]["id"])
        self.assertFalse(natural["route_resolution"]["conflict_detected"])
        self.assertEqual([], natural["alternative_results"])

    def test_wording_and_multiple_author_variants_do_not_escape_scope(self):
        cases = [
            ("成无己如何解释桂枝汤原文", "成无己"),
            ("成无己怎么说桂枝汤", "成无己"),
            ("成无己如何解释麻黄汤", "成无己"),
            ("成无己如何解释小柴胡汤", "成无己"),
            ("柯琴如何解释桂枝汤", "柯琴"),
            ("尤怡怎样解释百合病", "尤怡"),
            ("张介宾怎样解释治未病", "张介宾"),
            ("只看成无己对桂枝汤的解释，不要其他医家", "成无己"),
        ]
        for query, author in cases:
            with self.subTest(query=query):
                payload = self.search(query)
                self.assertTrue(payload["results"])
                self.assertTrue(all(author in i["author"] for i in payload["results"]))
                self.assertEqual("strict", payload["route_resolution"]["mode"])
                self.assertFalse(payload["route_resolution"]["conflict_detected"])
                self.assertEqual([], payload["alternative_results"])

    def test_author_aliases_do_not_add_intersecting_filters(self):
        variants = ["张介宾", "张景岳", "景岳", "張介賓"]
        for name in variants:
            with self.subTest(name=name):
                result = self.search(name + "如何解释三焦")
                self.assertTrue(result["results"])
                self.assertEqual(1, len(result["route"]["author_groups"]))
                self.assertTrue(all(i["author"] == "张介宾" for i in result["results"]))
        result = self.search("三焦", "--author", "张景岳")
        self.assertTrue(all(i["author"] == "张介宾" for i in result["results"]))

    def test_original_work_hit_is_not_replaced_by_representative(self):
        result = self.search("《金匮要略》桂枝汤原文")
        self.assertFalse(result["route_resolution"]["conflict_detected"])
        self.assertEqual("JKY-000233", result["results"][0]["id"])
        self.assertEqual([], result["alternative_results"])

    def test_commentary_titles_win_over_embedded_original_titles(self):
        for title, work in [
            ("注解伤寒论", "commentary-shanghan-chengwuji"),
            ("伤寒论条辨", "commentary-shanghan-fangyouzhi"),
            ("伤寒论注", "commentary-shanghan-keqin"),
            ("伤寒来苏集", "commentary-shanghan-keqin"),
        ]:
            with self.subTest(title=title):
                result = self.search(f"《{title}》桂枝汤原文")
                self.assertTrue(result["results"])
                self.assertEqual({work}, {i["work_id"] for i in result["results"]})
                self.assertFalse(result["route_resolution"]["conflict_detected"])

    def test_comparison_reserves_two_and_three_authors(self):
        for query, expected in [
            ("比较成无己和柯琴对桂枝汤的解释", {"成无己", "柯琴"}),
            ("比较成无己和柯琴对小柴胡汤的解释", {"成无己", "柯琴"}),
            ("比较方有执和柯琴对桂枝汤的解释", {"方有执", "柯琴"}),
            ("请比较成无己、柯琴、尤怡对桂枝汤的解释", {"成无己", "柯琴", "尤怡"}),
        ]:
            with self.subTest(query=query):
                packet = self.packet(query)
                coverage = packet["classic_search"]["scope_coverage"]
                self.assertEqual(expected, {g["label"] for g in coverage})
                self.assertTrue(all(g["status"] == "matched" for g in coverage))
                self.assertTrue(packet["answer_contract"]["comparison_complete"])
                self.assert_packet_consistent(packet)

    def test_missing_comparison_author_is_not_replaced(self):
        packet = self.packet("比较成无己和王冰对桂枝汤的解释")
        coverage = {g["label"]: g["status"] for g in packet["classic_search"]["scope_coverage"]}
        self.assertEqual("matched", coverage["成无己"])
        self.assertEqual("not-found", coverage["王冰"])
        self.assertFalse(packet["answer_contract"]["comparison_complete"])
        self.assertTrue(packet["classic_search"]["needs_clarification"]["required"])
        self.assertTrue(all(i["author"] == "成无己" for i in packet["B_physicians"]))

    def test_hard_scope_and_negative_mentions(self):
        result = self.search("不看成无己，只看柯琴怎样解释桂枝汤")
        self.assertTrue(result["results"])
        self.assertEqual({"柯琴"}, {i["author"] for i in result["results"]})
        for query, options in [
            ("只看王冰怎么注桂枝汤", []),
            ("只查《温病条辨》独取寸口", []),
            ("只在《温病条辨》中查独取寸口原文", []),
            ("王冰怎么注桂枝汤原文", ["--no-route-fallback"]),
            ("王冰怎么注桂枝汤原文", ["--author", "王冰"]),
        ]:
            with self.subTest(query=query, options=options):
                result = self.search(query, *options)
                self.assertEqual([], result["results"])
                self.assertEqual([], result["alternative_results"])
                self.assertFalse(result["route_resolution"]["conflict_detected"])

    def test_wrong_author_has_separate_alternatives_not_a_substitution(self):
        packet = self.packet("王冰怎么注桂枝汤原文")
        self.assertEqual([], packet["A_core"])
        self.assertEqual([], packet["B_physicians"])
        self.assertTrue(packet["source_alternatives"])
        self.assertIsNone(packet["answer_contract"]["primary_passage_id"])
        self.assertFalse(packet["classic_search"]["route_resolution"]["conflict_detected"])
        self.assertNotIn("记混", packet["classic_search"]["route_resolution"]["message"])
        for output in (render.render_markdown(packet), render.render_html(packet)):
            self.assertIn("范围外备选", output)
            self.assertNotIn("记错", output)
            self.assertNotIn("记混", output)
        self.assert_packet_consistent(packet)

    def test_real_source_lookup_still_recovers_with_neutral_notice(self):
        payload = self.search("《难经》里是不是有口渴才挖井的比喻")
        self.assertEqual("SW-000004", payload["results"][0]["id"])
        self.assertEqual("relaxed-fallback", payload["route_resolution"]["mode"])
        self.assertTrue(payload["route_resolution"]["conflict_detected"])
        self.assertIn("不归属于原指定来源", payload["route_resolution"]["message"])
        self.assertNotIn("记混", payload["route_resolution"]["message"])

    def test_quoted_phrase_and_focus_survive_formula_expansion(self):
        quoted = self.search("桂枝汤“啜热稀粥”原文")
        self.assertEqual(["啜热稀粥"], quoted["query_plan"]["quoted_terms"])
        self.assertEqual([], quoted["query_plan"]["preferred_passage_ids"])
        self.assertTrue(quoted["results"])
        self.assertTrue(all("啜热稀粥" in search.normalize(i["core_quote"]) for i in quoted["results"]))
        for query, expected_focus in [("桂枝汤服后啜热粥的原因", "啜热粥"),
                                      ("桂枝汤禁忌", "不可")]:
            with self.subTest(query=query):
                result = self.search(query)
                self.assertIn(expected_focus, result["query_plan"]["focus_terms"])
                self.assertTrue(result["results"])
                self.assertTrue(all(i["match"]["focus_matches"] for i in result["results"]))
        other = self.search("小柴胡汤禁忌")
        self.assertEqual(["小柴胡汤"], other["query_plan"]["topic_terms"])
        self.assertTrue(other["results"])

    def test_formula_comparison_keeps_both_sides_and_disease_qualifiers(self):
        for query, labels in [("桂枝汤与麻黄汤有什么区别", {"桂枝汤", "麻黄汤"}),
                              ("桂枝汤治疗太阳病与阳明病的区别", {"太阳病", "阳明病"})]:
            result = self.search(query)
            self.assertEqual(labels, {g["label"] for g in result["scope_coverage"]})
            self.assertTrue(all(g["status"] == "matched" for g in result["scope_coverage"]))

    def test_cross_work_comparison_reports_missing_original(self):
        result = self.search("《素问》和《难经》怎样谈寸口脉")
        statuses = {g["label"]: g["status"] for g in result["scope_coverage"]}
        self.assertEqual("matched", statuses["《难经》"])
        self.assertEqual("not-found", statuses["《素问》"])
        self.assertTrue(result["needs_clarification"]["required"])
        mixed = self.search("比较《伤寒论》和《注解伤寒论》的桂枝汤原文")
        self.assertTrue(all(g["status"] == "matched" for g in mixed["scope_coverage"]))
        self.assertEqual({"core-shanghanlun", "commentary-shanghan-chengwuji"},
                         {i["work_id"] for i in mixed["results"]})

    def test_comparison_limit_is_explicit_not_silent(self):
        result = self.search("比较成无己、柯琴、尤怡对桂枝汤的解释", "--limit-total", "1")
        self.assertEqual(1, len(result["results"]))
        self.assertTrue(any(g["status"] == "not-displayed" for g in result["scope_coverage"]))
        self.assertTrue(result["needs_clarification"]["required"])
        empty = self.search("成无己如何解释桂枝汤", "--limit-total", "0")
        self.assertEqual([], empty["results"])
        self.assertEqual("selection-limited", empty["needs_clarification"]["reason"])

    def test_quoted_core_does_not_consume_commentary_slot(self):
        for query in ["张介宾如何解释三焦", "张介宾怎样解释治未病"]:
            packet = self.packet(query)
            self.assertTrue(packet["B_physicians"])
            self.assertTrue(all(i["speaker_type"] != "quoted_core" for i in packet["B_physicians"]))
            self.assert_packet_consistent(packet)

    def test_context_keeps_quoted_core_but_labels_it(self):
        packet = self.packet("展开全文", "--anchor-id", "COMMENTARY-NEIJING-LEIJING-000194",
                             "--context-before", "0", "--context-after", "0")
        self.assertEqual("quoted_core", packet["B_physicians"][0]["speaker_type"])
        for output in (render.render_markdown(packet), render.render_html(packet)):
            self.assertIn("注书转引经文", output)
        self.assert_packet_consistent(packet)

    def test_budget_is_shared_and_omissions_are_not_no_match(self):
        packet = self.packet("阴阳者天地之道原文", "--character-budget", "500")
        self.assertTrue(packet["classic_search"]["quality_policy"]["budget_omitted"])
        self.assertTrue(packet["A_core"])
        for output in (render.render_markdown(packet), render.render_html(packet)):
            self.assertIn("已检得但因预算未展示", output)
            self.assertNotIn("未检得足够直接且可独立理解的原典材料", output)
        self.assert_packet_consistent(packet)

    def test_anchor_is_prioritized_before_previous_passage(self):
        packet = self.packet("展开前后文", "--anchor-id", "SHL-000054", "--character-budget", "500")
        self.assertEqual("SHL-000054", packet["answer_contract"]["primary_passage_id"])
        self.assertIn("SHL-000054", packet["answer_contract"]["classic_quote_ids"])
        self.assert_packet_consistent(packet)

    def test_oversized_or_missing_anchor_never_claimed_as_displayed(self):
        packet = self.packet("展开前后文", "--anchor-id", "SW-000011", "--character-budget", "500")
        self.assertEqual([], packet["A_core"])
        self.assertIsNone(packet["answer_contract"]["primary_passage_id"])
        self.assertEqual("anchor-over-budget", packet["classic_search"]["needs_clarification"]["reason"])
        self.assert_packet_consistent(packet)
        packet = self.packet("展开前后文", "--anchor-id", "NOT-FOUND")
        self.assertIsNone(packet["answer_contract"]["primary_passage_id"])
        self.assertEqual("anchor-not-found", packet["classic_search"]["needs_clarification"]["reason"])

    def test_preview_omits_empty_layer_and_uses_chinese_relations(self):
        packet = self.packet("成无己如何解释桂枝汤")
        self.assertNotIn("🟩 A｜原典", packet["answer_contract"]["required_sections"])
        for output in (render.render_markdown(packet), render.render_html(packet)):
            self.assertIn("材料预览说明", output)
            self.assertIn("直接注释", output)
            self.assertNotIn("direct_commentary", output)
            self.assertNotIn("🟩 A｜原典", output)
            self.assertNotIn("一句话主旨", output)

    def test_budgeted_comparison_updates_coverage(self):
        packet = self.packet("比较成无己、柯琴、尤怡对桂枝汤的解释", "--character-budget", "500")
        self.assertFalse(packet["answer_contract"]["comparison_complete"])
        self.assertTrue(any(g["status"] == "not-displayed-budget" for g in packet["classic_search"]["scope_coverage"]))
        self.assertTrue(packet["classic_search"]["needs_clarification"]["required"])
        self.assert_packet_consistent(packet)

    def test_m3_deferred_retrieval_has_no_alternatives_or_citations(self):
        packet = self.packet("我父亲突然说话不清楚，一侧手脚没力怎么办")
        self.assertTrue(packet["safety_first"]["classic_retrieval_deferred"])
        self.assertEqual([], packet["source_alternatives"])
        self.assertEqual([], packet["answer_contract"]["classic_quote_ids"])
        self.assert_packet_consistent(packet)


if __name__ == "__main__":
    unittest.main()

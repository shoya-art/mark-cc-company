import importlib.util
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "threads_analyze.py"
SPEC = importlib.util.spec_from_file_location("threads_analyze", SCRIPT_PATH)
threads_analyze = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = threads_analyze
SPEC.loader.exec_module(threads_analyze)


class ThreadsAnalyzeTests(unittest.TestCase):
    def test_language_review_uses_structured_tool_output(self):
        rows = [{
            "id": str(index),
            "body": f"投稿{index}",
            "views": 100 + index,
            "engagement_rate": 0.01,
        } for index in range(5)]
        expected = {
            "summary": "構造化成功",
            "facts": [],
            "problems": [],
            "hypotheses": [],
            "next_tests": [],
            "knowledge_candidates": [],
        }
        response = SimpleNamespace(content=[
            SimpleNamespace(type="tool_use", input=expected)
        ])
        fake_client = SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kwargs: response)
        )

        with patch.dict(threads_analyze.os.environ, {"ANTHROPIC_API_KEY": "test"}), patch.object(
            threads_analyze.anthropic,
            "Anthropic",
            return_value=fake_client,
        ):
            result = threads_analyze.language_review(rows)

        self.assertEqual(result, expected)

    def test_records_top_bottom_gap_without_claiming_a_cause(self):
        rows = [
            {"id": "high", "views": 500, "engagement_rate": 0.03},
            {"id": "middle-1", "views": 200, "engagement_rate": 0.02},
            {"id": "middle-2", "views": 150, "engagement_rate": 0.02},
            {"id": "low", "views": 50, "engagement_rate": 0.01},
        ]

        fact = threads_analyze.performance_contrast_facts(rows)[0]

        self.assertEqual(fact["top_post_ids"], ["high"])
        self.assertEqual(fact["bottom_post_ids"], ["low"])
        self.assertEqual(fact["ratio"], 10.0)

    def test_records_each_chain_transition(self):
        rows = [
            {"chain_id": "chain", "post_kind": "parent", "views": 100},
            {"chain_id": "chain", "post_kind": "reply_1", "views": 80},
            {"chain_id": "chain", "post_kind": "reply_2", "views": 40},
            {"chain_id": "chain", "post_kind": "final_reply", "views": 20},
        ]

        facts = {
            row["metric"]: row["value"]
            for row in threads_analyze.chain_facts(rows)
        }

        self.assertEqual(facts["reply_1_view_ratio"], 0.8)
        self.assertEqual(facts["reply_2_view_ratio_from_reply_1"], 0.5)
        self.assertEqual(facts["final_reply_view_ratio_from_reply_2"], 0.5)
        self.assertEqual(facts["final_reply_view_ratio_from_parent"], 0.2)

    def test_requires_minimum_sample_before_finding(self):
        rows = [
            {"views": 100, "hook_type": "共感", "id": str(index)}
            for index in range(4)
        ]

        self.assertEqual(threads_analyze.dimension_findings(rows), [])

    def test_finds_repeatable_high_lift_pattern(self):
        rows = []
        for index in range(5):
            rows.append({
                "id": f"high-{index}",
                "views": 300,
                "hook_type": "具体的な状況",
            })
        for index in range(5):
            rows.append({
                "id": f"base-{index}",
                "views": 100,
                "hook_type": "抽象的な共感",
            })

        findings = threads_analyze.dimension_findings(rows)

        self.assertTrue(any(
            row["field"] == "hook_type"
            and row["value"] == "具体的な状況"
            and row["lift"] > 1
            for row in findings
        ))


if __name__ == "__main__":
    unittest.main()

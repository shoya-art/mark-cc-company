import importlib.util
import sys
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "threads_post.py"
SPEC = importlib.util.spec_from_file_location("threads_post", SCRIPT_PATH)
threads_post = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = threads_post
SPEC.loader.exec_module(threads_post)


class ThreadsPostTests(unittest.TestCase):
    def test_strategy_mode_is_deterministic(self):
        now = datetime(2026, 7, 3, tzinfo=timezone.utc)
        first = threads_post.choose_strategy_mode("morning", now)
        second = threads_post.choose_strategy_mode("morning", now)

        self.assertEqual(first, second)
        self.assertIn(first, {"exploit", "explore"})

    def test_parses_generation_metadata(self):
        response = """
---TOPIC---
ブロック後の復縁
---TOPIC_END---
---HYPOTHESIS---
具体的な状況ほど自分事化される
---HYPOTHESIS_END---
---VARIABLE_CHANGED---
親投稿の具体性
---VARIABLE_CHANGED_END---
"""

        metadata = threads_post.parse_generation_metadata(response)

        self.assertEqual(metadata["topic"], "ブロック後の復縁")
        self.assertEqual(metadata["variable_changed"], "親投稿の具体性")

    def test_builds_post_database_payload(self):
        payload = threads_post._post_db_payload(
            post_id="thread-1",
            body="本文",
            post_kind="parent",
            posting_mode="chain",
            time_slot="morning",
            quality_score=9.0,
            header_type="B1",
            metadata={"topic": "冷却期間", "hypothesis": "表示数が伸びる"},
            details={
                "timestamp": "2026-07-03T00:00:00+0000",
                "permalink": "https://www.threads.com/test",
                "username": "ziro_fukuen_pro",
            },
            chain_id="chain-1",
        )

        self.assertEqual(payload["threads_post_id"], "thread-1")
        self.assertEqual(payload["topic"], "冷却期間")
        self.assertEqual(payload["chain_id"], "chain-1")
        self.assertEqual(payload["generation_metadata"]["source_post_id"], "B1")

    def test_parse_cli_args_supports_chain_mode(self):
        self.assertEqual(
            threads_post.parse_cli_args(["chain", "lunch", "/repo"]),
            ("chain", "lunch", "/repo"),
        )

    def test_parse_cli_args_keeps_old_format_as_legacy(self):
        self.assertEqual(
            threads_post.parse_cli_args(["evening", "/repo"]),
            ("legacy", "evening", "/repo"),
        )

    def test_parse_cli_args_rejects_unknown_slot(self):
        with self.assertRaises(threads_post.ConfigurationError):
            threads_post.parse_cli_args(["chain", "midnight", "."])

    def test_extracts_and_validates_four_sections(self):
        response = """
---PARENT_START---
親投稿
---PARENT_END---
---REPLY_ONE_START---
返信1
---REPLY_ONE_END---
---REPLY_TWO_START---
返信2
---REPLY_TWO_END---
---FINAL_REPLY_START---
最終返信
---FINAL_REPLY_END---
"""
        texts = [
            threads_post.extract_section(response, "PARENT"),
            threads_post.extract_section(response, "REPLY_ONE"),
            threads_post.extract_section(response, "REPLY_TWO"),
            threads_post.extract_section(response, "FINAL_REPLY"),
        ]

        threads_post.validate_chain_texts(texts)
        self.assertEqual(texts, ["親投稿", "返信1", "返信2", "最終返信"])

    def test_extracts_metadata_markers_without_start_suffix(self):
        response = """
---QUALITY_STATUS---
PASS
---QUALITY_STATUS_END---
---SCORE---
9.1
---SCORE_END---
---HEADER_TYPE---
B1
---HEADER_TYPE_END---
"""

        status = threads_post.extract_section(response, "QUALITY_STATUS")
        score, header_type = threads_post.parse_score_and_header(response)

        self.assertEqual(status, "PASS")
        self.assertEqual(score, 9.1)
        self.assertEqual(header_type, "B1")
        threads_post.validate_quality_gate(status, score)

    def test_rejects_text_over_threads_limit(self):
        texts = ["親投稿", "返信1", "返信2", "あ" * 501]

        with self.assertRaisesRegex(ValueError, "上限を超えています"):
            threads_post.validate_chain_texts(texts)

    def test_rejects_line_over_mobile_limit(self):
        texts = [
            "でも、実は…↓",
            "あ" * 23 + "↓",
            "必要になるのが…↓",
            "最後まで完結します。",
        ]

        with self.assertRaisesRegex(ValueError, "行目が長すぎます"):
            threads_post.validate_chain_structure(texts)

    def test_rejects_block_over_three_lines(self):
        texts = [
            "一行目\n二行目\n三行目\nでも、実は…↓",
            "復縁を遠ざける行動が…↓",
            "必要になるのが…↓",
            "最後まで完結します。",
        ]

        with self.assertRaisesRegex(ValueError, "4行以上"):
            threads_post.validate_chain_structure(texts)

    def test_rejects_chain_without_unfinished_cut(self):
        texts = [
            "でも、実は…↓",
            "復縁を遠ざける行動があります。",
            "必要になるのが…↓",
            "最後まで完結します。",
        ]

        with self.assertRaisesRegex(ValueError, "追いコメント①"):
            threads_post.validate_chain_structure(texts)

    def test_accepts_complete_cut_structure(self):
        texts = [
            "でも、実は…↓",
            "復縁を遠ざける行動が…↓",
            "必要になるのが…↓",
            "最後まで完結します。",
        ]

        threads_post.validate_chain_structure(texts)

    def test_quality_gate_rejects_non_pass_status(self):
        with self.assertRaisesRegex(ValueError, "PASSではない"):
            threads_post.validate_quality_gate("REVISE", 9.0)

    def test_quality_gate_rejects_low_score(self):
        with self.assertRaisesRegex(ValueError, "8.5点未満"):
            threads_post.validate_quality_gate("PASS", 8.4)

    def test_quality_gate_accepts_pass_at_threshold(self):
        threads_post.validate_quality_gate("pass", 8.5)

    @mock.patch.object(threads_post.time, "sleep")
    @mock.patch.object(threads_post, "threads_api_request")
    def test_post_to_threads_sends_reply_to_id(self, api_request, _sleep):
        api_request.side_effect = [{"id": "container-1"}, {"id": "published-1"}]

        post_id = threads_post.post_to_threads(
            "返信本文",
            "user-1",
            "secret-token",
            reply_to_id="parent-1",
        )

        self.assertEqual(post_id, "published-1")
        create_payload = urllib.parse.parse_qs(api_request.call_args_list[0].args[1].decode())
        self.assertEqual(create_payload["reply_to_id"], ["parent-1"])
        self.assertEqual(create_payload["text"], ["返信本文"])

    @mock.patch.object(threads_post, "post_to_threads")
    def test_publish_chain_resumes_and_links_to_previous_post(self, post_to_threads):
        post_to_threads.side_effect = ["reply-1", "reply-2", "reply-final"]
        state = {
            "texts": ["parent", "one", "two", "final"],
            "published_ids": ["parent-id"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            published_ids = threads_post.publish_chain(
                state,
                "user-1",
                "secret-token",
                repo_root=temp_dir,
            )
            saved = threads_post.load_chain_state(temp_dir)

        self.assertEqual(
            published_ids,
            ["parent-id", "reply-1", "reply-2", "reply-final"],
        )
        self.assertEqual(saved["published_ids"], published_ids)
        self.assertEqual(
            [call.kwargs["reply_to_id"] for call in post_to_threads.call_args_list],
            ["parent-id", "reply-1", "reply-2"],
        )

    @mock.patch.object(threads_post, "post_to_threads")
    def test_parent_has_no_reply_to_id(self, post_to_threads):
        post_to_threads.side_effect = ["parent-id", "reply-1", "reply-2", "reply-final"]
        state = {
            "texts": ["parent", "one", "two", "final"],
            "published_ids": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            threads_post.publish_chain(
                state,
                "user-1",
                "secret-token",
                repo_root=temp_dir,
            )

        self.assertIsNone(post_to_threads.call_args_list[0].kwargs["reply_to_id"])

    @mock.patch.object(threads_post, "post_to_threads")
    def test_partial_failure_keeps_last_published_id_for_resume(self, post_to_threads):
        post_to_threads.side_effect = ["parent-id", threads_post.ThreadsAPIError("failed")]
        state = {
            "texts": ["parent", "one", "two", "final"],
            "published_ids": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(threads_post.ThreadsAPIError):
                threads_post.publish_chain(
                    state,
                    "user-1",
                    "secret-token",
                    repo_root=temp_dir,
                )
            saved = threads_post.load_chain_state(temp_dir)

        self.assertEqual(saved["published_ids"], ["parent-id"])

    def test_legacy_and_chain_logs_are_separate(self):
        chain_texts = ["parent", "one", "two", "final"]
        post_ids = ["p", "r1", "r2", "rf"]

        with tempfile.TemporaryDirectory() as temp_dir:
            threads_post.append_legacy_to_log(
                "legacy post", 8.0, "A1", "legacy-id", "morning", temp_dir
            )
            threads_post.append_chain_to_log(
                chain_texts, 9.0, "B1", post_ids, "morning", temp_dir
            )
            content_plan = Path(temp_dir) / ".company" / "marketing" / "content-plan"
            legacy_log = (content_plan / "threads-log.md").read_text(encoding="utf-8")
            chain_log = (content_plan / "threads-chain-log.md").read_text(encoding="utf-8")

        self.assertIn("legacy post", legacy_log)
        self.assertNotIn("parent", legacy_log)
        self.assertIn("parent", chain_log)
        self.assertNotIn("legacy post", chain_log)


if __name__ == "__main__":
    unittest.main()

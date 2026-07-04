import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "threads_post_report.py"
SPEC = importlib.util.spec_from_file_location("threads_post_report", SCRIPT_PATH)
threads_post_report = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = threads_post_report
SPEC.loader.exec_module(threads_post_report)


class ThreadsPostReportTests(unittest.TestCase):
    def test_prefers_same_format_and_time_slot_for_baseline(self):
        records = [{
            "id": f"same-{index}",
            "published_at": f"2026-07-0{index + 1}T00:00:00+00:00",
            "post_kind": "parent",
            "time_slot": "morning",
        } for index in range(5)]
        records.append({
            "id": "other",
            "published_at": "2026-07-01T01:00:00+00:00",
            "post_kind": "single",
            "time_slot": "evening",
        })
        current = {
            "id": "current",
            "published_at": "2026-07-10T00:00:00+00:00",
            "post_kind": "parent",
            "time_slot": "morning",
        }

        baseline = threads_post_report.select_baseline(records, current)

        self.assertEqual(len(baseline), 5)
        self.assertTrue(all(row["id"].startswith("same-") for row in baseline))

    def test_classifies_against_past_median(self):
        self.assertEqual(
            threads_post_report.performance_label(130, 100)[0],
            "伸びた",
        )
        self.assertEqual(
            threads_post_report.performance_label(100, 100)[0],
            "平均的",
        )
        self.assertEqual(
            threads_post_report.performance_label(75, 100)[0],
            "平均的",
        )
        self.assertEqual(
            threads_post_report.performance_label(70, 100)[0],
            "伸びていない",
        )

    def test_formats_requested_four_sections(self):
        current = {
            "body": "復縁したい。でも連絡するのが怖い…↓",
            "published_at": "2026-07-04T00:00:00+00:00",
            "collected_at": "2026-07-05T02:00:00+00:00",
            "permalink": "https://threads.net/post/1",
            "views": 1300,
            "likes": 80,
            "replies": 12,
            "reposts": 5,
            "quotes": 2,
            "shares": 7,
        }
        baseline = {
            "views": 1000,
            "likes": 60,
            "replies": 10,
            "reposts": 4,
            "quotes": 1,
            "shares": 5,
        }
        plan = {
            "result_summary": "過去中央値を上回りました。",
            "reason_hypothesis": "具体的な迷いへの共感が届いた可能性があります。",
            "keep": "冒頭の具体的な葛藤",
            "change": "追いコメント①の長さだけ短くする",
            "next_post_plan": "彼に連絡したい夜の葛藤を扱う投稿",
        }

        message = threads_post_report.format_report(
            current, baseline, 20, "伸びた", 1.3, plan
        )

        self.assertIn("■ 投稿した内容", message)
        self.assertIn("■ 投稿から24時間後のデータ", message)
        self.assertIn("計測時点：投稿から26.0時間", message)
        self.assertIn("いいね：80", message)
        self.assertIn("保存：Threads APIでは取得対象外", message)
        self.assertIn("■ 過去20投稿との比較", message)
        self.assertIn("総合判定：伸びた", message)
        self.assertIn("今回の結果：過去中央値を上回りました。", message)
        self.assertNotIn("■ 今回の見立て", message)
        self.assertIn("■ 次の投稿方針", message)
        self.assertIn("次に出す投稿：", message)


if __name__ == "__main__":
    unittest.main()

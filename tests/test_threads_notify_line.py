import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "threads_notify_line.py"
SPEC = importlib.util.spec_from_file_location("threads_notify_line", SCRIPT_PATH)
threads_notify_line = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = threads_notify_line
SPEC.loader.exec_module(threads_notify_line)


class ThreadsNotifyLineTests(unittest.TestCase):
    def test_sends_message_to_relay_without_line_credentials(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(
            threads_notify_line.urllib.request,
            "urlopen",
            return_value=Response(),
        ) as urlopen:
            threads_notify_line.send_relay_message(
                "分析結果",
                "https://example.supabase.co/functions/v1/notify-threads-analysis",
                "shared-secret",
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-threads-notify-secret"), "shared-secret")
        self.assertNotIn("LINE", request.get_header("X-threads-notify-secret"))

    def test_formats_decision_ready_analysis(self):
        message = threads_notify_line.format_analysis_message({
            "created_at": "2026-07-04T02:30:00+00:00",
            "posts_analyzed": 12,
            "summary": "具体的な迷いを示した投稿が上位でした。",
            "facts": [
                {
                    "metric": "top_bottom_views_contrast",
                    "top_median_views": 1280,
                    "bottom_median_views": 190,
                    "ratio": 6.7368,
                },
                {"metric": "reply_1_view_ratio", "value": 0.81},
                {"metric": "reply_2_view_ratio_from_reply_1", "value": 0.42},
            ],
            "problems": [{"problem": "追いコメント①が長い可能性があります。"}],
            "hypotheses": [{"hypothesis": "結論まで遠く、②へ進まれていない可能性があります。"}],
            "next_tests": [{
                "variable": "追いコメント①の文字数",
                "test": "説明を一段落減らします。",
                "target_metric": "reply_2_view_ratio",
            }],
        })

        self.assertIn("上位中央値：1,280表示", message)
        self.assertIn("差：6.7倍", message)
        self.assertIn("①→②：42%", message)
        self.assertIn("変更するもの：追いコメント①の文字数", message)
        self.assertIn("原因は検証中の仮説", message)

    def test_does_not_exceed_line_text_limit(self):
        message = threads_notify_line.format_analysis_message({
            "summary": "あ" * 6000,
            "facts": [],
            "problems": [],
            "hypotheses": [],
            "next_tests": [],
        })

        self.assertLessEqual(len(message), threads_notify_line.LINE_TEXT_LIMIT)


if __name__ == "__main__":
    unittest.main()

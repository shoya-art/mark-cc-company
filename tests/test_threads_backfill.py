import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "threads_backfill.py"
SPEC = importlib.util.spec_from_file_location("threads_backfill", SCRIPT_PATH)
threads_backfill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = threads_backfill
SPEC.loader.exec_module(threads_backfill)


class ThreadsBackfillTests(unittest.TestCase):
    def test_parses_legacy_log(self):
        content = """# Threads投稿ログ

## 2026-07-03 12:00

**投稿内容:**
本文です。

**タグ:** #A1 #lunch
**品質スコア:** 8.5 / 10
**投稿ID:** post-1

---
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "threads-log.md"
            path.write_text(content, encoding="utf-8")
            records = threads_backfill.parse_legacy_log(path)

        self.assertEqual(records[0]["threads_post_id"], "post-1")
        self.assertEqual(records[0]["body"], "本文です。")
        self.assertEqual(records[0]["time_slot"], "lunch")

    def test_parses_chain_as_four_linked_records(self):
        content = """# Threads投稿チェーンログ

## 2026-07-03 15:29

**親投稿:**
親です…↓

**追いコメント①:**
一です…↓

**追いコメント②:**
二です…↓

**最終コメント:**
最後です。

**タグ:** #D3 #lunch
**品質スコア:** 9.0 / 10
**親投稿ID:** p1
**追いコメント① ID:** r1
**追いコメント② ID:** r2
**最終コメントID:** rf

---
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "threads-chain-log.md"
            path.write_text(content, encoding="utf-8")
            chains = threads_backfill.parse_chain_log(path)

        self.assertEqual(len(chains[0]), 4)
        self.assertEqual(
            [row["post_kind"] for row in chains[0]],
            ["parent", "reply_1", "reply_2", "final_reply"],
        )
        self.assertEqual(len({row["chain_id"] for row in chains[0]}), 1)


if __name__ == "__main__":
    unittest.main()

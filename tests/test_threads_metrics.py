import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "threads_metrics.py"
SPEC = importlib.util.spec_from_file_location("threads_metrics", SCRIPT_PATH)
threads_metrics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = threads_metrics
SPEC.loader.exec_module(threads_metrics)


class ThreadsMetricsTests(unittest.TestCase):
    def test_returns_only_window_currently_due(self):
        self.assertEqual(threads_metrics.due_windows(25, set()), ["24h"])
        self.assertEqual(threads_metrics.due_windows(75, set()), ["72h"])
        self.assertEqual(threads_metrics.due_windows(170, set()), ["7d"])

    def test_does_not_duplicate_existing_window(self):
        self.assertEqual(threads_metrics.due_windows(25, {"24h"}), [])

    def test_does_not_backfill_expired_window_with_late_data(self):
        self.assertEqual(threads_metrics.due_windows(100, set()), [])


if __name__ == "__main__":
    unittest.main()

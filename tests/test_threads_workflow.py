import unittest
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).parents[1] / ".github" / "workflows" / "threads-auto-post.yml"
)
INSIGHTS_WORKFLOW_PATH = (
    Path(__file__).parents[1] / ".github" / "workflows" / "threads-insights.yml"
)
LEARNING_WORKFLOW_PATH = (
    Path(__file__).parents[1] / ".github" / "workflows" / "threads-learning.yml"
)


class ThreadsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_contains_five_daily_schedules(self):
        for cron in (
            "'0 21 * * *'",
            "'0 22 * * *'",
            "'0 11 * * *'",
            "'0 12 * * *'",
            "'0 13 * * *'",
        ):
            self.assertIn(f"cron: {cron}", self.workflow)

    def test_scheduled_posts_are_chains(self):
        self.assertEqual(self.workflow.count("- cron:"), 5)
        self.assertNotIn('echo "mode=legacy"', self.workflow)
        self.assertNotIn('echo "slot=lunch"', self.workflow)

    def test_passes_mode_and_slot_to_script(self):
        self.assertIn(
            "threads_post.py ${{ steps.posting.outputs.mode }} "
            "${{ steps.posting.outputs.slot }} .",
            self.workflow,
        )

    def test_passes_supabase_secrets(self):
        self.assertIn("THREADS_SUPABASE_URL", self.workflow)
        self.assertIn("THREADS_SUPABASE_SECRET_KEY", self.workflow)

    def test_no_longer_commits_runtime_logs_to_main(self):
        self.assertNotIn("git push", self.workflow)

    def test_insights_and_learning_workflows_exist(self):
        insights = INSIGHTS_WORKFLOW_PATH.read_text(encoding="utf-8")
        learning = LEARNING_WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("python scripts/threads_backfill.py --limit 25", insights)
        self.assertIn("python scripts/threads_metrics.py", insights)
        self.assertIn("python scripts/threads_post_report.py", insights)
        self.assertIn("python scripts/threads_analyze.py", learning)
        self.assertNotIn("python scripts/threads_notify_line.py", learning)
        self.assertIn("THREADS_LINE_NOTIFY_URL", insights)
        self.assertIn("THREADS_LINE_NOTIFY_SECRET", insights)


if __name__ == "__main__":
    unittest.main()

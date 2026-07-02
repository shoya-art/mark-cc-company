import unittest
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).parents[1] / ".github" / "workflows" / "threads-auto-post.yml"
)


class ThreadsWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_contains_three_chain_schedules(self):
        for cron in (
            "'0 22 * * 0-4'",
            "'0 3 * * 1-5'",
            "'0 12 * * 1-5'",
        ):
            self.assertIn(f"cron: {cron}", self.workflow)

    def test_keeps_three_legacy_schedules(self):
        for cron in (
            "'50 22 * * 0-4'",
            "'20 3 * * 1-5'",
            "'30 12 * * 1-5'",
        ):
            self.assertIn(f"cron: {cron}", self.workflow)

    def test_passes_mode_and_slot_to_script(self):
        self.assertIn(
            "threads_post.py ${{ steps.posting.outputs.mode }} "
            "${{ steps.posting.outputs.slot }} .",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()

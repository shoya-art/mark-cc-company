import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "threads_data.py"
SPEC = importlib.util.spec_from_file_location("threads_data", SCRIPT_PATH)
threads_data = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = threads_data
SPEC.loader.exec_module(threads_data)


class ThreadsDataTests(unittest.TestCase):
    def test_new_secret_key_is_not_sent_as_bearer(self):
        client = threads_data.SupabaseClient(
            "https://example.supabase.co", "sb_secret_example"
        )
        headers = client._headers()

        self.assertEqual(headers["apikey"], "sb_secret_example")
        self.assertNotIn("Authorization", headers)

    def test_legacy_service_role_key_is_sent_as_bearer(self):
        client = threads_data.SupabaseClient(
            "https://example.supabase.co", "legacy-jwt"
        )
        headers = client._headers()

        self.assertEqual(headers["Authorization"], "Bearer legacy-jwt")


if __name__ == "__main__":
    unittest.main()

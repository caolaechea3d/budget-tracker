import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expense_tracker import paths


class DataLocationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_dir = Path(self.tmp.name) / "Budget Tracker"
        self.app_dir.mkdir()
        env = {k: v for k, v in os.environ.items() if k != "BUDGET_TRACKER_DATA"}
        env["APPDATA"] = str(Path(self.tmp.name) / "Roaming")
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def frozen(self):
        return mock.patch.multiple(sys, frozen=True, executable=str(self.app_dir / "Budget Tracker.exe"), create=True)

    def test_from_source_uses_project_data_folder(self):
        self.assertFalse(paths.is_frozen())
        self.assertEqual(paths.data_dir(), paths.PROJECT_ROOT / "data")

    def test_installed_uses_appdata(self):
        with self.frozen():
            self.assertFalse(paths.is_portable())
            self.assertEqual(paths.data_dir(), Path(self.tmp.name) / "Roaming" / "Budget Tracker" / "data")

    def test_portable_keeps_data_next_to_exe(self):
        (self.app_dir / paths.PORTABLE_MARKER).write_text("portable", encoding="utf-8")
        with self.frozen():
            self.assertTrue(paths.is_portable())
            self.assertEqual(paths.data_dir(), self.app_dir.resolve() / "data")
            self.assertEqual(paths.log_file(), self.app_dir.resolve() / "data" / "logs" / "errors.log")

    def test_error_log(self):
        from expense_tracker.gui import errors
        os.environ["BUDGET_TRACKER_DATA"] = str(Path(self.tmp.name) / "data")
        try:
            raise ZeroDivisionError("boom")
        except ZeroDivisionError:
            path = errors.write_log(*sys.exc_info())
        self.assertEqual(path, Path(self.tmp.name) / "data" / "logs" / "errors.log")
        text = path.read_text(encoding="utf-8")
        self.assertIn("ZeroDivisionError: boom", text)
        self.assertIn("Traceback", text)

    def test_environment_override_wins(self):
        os.environ["BUDGET_TRACKER_DATA"] = str(Path(self.tmp.name) / "elsewhere")
        with self.frozen():
            self.assertEqual(paths.data_dir(), Path(self.tmp.name) / "elsewhere")


if __name__ == "__main__":
    unittest.main()

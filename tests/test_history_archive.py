import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import history_archive


class HistoryArchiveTests(unittest.TestCase):
    def test_sections_merge_and_index_lists_dates_without_touching_old_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            history_dir = root / "history"
            index = history_dir / "index.json"
            history_dir.mkdir()
            old = history_dir / "2026-06-23.json"
            old.write_text('{"date":"2026-06-23","sentinel":"keep"}\n', encoding="utf-8")
            old_before = old.read_bytes()

            with (
                patch.object(history_archive, "HISTORY_DIR", history_dir),
                patch.object(history_archive, "INDEX", index),
            ):
                history_archive.update_history("2026-06-24", "clients", {"count": 2})
                history_archive.update_history("2026-06-24", "social", {"count": 3})

            archive = json.loads((history_dir / "2026-06-24.json").read_text(encoding="utf-8"))
            listing = json.loads(index.read_text(encoding="utf-8"))
            self.assertEqual(archive["clients"]["count"], 2)
            self.assertEqual(archive["social"]["count"], 3)
            self.assertEqual(old.read_bytes(), old_before)
            self.assertEqual(listing["dates"], ["2026-06-24", "2026-06-23"])


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import scraper


class DailyReportTests(unittest.TestCase):
    def test_recent_history_rolls_up_seven_days_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            history = pathlib.Path(folder)
            first = {
                "clients": {"clients": [{
                    "client": "Fix Price",
                    "new_items": [{"id": "p1"}, {"id": "p2"}],
                }]},
                "social": {"channels": [{
                    "client": "Sela Home", "platform": "telegram",
                    "new_posts": [{"id": "t1"}],
                }]},
            }
            second = {
                "clients": {"clients": [{
                    "client": "Fix Price", "new_items": [{"id": "p2"}],
                }]},
                "weekly": {"social": {"channels": [{
                    "client": "Sela Home", "platform": "telegram",
                    "new_posts": [{"id": "t2"}],
                }]}},
            }
            (history / "2026-06-20.json").write_text(json.dumps(first), encoding="utf-8")
            (history / "2026-06-24.json").write_text(json.dumps(second), encoding="utf-8")
            with patch.object(scraper, "HISTORY_DIR", history):
                lines, counts = scraper._recent_history_section(dt.date(2026, 6, 24))
        report = "\n".join(lines)
        self.assertEqual(counts, {"client_7d": 2, "social_7d": 2})
        self.assertIn("近7天累计", report)
        self.assertIn("2026-06-18 至 2026-06-24", report)

    def test_zero_customer_signals_never_push(self):
        self.assertFalse(scraper._should_push({"client_new": 0, "social_new": 0, "wb_new": 99}))
        self.assertTrue(scraper._should_push({"client_new": 1, "social_new": 0, "wb_new": 0}))

    def test_zero_signal_run_updates_panel_files_without_calling_push(self):
        counts = {
            "client_new": 0, "social_new": 0, "wb_new": 12,
            "client_7d": 3, "social_7d": 4,
        }
        with tempfile.TemporaryDirectory() as folder:
            data_dir = pathlib.Path(folder)
            snapshot = data_dir / "snapshot.json"
            snapshot.write_text("{}", encoding="utf-8")
            with (
                patch.object(scraper, "DATA_DIR", data_dir),
                patch.object(scraper, "SNAPSHOT", snapshot),
                patch.object(scraper, "build_report", return_value=("日报正文\n", {}, counts)),
                patch.object(scraper, "push_all") as push,
                patch.object(scraper, "update_history"),
            ):
                status = scraper.run_report(refresh_wb=False, allow_push=True)
            push.assert_not_called()
            self.assertFalse(status["pushed"])
            self.assertEqual(status["total_new"], 0)
            self.assertEqual((data_dir / "latest_report.md").read_text(encoding="utf-8"), "日报正文\n")
            saved = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["customer_signal_new"], 0)


if __name__ == "__main__":
    unittest.main()

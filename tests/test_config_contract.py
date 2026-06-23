import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import client_tracker
import scraper
import social_tracker


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ConfigContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "keywords.json").read_text(encoding="utf-8"))

    def test_new_categories_and_client_profiles_are_preserved(self):
        self.assertEqual(len(self.config["categories"]), 21)
        groups = self.config["meta"]["groups"]
        for category in self.config["categories"]:
            self.assertTrue({"cn", "ru", "kw", "group"} <= category.keys())
            self.assertIn(category["group"], groups)
        for client in self.config["clients"]:
            self.assertTrue(
                {"price_band", "aesthetic", "focus", "responsibility"} <= client.keys()
            )

    def test_tracked_client_sources_match_tracker_contract(self):
        required = {
            "fix_price_api": {"url", "api_url", "city_id", "page_size"},
            "sela_html": {"url", "max_pages"},
        }
        for client in self.config["clients"]:
            settings = client.get("new_arrivals") or {}
            if settings.get("track") is not True:
                continue
            source = settings.get("source")
            self.assertIn(source, client_tracker.FETCHERS)
            self.assertTrue(required[source] <= settings.keys())

    def test_social_channels_are_plain_names_not_urls(self):
        for client in self.config["clients"]:
            social = client.get("social") or {}
            for platform in ("telegram", "vk"):
                channel = str(social.get(platform) or "")
                self.assertFalse(channel.startswith(("http://", "https://", "@")))

    def test_tracked_client_without_channels_is_reported(self):
        fixture = {
            "clients": [{
                "name": "X5 · Перекрёсток",
                "social": {"track": True, "telegram": "", "vk": ""},
            }]
        }
        with tempfile.TemporaryDirectory() as folder:
            temp = pathlib.Path(folder)
            config = temp / "keywords.json"
            snapshot = temp / "social_snapshot.json"
            latest = temp / "social_latest.json"
            config.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(social_tracker, "CONFIG", config),
                patch.object(social_tracker, "SNAPSHOT", snapshot),
                patch.object(social_tracker, "LATEST", latest),
            ):
                result = social_tracker.run()
        entry = result["channels"][0]
        self.assertEqual(entry["client"], "X5 · Перекрёсток")
        self.assertIn("尚未配置", entry["error"])
        lines, _ = scraper._social_section(result)
        self.assertIn("### X5 · Перекрёсток · 未配置", lines)


if __name__ == "__main__":
    unittest.main()

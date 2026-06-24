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
            "perekrestok_api": {"url", "api_url", "category_titles"},
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

    def test_x5_official_telegram_and_quality_note_are_configured(self):
        x5 = next(client for client in self.config["clients"] if client["name"].startswith("X5"))
        self.assertEqual(x5["social"]["telegram"], "perekrestok_store")
        self.assertTrue(x5["social"]["track"])
        self.assertTrue(x5["new_arrivals"]["track"])
        self.assertIn("装饰品类占比低", x5["new_arrivals"]["quality_note"])

    def test_global_blacklist_and_numeric_price_bands_are_configured(self):
        blacklist = self.config["meta"]["exclude_name_keywords_ru"]
        self.assertIn("тряпка", blacklist)
        self.assertIn("салфетки бумажные", blacklist)
        self.assertIn("подгузник", blacklist)
        for name in ("Fix Price", "Sela Home", "X5 · Перекрёсток"):
            client = next(item for item in self.config["clients"] if item["name"] == name)
            self.assertRegex(client["price_band"], r"\d+\s*[–—-]\s*\d+\s*₽")

    def test_fix_price_uses_keyword_recheck_and_child_content_blacklist(self):
        fix_price = next(client for client in self.config["clients"] if client["name"] == "Fix Price")
        settings = fix_price["new_arrivals"]
        self.assertTrue(settings["require_decor_keyword_for_allowed_path"])
        blacklist = settings["exclude_name_keywords_ru"]
        for phrase in ("наклейка", "стикер", "игрушка", "игра", "военная техника", "раскраска"):
            self.assertIn(phrase, blacklist)
        self.assertIn("набор шаров с насосом", settings["decor_name_keywords"])

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
                patch.object(social_tracker, "update_history"),
            ):
                result = social_tracker.run()
        entry = result["channels"][0]
        self.assertEqual(entry["client"], "X5 · Перекрёсток")
        self.assertIn("尚未配置", entry["error"])
        lines, _ = scraper._social_section(result)
        self.assertIn("### X5 · Перекрёсток · 未配置", lines)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

import scraper


def product(product_id):
    return {
        "id": product_id,
        "name": "Ваза декоративная",
        "brand": "Test",
        "price": 399,
        "rating": 5,
        "feedbacks": 10,
        "url": f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx",
    }


class RateLimitedResponse:
    status_code = 429


class FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return RateLimitedResponse()


class WildberriesCacheTests(unittest.TestCase):
    def test_429_uses_dated_cache_and_opens_run_circuit(self):
        dest = "-1257786"
        first_keyword = "ваза декоративная"
        second_keyword = "свеча декоративная"
        disk_cache = {
            f"{dest}|{scraper._normalized(first_keyword)}": {
                "checked": "2026-06-22",
                "products": [product(1), product(2), product(3)],
            },
            f"{dest}|{scraper._normalized(second_keyword)}": {
                "checked": "2026-06-21",
                "products": [product(4), product(5), product(6)],
            },
        }
        session = FakeSession()
        with (
            patch.object(scraper, "WB_SESSION", session),
            patch.object(scraper, "_WB_DISK_CACHE", disk_cache),
            patch.object(scraper, "_WB_PRODUCTS_CACHE", {}),
            patch.object(scraper, "_WB_RESULT_META", {}),
            patch.object(scraper, "_WB_RATE_LIMITED", False),
            patch.object(scraper.time, "sleep", lambda _: None),
        ):
            first = scraper.wb_search(first_keyword, "popular", dest, 3)
            calls_after_first = session.calls
            second = scraper.wb_search(second_keyword, "popular", dest, 3)
            with self.assertRaisesRegex(RuntimeError, "无可用缓存"):
                scraper.wb_search("无缓存品类", "popular", dest, 3)
            first_meta = scraper._WB_RESULT_META[(scraper._normalized(first_keyword), dest)]
            second_meta = scraper._WB_RESULT_META[(scraper._normalized(second_keyword), dest)]

        self.assertEqual(len(first), 3)
        self.assertEqual(len(second), 3)
        self.assertEqual(calls_after_first, 2)
        self.assertEqual(session.calls, calls_after_first)
        self.assertTrue(first_meta["cached"])
        self.assertEqual(first_meta["cache_date"], "2026-06-22")
        self.assertIn("429", second_meta["reason"])


if __name__ == "__main__":
    unittest.main()

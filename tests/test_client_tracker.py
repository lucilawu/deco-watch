import unittest
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from client_tracker import _perekrestok_products, filter_decor_products
from scraper import _client_section


CATEGORIES = [
    {"kw": "ваза керамическая декоративная"},
    {"kw": "свеча ароматическая"},
    {"kw": "светильник интерьерный"},
    {"kw": "корзина декоративная для хранения"},
    {"kw": "праздничный декор"},
    {"kw": "салфетка сервировочная"},
]

SETTINGS = {
    "decor_path_allow": ["/dekor-dlya-doma-", "/vazy/", "/svechi/"],
    "decor_path_deny": ["/kantstovary/", "/bytovaya-khimiya/"],
    "decor_path_keyword_fallback": ["/dlya-doma/", "/suveniry-i-podarki/"],
}


class DecorFilteringTests(unittest.TestCase):
    def test_explicit_decor_path_is_kept(self):
        products = [{"name": "Набор шаров", "path": "/catalog/dekor-dlya-doma-tovary-dlya-prazdnika/item"}]
        kept, filtered = filter_decor_products(products, SETTINGS, CATEGORIES)
        self.assertEqual(kept, products)
        self.assertEqual(filtered, 0)

    def test_explicit_irrelevant_path_wins_over_keyword(self):
        products = [{"name": "Тетрадь с декоративной обложкой", "path": "/catalog/kantstovary/item"}]
        kept, filtered = filter_decor_products(products, SETTINGS, CATEGORIES)
        self.assertEqual(kept, [])
        self.assertEqual(filtered, 1)

    def test_broad_home_path_rejects_cleaning_rag(self):
        products = [{"name": "Тряпка для уборки", "path": "/catalog/dlya-doma/item"}]
        kept, filtered = filter_decor_products(products, SETTINGS, CATEGORIES)
        self.assertEqual(kept, [])
        self.assertEqual(filtered, 1)

    def test_broad_home_path_rejects_plain_storage_container(self):
        products = [{"name": "Контейнер для хранения с крышкой", "path": "/catalog/dlya-doma/item"}]
        kept, filtered = filter_decor_products(products, SETTINGS, CATEGORIES)
        self.assertEqual(kept, [])
        self.assertEqual(filtered, 1)

    def test_broad_home_path_rejects_cleaning_and_paper_napkins(self):
        products = [
            {"name": "Салфетки универсальные для уборки", "path": "/catalog/dlya-doma/item"},
            {"name": "Салфетки бумажные 250 шт.", "path": "/catalog/dlya-doma/item2"},
            {"name": "Салфетка сервировочная на стол", "path": "/catalog/dlya-doma/item3"},
        ]
        kept, filtered = filter_decor_products(products, SETTINGS, CATEGORIES)
        self.assertEqual([item["name"] for item in kept], ["Салфетка сервировочная на стол"])
        self.assertEqual(filtered, 2)

    def test_missing_category_uses_keywords(self):
        products = [{"name": "Ваза керамическая", "category": "未分类"}]
        kept, filtered = filter_decor_products(products, SETTINGS, CATEGORIES)
        self.assertEqual(kept, products)
        self.assertEqual(filtered, 0)

    def test_broad_gift_path_uses_fuzzy_decor_root(self):
        products = [{"name": "Настольная декорация Магия песка", "path": "/catalog/suveniry-i-podarki/item"}]
        kept, filtered = filter_decor_products(products, SETTINGS, CATEGORIES)
        self.assertEqual(kept, products)
        self.assertEqual(filtered, 0)

    def test_report_shows_filter_count_only(self):
        lines, total = _client_section({
            "clients": [{
                "client": "Fix Price",
                "url": "https://fix-price.com/catalog/novinki",
                "baseline": False,
                "new_count": 1,
                "new_items": [{
                    "id": "1", "name": "Ваза", "price": 299,
                    "url": "https://fix-price.com/catalog/vazy/1", "category": "Декор",
                }],
                "filtered_count": 18,
                "error": None,
            }]
        })
        report = "\n".join(lines)
        self.assertEqual(total, 1)
        self.assertIn("Ваза", report)
        self.assertIn("另有 18 件非装饰品类已过滤。", report)
        self.assertNotIn("Тряпка", report)

    def test_perekrestok_payload_uses_category_before_keyword_fallback(self):
        payload = {
            "content": {"items": [{
                "category": {"id": 45, "title": "Декор и интерьер"},
                "products": [{
                    "id": 100,
                    "title": "Ваза стеклянная",
                    "masterData": {"plu": "4000100", "slug": "vaza-steklannaa"},
                    "primaryCategory": {"id": 45, "title": "Декор и интерьер", "slug": "dekor-i-interer"},
                    "priceTag": {"price": 39999},
                }],
            }]}
        }
        products = _perekrestok_products(payload, "Для дома и дачи")
        settings = {
            "decor_path_allow": ["декор и интерьер"],
            "decor_path_deny": [],
            "decor_path_keyword_fallback": ["для дома и дачи"],
        }
        kept, filtered = filter_decor_products(products, settings, CATEGORIES)
        self.assertEqual(len(kept), 1)
        self.assertEqual(filtered, 0)
        self.assertEqual(kept[0]["price"], 399.99)
        self.assertIn("/cat/45/p/vaza-steklannaa-4000100", kept[0]["url"])


if __name__ == "__main__":
    unittest.main()

import unittest
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from client_tracker import filter_decor_products
from scraper import _client_section


CATEGORIES = [
    {"kw": "ваза керамическая декоративная"},
    {"kw": "свеча ароматическая"},
    {"kw": "светильник интерьерный"},
    {"kw": "корзина декоративная для хранения"},
    {"kw": "праздничный декор"},
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


if __name__ == "__main__":
    unittest.main()

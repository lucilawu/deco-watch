#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户官网上新追踪。所有客户、数据源和开关均来自 keywords.json。"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import html
import json
import pathlib
import re
import sys
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from history_archive import update_history


ROOT = pathlib.Path(__file__).parent
CONFIG = ROOT / "keywords.json"
DATA_DIR = ROOT / "data"
SNAPSHOT = DATA_DIR / "client_snapshot.json"
LATEST = DATA_DIR / "client_latest.json"
PEREKRESTOK_CACHE = DATA_DIR / "perekrestok_products_cache.json"
SOURCE_META: dict[str, dict[str, Any]] = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
}

RU_STOP_WORDS = {"в", "для", "и", "из", "на", "по", "с"}
UNKNOWN_CATEGORIES = {"", "未分类", "uncategorized", "без категории"}
RU_AMBIGUOUS_QUALIFIERS = {"салфетк": {"сервировочн"}}
RU_SUFFIXES = (
    "ическими", "ический", "ическая", "ические", "ического",
    "ениями", "енный", "енная", "енные", "ового", "овая", "овые",
    "иями", "ами", "ями", "ого", "ему", "ому", "ыми", "ими",
    "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой",
    "ам", "ям", "ах", "ях", "ов", "ев", "ом", "ем", "ами",
    "а", "я", "ы", "и", "у", "ю", "е", "о",
)


def read_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _number(value: Any) -> float | int | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return int(result) if result.is_integer() else round(result, 2)


def _normalize_words(value: Any) -> list[str]:
    text = str(value or "").casefold().replace("ё", "е")
    return re.findall(r"[a-zа-я0-9]+", text)


def _russian_root(word: str) -> str:
    if word.startswith("декор"):
        return "декор"
    for suffix in RU_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _word_roots(value: Any) -> set[str]:
    return {
        _russian_root(word)
        for word in _normalize_words(value)
        if word not in RU_STOP_WORDS and len(word) >= 4
    }


def _root_matches(left: str, right: str) -> bool:
    return left == right or (min(len(left), len(right)) >= 5 and (left in right or right in left))


def _phrase_matches(text: Any, phrase: Any) -> bool:
    text_roots = _word_roots(text)
    phrase_roots = _word_roots(phrase)
    return bool(phrase_roots) and all(
        any(_root_matches(expected, actual) for actual in text_roots)
        for expected in phrase_roots
    )


def _matches_any_phrase(text: Any, phrases: list[Any]) -> bool:
    return any(_phrase_matches(text, phrase) for phrase in phrases if phrase)


def keyword_roots(categories: list[dict[str, Any]]) -> set[str]:
    """提取每个搜索短语的品类核心词，并保留“装饰”这一通用强信号。"""
    roots: set[str] = set()
    for category in categories:
        words = [
            word for word in _normalize_words(category.get("kw"))
            if word not in RU_STOP_WORDS and len(word) >= 4
        ]
        if words:
            roots.add(_russian_root(words[0]))
        if any(word.startswith("декор") for word in words):
            roots.add("декор")
    return roots


def _matches_decor_keywords(product: dict[str, Any], roots: set[str]) -> bool:
    product_roots = _word_roots(f"{product.get('name', '')} {product.get('category', '')}")
    for left in roots:
        matched = any(
            left == right or (len(left) >= 5 and (left in right or right in left))
            for right in product_roots
        )
        if not matched:
            continue
        qualifiers = RU_AMBIGUOUS_QUALIFIERS.get(left)
        if qualifiers and not any(
            qualifier == right or qualifier in right or right in qualifier
            for qualifier in qualifiers
            for right in product_roots
        ):
            continue
        return True
    return False


def filter_decor_products(
    products: list[dict[str, Any]],
    settings: dict[str, Any],
    categories: list[dict[str, Any]],
    exclude_keywords: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """商品名排除词优先；其后才按分类/路径和装饰关键词判断。"""
    allow = [str(value).casefold() for value in settings.get("decor_path_allow", [])]
    deny = [str(value).casefold() for value in settings.get("decor_path_deny", [])]
    keyword_fallback = [
        str(value).casefold() for value in settings.get("decor_path_keyword_fallback", [])
    ]
    supplemental = [{"kw": value} for value in settings.get("decor_name_keywords", [])]
    roots = keyword_roots(categories + supplemental)
    name_excludes = list(exclude_keywords or []) + list(
        settings.get("exclude_name_keywords_ru", [])
    )
    kept: list[dict[str, Any]] = []

    for product in products:
        if _matches_any_phrase(product.get("name", ""), name_excludes):
            continue
        path = unquote(str(product.get("path") or "")).casefold()
        category = str(product.get("category") or "").casefold().strip()
        if category in UNKNOWN_CATEGORIES:
            category = ""
        classification = f"{path} {category}".strip()

        if classification and any(fragment in classification for fragment in deny):
            accepted = False
        elif classification and any(fragment in classification for fragment in allow):
            accepted = True
        elif not classification or any(fragment in classification for fragment in keyword_fallback):
            accepted = _matches_decor_keywords(product, roots)
        else:
            accepted = False

        if accepted:
            kept.append(product)

    return kept, len(products) - len(kept)


def _price_range(price_band: Any) -> tuple[float, float] | None:
    if isinstance(price_band, dict):
        low = price_band.get("min_rub", price_band.get("min"))
        high = price_band.get("max_rub", price_band.get("max"))
        try:
            return float(low), float(high)
        except (TypeError, ValueError):
            return None
    text = str(price_band or "").replace(" ", " ")
    match = re.search(r"(\d[\d ]*)\s*[–—-]\s*(\d[\d ]*)\s*(?:₽|руб|rub)", text, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(" ", "")), float(match.group(2).replace(" ", ""))


def annotate_and_rank_products(
    products: list[dict[str, Any]],
    client: dict[str, Any],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    price_range = _price_range(client.get("price_band"))
    focus = set(client.get("focus") or [])
    focus_keywords = (cfg.get("meta") or {}).get("focus_match_keywords") or {}

    ranked: list[dict[str, Any]] = []
    for position, original in enumerate(products):
        product = dict(original)
        price = product.get("price")
        price_match = False
        if price_range and isinstance(price, (int, float)):
            price_match = price_range[0] <= float(price) <= price_range[1]
        haystack = f"{product.get('name', '')} {product.get('category', '')} {product.get('path', '')}"
        focus_match = any(
            _matches_any_phrase(haystack, list(focus_keywords.get(group) or []))
            for group in focus
        )
        tags = []
        if price_match:
            tags.append("🎯 价位匹配")
        if focus_match:
            tags.append("✨ 品类对口")
        product["price_match"] = price_match
        product["focus_match"] = focus_match
        product["match_tags"] = tags
        product["_rank"] = (int(price_match) + int(focus_match), -position)
        ranked.append(product)

    ranked.sort(key=lambda item: item["_rank"], reverse=True)
    for product in ranked:
        product.pop("_rank", None)
    return ranked


def fetch_fix_price(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """调用 Fix Price 前端实际使用的 buyer/v1/product/in/novinki。"""
    api_url = settings["api_url"]
    catalog_url = settings["url"]
    page_size = int(settings.get("page_size", 100))
    session = curl_requests.Session(impersonate="chrome")
    headers = {
        "Accept": "application/json",
        "Accept-Language": HEADERS["Accept-Language"],
        "Content-Type": "application/json",
        "Origin": "https://fix-price.com",
        "Referer": catalog_url,
        "x-language": "ru",
        "x-city": str(settings.get("city_id", "55")),
    }
    body = {"category": "novinki", "brand": [], "price": [], "isDividedPrice": False}
    products: list[dict[str, Any]] = []
    page = 1
    total: int | None = None

    seen_ids: set[str] = set()
    while total is None or len(seen_ids) < total:
        params = {
            "page": page,
            "limit": page_size,
            "sort": "sold",
            "location": catalog_url,
            "referer": catalog_url,
        }
        response = session.post(api_url, params=params, json=body, headers=headers, timeout=40)
        response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("result", [])
        if total is None:
            total = int(response.headers.get("x-count") or len(rows))
        if not rows:
            break

        before = len(seen_ids)
        for row in rows:
            pid = str(row.get("id") or row.get("sku") or "").strip()
            title = str(row.get("title") or "").strip()
            relative_url = str(row.get("url") or "").lstrip("/")
            if not pid or not title or not relative_url:
                continue
            seen_ids.add(pid)
            category = row.get("category") or {}
            products.append(
                {
                    "id": pid,
                    "name": title,
                    "price": _number(row.get("price") or row.get("minPrice")),
                    "url": urljoin("https://fix-price.com/catalog/", relative_url),
                    "category": str(category.get("title") or "未分类"),
                    "path": f"/catalog/{relative_url}",
                }
            )
        # 该接口目前会把 limit=100 截成约 28 条，不能用 page_size 判断末页。
        if len(seen_ids) == before:
            break
        page += 1

    return _dedupe(products)


def _sela_category(product_url: str, fallback: str) -> str:
    parts = [part for part in urlparse(product_url).path.split("/") if part]
    try:
        home_index = parts.index("home")
        taxonomy = parts[home_index + 1 : -1]
    except ValueError:
        taxonomy = []
    return " / ".join(taxonomy) or fallback or "未分类"


def _parse_sela_page(text: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(text, "html.parser")
    products: list[dict[str, Any]] = []
    for card in soup.select(".product-thumb[data-p]"):
        try:
            row = json.loads(html.unescape(card.get("data-p", "")))
        except (TypeError, json.JSONDecodeError):
            continue
        link = card.select_one("a.product-thumb_lnk[href]")
        product_url = urljoin(base_url, link.get("href")) if link else ""
        pid = str(row.get("id") or row.get("url") or "").strip()
        title = str(row.get("name") or "").strip()
        if not pid or not title or not product_url:
            continue
        products.append(
            {
                "id": pid,
                "name": title,
                "price": _number(row.get("price")),
                "url": product_url,
                "category": _sela_category(product_url, str(row.get("category") or "")),
                "path": urlparse(product_url).path,
            }
        )
    return products


def _get_sela_page(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=40)
    response.raise_for_status()
    return response.text


def fetch_sela(settings: dict[str, Any]) -> list[dict[str, Any]]:
    base_url = settings["url"]
    first_text = _get_sela_page(base_url)
    products = _parse_sela_page(first_text, base_url)
    pages = [int(value) for value in re.findall(r"[?&]page=(\d+)", first_text)]
    last_page = min(max(pages, default=1), int(settings.get("max_pages", 100)))

    def fetch_page(page: int) -> list[dict[str, Any]]:
        separator = "&" if "?" in base_url else "?"
        return _parse_sela_page(_get_sela_page(f"{base_url}{separator}page={page}"), base_url)

    if last_page > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for rows in pool.map(fetch_page, range(2, last_page + 1)):
                products.extend(rows)
    return _dedupe(products)


def _perekrestok_category_nodes(
    items: list[dict[str, Any]], targets: set[str]
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for item in items:
        category = item.get("category") or {}
        if str(category.get("title") or "").casefold() in targets:
            matched.append(category)
        matched.extend(_perekrestok_category_nodes(item.get("children") or [], targets))
    return matched


def _perekrestok_products(payload: dict[str, Any], parent_title: str) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for group in (payload.get("content") or {}).get("items") or []:
        group_category = group.get("category") or group.get("group") or {}
        group_title = str(group_category.get("title") or "").strip()
        for row in group.get("products") or []:
            master = row.get("masterData") or {}
            primary = row.get("primaryCategory") or row.get("catalogPrimaryCategory") or {}
            product_id = str(master.get("plu") or row.get("id") or "").strip()
            title = str(row.get("title") or "").strip()
            slug = str(master.get("slug") or "").strip()
            category_id = primary.get("id") or group_category.get("id")
            if not product_id or not title or not slug or not category_id:
                continue
            price_kopecks = (row.get("priceTag") or {}).get("price") or row.get("medianPrice")
            category_parts = [parent_title, group_title, str(primary.get("title") or "")]
            category = " / ".join(dict.fromkeys(part for part in category_parts if part))
            products.append(
                {
                    "id": product_id,
                    "name": title,
                    "price": _number(float(price_kopecks) / 100) if price_kopecks else None,
                    "url": (
                        f"https://www.perekrestok.ru/cat/{category_id}/p/"
                        f"{slug}-{product_id}"
                    ),
                    "category": category or "未分类",
                    "path": f"/cat/c/{category_id}/{str(primary.get('slug') or '')}",
                }
            )
    return products


def fetch_perekrestok(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """读取 Перекрёсток 目录树与分类预览；受反爬限制时使用最近成功缓存。"""
    api_url = str(settings.get("api_url") or "").rstrip("/")
    if not api_url:
        raise RuntimeError("缺少 Перекрёсток api_url")
    target_titles = {
        str(value).casefold() for value in settings.get("category_titles", []) if value
    }
    if not target_titles:
        raise RuntimeError("缺少 Перекрёсток category_titles")

    cache = read_json(PEREKRESTOK_CACHE, {})
    session = curl_requests.Session(impersonate="chrome")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": HEADERS["Accept-Language"],
        "Origin": "https://www.perekrestok.ru",
        "Referer": settings["url"],
    }
    try:
        tree_response = session.post(f"{api_url}/catalog/tree", headers=headers, timeout=35)
        if tree_response.status_code == 403:
            raise RuntimeError("目录触发网站人机验证（HTTP 403）")
        tree_response.raise_for_status()
        tree_payload = tree_response.json()
        nodes = _perekrestok_category_nodes(
            (tree_payload.get("content") or {}).get("items") or [], target_titles
        )
        if not nodes:
            raise RuntimeError("目录树中未找到配置的家居分类")

        products: list[dict[str, Any]] = []
        for node in nodes:
            response = session.get(
                f"{api_url}/catalog/category/feed/{node['id']}",
                headers=headers,
                timeout=35,
            )
            response.raise_for_status()
            products.extend(_perekrestok_products(response.json(), str(node.get("title") or "")))
        products = _dedupe(products)
        if not products:
            raise RuntimeError("家居分类返回 0 个商品")
        today = dt.date.today().isoformat()
        write_json(PEREKRESTOK_CACHE, {"checked": today, "products": products})
        SOURCE_META["perekrestok_api"] = {"cached": False, "cache_date": today}
        return products
    except Exception as exc:
        cached_products = cache.get("products") or []
        cache_date = str(cache.get("checked") or "")
        if cached_products:
            SOURCE_META["perekrestok_api"] = {
                "cached": True,
                "cache_date": cache_date,
                "source_warning": f"官网实时目录不可用：{exc}",
            }
            return cached_products
        raise RuntimeError(f"Перекрёсток 官网目录不可用且无缓存：{exc}") from exc


FETCHERS = {
    "fix_price_api": fetch_fix_price,
    "sela_html": fetch_sela,
    "perekrestok_api": fetch_perekrestok,
}


def _dedupe(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for product in products:
        by_id[str(product["id"])] = product
    return list(by_id.values())


def run() -> dict[str, Any]:
    cfg = read_json(CONFIG, {})
    old_snapshot = read_json(SNAPSHOT, {"clients": {}})
    old_clients = old_snapshot.get("clients", {})
    new_clients = dict(old_clients)
    today = dt.date.today().isoformat()
    results: list[dict[str, Any]] = []

    for client in cfg.get("clients", []):
        settings = client.get("new_arrivals") or {}
        if settings.get("track") is not True:
            continue
        name = client.get("name", "未命名客户")
        source = settings.get("source")
        print(f"[client] {name}: {source}")
        try:
            fetcher = FETCHERS[source]
            fetched_products = fetcher(settings)
            if not fetched_products:
                raise RuntimeError("数据源返回 0 个商品，已拒绝覆盖快照")
            products, filtered_count = filter_decor_products(
                fetched_products,
                settings,
                cfg.get("categories", []),
                (cfg.get("meta") or {}).get("exclude_name_keywords_ru", []),
            )
            products = annotate_and_rank_products(products, client, cfg)
            previous = old_clients.get(name, {})
            previous_ids = {str(value) for value in previous.get("ids", [])}
            baseline = not bool(previous_ids)
            new_items = [] if baseline else [p for p in products if p["id"] not in previous_ids]
            new_clients[name] = {
                "ids": [p["id"] for p in products],
                "checked": today,
                "count": len(products),
                "filtered_count": filtered_count,
            }
            results.append(
                {
                    "client": name,
                    "source": source,
                    "url": settings.get("url"),
                    "baseline": baseline,
                    "total": len(products),
                    "fetched_total": len(fetched_products),
                    "filtered_count": filtered_count,
                    "new_count": len(new_items),
                    "new_items": new_items,
                    "sample": products[:8],
                    "quality_note": settings.get("quality_note"),
                    "decor_ratio": round(len(products) / len(fetched_products), 4),
                    **SOURCE_META.get(str(source), {}),
                    "error": None,
                }
            )
            print(
                f"  抓到 {len(fetched_products)} 件；保留装饰 {len(products)} 件；"
                f"过滤 {filtered_count} 件；新增 {len(new_items)} 件"
            )
        except Exception as exc:
            results.append(
                {
                    "client": name,
                    "source": source,
                    "url": settings.get("url"),
                    "baseline": False,
                    "total": 0,
                    "fetched_total": 0,
                    "filtered_count": 0,
                    "new_count": 0,
                    "new_items": [],
                    "sample": [],
                    "quality_note": settings.get("quality_note"),
                    "error": str(exc),
                }
            )
            print(f"  [warn] {exc}")

    output = {"date": today, "clients": results}
    write_json(SNAPSHOT, {"clients": new_clients})
    write_json(LATEST, output)
    update_history(today, "clients", output)
    return output


if __name__ == "__main__":
    run()

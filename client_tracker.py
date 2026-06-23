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
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests


ROOT = pathlib.Path(__file__).parent
CONFIG = ROOT / "keywords.json"
DATA_DIR = ROOT / "data"
SNAPSHOT = DATA_DIR / "client_snapshot.json"
LATEST = DATA_DIR / "client_latest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
}


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


FETCHERS = {
    "fix_price_api": fetch_fix_price,
    "sela_html": fetch_sela,
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
            products = fetcher(settings)
            if not products:
                raise RuntimeError("数据源返回 0 个商品，已拒绝覆盖快照")
            previous = old_clients.get(name, {})
            previous_ids = {str(value) for value in previous.get("ids", [])}
            baseline = not bool(previous_ids)
            new_items = [] if baseline else [p for p in products if p["id"] not in previous_ids]
            new_clients[name] = {
                "ids": [p["id"] for p in products],
                "checked": today,
                "count": len(products),
            }
            results.append(
                {
                    "client": name,
                    "source": source,
                    "url": settings.get("url"),
                    "baseline": baseline,
                    "total": len(products),
                    "new_count": len(new_items),
                    "new_items": new_items,
                    "sample": products[:8],
                    "error": None,
                }
            )
            print(f"  抓到 {len(products)} 件；新增 {len(new_items)} 件")
        except Exception as exc:
            results.append(
                {
                    "client": name,
                    "source": source,
                    "url": settings.get("url"),
                    "baseline": False,
                    "total": 0,
                    "new_count": 0,
                    "new_items": [],
                    "sample": [],
                    "error": str(exc),
                }
            )
            print(f"  [warn] {exc}")

    output = {"date": today, "clients": results}
    write_json(SNAPSHOT, {"clients": new_clients})
    write_json(LATEST, output)
    return output


if __name__ == "__main__":
    run()

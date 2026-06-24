#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总客户官网、客户社媒与 Wildberries 大盘，生成并推送中文周报。"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
from typing import Any

import requests


ROOT = pathlib.Path(__file__).parent
CONFIG = ROOT / "keywords.json"
DATA_DIR = ROOT / "data"
SNAPSHOT = DATA_DIR / "snapshot.json"
CLIENT_LATEST = DATA_DIR / "client_latest.json"
SOCIAL_LATEST = DATA_DIR / "social_latest.json"

# 这是 Wildberries 网页当前实际调用的 v18 搜索后端。
WB_API = "https://search.wb.ru/exactmatch/ru/common/v18/search"
WB_PARAMS_BASE = {
    "ab_testing": "false",
    "appType": "1",
    "curr": "rub",
    "hide_dtype": "15",
    "hide_vflags": "4294967296",
    "inheritFilters": "false",
    "lang": "ru",
    "locale": "ru",
    "page": "1",
    "resultset": "catalog",
    "spp": "30",
    "suppressSpellcheck": "false",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    "Origin": "https://www.wildberries.ru",
    "Referer": "https://www.wildberries.ru/",
}
WB_SESSION = requests.Session()


def read_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict[str, Any]:
    cfg = read_json(CONFIG, {})
    cfg.setdefault("meta", {})
    cfg["meta"].setdefault("top_n_per_keyword", 10)
    cfg["meta"].setdefault("dest_region", "-1257786")
    return cfg


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return " ".join(re.findall(r"[\w-]+", text, flags=re.UNICODE))


def _is_relevant(keyword: str, product: dict[str, Any]) -> bool:
    haystack = _normalized(f"{product.get('name', '')} {product.get('brand', '')}")
    tokens = [token for token in _normalized(keyword).split() if len(token) >= 4]
    return not tokens or any(token in haystack for token in tokens)


def _product_price_kopecks(product: dict[str, Any]) -> float:
    prices = []
    for size in product.get("sizes") or []:
        price = (size.get("price") or {}).get("product")
        if isinstance(price, (int, float)) and price > 0:
            prices.append(price)
    return min(prices) if prices else product.get("salePriceU") or product.get("priceU") or 0


def _wb_search_unvalidated(keyword: str, sort: str, dest: str, top_n: int) -> list[dict[str, Any]]:
    if sort not in {"newly", "popular"}:
        raise ValueError(f"不支持的 WB 排序：{sort}")
    params = dict(WB_PARAMS_BASE)
    params.update({"dest": str(dest), "query": keyword, "sort": sort})
    response = None
    for attempt in range(4):
        response = WB_SESSION.get(WB_API, params=params, headers=HEADERS, timeout=35)
        if response.status_code != 429:
            break
        wait_seconds = int(response.headers.get("Retry-After") or 2 ** (attempt + 1))
        time.sleep(min(wait_seconds, 12))
    assert response is not None
    response.raise_for_status()
    payload = response.json()
    normquery = (payload.get("metadata") or {}).get("normquery") or ""
    if not _normalized(normquery):
        raise RuntimeError("WB 返回了空搜索词，已拒绝采用默认热门流")
    rows = payload.get("products")
    if rows is None:
        rows = (payload.get("data") or {}).get("products")

    products: list[dict[str, Any]] = []
    for row in rows or []:
        pid = row.get("id")
        name = str(row.get("name") or "").strip()
        price_kopecks = _product_price_kopecks(row)
        item = {
            "id": pid,
            "name": name,
            "brand": str(row.get("brand") or "").strip(),
            "price": round(price_kopecks / 100),
            "rating": row.get("reviewRating") or row.get("nmReviewRating") or 0,
            "feedbacks": row.get("feedbacks") or row.get("nmFeedbacks") or 0,
            "url": f"https://www.wildberries.ru/catalog/{pid}/detail.aspx",
        }
        if not isinstance(pid, int) or pid <= 0 or not name or price_kopecks <= 0:
            continue
        if not _is_relevant(keyword, item):
            continue
        products.append(item)
        if len(products) >= top_n:
            break
    return products


WB_PRODUCTS_CACHE = DATA_DIR / "wb_products_cache.json"
_WB_PRODUCTS_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}
_WB_DISK_CACHE: dict[str, Any] = read_json(WB_PRODUCTS_CACHE, {})
_WB_RESULT_META: dict[tuple[str, str], dict[str, Any]] = {}
_WB_RATE_LIMITED = False
_WB_LAST_LIVE_REQUEST = 0.0
WB_MIN_REQUEST_INTERVAL = 1.2
WB_RETRY_DELAY = 2.0


def _wb_query_stems(value: Any) -> set[str]:
    stems: set[str] = set()
    for word in _normalized(value).split():
        if len(word) < 4:
            continue
        stems.add(word[:5] if len(word) >= 6 else word[:3])
        if "диффузор" in word:
            stems.add("диффуз")
        if word.startswith("настен"):
            stems.add("стен")
    return stems


def _wb_query_is_effective(keyword: str, normquery: str) -> bool:
    returned = _normalized(normquery)
    stems = _wb_query_stems(keyword)
    return bool(stems) and any(stem in returned for stem in stems)


def _wb_product_is_relevant(keyword: str, product: dict[str, Any]) -> bool:
    haystack = _normalized(f"{product.get('name') or ''} {product.get('brand') or ''}")
    return any(stem in haystack for stem in _wb_query_stems(keyword))


def wb_search(keyword: str, sort: str, dest: str, top_n: int) -> list[dict[str, Any]]:
    """Return validated WB products; rate limits trigger a fast persistent-cache fallback."""
    global _WB_LAST_LIVE_REQUEST, _WB_RATE_LIMITED
    if sort not in {"newly", "popular"}:
        raise ValueError(f"不支持的 WB 排序：{sort}")
    cache_key = (_normalized(keyword), str(dest))
    products = _WB_PRODUCTS_CACHE.get(cache_key)
    disk_key = f"{dest}|{_normalized(keyword)}"
    disk_entry = _WB_DISK_CACHE.get(disk_key) or {}
    cached_products = disk_entry.get("products") or []
    cache_date = str(disk_entry.get("checked") or "日期未知")
    today = dt.date.today().isoformat()

    if products is None and disk_entry.get("checked") == today and cached_products:
        products = cached_products
        _WB_PRODUCTS_CACHE[cache_key] = products
        _WB_RESULT_META[cache_key] = {
            "cached": True,
            "cache_date": cache_date,
            "reason": "复用当天缓存，避免重复请求",
        }
    if products is None and _WB_RATE_LIMITED and cached_products:
        products = cached_products
        _WB_PRODUCTS_CACHE[cache_key] = products
        _WB_RESULT_META[cache_key] = {
            "cached": True,
            "cache_date": cache_date,
            "reason": "WB 本轮已触发 429，跳过后续实时请求",
        }
    if products is None and _WB_RATE_LIMITED:
        raise RuntimeError(f"{keyword} / {sort}：WB 本轮已触发 429，且无可用缓存")

    if products is None:
        params = dict(WB_PARAMS_BASE)
        params.update({"dest": str(dest), "query": keyword, "sort": sort})
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                wait_seconds = WB_MIN_REQUEST_INTERVAL - (time.monotonic() - _WB_LAST_LIVE_REQUEST)
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                _WB_LAST_LIVE_REQUEST = time.monotonic()
                response = WB_SESSION.get(WB_API, params=params, headers=HEADERS, timeout=20)
                if response.status_code == 429:
                    _WB_RATE_LIMITED = True
                    raise RuntimeError("WB 返回 429 Too Many Requests")
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("products")
                if rows is None:
                    rows = (payload.get("data") or {}).get("products")
                if not rows:
                    raise RuntimeError("WB 返回了空商品列表")
                normquery = (payload.get("metadata") or {}).get("normquery") or ""
                if not _wb_query_is_effective(keyword, normquery):
                    raise RuntimeError(f"WB 搜索词未生效（normquery={normquery!r}）")
                mapped: list[dict[str, Any]] = []
                for row in rows:
                    pid = row.get("id")
                    name = str(row.get("name") or "").strip()
                    price_kopecks = _product_price_kopecks(row)
                    if not isinstance(pid, int) or pid <= 0 or not name or price_kopecks <= 0:
                        continue
                    if not _wb_product_is_relevant(keyword, row):
                        continue
                    mapped.append({
                        "id": pid,
                        "name": name,
                        "brand": str(row.get("brand") or "").strip(),
                        "price": round(price_kopecks / 100),
                        "rating": row.get("reviewRating") or row.get("nmReviewRating") or 0,
                        "feedbacks": row.get("feedbacks") or row.get("nmFeedbacks") or 0,
                        "url": f"https://www.wildberries.ru/catalog/{pid}/detail.aspx",
                    })
                if len(mapped) < min(top_n, 3):
                    raise RuntimeError(
                        f"WB 相关商品不足（{len(mapped)} 个），疑似返回默认热门流"
                    )
                products = mapped
                _WB_PRODUCTS_CACHE[cache_key] = products
                _WB_RESULT_META[cache_key] = {
                    "cached": False,
                    "cache_date": today,
                    "reason": "实时接口",
                }
                _WB_DISK_CACHE[disk_key] = {"checked": today, "products": products}
                write_json(WB_PRODUCTS_CACHE, _WB_DISK_CACHE)
                break
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(WB_RETRY_DELAY)

        if products is None and cached_products:
            products = cached_products
            _WB_PRODUCTS_CACHE[cache_key] = products
            _WB_RESULT_META[cache_key] = {
                "cached": True,
                "cache_date": cache_date,
                "reason": f"实时请求失败：{last_error}",
            }
        if products is None:
            raise RuntimeError(f"{keyword} / {sort} 请求失败：{last_error}")
    ordered = products
    if sort == "newly":
        # v18 currently ignores sort=newly; nmId is allocated monotonically.
        ordered = sorted(products, key=lambda product: product["id"], reverse=True)
    return ordered[:top_n]


def fmt_price(value: Any) -> str:
    if value in (None, ""):
        return "价格未标注"
    number = float(value)
    shown = f"{number:,.2f}" if not number.is_integer() else f"{int(number):,}"
    return shown.replace(",", " ") + " ₽"


def _client_section(data: dict[str, Any]) -> tuple[list[str], int]:
    lines = ["## ① 各客户官网上新"]
    total_new = 0
    clients = data.get("clients") or []
    if not clients:
        return lines + ["本期没有启用官网上新追踪的客户。"], 0
    for result in clients:
        name = result.get("client", "未命名客户")
        source_url = result.get("url") or ""
        title = f"### {name}"
        if source_url:
            title += f" · [上新页]({source_url})"
        lines.append(title)
        if result.get("error"):
            lines.append(f"⚠️ 抓取失败：{result['error']}")
            if result.get("quality_note"):
                lines.append(result["quality_note"])
            continue
        total_new += int(result.get("new_count", 0))
        if result.get("baseline"):
            lines.append(f"首次建立基线：当前共 {result.get('total', 0)} 件；下周起显示新增。")
            shown = result.get("sample") or []
            label = "当前真实样本"
        elif result.get("new_count"):
            lines.append(f"本周新增 {result['new_count']} 件（当前上新池 {result.get('total', 0)} 件）。")
            shown = result.get("new_items") or []
            label = "本周新增"
        else:
            lines.append(f"本周未发现新增（当前上新池 {result.get('total', 0)} 件）。")
            shown = result.get("sample") or []
            label = "当前样本"
        lines.append(f"{label}：")
        for product in shown[:12]:
            category = product.get("category") or "未分类"
            lines.append(
                f"- [{product.get('name', '未命名商品')}]({product.get('url')}) · "
                f"{fmt_price(product.get('price'))} · {category} · ID {product.get('id')}"
            )
        filtered_count = int(result.get("filtered_count", 0))
        if filtered_count:
            lines.append(f"另有 {filtered_count} 件非装饰品类已过滤。")
        if result.get("cached"):
            cache_date = result.get("cache_date") or "日期未知"
            lines.append(f"⚠️ 官网实时目录不可用，当前展示缓存（{cache_date}）。")
        if result.get("quality_note"):
            lines.append(result["quality_note"])
    return lines, total_new


def _social_section(data: dict[str, Any]) -> tuple[list[str], int]:
    lines = ["## ② 各客户社媒新品预告"]
    total_new = 0
    channels = data.get("channels") or []
    if not channels:
        return lines + ["本期没有启用社媒追踪的客户。"], 0
    for result in channels:
        platform = str(result.get("platform", "")).upper()
        channel = result.get("channel", "")
        title = f"### {result.get('client', '未命名客户')} · {platform}"
        if channel:
            title += f" · {channel}"
        lines.append(title)
        if result.get("error"):
            lines.append(f"⚠️ {result['error']}")
            continue
        total_new += int(result.get("new_count", 0))
        if result.get("baseline"):
            lines.append(f"首次建立频道基线：读取到最近 {result.get('total', 0)} 帖；下周起显示新帖。")
            shown = result.get("sample") or []
        elif result.get("new_count"):
            lines.append(f"本周新帖 {result['new_count']} 条。")
            shown = result.get("new_posts") or []
        else:
            lines.append("本周未发现新帖；以下为频道当前样本。")
            shown = result.get("sample") or []
        for post in shown[:10]:
            kind = "新品预告" if post.get("is_teaser") else "新帖"
            image_links = post.get("images") or []
            image = f" · [图片]({image_links[0]})" if image_links else ""
            lines.append(f"- **{kind}**：[{post.get('summary', '（无文字）')}]({post.get('url')}){image}")
    return lines, total_new


def _wb_section(cfg: dict[str, Any], snapshot: dict[str, Any]) -> tuple[list[str], dict[str, Any], int]:
    lines = ["## ③（次要）Wildberries 大盘热门"]
    new_snapshot: dict[str, Any] = {}
    total_new = 0
    top_n = int(cfg["meta"]["top_n_per_keyword"])
    dest = str(cfg["meta"]["dest_region"])
    today = dt.date.today().isoformat()

    for category in cfg.get("categories", []):
        keyword = category["kw"]
        name = category["cn"]
        print(f"[wb] {name}: {keyword}")
        try:
            # 快照保存最多 100 个新品，避免只存 Top10 时因榜单轮换制造“伪新增”。
            fresh = wb_search(keyword, "newly", dest, max(top_n, 100))
            hot = wb_search(keyword, "popular", dest, top_n)
        except Exception as exc:
            lines.append(f"### {name}\n⚠️ 抓取失败：{exc}")
            if keyword in snapshot:
                new_snapshot[keyword] = snapshot[keyword]
            continue
        previous_ids = {int(value) for value in snapshot.get(keyword, {}).get("ids", [])}
        result_meta = _WB_RESULT_META.get((_normalized(keyword), dest), {})
        cached = bool(result_meta.get("cached"))
        # 旧版只保存 10 个 ID；首次升级到完整快照时按迁移基线处理。
        baseline = not bool(previous_ids) or len(previous_ids) < 50
        new_items = [] if baseline or cached else [
            product for product in fresh if product["id"] not in previous_ids
        ]
        if cached and keyword in snapshot:
            new_snapshot[keyword] = snapshot[keyword]
        else:
            new_snapshot[keyword] = {"ids": [p["id"] for p in fresh], "checked": today}
        total_new += len(new_items)
        lines.append(f"### {name} · {keyword}")
        if cached:
            cache_date = result_meta.get("cache_date") or "日期未知"
            lines.append(
                f"⚠️ WB 实时接口限流或不可用，使用缓存（{cache_date}）；"
                "缓存数据不计算本周新增。"
            )
        elif baseline:
            lines.append("首次建立 WB 基线；下周起显示新增。")
        else:
            lines.append(f"本周新增 {len(new_items)} 件。")
        for product in new_items[:5]:
            lines.append(f"- [新增｜{product['name'][:60]}]({product['url']}) · {fmt_price(product['price'])}")
        if hot:
            lines.append("当前热门 Top 3：")
            for product in hot[:3]:
                feedbacks = f"{product['feedbacks']} 评" if product["feedbacks"] else "暂无评价"
                lines.append(
                    f"- [{product['name'][:60]}]({product['url']}) · "
                    f"{fmt_price(product['price'])} · {feedbacks}"
                )
    return lines, new_snapshot, total_new


def build_report(cfg: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, int]]:
    client_lines, client_new = _client_section(read_json(CLIENT_LATEST, {}))
    social_lines, social_new = _social_section(read_json(SOCIAL_LATEST, {}))
    wb_lines, new_snapshot, wb_new = _wb_section(cfg, snapshot)
    today = dt.date.today().isoformat()
    counts = {"client_new": client_new, "social_new": social_new, "wb_new": wb_new}
    summary = (
        f"客户官网新增 **{client_new}** 件，客户社媒新帖 **{social_new}** 条，"
        f"WB 关键词新增 **{wb_new}** 件。客户信号优先，WB 仅作大盘参考。"
    )
    report = "\n\n".join(
        [f"# Deco 客户上新与社媒周报 · {today}", summary, "\n".join(client_lines), "\n".join(social_lines), "\n".join(wb_lines)]
    )
    return report + "\n", new_snapshot, counts


def push_serverchan(title: str, content: str) -> bool:
    key = os.environ.get("SERVERCHAN_KEY", "").strip()
    if not key:
        return False
    try:
        response = requests.post(
            f"https://sctapi.ftqq.com/{key}.send",
            data={"title": title, "desp": content},
            timeout=20,
        )
        return response.ok
    except requests.RequestException:
        return False


def push_wecom(title: str, content: str) -> bool:
    url = os.environ.get("WECOM_WEBHOOK", "").strip()
    if not url:
        return False
    try:
        response = requests.post(
            url,
            json={"msgtype": "markdown", "markdown": {"content": f"**{title}**\n\n{content[:3500]}"}},
            timeout=20,
        )
        return response.ok
    except requests.RequestException:
        return False


def push_feishu(title: str, content: str) -> bool:
    url = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not url:
        return False
    try:
        response = requests.post(
            url,
            json={"msg_type": "text", "content": {"text": f"{title}\n\n{content[:3500]}"}},
            timeout=20,
        )
        return response.ok
    except requests.RequestException:
        return False


def push_bark(title: str, content: str) -> bool:
    base = os.environ.get("BARK_URL", "").strip().rstrip("/")
    if not base:
        return False
    try:
        response = requests.post(
            base,
            json={"title": title, "body": content[:500], "group": "DecoWatch"},
            timeout=20,
        )
        return response.ok
    except requests.RequestException:
        return False


def push_all(title: str, content: str) -> dict[str, bool]:
    """沿用原有四通道冗余推送；配置了哪个 Secret 就推哪个。"""
    results = {
        "serverchan": push_serverchan(title, content),
        "wecom": push_wecom(title, content),
        "feishu": push_feishu(title, content),
        "bark": push_bark(title, content),
    }
    sent = [name for name, ok in results.items() if ok]
    print(f"[push] 成功通道：{', '.join(sent)}" if sent else "[info] 未配置可用推送通道")
    return results


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = load_config()
    snapshot = read_json(SNAPSHOT, {})
    report, new_snapshot, counts = build_report(cfg, snapshot)
    today = dt.date.today().isoformat()
    title = f"Deco 客户上新与社媒周报 {today}"
    print(report)
    push_all(title, report)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_json(SNAPSHOT, new_snapshot)
    (DATA_DIR / "latest_report.md").write_text(report, encoding="utf-8")
    status = {
        "date": today,
        "total_new": sum(counts.values()),
        "title": title,
        "report": "data/latest_report.md",
        **counts,
    }
    write_json(DATA_DIR / "status.json", status)
    print("[done] 已写入 snapshot / latest_report.md / status.json")


if __name__ == "__main__":
    main()

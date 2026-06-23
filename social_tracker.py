#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户社媒公开帖追踪：Telegram 无 token，VK 使用官方 wall.get。"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
from typing import Any

import requests
from bs4 import BeautifulSoup


ROOT = pathlib.Path(__file__).parent
CONFIG = ROOT / "keywords.json"
DATA_DIR = ROOT / "data"
SNAPSHOT = DATA_DIR / "social_snapshot.json"
LATEST = DATA_DIR / "social_latest.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
}
TEASER_WORDS = re.compile(
    r"\b(новинк\w*|скоро|анонс\w*|коллекци\w*|поступлени\w*|скоро в продаж)\b",
    re.IGNORECASE,
)


def read_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _summary(text: str, limit: int = 280) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def fetch_telegram(channel: str) -> list[dict[str, Any]]:
    response = requests.get(f"https://t.me/s/{channel}", headers=HEADERS, timeout=40)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    posts: list[dict[str, Any]] = []
    for wrapper in soup.select(".tgme_widget_message_wrap"):
        message = wrapper.select_one(".tgme_widget_message[data-post]")
        if not message:
            continue
        post_key = str(message.get("data-post") or "")
        post_id = post_key.rsplit("/", 1)[-1]
        date_link = wrapper.select_one("a.tgme_widget_message_date[href]")
        url = date_link.get("href") if date_link else f"https://t.me/{post_key}"
        text_node = wrapper.select_one(".tgme_widget_message_text")
        text = text_node.get_text(" ", strip=True) if text_node else "（图片帖/无文字）"
        images: list[str] = []
        for photo in wrapper.select(".tgme_widget_message_photo_wrap"):
            style = str(photo.get("style") or "")
            match = re.search(r"background-image\s*:\s*url\(['\"]?([^'\")]+)", style)
            if match:
                images.append(match.group(1))
        time_node = wrapper.select_one("time[datetime]")
        posts.append(
            {
                "id": post_id,
                "summary": _summary(text),
                "images": list(dict.fromkeys(images)),
                "url": url,
                "published": time_node.get("datetime") if time_node else None,
                "is_teaser": bool(TEASER_WORDS.search(text)),
            }
        )
    if not posts:
        raise RuntimeError(f"Telegram @{channel} 未解析到公开帖")
    return posts


def _vk_photo_url(photo: dict[str, Any]) -> str | None:
    sizes = photo.get("sizes") or []
    if not sizes:
        return None
    best = max(sizes, key=lambda item: int(item.get("width", 0)) * int(item.get("height", 0)))
    return best.get("url")


def fetch_vk(domain: str, token: str) -> list[dict[str, Any]]:
    if not token:
        raise RuntimeError("缺少 VK_TOKEN；Telegram 仍会正常追踪")
    response = requests.get(
        "https://api.vk.com/method/wall.get",
        params={"domain": domain, "count": 30, "access_token": token, "v": "5.199"},
        headers=HEADERS,
        timeout=40,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("error_msg", "VK API 返回错误"))
    posts: list[dict[str, Any]] = []
    for row in (payload.get("response") or {}).get("items", []):
        if row.get("is_pinned"):
            # 置顶旧帖会一直出现在首位，id 快照仍能处理；保留即可。
            pass
        owner_id = row.get("owner_id")
        post_id = row.get("id")
        if owner_id is None or post_id is None:
            continue
        images = []
        for attachment in row.get("attachments") or []:
            if attachment.get("type") == "photo":
                image = _vk_photo_url(attachment.get("photo") or {})
                if image:
                    images.append(image)
        text = str(row.get("text") or "（图片帖/无文字）")
        posts.append(
            {
                "id": str(post_id),
                "summary": _summary(text),
                "images": images,
                "url": f"https://vk.com/wall{owner_id}_{post_id}",
                "published": dt.datetime.fromtimestamp(
                    int(row.get("date", 0)), tz=dt.timezone.utc
                ).isoformat(),
                "is_teaser": bool(TEASER_WORDS.search(text)),
            }
        )
    if not posts:
        raise RuntimeError(f"VK {domain} 未返回公开帖")
    return posts


def run() -> dict[str, Any]:
    cfg = read_json(CONFIG, {})
    old_snapshot = read_json(SNAPSHOT, {"channels": {}})
    old_channels = old_snapshot.get("channels", {})
    new_channels = dict(old_channels)
    token = os.environ.get("VK_TOKEN", "").strip()
    today = dt.date.today().isoformat()
    results: list[dict[str, Any]] = []

    for client in cfg.get("clients", []):
        social = client.get("social") or {}
        if social.get("track") is not True:
            continue
        client_name = client.get("name", "未命名客户")
        configured_channels = [
            platform for platform in ("telegram", "vk")
            if str(social.get(platform) or "").strip()
        ]
        if not configured_channels:
            results.append(
                {
                    "client": client_name,
                    "platform": "未配置",
                    "channel": "",
                    "baseline": False,
                    "total": 0,
                    "new_count": 0,
                    "new_posts": [],
                    "sample": [],
                    "error": "social.track 已开启，但尚未配置公开 Telegram/VK 频道",
                }
            )
            print(f"[social] {client_name}: 已启用，但未配置公开频道")
            continue
        for platform in ("telegram", "vk"):
            channel = str(social.get(platform) or "").strip().lstrip("@")
            if not channel:
                continue
            key = f"{platform}:{channel}"
            print(f"[social] {client_name} / {platform} / {channel}")
            try:
                posts = fetch_telegram(channel) if platform == "telegram" else fetch_vk(channel, token)
                previous_ids = {str(value) for value in old_channels.get(key, {}).get("ids", [])}
                baseline = not bool(previous_ids)
                new_posts = [] if baseline else [post for post in posts if post["id"] not in previous_ids]
                new_channels[key] = {
                    "client": client_name,
                    "platform": platform,
                    "channel": channel,
                    "ids": [post["id"] for post in posts],
                    "checked": today,
                }
                results.append(
                    {
                        "client": client_name,
                        "platform": platform,
                        "channel": channel,
                        "baseline": baseline,
                        "total": len(posts),
                        "new_count": len(new_posts),
                        "new_posts": new_posts,
                        "sample": posts[-5:][::-1],
                        "error": None,
                    }
                )
                print(f"  抓到 {len(posts)} 帖；新增 {len(new_posts)} 帖")
            except Exception as exc:
                results.append(
                    {
                        "client": client_name,
                        "platform": platform,
                        "channel": channel,
                        "baseline": False,
                        "total": 0,
                        "new_count": 0,
                        "new_posts": [],
                        "sample": [],
                        "error": str(exc),
                    }
                )
                print(f"  [warn] {exc}")

    output = {"date": today, "channels": results}
    write_json(SNAPSHOT, {"channels": new_channels})
    write_json(LATEST, output)
    return output


if __name__ == "__main__":
    run()

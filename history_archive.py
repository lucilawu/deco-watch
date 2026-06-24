#!/usr/bin/env python3
"""按日期保存结构化监测数据，并维护历史日期索引。"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).parent
HISTORY_DIR = ROOT / "data" / "history"
INDEX = HISTORY_DIR / "index.json"


def _read(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _signal_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("url") or item.get("name") or "")


def _merge_signal_section(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    collection: str,
    new_items_key: str,
    identity_fields: tuple[str, ...],
) -> dict[str, Any]:
    """同一天重复运行时保留此前已发现的新增，避免 7 天累计被后一次 0 新增覆盖。"""
    old_entries = existing.get(collection) or []
    new_entries = incoming.get(collection) or []
    by_identity = {
        tuple(str(entry.get(field) or "") for field in identity_fields): dict(entry)
        for entry in old_entries
    }
    order = list(by_identity)
    for entry in new_entries:
        identity = tuple(str(entry.get(field) or "") for field in identity_fields)
        previous = by_identity.get(identity, {})
        merged = {**previous, **entry}
        unique: dict[str, dict[str, Any]] = {}
        for item in list(previous.get(new_items_key) or []) + list(entry.get(new_items_key) or []):
            unique[_signal_id(item)] = item
        merged[new_items_key] = list(unique.values())
        merged["new_count"] = len(merged[new_items_key])
        by_identity[identity] = merged
        if identity not in order:
            order.append(identity)
    return {**existing, **incoming, collection: [by_identity[key] for key in order]}


def update_history(date: str, section: str, payload: Any) -> pathlib.Path:
    """更新当日归档的一个结构化区块；其他日期和已有区块保持不变。"""
    archive_path = HISTORY_DIR / f"{date}.json"
    archive = _read(archive_path, {"date": date})
    archive["date"] = date
    if section == "clients" and isinstance(payload, dict):
        payload = _merge_signal_section(
            archive.get(section) or {}, payload, "clients", "new_items", ("client", "source")
        )
    elif section == "social" and isinstance(payload, dict):
        payload = _merge_signal_section(
            archive.get(section) or {}, payload, "channels", "new_posts",
            ("client", "platform", "channel"),
        )
    archive[section] = payload
    archive["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _write(archive_path, archive)

    dates = sorted(
        (
            path.stem
            for path in HISTORY_DIR.glob("????-??-??.json")
            if path.stem != "index"
        ),
        reverse=True,
    )
    _write(
        INDEX,
        {
            "dates": dates,
            "items": [
                {"date": item, "file": f"data/history/{item}.json"} for item in dates
            ],
        },
    )
    return archive_path

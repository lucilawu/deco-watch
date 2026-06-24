#!/usr/bin/env python3
"""按日期保存结构化周报数据，并维护历史日期索引。"""

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


def update_history(date: str, section: str, payload: Any) -> pathlib.Path:
    """更新当日归档的一个结构化区块；其他日期和已有区块保持不变。"""
    archive_path = HISTORY_DIR / f"{date}.json"
    archive = _read(archive_path, {"date": date})
    archive["date"] = date
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

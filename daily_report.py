#!/usr/bin/env python3
"""生成每日客户信号报告；复用最近一次周度 WB 结果，不请求 WB 接口。"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from scraper import run_report


if __name__ == "__main__":
    run_report(refresh_wb=False, allow_push=True)

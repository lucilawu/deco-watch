#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deco 新品巡查 · 每周爬虫
- 读取 keywords.json 的 categories
- 对每个俄文关键词抓 Wildberries 的「新品」与「热销」Top N
- 与上周快照 data/snapshot.json 对比，找出本周新出现的 SKU 和热门榜
- 生成中文周报，推送到 Server酱（微信），并写回新快照

注意：
- Wildberries 的 search.wb.ru 接口参数会变动。失效时把仓库地址发给 Codex，
  让它更新 WB_API / 字段映射即可（这正是 Codex 擅长维护的部分）。
- Ozon 反爬较强，未在此脚本抓取；如需 Ozon 数据，建议用官方 API 或 headless 方案，
  可让 Codex 单独加一个 ozon.py 模块。
"""

import os, json, time, html, datetime, pathlib, urllib.parse
import requests

ROOT = pathlib.Path(__file__).parent
CONFIG = ROOT / "keywords.json"
SNAPSHOT = ROOT / "data" / "snapshot.json"

WB_API = "https://search.wb.ru/exactmatch/ru/common/v9/search"
WB_PARAMS_BASE = {
    "ab_testing": "false",
    "appType": "1",
    "curr": "rub",
    "lang": "ru",
    "resultset": "catalog",
    "spp": "30",
    "suppressSpellcheck": "false",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://www.wildberries.ru",
    "Referer": "https://www.wildberries.ru/",
}

def load_config():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    cfg.setdefault("meta", {})
    cfg["meta"].setdefault("top_n_per_keyword", 10)
    cfg["meta"].setdefault("dest_region", "-1257786")
    return cfg

def load_snapshot():
    if SNAPSHOT.exists():
        try:
            return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def wb_search(keyword, sort, dest, top_n):
    """sort: 'newly'(新品) | 'popular'(热销)。返回精简后的产品列表。"""
    params = dict(WB_PARAMS_BASE)
    params.update({"dest": dest, "query": keyword, "sort": sort})
    url = WB_API + "?" + urllib.parse.urlencode(params, safe="-")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [warn] {keyword} / {sort} 请求失败: {e}")
        return []
    products = (data.get("data") or {}).get("products") or []
    out = []
    for p in products[:top_n]:
        pid = p.get("id")
        if pid is None:
            continue
        # 价格字段在不同版本里可能是 salePriceU / sizes[0].price.product，做兼容
        price_kop = p.get("salePriceU")
        if price_kop is None:
            try:
                price_kop = p["sizes"][0]["price"]["product"]
            except Exception:
                price_kop = 0
        out.append({
            "id": pid,
            "name": (p.get("name") or "").strip(),
            "brand": (p.get("brand") or "").strip(),
            "price": round((price_kop or 0) / 100),
            "rating": p.get("reviewRating") or p.get("rating") or 0,
            "feedbacks": p.get("feedbacks") or 0,
            "url": f"https://www.wildberries.ru/catalog/{pid}/detail.aspx",
        })
    return out

def fmt_price(v):
    return f"{v:,}".replace(",", " ") + " ₽"

def build_report(cfg, snapshot):
    top_n = cfg["meta"]["top_n_per_keyword"]
    dest = str(cfg["meta"]["dest_region"])
    today = datetime.date.today().isoformat()
    new_snapshot = {}
    lines = [f"# Deco 新品周报 · {today}\n"]
    total_new = 0

    for cat in cfg["categories"]:
        kw = cat["kw"]
        cn = cat["cn"]
        print(f"[{cn}] {kw}")
        fresh = wb_search(kw, "newly", dest, top_n)
        time.sleep(1.2)
        hot = wb_search(kw, "popular", dest, top_n)
        time.sleep(1.2)

        prev_ids = set(snapshot.get(kw, {}).get("ids", []))
        cur_ids = [p["id"] for p in fresh]
        brand_new = [p for p in fresh if p["id"] not in prev_ids] if prev_ids else fresh
        new_snapshot[kw] = {"ids": cur_ids, "checked": today}

        if not fresh and not hot:
            continue

        lines.append(f"\n## {cn} · {kw}")
        if prev_ids:
            lines.append(f"🆕 本周新增 {len(brand_new)} 个新品（对比上周新品榜）")
        else:
            lines.append("🆕 首次建立基线，下周起显示新增")
        total_new += len(brand_new)

        for p in brand_new[:5]:
            star = f" ⭐{p['rating']}" if p["rating"] else ""
            fb = f" · {p['feedbacks']}评" if p["feedbacks"] else ""
            lines.append(f"- [{p['name'][:48]}]({p['url']}) · {fmt_price(p['price'])}{star}{fb}")

        if hot:
            lines.append("🔥 当前热门 Top3：")
            for p in hot[:3]:
                fb = f"{p['feedbacks']}评" if p["feedbacks"] else "—"
                lines.append(f"- [{p['name'][:48]}]({p['url']}) · {fmt_price(p['price'])} · {fb}")

    header = f"本周共捕捉新品约 {total_new} 个，覆盖 {len(cfg['categories'])} 个品类。\n"
    report = lines[0] + header + "\n".join(lines[1:])
    return report, new_snapshot, total_new

def push_serverchan(title, content):
    key = os.environ.get("SERVERCHAN_KEY", "").strip()
    if not key:
        return False
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                          data={"title": title, "desp": content}, timeout=20)
        print(f"[push] Server酱 {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[warn] Server酱 失败: {e}")
        return False

def push_wecom(title, content):
    """企业微信群机器人 webhook（国内最稳，推荐主用）。"""
    url = os.environ.get("WECOM_WEBHOOK", "").strip()
    if not url:
        return False
    body = {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n\n" + content[:3500]}}
    try:
        r = requests.post(url, json=body, timeout=20)
        print(f"[push] 企业微信 {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[warn] 企业微信 失败: {e}")
        return False

def push_feishu(title, content):
    """飞书群机器人 webhook。"""
    url = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not url:
        return False
    body = {"msg_type": "text", "content": {"text": f"{title}\n\n" + content[:3500]}}
    try:
        r = requests.post(url, json=body, timeout=20)
        print(f"[push] 飞书 {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[warn] 飞书 失败: {e}")
        return False

def push_bark(title, content):
    """Bark（iOS）。BARK_URL 形如 https://api.day.app/你的key"""
    base = os.environ.get("BARK_URL", "").strip().rstrip("/")
    if not base:
        return False
    try:
        body = content.split("\n", 2)[0][:200]
        r = requests.post(base, json={"title": title, "body": body, "group": "DecoWatch"}, timeout=20)
        print(f"[push] Bark {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"[warn] Bark 失败: {e}")
        return False

def push_all(title, content):
    """多通道冗余：设了哪个就发哪个，互不影响。一个失效其他照常。"""
    results = {
        "serverchan": push_serverchan(title, content),
        "wecom": push_wecom(title, content),
        "feishu": push_feishu(title, content),
        "bark": push_bark(title, content),
    }
    sent = [k for k, v in results.items() if v]
    if sent:
        print(f"[push] 成功通道: {', '.join(sent)}")
    else:
        print("[info] 没有可用推送通道（未设密钥或全部失败）。网页通知仍可在打开时弹出。")
    return results

def main():
    cfg = load_config()
    snapshot = load_snapshot()
    report, new_snapshot, total_new = build_report(cfg, snapshot)
    print("\n" + "=" * 50 + "\n" + report + "\n" + "=" * 50)

    today = datetime.date.today().isoformat()
    title = f"Deco 新品周报 {today}"
    push_all(title, report)

    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(new_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (data_dir / "latest_report.md").write_text(report, encoding="utf-8")
    # status.json：给网页轮询用，触发桌面通知/横幅
    status = {"date": today, "total_new": total_new, "title": title, "report": "data/latest_report.md"}
    (data_dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[done] 已写回 snapshot / latest_report.md / status.json")

if __name__ == "__main__":
    main()

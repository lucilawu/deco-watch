# Deco 新品巡查台 · UNION VISION

一个**在线网址 + 每周自动推送**的俄罗斯家居 deco 新品监测仓库。

- 在线面板（GitHub Pages）：按品类一键直达 WB / Ozon 新品热销 + 客户官网新品 + 对标商超
- 每周自动（GitHub Actions）：抓 Wildberries 新品/热销，对比上周，生成中文周报推送到微信（Server酱）
- 单一数据源 `keywords.json`：加关键词只改这一份，网页和爬虫同步更新

---

## 一、谁负责什么（重要）

| 角色 | 干什么 |
|---|---|
| **GitHub 仓库** | 一切的中心，也是你发给 Codex 的「网址」 |
| **GitHub Pages** | 给你一个随时打开的在线面板地址 |
| **GitHub Actions** | 真正的「每周自动」定时器，跑爬虫 + 推送 |
| **Server酱** | 把周报发到你微信 |
| **Codex** | 你指向这个仓库，让它改脚本/加功能（Codex 不常驻、不会自己定时） |

一句话：**Codex 是维修工，Actions 是闹钟。** 每周自动那一环靠 Actions，不是 Codex。

---

## 二、5 步搭起来

1. **建仓库**：在 GitHub 新建一个仓库（设 Private 也行），把本文件夹所有内容传上去。
2. **开 Pages**：仓库 Settings → Pages → Source 选 `main` 分支、根目录 `/`，保存。
   过一两分钟你会得到网址：`https://你的用户名.github.io/仓库名/` ← 这就是随时打开的在线面板。
3. **配推送通道（建议至少两个，冗余）**：仓库 Settings → Secrets and variables → Actions → New repository secret。设了哪个就发哪个，一个失效其他照常：

   | Secret 名 | 通道 | 说明 |
   |---|---|---|
   | `WECOM_WEBHOOK` | 企业微信群机器人 | **国内最稳，推荐主用**。群设置里加「机器人」拿 webhook 地址 |
   | `BARK_URL` | Bark（iOS） | iPhone 用，形如 `https://api.day.app/你的key`，秒到 |
   | `FEISHU_WEBHOOK` | 飞书群机器人 | 用飞书的话加这个 |
   | `SERVERCHAN_KEY` | Server酱 | 你原来的，留着当备用 |

4. **测试一次**：Actions 标签页 → `weekly-deco-watch` → `Run workflow` 手动跑，检查各通道是否到。
5. **交给定时器**：之后每周一自动跑（时间在 `weekly.yml` 的 cron 里改）。

---

## 通知怎么工作（两条腿）

- **网页桌面弹窗**：打开面板，点右上角「🔔 开启桌面通知」授权一次。之后只要每周爬虫更新了周报，
  面板检测到就弹桌面通知 + 顶部横幅，**完全不依赖 Server酱**。把面板装成桌面 App（地址栏的安装按钮）效果更好。
  - 限制：网页通知只在**面板开着或装成 App 在后台**时能弹。页面彻底关掉、人不在电脑前，浏览器无法自己醒来推送
    （静态托管给不了常驻推送服务器）。这正是上面那几个 webhook 通道补的位。
- **微信/手机推送**：GitHub Actions 每周跑完，多通道同时推。企业微信/Bark 比 Server酱 稳得多，建议主用。

两条腿合起来：**在电脑前看网页弹窗，不在就靠企业微信/Bark**，Server酱 退居备用，偶尔失效也不影响。

---

## 三、怎么加关键词

只改 `keywords.json` 里的 `categories`，加一行：

```json
{ "cn": "香薰石膏", "ru": "Гипс ароматический", "kw": "ароматический гипс декор" }
```

- `cn` 中文品类名（面板显示）
- `ru` 俄文小标签（面板显示）
- `kw` 真正用于搜索和抓取的俄文关键词

提交后，**在线面板自动多一张卡，下次每周爬虫也自动开始监测这个词**。手机上用 GitHub 网页直接编辑保存即可。

---

## 四、把网址发给 Codex 时怎么说

发给 Codex 的是**仓库地址**（不是 Pages 地址）。常用指令示例：

- 「WB 接口字段变了，周报价格抓不到，帮我更新 `scraper.py` 的字段映射」
- 「给 `scraper.py` 加一个 Ozon 抓取模块 `ozon.py`，用官方 API」
- 「周报里加一栏：本周价格比上周下降超过 20% 的款」
- 「把推送从 Server酱 改成同时写入我的 Airtable（沿用现有 Make 流程）」

Codex 读仓库、改代码、提交；Actions 继续按周自动跑改好的版本。

---

## 五、文件说明

```
keywords.json            # 唯一数据源：品类/关键词 + 客户/对标链接
index.html               # 在线面板（读 keywords.json）
scraper.py               # 每周爬虫：WB 新品/热销 → 对比 → 周报 → Server酱
requirements.txt         # Python 依赖
data/snapshot.json       # 上周快照（Actions 自动更新，勿手改）
data/latest_report.md    # 最近一期周报（自动生成）
.github/workflows/weekly.yml  # 每周定时任务
```

## 六、已知边界（诚实说明）

- **Wildberries 接口参数会变**：失效时让 Codex 更新即可，这是预期内的维护。
- **Ozon 反爬强**：本脚本只抓 WB。Ozon 想要数据需官方 API 或 headless，建议单独让 Codex 加。
- **X5 / Magnit 自营线上 deco 薄**：周报的真实价值在 WB 大盘 + 你和 Steve / Anastasia 的一手数据，线上官网做参考。
- **客户档案**：别用单次询盘定型，多渠道交叉验证后再更新 client_profiles.json。

# Deco 新品巡查台 · UNION VISION

一个**在线网址 + 客户信号每日监测 + WB 每周更新**的俄罗斯家居 deco 新品监测仓库。

- 在线面板（GitHub Pages）：按品类一键直达 WB / Ozon 新品热销 + 客户官网新品 + 对标商超
- 每日自动（GitHub Actions）：追踪客户官网上新与社媒预告，生成“今日新增 + 近7天累计”中文日报；仅有真实客户新增时推送
- 每周自动：单独刷新 Wildberries 大盘，避免加重接口限流
- 单一数据源 `keywords.json`：品类、客户官网和社媒频道都从这里读取，不在脚本中写死

---

## 一、谁负责什么（重要）

| 角色 | 干什么 |
|---|---|
| **GitHub 仓库** | 一切的中心，也是你发给 Codex 的「网址」 |
| **GitHub Pages** | 给你一个随时打开的在线面板地址 |
| **GitHub Actions** | 客户信号每天跑，WB 大盘每周跑；有客户新增才推送 |
| **Server酱** | 把周报发到你微信 |
| **Codex** | 你指向这个仓库，让它改脚本/加功能（Codex 不常驻、不会自己定时） |

一句话：**Codex 是维修工，Actions 是闹钟。** 自动监测靠 Actions，不是 Codex。

---

## 二、5 步搭起来

1. **建仓库**：在 GitHub 新建一个仓库（设 Private 也行），把本文件夹所有内容传上去。
2. **开 Pages**：仓库 Settings → Pages → Source 选 `main` 分支、根目录 `/`，保存。
   过一两分钟你会得到网址：`https://你的用户名.github.io/仓库名/`。
3. **配推送通道（建议至少两个，冗余）**：仓库 Settings → Secrets and variables → Actions → New repository secret。设了哪个就发哪个，一个失效其他照常：

   | Secret 名 | 通道 | 说明 |
   |---|---|---|
   | `WECOM_WEBHOOK` | 企业微信群机器人 | **国内最稳，推荐主用**。群设置里加「机器人」拿 webhook 地址 |
   | `BARK_URL` | Bark（iOS） | iPhone 用，形如 `https://api.day.app/你的key`，秒到 |
   | `FEISHU_WEBHOOK` | 飞书群机器人 | 用飞书的话加这个 |
   | `SERVERCHAN_KEY` | Server酱 | 留着当备用 |
   | `VK_TOKEN` | VK 官方 API | 用于读取客户公开墙；配置方式见下文 |

4. **测试一次**：Actions 标签页 → `daily-client-signals` → `Run workflow` 手动跑；只有真实新增时才会检查到推送。
5. **交给定时器**：客户官网/社媒每天跑（`daily.yml`），WB 每周一跑（`weekly.yml`）。

---

## 客户官网与社媒配置

所有客户配置都在 `keywords.json` 的 `clients[]`：

```json
{
  "name": "示例客户",
  "new_arrivals": {
    "track": true,
    "source": "sela_html",
    "url": "https://example.com/new/"
  },
  "social": {
    "track": true,
    "telegram": "public_channel",
    "vk": "public_group_domain"
  }
}
```

- `new_arrivals.track == true` 才追踪官网；先抓完整上新页，再按商品路径/分类保留家居装饰品。宽泛分类或无分类时，使用 `categories[].kw` 的俄文品类核心词兜底。
- `decor_path_allow`、`decor_path_deny` 和 `decor_path_keyword_fallback` 分别配置明确保留、明确排除和需要关键词判断的实际站点路径；报告会统计被过滤的非装饰商品数。Fix Price 还启用 `require_decor_keyword_for_allowed_path`，即使路径属于装饰类也必须通过关键词复核。
- `meta.exclude_name_keywords_ru` 是所有客户共用的商品名黑名单，优先级高于分类和包含词；客户还可在 `new_arrivals.exclude_name_keywords_ru` 追加专属排除词。
- `price_band` 可写成 `1000–7000 ₽ · 描述` 或 `{min_rub, max_rub, label}`；`focus` 通过 `meta.focus_match_keywords` 判断，并生成“🎯 价位匹配 / ✨ 品类对口”标记。
- `social.track == true` 才追踪社媒；缺少某个平台时可以省略对应字段。
- Telegram 读取 `https://t.me/s/{频道}` 公开页，无需 token。
- VK 使用官方 `wall.get`，需要 `VK_TOKEN`。
- Fix Price 使用官网前端实际调用的 `buyer/v1/product/in/novinki`；Sela Home 读取商品卡中的 `data-p` JSON 并遍历全部分页。

### 获取 VK_TOKEN

1. 在 [VK 开发者后台](https://dev.vk.com/apps)创建游戏或小程序。
2. 进入应用控制面板，打开 **开发（Разработка）→ 访问密钥（Ключи доступа）**。
3. 复制 **服务访问密钥（Сервисный ключ доступа）**。
4. 在 GitHub 仓库 `Settings → Secrets and variables → Actions` 新建名为 `VK_TOKEN` 的 Secret。

不要把 token 写入仓库、截图或聊天。没有 `VK_TOKEN` 时，VK 小节会明确提示，但 Telegram、官网和 WB 仍会继续运行，已有 VK 快照不会被清空。

---

## 通知怎么工作（两条腿）

- **网页桌面弹窗**：打开面板，点右上角「🔔 开启桌面通知」授权一次。只有当天官网或社媒真正新增时才弹出；0 新增只刷新面板。
- **微信/手机推送**：同样只在当天客户官网或社媒有新增时多通道推送。企业微信/Bark 比 Server酱稳定，建议主用。

两条腿合起来：**在电脑前看网页弹窗，不在就靠企业微信/Bark**，Server酱退居备用。

---

## 三、怎么加关键词

只改 `keywords.json` 里的 `categories`，加一行：

```json
{ "cn": "香薰石膏", "ru": "Гипс ароматический", "kw": "ароматический гипс декор" }
```

- `cn` 中文品类名（面板显示）
- `ru` 俄文小标签（面板显示）
- `kw` 真正用于搜索和抓取的俄文关键词

提交后，在线面板自动多一张卡，下次每周爬虫也自动开始监测这个词。

---

## 四、本地运行

```bash
pip install -r requirements.txt
python client_tracker.py
python social_tracker.py
python daily_report.py  # 日报，不请求 WB
python scraper.py       # 周度刷新 WB
```

首次运行只建立基线，同时在报告中展示真实商品/帖子样本；第二天及以后才把不在上次快照中的 ID 标为新增。

---

## 五、文件说明

```text
keywords.json                 # 唯一配置源：品类、客户官网、客户社媒
index.html                    # 在线面板（读 keywords.json）
client_tracker.py             # 客户官网全部上新 → 客户快照
social_tracker.py             # Telegram / VK 新帖 → 频道快照
daily_report.py               # 每日客户报告 + 近7天累计 + 智能推送
scraper.py                    # 每周 WB 大盘刷新 + 报告汇总
requirements.txt              # Python 依赖
data/client_snapshot.json     # 客户官网上新快照
data/social_snapshot.json     # 社媒频道快照
data/snapshot.json            # WB 关键词快照
data/wb_latest.json           # 最近一次周度 WB 结果，供每日日报复用
data/latest_report.md         # 最近一期日报
data/status.json              # 面板读取的日报状态
data/history/YYYY-MM-DD.json  # 每日客户、社媒及周度 WB 结构化历史归档
data/history/index.json       # 已归档日期与文件清单
.github/workflows/daily.yml   # 每日客户官网/社媒任务
.github/workflows/weekly.yml  # 每周 WB 任务
```

## 六、已知边界

- **Wildberries 接口参数会变**：当前使用网页实际调用的 v18 搜索参数，并带相关性过滤、限流重试和较完整的新品快照。
- **VK 官方 API**：必须配置有效 `VK_TOKEN`；未配置时不影响其他来源。
- **Ozon 反爬强**：本脚本只抓 WB。Ozon 想要数据需官方 API 或 headless。
- **X5 / Magnit 自营线上 deco 薄**：周报的真实价值在客户官网、社媒预告和 WB 大盘交叉验证。
- **提高频率会增加反爬风险**：Fix Price / Sela 官网现在每天抓取，比每周更容易触发 403 或人机验证（X5 已经发生）。如果两站开始频繁 403，应把 `daily.yml` 改为隔天或恢复每周，而不是继续重试加压。

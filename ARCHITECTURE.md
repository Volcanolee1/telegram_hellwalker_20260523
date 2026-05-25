# 📋 news_commander_project 项目架构文档

> 自动化全球新闻情报采集 → AI 提炼 → Telegram 推送系统  
> 作者：Volcanolee1 | 仓库：[telegram_hellwalker_20260523](https://github.com/Volcanolee1/telegram_hellwalker_20260523)

---

## 🏗️ 一、项目概览

本项目分为两大板块：

| 板块 | 运行位置 | 核心职责 |
|------|----------|---------|
| **本地 Clipper** | Windows 台式机 | 巡逻媒体首页 → 绕过付费墙抓全文 → 入本地库 + 同步 VPS |
| **云端服务** | 圣何塞 VPS | 接收情报 → Gemini 摘要 → Telegram 频道推送 + Bot 交互 |

---

## 🗂️ 二、文件角色分类

### 【本地核心链路】（Windows，按执行顺序）

| 文件 | 角色 | 说明 |
|------|------|------|
| **patrol.py** | ① 巡逻兵 | 用 CDP 接管真人 Chrome，逐站访问 20+ 全球媒体首页，CSS 选择器 + 正则双重过滤发现新文章链接，写入 `article_queue` 表。支持 `--only US CN` `--tag WAR` 参数化过滤 |
| **clip_worker.py** | ② 剪刀手 | 从 `article_queue` 出队 pending 链接，CDP 接管 Chrome 绕过付费墙（Bypass Paywalls Clean 插件），8 级 CSS Fallback 提取正文（≥300 字才合格），落入 `article` 表。**同时通过 HTTP POST 将全文发送到 VPS** |
| **summarizer.py** | ③ 提炼师 | 从 `article` 表取 `summary_status=pending` 的文章，通过 SOCKS5 代理调用 `gemini-3.1-flash-lite`，用深耕地缘政治的 system instruction 生成 150 字中文情报快报，回写 `summary` 列 |
| **publisher.py** | ④ 发报员 | 取 `summarized + publish_status=pending` 的文章，HTML 排版（标题蓝链 + 摘要），按来源路由到 US 频道 / CN 频道，推送到 Telegram |
| **orchestrator.py** | 总指挥 | 将 ①②③④ 串成一条定时流水线，默认每 30 分钟一轮，支持 `--once` `--interval` `--skip-patrol` 参数 |

### 【本地基础设施】

| 文件 | 角色 | 说明 |
|------|------|------|
| **news_db.py** | 数据库层 | SQLite (`commander.db`)，两张核心表：`article_queue`（待抓链接）+ `article`（成品文章）。完整状态机：pending → clipping → clipped/failed → pending_summary → summarizing → summarized → pending_publish → published。支持动态列迁移 |
| **browser_cdp.py** | Chrome 工具 | CDP 端口探测（9222）、反指纹 JS 注入、端口可用性检测提示 |
| **config_loader.py** | 配置中心 | 从 `config.json` 加载 API Key / Token / 代理配置，自动挂载全局 SOCKS5 代理环境变量 |
| **tg_commander.py** | TG 指挥官 Bot | 监听 Telegram 私聊，支持 `/stats` 查看进度、按国家（`US`/`CN` 等）和领域标签（`WAR`/`BIZZ` 等）实时查询 DB |
| **launch_chrome.bat** | 浏览器启动器 | 以调试模式（9222 端口）启动真人 Chrome，加载 Bypass Paywalls Clean 插件 |

### 【VPS 端】（圣何塞，`test` 开头是经过适配的版本）

| 文件 | 角色 | 说明 |
|------|------|------|
| **testapi.py** ⭐ | 接收网关 | FastAPI 服务（端口 8008），`POST /post-news` 接收本地发来的全文，存入 `news_data.db`。**收到新情报后自动触发 `run_cloud_cycle()` 后台任务**，即时启动摘要 + 发布流水线 |
| **orchestartor_cloud.py** ⭐ | 云端调度 | 云端版编排器，只走 `summarize → publish` 两阶段（不需要 patrol/clip），通过 `BackgroundTasks` 被 testapi 触发 |
| **testclip.py** ⭐ | VPS 版剪刀手 | clip_worker 的 VPS 适配版，区别在于通过 SSH 隧道 `127.0.0.1:8008` 发送数据 |
| **testsum.py** ⭐ | VPS 版提炼师 | summarizer 的 VPS 适配版，同样通过 SOCKS5 代理调用 Gemini |

### 【历史 / 备选文件】

| 文件 | 说明 |
|------|------|
| `api_server.py` | V1 版 FastAPI 接收端（端口 8000），已被 `testapi.py`（8008）取代 |
| `稳定版local_clipper.py` | V1 版独立 clipper，手动输入 URL 抓取并投递 VPS，已被 `clip_worker.py` + `patrol.py` 的自动化流水线取代 |
| `local.processor.py` | V1 版本地处理 + TG 推送，已被 `summarizer.py` + `publisher.py` 拆分取代 |
| `mvp_news_station.py` | 更早期的 RSS 聚合 + Gemini 日报方案，通过 `feedparser` 抓 RSS，已被 patrol 的 CDP 方案取代 |
| `Bloomberg_clear.py` | 空白占位文件，未实现 |
| `check_db.py` | 调试工具，打印 `article` 表列名 |
| `skip_source.py` | 跳过源配置 |
| `cleanup_bad_urls.py` | 清理坏链接工具 |

---

## 🔄 三、完整数据流

```
┌──────────── 阶段① PATROL ────────────┐
│  python patrol.py                     │
│  CDP → Chrome 访问 20+ 媒体首页       │
│  CSS 提取链接 → 正则过滤 → 去重入队   │
│  article_queue (status=pending)       │
└──────────────┬────────────────────────┘
               ▼
┌──────────── 阶段② CLIP ──────────────┐
│  python clip_worker.py                │
│  出队 → CDP 接管 Chrome → 绕过付费墙  │
│  8 级 CSS Fallback 正文提取 (MIN=300) │
│    ├─ article 表 (body 全文)          │
│    └─ HTTP POST → VPS testapi:8008    │
│         └─ VPS news_data.db           │
└──────────────┬────────────────────────┘
               ▼
┌────────── 阶段③ SUMMARIZE ───────────┐
│  python summarizer.py                 │
│  SOCKS5 代理 → Gemini flash-lite      │
│  地缘政治情报分析员角色               │
│  150 字中文凝练摘要 → article.summary │
└──────────────┬────────────────────────┘
               ▼
┌────────── 阶段④ PUBLISH ─────────────┐
│  python publisher.py                  │
│  HTML 排版（标题蓝链 + 摘要）         │
│  来源路由: US → @HellWalker_DailyNews │
│           CN → @HellWalker_CN_Daily   │
│  推送至 Telegram 频道                 │
└───────────────────────────────────────┘
```

---

## 🔑 四、核心技术亮点

1. **付费墙绕过**：Bypass Paywalls Clean 插件 + 真人 Chrome 指纹（反 webdriver 检测）+ 随机抖动间隔（3.5-7 秒）
2. **正文提取**：8 级 CSS Fallback（`article` → `main article` → `main` → `.article-body` → `.story-content` → `[class*="ArticleBody"]` → `[data-testid*="article"]` → `[itemprop="articleBody"]` → `body` 兜底）
3. **状态机设计**：每个环节都有完整状态流转，支持失败重试、配额检测自动中止、幂等操作
4. **轮询算法**：`_round_robin()` 确保多来源均匀出队，不会让某个源垄断整批
5. **双通道同步**：本地入库 + HTTP POST 同步 VPS，通过 SOCKS5 代理出海
6. **Gemini 角色化**：专为地缘政治 / 经济情报设计的 system instruction（温度 0.3 确保客观性）
7. **动态数据库迁移**：`_migrate()` 自动检测并添加缺失列，旧 DB 无需重建即可升级

---

## 🗺️ 五、信息源矩阵（20 个来源，8 个国家 / 地区）

| 国家 | 来源 | 标签 |
|------|------|------|
| 🇺🇸 US | Bloomberg, Reuters, NYT, APNews, Politico, CNBC, TechCrunch, DefenseNews, WarOnTheRocks | BIZZ / MARKET / ECON / POL / WAR / TECH |
| 🇬🇧 UK | BBC, TheGuardian, FT | MULTI / POL / WAR / BIZZ / ECON |
| 🇪🇺 EU | France24, DW, EUobserver | MULTI / POL / WAR / ECON |
| 🇨🇳 CN | GlobalTimes, SCMP, XinhuaNet | POL / BIZZ / MULTI |
| 🇯🇵 JP | NHKWorld, NikkeiAsia | MULTI / POL / BIZZ / ECON |
| 🇷🇺 RU | RT | MULTI / WAR / POL |
| 🌍 ME | AlJazeera | MULTI / WAR / POL |

### 标签分类说明

| 标签 | 含义 |
|------|------|
| MULTI | 综合新闻 |
| POL | 政治 |
| WAR | 战争 / 地缘冲突 |
| BIZZ | 商业 |
| ECON | 经济 |
| MARKET | 金融市场 |
| TECH | 科技 |

---

## 🗄️ 六、数据库设计

### 本地 `commander.db`

**表：article_queue（待抓链接队列）**

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| source | TEXT | 来源名称 |
| url | TEXT UNIQUE | 文章链接 |
| title | TEXT | 链接文本标题 |
| country | TEXT | 国家代码 |
| tags | TEXT | 逗号分隔的标签 |
| discovered_at | TIMESTAMP | 发现时间 |
| status | TEXT | pending → clipping → clipped / failed |
| attempt_count | INTEGER | 重试次数（上限 3） |
| last_error | TEXT | 最后一次错误信息 |
| last_attempt_at | TIMESTAMP | 最后尝试时间 |

**表：article（成品文章）**

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| queue_id | INTEGER | 关联队列记录 |
| source | TEXT | 来源名称 |
| url | TEXT UNIQUE | 文章链接 |
| title | TEXT | 文章标题 |
| body | TEXT | 全文内容 |
| body_length | INTEGER | 正文字数 |
| clipped_at | TIMESTAMP | 抓取时间 |
| sync_status | TEXT | pending → synced / failed |
| synced_at | TIMESTAMP | 同步到 VPS 的时间 |
| publish_status | TEXT | pending → publishing → published / failed |
| summary | TEXT | AI 生成的摘要 |
| summary_status | TEXT | pending → summarizing → summarized / failed |
| summary_at | TIMESTAMP | 摘要生成时间 |
| summary_model | TEXT | 使用的模型名 |
| summary_input_chars | INTEGER | 送入模型的字符数 |
| summary_error | TEXT | 摘要失败原因 |
| publish_at | TIMESTAMP | 发布时间 |
| publish_error | TEXT | 发布失败原因 |
| country | TEXT | 国家代码 |
| tags | TEXT | 逗号分隔的标签 |

### VPS `news_data.db`

**表：news（接收到的情报）**

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| source | TEXT | 来源名称 |
| title | TEXT UNIQUE | 标题（唯一约束防重复） |
| link | TEXT | 原文链接 |
| summary | TEXT | 全文内容 |
| status | TEXT | pending / 其他状态 |
| created_at | TIMESTAMP | 接收时间 |

---

## 📝 七、快速运行指南

### 本地 Windows

```bash
# 1. 先启动真人 Chrome（双击）
launch_chrome.bat

# 2. 本地一键流水线（巡逻 + 抓取 + 摘要 + 发布）
python orchestrator.py --once

# 3. 或分步手动运行
python patrol.py                        # 巡逻发现链接
python patrol.py --only US --tag WAR    # 只巡逻美国战争类源
python clip_worker.py --limit 20        # 抓取 20 篇全文
python clip_worker.py --url "https://..." # 抓取单篇
python summarizer.py --limit 10         # AI 摘要 10 篇
python summarizer.py --retry            # 重试失败条目
python publisher.py --limit 5           # TG 推送 5 篇
python publisher.py --dry-run           # 预览模式，不发

# 4. 启动 TG 交互 Bot
python tg_commander.py
```

### VPS 端

```bash
# 1. 启动 FastAPI 接收服务（端口 8008）
python testapi.py

# 2. 启动 TG 交互 Bot
python tg_commander.py
```

---

## 🌐 八、网络拓扑

```
本地 Windows (127.0.0.1)
  │
  ├─ Chrome CDP      :9222   ← playwright 接管
  │   └─ 浏览器流量  :10809  ← SOCKS5 → v2rayN 香港节点（新闻爬虫专用）
  │                             （与日常办公的 10808 新加坡节点隔离）
  │
  ├─ SOCKS5 代理     :10808  ← Gemini / TG API / VPS 同步出海
  │                             （走新加坡节点，日常办公复用）
  │
  └─ HTTP POST ────→ VPS 107.174.159.191:8008
                        │
                        ├─ FastAPI (testapi.py)
                        ├─ SQLite (news_data.db)
                        ├─ Gemini API ← 通过 SOCKS5
                        └─ Telegram Bot API ← 通过 SOCKS5
```

### 双代理分流原理

| 流量类型 | 端口 | 节点 | 控制方式 |
|----------|------|------|---------|
| **Chrome 浏览器**（访问新闻网站） | `10809` | 🟢 香港 | `launch_chrome.bat` 的 `--proxy-server` 参数 |
| **Python 请求**（Gemini、TG、VPS） | `10808` | 🟠 新加坡 | `config_loader.py` 的环境变量注入 |

**为什么不需要 Sandboxie**：Chrome 原生支持 `--proxy-server=socks5://127.0.0.1:10809` 启动参数，该参数独立于系统代理设置，不影响 Python 端的 10808 代理。两者是 Chrome 进程级代理 vs Python 环境变量代理，天然隔离，无需额外沙箱。

### v2rayN 配置（已完成）

**架构**：`10808` 端口走默认新加坡节点（日常），`10809` 端口走 HK 节点（新闻爬虫），Chrome 和 Python 的代理天然隔离，无需 Sandboxie。

**已修改的文件**：

| 文件 | 修改内容 |
|------|---------|
| `guiNConfig.json` | 添加 `"SecondLocalPort": 10809`（修复"已启用但未指定端口"的 bug） |
| `binConfigs/config.json` | ① `outbounds` 新增 `HKin-IPv4` 节点（vless+reality, 地址 `151.242.11.58:416`）  ② `routing` 新增规则：`inboundTag: socks2` → `outboundTag: HKin-IPv4` |
| `launch_chrome.bat` | 第 5 步自动检测 `127.0.0.1:10809` 是否在线，在线则注入 `--proxy-server=socks5://127.0.0.1:10809` |

**验证**：重启 v2rayN 后，`netstat -ano | findstr ":10809"` 应看到 `LISTENING`，然后双击 `launch_chrome.bat` 应输出 `[5/6] HK proxy port 10809 OK`。

---

> 📅 最后更新：2026-05-25  
> 📦 仓库：[telegram_hellwalker_20260523](https://github.com/Volcanolee1/telegram_hellwalker_20260523)

"""主动巡逻：用同一个真人 Chrome 逐站访问首页，把新文章 URL 推进队列。

信息源矩阵 —— 每条记录写入 DB 时带上 country 和 tags，为后续 bot 分类查询打基础。
  国家代码  US / UK / EU / CN / JP / RU / ME / INTL (国际)
  类别代码  MULTI(综合) / POL(政治) / WAR(战争/地缘) / BIZZ(商业) / ECON(经济) / MARKET(市场) / TECH(科技)

跑法：
  python patrol.py                         # 巡逻全部源
  python patrol.py --only US               # 只巡逻 country=US 的源
  python patrol.py --only EU CN            # 多个国家
  python patrol.py --tag WAR               # 只巡逻含 WAR 标签的源
  python patrol.py --only US --tag TECH    # 交叉过滤（AND 关系）
"""
import argparse
import re
from collections import namedtuple
from playwright.sync_api import sync_playwright

import news_db
from browser_cdp import ensure_port_alive, cdp_endpoint, apply_stealth

# ── 数据结构 ─────────────────────────────────────────────────────────────────
# name       : 来源名，唯一标识，写入 DB
# country    : 国家/地区代码，写入 DB
# tags       : 类别标签元组，写入 DB 时 join 成逗号字符串
# homepage   : 要巡逻的 URL
# selector   : CSS 选择器（粗筛，从 DOM 捞候选链接）
# article_re : 文章 URL 正则（精筛，过滤栏目页/导航链接）
Source = namedtuple("Source", ["name", "country", "tags", "homepage", "selector", "article_re"])

# ── 信息源矩阵 (全球顶级媒体库) ──────────────────────────────────────────────
HOMEPAGES: list[Source] = [

    # ══ 美国 US ══════════════════════════════════════════════════════════════
    Source("Bloomberg", "US", ("BIZZ", "MARKET", "ECON"),
           "https://www.bloomberg.com/",
           "a[href*='/news/articles/'], a[href*='/news/features/']",
           re.compile(r"/news/(articles|features)/\d{4}-\d{2}-\d{2}/")),

    Source("Reuters", "US", ("MULTI", "POL", "WAR"),
           "https://www.reuters.com/world/",
           "a[href*='/world/'], a[href*='/business/'], a[href*='/markets/']",
           re.compile(r"-\d{4}-\d{2}-\d{2}/?$")),

    Source("NYT", "US", ("MULTI", "POL"),
           "https://www.nytimes.com/section/world",
           "a[href^='/2025/'], a[href^='/2026/'], a[href*='nytimes.com/2025/'], a[href*='nytimes.com/2026/']",
           re.compile(r"/\d{4}/\d{2}/\d{2}/")),

    Source("APNews", "US", ("MULTI", "POL", "WAR"),
           "https://apnews.com/",
           "a[href*='/article/']",
           re.compile(r"/article/[a-z0-9-]+-[a-f0-9]{16,}")),

    Source("Politico", "US", ("POL",),
           "https://www.politico.com/",
           "a[href*='/news/2025/'], a[href*='/news/2026/']",
           re.compile(r"/news/\d{4}/\d{2}/\d{2}/")),

    Source("CNBC", "US", ("MARKET", "BIZZ", "TECH"),
           "https://www.cnbc.com/world/?region=world",
           "a[href*='cnbc.com/2025/'], a[href*='cnbc.com/2026/']",
           re.compile(r"cnbc\.com/\d{4}/\d{2}/\d{2}/")),

    Source("TechCrunch", "US", ("TECH",),
           "https://techcrunch.com/",
           "a[href*='techcrunch.com/2025/'], a[href*='techcrunch.com/2026/']",
           re.compile(r"techcrunch\.com/\d{4}/\d{2}/\d{2}/")),

    Source("DefenseNews", "US", ("WAR",),
           "https://www.defensenews.com/",
           "a[href*='defensenews.com/'][href*='2025/'], a[href*='defensenews.com/'][href*='2026/']",
           re.compile(r"defensenews\.com/[a-z-]+/\d{4}/\d{2}/\d{2}/")),

    Source("WarOnTheRocks", "US", ("WAR", "POL"),
           "https://warontherocks.com/",
           "a[href*='warontherocks.com/2025/'], a[href*='warontherocks.com/2026/']",
           re.compile(r"warontherocks\.com/\d{4}/\d{2}/[a-z0-9-]+")),

    # ══ 英国 UK ══════════════════════════════════════════════════════════════
    Source("BBC", "UK", ("MULTI", "POL", "WAR"),
           "https://www.bbc.com/news/world",
           "a[href*='/news/articles/'], a[href*='/news/world-']",
           re.compile(r"/news/(articles/[a-zA-Z0-9-]+|world-\d+)")),

    Source("TheGuardian", "UK", ("MULTI", "POL"),
           "https://www.theguardian.com/world",
           "a[href*='/2025/'], a[href*='/2026/']",
           re.compile(r"/\d{4}/[a-z]{3}/\d{2}/")),

    Source("FT", "UK", ("BIZZ", "ECON", "MARKET"),
           "https://www.ft.com/world",
           "a[href*='/content/']",
           re.compile(r"/content/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")),

    # ══ 欧洲 EU ══════════════════════════════════════════════════════════════
    Source("France24", "EU", ("MULTI", "POL", "WAR"),
           "https://www.france24.com/en/",
           "a[href*='/en/europe/'], a[href*='/en/middle-east/'], a[href*='/en/asia-pacific/'], a[href*='/en/africa/'], a[href*='/en/americas/'], a[href*='/en/economy/']",
           re.compile(r"/en/[a-z-]+/\d{8}-[a-z0-9-]+")),

    Source("DW", "EU", ("MULTI", "POL"),
           "https://www.dw.com/en/top-stories/s-9097",
           "a[href*='/en/'][href*='/a-']",
           re.compile(r"/en/[a-z0-9-]+/a-\d{7,}")),

    Source("EUobserver", "EU", ("POL", "ECON"),
           "https://euobserver.com/",
           "a[href*='/news/']",
           re.compile(r"euobserver\.com/[a-z-]+/\d{6,}")),

    # ══ 中国 / 香港 CN ════════════════════════════════════════════════════════
    Source("GlobalTimes", "CN", ("POL", "MULTI"),
           "https://www.globaltimes.cn/",
           "a[href*='/page/']",
           re.compile(r"/page/\d{6}/\d+\.shtml")),

    Source("SCMP", "CN", ("BIZZ", "POL", "MULTI"),
           "https://www.scmp.com/news/world",
           "a[href*='/news/world/article/'], a[href*='/news/china/article/'], a[href*='/news/asia/article/']",
           re.compile(r"/article/\d+/")),

    Source("XinhuaNet", "CN", ("POL", "MULTI"),
           "https://english.news.cn/",
           "a[href*='english.news.cn/'][href*='2025/'], a[href*='english.news.cn/'][href*='2026/']",
           re.compile(r"english\.news\.cn/\d{8}/")),

    # ══ 日本 JP ══════════════════════════════════════════════════════════════
    Source("NHKWorld", "JP", ("MULTI", "POL"),
           "https://www3.nhk.or.jp/nhkworld/en/news/",
           "a[href*='/nhkworld/en/news/']",
           re.compile(r"/nhkworld/en/news/\d{8}")),

    Source("NikkeiAsia", "JP", ("BIZZ", "ECON", "MARKET"),
           "https://asia.nikkei.com/",
           "a[href*='asia.nikkei.com/Politics/'], a[href*='asia.nikkei.com/Economy/'], a[href*='asia.nikkei.com/Business/'], a[href*='asia.nikkei.com/Markets/']",
           re.compile(r"asia\.nikkei\.com/(Politics|Economy|Business|Markets)/[^/]+/[^/]")),
           
    # ══ 俄罗斯 RU (可扩充) ═══════════════════════════════════════════════════
    Source("RT", "RU", ("MULTI", "WAR", "POL"),
           "https://www.rt.com/",
           "a[href*='/russia/'], a[href*='/news/']",
           re.compile(r"rt\.com/(russia|news)/\d+-")),
           
    # ══ 中东 ME (可扩充) ═════════════════════════════════════════════════════
    Source("AlJazeera", "ME", ("MULTI", "WAR", "POL"),
           "https://www.aljazeera.com/",
           "a[href*='/news/2025/'], a[href*='/news/2026/']",
           re.compile(r"aljazeera\.com/news/\d{4}/\d{1,2}/\d{1,2}/")),
]

MIN_TITLE_LEN = 12

# 注入浏览器的精炼 JS，直接去重并提取候选列表
EXTRACT_JS = """
(selector) => {
    const seen = new Set();
    const out = [];
    document.querySelectorAll(selector).forEach(a => {
        const url = a.href;
        let title = (a.innerText || a.textContent || '').trim().replace(/\\s+/g, ' ');
        if (!url || !title) return;
        if (seen.has(url)) return;
        seen.add(url);
        out.push({ url, title });
    });
    return out;
}
"""

# 黑名单防雷：避免爬虫钻进视频、播客、登录页等死胡同
URL_BLACKLIST = (
    "/video/", "/videos/", "/podcasts/", "/section/", "/sections/",
    "/topic/", "/topics/", "/tag/", "/tags/",
    "/account/", "/auth/", "/login", "/subscribe", "/newsletter",
    "/about/", "/help/",
)

def _looks_like_article(url: str, article_re: re.Pattern) -> bool:
    """双重校验：必须是 http 开头，不能命中黑名单，且符合各家特有的正则规则。"""
    if not url.startswith("http"):
        return False
    if "#" in url:
        url = url.split("#", 1)[0]
    if any(b in url for b in URL_BLACKLIST):
        return False
    return bool(article_re.search(url))

def patrol_one_site(page, src: Source) -> int:
    """执行单站点的巡逻抓取"""
    print(f"\n[巡逻] {src.name} ({src.country}/{','.join(src.tags)}) → {src.homepage}")
    try:
        page.goto(src.homepage, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500) # 稍微给点喘息时间，让 JS 渲染出新闻列表
        candidates = page.evaluate(EXTRACT_JS, src.selector)
    except Exception as e:
        print(f"  ⚠️ 巡逻失败：{e}")
        return 0

    tags_str = ",".join(src.tags)
    new_count, dup_count, skip_count = 0, 0, 0
    
    for item in candidates:
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        
        if len(title) < MIN_TITLE_LEN:
            skip_count += 1
            continue
        if not _looks_like_article(url, src.article_re):
            skip_count += 1
            continue
            
        # 尝试推入数据库队列 (依赖 news_db 模块)
        if news_db.enqueue(src.name, url, title, country=src.country, tags=tags_str):
            new_count += 1
        else:
            dup_count += 1

    print(f"  ✓ 候选 {len(candidates)} → 新增 {new_count} / 重复 {dup_count} / 跳过 {skip_count}")
    
    # 如果全被跳过，可能是选择器抓到了导航栏，或者媒体网站改版导致正则失效，打印出样例辅助调试
    if skip_count > 0 and new_count == 0 and dup_count == 0 and candidates:
        samples = [c["url"] for c in candidates[:3] if c.get("url")]
        print(f"  ℹ️  跳过样例（前3条，请确认正则是否匹配）：")
        for s in samples:
            print(f"      {s}")
            
    return new_count

def patrol(only_countries: list[str] | None = None,
           only_tag: str | None = None) -> None:
    """主编排逻辑：连接浏览器、过滤执行源、调度抓取并打印汇总。"""
    if not ensure_port_alive():
        print("❌ 无法连接到本地 Chrome CDP，请确认浏览器是否通过指定端口启动。")
        return

    news_db.init_db()

    sources = HOMEPAGES
    
    # 过滤国家逻辑
    if only_countries:
        uc = [c.upper() for c in only_countries]
        sources = [s for s in sources if s.country in uc]
        
    # 过滤标签逻辑
    if only_tag:
        ut = only_tag.upper()
        sources = [s for s in sources if ut in s.tags]

    if not sources:
        print("⚠️ 过滤后没有匹配的信息源，请检查 --only / --tag 参数。")
        return

    print(f"📋 本次巡逻 {len(sources)} 个信息源：{[s.name for s in sources]}")

    with sync_playwright() as p:
        print("🔗 通过 CDP 接管真人 Chrome...")
        browser = p.chromium.connect_over_cdp(cdp_endpoint())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        apply_stealth(page)

        total_new = 0
        try:
            for src in sources:
                total_new += patrol_one_site(page, src)
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    print(f"\n📡 巡逻完毕，本轮共发现 {total_new} 条新链接")
    print(f"   article_queue: {news_db.queue_stats()}")

def main() -> None:
    ap = argparse.ArgumentParser(description="新闻首页巡逻与情报收割引擎")
    ap.add_argument("--only", nargs="+", metavar="COUNTRY",
                    help="只巡逻指定国家代码的源，如 US UK CN（空格分隔，可多个）")
    ap.add_argument("--tag", metavar="TAG",
                    help="只巡逻含指定标签的源，如 WAR / TECH / MARKET")
    args = ap.parse_args()
    patrol(only_countries=args.only, only_tag=args.tag)

if __name__ == "__main__":
    main()
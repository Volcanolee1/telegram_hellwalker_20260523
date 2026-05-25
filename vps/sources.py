"""统一信息源定义。所有模块共用同一份源列表，新增源只需在这里改。"""
import re
from collections import namedtuple

Source = namedtuple("Source", [
    "name", "country", "tags", "homepage", "selector", "article_re"
])

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
           "a[href^='/2025/'], a[href^='/2026/'], "
           "a[href*='nytimes.com/2025/'], a[href*='nytimes.com/2026/']",
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
           "a[href*='defensenews.com/'][href*='2025/'], "
           "a[href*='defensenews.com/'][href*='2026/']",
           re.compile(r"defensenews\.com/[a-z-]+/\d{4}/\d{2}/\d{2}/")),

    Source("WarOnTheRocks", "US", ("WAR", "POL"),
           "https://warontherocks.com/",
           "a[href*='warontherocks.com/2025/'], a[href*='warontherocks.com/2026/']",
           re.compile(r"warontherocks\.com/\d{4}/\d{2}/[a-z0-9-]+")),

    # ══ 英国 UK ══════════════════════════════════════════════════════════════

    Source("BBC", "UK", ("MULTI", "POL", "WAR"),
           "https://www.bbc.com/news/world",
           "a[href*='/news/articles/'], a[href*='/news/world-']",
           re.compile(r"/news/(articles/[a-z0-9-]+|world-\d+)")),

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
           "a[href*='/en/europe/'], a[href*='/en/middle-east/'], "
           "a[href*='/en/asia-pacific/'], a[href*='/en/africa/'], "
           "a[href*='/en/americas/'], a[href*='/en/economy/']",
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
           "a[href*='/news/world/article/'], a[href*='/news/china/article/'], "
           "a[href*='/news/asia/article/']",
           re.compile(r"/article/\d+/")),

    Source("XinhuaNet", "CN", ("POL", "MULTI"),
           "https://english.news.cn/",
           "a[href*='english.news.cn/'][href*='2025/'], "
           "a[href*='english.news.cn/'][href*='2026/']",
           re.compile(r"english\.news\.cn/\d{8}/")),

    # ══ 日本 JP ══════════════════════════════════════════════════════════════

    Source("NHKWorld", "JP", ("MULTI", "POL"),
           "https://www3.nhk.or.jp/nhkworld/en/news/",
           "a[href*='/nhkworld/en/news/']",
           re.compile(r"/nhkworld/en/news/\d{8}")),

    Source("NikkeiAsia", "JP", ("BIZZ", "ECON", "MARKET"),
           "https://asia.nikkei.com/",
           "a[href*='asia.nikkei.com/Politics/'], "
           "a[href*='asia.nikkei.com/Economy/'], "
           "a[href*='asia.nikkei.com/Business/'], "
           "a[href*='asia.nikkei.com/Markets/']",
           re.compile(r"asia\.nikkei\.com/(Politics|Economy|Business|Markets)/")),

    # ══ 可在此继续添加 ════════════════════════════════════════════════════════
    # Source("SourceName", "XX", ("TAG1", "TAG2"),
    #        "https://homepage/",
    #        "a[href*='/pattern/']",
    #        re.compile(r"/url-pattern/\d+")),
]

# ── 从 HOMEPAGES 派生的辅助查询结构 ────────────────────────────────────────────

ALL_TAGS = sorted(set(tag for s in HOMEPAGES for tag in s.tags))

ALL_COUNTRIES = sorted(set(s.country for s in HOMEPAGES))

# 源 → 频道区域（CN 源推送中文频道，其余推送英文频道）
SOURCE_CHANNEL_MAP: dict[str, str] = {
    s.name: "CN" if s.country == "CN" else "US" for s in HOMEPAGES
}

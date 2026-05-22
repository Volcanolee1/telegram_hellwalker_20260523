"""主动巡逻：用同一个真人 Chrome 逐站访问首页，把新文章 URL 推进队列。

跑法：
  1) 双击 launch_chrome.bat（把真人 Chrome 起到 9222）
  2) python patrol.py
"""
import re
from playwright.sync_api import sync_playwright

import news_db
from browser_cdp import ensure_port_alive, cdp_endpoint, apply_stealth


# 巡逻路线表：(站点名, 首页 URL, 粗筛 CSS 选择器, 精筛 URL 正则)
# 两步过滤：先用 CSS 从 DOM 捞候选，再用正则验证是不是单篇文章 URL（关键，避免栏目页混入）。
#
# 各站文章 URL 形态：
#   Bloomberg   : /news/articles/2026-05-22/slug   /news/features/2026-05-22/slug
#   Reuters     : /world/europe/some-slug-2026-05-22/   ← 结尾必须有 -YYYY-MM-DD/
#   NYT         : /2026/05/22/world/europe/slug.html
#   SCMP        : /news/world/article/3389772/some-slug   ← /article/<纯数字 id>/
#   APNews      : /article/some-slug-<32位 hex>
#   GlobalTimes : /page/2026/05/1332123.shtml   ← 环球时报英文版
#   France24    : /en/europe/20260522-some-title  ← 法新社级别欧洲视角
HOMEPAGES = [
    ("Bloomberg", "https://www.bloomberg.com/",
     "a[href*='/news/articles/'], a[href*='/news/features/']",
     re.compile(r"/news/(articles|features)/\d{4}-\d{2}-\d{2}/")),

    ("Reuters", "https://www.reuters.com/world/",
     "a[href*='/world/'], a[href*='/business/'], a[href*='/markets/']",
     re.compile(r"-\d{4}-\d{2}-\d{2}/?$")),

    ("NYT", "https://www.nytimes.com/section/world",
     "a[href^='/2025/'], a[href^='/2026/'], a[href*='nytimes.com/2025/'], a[href*='nytimes.com/2026/']",
     re.compile(r"/\d{4}/\d{2}/\d{2}/")),

    ("SCMP", "https://www.scmp.com/news/world",
     "a[href*='/news/world/article/'], a[href*='/news/china/article/'], a[href*='/news/asia/article/']",
     re.compile(r"/article/\d+/")),

    ("APNews", "https://apnews.com/",
     "a[href*='/article/']",
     re.compile(r"/article/[a-z0-9-]+-[a-f0-9]{16,}")),

    ("GlobalTimes", "https://www.globaltimes.cn/",
     "a[href*='/page/']",
     re.compile(r"/page/\d{4}/\d{2}/\d+\.shtml")),

    ("France24", "https://www.france24.com/en/",
     "a[href*='/en/europe/'], a[href*='/en/middle-east/'], a[href*='/en/asia-pacific/'], "
     "a[href*='/en/africa/'], a[href*='/en/americas/'], a[href*='/en/economy/']",
     re.compile(r"/en/[a-z-]+/\d{8}-[a-z0-9-]+")),
]

MIN_TITLE_LEN = 12

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

# 粗过滤：URL 里出现这些片段的，多半不是文章页
URL_BLACKLIST = (
    "/video/", "/videos/", "/podcasts/", "/section/", "/sections/",
    "/topic/", "/topics/", "/tag/", "/tags/",
    "/account/", "/auth/", "/login", "/subscribe", "/newsletter",
    "/about/", "/help/",
)


def _looks_like_article(url: str, article_re: re.Pattern) -> bool:
    if not url.startswith("http"):
        return False
    if "#" in url:
        url = url.split("#", 1)[0]
    if any(b in url for b in URL_BLACKLIST):
        return False
    # 关键：每站特定的文章 URL 模式必须匹配，否则一律当栏目页/导航链接丢掉
    return bool(article_re.search(url))


def patrol_one_site(page, source: str, homepage: str, link_selector: str,
                    article_re: re.Pattern) -> int:
    print(f"\n[巡逻] {source} → {homepage}")
    try:
        page.goto(homepage, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)  # 给 JS 渲染一下首屏列表
        candidates = page.evaluate(EXTRACT_JS, link_selector)
    except Exception as e:
        print(f"  ⚠️ 巡逻失败：{e}")
        return 0

    new_count, dup_count, skip_count = 0, 0, 0
    for item in candidates:
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        if len(title) < MIN_TITLE_LEN:
            skip_count += 1
            continue
        if not _looks_like_article(url, article_re):
            skip_count += 1
            continue
        if news_db.enqueue(source, url, title):
            new_count += 1
        else:
            dup_count += 1

    print(f"  ✓ 候选 {len(candidates)} → 新增 {new_count} / 重复 {dup_count} / 跳过 {skip_count}")
    # 全部被跳过时打印样例，方便诊断 CSS 选择器 / URL 正则是否匹配
    if skip_count > 0 and new_count == 0 and dup_count == 0 and candidates:
        samples = [c["url"] for c in candidates[:3] if c.get("url")]
        print(f"  ℹ️  跳过样例（前3条，请确认正则是否匹配）：")
        for s in samples:
            print(f"      {s}")
    return new_count


def patrol() -> None:
    if not ensure_port_alive():
        return

    news_db.init_db()

    with sync_playwright() as p:
        print("🔗 通过 CDP 接管真人 Chrome...")
        browser = p.chromium.connect_over_cdp(cdp_endpoint())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        apply_stealth(page)

        total_new = 0
        try:
            for source, homepage, sel, art_re in HOMEPAGES:
                total_new += patrol_one_site(page, source, homepage, sel, art_re)
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                browser.close()  # CDP 模式下只断开，不杀真人 Chrome
            except Exception:
                pass

    print(f"\n📡 巡逻完毕，本轮共发现 {total_new} 条新链接")
    print(f"   article_queue: {news_db.queue_stats()}")


if __name__ == "__main__":
    patrol()

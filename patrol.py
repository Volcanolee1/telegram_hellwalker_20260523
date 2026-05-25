"""主动巡逻：用同一个真人 Chrome 逐站访问首页，把新文章 URL 推进队列。

信息源矩阵 —— 每条记录写入 DB 时带上 country 和 tags，为后续 bot 分类查询打基础。
  国家代码  US / UK / EU / CN / JP / INTL
  类别代码  MULTI / POL / WAR / BIZZ / ECON / MARKET / TECH

跑法：
  python patrol.py                         # 巡逻全部源
  python patrol.py --only US               # 只巡逻 country=US 的源
  python patrol.py --only EU CN            # 多个国家
  python patrol.py --tag WAR               # 只巡逻含 WAR 标签的源
  python patrol.py --only US --tag TECH    # 交叉过滤（AND 关系）
"""
import argparse
import re
from playwright.sync_api import sync_playwright

import news_db
from browser_cdp import ensure_port_alive, cdp_endpoint, apply_stealth
from sources import Source, HOMEPAGES

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
    return bool(article_re.search(url))


def patrol_one_site(page, src: Source) -> int:
    print(f"\n[巡逻] {src.name} ({src.country}/{','.join(src.tags)}) → {src.homepage}")
    try:
        page.goto(src.homepage, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
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
        if news_db.enqueue(src.name, url, title, country=src.country, tags=tags_str):
            new_count += 1
        else:
            dup_count += 1

    print(f"  ✓ 候选 {len(candidates)} → 新增 {new_count} / 重复 {dup_count} / 跳过 {skip_count}")
    if skip_count > 0 and new_count == 0 and dup_count == 0 and candidates:
        samples = [c["url"] for c in candidates[:3] if c.get("url")]
        print(f"  ℹ️  跳过样例（前3条，请确认正则是否匹配）：")
        for s in samples:
            print(f"      {s}")
    return new_count


def patrol(only_countries: list[str] | None = None,
           only_tag: str | None = None) -> None:
    if not ensure_port_alive():
        return

    news_db.init_db()

    sources = HOMEPAGES
    if only_countries:
        uc = [c.upper() for c in only_countries]
        sources = [s for s in sources if s.country in uc]
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
    ap = argparse.ArgumentParser(description="新闻首页巡逻")
    ap.add_argument("--only", nargs="+", metavar="COUNTRY",
                    help="只巡逻指定国家代码的源，如 US UK CN（空格分隔，可多个）")
    ap.add_argument("--tag", metavar="TAG",
                    help="只巡逻含指定标签的源，如 WAR / TECH / MARKET")
    args = ap.parse_args()
    patrol(only_countries=args.only, only_tag=args.tag)


if __name__ == "__main__":
    main()

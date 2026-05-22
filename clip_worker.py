"""队列消费者：从 article_queue 出队 → CDP 接管真人 Chrome → 抓全文 → 落 article 表。

跑法：
  python clip_worker.py                # 把当前 pending 全部干掉（默认上限 30 条/批）
  python clip_worker.py --limit 5      # 只处理 5 条
  python clip_worker.py --url <link>   # 单条 ad-hoc，不走队列

前提：launch_chrome.bat 已经把真人 Chrome 起到 9222。
"""
import argparse
import random
import time

from playwright.sync_api import sync_playwright

import news_db
from browser_cdp import ensure_port_alive, cdp_endpoint, apply_stealth


# 单页抓取相关
PAGE_TIMEOUT_MS = 60000
PAYWALL_BUFFER_MS = 6000     # 给 Bypass Paywalls Clean 反应的时间
MIN_BODY_LEN = 300           # 短于这个就视为抓取失败
DELAY_BETWEEN_MS = (3500, 7000)  # 每篇之间随机抖动，避开检测

# 多级正文剥离：通杀彭博/路透/NYT/SCMP/AP
EXTRACT_BODY_JS = """
() => {
    const selectors = [
        'article',
        'main article',
        'main',
        '.article-body',
        '.story-content',
        '[class*="ArticleBody"]',
        '[data-testid*="article"]',
        '[itemprop="articleBody"]'
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) {
            const text = (el.innerText || '').trim();
            if (text.length > 300) return { ok: true, body: text, used: sel };
        }
    }
    return { ok: false, body: (document.body.innerText || '').trim(), used: 'body-fallback' };
}
"""


def clip_one(page, url: str) -> tuple[str, str]:
    """抓单篇。返回 (title, body)；任何失败都 raise。"""
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    page.wait_for_timeout(PAYWALL_BUFFER_MS)

    result = page.evaluate(EXTRACT_BODY_JS)
    body = (result.get("body") or "").strip()
    used = result.get("used", "?")

    if not result.get("ok") or len(body) < MIN_BODY_LEN:
        raise RuntimeError(
            f"body too short ({len(body)} chars, selector={used}) — paywall or render fail"
        )

    title = (page.title() or "").strip()
    print(f"     selector={used}  title={title[:60]}  body={len(body)} chars")
    return title, body


def process_queue(limit: int) -> None:
    if not ensure_port_alive():
        return
    news_db.init_db()

    pending = news_db.fetch_pending(limit=limit)
    if not pending:
        print("📭 队列空，没有待抓的链接。")
        print(f"   article_queue: {news_db.queue_stats()}")
        return

    print(f"📥 取出 {len(pending)} 条待抓链接")

    ok_count, fail_count = 0, 0
    with sync_playwright() as p:
        print("🔗 通过 CDP 接管真人 Chrome...")
        browser = p.chromium.connect_over_cdp(cdp_endpoint())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        apply_stealth(page)

        try:
            for i, item in enumerate(pending, 1):
                qid     = item["id"]
                source  = item["source"]
                url     = item["url"]
                title_hint = item["title"]
                country = item.get("country")
                tags    = item.get("tags")
                print(f"\n[{i}/{len(pending)}] {source}({country or '?'})  {url}")

                news_db.mark_clipping(qid)
                try:
                    title, body = clip_one(page, url)
                    news_db.mark_clipped(qid, source, url, title or (title_hint or ""), body,
                                         country=country, tags=tags)
                    ok_count += 1
                    print(f"  ✅ 入库")
                except Exception as e:
                    err = str(e)[:300]
                    news_db.mark_failed(qid, err)
                    fail_count += 1
                    print(f"  ❌ 失败：{err}")

                # 礼貌抖动：避免连续命中同一站点的频控
                if i < len(pending):
                    delay = random.uniform(*DELAY_BETWEEN_MS) / 1000
                    time.sleep(delay)
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                browser.close()  # 仅断开 CDP，不杀真人 Chrome
            except Exception:
                pass

    print(f"\n🏁 本批完成：成功 {ok_count} / 失败 {fail_count}")
    print(f"   article_queue: {news_db.queue_stats()}")
    print(f"   article:       {news_db.article_stats()}")


def process_single(url: str) -> None:
    """ad-hoc 模式：不走队列，直接抓一条并入 article 表。"""
    if not ensure_port_alive():
        return
    news_db.init_db()

    with sync_playwright() as p:
        print("🔗 通过 CDP 接管真人 Chrome...")
        browser = p.chromium.connect_over_cdp(cdp_endpoint())
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        apply_stealth(page)

        try:
            print(f"\n[ad-hoc] {url}")
            try:
                title, body = clip_one(page, url)
            except Exception as e:
                print(f"  ❌ 失败：{e}")
                return

            # ad-hoc 没有 queue_id，借 enqueue+immediate-clip 的路子做最简单落库
            news_db.enqueue("ad-hoc", url, title)
            pending = news_db.fetch_pending(limit=50)
            qid = next((r["id"] for r in pending if r["url"] == url), None)
            if qid is not None:
                news_db.mark_clipping(qid)
                news_db.mark_clipped(qid, "ad-hoc", url, title, body)
                print(f"  ✅ 入库 (queue_id={qid})")
            else:
                # 已经被 clip 过了
                print(f"  ℹ️ 这条 URL 之前已抓过，未重复入库")
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 clip worker")
    parser.add_argument("--limit", type=int, default=30, help="本批最多处理多少条（默认 30）")
    parser.add_argument("--url", type=str, default=None, help="ad-hoc 模式：直接抓单条")
    args = parser.parse_args()

    if args.url:
        process_single(args.url.strip())
    else:
        process_queue(args.limit)


if __name__ == "__main__":
    main()

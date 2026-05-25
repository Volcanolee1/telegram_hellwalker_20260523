"""队列消费者：从 article_queue 出队 → CDP 接管真人 Chrome → 抓全文 → 落 article 表 → 并发送到云端。"""
import argparse
import random
import time
import requests  # 📦 [新增] 用于向云端发送数据的网络库

from playwright.sync_api import sync_playwright

import news_db
from browser_cdp import ensure_port_alive, cdp_endpoint, apply_stealth

# ==========================================
# 📦 [新增] 云端总部连接配置 (请修改为真实IP)
# ==========================================
VPS_API_URL = "http://107.174.159.191:8008/post-news"
API_TOKEN = "h6C99Ylz_qubklLALk0X5Dn12FlFkblh6M013qhySTFezY01TmAaD0aD0"

def ship_to_cloud(source, title, link, summary=""):
    # 🚨 确保 payload 在这里被重新定义，这样函数内才能找到它
    payload = {
        "source": str(source),
        "title": str(title),
        "link": str(link),
        "summary": str(summary)
    }
    headers = {"token": API_TOKEN}
    VPS_LOCAL_URL = "http://127.0.0.1:8008/post-news"
    
    try:
        print(f"  📦 [SSH隧道] 正在通过本地映射通道发往圣何塞...")
        # 🚨 使用刚才定义的 payload 变量
        res = requests.post(VPS_LOCAL_URL, json=payload, headers=headers, timeout=20)
        
        if res.status_code == 200:
            print("  ✅ 圣何塞总部传达室已成功签收！")
        else:
            print(f"  ❌ 总部拒签！原因: {res.text}")
    except Exception as e:
        print(f"  ⚠️ 邮寄断联: {e}")

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
    print(f"    selector={used}  title={title[:60]}  body={len(body)} chars")
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
                    print(f"  ✅ 本地入库完成")
                    
                    # 🚀 [新增] 本地入库成功后，立刻发往圣何塞！
                    ship_to_cloud(source=source, title=title or title_hint, link=url, summary=body)
                    
                    ok_count += 1
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

            news_db.enqueue("ad-hoc", url, title)
            pending = news_db.fetch_pending(limit=50)
            qid = next((r["id"] for r in pending if r["url"] == url), None)
            if qid is not None:
                news_db.mark_clipping(qid)
                news_db.mark_clipped(qid, "ad-hoc", url, title, body)
                print(f"  ✅ 本地入库 (queue_id={qid})")
                
                # 🚀 [新增] 临时模式抓取成功后，也发往圣何塞！
                ship_to_cloud(source="ad-hoc", title=title, link=url, summary=body)
            else:
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
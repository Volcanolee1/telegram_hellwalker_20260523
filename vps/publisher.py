"""Stage 2.2 — Publisher: 把已摘要文章推送到 Telegram 频道。

设计要点：
  - 只挑 summary_status='summarized' AND publish_status='pending' 的文章
  - HTML 排版（与 V1 mvp_news_station.py 风格一致）：标题做蓝链 + 摘要正文
  - SOCKS5 (127.0.0.1:10808) 出海，telebot 通过 requests env var 自动走代理
  - 失败按错误类型分类处理：网络错误退出本批以免雪崩，业务错误（被频道拒绝、消息格式炸）继续

跑法：
  python publisher.py --dry-run        # 只打印消息预览，不真发
  python publisher.py --limit 1        # 真发 1 条试水
  python publisher.py --limit 20       # 真发一批
  python publisher.py --retry          # 把 failed 重置为 pending 后再发
"""
import argparse
import time
from html import escape

import telebot

from config_loader import TG_BOT_TOKEN, US_CHANNEL, CN_CHANNEL, PROXY_URL
import news_db


DELAY_BETWEEN_S = 2.0   # 礼貌间隔，TG 频道 30 msg/sec 上限远高于这个，纯防节奏太密

CHANNEL_MAP = {"US": US_CHANNEL, "CN": CN_CHANNEL}


from sources import SOURCE_CHANNEL_MAP

DEFAULT_CHANNEL = "US"


def resolve_channel(source: str) -> tuple[str, str]:
    """返回 (region_label, channel_id)。"""
    region = SOURCE_CHANNEL_MAP.get(source, DEFAULT_CHANNEL)
    channel = CHANNEL_MAP.get(region)
    if not channel:
        raise RuntimeError(f"未找到 {region} 对应的频道，请检查 config.json 和 CHANNEL_MAP")
    return region, channel


def format_message(source: str, title: str, url: str, summary: str) -> str:
    """HTML 格式：标题做蓝链 + 摘要正文。所有用户可控字段必须 escape。"""
    return (
        f"<b>🔔 【{escape(source)} 一手情报】</b>\n"
        f"<a href=\"{escape(url, quote=True)}\">{escape(title)}</a>\n\n"
        f"{escape(summary)}"
    )


def run(limit: int, dry_run: bool, retry: bool) -> None:
    if not TG_BOT_TOKEN:
        print("❌ TG_BOT_TOKEN 未配置，请检查 config.yaml")
        return

    news_db.init_db()

    if retry:
        n = news_db.reset_publish_failed_to_pending()
        print(f"🔄 重试模式：已把 {n} 条 发布失败 重置为 summarized")

    pending = news_db.fetch_pending_publish(limit=limit)
    if not pending:
        print("📭 没有待发送的文章。")
        print(f"  publish 状态分布: {news_db.publish_stats()}")
        return

    print(f"📥 取出 {len(pending)} 条待发送文章")
    if dry_run:
        print("🧪 DRY-RUN：只预览消息，不真发\n")
    else:
        print(f"🔌 通过 {PROXY_URL} 接入 Telegram\n")

    bot = telebot.TeleBot(TG_BOT_TOKEN) if not dry_run else None
    ok, fail, aborted = 0, 0, False

    for i, art in enumerate(pending, 1):
        aid = art["id"]
        source = art["source"] or "?"
        title = art["title"] or ""
        url = art["url"] or ""
        summary = art["summary"] or ""

        try:
            region, channel = resolve_channel(source)
        except Exception as e:
            news_db.mark_publish_failed(aid, str(e))
            fail += 1
            print(f"[{i}/{len(pending)}] ❌ 频道路由失败：{e}")
            continue

        msg = format_message(source, title, url, summary)
        print(f"[{i}/{len(pending)}] [{source} → {region}/{channel}] {title[:60]}")

        if dry_run:
            print("    --- 消息预览 ---")
            for line in msg.splitlines():
                print(f"    | {line}")
            print("    ----------------\n")
            ok += 1
            continue

        news_db.mark_publishing(aid)
        try:
            bot.send_message(
                channel, msg,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        except Exception as e:
            err = str(e)[:500]
            news_db.mark_publish_failed(aid, err)
            fail += 1
            print(f"    ❌ 发送失败：{err[:200]}")
            # 网络/代理类系统性错误，整批中止
            low = err.lower()
            if any(s in low for s in ("connection", "timeout", "proxy", "socks", "unreachable")):
                print("    ⛔ 网络/代理类错误，本批中止。")
                aborted = True
                break
            time.sleep(DELAY_BETWEEN_S)
            continue

        news_db.mark_published(aid)
        ok += 1
        print(f"    ✅ 已推送")
        time.sleep(DELAY_BETWEEN_S)

    print("\n🏁 本批结束" + ("（中止）" if aborted else ""))
    print(f"   成功 {ok} / 失败 {fail}" + ("（dry-run 不计实际推送）" if dry_run else ""))
    print(f"   publish 状态分布: {news_db.publish_stats()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5,
                    help="本批最多处理多少条（默认 5）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印消息预览，不真发到 TG")
    ap.add_argument("--retry", action="store_true",
                    help="把 publish_status=failed 的也重试一次")
    args = ap.parse_args()
    run(args.limit, args.dry_run, args.retry)


if __name__ == "__main__":
    main()

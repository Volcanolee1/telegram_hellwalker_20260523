"""Stage 2.1 — AI 摘要器：从 article 表取未摘要条目 → Gemini → 回写 summary。

设计要点：
  - 通过 SOCKS5 隧道（127.0.0.1:10808）出海，复用 V1 mvp_news_station.py 验证过的方式
  - 模型 gemini-3.1-flash-lite（用户每天 1.5M token 配额，放开用）
  - 不发 TG！发推交给 Stage 2.2 的 publisher.py。摘要变独立资产，
    意味着可以反复重跑、可以让 VPS 直接读 summary 兜底广播
  - 失败状态分级：单条 failed 不影响其他文章；超出配额时整批退出

跑法：
  python summarizer.py                # 默认处理 5 条
  python summarizer.py --limit 20     # 一批 20 条
  python summarizer.py --retry        # 把 status=failed 的也重试一遍
"""
import argparse
import time

from google.genai import Client
from google.genai import types

# 初始化客户端，这样写才对


from config_loader import GEMINI_API_KEY, PROXY_URL
import news_db


MODEL = "gemini-3.1-flash-lite"
MAX_INPUT_CHARS = 8000          # 单篇正文最多送多少字符（防止过长 token 浪费）
DELAY_BETWEEN_S = 1.5           # 每条之间的礼貌间隔


SYSTEM_INSTRUCTION = (
    "你是一位深谙地缘政治、国际冲突与宏观经济的资深通讯社情报分析员。\n"
    "请阅读用户提供的英文新闻原文，过滤掉广告、版权声明、订阅引导、作者介绍、"
    "无关导航等噪音，提取核心商业/政治事实。\n"
    "用极其凝练、辛辣且中立的简体中文输出 150 字以内的情报快报。\n\n"
    "【写作规范】\n"
    "1. 禁止地摊文学、谣言和煽动性表述，保持严肃媒体的操守。\n"
    "2. 一句话提炼核心论点，紧跟若干条关键事实/数字/影响。\n"
    "3. 拒绝翻译腔和啰嗦的转述。直接给结论和事实。\n"
    "4. 不要使用 Markdown 语法，不要使用 HTML 标签，输出纯文本。\n"
    "5. 不要重复原标题，不要写'本文报道...'之类的元描述。"
)


def make_client() -> Client:
    http_options = types.HttpOptions(client_args={"proxy": PROXY_URL})
    return Client(api_key=GEMINI_API_KEY, http_options=http_options)

def summarize_one(client: Client, source: str, title: str, body: str) -> str:
    body_clipped = (body or "")[:MAX_INPUT_CHARS]
    user_content = (
        f"来源: {source}\n"
        f"标题: {title}\n\n"
        f"原文:\n{body_clipped}"
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.3,
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini 返回空文本")
    return text


def reset_failed_to_pending() -> int:
    """把摘要失败的条目改回 clipped，让本批次重试（只重置 summary 阶段的失败）。"""
    with news_db.conn() as c:
        n = c.execute(
            "UPDATE article SET status='clipped', summary_error=NULL "
            "WHERE status='failed' AND summary_error IS NOT NULL"
        ).rowcount
    return n


def run(limit: int, retry: bool) -> None:
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY 未配置，请检查 config.yaml")
        return

    news_db.init_db()

    if retry:
        n_reset = reset_failed_to_pending()
        print(f"🔄 重试模式：已把 {n_reset} 条 failed 重置为 pending")

    pending = news_db.fetch_pending_summary(limit=limit)
    if not pending:
        print("📭 没有待摘要的文章。")
        print(f"  summary 状态分布: {news_db.summary_stats()}")
        return

    print(f"📥 取出 {len(pending)} 条待摘要文章")
    print(f"🔌 通过 {PROXY_URL} 接入 Gemini ({MODEL})\n")

    client = make_client()
    ok, fail = 0, 0
    aborted = False

    for i, art in enumerate(pending, 1):
        aid = art["id"]
        source = art["source"] or "?"
        title = art["title"] or ""
        body = art["body"] or ""
        body_chars = min(len(body), MAX_INPUT_CHARS)

        print(f"[{i}/{len(pending)}] [{source}] {title[:60]}")
        print(f"    body={len(body)} chars → 送 {body_chars} chars 给模型")

        news_db.mark_summarizing(aid)
        try:
            summary = summarize_one(client, source, title, body)
        except Exception as e:
            err = str(e)[:500]
            news_db.mark_summary_failed(aid, err)
            fail += 1
            print(f"    ❌ 失败：{err[:200]}")
            # 配额耗尽这种系统性错误，整批中止避免烧掉更多请求
            low = err.lower()
            if any(s in low for s in ("quota", "rate limit", "resource_exhausted", "429")):
                print("    ⛔ 检测到配额/限流类错误，本批中止。")
                aborted = True
                break
            time.sleep(DELAY_BETWEEN_S)
            continue

        news_db.mark_summarized(aid, summary, MODEL, body_chars)
        ok += 1
        print(f"    ✅ 摘要 ({len(summary)} 字)：{summary[:120]}{'…' if len(summary) > 120 else ''}\n")
        time.sleep(DELAY_BETWEEN_S)

    print("\n🏁 本批结束" + ("（中止）" if aborted else ""))
    print(f"   成功 {ok} / 失败 {fail}")
    print(f"   summary 状态分布: {news_db.summary_stats()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5,
                    help="本批最多处理多少条（默认 5；首次试水别一次性烧太多）")
    ap.add_argument("--retry", action="store_true",
                    help="把已经 failed 的也重试一次")
    args = ap.parse_args()
    run(args.limit, args.retry)


if __name__ == "__main__":
    main()

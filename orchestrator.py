"""Stage 2.3 — 编排器：定时跑完整流水线 patrol → clip → summarize → publish。

每个 CYCLE_INTERVAL 分钟执行一轮，各步骤独立 try/except，任一步失败不影响其他步骤。
Chrome 没开时 patrol/clip 自动跳过，summarize/publish 照常运行（不依赖浏览器）。

跑法：
  python orchestrator.py                     # 默认每 30 分钟一轮
  python orchestrator.py --interval 15       # 每 15 分钟一轮（如果你想更快更新）
  python orchestrator.py --once              # 只跑一轮就退出（手动触发用）
  python orchestrator.py --skip-patrol       # 跳过巡逻（Chrome 没开时）
"""
import argparse
import sys
import time
import traceback
from datetime import datetime

import news_db

# ── 各步骤默认批量上限 ──────────────────────────────────────────
CLIP_BATCH     = 20   # 每轮最多 clip 多少篇（太大会让 Chrome 一直工作）
SUMMARY_BATCH  = 10   # 每轮最多摘要多少篇（~30-40k token/轮）
PUBLISH_BATCH  = 5    # 每轮最多推 TG 多少篇（避免一次性刷屏频道）


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def step_patrol() -> None:
    from patrol import patrol
    print(f"\n[{ts()}] ── PATROL ──")
    patrol()


def step_clip(batch: int) -> None:
    from clip_worker import process_queue
    print(f"\n[{ts()}] ── CLIP (max {batch}) ──")
    process_queue(limit=batch)


def step_summarize(batch: int) -> None:
    from summarizer import run as summarize_run
    print(f"\n[{ts()}] ── SUMMARIZE (max {batch}) ──")
    summarize_run(limit=batch, retry=False)


def step_publish(batch: int) -> None:
    from publisher import run as publish_run
    print(f"\n[{ts()}] ── PUBLISH (max {batch}) ──")
    publish_run(limit=batch, dry_run=False, retry=False)


def run_cycle(skip_patrol: bool, clip_batch: int, summary_batch: int, publish_batch: int) -> None:
    print(f"\n{'='*60}")
    print(f"[{ts()}] 开始新一轮流水线")
    print(f"{'='*60}")

    steps = []
    if not skip_patrol:
        steps.append(("patrol", lambda: step_patrol()))
    steps += [
        ("clip",      lambda: step_clip(clip_batch)),
        ("summarize", lambda: step_summarize(summary_batch)),
        ("publish",   lambda: step_publish(publish_batch)),
    ]

    for name, fn in steps:
        try:
            fn()
        except KeyboardInterrupt:
            raise
        except Exception:
            print(f"\n[{ts()}] ⚠️  {name} 步骤异常（已记录，继续下一步）：")
            traceback.print_exc(limit=4)

    print(f"\n[{ts()}] 本轮完成。DB 快照：")
    try:
        print(f"  queue:   {news_db.queue_stats()}")
        print(f"  article: {news_db.article_stats()}")
        print(f"  summary: {news_db.summary_stats()}")
        print(f"  publish: {news_db.publish_stats()}")
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="news_commander 编排器")
    ap.add_argument("--interval", type=int, default=30,
                    help="两轮之间的间隔分钟数（默认 30）")
    ap.add_argument("--once", action="store_true",
                    help="只跑一轮就退出")
    ap.add_argument("--skip-patrol", action="store_true",
                    help="跳过巡逻步骤（比如 Chrome 没开又不想等）")
    ap.add_argument("--clip-batch",    type=int, default=CLIP_BATCH)
    ap.add_argument("--summary-batch", type=int, default=SUMMARY_BATCH)
    ap.add_argument("--publish-batch", type=int, default=PUBLISH_BATCH)
    args = ap.parse_args()

    news_db.init_db()

    if args.once:
        run_cycle(args.skip_patrol, args.clip_batch, args.summary_batch, args.publish_batch)
        return

    interval_s = args.interval * 60
    print(f"🚀 编排器启动，间隔 {args.interval} 分钟 / Ctrl+C 退出")
    print(f"   clip≤{args.clip_batch}  summarize≤{args.summary_batch}  publish≤{args.publish_batch}")

    cycle = 0
    while True:
        cycle += 1
        print(f"\n第 {cycle} 轮")
        try:
            run_cycle(args.skip_patrol, args.clip_batch, args.summary_batch, args.publish_batch)
        except KeyboardInterrupt:
            print(f"\n[{ts()}] 收到 Ctrl+C，退出。")
            sys.exit(0)

        next_time = datetime.now().strftime("%H:%M")
        print(f"\n[{ts()}] 休眠 {args.interval} 分钟，下次约 {next_time} + {args.interval}min 后唤醒")
        try:
            time.sleep(interval_s)
        except KeyboardInterrupt:
            print(f"\n[{ts()}] 收到 Ctrl+C（休眠中），退出。")
            sys.exit(0)


if __name__ == "__main__":
    main()

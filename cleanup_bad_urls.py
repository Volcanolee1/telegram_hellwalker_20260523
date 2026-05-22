"""清洗历史数据：用 patrol.py 里新的 per-source URL 正则，
重新审视 article_queue 和 article 表里已有的记录，
把不像单篇文章的 URL 清理掉（避免污染 AI summary 阶段）。

跑法：
  python cleanup_bad_urls.py             # dry-run，只报告不改动
  python cleanup_bad_urls.py --apply     # 真正执行删除
"""
import argparse
import sqlite3
from pathlib import Path

from patrol import HOMEPAGES  # 复用同一份精筛正则

DB = Path(__file__).parent / "commander.db"

# source -> 正则 的快速查表
SOURCE_RE = {src: art_re for src, _, _, art_re in HOMEPAGES}


def find_bad_rows(conn) -> tuple[list[tuple], list[tuple]]:
    """返回 (bad_queue_rows, bad_article_rows)，每条带 (id, source, url, title)。"""
    bad_queue, bad_article = [], []

    for row in conn.execute(
        "SELECT id, source, url, title FROM article_queue WHERE source IN (?,?,?,?,?)",
        tuple(SOURCE_RE.keys()),
    ):
        rid, src, url, title = row
        rgx = SOURCE_RE.get(src)
        if rgx and not rgx.search(url):
            bad_queue.append(row)

    for row in conn.execute(
        "SELECT id, source, url, title FROM article WHERE source IN (?,?,?,?,?)",
        tuple(SOURCE_RE.keys()),
    ):
        rid, src, url, title = row
        rgx = SOURCE_RE.get(src)
        if rgx and not rgx.search(url):
            bad_article.append(row)

    return bad_queue, bad_article


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="真正执行删除；不加这个参数只是 dry-run 报告")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    bad_queue, bad_article = find_bad_rows(conn)

    print(f"\n=== article_queue 中疑似栏目页/导航链接：{len(bad_queue)} 条 ===")
    for rid, src, url, title in bad_queue[:30]:
        print(f"  [{src}] {url}")
        print(f"     title: {title[:80]}")
    if len(bad_queue) > 30:
        print(f"  ...（还有 {len(bad_queue)-30} 条未列出）")

    print(f"\n=== article 表（已抓正文）中疑似污染：{len(bad_article)} 条 ===")
    for rid, src, url, title in bad_article[:30]:
        print(f"  [{src}] {url}")
        print(f"     title: {title[:80]}")
    if len(bad_article) > 30:
        print(f"  ...（还有 {len(bad_article)-30} 条未列出）")

    if not args.apply:
        print("\n💡 当前是 dry-run。确认后请加 --apply 真正执行。")
        print("   article_queue: 改 status='skipped'（保留记录、不再被 worker 取出）")
        print("   article:       直接 DELETE（避免污染后续 AI summary）")
        conn.close()
        return

    # 执行清理
    if bad_queue:
        ids = [r[0] for r in bad_queue]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE article_queue SET status='skipped', last_error='cleanup: not an article URL' "
            f"WHERE id IN ({placeholders})",
            ids,
        )
    if bad_article:
        ids = [r[0] for r in bad_article]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM article WHERE id IN ({placeholders})", ids)
    conn.commit()
    print(f"\n✅ 已清理：article_queue {len(bad_queue)} 条转 skipped，article {len(bad_article)} 条删除")
    conn.close()


if __name__ == "__main__":
    main()

"""临时把某个源的 pending 链接标为 skipped，不让 worker 去抓它。

跑法：
  python skip_source.py Bloomberg          # 跳过 Bloomberg
  python skip_source.py Bloomberg --undo   # 恢复回 pending
"""
import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "commander.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="源名，如 Bloomberg / Reuters / NYT / SCMP / APNews")
    ap.add_argument("--undo", action="store_true", help="把 skipped 改回 pending")
    args = ap.parse_args()

    src, undo = args.source, args.undo
    from_status, to_status = ("skipped", "pending") if undo else ("pending", "skipped")

    with sqlite3.connect(DB) as c:
        n = c.execute(
            "UPDATE article_queue SET status=? WHERE source=? AND status=?",
            (to_status, src, from_status),
        ).rowcount
        c.commit()

    action = "恢复" if undo else "跳过"
    print(f"已{action} {src} {n} 条 ({from_status} → {to_status})")

    with sqlite3.connect(DB) as c:
        rows = c.execute(
            "SELECT status, COUNT(*) FROM article_queue WHERE source=? GROUP BY status",
            (src,),
        ).fetchall()
    print(f"  {src} 当前分布：{dict(rows) if rows else '空'}")


if __name__ == "__main__":
    main()

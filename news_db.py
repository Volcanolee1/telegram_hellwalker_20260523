"""本地 SQLite 数据层。

两张核心表：
  article_queue —— 巡逻发现的候选链接，等待 clip
  article       —— clip 成功的成品文章（带全文 body）

故意不复用 V1 的 news_data.db，避免新旧 schema 互相污染。
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "commander.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS article_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT,
    country         TEXT,
    tags            TEXT,
    discovered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status          TEXT NOT NULL DEFAULT 'pending',
    -- pending → clipping → clipped | failed
    -- skipped 可由人工手动设置（不感兴趣的链接）
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    last_attempt_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON article_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_discovered ON article_queue(discovered_at);

CREATE TABLE IF NOT EXISTS article (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id        INTEGER,
    source          TEXT,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT,
    body            TEXT,
    body_length     INTEGER,
    clipped_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sync_status     TEXT DEFAULT 'pending',
    -- pending → synced | failed (向 VPS 同步状态)
    synced_at       TIMESTAMP,
    publish_status  TEXT DEFAULT 'pending',
    -- pending → published | failed (TG 推送状态)

    -- Stage 2.1 摘要相关（通过 _migrate 动态加列保证旧 DB 也能升上来）
    summary             TEXT,
    summary_status      TEXT DEFAULT 'pending',
    -- pending → summarizing → summarized | failed | skipped
    summary_at          TIMESTAMP,
    summary_model       TEXT,
    summary_input_chars INTEGER,
    summary_error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_article_sync ON article(sync_status);
CREATE INDEX IF NOT EXISTS idx_article_publish ON article(publish_status);
-- idx_article_summary 索引在 _migrate() 里建，因为旧 DB 这时候还没 summary_status 列
"""

# 动态迁移：旧 DB 没有对应列时自动补上
QUEUE_NEW_COLUMNS = {
    "country": "country TEXT",
    "tags":    "tags TEXT",
}

ARTICLE_NEW_COLUMNS = {
    "summary":             "summary TEXT",
    "summary_status":      "summary_status TEXT DEFAULT 'pending'",
    "summary_at":          "summary_at TIMESTAMP",
    "summary_model":       "summary_model TEXT",
    "summary_input_chars": "summary_input_chars INTEGER",
    "summary_error":       "summary_error TEXT",
    "publish_at":          "publish_at TIMESTAMP",
    "publish_error":       "publish_error TEXT",
    "country":             "country TEXT",
    "tags":                "tags TEXT",
}


def _migrate(c) -> None:
    # article_queue 新列
    existing_queue = {r["name"] for r in c.execute("PRAGMA table_info(article_queue)")}
    for col, ddl in QUEUE_NEW_COLUMNS.items():
        if col not in existing_queue:
            c.execute(f"ALTER TABLE article_queue ADD COLUMN {ddl}")
            print(f"  + 已为 article_queue 表新增列: {col}")
    # article 新列
    existing = {r["name"] for r in c.execute("PRAGMA table_info(article)")}
    for col, ddl in ARTICLE_NEW_COLUMNS.items():
        if col not in existing:
            c.execute(f"ALTER TABLE article ADD COLUMN {ddl}")
            print(f"  + 已为 article 表新增列: {col}")
    # 索引补建（CREATE IF NOT EXISTS 幂等）
    c.execute("CREATE INDEX IF NOT EXISTS idx_article_summary ON article(summary_status)")

MAX_ATTEMPTS = 3


def _round_robin(rows: list[dict], limit: int) -> list[dict]:
    """从多来源行里按轮询方式取 limit 条，确保单源不会垄断一批次。"""
    from collections import defaultdict
    buckets: dict[str, list] = defaultdict(list)
    for r in rows:
        buckets[r["source"]].append(r)
    sources = sorted(buckets.keys())
    result: list[dict] = []
    i = 0
    while len(result) < limit and any(buckets[s] for s in sources):
        s = sources[i % len(sources)]
        if buckets[s]:
            result.append(buckets[s].pop(0))
        i += 1
    return result


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA foreign_keys=ON;")
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
        _migrate(c)


# 公共连接：让外部模块（summarizer / publisher）借用同一套 PRAGMA + Row factory
@contextmanager
def conn():
    with _conn() as c:
        yield c


# ============ 队列写入：巡逻发现新链接 ============

def enqueue(source: str, url: str, title: str | None = None,
            country: str | None = None, tags: str | None = None) -> bool:
    """新链接入队。返回 True 表示是新链接，False 表示已存在。"""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO article_queue (source, url, title, country, tags) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, url, title, country, tags),
        )
        return cur.rowcount > 0


# ============ 队列出队：clipper 取活干 ============

def fetch_pending(limit: int = 10) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, source, url, title, country, tags FROM article_queue "
            "WHERE status = 'pending' AND attempt_count < ? "
            "ORDER BY discovered_at ASC LIMIT ?",
            (MAX_ATTEMPTS, limit * 5),   # 多取以便轮询均分
        ).fetchall()
    return _round_robin([dict(r) for r in rows], limit)


def mark_clipping(queue_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article_queue SET status='clipping', "
            "  attempt_count = attempt_count + 1, "
            "  last_attempt_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (queue_id,),
        )


def mark_clipped(queue_id: int, source: str, url: str, title: str, body: str,
                 country: str | None = None, tags: str | None = None) -> None:
    """clip 成功：把全文落到 article 表，队列条目转 clipped。原子事务。"""
    with _conn() as c:
        c.execute(
            "UPDATE article_queue SET status='clipped' WHERE id = ?",
            (queue_id,),
        )
        c.execute(
            "INSERT OR IGNORE INTO article "
            "  (queue_id, source, url, title, body, body_length, country, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (queue_id, source, url, title, body, len(body or ""), country, tags),
        )


def mark_failed(queue_id: int, error: str) -> None:
    """clip 失败：尝试次数没用完则回到 pending 等下次重试，用完则标 failed。"""
    with _conn() as c:
        c.execute(
            "UPDATE article_queue SET "
            "  status = CASE WHEN attempt_count >= ? THEN 'failed' ELSE 'pending' END, "
            "  last_error = ? "
            "WHERE id = ?",
            (MAX_ATTEMPTS, error, queue_id),
        )


# ============ 状态/调试 ============

def queue_stats() -> dict:
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM article_queue GROUP BY status"
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def article_stats() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM article").fetchone()["n"]
        unsynced = c.execute(
            "SELECT COUNT(*) AS n FROM article WHERE sync_status='pending'"
        ).fetchone()["n"]
        unpublished = c.execute(
            "SELECT COUNT(*) AS n FROM article WHERE publish_status='pending'"
        ).fetchone()["n"]
    return {"total": total, "unsynced": unsynced, "unpublished": unpublished}


def summary_stats() -> dict:
    with _conn() as c:
        rows = c.execute(
            "SELECT summary_status, COUNT(*) AS n FROM article GROUP BY summary_status"
        ).fetchall()
    return {r["summary_status"] or "(null)": r["n"] for r in rows}


# ============ Stage 2.1: summarizer 用的查询/写入 ============

def fetch_pending_summary(limit: int = 5) -> list[dict]:
    """取出待摘要的成品文章，按来源轮询确保各源均匀。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, source, title, body, url FROM article "
            "WHERE summary_status = 'pending' "
            "ORDER BY id ASC LIMIT ?",
            (limit * 5,),   # 多取以便轮询有足够候选
        ).fetchall()
    return _round_robin([dict(r) for r in rows], limit)


def mark_summarizing(article_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET summary_status='summarizing' WHERE id = ?",
            (article_id,),
        )


def mark_summarized(article_id: int, summary: str, model: str, input_chars: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET "
            "  summary = ?, "
            "  summary_status = 'summarized', "
            "  summary_at = CURRENT_TIMESTAMP, "
            "  summary_model = ?, "
            "  summary_input_chars = ?, "
            "  summary_error = NULL "
            "WHERE id = ?",
            (summary, model, input_chars, article_id),
        )


def mark_summary_failed(article_id: int, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET "
            "  summary_status = 'failed', "
            "  summary_error = ? "
            "WHERE id = ?",
            (error, article_id),
        )


# ============ Stage 2.2: publisher 用的查询/写入 ============

def fetch_pending_publish(limit: int = 5) -> list[dict]:
    """取出"已摘要、未发布"的文章，按来源轮询确保各源均匀。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, source, title, url, summary FROM article "
            "WHERE summary_status = 'summarized' "
            "  AND publish_status = 'pending' "
            "  AND summary IS NOT NULL "
            "ORDER BY id ASC LIMIT ?",
            (limit * 5,),   # 多取以便轮询有足够候选
        ).fetchall()
    return _round_robin([dict(r) for r in rows], limit)


def mark_publishing(article_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET publish_status='publishing' WHERE id = ?",
            (article_id,),
        )


def mark_published(article_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET "
            "  publish_status = 'published', "
            "  publish_at = CURRENT_TIMESTAMP, "
            "  publish_error = NULL "
            "WHERE id = ?",
            (article_id,),
        )


def mark_publish_failed(article_id: int, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET "
            "  publish_status = 'failed', "
            "  publish_error = ? "
            "WHERE id = ?",
            (error, article_id),
        )


def reset_publish_failed_to_pending() -> int:
    with _conn() as c:
        n = c.execute(
            "UPDATE article SET publish_status='pending', publish_error=NULL "
            "WHERE publish_status='failed'"
        ).rowcount
    return n


def publish_stats() -> dict:
    with _conn() as c:
        rows = c.execute(
            "SELECT publish_status, COUNT(*) AS n FROM article GROUP BY publish_status"
        ).fetchall()
    return {r["publish_status"] or "(null)": r["n"] for r in rows}


if __name__ == "__main__":
    init_db()
    print(f"✓ 数据库已就绪：{DB_PATH}")
    print(f"  article_queue: {queue_stats()}")
    print(f"  article:       {article_stats()}")
    print(f"  summary:       {summary_stats()}")
    print(f"  publish:       {publish_stats()}")

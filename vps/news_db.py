"""本地 SQLite 数据层。

两张核心表：
  article_queue —— 巡逻发现的候选链接，等待 clip
  article       —— clip 成功的成品文章（带全文 body）

pipeline 线性状态机（status 列）：
  clipped → summarizing → summarized → publishing → published
                ↓                    ↓
              failed  ←─────────────┘

每次状态推进由单一 status 列保证，杜绝"已发布但未摘要"这类非法状态。
"""
import sqlite3
from collections import defaultdict
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

    -- 统一线性状态（替换旧的 sync_status / summary_status / publish_status）
    status          TEXT NOT NULL DEFAULT 'clipped'
                    CHECK (status IN ('clipped','summarizing','summarized',
                                      'publishing','published','failed','skipped')),

    -- 摘要结果
    summary             TEXT,
    summary_at          TIMESTAMP,
    summary_model       TEXT,
    summary_input_chars INTEGER,
    summary_error       TEXT,

    -- 发布结果
    publish_at          TIMESTAMP,
    publish_error       TEXT,

    -- 旧 sync_status 已废弃，保留列定义仅用于存量数据兼容
    sync_status     TEXT,
    synced_at       TIMESTAMP,

    -- 源属性（patrol 阶段写入）
    country         TEXT,
    tags            TEXT
);

-- idx_article_status 索引在 _migrate() 里建（旧 DB 还没有 status 列）
"""

# 动态迁移：旧 DB 没有对应列时自动补上
QUEUE_NEW_COLUMNS = {
    "country": "country TEXT",
    "tags":    "tags TEXT",
}

ARTICLE_NEW_COLUMNS = {
    "summary":             "summary TEXT",
    "summary_at":          "summary_at TIMESTAMP",
    "summary_model":       "summary_model TEXT",
    "summary_input_chars": "summary_input_chars INTEGER",
    "summary_error":       "summary_error TEXT",
    "publish_at":          "publish_at TIMESTAMP",
    "publish_error":       "publish_error TEXT",
    "country":             "country TEXT",
    "tags":                "tags TEXT",
    "summary_status":      "summary_status TEXT DEFAULT 'pending'",
    "publish_status":      "publish_status TEXT DEFAULT 'pending'",
}

MAX_ATTEMPTS = 3


def _round_robin(rows: list[dict], limit: int) -> list[dict]:
    """从多来源行里按轮询方式取 limit 条，确保单源不会垄断一批次。"""
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

    # 统一 status 列迁移：旧 DB 用三个独立状态列 → 新 DB 用单一 status
    if "status" not in existing:
        c.execute("ALTER TABLE article ADD COLUMN status TEXT NOT NULL DEFAULT 'clipped'")
        # 从旧列聚合出当前状态：优先取最晚阶段的
        c.execute("""
            UPDATE article SET status = CASE
                WHEN publish_status = 'published'  THEN 'published'
                WHEN publish_status = 'publishing' THEN 'publishing'
                WHEN summary_status = 'summarized' THEN 'summarized'
                WHEN summary_status = 'summarizing' THEN 'summarizing'
                WHEN summary_status = 'failed' OR publish_status = 'failed' THEN 'failed'
                ELSE 'clipped'
            END
        """)
        print("  + 已添加统一 status 列并从旧状态列迁移数据")

    # 索引补建（CREATE IF NOT EXISTS 幂等）
    c.execute("CREATE INDEX IF NOT EXISTS idx_article_status ON article(status)")
    # 为旧 DB 添加 trigger 约束（等价于新 DB 的 CHECK，SQLite ALTER TABLE 不支持直接加 CHECK）
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS check_article_status
        BEFORE UPDATE ON article
        WHEN NEW.status NOT IN ('clipped','summarizing','summarized',
                                'publishing','published','failed','skipped')
        BEGIN
            SELECT RAISE(ABORT, 'Invalid pipeline status');
        END;
    """)
    c.execute("""
        CREATE TRIGGER IF NOT EXISTS check_article_status_insert
        BEFORE INSERT ON article
        WHEN NEW.status NOT IN ('clipped','summarizing','summarized',
                                'publishing','published','failed','skipped')
        BEGIN
            SELECT RAISE(ABORT, 'Invalid pipeline status');
        END;
    """)


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
        _migrate(c)


# 公共连接：让外部模块借用同一套 PRAGMA + Row factory
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
            (MAX_ATTEMPTS, limit * 5),
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
    """统一状态分布（替代旧的 article_stats / summary_stats / publish_stats）。"""
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM article").fetchone()["n"]
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM article GROUP BY status"
        ).fetchall()
    result = {r["status"]: r["n"] for r in rows}
    result["total"] = total
    return result


# 保持旧函数签名以兼容现有调用方
def summary_stats() -> dict:
    """摘要阶段状态（从统一 status 列派生，兼容旧调用方）。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM article "
            "WHERE status IN ('clipped','summarizing','summarized','failed') "
            "GROUP BY status"
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def publish_stats() -> dict:
    """发布阶段状态（从统一 status 列派生，兼容旧调用方）。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM article "
            "WHERE status IN ('summarized','publishing','published','failed') "
            "GROUP BY status"
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


# ============ Stage 2.1: summarizer 用的查询/写入 ============

def fetch_pending_summary(limit: int = 5) -> list[dict]:
    """取出待摘要的成品文章（status='clipped'），按来源轮询。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, source, title, body, url FROM article "
            "WHERE status = 'clipped' "
            "ORDER BY id ASC LIMIT ?",
            (limit * 5,),
        ).fetchall()
    return _round_robin([dict(r) for r in rows], limit)


def mark_summarizing(article_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET status='summarizing' WHERE id = ?",
            (article_id,),
        )


def mark_summarized(article_id: int, summary: str, model: str, input_chars: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET "
            "  summary = ?, "
            "  status = 'summarized', "
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
            "  status = 'failed', "
            "  summary_error = ? "
            "WHERE id = ?",
            (error, article_id),
        )


# ============ Stage 2.2: publisher 用的查询/写入 ============

def fetch_pending_publish(limit: int = 5) -> list[dict]:
    """取出"已摘要、未发布"的文章，按来源轮询。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, source, title, url, summary FROM article "
            "WHERE status = 'summarized' "
            "  AND summary IS NOT NULL "
            "ORDER BY id ASC LIMIT ?",
            (limit * 5,),
        ).fetchall()
    return _round_robin([dict(r) for r in rows], limit)


def mark_publishing(article_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET status='publishing' WHERE id = ?",
            (article_id,),
        )


def mark_published(article_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET "
            "  status = 'published', "
            "  publish_at = CURRENT_TIMESTAMP, "
            "  publish_error = NULL "
            "WHERE id = ?",
            (article_id,),
        )


def mark_publish_failed(article_id: int, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE article SET "
            "  status = 'failed', "
            "  publish_error = ? "
            "WHERE id = ?",
            (error, article_id),
        )


def reset_publish_failed_to_pending() -> int:
    """把 publish 失败的条目重置回 summarized（仅当是自己这步失败的）。"""
    with _conn() as c:
        n = c.execute(
            "UPDATE article SET status='summarized', publish_error=NULL "
            "WHERE status='failed' AND publish_error IS NOT NULL"
        ).rowcount
    return n


if __name__ == "__main__":
    init_db()
    print(f"✓ 数据库已就绪：{DB_PATH}")
    print(f"  article_queue: {queue_stats()}")
    print(f"  article:       {article_stats()}")

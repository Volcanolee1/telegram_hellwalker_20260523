from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel
import threading

from vps_orchestrator import run_cloud_cycle
from config_loader import API_TOKEN
from sources import HOMEPAGES
import news_db

# source → (country, tags) 映射表，API 入库时用
_SOURCE_META: dict[str, tuple[str, str]] = {
    s.name: (s.country, ",".join(s.tags)) for s in HOMEPAGES
}

app = FastAPI()

# 防并发：同一时间只允许一个流水线实例运行
_pipeline_lock = threading.Lock()
_pipeline_running = False

def _safe_pipeline():
    global _pipeline_running
    with _pipeline_lock:
        if _pipeline_running:
            print("  -> 流水线已在运行中，跳过本次调度")
            return
        _pipeline_running = True
    try:
        run_cloud_cycle()
    finally:
        with _pipeline_lock:
            _pipeline_running = False


class NewsItema(BaseModel):
    source: str
    title: str
    link: str
    summary: str

# 心跳接口
@app.get("/health")
async def health():
    return {"status": "ok", "message": "云端传达室大爷很健康，随时可以接单！"}

# 接收新闻接口
@app.post("/post-news")
async def post_news(news: NewsItema, background_tasks: BackgroundTasks, token: str = Header(...)):
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="暗号不对，大爷拒绝开门！")

    print(f"收到前线发来的情报: {news.title[:20]}...")

    news_db.init_db()

    # 从 source 名解析 country + tags
    country, tags = _SOURCE_META.get(news.source, ("INTL", ""))

    # 写入 article 表，直接进入流水线（status='clipped'）
    with news_db.conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO article "
            "(source, title, url, body, body_length, country, tags, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'clipped')",
            (news.source, news.title, news.link, news.summary,
             len(news.summary or ""), country, tags),
        )
        inserted_rows = cur.rowcount

    if inserted_rows > 0:
        print("  -> 新情报已安全存入云端数据库！")
        background_tasks.add_task(_safe_pipeline)
        print("  -> 已通知云端大脑在后台启动摘要与发布流水线...")
    else:
        print("  -> 发现重复情报 (触发 IGNORE)，云端大脑继续休眠。")

    return {"status": "情报已处理", "title": news.title[:10]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("vps_api_server:app", host="0.0.0.0", port=8008, reload=False)

from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from pydantic import BaseModel
import sqlite3
from pathlib import Path

# 🚀 新增导入：把你的云端大脑核心逻辑接进来
from orchestrator_cloud import run_cloud_cycle

app = FastAPI()
API_TOKEN = "h6C99Ylz_qubklLALk0X5Dn12FlFkblh6M013qhySTFezY01TmAaD0aD0"

# 动态获取当前文件所在目录，数据库将直接建在这个目录下
DB_PATH = Path(__file__).parent / "news_data.db"

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
# 🚀 修改 1：参数里注入 background_tasks
@app.post("/post-news")
async def post_news(news: NewsItema, background_tasks: BackgroundTasks, token: str = Header(...)):
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="暗号不对，大爷拒绝开门！")
    
    print(f"🛎️ 收到前线发来的情报: {news.title[:20]}...")
    
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        
        # [防呆设计] 确保接收数据库和表一定存在
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                title TEXT UNIQUE,
                link TEXT,
                summary TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 存入数据库
        cursor.execute('''
            INSERT OR IGNORE INTO news (source, title, link, summary, status) 
            VALUES (?,?,?,?, 'pending')
        ''', (news.source, news.title, news.link, news.summary))
        
        # 🚀 修改 2：获取实际受影响的行数
        inserted_rows = cursor.rowcount
        conn.commit()
        
        if inserted_rows > 0:
            print("  -> 💾 新情报已安全存入云端数据库！")
            # 🚀 修改 3：触发后台任务
            background_tasks.add_task(run_cloud_cycle)
            print("  -> 🧠 已通知云端大脑在后台启动摘要与发布流水线...")
        else:
            print("  -> ⏸️ 发现重复情报 (触发 IGNORE)，云端大脑继续休眠。")
            
    except Exception as e:
        print(f"数据库写入异常: {e}")
        raise HTTPException(status_code=500, detail="服务器内部数据库罢工了")
    finally:
        conn.close() 
        
    return {"status": "情报已处理", "title": news.title[:10]}

if __name__ == "__main__":
    import uvicorn
    # 彻底告别加载报错！
    uvicorn.run("api_server:app", host="0.0.0.0", port=8008, reload=False)
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import sqlite3

app = FastAPI()
API_TOKEN = "h6C99Ylz_qubklLALk0X5Dn12FlFkblh6M013qhySTFezY01TmAaD0aD0"

class NewsItema(BaseModel):
    source: str
    title: str
    link: str
    summary: str

# 心跳接口
@app.get("/health")
async def health():
    return {"status": "ok", "message": "传达室大爷很健康"}

# 接收新闻接口
@app.post("/post-news")
async def post_news(news: NewsItema, token: str = Header(...)):
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="暗号不对！")
    
    print(f"收到情报: {news.title}")
    
    conn = sqlite3.connect('/root/eu_news_hub/news_data.db')
    try:
        cursor = conn.cursor()
        # 使用 INSERT OR IGNORE 防止重复标题导致崩溃
        cursor.execute('INSERT OR IGNORE INTO news (source, title, link, summary) VALUES (?,?,?,?)', 
                       (news.source, news.title, news.link, news.summary))
        conn.commit()
    except Exception as e:
        print(f"数据库写入异常: {e}")
    finally:
        conn.close() # 无论如何都会关门
        
    return {"status": "情报已入库"}

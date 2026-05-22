"""
local_processor.py - 本地读取成品库，调用 Gemini 总结，推送到 Telegram
"""
import os
import time
import sqlite3

# ==================== 终极防封与穿透配置 ====================
# 强制让 Python 走你的本地代理出海 (假设你的本地 v2ray/clash 代理端口是 10808)
# 如果你是 7890 端口，请把下面两行的 10808 改成 7890
os.environ["http_proxy"] = "socks5h://127.0.0.1:10808"
os.environ["https_proxy"] = "socks5h://127.0.0.1:10808"

from google import genai
import telebot
import news_db

API_KEY = "AIzaSyALaa8acGoUXpAWbCsb08qknk136Nubnkk"       
TG_TOKEN = "8717762121:AAFmbzXDdfost90-FgvUrdCiXsS6EecPFOc"         
CHANNEL_ID = "@HellWalker_DailyNews"               

client = genai.Client(api_key=API_KEY)
bot = telebot.TeleBot(TG_TOKEN)

def process_and_publish(limit=3):
    print("📡 正在检查本地成品库中未发布的情报...")
    
    with news_db._conn() as c:
        # 提取尚未发布的成品文章
        rows = c.execute(
            "SELECT id, source, title, body, url FROM article "
            "WHERE publish_status = 'pending' LIMIT ?", 
            (limit,)
        ).fetchall()
        
    if not rows:
        print("☕ 暂无新成品需要提纯。")
        return

    print(f"🔥 发现 {len(rows)} 篇原稿，开始请求大模型提纯...")

    for row in rows:
        article_id = row["id"]
        source = row["source"]
        title = row["title"]
        body = row["body"]
        url = row["url"]
        
        print(f"🧠 正在分析 [{source}] 的文章: {title[:20]}...")
        
        prompt = f"""
        你是一位高级情报分析员。请阅读以下从 {source} 抓取的网页内容，过滤掉广告、版权声明、作者介绍等无关噪音。
        请提取核心商业/政治事实，用极具专业度、客观且易于阅读的中文总结成 150 字以内的情报快报。
        
        原始文本:
        {body[:3500]}
        """
        
        try:
            # 调用 Gemini 3.1 Flash
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite', 
                contents=prompt
            )
            summary_text = response.text.strip()
        except Exception as e:
            print(f"❌ Gemini 调用失败: {e}")
            continue
            
        # 排版并推送到 Telegram
        msg = f"<b>🔔 【{source} 一手情报】</b>\n<a href='{url}'>{title}</a>\n\n{summary_text}"
        
        try:
            bot.send_message(CHANNEL_ID, msg, parse_mode="HTML")
            print("🚀 Telegram 频道播报成功！")
        except Exception as e:
            print(f"❌ TG 推送失败: {e}")
            continue
            
        # 成功闭环，更新本地数据库状态
        with news_db._conn() as c:
            c.execute("UPDATE article SET publish_status = 'published' WHERE id = ?", (article_id,))
            
        print(f"✅ 【{title[:15]}...】处理流程闭环完毕！\n")
        time.sleep(2)

if __name__ == "__main__":
    process_and_publish(limit=3)
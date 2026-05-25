# tg_commander.py
import sqlite3
import telebot
from config_loader import TG_BOT_TOKEN
import news_db
from sources import ALL_TAGS, ALL_COUNTRIES

# 1. 初始化 Bot
bot = telebot.TeleBot(TG_BOT_TOKEN)

# ⚠️ 极其重要：填入你自己的 Telegram User ID，防止陌生人控制你的系统！
# （你可以找 @userinfobot 发送任意消息获取你的 ID，一串纯数字）
ADMIN_ID = 8697299028  # <--- 修改这里！

VALID_COUNTRIES = ALL_COUNTRIES + ["INTL"]  # 数据库可能包含非信息源定义的国家

def verify_admin(message):
    """防爆破：身份验证拦截器"""
    return message.chat.id == ADMIN_ID

@bot.message_handler(commands=['start', 'help'], func=verify_admin)
def send_welcome(message):
    countries_str = " | ".join(f"`{c}`" for c in VALID_COUNTRIES)
    tags_str = " | ".join(f"`{t}`" for t in ALL_TAGS)
    welcome_text = (
        "👑 Boss，指挥官模块已上线！\n\n"
        "**📊 系统状态**\n"
        "`/stats` - 查看当前流水线收割进度\n\n"
        f"**🌍 按国家调取 (横向切片)**\n"
        f"{countries_str}\n\n"
        "**🏷️ 按领域调取 (纵向切片)**\n"
        f"{tags_str}"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'], func=verify_admin)
def handle_stats(message):
    """查看数据库实时状态"""
    stats = news_db.article_stats()
    reply = (
        "📈 **当前流水线状态**\n"
        f"📥 待摘要 (Clipped): {stats.get('clipped', 0)}\n"
        f"📝 已摘要 (Summarized): {stats.get('summarized', 0)}\n"
        f"📤 已发布 (Published): {stats.get('published', 0)}\n"
        f"❌ 失败 (Failed): {stats.get('failed', 0)}\n"
        f"📊 总计: {stats.get('total', 0)}\n"
    )
    bot.reply_to(message, reply, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: verify_admin(msg) and msg.text.strip().upper() in VALID_COUNTRIES)
def handle_country_query(message):
    """处理国家短码查询"""
    country = message.text.strip().upper()
    bot.reply_to(message, f"🔍 正在为你调取 {country} 数据库中最新的 5 条已摘要情报...")

    # 连接数据库捞取数据
    with sqlite3.connect(news_db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # 查找该国家，且已经 summarize 过的数据
        cur.execute("""
            SELECT title, summary
            FROM article
            WHERE country = ? AND status = 'summarized'
            ORDER BY id DESC LIMIT 5
        """, (country,))
        rows = cur.fetchall()

    if not rows:
        bot.reply_to(message, f"📭 报告 Boss，当前数据库中没有 {country} 的已就绪情报。")
        return

    for row in rows:
        text = f"📌 **{row['title']}**\n\n{row['summary']}"
        bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: verify_admin(msg) and msg.text.strip().upper() in ALL_TAGS)
def handle_tag_query(message):
    """处理垂直领域/标签查询"""
    tag = message.text.strip().upper()
    bot.reply_to(message, f"📡 正在全网扫描，为您过滤最新的 5 条【{tag}】类垂直情报...")
    
    with sqlite3.connect(news_db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # 核心语法：使用 LIKE '%TAG%' 进行模糊匹配，因为库里存的是 "BIZZ,MARKET" 格式
        cur.execute("""
            SELECT country, title, summary
            FROM article
            WHERE tags LIKE ? AND status = 'summarized'
            ORDER BY id DESC LIMIT 5
        """, (f"%{tag}%",))
        rows = cur.fetchall()
        
    if not rows:
        bot.reply_to(message, f"📭 报告 Boss，当前弹药库中没有带有 {tag} 标签的就绪情报。")
        return
        
    for row in rows:
        # 推送时顺便在标题前加上这篇新闻是哪个国家的，体验更好
        text = f"[{row['country']}] 📌 **{row['title']}**\n\n{row['summary']}"
        bot.send_message(message.chat.id, text, parse_mode="Markdown")
        
@bot.message_handler(func=lambda msg: True)
def handle_unknown(message):
    """非主人的消息直接无视，主人发错的消息给提示"""
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "⚠️ 未知指令。请发送 /help 查看可用命令，或直接发送国家代码 (如 US, CN)。")

if __name__ == "__main__":
    print("🤖 赛博指挥官监听模块启动...等待 Boss 指令 (Ctrl+C 退出)")
    # 使用 infinity_polling 保证哪怕网络抖动断开，它也会自动重连
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
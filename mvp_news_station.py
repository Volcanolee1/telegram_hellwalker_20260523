import os
import feedparser
import requests
import datetime
from google import genai
from google.genai import types

# ==================== 🛠 终极生产线配置项 ====================
TG_BOT_TOKEN = "8717762121:AAG8ihag0LQejHza1U0e8resN7TWQQeg0g0"
TG_CHANNEL_ID = "@HellWalker_DailyNews"
GEMINI_API_KEY = "AIzaSyAlr-iJ7XtZQan9fAI6HspsObuy0GDofH4"

# 🌟 极简且致命的防污染隧道（自带 h，专治各种不服）
PROXY_URL = "socks5h://127.0.0.1:10808"

# 🌟 将代理打包成强力字典，准备硬塞进每一个底层网络请求中
PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}

# 强制全局生效：让接下来的抓取和发报请求自动走隧道，绕过 GFW
os.environ['http_proxy'] = PROXY_URL
os.environ['https_proxy'] = PROXY_URL
# =============================================================

def get_ai_summary_by_gemini(raw_news_data):
    """调用 Gemini 智脑进行多信源情报提炼，并强制输出标准 HTML 格式"""
    print("🧠 正在呼叫 Gemini 总主编进行智能化编译...")
    try:
        # 挂载本地 Socks5h 隧道
        http_options = types.HttpOptions(client_args={'proxy': PROXY_URL})
        client = genai.Client(api_key=GEMINI_API_KEY, http_options=http_options)

        # 1. 极致优化后的主编提示词（System Instruction）
        system_instruction = (
            "你是一位深谙地缘政治、国际冲突与宏观经济的顶级独立通讯社总主编。\n"
            "请将输入的多个严肃媒体新闻（包含标题、摘要和原文链接）进行深度整合，用极其凝练、辛辣且中立的简体中文输出日报。\n\n"
            "【核心写作规范】\n"
            "1. 严禁散播地摊文学和未经证实的营销号谣言，保持严肃媒体的操守和逼格。\n"
            "2. 从所有情报中，精选出今天全球最核心的 8-10 条时政经济大事件，按条独立输出。\n"
            "3. 拒绝翻译腔。每条新闻用一句话提炼核心论点，随后紧跟 100 字以内的透彻内幕综述，一针见血。\n\n"
            "【极致 HTML 排版规范 - 极其重要】\n"
            "你必须严格使用标准 HTML 标签输出内容，绝对不能包含任何 Markdown 语法（如 *, _, #, [ ]等）。\n"
            "- 每一个事件的标题，必须使用 <b>标签加粗</b>，并配合时政相关的 Emoji 开头（如 🇺🇸, 🇨🇳, 🇷🇺, 📈, 💣）。\n"
            "- 在每一条新闻综述的末尾，必须嵌入原作者的网页蓝链作为出处，格式严格为： <a href=\"原文链接\">🔗 閱讀原文</a>。\n"
            "- 每个大事件之间，使用换行符隔开，确保手机端阅读极其舒适。"
        )

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=f"{system_instruction}\n\n以下是今日采集到的全球一手多源情报原材料：\n{raw_news_data}"
        )

        return response.text
    except Exception as e:
        print(f"❌ Gemini 智脑通信崩溃: {e}")
        return None

def fetch_and_push():
    # 2. 全面扩容后的多源全球情报雷达
    feeds = {
        # --- 官方原生 RSS 天团 ---
        "路透社·世界时政": "http://feeds.reuters.com/reuters/worldNews",
        "纽约时报·头条要闻": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "BBC·全球直击": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "华尔街日报·宏观经济": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
        "南华早报·中国前线": "https://www.scmp.com/rss/3/feed",
        "南华早报·亚洲局势": "https://www.scmp.com/rss/9/feed",
        "金融时报·全球财经": "https://www.ft.com/?format=rss",
        "CNBC·国际金融": "https://www.cnbc.com/id/100727362/device/rss/rss.xml",
        # --- 本地 RSSHub 驱动天团 (本地桌面无 RSSHub 容器，暂时注释) ---
        # "彭博社·商业周刊": "http://127.0.0.1:1200/bloomberg/feeds/bworldview",
        # "彭博社·经济前沿": "http://127.0.0.1:1200/bloomberg/feeds/economics"
     }

    raw_news_collected = ""
    print("📡 正在全面扫描多源新闻雷达...")

    for source_name, url in feeds.items():
        try:
            # 配合 requests 确保走代理，硬塞 proxies 强力输液管！
            resp = requests.get(url, timeout=15, proxies=PROXIES)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:3]:  # 每个权威源精准掐取最新的3条动态
                title = entry.get('title', '')
                description = entry.get('description', '无摘要')
                link = entry.get('link', '')  
                raw_news_collected += f"【信源: {source_name}】\n标题: {title}\n摘要: {description}\n链接: {link}\n\n"
        except Exception as e:
            print(f"⚠️ 抓取 {source_name} 暂时受阻，已跳过。")

    if not raw_news_collected:
        print("❌ 全网雷达未搜集到任何情报，终止发射。")
        return

    ai_report = get_ai_summary_by_gemini(raw_news_collected)

    if not ai_report:
        print("❌ AI 总编加工失败，终止发射。")
        return

    # 🚨 终极清洗滤网
    ai_report = ai_report.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    ai_report = ai_report.replace("**", "")

    # 3. 顶级排版艺术
    BANNER_IMAGE = "https://images.unsplash.com/photo-1504711434969-e33886168f5c?q=80&w=1000"
    hidden_image_tag = f'<a href="{BANNER_IMAGE}">&#8203;</a>'
    time_now = datetime.datetime.now().strftime('%Y-%m-%d')

    final_html_post = (
        f"{hidden_image_tag}"  
        f"🌟 <b>赛博未遮蔽要闻晚报</b> ({time_now})\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{ai_report}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📡 <i>信息茧房外面的世界，祝您今晚键政愉快！</i>"
    )

    tg_url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHANNEL_ID,
        "text": final_html_post,
        "parse_mode": "HTML",  
    }

    print("🚀 正在向 TG 频道发射完全体智能化图文日报...")
    # 发射时也硬塞 proxies 字典，无视系统代理模式！
    res = requests.post(tg_url, json=payload, proxies=PROXIES)
    if res.status_code == 200:
        print("✨ 恭喜！多源聚合、自带高清题图、自带原文蓝链的完全体日报已成功破墙发射！")
    else:
        print(f"❌ 发射失败，详情: {res.text}")

if __name__ == "__main__":
    fetch_and_push()
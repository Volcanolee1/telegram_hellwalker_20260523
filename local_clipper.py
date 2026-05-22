import os
import sys
import time
import json
import subprocess
import requests
from playwright.sync_api import sync_playwright

# ==================== 配置区 ====================
VPS_IP = "107.174.159.191"
API_URL = f"http://{VPS_IP}:8000/post-news"
TOKEN = "h6C99Ylz_qubklLALk0X5Dn12FlFkblh6M013qhySTFezY01TmAaD0aD0" 

# 1. 你的“特工隔离安全屋”路径
CHROME_USER_DATA = r"C:\Users\36121\Desktop\news_commander_project\automation_chrome"
# 2. 破墙插件的绝对路径
EXTENSION_PATH = r"C:\Users\36121\Desktop\news_commander_project\bypass-paywalls-chrome-clean-master"
# 3. 真实 Chrome 的可执行文件路径
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# 4. 原生调试端口
DEBUG_PORT = 9222 

def apply_stealth_js(page):
    """底层黑魔法：抹除自动化痕迹"""
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'zh-CN'] });
    """)

def clipper(target_url):
    print("🔧 [步骤 1] 正在强行清理本地残留的 Chrome 进程，确保端口独占...")
    os.system("taskkill /F /IM chrome.exe /T >nul 2>&1")
    time.sleep(1)

    print("🚀 [步骤 2] 正在通过本地 Subprocess 以原生真人模式拉起 Chrome...")
    chrome_cmd = [
        CHROME_EXE,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={CHROME_USER_DATA}",
        f"--load-extension={EXTENSION_PATH}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check"
    ]
    
    subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("⏳ 正在等待浏览器与 Bypass 插件初始化（缓冲 4 秒）...")
    time.sleep(4)

    with sync_playwright() as p:
        print("🔗 [步骤 3] 正在通过 CDP 协议秘密接管真人 Chrome 实例...")
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{DEBUG_PORT}")
        except Exception as e:
            print(f"❌ CDP 接管失败 (端口未响应): {e}")
            return

        # 直接接管当前活跃页面
        context = browser.contexts[0]
        page = context.pages[0] if len(context.pages) > 0 else context.new_page()
        
        # 注入指纹抹除脚本
        apply_stealth_js(page)
        
        print(f"🌍 [步骤 4] 正在前往情报目标站点: {target_url}")
        try:
            # 改用 domcontentloaded，防止被路透社厚重的动态统计流量卡死
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            
            print("⏳ 正在给 Bypass 插件留出 6 秒钟的时间粉碎付费墙并加载数据...")
            page.wait_for_timeout(6000)
            
            # 💡 极其暴力的多级容器正文剥离算法（通杀彭博、路透、纽时）
            # 优先找 article，再找 main，最后兜底用包含主要文字的 div 层，防止提取出空白
            content = page.evaluate("""() => {
                const selectors = ['article', 'main', '.article-body', '.story-content', '[class*="ArticleBody"]'];
                for (const selector of selectors) {
                    const el = document.querySelector(selector);
                    if (el && el.innerText.trim().length > 300) {
                        return el.innerText;
                    }
                }
                return document.body.innerText; // 最终兜底
            }""")
            
            title = page.title()
            
            if len(content.strip()) < 300:
                print("⚠️ 警告：抓取到的正文长度依然过短，可能页面未正常渲染。")
            else:
                print(f"✅ 抓取大成功！标题: {title}，成功剥离出 {len(content)} 字正文！")
                
        except Exception as e:
            print(f"❌ 网页内容抓取异常: {e}")
            browser.close() # 💡 修正点：使用标准的 close() 断开连接
            return

        # 💡 修正点：with 块结束时 Playwright 会自动优雅地解绑 CDP 控制，
        # 不关闭你的浏览器，让你的 Chrome 舒舒服服地留在桌面上供你阅读
        browser.close() 
        
        # ================= [步骤 5] 投递情报至圣何塞 VPS =================
        data = {
            "source": "CDP-Bypass特工",
            "title": title,
            "link": target_url,
            "summary": content[:2000]  # 切前 2000 字
        }
        
        headers = {
            "Token": TOKEN,
            "Content-Type": "application/json"
        }
        
        print("🚀 [步骤 6] 正在跨海向圣何塞 VPS 投递情报载荷...")
        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=15)
            print(f"📡 服务器响应状态码: {response.status_code}")
            print(f"✨ 投递结果回执: {response.text}")
        except Exception as e:
            print(f"❌ 投递失败 (VPS 接口未响应): {e}")

if __name__ == "__main__":
    url = input("请输入要剪藏的新闻链接: ")
    if url.strip():
        clipper(url.strip())
    else:
        print("错误：链接不能为空！")



import time
import traceback
from datetime import datetime
import news_db

# ── 云端流水线批次设置 ──────────────────────────────────────────
# 此时我们不需要 patrol 和 clip，只需专注于摘要和发布
SUMMARY_BATCH = 10 
PUBLISH_BATCH = 5 

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def step_summarize(batch: int) -> None:
    # 确保 VPS 有 summarizer.py 和你的 Gemini API Key
    from summarizer import run as summarize_run
    print(f"\n[{ts()}] ── 云端 SUMMARIZE (max {batch}) ──")
    summarize_run(limit=batch, retry=False)

def step_publish(batch: int) -> None:
    # 确保 VPS 有 publisher.py 和你的 TG Bot Token
    from publisher import run as publish_run
    print(f"\n[{ts()}] ── 云端 PUBLISH (max {batch}) ──")
    publish_run(limit=batch, dry_run=False, retry=False)

def run_cloud_cycle():
    print(f"\n[{ts()}] ☁️ 云端大脑开始新一轮巡检...")
    
    # 步骤只剩下：摘要 -> 发布
    tasks = [
        ("summarize", lambda: step_summarize(SUMMARY_BATCH)),
        ("publish",   lambda: step_publish(PUBLISH_BATCH)),
    ]

    for name, fn in tasks:
        try:
            fn()
        except Exception:
            print(f"\n[{ts()}] ⚠️ {name} 步骤异常：")
            traceback.print_exc(limit=2)

def main():
    # 初始化...
    print("🚀 云端调度器启动")
    while True:  # 🚨 必须有这个死循环
        try:
            run_cloud_cycle()  # 你原本的逻辑
        except Exception as e:
            print(f"调度器单轮运行出错: {e}")
            
        print("💤 本轮休息 60 秒...")
        time.sleep(60)  # 🚨 必须 sleep，否则 CPU 会瞬间跑满

if __name__ == "__main__":
    main()
import sys
import time
import traceback
from datetime import datetime
import news_db

# ── 云端流水线批次设置 ──────────────────────────────────────────
SUMMARY_BATCH = 10 
PUBLISH_BATCH = 5 

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def step_summarize(batch: int) -> None:
    from vps_summarizer import run as summarize_run
    print(f"\n[{ts()}] ── 云端 SUMMARIZE (max {batch}) ──")
    summarize_run(limit=batch, retry=False)

def step_publish(batch: int) -> None:
    from publisher import run as publish_run
    print(f"\n[{ts()}] ── 云端 PUBLISH (max {batch}) ──")
    publish_run(limit=batch, dry_run=False, retry=False)

def run_cloud_cycle():
    print(f"\n[{ts()}] ☁️ 云端大脑被 Timer 唤醒，开始巡检...")
    
    tasks = [
        ("summarize", lambda: step_summarize(SUMMARY_BATCH)),
        ("publish",   lambda: step_publish(PUBLISH_BATCH)),
    ]

    for name, fn in tasks:
        try:
            fn()
        except Exception:
            # 这里捕获 Exception 是正确的，只捕获业务错误，不拦截系统退出信号
            print(f"\n[{ts()}] ⚠️ {name} 步骤异常：")
            traceback.print_exc(limit=2)

def main():
    print("🚀 云端大脑已激活 (Oneshot Mode)")
    
    try:
        run_cloud_cycle()
        print(f"\n[{ts()}] ✅ 本轮巡检全部完成，大脑进入休眠，等待下一次 Timer 唤醒。")
        
    except Exception as e:
        print(f"\n[{ts()}] 🚨 调度器发生意外报错: {e}")
        traceback.print_exc()
        sys.exit(1)  # 抛出非 0 退出码，方便 Systemd 记录失败状态

if __name__ == "__main__":
    main()

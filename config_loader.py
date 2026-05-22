# config_loader.py
import json
import os
from pathlib import Path

# 自动定位同一目录下的 config.json
CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"❌ 找不到配置文件: {CONFIG_PATH}，请确认是否创建！")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

# 读取配置
cfg = load_config()

# --- 提取出所有的关键变量供其他文件使用 ---
PROXY_URL = cfg.get("PROXY_URL", "socks5h://127.0.0.1:10808")
GEMINI_API_KEY = cfg.get("GEMINI_API_KEY", "")
TG_BOT_TOKEN = cfg.get("TG_BOT_TOKEN", "")
US_CHANNEL = cfg.get("US_CHANNEL", "@HellWalker_DailyNews")
CN_CHANNEL = cfg.get("CN_CHANNEL", "@HellWalker_CN_DailyNews")
API_TOKEN = cfg.get("API_TOKEN", "")

# --- 终极魔法：只要其他文件导入了此模块，全局代理就自动挂上！ ---
if PROXY_URL:
    os.environ["http_proxy"] = PROXY_URL
    os.environ["https_proxy"] = PROXY_URL
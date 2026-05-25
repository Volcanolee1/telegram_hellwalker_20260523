"""统一配置加载器：从 config.yaml 读取，环境变量可覆盖任意字段。

优先级：环境变量 > config.yaml > 硬编码默认值
为敏感字段（API Key / Token）提供了环境变量直通能力，避免写入磁盘。
"""
import os
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "config.yaml"

_DEFAULTS = {
    "proxy_url": "socks5h://127.0.0.1:10808",
    "us_channel": "@HellWalker_DailyNews",
    "cn_channel": "@HellWalker_CN_DailyNews",
    "gemini_api_key": "",
    "tg_bot_token": "",
    "api_token": "",
}

_ENV_MAP = {
    "gemini_api_key": "GEMINI_API_KEY",
    "tg_bot_token": "TG_BOT_TOKEN",
    "us_channel": "US_CHANNEL",
    "cn_channel": "CN_CHANNEL",
    "api_token": "API_TOKEN",
    "proxy_url": "PROXY_URL",
}


def _load() -> dict:
    """从 YAML 文件加载，不存在时使用空字典。"""
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _get(key: str) -> str:
    """读取单个配置值，优先级：环境变量 > YAML > 默认值。"""
    env_var = _ENV_MAP.get(key)
    if env_var:
        env_val = os.environ.get(env_var)
        if env_val is not None:
            return env_val
    yaml_val = _cfg.get(key)
    if yaml_val is not None:
        return str(yaml_val)
    return _DEFAULTS.get(key, "")


_cfg = _load()

PROXY_URL = _get("proxy_url")
GEMINI_API_KEY = _get("gemini_api_key")
TG_BOT_TOKEN = _get("tg_bot_token")
US_CHANNEL = _get("us_channel")
CN_CHANNEL = _get("cn_channel")
API_TOKEN = _get("api_token")

# 自动挂载全局代理环境变量，确保 HTTP 请求走 SOCKS5 隧道
if PROXY_URL:
    os.environ["http_proxy"] = PROXY_URL
    os.environ["https_proxy"] = PROXY_URL

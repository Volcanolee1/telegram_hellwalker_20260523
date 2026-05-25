# config_loader.py
"""
支持两种模式：
  明文模式  — 直接读取 config.json（开发/本地）
  加密模式  — 读取 config.json.enc，用 CONFIG_KEY 环境变量解密

加密你的配置（只需运行一次）：
  python config_loader.py --encrypt
然后删掉 config.json，在 VPS 上设置环境变量 CONFIG_KEY。
"""
import json
import os
import sys
import base64
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
ENC_PATH    = Path(__file__).parent / "config.json.enc"


# ── 解密 ─────────────────────────────────────────────────────────────
def _decrypt(enc_path: Path, key: str) -> bytes:
    from cryptography.fernet import Fernet
    import hashlib

    # 用 SHA-256 把任意长度的 CONFIG_KEY 规整为 32 字节 Fernet key 的 base64
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    f = Fernet(fernet_key)
    return f.decrypt(enc_path.read_bytes())


# ── 加载 ─────────────────────────────────────────────────────────────
def _load_config() -> dict:
    key = os.environ.get("CONFIG_KEY", "").strip()

    if key and ENC_PATH.exists():
        plain = _decrypt(ENC_PATH, key)
        return json.loads(plain)

    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text("utf-8"))

    raise FileNotFoundError(
        f"找不到配置文件: {CONFIG_PATH} 或 {ENC_PATH}"
    )


# ── 加密（一次性操作）────────────────────────────────────────────────
def _encrypt_config() -> None:
    key = os.environ.get("CONFIG_KEY", "").strip()
    if not key:
        print("请先设置 CONFIG_KEY 环境变量，例如：")
        print('  export CONFIG_KEY="你的强密码-随意写一串"')
        print("然后重新运行: python config_loader.py --encrypt")
        sys.exit(1)

    from cryptography.fernet import Fernet
    import hashlib

    if not CONFIG_PATH.exists():
        print(f"找不到 {CONFIG_PATH}，请确认 config.json 存在。")
        sys.exit(1)

    digest = hashlib.sha256(key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    f = Fernet(fernet_key)

    plain = CONFIG_PATH.read_bytes()
    ENC_PATH.write_bytes(f.encrypt(plain))

    print(f"已生成加密文件: {ENC_PATH}")
    print("现在你可以安全地删除明文 config.json，并牢记你的 CONFIG_KEY。")
    print(f"在 VPS 上启动服务前执行: export CONFIG_KEY='<你的密码>'")


# ── 模块级导出 ───────────────────────────────────────────────────────
cfg = _load_config()

PROXY_URL      = cfg.get("PROXY_URL", "socks5h://127.0.0.1:10808")
GEMINI_API_KEY = cfg.get("GEMINI_API_KEY", "")
TG_BOT_TOKEN   = cfg.get("TG_BOT_TOKEN", "")
US_CHANNEL     = cfg.get("US_CHANNEL", "@HellWalker_DailyNews")
CN_CHANNEL     = cfg.get("CN_CHANNEL", "@HellWalker_CN_DailyNews")
API_TOKEN      = cfg.get("API_TOKEN", "")

# 仅本地需要代理；VPS 直连应留空 PROXY_URL
if PROXY_URL:
    os.environ["http_proxy"] = PROXY_URL
    os.environ["https_proxy"] = PROXY_URL


if __name__ == "__main__":
    if "--encrypt" in sys.argv:
        _encrypt_config()
    else:
        print("用法: python config_loader.py --encrypt   # 加密 config.json")

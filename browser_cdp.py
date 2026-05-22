"""CDP 接管真人 Chrome 的公共工具。

设计原则：浏览器永远是用户手动 launch_chrome.bat 起的，
本模块只负责"探测端口 + 接管"，不创建任何 Chrome 进程。
"""
import socket
import requests

DEBUG_HOST = "127.0.0.1"
DEBUG_PORT = 9222


def is_debug_port_alive(host: str = DEBUG_HOST, port: int = DEBUG_PORT,
                        timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_cdp_version(host: str = DEBUG_HOST, port: int = DEBUG_PORT):
    try:
        r = requests.get(f"http://{host}:{port}/json/version", timeout=2)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return None


def cdp_endpoint(host: str = DEBUG_HOST, port: int = DEBUG_PORT) -> str:
    return f"http://{host}:{port}"


# 兜底用的指纹抹除脚本：接管真人 Chrome 时本来就不太需要，
# 但 Playwright 的 CDP 通道偶尔会留点痕迹，加上不亏。
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'zh-CN'] });
"""


def apply_stealth(page) -> None:
    page.add_init_script(STEALTH_JS)


PORT_DEAD_HINT = """
========================================================================
❌ 调试端口 9222 没有响应。

请先双击 launch_chrome.bat 启动一个带调试端口的真人 Chrome，
确认 Bypass Paywalls Clean 已生效、需要的账号已登录后，再回来跑本脚本。
========================================================================
""".strip()


def ensure_port_alive() -> bool:
    """返回 True 表示端口可用；否则打印提示并返回 False。"""
    if is_debug_port_alive():
        info = fetch_cdp_version()
        if info:
            print(f"✓ 已锁定真人 Chrome：{info.get('Browser', 'unknown')}")
        return True
    print(PORT_DEAD_HINT)
    return False

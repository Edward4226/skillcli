"""本地只读看板的 HTTP server（标准库，无依赖）。

只在 127.0.0.1 监听；只服务本地文件 + 本地 JSON；不写任何东西（Phase 4 P0
按 SPEC §11.1，只读看板；Phase 6 才加"一键确认规则"的受限写端点）。
"""
from __future__ import annotations

import http.server
import json
import socket
import threading
import webbrowser
from pathlib import Path

from .. import registry as reg
from ..usage import DEFAULT_SUGGESTIONS_PATH

_INDEX_HTML = Path(__file__).parent / "index.html"


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """读：index.html / registry.json / suggestions.json / health。"""

    def do_GET(self) -> None:    # noqa: N802 — http.server 约定
        if self.path in ("/", "/index.html"):
            self._serve_file(_INDEX_HTML, "text/html; charset=utf-8")
            return
        if self.path == "/api/registry.json":
            self._serve_json(self._load_registry_raw())
            return
        if self.path == "/api/suggestions.json":
            self._serve_json(self._load_suggestions_raw())
            return
        if self.path == "/api/health":
            self._serve_json({"ok": True})
            return
        self.send_error(404, "not found")

    # 我们不响应任何 POST/PUT/DELETE——只读看板，按 SPEC §11.1。

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except OSError as e:
            self.send_error(500, f"cannot read {path.name}: {e}")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_json(self, obj: object) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _load_registry_raw(self) -> dict:
        if not reg.DEFAULT_REGISTRY_PATH.is_file():
            return {"version": 1, "skills": {}, "saved_at": None}
        try:
            return json.loads(reg.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "skills": {}, "saved_at": None}

    def _load_suggestions_raw(self) -> dict:
        if not DEFAULT_SUGGESTIONS_PATH.is_file():
            return {"version": 1, "suggestions": []}
        try:
            return json.loads(DEFAULT_SUGGESTIONS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "suggestions": []}

    def log_message(self, format: str, *args) -> None:    # noqa: A002
        # 静默 access log；进程级日志由调用方自管
        pass


def serve(port: int = 7878, *, open_browser: bool = True, host: str = "127.0.0.1") -> None:
    """启服务。Ctrl-C 干净停。"""
    try:
        httpd = http.server.HTTPServer((host, port), DashboardHandler)
    except OSError:
        raise
    url = f"http://{host}:{port}/"
    print(f"📊 skillcli 看板已启动")
    print(f"   {url}")
    print(f"   按 Ctrl-C 停止")
    if open_browser:
        threading.Thread(
            target=lambda: webbrowser.open(url),
            daemon=True,
        ).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n看板已停止。")
    finally:
        httpd.server_close()


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """端口探测工具，单元测试用。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
    except OSError:
        return False
    finally:
        s.close()
    return True

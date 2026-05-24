"""Phase 4 单元测试 · dashboard server。

测试用 ephemeral 端口起真 HTTPServer，避免 mock，确保 endpoint 协议真的正确。
"""
from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

from skill_control_plane.dashboard.server import DashboardHandler, is_port_available


def _pick_port(start: int = 23000) -> int:
    for p in range(start, start + 200):
        if is_port_available(p):
            return p
    raise RuntimeError("no free port in test range")


class TestDashboardEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.port = _pick_port()
        cls.httpd = HTTPServer(("127.0.0.1", cls.port), DashboardHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        # 热身：等 server 就绪
        for _ in range(20):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{cls.port}/api/health", timeout=1,
                ).read()
                break
            except Exception:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path: str):
        return urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{path}", timeout=2,
        )

    def test_index_html_served(self):
        """GET / → 200 + 含核心 HTML 标记。"""
        r = self._get("/")
        self.assertEqual(r.status, 200)
        body = r.read().decode("utf-8")
        self.assertIn("skillcli", body)
        # 关键 UI 元素必须存在（防止意外砍掉）
        self.assertIn('id="badge-chart"', body)
        self.assertIn('id="tool-chart"', body)
        self.assertIn("disclaimer", body)

    def test_health(self):
        r = self._get("/api/health")
        body = json.loads(r.read())
        self.assertTrue(body["ok"])

    def test_registry_endpoint_json(self):
        """GET /api/registry.json → 返回 valid JSON 含 skills 字段。
        意图：前端硬依赖这个字段；schema 改了应在这里立刻发现。"""
        r = self._get("/api/registry.json")
        body = json.loads(r.read())
        self.assertIn("skills", body)

    def test_suggestions_endpoint_json(self):
        r = self._get("/api/suggestions.json")
        body = json.loads(r.read())
        self.assertIn("suggestions", body)

    def test_unknown_path_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/no-such-endpoint")
        self.assertEqual(ctx.exception.code, 404)

    def test_post_not_allowed(self):
        """看板是只读的——POST 必须不被处理（不能误开写端点）。意图：SPEC §11.1
        明说只读；放行写端点 = 攻破"本地只读"承诺。"""
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/registry.json",
            data=b"{}",
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=2)
        # do_POST 未实装时 BaseHTTPRequestHandler 默认返 501 Not Implemented
        self.assertIn(ctx.exception.code, (404, 405, 501))


if __name__ == "__main__":
    unittest.main()

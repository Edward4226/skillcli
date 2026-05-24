"""本地只读看板（Phase 4）。stdlib http.server + 单文件 HTML + Chart.js CDN。"""
from .server import serve

__all__ = ["serve"]

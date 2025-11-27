"""Web 服务模块"""

from termsupervisor.web.app import create_app
from termsupervisor.web.server import WebServer

__all__ = ["create_app", "WebServer"]

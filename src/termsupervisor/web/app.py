"""FastAPI 应用初始化"""

import asyncio

import iterm2
import uvicorn

from termsupervisor import config
from termsupervisor.iterm import ITerm2Client
from termsupervisor.supervisor import TermSupervisor
from termsupervisor.web.server import WebServer


def create_app(supervisor: TermSupervisor, iterm_client: ITerm2Client) -> WebServer:
    """创建 Web 应用"""
    return WebServer(supervisor, iterm_client)


async def start_server(connection: iterm2.Connection):
    """启动服务器"""
    iterm_client = ITerm2Client(connection)

    supervisor = TermSupervisor(
        interval=config.INTERVAL,
        exclude_names=config.EXCLUDE_NAMES,
        min_changed_lines=config.MIN_CHANGED_LINES,
        debug=config.DEBUG,
    )

    server = create_app(supervisor, iterm_client)

    supervisor_task = asyncio.create_task(supervisor.run(connection))

    uvicorn_config = uvicorn.Config(
        server.app,
        host="0.0.0.0",
        port=8765,
        log_level="info"
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    print("TermSupervisor Web Server starting at http://localhost:8765")

    try:
        await uvicorn_server.serve()
    finally:
        supervisor.stop()
        supervisor_task.cancel()


def main():
    """入口函数"""
    try:
        iterm2.run_until_complete(start_server)
    except KeyboardInterrupt:
        print("\nServer stopped")

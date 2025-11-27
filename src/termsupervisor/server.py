"TermSupervisor Web Server - WebSocket 服务展示 iTerm2 布局和更新"

import asyncio
from pathlib import Path

import iterm2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from termsupervisor import config
from termsupervisor.supervisor import TermSupervisor, LayoutData


class WebServer:
    """WebSocket 服务器"""

    def __init__(self, supervisor: TermSupervisor):
        self.app = FastAPI(title="TermSupervisor")
        self.supervisor = supervisor
        self.clients: list[WebSocket] = []

        # Setup templates
        templates_dir = Path(__file__).parent / "templates"
        self.templates = Jinja2Templates(directory=str(templates_dir))

        self._setup_routes()

        # 注册更新回调
        supervisor.on_update(self._on_layout_update)

    async def _on_layout_update(self, layout: LayoutData):
        """布局更新回调"""
        await self.broadcast(self.supervisor.get_layout_dict())

    def _setup_routes(self):
        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            return self.templates.TemplateResponse("index.html", {"request": request})

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.clients.append(websocket)
            try:
                # 发送初始布局
                await websocket.send_json(self.supervisor.get_layout_dict())
                while True:
                    data = await websocket.receive_text()
                    if data.startswith("activate:"):
                        session_id = data.split(":", 1)[1]
                        # TODO: 激活对应 session
            except WebSocketDisconnect:
                self.clients.remove(websocket)

    async def broadcast(self, data: dict):
        """广播消息给所有客户端"""
        for client in self.clients:
            try:
                await client.send_json(data)
            except Exception:
                pass


async def start_server(connection: iterm2.Connection):
    """启动服务器"""
    import uvicorn

    # 创建 supervisor
    supervisor = TermSupervisor(
        interval=config.INTERVAL,
        exclude_names=config.EXCLUDE_NAMES,
        min_changed_lines=config.MIN_CHANGED_LINES,
        debug=config.DEBUG,
    )

    # 创建 web 服务器
    server = WebServer(supervisor)

    # 启动 supervisor 监控任务
    supervisor_task = asyncio.create_task(supervisor.run(connection))

    # 启动 web 服务器
    config_uvicorn = uvicorn.Config(server.app, host="0.0.0.0", port=8765, log_level="info")
    uvicorn_server = uvicorn.Server(config_uvicorn)

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


if __name__ == "__main__":
    main()
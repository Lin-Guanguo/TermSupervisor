"""Web 服务器"""

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from termsupervisor.models import LayoutData
from termsupervisor.iterm import ITerm2Client
from termsupervisor.supervisor import TermSupervisor
from termsupervisor.web.handlers import MessageHandler

if TYPE_CHECKING:
    from termsupervisor.hooks import HookReceiver


class WebServer:
    """WebSocket 服务器"""

    def __init__(self, supervisor: TermSupervisor, iterm_client: ITerm2Client):
        self.app = FastAPI(title="TermSupervisor")
        self.supervisor = supervisor
        self.iterm_client = iterm_client
        self.clients: list[WebSocket] = []
        self._hook_receiver: "HookReceiver | None" = None

        templates_dir = Path(__file__).parent.parent / "templates"
        self.templates = Jinja2Templates(directory=str(templates_dir))

        self._handler = MessageHandler(
            iterm_client=iterm_client,
            supervisor=supervisor,
            broadcast=self.broadcast
        )

        self._setup_routes()
        supervisor.on_update(self._on_layout_update)

    def setup_hook_receiver(self, receiver: "HookReceiver") -> None:
        """设置 Hook 接收器"""
        self._hook_receiver = receiver
        receiver.setup_routes(self.app)

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
                await websocket.send_json(self.supervisor.get_layout_dict())
                while True:
                    data = await websocket.receive_text()
                    await self._handler.handle(websocket, data)
            except WebSocketDisconnect:
                self.clients.remove(websocket)

    async def broadcast(self, data: dict):
        """广播消息给所有客户端"""
        for client in self.clients:
            try:
                await client.send_json(data)
            except Exception:
                pass

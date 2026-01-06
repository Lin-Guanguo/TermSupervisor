"""Web 服务器"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from termsupervisor.adapters import TerminalAdapter
from termsupervisor.render import RenderPipeline, TerminalRenderer
from termsupervisor.render.types import LayoutUpdate
from termsupervisor.web.handlers import MessageHandler

if TYPE_CHECKING:
    from termsupervisor.adapters.iterm2 import ITerm2Client
    from termsupervisor.hooks import HookReceiver


class WebServer:
    """WebSocket 服务器"""

    def __init__(
        self,
        pipeline: RenderPipeline,
        adapter: TerminalAdapter,
        iterm_client: "ITerm2Client | None" = None,
    ):
        self.app = FastAPI(title="TermSupervisor")
        self.pipeline = pipeline
        self.adapter = adapter
        self.iterm_client = iterm_client  # Optional, for iTerm2-specific features
        self.clients: list[WebSocket] = []
        self._hook_receiver: HookReceiver | None = None
        self._renderer = TerminalRenderer()
        # Debug subscribers (WebSocket clients that want debug events)
        self._debug_subscribers: set[WebSocket] = set()

        templates_dir = Path(__file__).parent.parent / "templates"
        self.templates = Jinja2Templates(directory=str(templates_dir))

        self._handler = MessageHandler(
            adapter=adapter,
            pipeline=pipeline,
            broadcast=self.broadcast,
            web_server=self,
            iterm_client=iterm_client,
        )

        self._setup_routes()
        pipeline.on_update(self._on_layout_update)

    def setup_hook_receiver(self, receiver: "HookReceiver") -> None:
        """设置 Hook 接收器"""
        self._hook_receiver = receiver
        receiver.setup_routes(self.app)
        # 将 HookManager 传给 MessageHandler，用于处理用户点击事件
        self._handler.hook_manager = receiver.hook_manager
        # 设置调试事件回调
        receiver.hook_manager.set_debug_event_callback(self._on_debug_event)

    def _on_debug_event(self, event: dict) -> None:
        """调试事件回调（从 StateManager 接收）

        由于这是同步回调，需要在事件循环中调度广播。
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast_debug_event(event))
        except RuntimeError:
            # 没有运行中的事件循环，忽略
            pass

    async def _on_layout_update(self, update: LayoutUpdate):
        """布局更新回调"""
        await self.broadcast(self.pipeline.get_layout_dict())

    def _setup_routes(self):
        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            return self.templates.TemplateResponse("index.html", {"request": request})

        @self.app.get("/api/pane/{pane_id}/svg")
        async def get_pane_svg(pane_id: str):
            """获取指定 pane 的 SVG 渲染图。

            Note: SVG rendering is only available for iTerm2.
            """
            if not self.iterm_client:
                return Response(
                    content="SVG rendering not available for this terminal",
                    status_code=501,
                    media_type="text/plain",
                )

            session = await self.iterm_client.get_session_by_id(pane_id)
            if not session:
                return Response(
                    content="Session not found", status_code=404, media_type="text/plain"
                )

            try:
                svg = await self._renderer.render_session(session)
                return Response(
                    content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"}
                )
            except Exception as e:
                return Response(
                    content=f"Render error: {e}", status_code=500, media_type="text/plain"
                )

        @self.app.get("/api/debug/states")
        async def get_debug_states(
            limit: int | None = None,
            offset: int = 0,
        ):
            """获取所有 pane 的调试快照列表

            Query params:
                limit: 最大返回数量 (optional)
                offset: 起始偏移量 (default: 0)

            Returns:
                调试快照列表，每个包含:
                - pane_id, status, source, state_id, description
                - running_duration, queue_depth, queue_overflow_drops
                - latest_history
            """
            hook_manager = self._hook_receiver.hook_manager if self._hook_receiver else None
            if not hook_manager:
                return Response(
                    content="Hook system not initialized",
                    status_code=503,
                    media_type="text/plain",
                )

            snapshots, total = hook_manager.get_all_debug_states(
                limit=limit,
                offset=offset,
            )
            return {"states": snapshots, "total": total}

        @self.app.get("/api/debug/state/{pane_id}")
        async def get_debug_state(
            pane_id: str,
            max_history: int = 30,
            max_pending_events: int = 10,
        ):
            """获取状态机/队列调试信息"""
            hook_manager = self._hook_receiver.hook_manager if self._hook_receiver else None
            if not hook_manager:
                return Response(
                    content="Hook system not initialized",
                    status_code=503,
                    media_type="text/plain",
                )

            history_limit = max_history if max_history > 0 else None
            snapshot = hook_manager.get_debug_state(
                pane_id,
                max_history=history_limit,
                max_pending_events=max_pending_events,
            )
            if snapshot is None:
                return Response(
                    content="Pane not found",
                    status_code=404,
                    media_type="text/plain",
                )
            return snapshot

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.clients.append(websocket)
            try:
                await websocket.send_json(self.pipeline.get_layout_dict())
                while True:
                    data = await websocket.receive_text()
                    await self._handler.handle(websocket, data)
            except WebSocketDisconnect:
                # Safe removal to avoid race with broadcast cleanup
                if websocket in self.clients:
                    self.clients.remove(websocket)
                self._debug_subscribers.discard(websocket)

    async def broadcast(self, data: dict):
        """广播消息给所有客户端"""
        disconnected = []
        for client in list(self.clients):  # Snapshot for safe iteration
            try:
                await client.send_json(data)
            except Exception as e:
                logger.debug(f"Failed to send to client: {e}")
                disconnected.append(client)
        # Remove disconnected clients (safe removal to avoid race with disconnect handler)
        for client in disconnected:
            if client in self.clients:
                self.clients.remove(client)
            self._debug_subscribers.discard(client)

    async def broadcast_debug_event(self, event: dict):
        """广播调试事件给订阅者"""
        if not self._debug_subscribers:
            return

        debug_msg = {"type": "debug_event", **event}
        for client in list(self._debug_subscribers):
            try:
                await client.send_json(debug_msg)
            except Exception as e:
                logger.debug(f"Failed to send debug event to client: {e}")
                self._debug_subscribers.discard(client)

    def subscribe_debug(self, websocket: WebSocket) -> bool:
        """订阅调试事件"""
        self._debug_subscribers.add(websocket)
        return True

    def unsubscribe_debug(self, websocket: WebSocket) -> bool:
        """取消订阅调试事件"""
        self._debug_subscribers.discard(websocket)
        return True

    @property
    def debug_subscriber_count(self) -> int:
        """获取调试订阅者数量"""
        return len(self._debug_subscribers)

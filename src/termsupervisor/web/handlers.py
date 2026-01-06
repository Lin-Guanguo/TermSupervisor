"""WebSocket 消息处理器

JSON 格式：
- {"action": "activate", "pane_id": "xxx"}
- {"action": "rename", "type": "pane|tab|window", "id": "xxx", "name": "yyy"}
- {"action": "create_tab", "window_id": "xxx", "layout": "single|split"}
- {"action": "debug_subscribe", "subscribe": true|false}
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import WebSocket

from termsupervisor.adapters.iterm2 import ITerm2Client
from termsupervisor.render import RenderPipeline
from termsupervisor.telemetry import get_logger

if TYPE_CHECKING:
    from termsupervisor.hooks import HookManager
    from termsupervisor.web.server import WebServer

logger = get_logger(__name__)


@dataclass
class MessageHandler:
    """WebSocket 消息处理器

    使用 JSON 格式的 action 消息。
    """

    iterm_client: ITerm2Client
    pipeline: RenderPipeline
    broadcast: Callable[[dict], Awaitable[None]]
    hook_manager: "HookManager | None" = field(default=None)
    web_server: "WebServer | None" = field(default=None)

    async def handle(self, websocket: WebSocket, data: str):
        """处理 WebSocket 消息

        所有消息必须为 JSON 格式。
        """
        try:
            msg = json.loads(data)
            await self._dispatch_action(websocket, msg)
        except json.JSONDecodeError as e:
            logger.warning(f"[WS] Invalid JSON: {e}")
            await websocket.send_json({"type": "error", "message": "Invalid JSON format"})

    async def _dispatch_action(self, websocket: WebSocket, msg: dict):
        """分发 action 到处理器"""
        action = msg.get("action")

        if action == "activate":
            await self._handle_activate(websocket, msg)
        elif action == "rename":
            await self._handle_rename_action(websocket, msg)
        elif action == "create_tab":
            await self._handle_create_tab_action(websocket, msg)
        elif action == "debug_subscribe":
            await self._handle_debug_subscribe(websocket, msg)
        else:
            logger.warning(f"[WS] Unknown action: {action}")
            await websocket.send_json({"type": "error", "message": f"Unknown action: {action}"})

    async def _handle_activate(self, websocket: WebSocket, msg: dict):
        """处理激活请求（用户点击 pane）

        JSON 格式: {"action": "activate", "pane_id": "xxx"}
        """
        pane_id = msg.get("pane_id", "")
        if not pane_id:
            await websocket.send_json({"type": "error", "message": "Missing pane_id"})
            return

        # 通知 HookManager 用户点击事件，清除 DONE/FAILED 状态
        if self.hook_manager:
            await self.hook_manager.emit_event(
                source="frontend",
                pane_id=pane_id,
                event_type="click_pane",
            )

        success = await self.iterm_client.activate_session(pane_id)
        await websocket.send_json(
            {"type": "activate_result", "pane_id": pane_id, "success": success}
        )

    async def _handle_rename_action(self, websocket: WebSocket, msg: dict):
        """处理重命名请求

        JSON 格式: {"action": "rename", "type": "pane|tab|window", "id": "xxx", "name": "yyy"}
        """
        success = await self._handle_rename(msg)
        await websocket.send_json(
            {
                "type": "rename_result",
                "target_type": msg.get("type", ""),
                "id": msg.get("id", ""),
                "success": success,
            }
        )

    async def _handle_create_tab_action(self, websocket: WebSocket, msg: dict):
        """处理创建 Tab 请求

        JSON 格式: {"action": "create_tab", "window_id": "xxx", "layout": "single|split"}
        """
        success = await self._handle_create_tab(msg)
        await websocket.send_json(
            {"type": "create_tab_result", "window_id": msg.get("window_id", ""), "success": success}
        )

    async def _handle_rename(self, msg: dict) -> bool:
        """处理重命名请求"""
        target_type = msg.get("type")
        target_id = msg.get("id")
        name = msg.get("name")
        if not all([target_type, target_id, name]):
            logger.warning(f"[WS] Rename missing required fields: {msg}")
            return False

        success = await self.iterm_client.rename_item(target_type, target_id, name)
        if success:
            await self.pipeline.check_updates()
            await self.broadcast(self.pipeline.get_layout_dict())
        return success

    async def _handle_create_tab(self, msg: dict) -> bool:
        """处理创建 Tab 请求"""
        window_id = msg.get("window_id")
        if not window_id:
            logger.warning(f"[WS] Create tab missing window_id: {msg}")
            return False

        layout = msg.get("layout", "single")
        success = await self.iterm_client.create_tab(window_id, layout)
        if success:
            await self.pipeline.check_updates()
            await self.broadcast(self.pipeline.get_layout_dict())
        return success

    async def _handle_debug_subscribe(self, websocket: WebSocket, msg: dict):
        """处理调试订阅请求

        JSON 格式: {"action": "debug_subscribe", "subscribe": true|false}
        """
        subscribe = msg.get("subscribe", True)

        if not self.web_server:
            await websocket.send_json(
                {
                    "type": "debug_subscribe_result",
                    "success": False,
                    "message": "WebServer not initialized",
                }
            )
            return

        if subscribe:
            self.web_server.subscribe_debug(websocket)
            logger.info("[WS] Debug subscription enabled")
        else:
            self.web_server.unsubscribe_debug(websocket)
            logger.info("[WS] Debug subscription disabled")

        await websocket.send_json(
            {
                "type": "debug_subscribe_result",
                "success": True,
                "subscribed": subscribe,
                "subscriber_count": self.web_server.debug_subscriber_count,
            }
        )

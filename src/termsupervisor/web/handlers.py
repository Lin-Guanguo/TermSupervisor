"""WebSocket 消息处理器"""

import json
from dataclasses import dataclass
from typing import Callable, Awaitable

from fastapi import WebSocket

from termsupervisor.iterm import ITerm2Client
from termsupervisor.supervisor import TermSupervisor


@dataclass
class MessageHandler:
    """WebSocket 消息处理器"""

    iterm_client: ITerm2Client
    supervisor: TermSupervisor
    broadcast: Callable[[dict], Awaitable[None]]

    async def handle(self, websocket: WebSocket, data: str):
        """处理 WebSocket 消息"""
        if data.startswith("activate:"):
            await self._handle_activate(websocket, data)
        elif data.startswith("{"):
            await self._handle_json(websocket, data)

    async def _handle_activate(self, websocket: WebSocket, data: str):
        """处理激活请求"""
        session_id = data.split(":", 1)[1]
        success = await self.iterm_client.activate_session(session_id)
        await websocket.send_json({
            "type": "activate_result",
            "session_id": session_id,
            "success": success
        })

    async def _handle_json(self, websocket: WebSocket, data: str):
        """处理 JSON 消息"""
        msg = json.loads(data)
        if msg.get("action") == "rename":
            success = await self._handle_rename(msg)
            await websocket.send_json({
                "type": "rename_result",
                "target_type": msg["type"],
                "id": msg["id"],
                "success": success
            })
        elif msg.get("action") == "create_tab":
            success = await self._handle_create_tab(msg)
            await websocket.send_json({
                "type": "create_tab_result",
                "window_id": msg["window_id"],
                "success": success
            })

    async def _handle_rename(self, msg: dict) -> bool:
        """处理重命名请求"""
        success = await self.iterm_client.rename_item(
            msg["type"], msg["id"], msg["name"]
        )
        if success:
            await self.supervisor.check_updates(self.iterm_client.connection)
            await self.broadcast(self.supervisor.get_layout_dict())
        return success

    async def _handle_create_tab(self, msg: dict) -> bool:
        """处理创建 Tab 请求"""
        layout = msg.get("layout", "single")
        success = await self.iterm_client.create_tab(msg["window_id"], layout)
        if success:
            await self.supervisor.check_updates(self.iterm_client.connection)
            await self.broadcast(self.supervisor.get_layout_dict())
        return success

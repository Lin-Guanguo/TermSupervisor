"""HTTP Hook 接收器 - 接收外部 Hook 事件"""

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .manager import HookManager

logger = logging.getLogger(__name__)


class HookEventRequest(BaseModel):
    """Hook 事件请求体"""

    source: str  # 来源: "claude-code", "gemini", "codex"
    event: str  # 事件类型
    pane_id: str  # iTerm2 session_id ($ITERM_SESSION_ID)
    data: dict = {}  # 额外数据


class HookEventResponse(BaseModel):
    """Hook 事件响应"""

    success: bool
    message: str


class HookReceiver:
    """HTTP Hook 接收器

    提供 `/api/hook` 端点，接收外部工具的 hook 事件。
    """

    def __init__(self, manager: "HookManager"):
        self.manager = manager
        self._adapters: dict = {}  # source_name -> HookSource

    @property
    def hook_manager(self) -> "HookManager":
        """获取 HookManager 实例"""
        return self.manager

    def register_adapter(self, adapter) -> None:
        """注册适配器"""
        self._adapters[adapter.source_name] = adapter
        logger.info(f"[HookReceiver] 注册适配器: {adapter.source_name}")

    def setup_routes(self, app: "FastAPI") -> None:
        """设置 API 路由"""

        @app.post("/api/hook", response_model=HookEventResponse)
        async def receive_hook(request: HookEventRequest):
            """接收 Hook 事件"""
            logger.debug(
                f"[HookReceiver] 收到事件: {request.source}/{request.event} -> {request.pane_id}"
            )

            # 查找适配器
            adapter = self._adapters.get(request.source)
            if not adapter:
                logger.warning(f"[HookReceiver] 未知来源: {request.source}")
                return HookEventResponse(success=False, message=f"Unknown source: {request.source}")

            try:
                await adapter.handle_event(
                    pane_id=request.pane_id, event=request.event, data=request.data
                )
                return HookEventResponse(success=True, message="Event processed")
            except Exception as e:
                logger.error(f"[HookReceiver] 处理事件失败: {e}")
                return HookEventResponse(success=False, message=str(e))

        @app.get("/api/hook/status")
        async def hook_status():
            """获取 Hook 系统状态"""
            return {
                "adapters": list(self._adapters.keys()),
                "panes": list(self.manager.get_all_panes()),
            }

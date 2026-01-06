"""Bootstrap - 集中构造系统组件

职责：
- 创建 HookManager, 各 Source, Receiver
- 返回 RuntimeComponents 供调用方使用

不负责：
- 启动/停止生命周期（由调用方管理）
- Supervisor/WebServer 创建（独立于 hook 系统）
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..hooks.manager import HookManager
from ..hooks.receiver import HookReceiver
from ..hooks.sources.claude_code import ClaudeCodeHookSource
from ..hooks.sources.iterm import ItermHookSource
from ..hooks.sources.shell import ShellHookSource
from ..telemetry import get_logger

if TYPE_CHECKING:
    import iterm2

logger = get_logger(__name__)

# Global registry to track bootstrap state and prevent dual-construction
_current_components: "RuntimeComponents | None" = None


@dataclass
class RuntimeComponents:
    """Bootstrap 返回的运行时组件集合"""

    hook_manager: HookManager
    receiver: HookReceiver
    shell_source: ShellHookSource
    claude_code_source: ClaudeCodeHookSource
    iterm_source: ItermHookSource

    async def start_sources(self) -> None:
        """启动所有 source（Supervisor 启动后调用）"""
        await self.shell_source.start()
        await self.claude_code_source.start()
        await self.iterm_source.start()
        logger.info("[Bootstrap] All sources started")

    async def stop_sources(self) -> None:
        """停止所有 source"""
        await self.shell_source.stop()
        await self.claude_code_source.stop()
        await self.iterm_source.stop()
        logger.info("[Bootstrap] All sources stopped")


def bootstrap(connection: "iterm2.Connection") -> RuntimeComponents:
    """构造运行时组件

    Args:
        connection: iTerm2 连接

    Returns:
        RuntimeComponents 包含所有构造好的组件

    Raises:
        RuntimeError: 如果已经调用过 bootstrap（防止双重构造）
    """
    global _current_components

    if _current_components is not None:
        raise RuntimeError("bootstrap() has already been called.")

    # 1. 创建 HookManager
    hook_manager = HookManager()

    # 2. 创建 Sources
    shell_source = ShellHookSource(hook_manager, connection)
    claude_code_source = ClaudeCodeHookSource(hook_manager)
    iterm_source = ItermHookSource(hook_manager, connection)

    # 3. 创建 Receiver 并注册适配器
    receiver = HookReceiver(hook_manager)
    receiver.register_adapter(claude_code_source)

    logger.info("[Bootstrap] Components created")

    _current_components = RuntimeComponents(
        hook_manager=hook_manager,
        receiver=receiver,
        shell_source=shell_source,
        claude_code_source=claude_code_source,
        iterm_source=iterm_source,
    )

    return _current_components

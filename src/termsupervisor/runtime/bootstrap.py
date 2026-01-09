"""Bootstrap - 集中构造系统组件

职责：
- 创建 HookManager, 各 Source, Receiver
- 返回 RuntimeComponents 供调用方使用
- 支持 iTerm2、tmux 和 composite（iTerm2+tmux）三种终端模式

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
from ..hooks.sources.tmux import TmuxHookSource
from ..telemetry import get_logger

if TYPE_CHECKING:
    import iterm2

    from ..adapters.tmux import TmuxClient

logger = get_logger(__name__)

# Global registry to track bootstrap state and prevent dual-construction
_current_components: "RuntimeComponents | None" = None


@dataclass
class RuntimeComponents:
    """Bootstrap 返回的运行时组件集合

    支持 iTerm2、tmux 和 composite（iTerm2+tmux）三种终端模式。
    - iterm2: shell_source + iterm_source
    - tmux: tmux_source only
    - composite: shell_source + iterm_source + tmux_source (all active)
    """

    hook_manager: HookManager
    receiver: HookReceiver
    claude_code_source: ClaudeCodeHookSource
    terminal_type: str  # "iterm2", "tmux", or "composite"

    # iTerm2-specific sources (active in iterm2 and composite modes)
    shell_source: ShellHookSource | None = None
    iterm_source: ItermHookSource | None = None

    # tmux-specific sources (active in tmux and composite modes)
    tmux_source: TmuxHookSource | None = None

    async def start_sources(self) -> None:
        """启动所有 source（Supervisor 启动后调用）"""
        await self.claude_code_source.start()

        if self.terminal_type in ("iterm2", "composite"):
            if self.shell_source:
                await self.shell_source.start()
            if self.iterm_source:
                await self.iterm_source.start()

        if self.terminal_type in ("tmux", "composite"):
            if self.tmux_source:
                await self.tmux_source.start()

        logger.info(f"[Bootstrap] All sources started (mode={self.terminal_type})")

    async def stop_sources(self) -> None:
        """停止所有 source"""
        await self.claude_code_source.stop()

        if self.terminal_type in ("iterm2", "composite"):
            if self.shell_source:
                await self.shell_source.stop()
            if self.iterm_source:
                await self.iterm_source.stop()

        if self.terminal_type in ("tmux", "composite"):
            if self.tmux_source:
                await self.tmux_source.stop()

        logger.info(f"[Bootstrap] All sources stopped (mode={self.terminal_type})")


def bootstrap(connection: "iterm2.Connection") -> RuntimeComponents:
    """构造 iTerm2 模式的运行时组件

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

    logger.info("[Bootstrap] iTerm2 components created")

    _current_components = RuntimeComponents(
        hook_manager=hook_manager,
        receiver=receiver,
        claude_code_source=claude_code_source,
        terminal_type="iterm2",
        shell_source=shell_source,
        iterm_source=iterm_source,
    )

    return _current_components


def bootstrap_tmux(tmux_client: "TmuxClient") -> RuntimeComponents:
    """构造 tmux 模式的运行时组件

    Args:
        tmux_client: TmuxClient 实例

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

    # 2. 创建 Sources (Claude Code + Tmux focus)
    claude_code_source = ClaudeCodeHookSource(hook_manager)
    tmux_source = TmuxHookSource(hook_manager, tmux_client)

    # 3. 创建 Receiver 并注册适配器
    receiver = HookReceiver(hook_manager)
    receiver.register_adapter(claude_code_source)

    logger.info("[Bootstrap] Tmux components created")

    _current_components = RuntimeComponents(
        hook_manager=hook_manager,
        receiver=receiver,
        claude_code_source=claude_code_source,
        terminal_type="tmux",
        tmux_source=tmux_source,
    )

    return _current_components


def bootstrap_composite(
    connection: "iterm2.Connection",
    tmux_client: "TmuxClient",
) -> RuntimeComponents:
    """构造 composite 模式的运行时组件

    Composite 模式同时启用 iTerm2 和 tmux 的 sources：
    - Shell + iTerm focus 用于 iTerm2 原生 pane
    - Tmux focus 用于 tmux pane

    Args:
        connection: iTerm2 连接
        tmux_client: TmuxClient 实例

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

    # 2. 创建所有 Sources
    # In composite mode, enable namespace for all focus events
    shell_source = ShellHookSource(hook_manager, connection)
    claude_code_source = ClaudeCodeHookSource(hook_manager)
    iterm_source = ItermHookSource(hook_manager, connection, use_namespace=True)
    tmux_source = TmuxHookSource(hook_manager, tmux_client, use_namespace=True)

    # 3. 创建 Receiver 并注册适配器
    receiver = HookReceiver(hook_manager)
    receiver.register_adapter(claude_code_source)

    logger.info("[Bootstrap] Composite (iTerm2 + tmux) components created")

    _current_components = RuntimeComponents(
        hook_manager=hook_manager,
        receiver=receiver,
        claude_code_source=claude_code_source,
        terminal_type="composite",
        shell_source=shell_source,
        iterm_source=iterm_source,
        tmux_source=tmux_source,
    )

    return _current_components


def reset_bootstrap() -> None:
    """Reset bootstrap state (for testing only)."""
    global _current_components
    _current_components = None

"""Adapter factory for creating terminal adapters."""

import logging
import os
from typing import TYPE_CHECKING

from termsupervisor import config

if TYPE_CHECKING:
    import iterm2

    from termsupervisor.adapters.base import TerminalAdapter

logger = logging.getLogger(__name__)


def detect_terminal_type() -> str:
    """Detect terminal type from environment.

    Returns:
        "tmux" if $TMUX is set, otherwise "iterm2"
    """
    if os.environ.get("TMUX"):
        return "tmux"
    return "iterm2"


def create_adapter(
    adapter_type: str | None = None,
    connection: "iterm2.Connection | None" = None,
    socket_path: str | None = None,
    exclude_names: list[str] | None = None,
) -> "TerminalAdapter":
    """Create a terminal adapter.

    Args:
        adapter_type: Adapter type ("iterm2", "tmux", "auto"). Default from config.
        connection: iTerm2 connection (required for iterm2 adapter)
        socket_path: Tmux socket path (optional for tmux adapter)
        exclude_names: Pane/tab names to exclude

    Returns:
        TerminalAdapter instance

    Raises:
        ValueError: If adapter type is unknown or required connection missing
    """
    if adapter_type is None:
        adapter_type = config.TERMINAL_ADAPTER

    if adapter_type == "auto":
        adapter_type = detect_terminal_type()
        logger.info(f"Auto-detected terminal type: {adapter_type}")

    if adapter_type == "iterm2":
        if connection is None:
            raise ValueError("iTerm2 adapter requires connection")
        from termsupervisor.adapters.iterm2 import ITerm2Adapter

        return ITerm2Adapter(connection, exclude_names=exclude_names)

    if adapter_type == "tmux":
        from termsupervisor.adapters.tmux import TmuxAdapter

        return TmuxAdapter(socket_path=socket_path)

    raise ValueError(f"Unknown adapter type: {adapter_type}")

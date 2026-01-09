"""Adapter factory for creating terminal adapters."""

import logging
import os
from typing import TYPE_CHECKING

from termsupervisor import config

if TYPE_CHECKING:
    import iterm2

    from termsupervisor.adapters.base import TerminalAdapter
    from termsupervisor.adapters.composite import CompositeAdapter

logger = logging.getLogger(__name__)


def detect_terminal_type() -> str:
    """Detect terminal type from environment.

    Returns:
        "tmux" if $TMUX is set, otherwise "iterm2"
    """
    if os.environ.get("TMUX"):
        return "tmux"
    return "iterm2"


def is_tmux_available() -> bool:
    """Check if tmux is available and has active sessions.

    Used to determine if composite mode should be enabled.

    Returns:
        True if tmux is running with at least one session.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["tmux", "list-sessions"],
            capture_output=True,
            timeout=2,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def create_adapter(
    adapter_type: str | None = None,
    connection: "iterm2.Connection | None" = None,
    socket_path: str | None = None,
    exclude_names: list[str] | None = None,
) -> "TerminalAdapter":
    """Create a terminal adapter.

    Args:
        adapter_type: Adapter type ("iterm2", "tmux", "composite", "auto").
                      Default from config.
        connection: iTerm2 connection (required for iterm2/composite adapter)
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

        return TmuxAdapter(socket_path=socket_path, exclude_names=exclude_names)

    if adapter_type == "composite":
        if connection is None:
            raise ValueError("Composite adapter requires iTerm2 connection")
        return create_composite_adapter(
            connection=connection,
            socket_path=socket_path,
            exclude_names=exclude_names,
        )

    raise ValueError(f"Unknown adapter type: {adapter_type}")


def create_composite_adapter(
    connection: "iterm2.Connection",
    socket_path: str | None = None,
    exclude_names: list[str] | None = None,
) -> "CompositeAdapter":
    """Create a composite adapter combining iTerm2 and tmux.

    Args:
        connection: iTerm2 connection
        socket_path: Optional tmux socket path
        exclude_names: Pane/tab names to exclude

    Returns:
        CompositeAdapter instance
    """
    from termsupervisor.adapters.composite import CompositeAdapter
    from termsupervisor.adapters.iterm2 import ITerm2Adapter
    from termsupervisor.adapters.tmux import TmuxAdapter
    from termsupervisor.adapters.tmux.client import TmuxClient

    iterm2_adapter = ITerm2Adapter(connection, exclude_names=exclude_names)
    tmux_client = TmuxClient(socket_path=socket_path)
    tmux_adapter = TmuxAdapter(socket_path=socket_path, exclude_names=exclude_names)

    return CompositeAdapter(
        iterm2_adapter=iterm2_adapter,
        tmux_adapter=tmux_adapter,
        tmux_client=tmux_client,
        exclude_names=exclude_names,
    )

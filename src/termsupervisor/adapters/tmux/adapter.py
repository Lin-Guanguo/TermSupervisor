"""Tmux adapter implementing TerminalAdapter protocol."""

import logging
from typing import TYPE_CHECKING

from termsupervisor.adapters.base import JobMetadata

from .client import TmuxClient
from .layout import TmuxLayoutBuilder

if TYPE_CHECKING:
    from termsupervisor.adapters.iterm2.models import LayoutData

logger = logging.getLogger(__name__)


class TmuxAdapter:
    """Tmux adapter implementing TerminalAdapter protocol.

    Wraps TmuxClient to provide the standard adapter interface.
    """

    name: str = "tmux"

    def __init__(self, socket_path: str | None = None):
        """Initialize TmuxAdapter.

        Args:
            socket_path: Optional tmux socket path.
        """
        self._client = TmuxClient(socket_path=socket_path)
        self._layout_builder = TmuxLayoutBuilder()

    @property
    def client(self) -> TmuxClient:
        """Access underlying TmuxClient."""
        return self._client

    async def get_layout(self) -> "LayoutData | None":
        """Get current layout from tmux.

        Returns:
            LayoutData with windows/tabs/panes, or None on error.
        """
        try:
            windows = await self._client.list_windows()
            panes = await self._client.list_panes()
            return self._layout_builder.build(windows=windows, panes=panes)
        except Exception as e:
            logger.error(f"Failed to get tmux layout: {e}")
            return None

    async def get_pane_content(self, pane_id: str) -> str | None:
        """Get content from a pane.

        Args:
            pane_id: The pane identifier (e.g., "%0")

        Returns:
            Pane content string, or None if not found.
        """
        return await self._client.capture_pane(pane_id)

    async def get_job_metadata(self, pane_id: str) -> JobMetadata | None:
        """Get job metadata for a pane.

        Args:
            pane_id: The pane identifier

        Returns:
            JobMetadata with current command info, or None if not found.
        """
        info = await self._client.get_pane_info(pane_id)
        if info is None:
            return None

        return JobMetadata(
            job_name=info.get("current_command", "").split()[0] if info.get("current_command") else "",
            path=info.get("path", ""),
            command_line=info.get("current_command", ""),
        )

    async def activate_pane(self, pane_id: str) -> bool:
        """Activate/focus a pane.

        Args:
            pane_id: The pane identifier

        Returns:
            True on success, False on failure.
        """
        return await self._client.select_pane(pane_id)

    async def rename_pane(self, pane_id: str, name: str) -> bool:
        """Rename a pane.

        Args:
            pane_id: The pane identifier
            name: New name for the pane

        Returns:
            True on success, False on failure.
        """
        return await self._client.rename_pane(pane_id, name)

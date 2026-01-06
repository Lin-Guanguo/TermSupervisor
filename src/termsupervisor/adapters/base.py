"""Terminal adapter base types and protocol.

Defines the interface that all terminal adapters must implement.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from termsupervisor.adapters.iterm2.models import LayoutData


@dataclass
class JobMetadata:
    """Foreground job metadata.

    Common metadata available from terminal emulators about the current
    foreground process in a pane.
    """

    job_name: str = ""
    job_pid: int | None = None
    command_line: str = ""
    tty: str = ""
    path: str = ""  # Current working directory


@runtime_checkable
class TerminalAdapter(Protocol):
    """Terminal adapter protocol.

    Defines the minimal interface for terminal adapters (iTerm2, tmux, etc.).
    All adapters must implement these methods to work with RenderPipeline.
    """

    name: str  # Adapter name: "iterm2", "tmux"

    async def get_layout(self) -> "LayoutData | None":
        """Get current terminal layout.

        Returns:
            LayoutData with windows/tabs/panes, or None if unavailable.
        """
        ...

    async def get_pane_content(self, pane_id: str) -> str | None:
        """Get content of a specific pane.

        Args:
            pane_id: The pane ID to get content for.

        Returns:
            Pane content string, or None if unavailable.
        """
        ...

    async def get_job_metadata(self, pane_id: str) -> JobMetadata | None:
        """Get foreground job metadata for a pane.

        Args:
            pane_id: The pane ID.

        Returns:
            JobMetadata with process info, or None if unavailable.
        """
        ...

    async def activate_pane(self, pane_id: str) -> bool:
        """Activate/focus a specific pane.

        Args:
            pane_id: The pane ID to activate.

        Returns:
            True if successful, False otherwise.
        """
        ...

    async def rename_pane(self, pane_id: str, name: str) -> bool:
        """Rename a pane.

        Args:
            pane_id: The pane ID to rename.
            name: The new name.

        Returns:
            True if successful, False otherwise.
        """
        ...

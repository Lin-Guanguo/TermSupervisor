"""iTerm2 adapter implementing TerminalAdapter protocol."""

import logging
from typing import TYPE_CHECKING

from termsupervisor.adapters.base import JobMetadata, TerminalAdapter
from termsupervisor.adapters.iterm2.client import ITerm2Client
from termsupervisor.adapters.iterm2.client import JobMetadata as ITerm2JobMetadata
from termsupervisor.adapters.iterm2.layout import get_layout

if TYPE_CHECKING:
    import iterm2

    from termsupervisor.adapters.iterm2.models import LayoutData

logger = logging.getLogger(__name__)


class ITerm2Adapter:
    """iTerm2 adapter implementing TerminalAdapter protocol.

    Wraps ITerm2Client and provides a uniform interface for RenderPipeline.
    """

    name: str = "iterm2"

    def __init__(
        self,
        connection: "iterm2.Connection",
        exclude_names: list[str] | None = None,
    ):
        """Initialize iTerm2 adapter.

        Args:
            connection: iTerm2 connection
            exclude_names: Tab/pane names to exclude from layout
        """
        self._client = ITerm2Client(connection)
        self._exclude_names = exclude_names or []

    @property
    def client(self) -> ITerm2Client:
        """Access underlying ITerm2Client for operations not in protocol."""
        return self._client

    async def get_layout(self) -> "LayoutData | None":
        """Get current terminal layout."""
        app = await self._client.get_app()
        if app is None:
            return None
        return await get_layout(app, self._exclude_names)

    async def get_pane_content(self, pane_id: str) -> str | None:
        """Get content of a specific pane."""
        app = await self._client.get_app()
        if app is None:
            return None

        session = app.get_session_by_id(pane_id)
        if session is None:
            return None

        return await self._client.get_session_content(session)

    async def get_job_metadata(self, pane_id: str) -> JobMetadata | None:
        """Get foreground job metadata for a pane."""
        app = await self._client.get_app()
        if app is None:
            return None

        session = app.get_session_by_id(pane_id)
        if session is None:
            return None

        iterm_job = await self._client.get_session_job_metadata(session)
        return self._convert_job_metadata(iterm_job)

    async def activate_pane(self, pane_id: str) -> bool:
        """Activate/focus a specific pane."""
        return await self._client.activate_session(pane_id)

    async def rename_pane(self, pane_id: str, name: str) -> bool:
        """Rename a pane."""
        return await self._client.rename_session(pane_id, name)

    @staticmethod
    def _convert_job_metadata(iterm_job: ITerm2JobMetadata) -> JobMetadata:
        """Convert iTerm2-specific JobMetadata to base JobMetadata."""
        return JobMetadata(
            job_name=iterm_job.job_name,
            job_pid=iterm_job.job_pid,
            command_line=iterm_job.command_line,
            tty=iterm_job.tty,
            path=iterm_job.path,
        )


# Type assertion to verify protocol compliance
def _check_protocol_compliance() -> None:
    """Static check that ITerm2Adapter satisfies TerminalAdapter."""
    adapter: TerminalAdapter = ITerm2Adapter.__new__(ITerm2Adapter)  # type: ignore[arg-type]
    _ = adapter  # Use to avoid unused variable warning

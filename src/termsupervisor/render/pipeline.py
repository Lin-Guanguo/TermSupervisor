"""Render Pipeline

Coordinates content polling, change detection, caching, and notifications.
"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from termsupervisor import config
from termsupervisor.analysis import ContentCleaner
from termsupervisor.core.ids import id_match, normalize_id
from termsupervisor.state import TaskStatus

from .cache import LayoutCache
from .detector import ChangeDetector
from .poller import ContentPoller
from .types import LayoutUpdate

if TYPE_CHECKING:
    from termsupervisor.adapters.iterm2 import ITerm2Client
    from termsupervisor.adapters.iterm2.client import JobMetadata
    from termsupervisor.adapters.iterm2.models import LayoutData
    from termsupervisor.hooks.manager import HookManager

logger = logging.getLogger(__name__)

# Type for status provider callback
StatusProviderCallback = Callable[[str], dict[str, Any] | None]

# Callback type for layout updates
LayoutUpdateCallback = Callable[[LayoutUpdate], Awaitable[None]]


class RenderPipeline:
    """Render Pipeline

    Coordinates:
    - Content polling from terminal adapter
    - Change detection with debouncing
    - Layout and content caching
    - Subscriber notifications

    Data flow:
        tick() → poll_layout() → poll_contents() → detect_changes() → notify()
    """

    def __init__(
        self,
        iterm_client: "ITerm2Client",
        exclude_names: list[str] | None = None,
        refresh_lines: int | None = None,
        waiting_refresh_lines: int | None = None,
        flush_timeout: float | None = None,
    ):
        """Initialize the render pipeline.

        Args:
            iterm_client: iTerm2 client for terminal access
            exclude_names: Tab/pane names to exclude from monitoring
            refresh_lines: Minimum changed lines to trigger refresh
            waiting_refresh_lines: Changed lines threshold when WAITING
            flush_timeout: Maximum time between refreshes
        """
        self._poller = ContentPoller(iterm_client, exclude_names)
        self._detector = ChangeDetector(
            refresh_lines=refresh_lines,
            waiting_refresh_lines=waiting_refresh_lines,
            flush_timeout=flush_timeout,
        )
        self._cache = LayoutCache()
        self._callbacks: list[LayoutUpdateCallback] = []
        self._running = False

        # External state providers (e.g., HookManager)
        self._waiting_provider: Callable[[str], bool] | None = None
        self._status_provider: StatusProviderCallback | None = None

    @property
    def cache(self) -> LayoutCache:
        """Access the layout cache."""
        return self._cache

    @property
    def layout(self) -> "LayoutData":
        """Get current layout data."""
        return self._cache.layout

    def set_waiting_provider(self, provider: Callable[[str], bool]) -> None:
        """Set callback to check if a pane is in WAITING state.

        Args:
            provider: Function that returns True if pane_id is WAITING
        """
        self._waiting_provider = provider

    def on_update(self, callback: LayoutUpdateCallback) -> None:
        """Register a callback for layout updates.

        Args:
            callback: Async function called with LayoutUpdate
        """
        self._callbacks.append(callback)

    async def check_updates(self) -> list[str]:
        """Execute one polling cycle.

        Compatibility method for Supervisor interface.

        Returns:
            List of pane IDs that were updated
        """
        update = await self.tick()
        return update.updated_panes

    async def tick(self) -> LayoutUpdate:
        """Execute one polling cycle.

        Returns:
            LayoutUpdate with changed panes and current state
        """
        # 1. Poll layout
        layout = await self._poller.poll_layout()
        if layout is None:
            return LayoutUpdate(layout=self._cache.layout)

        self._cache.update_layout(layout)

        # 2. Poll content and detect changes for each pane
        updated_panes: list[str] = []

        for window in layout.windows:
            for tab in window.tabs:
                for pane in tab.panes:
                    pane_id = pane.pane_id

                    # Get content
                    content = await self._poller.get_pane_content(pane_id)
                    if content is None:
                        continue

                    # Get job metadata
                    job = await self._poller.get_job_metadata(pane_id)

                    # Check WAITING state
                    is_waiting = False
                    if self._waiting_provider:
                        is_waiting = self._waiting_provider(pane_id)

                    # Clean content and compute hash
                    cleaned_content = ContentCleaner.clean_content_str(content)
                    content_hash = ContentCleaner.content_hash(cleaned_content)

                    # Check if refresh needed
                    should_refresh = self._detector.should_refresh(
                        pane_id, cleaned_content, is_waiting
                    )

                    # Update cache
                    self._cache.update_pane_state(
                        pane_id=pane_id,
                        name=pane.name,
                        content=content,
                        content_hash=content_hash,
                        cleaned_content=cleaned_content,
                        job=job,
                        is_waiting=is_waiting,
                    )

                    if should_refresh:
                        updated_panes.append(pane_id)
                        self._detector.mark_rendered(pane_id, cleaned_content)
                        self._cache.mark_rendered(pane_id)

        # 3. Cleanup closed panes
        closed_panes = self._cache.cleanup_closed_panes()
        for pane_id in closed_panes:
            self._detector.remove_pane(pane_id)

        # 4. Build update notification
        update = LayoutUpdate(
            layout=layout,
            updated_panes=updated_panes,
            pane_states=dict(self._cache.pane_states),
        )

        # 5. Notify callbacks
        await self._notify(update)

        return update

    async def _notify(self, update: LayoutUpdate) -> None:
        """Notify all registered callbacks.

        Args:
            update: The layout update to broadcast
        """
        for callback in self._callbacks:
            try:
                await callback(update)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def run(self, interval: float | None = None) -> None:
        """Run the polling loop.

        Args:
            interval: Polling interval in seconds (default from config)
        """
        if interval is None:
            interval = config.POLL_INTERVAL

        self._running = True
        logger.info(f"RenderPipeline started, interval: {interval}s")

        while self._running:
            try:
                await self.tick()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(interval)

        logger.info("RenderPipeline stopped")

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False

    def get_pane_content(self, pane_id: str) -> str | None:
        """Get cached content for a pane.

        Args:
            pane_id: The pane ID

        Returns:
            Cached content or None if not found
        """
        state = self._cache.get_pane_state(pane_id)
        if state:
            return state.current.content
        return None

    def get_job_metadata(self, pane_id: str) -> "JobMetadata | None":
        """Get cached job metadata for a pane.

        Args:
            pane_id: The pane ID

        Returns:
            Cached job metadata or None if not found
        """
        state = self._cache.get_pane_state(pane_id)
        if state:
            return state.job
        return None

    def set_status_provider(self, provider: StatusProviderCallback) -> None:
        """Set callback to get pane status info.

        The provider should return a dict with status info for the pane_id,
        or None if the pane has no status. The dict should contain:
        - status: TaskStatus value
        - status_color: color string
        - status_reason: description string
        - is_running: bool
        - needs_notification: bool
        - needs_attention: bool
        - display: display string

        Args:
            provider: Function that returns status dict for a pane_id
        """
        self._status_provider = provider

    def get_pane_location(self, pane_id: str) -> tuple[str, str, str]:
        """Get pane's window/tab/pane names.

        Args:
            pane_id: The pane ID

        Returns:
            Tuple of (window_name, tab_name, pane_name)
        """
        tab_index = 0
        for window in self.layout.windows:
            for tab in window.tabs:
                tab_index += 1
                for pane in tab.panes:
                    if id_match(pane.pane_id, pane_id):
                        tab_display = tab.name if tab.name else f"Tab{tab_index}"
                        return (window.name or "Window", tab_display, pane.name or "Pane")

        # Try to get from pane_states if not in current layout
        pure_id = normalize_id(pane_id)
        state = self._cache.get_pane_state(pure_id)
        if state:
            return ("Window", "Tab", state.name or "Pane")
        return ("Window", "Tab", "Pane")

    @staticmethod
    def _shorten_path(path: str) -> str:
        """Replace home directory prefix with ~."""
        if not path:
            return ""
        home = os.path.expanduser("~")
        if path.startswith(home):
            return "~" + path[len(home):]
        return path

    def get_layout_dict(self) -> dict:
        """Get layout data as dict with status info.

        Returns:
            Dict containing layout data and pane_statuses
        """
        data = self.layout.to_dict()
        pane_statuses = {}

        for window in self.layout.windows:
            for tab in window.tabs:
                for pane in tab.panes:
                    pane_id = pane.pane_id
                    state = self._cache.get_pane_state(pane_id)
                    job = state.job if state else None
                    path = self._shorten_path(job.path) if job else ""

                    # Get status from provider
                    status_info = None
                    if self._status_provider:
                        status_info = self._status_provider(pane_id)

                    if status_info:
                        pane_statuses[pane_id] = {
                            **status_info,
                            "job_name": job.job_name if job else "",
                            "path": path,
                        }
                    else:
                        # Default to IDLE status
                        pane_statuses[pane_id] = {
                            "status": TaskStatus.IDLE.value,
                            "status_color": TaskStatus.IDLE.color,
                            "status_reason": "",
                            "is_running": False,
                            "needs_notification": False,
                            "needs_attention": False,
                            "display": "",
                            "job_name": job.job_name if job else "",
                            "path": path,
                        }

        data["pane_statuses"] = pane_statuses
        return data

    def get_pane_ids(self) -> set[str]:
        """Get all tracked pane IDs.

        Returns:
            Set of pane IDs currently in the cache
        """
        return set(self._cache.pane_states.keys())

"""Composite adapter for iTerm2 + tmux integration.

Provides unified layout by combining iTerm2 windows/tabs with tmux
windows/panes when running tmux inside iTerm2.

Architecture:
- iTerm2 is the primary adapter (provides window/tab structure)
- tmux is detected via tty matching with tmux clients
- iTerm2 panes running tmux are "expanded" to show tmux windows as tabs
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from termsupervisor.adapters.base import JobMetadata
from termsupervisor.adapters.iterm2.models import (
    LayoutData,
    PaneInfo,
    TabInfo,
    WindowInfo,
)
from termsupervisor.core.ids import (
    AdapterType,
    get_native_id,
    is_iterm2_id,
    is_tmux_id,
    make_pane_id,
    make_tab_id,
)

if TYPE_CHECKING:
    import iterm2

    from termsupervisor.adapters.iterm2 import ITerm2Adapter
    from termsupervisor.adapters.tmux import TmuxAdapter, TmuxClient

logger = logging.getLogger(__name__)


@dataclass
class TmuxMapping:
    """Mapping between iTerm2 pane and tmux session."""

    iterm2_pane_id: str  # Original iTerm2 pane ID (without namespace)
    iterm2_tty: str
    tmux_session: str


class CompositeAdapter:
    """Composite adapter combining iTerm2 and tmux.

    When running tmux inside iTerm2:
    - Detects iTerm2 panes that are tmux clients via tty matching
    - Expands those panes to show tmux windows as virtual tabs
    - Routes operations to the correct adapter based on pane ID namespace
    """

    name: str = "composite"

    def __init__(
        self,
        iterm2_adapter: "ITerm2Adapter",
        tmux_adapter: "TmuxAdapter",
        tmux_client: "TmuxClient",
        exclude_names: list[str] | None = None,
    ):
        """Initialize CompositeAdapter.

        Args:
            iterm2_adapter: iTerm2 adapter instance
            tmux_adapter: tmux adapter instance
            tmux_client: tmux client for additional operations
            exclude_names: Pane names to exclude (substring match)
        """
        self._iterm2 = iterm2_adapter
        self._tmux = tmux_adapter
        self._tmux_client = tmux_client
        self._exclude_names = exclude_names or []

        # Cache: iTerm2 pane tty -> TmuxMapping
        self._tmux_mappings: dict[str, TmuxMapping] = {}

        # Cache: namespaced pane_id -> host iTerm2 pane_id (for activation routing)
        self._tmux_host_panes: dict[str, str] = {}

    async def get_layout(self) -> LayoutData | None:
        """Get composite layout merging iTerm2 and tmux.

        Flow:
        1. Get iTerm2 base layout
        2. Detect which iTerm2 panes are tmux clients
        3. For each tmux client pane, expand with tmux windows as tabs

        Returns:
            LayoutData with namespaced IDs, or None on failure.
        """
        # Step 1: Get iTerm2 layout
        iterm2_layout = await self._iterm2.get_layout()
        if not iterm2_layout:
            return None

        # Step 2: Build tty -> tmux session mapping
        await self._refresh_tmux_mappings()

        # Step 3: Get tmux layout for expansion
        tmux_layout = await self._tmux.get_layout()

        # Step 4: Build composite layout
        composite_windows = []
        self._tmux_host_panes.clear()

        for window in iterm2_layout.windows:
            composite_tabs = []

            for tab in window.tabs:
                # Check if any pane in this tab is running tmux
                tmux_panes_in_tab = []
                regular_panes_in_tab = []

                for pane in tab.panes:
                    mapping = await self._get_tmux_mapping_for_pane(pane.pane_id)
                    if mapping:
                        tmux_panes_in_tab.append((pane, mapping))
                    else:
                        regular_panes_in_tab.append(pane)

                if tmux_panes_in_tab and tmux_layout:
                    # This tab has tmux panes - expand them
                    expanded_tabs = self._expand_tmux_tab(
                        tab, tmux_panes_in_tab, regular_panes_in_tab, tmux_layout
                    )
                    composite_tabs.extend(expanded_tabs)
                else:
                    # Regular iTerm2 tab - namespace the pane IDs
                    namespaced_panes = [
                        PaneInfo(
                            pane_id=make_pane_id(AdapterType.ITERM2, p.pane_id),
                            name=p.name,
                            index=p.index,
                            x=p.x,
                            y=p.y,
                            width=p.width,
                            height=p.height,
                        )
                        for p in tab.panes
                    ]
                    composite_tabs.append(
                        TabInfo(
                            tab_id=make_pane_id(AdapterType.ITERM2, tab.tab_id),
                            name=tab.name,
                            panes=namespaced_panes,
                        )
                    )

            if composite_tabs:
                composite_windows.append(
                    WindowInfo(
                        window_id=make_pane_id(AdapterType.ITERM2, window.window_id),
                        name=window.name,
                        x=window.x,
                        y=window.y,
                        width=window.width,
                        height=window.height,
                        tabs=composite_tabs,
                    )
                )

        return LayoutData(windows=composite_windows)

    def _expand_tmux_tab(
        self,
        iterm2_tab: TabInfo,
        tmux_panes: list[tuple[PaneInfo, TmuxMapping]],
        regular_panes: list[PaneInfo],
        tmux_layout: LayoutData,
    ) -> list[TabInfo]:
        """Expand an iTerm2 tab containing tmux panes.

        For each tmux session found, create virtual tabs from tmux windows.

        Args:
            iterm2_tab: Original iTerm2 tab
            tmux_panes: List of (pane, mapping) for panes running tmux
            regular_panes: List of regular (non-tmux) panes
            tmux_layout: Full tmux layout

        Returns:
            List of TabInfo (regular panes + expanded tmux windows)
        """
        result_tabs = []

        # First, add regular panes as a tab (if any)
        if regular_panes:
            namespaced_panes = [
                PaneInfo(
                    pane_id=make_pane_id(AdapterType.ITERM2, p.pane_id),
                    name=p.name,
                    index=p.index,
                    x=p.x,
                    y=p.y,
                    width=p.width,
                    height=p.height,
                )
                for p in regular_panes
            ]
            result_tabs.append(
                TabInfo(
                    tab_id=make_pane_id(AdapterType.ITERM2, iterm2_tab.tab_id),
                    name=iterm2_tab.name,
                    panes=namespaced_panes,
                )
            )

        # Track sessions we've already expanded (avoid duplicates)
        expanded_sessions: set[str] = set()

        for pane, mapping in tmux_panes:
            session_name = mapping.tmux_session
            if session_name in expanded_sessions:
                continue
            expanded_sessions.add(session_name)

            # Find tmux windows for this session
            for tmux_window in tmux_layout.windows:
                # tmux window_id format: "session_id:window_id" (e.g., "$0:@1")
                parts = tmux_window.window_id.split(":")
                if len(parts) >= 2:
                    win_session_id = parts[0]  # e.g., "$0"
                    # Match by session ID (e.g., "$0") or session name/index (e.g., "0")
                    # client_session from list_clients returns name, window uses $id
                    session_id_match = (
                        win_session_id == session_name or  # Direct match
                        win_session_id == f"${session_name}" or  # $0 matches "0"
                        win_session_id.lstrip("$") == session_name  # $0 -> "0"
                    )
                    if not session_id_match:
                        continue

                # Each tmux window becomes a virtual tab
                for tmux_tab in tmux_window.tabs:
                    namespaced_panes = []
                    for tmux_pane in tmux_tab.panes:
                        namespaced_id = make_pane_id(AdapterType.TMUX, tmux_pane.pane_id)
                        # Track host pane for activation routing
                        self._tmux_host_panes[namespaced_id] = pane.pane_id

                        namespaced_panes.append(
                            PaneInfo(
                                pane_id=namespaced_id,
                                name=tmux_pane.name,
                                index=tmux_pane.index,
                                x=tmux_pane.x,
                                y=tmux_pane.y,
                                width=tmux_pane.width,
                                height=tmux_pane.height,
                            )
                        )

                    if namespaced_panes:
                        # Tab name: tmux window name
                        tab_name = tmux_tab.name or tmux_window.name
                        result_tabs.append(
                            TabInfo(
                                tab_id=make_tab_id(
                                    AdapterType.TMUX,
                                    session_name,
                                    tmux_tab.tab_id,
                                ),
                                name=f"[tmux] {tab_name}",
                                panes=namespaced_panes,
                            )
                        )

        return result_tabs

    async def _refresh_tmux_mappings(self) -> None:
        """Refresh tty -> tmux session mappings."""
        self._tmux_mappings.clear()

        clients = await self._tmux_client.list_clients()
        for client in clients:
            tty = client.get("client_tty", "")
            session = client.get("client_session", "")
            if tty and session:
                self._tmux_mappings[tty] = TmuxMapping(
                    iterm2_pane_id="",  # Will be filled when matching
                    iterm2_tty=tty,
                    tmux_session=session,
                )

    async def _get_tmux_mapping_for_pane(self, iterm2_pane_id: str) -> TmuxMapping | None:
        """Check if an iTerm2 pane is running tmux.

        Args:
            iterm2_pane_id: Native iTerm2 pane ID

        Returns:
            TmuxMapping if pane is running tmux, None otherwise.
        """
        # Get pane's tty via job metadata
        job = await self._iterm2.get_job_metadata(iterm2_pane_id)
        if not job or not job.tty:
            return None

        mapping = self._tmux_mappings.get(job.tty)
        if mapping:
            mapping.iterm2_pane_id = iterm2_pane_id
            return mapping

        return None

    async def get_pane_content(self, pane_id: str) -> str | None:
        """Get pane content, routing to correct adapter.

        Args:
            pane_id: Namespaced pane ID

        Returns:
            Pane content string, or None.
        """
        if is_tmux_id(pane_id):
            native_id = get_native_id(pane_id)
            return await self._tmux.get_pane_content(native_id)
        elif is_iterm2_id(pane_id):
            native_id = get_native_id(pane_id)
            return await self._iterm2.get_pane_content(native_id)
        else:
            # Assume legacy ID without namespace - try iTerm2 first
            content = await self._iterm2.get_pane_content(pane_id)
            if content is None:
                content = await self._tmux.get_pane_content(pane_id)
            return content

    async def get_job_metadata(self, pane_id: str) -> JobMetadata | None:
        """Get job metadata, routing to correct adapter.

        Args:
            pane_id: Namespaced pane ID

        Returns:
            JobMetadata, or None.
        """
        if is_tmux_id(pane_id):
            native_id = get_native_id(pane_id)
            return await self._tmux.get_job_metadata(native_id)
        elif is_iterm2_id(pane_id):
            native_id = get_native_id(pane_id)
            return await self._iterm2.get_job_metadata(native_id)
        else:
            # Legacy fallback
            job = await self._iterm2.get_job_metadata(pane_id)
            if job is None:
                job = await self._tmux.get_job_metadata(pane_id)
            return job

    async def activate_pane(self, pane_id: str) -> bool:
        """Activate pane with two-step routing for tmux.

        For tmux panes:
        1. First activate the host iTerm2 pane
        2. Then select the tmux pane

        Args:
            pane_id: Namespaced pane ID

        Returns:
            True on success, False on failure.
        """
        if is_tmux_id(pane_id):
            # Step 1: Activate host iTerm2 pane
            host_pane_id = self._tmux_host_panes.get(pane_id)
            if host_pane_id:
                await self._iterm2.activate_pane(host_pane_id)

            # Step 2: Select tmux pane
            native_id = get_native_id(pane_id)
            return await self._tmux.activate_pane(native_id)

        elif is_iterm2_id(pane_id):
            native_id = get_native_id(pane_id)
            return await self._iterm2.activate_pane(native_id)
        else:
            # Legacy fallback
            return await self._iterm2.activate_pane(pane_id)

    async def rename_pane(self, pane_id: str, name: str) -> bool:
        """Rename pane, routing to correct adapter.

        Args:
            pane_id: Namespaced pane ID
            name: New name

        Returns:
            True on success, False on failure.
        """
        if is_tmux_id(pane_id):
            native_id = get_native_id(pane_id)
            return await self._tmux.rename_pane(native_id, name)
        elif is_iterm2_id(pane_id):
            native_id = get_native_id(pane_id)
            return await self._iterm2.rename_pane(native_id, name)
        else:
            # Legacy fallback
            return await self._iterm2.rename_pane(pane_id, name)

    def get_host_pane_id(self, tmux_pane_id: str) -> str | None:
        """Get the iTerm2 host pane ID for a tmux pane.

        Args:
            tmux_pane_id: Namespaced tmux pane ID

        Returns:
            iTerm2 pane ID, or None if not found.
        """
        return self._tmux_host_panes.get(tmux_pane_id)

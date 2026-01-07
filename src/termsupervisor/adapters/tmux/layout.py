"""Tmux layout builder.

Converts tmux window/pane data into LayoutData structures.
"""

from termsupervisor.adapters.iterm2.models import (
    LayoutData,
    PaneInfo,
    TabInfo,
    WindowInfo,
)


class TmuxLayoutBuilder:
    """Builds LayoutData from tmux window and pane information.

    Tmux structure mapping:
    - tmux session:window -> WindowInfo (identified by "session:window" ID)
    - tmux window -> TabInfo (one tab per window)
    - tmux pane -> PaneInfo
    """

    def __init__(self, exclude_names: list[str] | None = None):
        """Initialize TmuxLayoutBuilder.

        Args:
            exclude_names: List of pane names to exclude (substring match).
        """
        self._exclude_names = exclude_names or []

    def _should_exclude(self, pane_name: str) -> bool:
        """Check if pane should be excluded based on name."""
        return any(excl in pane_name for excl in self._exclude_names)

    def build(self, windows: list[dict], panes: list[dict]) -> LayoutData:
        """Build LayoutData from tmux data.

        Args:
            windows: List of window dicts from TmuxClient.list_windows()
            panes: List of pane dicts from TmuxClient.list_panes()

        Returns:
            LayoutData with windows, tabs, and panes.
        """
        if not windows:
            return LayoutData(windows=[])

        # Group panes by session:window (filtering excluded panes)
        panes_by_window: dict[str, list[dict]] = {}
        for pane in panes:
            # Skip excluded panes
            pane_name = pane.get("pane_name", "")
            if self._should_exclude(pane_name):
                continue

            key = f"{pane['session_id']}:{pane['window_id']}"
            if key not in panes_by_window:
                panes_by_window[key] = []
            panes_by_window[key].append(pane)

        # Build WindowInfo for each tmux window
        window_infos = []
        for win in windows:
            win_key = f"{win['session_id']}:{win['window_id']}"
            win_panes = panes_by_window.get(win_key, [])

            # Skip windows with no panes after filtering
            if not win_panes:
                continue

            # Build PaneInfo list with validation
            pane_infos = []
            for idx, pane in enumerate(win_panes):
                try:
                    pane_info = PaneInfo(
                        pane_id=pane.get("pane_id", ""),
                        name=pane.get("pane_name", ""),
                        index=idx,
                        x=float(pane.get("x", 0)),
                        y=float(pane.get("y", 0)),
                        width=float(pane.get("width", 0)),
                        height=float(pane.get("height", 0)),
                    )
                    pane_infos.append(pane_info)
                except (KeyError, ValueError, TypeError):
                    # Skip malformed pane data
                    continue

            if not pane_infos:
                continue

            # Create TabInfo (one tab per tmux window)
            tab_info = TabInfo(
                tab_id=win_key,
                name=win.get("window_name", ""),
                panes=pane_infos,
            )

            # Create WindowInfo
            window_info = WindowInfo(
                window_id=win_key,
                name=win.get("window_name", ""),
                x=0.0,  # tmux windows don't have position
                y=0.0,
                width=float(win.get("width", 0)),
                height=float(win.get("height", 0)),
                tabs=[tab_info],
            )
            window_infos.append(window_info)

        return LayoutData(windows=window_infos)

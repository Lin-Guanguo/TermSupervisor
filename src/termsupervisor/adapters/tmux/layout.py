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

        # Group panes by session:window
        panes_by_window: dict[str, list[dict]] = {}
        for pane in panes:
            key = f"{pane['session_id']}:{pane['window_id']}"
            if key not in panes_by_window:
                panes_by_window[key] = []
            panes_by_window[key].append(pane)

        # Build WindowInfo for each tmux window
        window_infos = []
        for win in windows:
            win_key = f"{win['session_id']}:{win['window_id']}"
            win_panes = panes_by_window.get(win_key, [])

            # Build PaneInfo list
            pane_infos = []
            for idx, pane in enumerate(win_panes):
                pane_info = PaneInfo(
                    pane_id=pane["pane_id"],
                    name=pane["pane_name"],
                    index=idx,
                    x=float(pane["x"]),
                    y=float(pane["y"]),
                    width=float(pane["width"]),
                    height=float(pane["height"]),
                )
                pane_infos.append(pane_info)

            # Create TabInfo (one tab per tmux window)
            tab_info = TabInfo(
                tab_id=win_key,
                name=win["window_name"],
                panes=pane_infos,
            )

            # Create WindowInfo
            window_info = WindowInfo(
                window_id=win_key,
                name=win["window_name"],
                x=0.0,  # tmux windows don't have position
                y=0.0,
                width=float(win["width"]),
                height=float(win["height"]),
                tabs=[tab_info],
            )
            window_infos.append(window_info)

        return LayoutData(windows=window_infos)

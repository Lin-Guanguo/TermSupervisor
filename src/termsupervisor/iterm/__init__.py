"""iTerm2 交互模块"""

from termsupervisor.iterm.client import ITerm2Client
from termsupervisor.iterm.layout import get_layout
from termsupervisor.iterm.models import (
    LayoutData,
    PaneInfo,
    PaneSnapshot,
    TabInfo,
    UpdateCallback,
    WindowInfo,
)
from termsupervisor.iterm.naming import (
    get_name,
    get_session_name,
    get_tab_name,
    get_window_name,
    set_name,
    set_session_name,
    set_tab_name,
    set_window_name,
)
# Re-export from core for backwards compatibility
from termsupervisor.core.ids import id_match as session_id_match
from termsupervisor.core.ids import normalize_id as normalize_session_id

__all__ = [
    "ITerm2Client",
    "get_layout",
    # Layout models
    "PaneInfo",
    "TabInfo",
    "WindowInfo",
    "LayoutData",
    "PaneSnapshot",
    "UpdateCallback",
    # Naming
    "get_name",
    "get_session_name",
    "get_tab_name",
    "get_window_name",
    "set_name",
    "set_session_name",
    "set_tab_name",
    "set_window_name",
    # Utils
    "normalize_session_id",
    "session_id_match",
]

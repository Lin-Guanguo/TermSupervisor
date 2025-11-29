"""iTerm2 交互模块"""

from termsupervisor.iterm.client import ITerm2Client
from termsupervisor.iterm.layout import get_layout
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
from termsupervisor.iterm.utils import normalize_session_id, session_id_match

__all__ = [
    "ITerm2Client",
    "get_layout",
    "get_name",
    "get_session_name",
    "get_tab_name",
    "get_window_name",
    "set_name",
    "set_session_name",
    "set_tab_name",
    "set_window_name",
    "normalize_session_id",
    "session_id_match",
]

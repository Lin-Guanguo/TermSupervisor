"""iTerm2 交互模块"""

from termsupervisor.iterm.client import ITerm2Client
from termsupervisor.iterm.layout import get_layout, get_name

__all__ = ["ITerm2Client", "get_layout", "get_name"]

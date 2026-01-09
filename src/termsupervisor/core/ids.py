"""Terminal-agnostic ID utilities

Provides functions for normalizing and comparing pane/session IDs across
different terminal emulators (iTerm2, tmux, etc.).

Composite mode uses namespaced IDs to distinguish between adapters:
- iterm2:<session_id>  - iTerm2 pane
- tmux:<pane_id>       - tmux pane (e.g., tmux:%0)
- tmux:<session>:<window_id>  - tmux tab/window
"""

from dataclasses import dataclass
from enum import Enum


class AdapterType(Enum):
    """Terminal adapter type."""

    ITERM2 = "iterm2"
    TMUX = "tmux"


@dataclass
class ParsedId:
    """Parsed namespaced ID."""

    adapter: AdapterType
    native_id: str
    # For tmux windows/tabs, contains session info
    session: str | None = None

    def __str__(self) -> str:
        if self.adapter == AdapterType.TMUX and self.session:
            return f"tmux:{self.session}:{self.native_id}"
        return f"{self.adapter.value}:{self.native_id}"


def make_pane_id(adapter: AdapterType | str, native_id: str) -> str:
    """Create a namespaced pane ID.

    Args:
        adapter: Adapter type ("iterm2", "tmux") or AdapterType enum
        native_id: The native pane ID from the adapter

    Returns:
        Namespaced ID like "iterm2:UUID" or "tmux:%0"
    """
    if isinstance(adapter, AdapterType):
        adapter = adapter.value
    return f"{adapter}:{native_id}"


def make_tab_id(adapter: AdapterType | str, session: str, window_id: str) -> str:
    """Create a namespaced tab ID for tmux windows.

    Args:
        adapter: Adapter type
        session: tmux session ID
        window_id: tmux window ID

    Returns:
        Namespaced ID like "tmux:$0:@1"
    """
    if isinstance(adapter, AdapterType):
        adapter = adapter.value
    return f"{adapter}:{session}:{window_id}"


def parse_id(namespaced_id: str) -> ParsedId | None:
    """Parse a namespaced ID into components.

    Args:
        namespaced_id: ID in format "adapter:native_id" or "adapter:session:native_id"

    Returns:
        ParsedId with adapter and native_id, or None if invalid
    """
    parts = namespaced_id.split(":", 2)
    if len(parts) < 2:
        return None

    try:
        adapter = AdapterType(parts[0])
    except ValueError:
        return None

    if len(parts) == 3:
        # tmux tab: "tmux:session:window_id"
        return ParsedId(adapter=adapter, native_id=parts[2], session=parts[1])
    else:
        # Regular pane: "adapter:native_id"
        return ParsedId(adapter=adapter, native_id=parts[1])


def get_adapter_type(namespaced_id: str) -> AdapterType | None:
    """Extract adapter type from a namespaced ID.

    Args:
        namespaced_id: ID in format "adapter:native_id"

    Returns:
        AdapterType enum, or None if invalid
    """
    parsed = parse_id(namespaced_id)
    return parsed.adapter if parsed else None


def get_native_id(namespaced_id: str) -> str:
    """Extract native ID from a namespaced ID.

    Args:
        namespaced_id: ID in format "adapter:native_id"

    Returns:
        The native ID part, or the original if not namespaced
    """
    parsed = parse_id(namespaced_id)
    return parsed.native_id if parsed else namespaced_id


def is_tmux_id(pane_id: str) -> bool:
    """Check if a pane ID is from tmux adapter."""
    return pane_id.startswith("tmux:")


def is_iterm2_id(pane_id: str) -> bool:
    """Check if a pane ID is from iTerm2 adapter."""
    return pane_id.startswith("iterm2:")


def normalize_id(session_id: str) -> str:
    """Normalize a session/pane ID by extracting the canonical ID part.

    Different terminals use different ID formats:
    - iTerm2 pure UUID: "3EB79F67-40C3-4583-A9E4-AD8224807F34"
    - iTerm2 with prefix ($ITERM_SESSION_ID): "w0t1p1:3EB79F67-40C3-4583-A9E4-AD8224807F34"
    - tmux: "%0", "%1", etc.
    - Namespaced: "iterm2:UUID" or "tmux:%0" (composite mode)

    This function extracts the canonical part after iTerm2 window/tab/pane prefixes,
    but PRESERVES adapter namespace prefixes (iterm2:, tmux:).

    Args:
        session_id: The session/pane ID to normalize

    Returns:
        The normalized ID (preserves namespace prefixes, strips iTerm2 w/t/p prefixes)
    """
    # Preserve namespace prefixes (composite mode)
    if session_id.startswith(("iterm2:", "tmux:")):
        return session_id

    # Strip iTerm2 window/tab/pane prefix (e.g., "w0t1p1:UUID" -> "UUID")
    if ":" in session_id:
        return session_id.split(":")[-1]
    return session_id


def id_match(id1: str, id2: str) -> bool:
    """Compare two session/pane IDs for equality.

    Supports comparing IDs with different formats (e.g., prefixed vs pure UUID).

    Args:
        id1: First ID to compare
        id2: Second ID to compare

    Returns:
        True if the IDs refer to the same pane/session
    """
    return normalize_id(id1) == normalize_id(id2)


def short_id(pane_id: str, length: int = 8) -> str:
    """Get a short display version of a pane ID for logging.

    Extracts the last part after ':' (if present) and truncates to length.

    Args:
        pane_id: The pane ID to shorten
        length: Maximum length (default 8)

    Returns:
        Shortened ID for display in logs
    """
    # Extract UUID part if prefixed (e.g., "w0t1p1:UUID" -> "UUID")
    pure_id = pane_id.split(":")[-1] if ":" in pane_id else pane_id
    return pure_id[:length]

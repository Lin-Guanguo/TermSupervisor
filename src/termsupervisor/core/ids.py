"""Terminal-agnostic ID utilities

Provides functions for normalizing and comparing pane/session IDs across
different terminal emulators (iTerm2, tmux, etc.).
"""


def normalize_id(session_id: str) -> str:
    """Normalize a session/pane ID by extracting the canonical ID part.

    Different terminals use different ID formats:
    - iTerm2 pure UUID: "3EB79F67-40C3-4583-A9E4-AD8224807F34"
    - iTerm2 with prefix ($ITERM_SESSION_ID): "w0t1p1:3EB79F67-40C3-4583-A9E4-AD8224807F34"
    - tmux: "%0", "%1", etc. (future support)

    This function extracts the canonical part after any prefix.

    Args:
        session_id: The session/pane ID to normalize

    Returns:
        The normalized ID (UUID part for iTerm2, or the original ID if no prefix)
    """
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

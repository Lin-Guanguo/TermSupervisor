"""Tmux client for subprocess-based tmux interaction."""

import asyncio
import logging

logger = logging.getLogger(__name__)


class TmuxClient:
    """Client for interacting with tmux via subprocess commands.

    Provides async methods for:
    - Listing windows and panes
    - Capturing pane content
    - Selecting/activating panes
    - Getting pane metadata
    """

    def __init__(self, socket_path: str | None = None):
        """Initialize TmuxClient.

        Args:
            socket_path: Optional tmux socket path. If None, uses default socket.
        """
        self._socket_path = socket_path

    async def run(self, *args: str) -> str | None:
        """Execute a tmux command.

        Args:
            *args: Command arguments (e.g., "list-windows", "-a", "-F", "...")

        Returns:
            Command stdout on success, None on failure.
        """
        cmd = ["tmux"]
        if self._socket_path:
            cmd.extend(["-S", self._socket_path])
        cmd.extend(args)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.debug(f"tmux command failed: {stderr.decode()}")
                return None

            return stdout.decode()

        except Exception as e:
            logger.error(f"tmux subprocess error: {e}")
            return None

    async def list_windows(self) -> list[dict]:
        """List all tmux windows across all sessions.

        Returns:
            List of window dicts with keys:
            - session_id: str
            - window_id: str
            - window_name: str
            - width: int
            - height: int
            - active: bool
        """
        # Format: session_id:window_id:window_name:width:height:active_flag
        fmt = "#{session_id}:#{window_id}:#{window_name}:#{window_width}:#{window_height}:#{window_active}"
        output = await self.run("list-windows", "-a", "-F", fmt)

        if not output:
            return []

        windows = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 6:
                windows.append(
                    {
                        "session_id": parts[0],
                        "window_id": parts[1],
                        "window_name": parts[2],
                        "width": int(parts[3]),
                        "height": int(parts[4]),
                        "active": parts[5] == "1",
                    }
                )

        return windows

    async def list_panes(self) -> list[dict]:
        """List all tmux panes across all sessions.

        Returns:
            List of pane dicts with keys:
            - pane_id: str (e.g., "%0")
            - session_id: str
            - window_id: str
            - pane_name: str
            - x: int (character position)
            - y: int (character position)
            - width: int
            - height: int
            - active: bool
            - path: str
        """
        # Format: pane_id:session_id:window_id:pane_title:pane_left:pane_top:width:height:active:path
        fmt = "#{pane_id}:#{session_id}:#{window_id}:#{pane_title}:#{pane_left}:#{pane_top}:#{pane_width}:#{pane_height}:#{pane_active}:#{pane_current_path}"
        output = await self.run("list-panes", "-a", "-F", fmt)

        if not output:
            return []

        panes = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 10:
                panes.append(
                    {
                        "pane_id": parts[0],
                        "session_id": parts[1],
                        "window_id": parts[2],
                        "pane_name": parts[3],
                        "x": int(parts[4]),
                        "y": int(parts[5]),
                        "width": int(parts[6]),
                        "height": int(parts[7]),
                        "active": parts[8] == "1",
                        "path": parts[9],
                    }
                )

        return panes

    async def capture_pane(self, pane_id: str, lines: int = 30) -> str | None:
        """Capture content from a pane.

        Args:
            pane_id: The pane identifier (e.g., "%0")
            lines: Number of lines to capture (from bottom)

        Returns:
            Pane content string, or None on failure.
        """
        # capture-pane -t pane_id -p -S -lines
        # -p: print to stdout
        # -S: start line (negative = from bottom)
        output = await self.run(
            "capture-pane", "-t", pane_id, "-p", "-S", f"-{lines}"
        )
        return output

    async def select_pane(self, pane_id: str) -> bool:
        """Select/activate a pane.

        Args:
            pane_id: The pane identifier

        Returns:
            True on success, False on failure.
        """
        result = await self.run("select-pane", "-t", pane_id)
        return result is not None

    async def get_active_pane(self) -> str | None:
        """Get the currently active pane ID.

        Returns:
            Pane ID string (e.g., "%2"), or None if tmux not running.
        """
        output = await self.run("display-message", "-p", "#{pane_id}")
        if output:
            return output.strip()
        return None

    async def rename_pane(self, pane_id: str, name: str) -> bool:
        """Rename a pane (set its title).

        Args:
            pane_id: The pane identifier
            name: New name/title for the pane

        Returns:
            True on success, False on failure.
        """
        # select-pane -t pane_id -T title
        result = await self.run("select-pane", "-t", pane_id, "-T", name)
        return result is not None

    async def get_pane_info(self, pane_id: str) -> dict | None:
        """Get detailed info for a specific pane.

        Args:
            pane_id: The pane identifier

        Returns:
            Dict with pane_id, pane_name, path, current_command, or None if not found.
        """
        # Format: pane_id:pane_title:path:current_command
        fmt = "#{pane_id}:#{pane_title}:#{pane_current_path}:#{pane_current_command}"
        output = await self.run("display-message", "-t", pane_id, "-p", fmt)

        if not output:
            return None

        parts = output.strip().split(":")
        if len(parts) >= 4:
            return {
                "pane_id": parts[0],
                "pane_name": parts[1],
                "path": parts[2],
                "current_command": parts[3],
            }

        return None

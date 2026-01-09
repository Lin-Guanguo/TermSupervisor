"""Tmux client for subprocess-based tmux interaction."""

import asyncio
import logging

logger = logging.getLogger(__name__)

# Use tab as delimiter to avoid conflicts with colons in data (paths, names)
_FIELD_SEP = "\t"

# Default number of lines to capture from pane
DEFAULT_CAPTURE_LINES = 30


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
                logger.warning(f"tmux command failed: {' '.join(cmd)}: {stderr.decode()}")
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
        # Use tab delimiter to avoid conflicts with colons in window names
        fmt = _FIELD_SEP.join([
            "#{session_id}", "#{window_id}", "#{window_name}",
            "#{window_width}", "#{window_height}", "#{window_active}"
        ])
        output = await self.run("list-windows", "-a", "-F", fmt)

        if not output:
            return []

        windows = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split(_FIELD_SEP)
            if len(parts) >= 6:
                try:
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
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse window line: {line!r}: {e}")

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
            - pane_pid: int (optional)
            - pane_tty: str (optional)
        """
        # Use tab delimiter to avoid conflicts with colons in paths/titles
        fmt = _FIELD_SEP.join([
            "#{pane_id}", "#{session_id}", "#{window_id}", "#{pane_title}",
            "#{pane_left}", "#{pane_top}", "#{pane_width}", "#{pane_height}",
            "#{pane_active}", "#{pane_current_path}", "#{pane_pid}", "#{pane_tty}"
        ])
        output = await self.run("list-panes", "-a", "-F", fmt)

        if not output:
            return []

        panes = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split(_FIELD_SEP)
            if len(parts) >= 10:
                try:
                    pane_data = {
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
                    # Optional fields for JobMetadata
                    if len(parts) >= 11 and parts[10]:
                        pane_data["pane_pid"] = int(parts[10])
                    if len(parts) >= 12 and parts[11]:
                        pane_data["pane_tty"] = parts[11]
                    panes.append(pane_data)
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse pane line: {line!r}: {e}")

        return panes

    async def capture_pane(
        self, pane_id: str, lines: int = DEFAULT_CAPTURE_LINES, escape: bool = False
    ) -> str | None:
        """Capture content from a pane.

        Args:
            pane_id: The pane identifier (e.g., "%0")
            lines: Number of lines to capture (from bottom). Default is 30.
            escape: If True, include ANSI escape sequences for colors/styles.

        Returns:
            Pane content string, or None on failure.
        """
        # capture-pane -t pane_id -p -S -lines
        # -p: print to stdout
        # -S: start line (negative = from bottom)
        # -e: include escape sequences (ANSI colors)
        args = ["capture-pane", "-t", pane_id, "-p", "-S", f"-{lines}"]
        if escape:
            args.append("-e")
        output = await self.run(*args)
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
            Dict with pane_id, pane_name, path, current_command, pane_pid, pane_tty,
            or None if not found.
        """
        # Use tab delimiter to avoid conflicts with colons in paths/commands
        fmt = _FIELD_SEP.join([
            "#{pane_id}", "#{pane_title}", "#{pane_current_path}",
            "#{pane_current_command}", "#{pane_pid}", "#{pane_tty}"
        ])
        output = await self.run("display-message", "-t", pane_id, "-p", fmt)

        if not output:
            return None

        parts = output.strip().split(_FIELD_SEP)
        if len(parts) >= 4:
            result = {
                "pane_id": parts[0],
                "pane_name": parts[1],
                "path": parts[2],
                "current_command": parts[3],
            }
            # Optional fields
            if len(parts) >= 5 and parts[4]:
                try:
                    result["pane_pid"] = int(parts[4])
                except ValueError:
                    pass
            if len(parts) >= 6 and parts[5]:
                result["pane_tty"] = parts[5]
            return result

        return None

    async def list_clients(self) -> list[dict]:
        """List all tmux clients (attached terminals).

        Used for composite mode to detect which iTerm2 panes are running tmux.

        Returns:
            List of client dicts with keys:
            - client_tty: str (e.g., "/dev/ttys001")
            - client_session: str (session name)
            - client_width: int
            - client_height: int
        """
        fmt = _FIELD_SEP.join([
            "#{client_tty}", "#{client_session}",
            "#{client_width}", "#{client_height}"
        ])
        output = await self.run("list-clients", "-F", fmt)

        if not output:
            return []

        clients = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split(_FIELD_SEP)
            if len(parts) >= 4:
                try:
                    clients.append({
                        "client_tty": parts[0],
                        "client_session": parts[1],
                        "client_width": int(parts[2]),
                        "client_height": int(parts[3]),
                    })
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse client line: {line!r}: {e}")

        return clients

    async def select_window(self, target: str) -> bool:
        """Select/activate a tmux window.

        Args:
            target: Window target (e.g., "session:window" or "@1")

        Returns:
            True on success, False on failure.
        """
        result = await self.run("select-window", "-t", target)
        return result is not None

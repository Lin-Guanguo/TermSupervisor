"""内容轮询器

从终端适配器获取布局和 pane 内容。
"""

from typing import TYPE_CHECKING

from termsupervisor.adapters import JobMetadata, TerminalAdapter
from termsupervisor.adapters.iterm2.models import LayoutData

if TYPE_CHECKING:
    pass


class ContentPoller:
    """内容轮询器

    负责：
    - 获取终端布局
    - 获取 pane 内容
    - 获取 job metadata

    Uses TerminalAdapter protocol for terminal-agnostic operation.
    """

    def __init__(
        self,
        adapter: TerminalAdapter,
        exclude_names: list[str] | None = None,
    ):
        """Initialize content poller.

        Args:
            adapter: Terminal adapter implementing TerminalAdapter protocol
            exclude_names: Tab/pane names to exclude (handled by adapter)
        """
        self._adapter = adapter
        self._exclude_names = exclude_names or []

    async def poll_layout(self) -> LayoutData | None:
        """获取当前布局

        Returns:
            布局数据，如果无法获取返回 None
        """
        return await self._adapter.get_layout()

    async def get_pane_content(self, pane_id: str) -> str | None:
        """获取 pane 内容

        Args:
            pane_id: pane ID

        Returns:
            pane 内容，如果无法获取返回 None
        """
        return await self._adapter.get_pane_content(pane_id)

    async def get_job_metadata(self, pane_id: str) -> JobMetadata | None:
        """获取 pane 的 job metadata

        Args:
            pane_id: pane ID

        Returns:
            job metadata，如果无法获取返回 None
        """
        return await self._adapter.get_job_metadata(pane_id)

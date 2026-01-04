"""内容轮询器

从终端适配器获取布局和 pane 内容。
"""

from typing import TYPE_CHECKING

from termsupervisor.adapters.iterm2 import get_layout
from termsupervisor.adapters.iterm2.models import LayoutData

if TYPE_CHECKING:
    from termsupervisor.adapters.iterm2 import ITerm2Client
    from termsupervisor.adapters.iterm2.client import JobMetadata


class ContentPoller:
    """内容轮询器

    负责：
    - 获取 iTerm2 布局
    - 获取 pane 内容
    - 获取 job metadata
    """

    def __init__(
        self,
        iterm_client: "ITerm2Client",
        exclude_names: list[str] | None = None,
    ):
        self._client = iterm_client
        self._exclude_names = exclude_names or []

    async def poll_layout(self) -> LayoutData | None:
        """获取当前布局

        Returns:
            布局数据，如果无法获取返回 None
        """
        app = await self._client.get_app()
        if app is None:
            return None
        return await get_layout(app, self._exclude_names)

    async def get_pane_content(self, pane_id: str) -> str | None:
        """获取 pane 内容

        Args:
            pane_id: pane ID

        Returns:
            pane 内容，如果无法获取返回 None
        """
        app = await self._client.get_app()
        if app is None:
            return None

        session = app.get_session_by_id(pane_id)
        if session is None:
            return None

        return await self._client.get_session_content(session)

    async def get_job_metadata(self, pane_id: str) -> "JobMetadata | None":
        """获取 pane 的 job metadata

        Args:
            pane_id: pane ID

        Returns:
            job metadata，如果无法获取返回 None
        """
        app = await self._client.get_app()
        if app is None:
            return None

        session = app.get_session_by_id(pane_id)
        if session is None:
            return None

        return await self._client.get_session_job_metadata(session)

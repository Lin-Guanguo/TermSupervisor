"""ITerm2Adapter 测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from termsupervisor.adapters.base import TerminalAdapter
from termsupervisor.adapters.iterm2.models import LayoutData
from termsupervisor.adapters.iterm2.adapter import ITerm2Adapter


class TestITerm2AdapterInterface:
    """ITerm2Adapter 接口实现测试"""

    def test_implements_terminal_adapter(self):
        """ITerm2Adapter 实现 TerminalAdapter 接口"""
        assert issubclass(ITerm2Adapter, TerminalAdapter)

    def test_name_property(self):
        """name 属性返回 'iterm2'"""
        adapter = ITerm2Adapter.__new__(ITerm2Adapter)
        adapter._connection = None
        adapter._client = None
        adapter._app = None
        assert adapter.name == "iterm2"


class TestITerm2AdapterWithMock:
    """使用 mock 测试 ITerm2Adapter"""

    @pytest.fixture
    def mock_connection(self):
        """创建 mock connection"""
        return MagicMock()

    @pytest.fixture
    def adapter(self, mock_connection):
        """创建 adapter"""
        return ITerm2Adapter(mock_connection)

    def test_init(self, adapter, mock_connection):
        """初始化创建 client"""
        assert adapter._connection == mock_connection
        assert adapter._client is not None

    async def test_connect_success(self, adapter):
        """连接成功"""
        mock_app = MagicMock()
        with patch.object(adapter._client, "get_app", new_callable=AsyncMock) as mock_get_app:
            mock_get_app.return_value = mock_app
            result = await adapter.connect()
            assert result is True
            assert adapter._app == mock_app

    async def test_connect_failure(self, adapter):
        """连接失败"""
        with patch.object(adapter._client, "get_app", new_callable=AsyncMock) as mock_get_app:
            mock_get_app.return_value = None
            result = await adapter.connect()
            assert result is False
            assert adapter._app is None

    async def test_disconnect(self, adapter):
        """断开连接"""
        adapter._app = MagicMock()
        await adapter.disconnect()
        assert adapter._app is None

    async def test_get_layout_not_connected(self, adapter):
        """未连接时返回空布局"""
        adapter._app = None
        layout = await adapter.get_layout()
        assert len(layout.windows) == 0

    async def test_activate_pane(self, adapter):
        """激活 pane"""
        with patch.object(adapter._client, "activate_session", new_callable=AsyncMock) as mock_activate:
            mock_activate.return_value = True
            result = await adapter.activate_pane("test-pane")
            assert result is True
            mock_activate.assert_called_once_with("test-pane")

    async def test_rename_pane(self, adapter):
        """重命名 pane"""
        with patch.object(adapter._client, "rename_session", new_callable=AsyncMock) as mock_rename:
            mock_rename.return_value = True
            result = await adapter.rename_pane("test-pane", "new-name")
            assert result is True
            mock_rename.assert_called_once_with("test-pane", "new-name")

    async def test_rename_tab(self, adapter):
        """重命名 tab"""
        with patch.object(adapter._client, "rename_tab", new_callable=AsyncMock) as mock_rename:
            mock_rename.return_value = True
            result = await adapter.rename_tab("test-tab", "new-name")
            assert result is True
            mock_rename.assert_called_once_with("test-tab", "new-name")

    async def test_rename_window(self, adapter):
        """重命名 window"""
        with patch.object(adapter._client, "rename_window", new_callable=AsyncMock) as mock_rename:
            mock_rename.return_value = True
            result = await adapter.rename_window("test-window", "new-name")
            assert result is True
            mock_rename.assert_called_once_with("test-window", "new-name")

    async def test_create_tab(self, adapter):
        """创建 tab"""
        with patch.object(adapter._client, "create_tab", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = True
            result = await adapter.create_tab("test-window", "2x2")
            assert result is True
            mock_create.assert_called_once_with("test-window", "2x2")

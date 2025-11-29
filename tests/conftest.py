"""Pytest 配置"""

import pytest


@pytest.fixture
def anyio_backend():
    """指定 anyio 只使用 asyncio backend"""
    return "asyncio"

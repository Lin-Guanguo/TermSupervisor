"""持久化模块

提供状态持久化功能：
- 原子写入（temp + rename）
- checksum 校验（sha256）
- version 版本控制
- 损坏文件跳过告警
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..telemetry import get_logger, metrics
from ..config import PERSIST_DIR, PERSIST_FILE, PERSIST_VERSION

logger = get_logger(__name__)


def _calculate_checksum(data: bytes) -> str:
    """计算 SHA256 checksum"""
    return hashlib.sha256(data).hexdigest()


def _ensure_dir(path: Path) -> None:
    """确保目录存在"""
    path.mkdir(parents=True, exist_ok=True)


def save(
    machines: dict[str, dict],
    panes: dict[str, dict],
    path: Path | None = None,
    version: int = PERSIST_VERSION,
) -> bool:
    """保存状态到文件

    使用 temp + rename 原子写入，包含 checksum 校验。

    Args:
        machines: 状态机数据 {pane_id: machine.to_dict()}
        panes: Pane 数据 {pane_id: pane.to_dict()}
        path: 保存路径，默认使用配置
        version: 版本号

    Returns:
        是否成功
    """
    path = path or PERSIST_FILE

    try:
        # 构建数据
        import time
        data = {
            "version": version,
            "saved_at": time.time(),
            "machines": machines,
            "panes": panes,
        }

        # 序列化
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        checksum = _calculate_checksum(json_bytes)

        # 添加 checksum
        data["checksum"] = checksum
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

        # 确保目录存在
        _ensure_dir(path.parent)

        # 原子写入：先写临时文件，再 rename
        fd, temp_path = tempfile.mkstemp(
            prefix="termsupervisor_state_",
            suffix=".tmp",
            dir=path.parent,
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(json_bytes)
            os.rename(temp_path, path)
        except Exception:
            # 清理临时文件
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

        logger.info(f"[Persist] Saved {len(machines)} machines, {len(panes)} panes")
        return True

    except Exception as e:
        logger.error(f"[Persist] Save failed: {e}")
        metrics.inc("persist.error", {"op": "save"})
        return False


def load(
    path: Path | None = None,
    version: int = PERSIST_VERSION,
) -> tuple[dict[str, dict], dict[str, dict]] | None:
    """加载状态文件

    校验 version 和 checksum，失败时返回 None。

    Args:
        path: 文件路径，默认使用配置
        version: 期望的版本号

    Returns:
        (machines, panes) 元组，失败返回 None
    """
    path = path or PERSIST_FILE

    if not path.exists():
        logger.debug(f"[Persist] File not found: {path}")
        return None

    try:
        # 读取文件
        with open(path, "rb") as f:
            content = f.read()

        data = json.loads(content.decode("utf-8"))

        # 检查版本
        file_version = data.get("version", 1)
        if file_version != version:
            logger.warning(
                f"[Persist] Version mismatch: file={file_version}, expected={version}"
            )
            metrics.inc("persist.error", {"op": "load", "reason": "version"})
            return None

        # 检查 checksum
        stored_checksum = data.pop("checksum", None)
        if stored_checksum:
            # 重新计算
            json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            calculated = _calculate_checksum(json_bytes)
            if calculated != stored_checksum:
                logger.warning(f"[Persist] Checksum mismatch")
                metrics.inc("persist.error", {"op": "load", "reason": "checksum"})
                return None

        machines = data.get("machines", {})
        panes = data.get("panes", {})

        logger.info(f"[Persist] Loaded {len(machines)} machines, {len(panes)} panes")
        return machines, panes

    except json.JSONDecodeError as e:
        logger.warning(f"[Persist] Invalid JSON: {e}")
        metrics.inc("persist.error", {"op": "load", "reason": "json"})
        return None

    except Exception as e:
        logger.error(f"[Persist] Load failed: {e}")
        metrics.inc("persist.error", {"op": "load", "reason": "unknown"})
        return None


def delete(path: Path | None = None) -> bool:
    """删除状态文件

    Args:
        path: 文件路径

    Returns:
        是否成功
    """
    path = path or PERSIST_FILE

    try:
        if path.exists():
            os.unlink(path)
            logger.info(f"[Persist] Deleted: {path}")
        return True
    except Exception as e:
        logger.error(f"[Persist] Delete failed: {e}")
        return False

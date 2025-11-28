"""LLM 分析器：使用 OpenRouter API 分析 pane 状态"""

import os
import json
import logging
import httpx
from datetime import datetime
from typing import TYPE_CHECKING

from .base import StatusAnalyzer, TaskStatus
from .cleaner import ChangeCleaner
from .. import config

if TYPE_CHECKING:
    from ..models import PaneHistory

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """分析这个终端 pane 的当前状态。

屏幕内容（最后 {n_lines} 行）:
```
{content}
```

最近变化摘要:
{changes_summary}

请判断状态并返回 JSON（不要输出其他内容）:
{{"status": "idle|running|thinking|waiting_approval|completed|failed|interrupted", "reason": "一句话理由"}}

状态说明:
- idle: 空闲，显示 shell prompt，等待用户输入
- running: 命令正在执行，有输出
- thinking: AI 工具在思考（如 Claude Code 显示旋转符号 ✽✳✶）
- waiting_approval: 等待用户确认（如 Y/n 提示、权限确认）
- completed: 任务成功完成（出现 ✓ ✔ Done Success 等）
- failed: 任务出错（出现 Error Failed Exception 等）
- interrupted: 用户中断（Ctrl+C）
"""


class LLMAnalyzer(StatusAnalyzer):
    """LLM 分析器：使用 OpenRouter API"""

    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.cleaner = ChangeCleaner(
            min_changed_lines=config.CLEANER_MIN_CHANGED_LINES,
            similarity_threshold=config.CLEANER_SIMILARITY_THRESHOLD,
            debounce_seconds=config.CLEANER_DEBOUNCE_SECONDS,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=config.LLM_TIMEOUT)
        return self._client

    async def analyze(self, pane: "PaneHistory") -> TaskStatus:
        """分析 pane 状态"""
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not set, returning UNKNOWN")
            return TaskStatus.UNKNOWN

        if not pane.changes:
            return TaskStatus.UNKNOWN

        last_change = pane.changes[-1]
        content = '\n'.join(last_change.last_n_lines)
        changes_summary = self._build_changes_summary(pane)

        try:
            result = await self._call_llm(content, changes_summary)
            status_str = result.get("status", "unknown")

            # 验证状态值
            try:
                status = TaskStatus(status_str)
            except ValueError:
                logger.warning(f"Invalid status from LLM: {status_str}")
                status = TaskStatus.UNKNOWN

            # 更新 pane 状态
            pane.last_analysis = datetime.now()
            pane.current_status = status
            pane.status_reason = result.get("reason", "")

            # 如果不是 thinking 状态，重置 thinking 标记
            if status != TaskStatus.THINKING:
                pane.is_thinking = False
                pane.thinking_since = None

            logger.debug(f"Pane {pane.session_id} status: {status.value} - {pane.status_reason}")
            return status

        except httpx.TimeoutException:
            logger.warning(f"LLM timeout for pane {pane.session_id}")
            return pane.current_status or TaskStatus.UNKNOWN
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM HTTP error: {e.response.status_code}")
            return pane.current_status or TaskStatus.UNKNOWN
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return pane.current_status or TaskStatus.UNKNOWN
        except Exception as e:
            logger.error(f"LLM analysis error: {e}")
            return pane.current_status or TaskStatus.UNKNOWN

    def should_analyze(self, pane: "PaneHistory") -> bool:
        """判断是否需要分析（委托给 ChangeCleaner）"""
        should, reason = self.cleaner.should_analyze(pane)
        if not should:
            logger.debug(f"Skip analysis for pane {pane.session_id}: {reason}")
        return should

    def _build_changes_summary(self, pane: "PaneHistory") -> str:
        """构建最近变化摘要"""
        if len(pane.changes) <= 1:
            return "无历史变化"

        summaries = []
        for i, change in enumerate(list(pane.changes)[-3:]):
            time_str = change.timestamp.strftime('%H:%M:%S')
            summary = change.diff_summary[:50]
            summaries.append(f"{i+1}. [{time_str}] {summary}")
        return '\n'.join(summaries)

    async def _call_llm(self, content: str, changes_summary: str) -> dict:
        """调用 OpenRouter API"""
        client = await self._get_client()

        prompt = ANALYSIS_PROMPT.format(
            n_lines=config.SCREEN_LAST_N_LINES,
            content=content,
            changes_summary=changes_summary,
        )

        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/termsupervisor",
                "X-Title": "TermSupervisor",
            },
            json={
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": config.LLM_MAX_TOKENS,
                "temperature": 0.1,
            },
        )
        response.raise_for_status()

        text = response.json()["choices"][0]["message"]["content"]

        # 解析 JSON（处理可能的 markdown 代码块）
        text = text.strip()
        if text.startswith("```"):
            # 移除 ```json 或 ``` 开头
            text = text.split('\n', 1)[1] if '\n' in text else text[3:]
            text = text.rsplit('```', 1)[0]
        text = text.strip()

        return json.loads(text)

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

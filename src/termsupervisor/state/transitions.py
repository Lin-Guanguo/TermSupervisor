"""状态流转规则表

规则表：
| # | from_status | from_source | signal | to_status | to_source | 描述 |
|---|-------------|-------------|--------|-----------|-----------|------|
| S1 | * | * | shell.command_start | RUNNING | shell | 执行: {command:30} |
| S2 | RUNNING | shell | shell.command_end(exit=0) | DONE | shell |
| S3 | RUNNING | shell | shell.command_end(exit≠0) | FAILED | shell |
| C1 | * | * | claude-code.SessionStart | RUNNING | claude-code |
| C2 | * | * | claude-code.PreToolUse | RUNNING | claude-code |
| C3 | RUNNING | claude-code | claude-code.Stop | DONE | claude-code |
| C4 | * | * | claude-code.Notification:permission_prompt | WAITING | claude-code |
| C5 | * | * | claude-code.Notification:idle_prompt | IDLE | claude-code |
| C6 | * | * | claude-code.SessionEnd | IDLE | claude-code |
| U1 | WAITING | * | iterm.focus / frontend.click_pane | IDLE | user |
| U2 | DONE|FAILED | * | iterm.focus / frontend.click_pane | IDLE | user |
"""

from .predicates import (
    require_exit_code,
    require_exit_code_nonzero,
)
from .types import TaskStatus, TransitionRule


# === Shell 规则 ===

S1_SHELL_COMMAND_START = TransitionRule(
    from_status=None,  # 任意状态
    from_source=None,  # 任意来源
    signal_pattern="shell.command_start",
    to_status=TaskStatus.RUNNING,
    to_source="shell",
    description_template="执行: {command:30}",
    reset_started_at=True,
)

S2_SHELL_COMMAND_END_SUCCESS = TransitionRule(
    from_status={TaskStatus.RUNNING},
    from_source="shell",  # 只处理 shell 发起的 RUNNING
    signal_pattern="shell.command_end",
    to_status=TaskStatus.DONE,
    to_source="shell",
    description_template="命令完成",
    reset_started_at=False,  # 保留 started_at 用于计算运行时长
    predicates=[require_exit_code(0)],
)

S3_SHELL_COMMAND_END_FAILED = TransitionRule(
    from_status={TaskStatus.RUNNING},
    from_source="shell",
    signal_pattern="shell.command_end",
    to_status=TaskStatus.FAILED,
    to_source="shell",
    description_template="失败 (exit={exit_code})",
    reset_started_at=False,
    predicates=[require_exit_code_nonzero()],
)


# === Claude Code 规则 ===

C1_CLAUDE_SESSION_START = TransitionRule(
    from_status=None,
    from_source=None,
    signal_pattern="claude-code.SessionStart",
    to_status=TaskStatus.RUNNING,
    to_source="claude-code",
    description_template="会话开始",
    reset_started_at=True,
)

C2_CLAUDE_PRE_TOOL_USE = TransitionRule(
    from_status=None,
    from_source=None,
    signal_pattern="claude-code.PreToolUse",
    to_status=TaskStatus.RUNNING,
    to_source="claude-code",
    description_template="工具: {tool_name:30}",
    reset_started_at=True,
    preserve_started_at_if_same_source=True,  # 同源时保持 started_at
)

C3_CLAUDE_STOP = TransitionRule(
    from_status={TaskStatus.RUNNING},
    from_source="claude-code",
    signal_pattern="claude-code.Stop",
    to_status=TaskStatus.DONE,
    to_source="claude-code",
    description_template="已完成回复",
    reset_started_at=False,
)

C4_CLAUDE_PERMISSION_PROMPT = TransitionRule(
    from_status=None,
    from_source=None,
    signal_pattern="claude-code.Notification:permission_prompt",
    to_status=TaskStatus.WAITING_APPROVAL,
    to_source="claude-code",
    description_template="需要权限确认",
    reset_started_at=False,
)

C5_CLAUDE_IDLE_PROMPT = TransitionRule(
    from_status=None,
    from_source=None,
    signal_pattern="claude-code.Notification:idle_prompt",
    to_status=TaskStatus.IDLE,
    to_source="claude-code",
    description_template="",
    reset_started_at=True,
)

C6_CLAUDE_SESSION_END = TransitionRule(
    from_status=None,
    from_source=None,
    signal_pattern="claude-code.SessionEnd",
    to_status=TaskStatus.IDLE,
    to_source="claude-code",
    description_template="",
    reset_started_at=True,
)


# === User 规则（iterm/frontend）===

U1_USER_CLEAR_WAITING = TransitionRule(
    from_status={TaskStatus.WAITING_APPROVAL},
    from_source=None,  # 任意来源
    signal_pattern="iterm.focus",
    to_status=TaskStatus.IDLE,
    to_source="user",
    description_template="",
    reset_started_at=True,
)

U1_USER_CLEAR_WAITING_CLICK = TransitionRule(
    from_status={TaskStatus.WAITING_APPROVAL},
    from_source=None,
    signal_pattern="frontend.click_pane",
    to_status=TaskStatus.IDLE,
    to_source="user",
    description_template="",
    reset_started_at=True,
)

U2_USER_CLEAR_DONE_FAILED = TransitionRule(
    from_status={TaskStatus.DONE, TaskStatus.FAILED},
    from_source=None,
    signal_pattern="iterm.focus",
    to_status=TaskStatus.IDLE,
    to_source="user",
    description_template="",
    reset_started_at=True,
)

U2_USER_CLEAR_DONE_FAILED_CLICK = TransitionRule(
    from_status={TaskStatus.DONE, TaskStatus.FAILED},
    from_source=None,
    signal_pattern="frontend.click_pane",
    to_status=TaskStatus.IDLE,
    to_source="user",
    description_template="",
    reset_started_at=True,
)


# === 规则表 ===
# 按优先级排序：先匹配的规则优先

TRANSITION_RULES: list[TransitionRule] = [
    # Shell 规则
    S1_SHELL_COMMAND_START,
    S2_SHELL_COMMAND_END_SUCCESS,
    S3_SHELL_COMMAND_END_FAILED,
    # Claude Code 规则
    C1_CLAUDE_SESSION_START,
    C2_CLAUDE_PRE_TOOL_USE,
    C3_CLAUDE_STOP,
    C4_CLAUDE_PERMISSION_PROMPT,
    C5_CLAUDE_IDLE_PROMPT,
    C6_CLAUDE_SESSION_END,
    # User 规则
    U1_USER_CLEAR_WAITING,
    U1_USER_CLEAR_WAITING_CLICK,
    U2_USER_CLEAR_DONE_FAILED,
    U2_USER_CLEAR_DONE_FAILED_CLICK,
]


def find_matching_rules(
    signal: str,
    current_status: TaskStatus,
    current_source: str,
) -> list[TransitionRule]:
    """查找所有可能匹配的规则（不检查谓词）

    返回所有基本条件匹配的规则，由调用者检查谓词。

    Args:
        signal: 事件信号
        current_status: 当前状态
        current_source: 当前来源

    Returns:
        匹配的规则列表
    """
    result = []
    for rule in TRANSITION_RULES:
        if not rule.matches_signal(signal):
            continue
        if not rule.matches_from_status(current_status):
            continue
        if not rule.matches_from_source(current_source, signal.split(".")[0]):
            continue
        result.append(rule)
    return result

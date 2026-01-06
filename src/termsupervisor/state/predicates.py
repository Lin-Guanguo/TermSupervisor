"""内置谓词库

提供 TransitionRule 可用的谓词函数。
谓词函数签名: (event: HookEvent, snapshot: StateSnapshot) -> bool

可用谓词：
- require_exit_code(code): 检查 exit_code 是否匹配
- require_exit_code_nonzero(): 检查 exit_code 是否非零
"""

from .types import HookEvent, Predicate, StateSnapshot


def require_exit_code(code: int) -> Predicate:
    """创建检查 exit_code 的谓词

    Args:
        code: 期望的 exit_code

    Returns:
        谓词函数
    """

    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        return event.data.get("exit_code") == code

    return predicate


def require_exit_code_nonzero() -> Predicate:
    """创建检查 exit_code 非零的谓词

    Returns:
        谓词函数
    """

    def predicate(event: HookEvent, snapshot: StateSnapshot) -> bool:
        exit_code = event.data.get("exit_code")
        return exit_code is not None and exit_code != 0

    return predicate

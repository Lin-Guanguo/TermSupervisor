"""iTerm2 工具函数"""


def normalize_session_id(session_id: str) -> str:
    """标准化 session_id，提取纯 UUID 部分

    iTerm2 的 session_id 有两种格式：
    - 纯 UUID: "3EB79F67-40C3-4583-A9E4-AD8224807F34"
    - 带前缀: "w0t1p1:3EB79F67-40C3-4583-A9E4-AD8224807F34" ($ITERM_SESSION_ID 环境变量)

    此函数统一返回纯 UUID 格式，方便比较。
    """
    if ":" in session_id:
        return session_id.split(":")[-1]
    return session_id


def session_id_match(id1: str, id2: str) -> bool:
    """比较两个 session_id 是否指向同一个 session

    支持混合格式比较（带前缀 vs 纯 UUID）。
    """
    return normalize_session_id(id1) == normalize_session_id(id2)

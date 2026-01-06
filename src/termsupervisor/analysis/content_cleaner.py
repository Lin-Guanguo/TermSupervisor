"""终端内容清洗器 - 白名单过滤（仅保留文字）"""

import hashlib
import re
from difflib import unified_diff


class ContentCleaner:
    """终端内容清洗器

    使用 Unicode 白名单过滤，只保留文字（字母、数字、中日韩文字）。
    过滤所有符号、标点、空格、Spinner、进度条、Emoji、ANSI 转义序列。

    设计目的：
    - 稳定 diff 对比，避免动态内容（进度条、Spinner）导致的频繁误判
    - 按行 diff，只对比有意义的文字内容
    """

    # Unicode 白名单范围 - 只保留文字
    ALLOWED_RANGES = [
        # === 英文字母和数字 ===
        (0x0030, 0x0039),  # 0-9
        (0x0041, 0x005A),  # A-Z
        (0x0061, 0x007A),  # a-z
        # === 拉丁扩展（带重音的字母）===
        (0x00C0, 0x00FF),  # Latin-1 补充 (À-ÿ，不含标点)
        (0x0100, 0x017F),  # Latin Extended-A
        (0x0180, 0x024F),  # Latin Extended-B
        # === 中文 ===
        (0x4E00, 0x9FFF),  # CJK 统一汉字 (基本区)
        (0x3400, 0x4DBF),  # CJK 统一汉字扩展 A
        # === 日语 ===
        (0x3040, 0x309F),  # 平假名
        (0x30A0, 0x30FF),  # 片假名
        # === 韩语 ===
        (0xAC00, 0xD7AF),  # 韩语音节块
        (0x1100, 0x11FF),  # 韩语字母 (Jamo)
    ]

    # 编译 ANSI 转义序列正则
    _ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

    @classmethod
    def is_allowed_char(cls, char: str) -> bool:
        """判断字符是否在白名单范围内"""
        code = ord(char)
        for start, end in cls.ALLOWED_RANGES:
            if start <= code <= end:
                return True
        return False

    @classmethod
    def clean_line(cls, line: str) -> str:
        """清洗单行：移除 ANSI、只保留文字

        Args:
            line: 原始行内容

        Returns:
            清洗后的行（只包含文字）
        """
        # 1. 移除 ANSI 转义序列
        line = cls._ANSI_PATTERN.sub("", line)
        # 2. 白名单过滤（只保留文字）
        return "".join(c for c in line if cls.is_allowed_char(c))

    @classmethod
    def clean_content(cls, content: str) -> list[str]:
        """清洗整个内容，返回非空行列表

        Args:
            content: 原始终端内容

        Returns:
            清洗后的非空行列表
        """
        lines = []
        for line in content.split("\n"):
            cleaned = cls.clean_line(line)
            if cleaned:  # 跳过空行
                lines.append(cleaned)
        return lines

    @classmethod
    def clean_content_str(cls, content: str) -> str:
        """清洗整个内容，返回换行符连接的字符串

        Args:
            content: 原始终端内容

        Returns:
            清洗后的内容字符串（非空行用换行符连接）
        """
        return "\n".join(cls.clean_content(content))

    @classmethod
    def diff_lines(cls, old: str, new: str) -> tuple[int, list[str]]:
        """对比清洗后内容，按行 diff

        Args:
            old: 旧内容（已清洗或原始内容）
            new: 新内容（已清洗或原始内容）

        Returns:
            (changed_lines, diff_details)
            - changed_lines: 变化行数（增加 + 删除）
            - diff_details: unified diff 行列表
        """
        # Split content into lines (expects pre-cleaned content)
        old_lines = old.split("\n")
        new_lines = new.split("\n")

        # 过滤空字符串
        old_lines = [line for line in old_lines if line]
        new_lines = [line for line in new_lines if line]

        # 生成 unified diff
        diff = list(unified_diff(old_lines, new_lines, lineterm=""))

        # 统计变化行数（以 + 或 - 开头，但不是 +++ 或 ---）
        changed_lines = 0
        diff_details = []
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+") or line.startswith("-"):
                changed_lines += 1
                diff_details.append(line)

        return changed_lines, diff_details

    @classmethod
    def content_hash(cls, content: str) -> str:
        """计算清洗后内容的 hash

        Args:
            content: 原始或清洗后的内容

        Returns:
            MD5 hash 字符串
        """
        cleaned = cls.clean_content_str(content)
        return hashlib.md5(cleaned.encode("utf-8")).hexdigest()

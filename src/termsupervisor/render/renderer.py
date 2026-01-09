"""Terminal content to SVG renderer using Rich library."""

import logging
import re

import iterm2

logger = logging.getLogger(__name__)
from rich.console import Console
from rich.style import Style
from rich.text import Text

# XML 1.0 允许的字符范围
# #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
_INVALID_XML_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff\ufffe\uffff]"
)


def _sanitize_for_xml(text: str) -> str:
    """移除 XML 中不允许的字符。"""
    return _INVALID_XML_CHARS_RE.sub("", text)


# ANSI 16 色映射到 Rich 颜色名
ANSI_TO_RICH = {
    0: "black",
    1: "red",
    2: "green",
    3: "yellow",
    4: "blue",
    5: "magenta",
    6: "cyan",
    7: "white",
    8: "bright_black",
    9: "bright_red",
    10: "bright_green",
    11: "bright_yellow",
    12: "bright_blue",
    13: "bright_magenta",
    14: "bright_cyan",
    15: "bright_white",
}


def _color_to_rich(color, default: str = "default") -> str:
    """将 iTerm2 颜色转换为 Rich 颜色格式。"""
    if color is None:
        return default

    # RGB 颜色
    try:
        if hasattr(color, "rgb") and color.rgb is not None:
            return f"rgb({color.rgb.red},{color.rgb.green},{color.rgb.blue})"
    except Exception as e:
        logger.debug(f"Failed to convert RGB color: {e}")

    # 标准 ANSI 颜色
    try:
        if hasattr(color, "standard") and color.standard is not None:
            idx = color.standard
            if idx < 16:
                return ANSI_TO_RICH.get(idx, default)
            elif idx < 232:
                # 216 色立方
                idx -= 16
                r = (idx // 36) * 51
                g = ((idx // 6) % 6) * 51
                b = (idx % 6) * 51
                return f"rgb({r},{g},{b})"
            else:
                # 灰度
                gray = (idx - 232) * 10 + 8
                return f"rgb({gray},{gray},{gray})"
    except Exception as e:
        logger.debug(f"Failed to convert ANSI color: {e}")

    return default


def _is_wide_char(char: str) -> bool:
    """判断是否为宽字符（占 2 个 cell）。"""
    if not char:
        return False
    code = ord(char[0])
    return (
        0x4E00 <= code <= 0x9FFF  # CJK 统一汉字
        or 0x3400 <= code <= 0x4DBF  # CJK 扩展 A
        or 0xF900 <= code <= 0xFAFF  # CJK 兼容汉字
        or 0x3000 <= code <= 0x303F  # CJK 符号和标点
        or 0xFF00 <= code <= 0xFFEF  # 全角字符
        or 0x2E80 <= code <= 0x2EFF  # CJK 部首补充
        or 0x31C0 <= code <= 0x31EF  # CJK 笔画
        or 0x2FF0 <= code <= 0x2FFF  # 表意文字描述符
    )


class TerminalRenderer:
    """终端内容渲染器，将 iTerm2 session 内容转换为 SVG。"""

    def __init__(self, font_size: int = 14):
        """
        初始化渲染器。

        Args:
            font_size: 字体大小
        """
        self.font_size = font_size

    async def render_session(self, session: iterm2.Session) -> str:
        """
        渲染单个 session 为 SVG。

        Args:
            session: iTerm2 session 对象

        Returns:
            SVG 字符串
        """
        # 获取实际终端尺寸
        grid_size = session.grid_size
        width = grid_size.width
        height = grid_size.height

        rich_text = await self._capture_styled_content(session)
        return self._render_to_svg(rich_text, width=width, height=height)

    async def render_session_content(
        self, contents: "iterm2.screen.ScreenContents", width: int = 80
    ) -> str:
        """
        渲染 ScreenContents 为 SVG。

        Args:
            contents: iTerm2 ScreenContents 对象
            width: 终端宽度（字符数）

        Returns:
            SVG 字符串
        """
        rich_text = self._convert_contents_to_rich(contents)
        return self._render_to_svg(rich_text, width=width)

    async def _capture_styled_content(self, session: iterm2.Session) -> Text:
        """捕获 session 的带样式内容。"""
        contents = await session.async_get_screen_contents()
        return self._convert_contents_to_rich(contents)

    def _convert_contents_to_rich(self, contents: "iterm2.screen.ScreenContents") -> Text:
        """将 ScreenContents 转换为 Rich Text。"""
        rich_text = Text()

        for line_idx in range(contents.number_of_lines):
            line = contents.line(line_idx)
            line_str = line.string  # 使用完整字符串
            # 清理无效 XML 字符
            line_str = _sanitize_for_xml(line_str)

            # 构建字符到 cell 位置的映射
            cell_idx = 0
            for char in line_str:
                if not char:
                    continue

                # 获取当前 cell 的样式
                style_info = line.style_at(cell_idx) if cell_idx < 500 else None

                if style_info:
                    style = self._build_rich_style(style_info)
                else:
                    style = None

                rich_text.append(char, style=style)

                # 宽字符占 2 个 cell
                cell_idx += 2 if _is_wide_char(char) else 1

            rich_text.append("\n")

        return rich_text

    def _build_rich_style(self, style_info) -> Style | None:
        """从 iTerm2 样式信息构建 Rich Style。"""
        fg = _color_to_rich(style_info.fg_color, "default")
        bg = _color_to_rich(style_info.bg_color, "default")

        style_kwargs: dict[str, str | bool] = {}
        if fg != "default":
            style_kwargs["color"] = fg
        if bg != "default":
            style_kwargs["bgcolor"] = bg
        if style_info.bold:
            style_kwargs["bold"] = True
        if style_info.italic:
            style_kwargs["italic"] = True
        if style_info.underline:
            style_kwargs["underline"] = True

        return Style(**style_kwargs) if style_kwargs else None  # type: ignore[arg-type]

    def _render_to_svg(self, rich_text: Text, width: int = 80, height: int | None = None) -> str:
        """将 Rich Text 渲染为 SVG。

        Args:
            rich_text: Rich Text 对象
            width: 终端宽度（字符数）
            height: 终端高度（行数），用于确保 SVG 比例正确
        """
        console = Console(
            record=True,
            width=width,
            height=height,
            force_terminal=True,
            color_system="truecolor",
        )
        console.print(rich_text, end="")

        return console.export_svg(title="")

    def render_ansi_text(self, text: str, width: int = 80, height: int | None = None) -> str:
        """Render ANSI-escaped text to SVG.

        Used for tmux pane content which comes with ANSI escape sequences.

        Args:
            text: Text with ANSI escape sequences
            width: Terminal width (characters)
            height: Terminal height (lines)

        Returns:
            SVG string
        """
        # Sanitize for XML
        text = _sanitize_for_xml(text)

        console = Console(
            record=True,
            width=width,
            height=height,
            force_terminal=True,
            color_system="truecolor",
        )
        # Rich Console automatically parses ANSI escape sequences
        console.print(text, end="")

        return console.export_svg(title="")

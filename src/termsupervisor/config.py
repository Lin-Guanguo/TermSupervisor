"""TermSupervisor 配置

配置分为以下几类：
- 轮询配置：内容读取间隔
- 状态机配置：状态流转阈值
- 队列配置：Actor 队列参数
- Timer 配置：定时器参数
- 显示配置：延迟显示、通知抑制
- Focus 配置：防抖参数
"""

import os

# === 轮询配置 ===
POLL_INTERVAL = 1.0  # 内容读取间隔（秒）

# === 排除配置 ===
EXCLUDE_NAMES = ["supervisor"]  # 排除的 pane 名称（包含匹配）

# === 调试配置 ===
DEBUG = True  # 调试模式

# === 用户配置 ===
USER_NAME_VAR = "user.name"  # 用户自定义名称变量名

# === 清洗器配置（用于内容变化去重）===
CLEANER_MIN_CHANGED_LINES = 3  # 最少变化行数才触发分析
CLEANER_SIMILARITY_THRESHOLD = 0.9  # 相似度阈值
CLEANER_DEBOUNCE_SECONDS = 5.0  # 防抖间隔（秒）

# === 屏幕内容配置 ===
SCREEN_LAST_N_LINES = 30  # 屏幕内容截取行数
MIN_CHANGED_LINES = 5  # 最少变更行数

# === Actor 队列配置 ===
QUEUE_MAX_SIZE = 256  # 队列最大长度
QUEUE_HIGH_WATERMARK = 0.75  # 高水位阈值（打印 debug 日志）
QUEUE_LOW_PRIORITY_DROP_WATERMARK = 0.80  # 低优先级事件丢弃水位
LOW_PRIORITY_SIGNALS = {"content.changed", "content.update"}  # 低优先级信号
PROTECTED_SIGNALS = {
    "shell.command_end",
    "claude-code.Stop",
    "claude-code.SessionEnd",
}  # 不可丢弃信号

# === Timer 配置 ===
TIMER_TICK_INTERVAL = 1.0  # Timer tick 间隔（秒）

# === 状态机配置 ===
LONG_RUNNING_THRESHOLD_SECONDS = 60.0  # RUNNING → LONG_RUNNING 阈值
STATE_HISTORY_MAX_LENGTH = 30  # 内存中历史记录最大长度

# === 显示层配置 ===
DISPLAY_DELAY_SECONDS = 5.0  # DONE/FAILED → IDLE 延迟显示（秒）
NOTIFICATION_MIN_DURATION_SECONDS = 3.0  # 短任务通知抑制阈值（秒）
AUTO_DISMISS_DWELL_SECONDS = 60.0  # DONE/FAILED 自动消失时间（秒），即使 focused
RECENTLY_FINISHED_HINT_SECONDS = 10.0  # "recently finished" 提示持续时间（秒）
QUIET_COMPLETION_THRESHOLD_SECONDS = 3.0  # 静默完成阈值（秒），短于此不闪烁

# === Focus 防抖配置 ===
FOCUS_DEBOUNCE_SECONDS = 0.3  # iTerm2 focus 防抖时间

# === 内容渲染配置 ===
QUEUE_REFRESH_LINES = 5  # 中等变化阈值，触发页面刷新
QUEUE_NEW_RECORD_LINES = 20  # 大变化阈值
QUEUE_FLUSH_TIMEOUT = 10.0  # 小变化兜底刷新时间（秒）
WAITING_REFRESH_LINES = 1  # WAITING 状态下刷新阈值（更敏感）

# === WAITING 恢复配置 ===
WAITING_FALLBACK_TIMEOUT_SECONDS = 25.0  # WAITING 超时 fallback（秒）
WAITING_FALLBACK_TO_RUNNING = True  # True=超时转 RUNNING，False=超时转 IDLE

# === 日志配置 ===
LOG_LEVEL = os.environ.get("TERMSUPERVISOR_LOG_LEVEL", "INFO")  # 日志级别
LOG_MAX_CMD_LEN = 120  # shell 命令日志截断长度
MASK_COMMANDS = False  # 是否完全隐藏命令内容（隐私模式）

# === 指标配置 ===
METRICS_ENABLED = True  # 是否启用指标收集

# === 通用配置 ===
# Command line redaction: max length before truncation
COMMAND_LINE_MAX_LENGTH = 50

# === Content Heuristic 配置 ===
# Entry keyword: non-empty string enables heuristic mode; empty disables
CONTENT_HEURISTIC_KEYWORD = ""  # e.g., "go/heuristic" or "claude-code"

# Optional exit keyword (empty => disabled)
CONTENT_HEURISTIC_EXIT_KEYWORD = ""

# Optional exit timeout in seconds (0 => no auto-exit)
CONTENT_HEURISTIC_EXIT_TIMEOUT_SECONDS = 0

# Default cooldown for pattern detectors (seconds)
CONTENT_HEURISTIC_COOLDOWN_SECONDS = 2.0

# Resource guard: max lines to scan for heuristic patterns
CONTENT_HEURISTIC_MAX_SCAN_LINES = 200

# Keyword signal mapping: {keyword: {on_appear, on_disappear}}
# Used for keyword presence tracking and RUNNING/DONE status
# Example: {"thinking": {"on_appear": "content.thinking", "on_disappear": "content.thinking_done"}}
CONTENT_HEURISTIC_KEYWORDS: dict[str, dict[str, str]] = {}

# Pattern detectors: list of pattern definitions
# Each pattern has: name, regex, signal, guards (optional), target_group (optional), cooldown (optional)
# Patterns are evaluated in order; first match on a line wins (use for priority)
# Empty list disables pattern detection
CONTENT_HEURISTIC_PATTERNS: list[dict[str, object]] = [
    {
        "name": "esc_to",
        "regex": r"\besc to ([\w./:-]{1,64})\b",
        "regex_flags": ["IGNORECASE"],
        "signal": "heuristic_esc_to",
        "target_group": 1,  # Capture group for target extraction
        "target_strip": ".,;:!?",  # Characters to strip from target
        "guards": [  # Lines matching any guard are skipped
            r"\b(class|def|function|const|let|var)\b",
            r"[{}();]",
            r"\bescape_to\b",
            r"^```|`[^`]+`",
        ],
        "cooldown": 2.0,
    },
    {
        "name": "1yes",
        "regex": r"^1\s*yes",
        "regex_flags": ["IGNORECASE", "MULTILINE"],
        "signal": "heuristic_1yes",
        "target": "approval",  # Fixed target value (no capture group)
        "guards": [
            r"\b(class|def|function|const|let|var)\b",
            r"[{}();]",
            r"\bescape_to\b",
            r"^```|`[^`]+`",
            # Additional 1yes-specific guards
            r"\b(case|switch|enum|return)\b",
            r"^-\s+1\s*yes",
        ],
        "cooldown": 2.0,
    },
]

# 旧配置别名
INTERVAL = POLL_INTERVAL

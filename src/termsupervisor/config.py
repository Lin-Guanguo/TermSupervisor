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
PROTECTED_SIGNALS = {"shell.command_end", "claude-code.Stop", "claude-code.SessionEnd"}  # 不可丢弃信号

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
FOCUS_DEBOUNCE_SECONDS = 2.0  # iTerm2 focus 防抖时间

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

# === 内容启发式配置 ===
# Feature toggle
CONTENT_HEURISTIC_ENABLED = True  # Master switch for content heuristics

# Pane whitelist (only run heuristics for these process/title patterns)
CONTENT_HEURISTIC_PANE_WHITELIST = {"gemini", "codex", "copilot"}

# Job whitelist (for jobName-based gating; defaults to same as pane whitelist)
CONTENT_HEURISTIC_JOB_WHITELIST = {"gemini", "codex", "copilot", "python", "node"}

# Prefer jobName over title when both are available
CONTENT_HEURISTIC_PREFER_JOB_NAME = True

# Command line redaction: max length before truncation
COMMAND_LINE_MAX_LENGTH = 50

# Prompt silence gate: heuristics only activate when PromptMonitor has been
# silent for this duration (seconds); prevents double-firing with shell hooks
CONTENT_T_PROMPT_SILENCE = 5.0

# Quiet thresholds for signal detection (seconds)
CONTENT_T_QUIET_DONE = 2.0   # Quiet time before heuristic_done
CONTENT_T_QUIET_IDLE = 5.0   # Quiet time before heuristic_idle
CONTENT_T_QUIET_WAIT = 1.0   # Quiet time before heuristic_wait

# Debounce and re-emit
CONTENT_HEURISTIC_DEBOUNCE_SEC = 1.0     # Per-signal debounce window
CONTENT_HEURISTIC_REEMIT_IDLE_SEC = 30.0  # Periodic idle re-emit interval

# Newline/burst gate for heuristic_run
CONTENT_HEURISTIC_MIN_NEWLINES = 1       # Min newline increase to trigger run
CONTENT_HEURISTIC_MIN_BURST_CHARS = 50   # Alternative: burst length threshold

# Regex patterns (maintain here; add new anchors centrally)
# Prompt anchors: shell prompts, REPL prompts (>>>, In[n]:, Pdb, Gemini>)
CONTENT_PROMPT_ANCHOR_REGEX = (
    r"(?:[$#%>] |❯|➜|>>>|\.\.\.|\(Pdb\)|In \[\d+\]:|[A-Za-z]+> )\s*$"
)

# Interactivity patterns: y/n prompts, questions, press-to-continue
CONTENT_INTERACTIVITY_REGEX = (
    r"(?:\([yY]/[nN]\)|\[[yY]/[nN]\]|\?\s*$|:\s*$"
    r"|Press .* to .*|Press Enter to continue\.?\s*$|Select.*:\s*$)"
)

# Spinner patterns (progress indicators)
CONTENT_SPINNER_PATTERNS = [
    r"\.{3,}$",           # Trailing ellipsis
    r"[|/\\-]$",          # Spinner chars at end
    r"\d+%",              # Percentage
    r"ETA",               # ETA indicator
    r"MB/s|KB/s",         # Transfer rate
    r"⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏",  # Braille spinner
]

# Completion tokens for heuristic_done
CONTENT_COMPLETION_TOKENS = [
    "done", "finished", "success", "complete", "completed",
    "exit code 0", "ready", "applied", "updated",
]

# Negative patterns: suppress heuristics when these appear (e.g., spinners ending with >)
CONTENT_NEGATIVE_PATTERNS = [
    r"⠋>|⠙>|⠹>|⠸>|⠼>|⠴>|⠦>|⠧>|⠇>|⠏>",  # Spinner followed by prompt-like char
]

# Legacy config aliases (deprecated, kept for backward compatibility)
HEURISTICS_ENABLED = CONTENT_HEURISTIC_ENABLED
HEURISTICS_ALLOWED_SOURCES = CONTENT_HEURISTIC_PANE_WHITELIST
HEURISTICS_IDLE_TIMEOUT_SECONDS = CONTENT_T_QUIET_IDLE
HEURISTICS_MIN_ACTIVITY_LINES = 3  # Not used in new system

# 旧配置别名
INTERVAL = POLL_INTERVAL

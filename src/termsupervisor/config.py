"""TermSupervisor 配置

配置分为以下几类：
- 轮询配置：内容读取间隔
- 状态机配置：状态流转阈值
- 队列配置：Actor 队列参数
- Timer 配置：定时器参数
- 显示配置：延迟显示
- Focus 配置：防抖参数
"""

# === 轮询配置 ===
POLL_INTERVAL = 1.0  # 内容读取间隔（秒）

# === 排除配置 ===
EXCLUDE_NAMES = ["supervisor"]  # 排除的 pane 名称（包含匹配）

# === 调试配置 ===
DEBUG = True  # 调试模式

# === 用户配置 ===
USER_NAME_VAR = "user.name"  # 用户自定义名称变量名

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

# === 日志配置 ===
LOG_MAX_CMD_LEN = 120  # shell 命令日志截断长度

# === 指标配置 ===
METRICS_ENABLED = True  # 是否启用指标收集

# === 通用配置 ===
COMMAND_LINE_MAX_LENGTH = 50  # Command line redaction: max length before truncation

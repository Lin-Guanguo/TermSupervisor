"""TermSupervisor 配置

配置分为以下几类：
- 轮询配置：内容读取间隔
- 状态机配置：状态流转阈值
- 队列配置：Actor 队列参数
- Timer 配置：定时器参数
- 显示配置：延迟显示、通知抑制
- Focus 配置：防抖参数
- 持久化配置：状态文件路径和版本
"""

import os
from pathlib import Path

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

# === Timer 配置 ===
TIMER_TICK_INTERVAL = 1.0  # Timer tick 间隔（秒）

# === 状态机配置 ===
LONG_RUNNING_THRESHOLD_SECONDS = 60.0  # RUNNING → LONG_RUNNING 阈值
STATE_HISTORY_MAX_LENGTH = 30  # 内存中历史记录最大长度
STATE_HISTORY_PERSIST_LENGTH = 5  # 持久化历史记录长度

# === 显示层配置 ===
DISPLAY_DELAY_SECONDS = 5.0  # DONE/FAILED → IDLE 延迟显示（秒）
NOTIFICATION_MIN_DURATION_SECONDS = 3.0  # 短任务通知抑制阈值（秒）

# === Focus 防抖配置 ===
FOCUS_DEBOUNCE_SECONDS = 2.0  # iTerm2 focus 防抖时间

# === 持久化配置 ===
PERSIST_DIR = Path(os.path.expanduser("~/.termsupervisor"))
PERSIST_FILE = PERSIST_DIR / "state.json"
PERSIST_VERSION = 2  # 持久化文件版本

# === 内容渲染配置 ===
QUEUE_REFRESH_LINES = 5  # 中等变化阈值，触发页面刷新
QUEUE_NEW_RECORD_LINES = 20  # 大变化阈值
QUEUE_FLUSH_TIMEOUT = 10.0  # 小变化兜底刷新时间（秒）

# === 日志配置 ===
LOG_LEVEL = os.environ.get("TERMSUPERVISOR_LOG_LEVEL", "INFO")  # 日志级别
LOG_MAX_CMD_LEN = 120  # shell 命令日志截断长度
MASK_COMMANDS = False  # 是否完全隐藏命令内容（隐私模式）

# === 指标配置 ===
METRICS_ENABLED = True  # 是否启用指标收集

# 旧配置别名
INTERVAL = POLL_INTERVAL

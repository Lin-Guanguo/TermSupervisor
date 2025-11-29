"""TermSupervisor 配置"""

# === 轮询配置 ===
# 监控间隔（秒）- 已废弃，使用 POLL_INTERVAL
INTERVAL = 3.0

# 内容读取间隔（秒）
POLL_INTERVAL = 1.0

# 长时间运行任务阈值（秒），超过此时间持续更新则高亮为蓝色
# 已废弃，使用 LONG_RUNNING_THRESHOLD_SECONDS
LONG_RUNNING_THRESHOLD = 15.0

# 排除的 pane 名称（包含匹配）
EXCLUDE_NAMES = ["supervisor"]

# 最少变更行数，超过此值才算有变化
MIN_CHANGED_LINES = 5

# 调试模式
DEBUG = True

# 用户自定义名称变量名
USER_NAME_VAR = "user.name"

# === 状态分析配置 ===
# 状态管理已完全由 Hook 系统接管（Shell PromptMonitor + Claude Code HTTP Hook）
# 原有的 LLM/Rule 分析器已废弃删除

# 清洗器配置（用于变化去重）
CLEANER_MIN_CHANGED_LINES = 3  # 最少变化行数才触发分析
CLEANER_SIMILARITY_THRESHOLD = 0.9  # 相似度阈值
CLEANER_DEBOUNCE_SECONDS = 5.0  # 防抖间隔（秒）

# 屏幕内容截取行数（用于 LLM 分析）
SCREEN_LAST_N_LINES = 30

# === PaneChangeQueue 配置 ===
QUEUE_MAX_SIZE = 20           # 队列最大长度
QUEUE_REFRESH_LINES = 5       # 中等变化阈值，触发页面刷新
QUEUE_NEW_RECORD_LINES = 20   # 大变化阈值，新增队列记录
QUEUE_FLUSH_TIMEOUT = 10.0    # 小变化兜底刷新时间（秒）

# === 状态机配置 ===
LONG_RUNNING_THRESHOLD_SECONDS = 60.0    # RUNNING → LONG_RUNNING 阈值
STATE_HISTORY_MAX_LENGTH = 30            # 状态变化历史队列最大长度

# === Render 事件配置 ===
RENDER_EVENT_MIN_INTERVAL_SECONDS = 10.0  # render 事件最小间隔
RENDER_EVENT_MIN_LINES_CHANGED = 5        # 最小变化行数才触发事件

# === Focus 防抖配置 ===
FOCUS_DEBOUNCE_SECONDS = 3.0              # iTerm2 focus 防抖时间

# === Source 优先级 ===
# 数字越大优先级越高，高优先级 source 可以覆盖低优先级状态
SOURCE_PRIORITY = {
    "claude-code": 10,
    "gemini": 10,
    "codex": 10,
    "shell": 1,
    "render": 1,
    "timer": 0,
}

"""TermSupervisor 配置"""

# === 轮询配置 ===
# 监控间隔（秒）- 已废弃，使用 POLL_INTERVAL
INTERVAL = 3.0

# 内容读取间隔（秒）
POLL_INTERVAL = 1.0

# 长时间运行任务阈值（秒），超过此时间持续更新则高亮为蓝色
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

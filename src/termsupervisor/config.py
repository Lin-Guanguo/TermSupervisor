"""TermSupervisor 配置"""

# 监控间隔（秒）
INTERVAL = 3.0

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

# 分析器类型: "rule" (规则引擎) | "llm" (LLM 分析)
ANALYZER_TYPE = "rule"

# LLM 分析器配置
LLM_MODEL = "google/gemini-2.5-flash"
LLM_TIMEOUT = 15.0
LLM_MAX_TOKENS = 100

# 清洗器配置
CLEANER_MIN_CHANGED_LINES = 3  # 最少变化行数才触发分析
CLEANER_SIMILARITY_THRESHOLD = 0.9  # 相似度阈值
CLEANER_DEBOUNCE_SECONDS = 5.0  # 防抖间隔（秒）

# 屏幕内容截取行数（用于 LLM 分析）
SCREEN_LAST_N_LINES = 30

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

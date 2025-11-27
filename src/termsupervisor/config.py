"""TermSupervisor 配置"""

# 监控间隔（秒）
INTERVAL = 5.0

# 排除的 pane 名称（包含匹配）
EXCLUDE_NAMES = ["supervisor"]

# 最少变更行数，超过此值才算有变化
MIN_CHANGED_LINES = 3

# 调试模式
DEBUG = True

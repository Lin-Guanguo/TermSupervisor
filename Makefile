.PHONY: run rerun run-web run-cli stop viewlog taillog loghook logerr debug-states debug-state clean test help

LOG_FILE = server.log
PROC_NAME = termsupervisor
DEBUG_BASE = http://localhost:8765

# 后台运行 Web 服务
run:
	@echo "Starting TermSupervisor Web Server..."
	@nohup uv run $(PROC_NAME) >> $(LOG_FILE) 2>&1 &
	@sleep 1
	@PID=$$(pgrep -f "$(PROC_NAME)" | head -1); \
	if [ -n "$$PID" ]; then \
		echo "Server started (PID: $$PID)"; \
	else \
		echo "Server started"; \
	fi
	@echo "Log: $(LOG_FILE)"
	@echo "URL: http://localhost:8765"

# 重启服务
rerun: stop run

# 前台运行 Web 服务
run-web:
	uv run $(PROC_NAME) 2>&1 | tee $(LOG_FILE)

# 运行 CLI 监控
run-cli:
	uv run termsupervisor

# 停止后台服务
stop:
	@PID=$$(pgrep -f "$(PROC_NAME)"); \
	if [ -n "$$PID" ]; then \
		echo "Stopping server (PID: $$PID)..."; \
		kill $$PID 2>/dev/null || true; \
		sleep 1; \
		echo "Server stopped"; \
	else \
		echo "No server running"; \
	fi

# 查看完整日志
viewlog:
	@if [ -f $(LOG_FILE) ]; then \
		cat $(LOG_FILE); \
	else \
		echo "No log file found"; \
	fi

# 实时查看日志
taillog:
	@if [ -f $(LOG_FILE) ]; then \
		tail -f $(LOG_FILE); \
	else \
		echo "No log file found"; \
	fi

# 实时监控 Hook 事件
loghook:
	@if [ -f $(LOG_FILE) ]; then \
		tail -f $(LOG_FILE) | while IFS= read -r line; do echo "$$line" | grep -q "\[HookEvent\]" && echo "$$line"; done; \
	else \
		echo "No log file found"; \
	fi

# 实时监控错误日志
logerr:
	@if [ -f $(LOG_FILE) ]; then \
		tail -f $(LOG_FILE) | while IFS= read -r line; do echo "$$line" | grep -qiE "error|exception|traceback|failed" && echo "$$line"; done; \
	else \
		echo "No log file found"; \
	fi

# 调试：列出所有 pane 调试快照（参考 README）
debug-states:
	@resp=$$(curl -sf "$(DEBUG_BASE)/api/debug/states") || { \
		echo "debug-states: failed to reach $(DEBUG_BASE) (server down or sandbox blocked)"; \
		exit 1; \
	}; \
	echo "$$resp" | jq '.states[] | {pane_id,status,source,queue_depth,latest_history: .latest_history[0]}'

# 调试：查看单个 pane 状态机/队列详情，ID=<pane_id>（参考 README）
debug-state:
	@if [ -z "$(ID)" ]; then \
		echo "Usage: make debug-state ID=<pane_id> [HIST=20] [PENDING=10]"; \
	else \
		resp=$$(curl -sf "$(DEBUG_BASE)/api/debug/state/$(ID)?max_history=$${HIST:-20}&max_pending_events=$${PENDING:-10}") || { \
			echo "debug-state: failed to reach $(DEBUG_BASE) (server down or sandbox blocked)"; \
			exit 1; \
		}; \
		echo "$$resp" | jq '.'; \
	fi

# 运行测试
test:
	uv run pytest

# 清理
clean:
	rm -f $(LOG_FILE)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

.PHONY: run rerun run-web run-cli stop viewlog taillog clean test help

LOG_FILE = server.log
PROC_NAME = termsupervisor

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

# 运行测试
test:
	uv run pytest

# 清理
clean:
	rm -f $(LOG_FILE)
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

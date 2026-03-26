# DeerFlow API 测试脚本使用指南

## 前置条件

1. 确保后端服务已启动（至少 Gateway 在 `:8001` 运行）
2. 如果要测试 LangGraph 对话接口，需要 LangGraph Server 在 `:2024` 运行
3. 通过 `make dev` 或 `scripts/serve.sh` 启动全部服务

## 测试脚本位置

```
backend/tests/test_api_debug.py    # 完整 API 测试脚本 (httpx)
```

## 使用方式

### 1. 运行全部测试
```bash
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py
```

### 2. 运行单个模块测试
```bash
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module models
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module memory
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module mcp
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module skills
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module agents
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module uploads
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module artifacts
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module threads
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module suggestions
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module channels
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module user_profile
cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module langgraph
```

**LangGraph 细分功能测试：**
在 `langgraph` 主入口下，涵盖了 17 个细分功能的子测试，您也可以单独运行某一个，例如：
```bash
uv run python tests/test_api_debug.py --module lg_plan          # 单独测 Plan 模式
uv run python tests/test_api_debug.py --module lg_tools         # 单独测 Sandbox 工具执行
uv run python tests/test_api_debug.py --module lg_clarification # 单独测 Clarification 中断与恢复
```
全部 17 个子模块标识为：
`lg_basic`, `lg_multiturn`, `lg_thinking`, `lg_plan`, `lg_tools`, `lg_subagent`, `lg_custom_agent`, `lg_file_upload`, `lg_stream_modes`, `lg_reasoning`, `lg_model`, `lg_search`, `lg_clarification`, `lg_bootstrap`, `lg_error`, `lg_thread_mgmt`, `lg_run_mgmt`。

---

## 高阶：底层组件级调试 (Component Debug)

在实际开发中，一些功能依赖于 `config.yaml` 的配置才能触发网络接口测试（如 AioSandboxProvider 即 Docker 沙箱、Guardrails 拦截等）。如果您希望**脱离 API 网络层并且不修改主 `config.yaml`** 直接硬编码调试底层隔离组件，可以使用组件专用的调试脚本。

### 测试脚本位置

```
backend/tests/test_components_debug.py    # 底层配置组件测试与调试脚本
```

### 使用方式

可以直接在 PyCharm / VS Code 中以 Debug 模式运行它，它提供了对 `LocalSandboxProvider` 和 `AioSandboxProvider` 的直接依赖实例化并调用 `execute_command()`：

```bash
cd backend && uv run python tests/test_components_debug.py
```
*此脚本会真实占用本地进程并（若调起 Docker 沙箱）创建真实的容器与挂载卷，特别适合排查文件 `mount` 挂载及 Docker 权限问题。*

---

## 最佳实践与 IDE 调试

### 1. PyCharm/VS Code 调试网络层
在 IDE 中设置断点，然后以 debug 模式运行 `tests/test_api_debug.py`。
脚本中的每个接口调用都有详细注释，可以在关键位置设置断点来理解后端处理流程。

### 2. 配合后端 debug 调试
同时用 debug 模式启动后端 Gateway:
```bash
cd backend && PYTHONPATH=. uv run python -m uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload
```
然后在 `app/gateway/routers/*.py` 或是 `agent.py` 的处理函数中设置断点。

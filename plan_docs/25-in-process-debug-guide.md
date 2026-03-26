# DeerFlow 内部源码级调试测试指南 (In-Process Debug Guide)

本指南针对 `test_api_debug_in.py` 的设计理念、具体使用方法以及底层隔离细节进行了详细描述。无论你是需要排查复杂的 LangGraph Agent 执行流异常，还是诊断 Gateway 层面的 API 服务错误，这个文件都是调试问题的首选入口。

---

## 1. 为什么需要 `test_api_debug_in`？

在常规系统架构中，DeerFlow 的后端被分为两个独立运行的服务进程：
1. **Gateway 服务 (FastAPI)**：只负责请求路由、客户端通信封装。
2. **LangGraph Server**：承载 Agent 侧心智和执行底层能力（沙箱、知识库等）。

最初的 `test_api_debug.py` 测试文件是站在**客户端**的视角，使用 `httpx` (HTTP 请求客户端) 先后向 Gateway 和 LangGraph Server 发请求。
- **痛点**：如果你在 `deerflow/agents/lead_agent/agent.py` 的源码中打了一个断点，但在跑 `test_api_debug.py` 时是用 PyCharm 断点调试启动的，这个程序只会**停在网络请求 (`httpx.post`) 发出的地方**，因为它没有权限拦截到另外开启的服务端进程的内部执行细节。

**解决方案就是 `test_api_debug_in.py`。**
它摒弃了网络层的隔离限制，将 FastAPI 应用 (`app.gateway.app`) 和 LangGraph 的引擎 (`make_lead_agent`) 直接加载到了**同一个 Python 进程的内存中**运行，从而实现了完美的**一键全链路断点调试**。

---

## 2. 测试集脚本位置

```bash
backend/tests/test_api_debug_in.py
```

---

## 3. 详细的 PyCharm 调试实战配置

### 3.1 环境路径自动处理
该脚本内部头两行自动执行了 `sys.path.insert(0, ...)` 以注入 `backend/` 根目录。这意味着你在运行时可以**不再需要**反复去调整环境变量 (`PYTHONPATH=.`)。只要使用的是此虚拟环境 (`.venv`) 即可直接启动。

### 3.2 在 PyCharm 设置 Debug Configurations（运行配置）
你可以通过以下配置在 PyCharm 中轻松管理并针对特定模块进行断点打点：

1. 打开右上角的 **Edit Configurations...**
2. 点击 `+` 添加一个新的 **Python** 配置。
3. 配置参数建议：
   - **Name**: `Debug: Deerflow API In-Process`
   - **Script Path**: 选中本地的 `backend/tests/test_api_debug_in.py` 路径
   - **Parameters**（按需可选）: 
     - 留空表示**一次性将 Gateway和 LangGraph 所有 30+ 项的测试跑完**。
     - `--module langgraph`：仅运行 LangGraph Agent 大类的全部通信测试。
     - `--module lg_plan`：仅执行 LangGraph 的 Plan(Todo计划) 模式单点测试。
     - `--module lg_subagent`：仅调试 子节点任务分发 模式。
   - **Environment Variables**（按需可选）：例如 `TAVILY_API_KEY=your_key` 解决联网搜索失败报错问题。

### 3.3 实战：在不同模块的源码处打断点
根据测试运行目标的差异，你可以在不同的代码区打断点并完美命中：

#### 情境 A：调试普通的 Gateway API 接口
- **需求**：你想调试文件上传接口遇到 404 或解析问题，或者调试 Agent 配置管理报错。
- **断点位置**：定位到 `backend/app/gateway/routers/` 这个文件夹。举例：在 `uploads.py` 中的 `upload_files` 方法内打断点。
- **原理**：`test_api_debug_in.py` 使用了 `fastapi.testclient.TestClient(app)` 进行路由调用。它是直接在 Python 内存堆栈级调起目标方法。

#### 情境 B：调试 LangGraph 以及 Agent 的提示词生成、工具分发流
- **需求**：你想看看大模型收到的 System Prompt 被中间件组装成了什么样，或者检查为何 `Agent` 没有调用沙箱工具。
- **断点位置**：
  - `backend/packages/harness/deerflow/agents/lead_agent/agent.py` （通常在 `make_lead_agent` 入口或者 `_build_middlewares` 函数中）
  - 各类具体的 Middleware，例如 `tool_error_handling_middleware.py` 的 `awrap_tool_call`
  - 某个具体 Tool 的功能源码：如 `deerflow/tools/sandbox/tools.py` 里的 `run_code` 函数内。
- **原理**：底层使用了 `asyncio.run` 同步包装引擎，并且将 `make_checkpointer` 直接手动注册给初始化好的局域 `graph` 进行流式（`graph.astream`）事件推演。由于同属于同一个解释器，在流式触发上述函数时直接命中你的断点。

---

## 4. 技术实现与底层 Mock（模拟）细节

与 `test_api_debug.py` 相比，我们在 In-Process 脚本中进行了深度的接口隔离平替与网络模拟操作：

* **API Client 替换**：将所有的 `httpx.get(f"{gw}/api/xxx")` 批量替换成了 `gateway_client.get("/api/xxx")`，使其变为 HTTP 测试请求（跳过真实的网关绑定端口直接进入 FastAPI 路由解析层）。
* **线程态（State）虚拟储存**：
  由于我们没有开 LangGraph Server，原本发送 `POST /threads` 请求来创建隔离线程的操作，被平替为 `_IN_PROCESS_THREADS` 全局字典作为本地测试运行周期的生命持久化对象层。所有在 Agent 过程执行 `aget_state` 的数据变化全部缓存于 Python 内存中并作为测试效能反馈。
* **模拟流式 SSE `_async_lg_stream_chat`**：
  完全绕过了原有的 Server 引擎监听端。直接在 Python 实例中创建了原始 `langgraph.types.Checkpointer`，传入配置直接开启原生的 `graph.astream()` 接口输出数据并且将其组装成了日志打印。

---

## 5. 日志与异常诊断指南 (Q&A)

### Q: 我在运行到联网搜索测试环节时，见到了大段红字 Traceback (例如 `MissingAPIKeyError`)？这是代表程序崩溃了吗？

```text
26-04-12 23:22:50 - deerflow.agents.middlewares.tool_error_handling_middleware - ERROR - Tool execution failed (async): name=web_search id=call_-77155291...
Traceback (most recent call last):
  ...
  File "/Users/fxl/.../tavily/tavily.py", line 20, in __init__
    raise MissingAPIKeyError()
tavily.errors.MissingAPIKeyError: No API key provided. Please provide the api_key...
```

**A: 绝对没有崩溃。这是框架底层出色的异常容灾处理体现，是一个极具误导性的正确行为。**  
它的流程拆解如下：
1. 大模型 (Agent) 在接受到请求时主动输出了期望调用 `web_search_tool` 工具的请求。
2. 内部源码在启动 `TavilyClient` 初始化时，发现本地未配备环境变量 `TAVILY_API_KEY`，抛出了原生的级联阻断错误 `MissingAPIKeyError`。
3. **关键点**：`ToolErrorHandlingMiddleware` 中间件作为我们 LangGraph 框架的守护拦截者，**成功拦截了这个代码层面的崩溃**。
4. 拦截之后，该中间件向控制台打印错误记录（使用 `logging.error(..., exc_info=True)` 将原生的堆栈信息如上红字打印记录以便排查）。
5. \*\*中间件紧接着会将这一段错误转化为单纯的字符串（如：`"Tool failed: No API key provided."`），包装进 `ToolMessage` 发回给大模型。
6. 大模型收到了这段文本，然后正常继续执行对话循环（有可能会输出“抱歉我无法搜网因为缺少凭证”），使得你的整个后续流不被终止。

如果你的调试觉得这些红字影响心智：你只需要在运行参数的 Environment Variabes 里增加一个虚拟键值 `TAVILY_API_KEY=debug_bypass_key ` 绕过它即可。

---

## 6. 特别注意：组件专用的单元沙箱机制

此脚本 (`_in` 版本) 主要负责整合打通业务流程层的接口（也就是从用户发了一条信息到路由层再到 Agent 跑完这一整条线）。

如果你仅仅想关注：**如何测试基于 Docker 的 `AioSandboxProvider` 的挂载、容器读写，或者某个防护（Guardrails）底层的隔离边界能否限制执行**：
那么不要用 `test_api_debug_in.py`，而是请直接前往 `tests/test_components_debug.py`。在该脚本下你能更低层级地抛开 Agent，去纯粹执行一次沙箱内部命令（`sandbox.execute_command`）验证容器化技术的权限控制结果。

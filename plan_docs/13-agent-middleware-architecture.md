# Agent 中间件架构详解

## 1. AgentMiddleware 概述

### 1.1 什么是 AgentMiddleware

`AgentMiddleware` 是 LangChain 定义的 Agent 执行拦截器基类，允许在 Agent 主循环的各个阶段自定义行为。

源码位置：https://github.com/langchain-ai/langchain/blob/master/libs/langchain_v1/langchain/agents/middleware/types.py

```python
class AgentMiddleware(Generic[StateT, ContextT, ResponseT]):
    """Base middleware class for an agent."""
```

### 1.2 生命周期钩子

| 阶段 | 同步方法 | 异步方法 | 作用 |
|------|---------|---------|------|
| Agent 执行前 | `before_agent` | `abefore_agent` | 准备状态、目录、资源 |
| 调用模型前 | `before_model` | `abefore_model` | 修改请求/消息 |
| 调用模型后 | `after_model` | `aafter_model` | 处理响应 |
| **工具调用（同步）** | **`wrap_tool_call`** | - | 拦截同步工具执行 |
| **工具调用（异步）** | - | **`awrap_tool_call`** | 拦截异步工具执行 |
| Agent 执行后 | `after_agent` | `aafter_agent` | 清理资源 |

### 1.3 中间件组合顺序

多个中间件按数组顺序组合，**第一个定义的中间件 = 最外层**：

```
middlewares = [
    MiddlewareA,  # [0] 最外层，先进入后退出
    MiddlewareB,  # [1] 中间层
    MiddlewareC,  # [2] 最内层，最后进入最先退出
]
```

调用链：

```
MiddlewareA.before_agent()
         │
         ▼
    MiddlewareB.before_agent()
         │
         ▼
    MiddlewareC.before_agent()
         │
         ▼
    [Model Execution]
         │
         ▼
    MiddlewareC.after_agent()
         │
         ▼
    MiddlewareB.after_agent()
         │
         ▼
    MiddlewareA.after_agent()
```

### 1.4 wrap_tool_call / awrap_tool_call 详解

```python
def wrap_tool_call(
    self,
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
) -> ToolMessage | Command[Any]
```

**关键特性**：
- `handler` 是实际执行工具的回调，**可以被多次调用**（用于重试）
- 可以**跳过不调用**直接返回实现短路
- 可以**修改请求/响应**

```
┌─────────────────────────────────────────────────────────────┐
│          wrap_tool_call() 执行流程                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ToolCallRequest ──────────────────────────────────────────│
│       │                                                    │
│       ▼                                                    │
│  ┌────────────────────────────────────────┐               │
│  │ 中间件可以修改 request                  │               │
│  └────────────────────────────────────────┘               │
│       │                                                    │
│       ▼                                                    │
│  ┌────────────────────────────────────────┐               │
│  │ 调用 handler(request) 执行工具         │               │
│  │ 或者跳过（短路）                       │               │
│  └────────────────────────────────────────┘               │
│       │                                                    │
│       ▼                                                    │
│  ┌────────────────────────────────────────┐               │
│  │ 中间件可以修改响应                      │               │
│  └────────────────────────────────────────┘               │
│       │                                                    │
│       ▼                                                    │
│  返回 ToolMessage 或 Command                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 2. DeerFlow 中间件数组

### 2.1 构建入口

中间件在 `make_lead_agent()` 内部通过 `_build_middlewares()` 构建：

```python
# deerflow/agents/lead_agent/agent.py:208-265
def _build_middlewares(config: RunnableConfig, model_name: str | None, agent_name: str | None = None):
    """Build middleware chain based on runtime configuration."""
    middlewares = build_lead_runtime_middlewares(lazy_init=True)

    # Add summarization middleware if enabled
    summarization_middleware = _create_summarization_middleware()
    if summarization_middleware is not None:
        middlewares.append(summarization_middleware)

    # Add TodoList middleware if plan mode is enabled
    is_plan_mode = config.get("configurable", {}).get("is_plan_mode", False)
    todo_list_middleware = _create_todo_list_middleware(is_plan_mode)
    if todo_list_middleware is not None:
        middlewares.append(todo_list_middleware)

    # Add TokenUsageMiddleware when token_usage tracking is enabled
    if get_app_config().token_usage.enabled:
        middlewares.append(TokenUsageMiddleware())

    # Add TitleMiddleware
    middlewares.append(TitleMiddleware())

    # Add MemoryMiddleware (after TitleMiddleware)
    middlewares.append(MemoryMiddleware(agent_name=agent_name))

    # Add ViewImageMiddleware only if the current model supports vision
    if model_config is not None and model_config.supports_vision:
        middlewares.append(ViewImageMiddleware())

    # Add DeferredToolFilterMiddleware to hide deferred tool schemas from model binding
    if app_config.tool_search.enabled:
        middlewares.append(DeferredToolFilterMiddleware())

    # Add SubagentLimitMiddleware to truncate excess parallel task calls
    if subagent_enabled:
        middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents))

    # LoopDetectionMiddleware — detect and break repetitive tool call loops
    middlewares.append(LoopDetectionMiddleware())

    # ClarificationMiddleware should always be last
    middlewares.append(ClarificationMiddleware())
    return middlewares
```

### 2.2 Lead Agent 完整中间件数组

```
[0]  ThreadDataMiddleware
[1]  UploadsMiddleware
[2]  SandboxMiddleware
[3]  DanglingToolCallMiddleware
[4]  GuardrailMiddleware (条件启用)
[5]  ToolErrorHandlingMiddleware
[6]  SummarizationMiddleware (条件启用)
[7]  TodoMiddleware (条件启用)
[8]  TokenUsageMiddleware (条件启用)
[9]  TitleMiddleware
[10] MemoryMiddleware
[11] ViewImageMiddleware (条件启用)
[12] DeferredToolFilterMiddleware (条件启用)
[13] SubagentLimitMiddleware (条件启用)
[14] LoopDetectionMiddleware
[15] ClarificationMiddleware
```

### 2.3 中间件执行顺序注释

代码注释明确说明了各中间件的顺序要求：

```python
# deerflow/agents/lead_agent/agent.py:200-207
# DanglingToolCallMiddleware patches missing ToolMessages before model sees the history
# SummarizationMiddleware should be early to reduce context before other processing
# TodoListMiddleware should be before ClarificationMiddleware to allow todo management
# TitleMiddleware generates title after first exchange
# MemoryMiddleware queues conversation for memory update (after TitleMiddleware)
# ViewImageMiddleware should be before ClarificationMiddleware to inject image details before LLM
# ToolErrorHandlingMiddleware should be before ClarificationMiddleware to convert tool exceptions to ToolMessages
# ClarificationMiddleware should be the last to intercept clarification requests after model calls
```

### 2.4 中间件分类表

| 索引 | 中间件 | 钩子 | 条件 | 作用 |
|-----|--------|------|------|------|
| 0 | ThreadDataMiddleware | before_agent | 始终 | 准备线程数据目录 |
| 1 | UploadsMiddleware | before_agent | 始终 | 注入上传文件信息 |
| 2 | SandboxMiddleware | before/after_agent | 始终 | 沙箱获取/释放 |
| 3 | DanglingToolCallMiddleware | wrap/awrap_model_call | 始终 | 修复悬空工具调用 |
| 4 | GuardrailMiddleware | wrap/awrap_tool_call | config | 安全审查 |
| 5 | ToolErrorHandlingMiddleware | wrap/awrap_tool_call | 始终 | 异常处理 |
| 6 | SummarizationMiddleware | after_model | config | 消息摘要压缩 |
| 7 | TodoMiddleware | before_model | config | Todo 上下文丢失检测 |
| 8 | TokenUsageMiddleware | after_model | config | Token 使用日志 |
| 9 | TitleMiddleware | after_model | 始终 | 生成对话标题 |
| 10 | MemoryMiddleware | after_agent | config | 记忆队列更新 |
| 11 | ViewImageMiddleware | before_model | config | 注入图片详情 |
| 12 | DeferredToolFilterMiddleware | wrap/awrap_model_call | config | 过滤延迟工具 |
| 13 | SubagentLimitMiddleware | after_model | config | 限制并发子代理 |
| 14 | LoopDetectionMiddleware | after_model | 始终 | 循环检测 |
| 15 | ClarificationMiddleware | wrap/awrap_tool_call | 始终 | 拦截澄清请求 |

## 3. 各中间件详解

### 3.1 ThreadDataMiddleware

**源文件**：`deerflow/agents/middlewares/thread_data_middleware.py`

**作用**：在 Agent 执行前准备线程数据目录

**使用钩子**：`before_agent`

```python
# deerflow/agents/middlewares/thread_data_middleware.py:18-96
class ThreadDataMiddleware(AgentMiddleware[ThreadDataMiddlewareState]):
    """Create thread data directories for each thread execution."""

    def __init__(self, base_dir: str | None = None, lazy_init: bool = True):
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()
        self._lazy_init = lazy_init

    @override
    def before_agent(self, state: ThreadDataMiddlewareState, runtime: Runtime) -> dict | None:
        context = runtime.context or {}
        thread_id = context.get("thread_id")
        if thread_id is None:
            config = get_config()
            thread_id = config.get("configurable", {}).get("thread_id")

        if thread_id is None:
            raise ValueError("Thread ID is required in runtime context or config.configurable")

        if self._lazy_init:
            # 懒加载：只计算路径，不创建目录
            paths = self._get_thread_paths(thread_id)
        else:
            #  eager 加载：立即创建目录
            paths = self._create_thread_directories(thread_id)

        return {"thread_data": {...paths}}
```

**目录结构**：

```
{base_dir}/threads/{thread_id}/
├── user-data/
│   ├── workspace/      # 工作目录
│   ├── uploads/        # 上传文件目录
│   └── outputs/        # 输出文件目录
```

**执行流程**：

```
before_agent(thread_id="thread-123")
         │
         ▼
┌─────────────────────────────────────────┐
│ 1. 从 runtime.context 获取 thread_id   │
│ 2. 构建目录路径:                         │
│    - workspace_path: .../thread-123/   │
│    - uploads_path:  .../thread-123/   │
│    - outputs_path:  .../thread-123/   │
│                                         │
│ 3. lazy_init=True (默认):               │
│    只计算路径，不创建目录                │
│                                         │
│ 4. lazy_init=False:                     │
│    立即创建目录                          │
└─────────────────────────────────────────┘
         │
         ▼
更新 state: {thread_data: {workspace_path, uploads_path, outputs_path}}
```

### 3.2 UploadsMiddleware

**源文件**：`deerflow/agents/middlewares/uploads_middleware.py`

**作用**：注入上传文件信息到 Agent 上下文

**使用钩子**：`before_agent`

```python
# deerflow/agents/middlewares/uploads_middleware.py:119-204
@override
def before_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
    messages = list(state.get("messages", []))
    if not messages:
        return None

    last_message_index = len(messages) - 1
    last_message = messages[last_message_index]

    if not isinstance(last_message, HumanMessage):
        return None

    # 从 additional_kwargs.files 获取新上传文件
    new_files = self._files_from_kwargs(last_message, uploads_dir) or []

    # 扫描 uploads 目录获取历史文件
    historical_files: list[dict] = []
    if uploads_dir and uploads_dir.exists():
        for file_path in sorted(uploads_dir.iterdir()):
            if file_path.is_file() and file_path.name not in new_filenames:
                historical_files.append({...})

    # 构造 <uploaded_files> 消息块
    files_message = self._create_files_message(new_files, historical_files)

    # 追加到用户消息内容前
    updated_message = HumanMessage(
        content=f"{files_message}\n\n{original_content}",
        id=last_message.id,
        additional_kwargs=last_message.additional_kwargs,
    )

    return {"uploaded_files": new_files, "messages": messages}
```

**执行效果**：

```
用户消息:
┌─────────────────────────────────────────────────┐
│ 帮我分析这个文件                                 │
└─────────────────────────────────────────────────┘

经过 UploadsMiddleware 后:
┌─────────────────────────────────────────────────┐
│ <uploaded_files>                               │
│ The following files were uploaded in this       │
│ message:                                       │
│ - report.pdf (2.3 MB)                          │
│   Path: /mnt/user-data/uploads/report.pdf      │
│                                                 │
│ The following files were uploaded in previous   │
│ messages and are still available:              │
│ - data.xlsx (500 KB)                           │
│ </uploaded_files>                              │
│                                                 │
│ 帮我分析这个文件                                 │
└─────────────────────────────────────────────────┘
```

### 3.3 SandboxMiddleware

**源文件**：`deerflow/sandbox/middleware.py`

**作用**：获取/释放沙箱环境

**使用钩子**：`before_agent`（获取）、`after_agent`（释放）

```python
# deerflow/sandbox/middleware.py:45-83
class SandboxMiddleware(AgentMiddleware[SandboxMiddlewareState]):
    def __init__(self, lazy_init: bool = True):
        super().__init__()
        self._lazy_init = lazy_init

    def _acquire_sandbox(self, thread_id: str) -> str:
        provider = get_sandbox_provider()
        sandbox_id = provider.acquire(thread_id)
        return sandbox_id

    @override
    def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        if self._lazy_init:
            # 懒加载：延迟到第一个工具调用
            return super().before_agent(state, runtime)

        # 立即获取沙箱
        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = (runtime.context or {}).get("thread_id")
            sandbox_id = self._acquire_sandbox(thread_id)
            return {"sandbox": {"sandbox_id": sandbox_id}}

    @override
    def after_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        sandbox = state.get("sandbox")
        if sandbox is not None:
            sandbox_id = sandbox["sandbox_id"]
            get_sandbox_provider().release(sandbox_id)
        return None
```

**生命周期**：

```
┌─────────────────────────────────────────────────────────────────┐
│                    SandboxMiddleware 生命周期                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  before_agent():                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ if lazy_init=True (默认):                                 │  │
│  │     跳过获取沙箱（延迟到第一个工具调用）                    │  │
│  │ else:                                                      │  │
│  │     sandbox_id = acquire(thread_id)                        │  │
│  │     return {"sandbox": {"sandbox_id}}                     │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  after_agent():                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ release(sandbox_id)                                       │  │
│  │ (实际由 provider 决定是否复用或销毁)                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.4 DanglingToolCallMiddleware

**源文件**：`deerflow/agents/middlewares/dangling_tool_call_middleware.py`

**作用**：修复"悬空"工具调用

**使用钩子**：`wrap_model_call` / `awrap_model_call`

```python
# deerflow/agents/middlewares/dangling_tool_call_middleware.py:36-88
class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """Inserts placeholder ToolMessages for dangling tool calls."""

    def _build_patched_messages(self, messages: list) -> list | None:
        # 收集所有现有 ToolMessage.id
        existing_tool_msg_ids: set[str] = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                existing_tool_msg_ids.add(msg.tool_call_id)

        # 检查是否存在悬空 tool_calls
        needs_patch = False
        for msg in messages:
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in getattr(msg, "tool_calls", None) or []:
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids:
                    needs_patch = True
                    break

        if not needs_patch:
            return None

        # 在悬空的 AIMessage 后插入占位 ToolMessage
        patched: list = []
        for msg in messages:
            patched.append(msg)
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in getattr(msg, "tool_calls", None) or []:
                tc_id = tc.get("id")
                if tc_id and tc_id not in existing_tool_msg_ids:
                    patched.append(
                        ToolMessage(
                            content="[Tool call was interrupted and did not return a result.]",
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
        return patched

    @override
    def wrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)
```

**问题场景与修复**：

```
【问题场景】用户中断请求时可能产生悬空 tool_calls：

┌─────────────────────────────────────────┐
│ AIMessage (tool_calls=[{id:"tc1",...}]) │
│      │                                  │
│      │ 缺少对应的 ToolMessage!          │
│      ▼                                  │
│ (后续消息...)                           │
└─────────────────────────────────────────┘

LLM 看到这个不完整的消息链会报错。

【修复后】：

┌─────────────────────────────────────────┐
│ AIMessage (tool_calls=[{id:"tc1",...}]) │
│ ToolMessage ────────────────────────────│
│   content="[interrupted]"              │
│   status="error"                       │ ← 插入的占位符
│ (其他消息...)                           │
└─────────────────────────────────────────┘
```

**为什么用 wrap_model_call 而不是 before_model**：

注释说明：
> Uses `wrap_model_call` instead of `before_model` to ensure patches are inserted at the correct positions (immediately after each dangling AIMessage), not appended to the end of the message list as `before_model` + `add_messages` reducer would do.

### 3.5 GuardrailMiddleware

**源文件**：`deerflow/guardrails/middleware.py`

**作用**：工具执行前的安全审查

**使用钩子**：`wrap_tool_call` / `awrap_tool_call`

```python
# deerflow/guardrails/middleware.py:20-98
class GuardrailMiddleware(AgentMiddleware[AgentState]):
    def __init__(self, provider: GuardrailProvider, *, fail_closed: bool = True, passport: str | None = None):
        self.provider = provider
        self.fail_closed = fail_closed
        self.passport = passport

    @override
    def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        gr = self._build_request(request)  # 构建审查请求
        try:
            decision = await self.provider.aevaluate(gr)
        except GraphBubbleUp:
            raise  # 保留 LangGraph 控制流信号
        except Exception:
            logger.exception("Guardrail provider error (async)")
            if self.fail_closed:
                # fail_closed=True: 拒绝
                decision = GuardrailDecision(allow=False, reasons=[...])
            else:
                # fail_closed=False: 放行
                return await handler(request)

        if not decision.allow:
            # 拒绝：返回错误 ToolMessage
            logger.warning("Guardrail denied: ...")
            return self._build_denied_message(request, decision)

        return await handler(request)
```

**GuardrailProvider 协议**：

```python
# deerflow/guardrails/provider.py
class GuardrailProvider(Protocol):
    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision: ...
    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision: ...
```

**AllowlistProvider 内置实现**：

```python
# deerflow/guardrails/builtin.py:6-23
class AllowlistProvider:
    def __init__(self, *, allowed_tools=None, denied_tools=None):
        self._allowed = set(allowed_tools) if allowed_tools else None
        self._denied = set(denied_tools) if denied_tools else set()

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        # 白名单模式：不在白名单则拒绝
        if self._allowed is not None and request.tool_name not in self._allowed:
            return GuardrailDecision(allow=False, reasons=[...])
        # 黑名单模式：在黑名单则拒绝
        if request.tool_name in self._denied:
            return GuardrailDecision(allow=False, reasons=[...])
        return GuardrailDecision(allow=True, reasons=[...])
```

**执行流程**：

```
awrap_tool_call(工具调用请求)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 构建 GuardrailRequest:                                   │
│    - tool_name: "bash"                                     │
│    - tool_input: {"command": "rm -rf /"}                   │
│    - agent_id: passport                                     │
│    - timestamp: "2026-03-31T..."                           │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 调用 provider.evaluate(request)                         │
│    AllowlistProvider.evaluate():                            │
│    - denied_tools: ["bash", "write_file"]                  │
│    - "bash" in denied_tools? → True                        │
│    → return GuardrailDecision(allow=False, ...)            │
└─────────────────────────────────────────────────────────────┘
         │
         ├─── allow=True ──► 执行 handler(request) → 工具执行
         │
         └─── allow=False ──► 返回错误 ToolMessage
                              Agent 看到错误，换其他工具
```

**配置示例**：

```yaml
# config.yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: ["bash", "write_file"]
```

### 3.6 ToolErrorHandlingMiddleware

**源文件**：`deerflow/agents/middlewares/tool_error_handling_middleware.py`

**作用**：捕获工具执行异常，返回错误消息使 Agent 能继续

**使用钩子**：`wrap_tool_call` / `awrap_tool_call`

```python
# deerflow/agents/middlewares/tool_error_handling_middleware.py:19-65
class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    def _build_error_message(self, request: ToolCallRequest, exc: Exception) -> ToolMessage:
        tool_name = str(request.tool_call.get("name") or "unknown_tool")
        tool_call_id = str(request.tool_call.get("id") or _MISSING_TOOL_CALL_ID)
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 500:
            detail = detail[:497] + "..."

        content = f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. Continue with available context, or choose an alternative tool."
        return ToolMessage(content=content, tool_call_id=tool_call_id, name=tool_name, status="error")

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        try:
            return await handler(request)  # 执行工具
        except GraphBubbleUp:
            raise  # LangGraph 控制流信号不吞掉
        except Exception as exc:
            logger.exception("Tool execution failed (async): ...")
            return self._build_error_message(request, exc)
```

**关键设计**：

1. **GraphBubbleUp 特殊处理**：LangGraph 的 interrupt/pause/resume 控制流信号必须重新抛出，不能被当作普通异常
2. **异常不抛出**：返回错误 ToolMessage，Agent 可以选择其他工具继续执行

**执行流程**：

```
awrap_tool_call(工具调用请求)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ try:                                                      │
│     return await handler(request)  # 执行工具              │
│                                                         │
│ except GraphBubbleUp:                                    │
│     raise  # LangGraph 控制流不吞掉                       │
│                                                         │
│ except Exception as exc:                                  │
│     logger.exception(...)                                │
│     return _build_error_message(request, exc)            │
└─────────────────────────────────────────────────────────────┘
         │
         ├─── 正常执行 ──► 返回 ToolMessage
         ├─── GraphBubbleUp ──► 重新抛出
         └─── 工具异常 ──► 返回错误 ToolMessage
                            Agent 看到: "Error: Tool 'bash' failed...
                            换其他工具继续"
```

### 3.7 TodoMiddleware

**源文件**：`deerflow/agents/middlewares/todo_middleware.py`

**作用**：检测 todo 列表上下文丢失并注入提醒

**使用钩子**：`before_model` / `abefore_model`

```python
# deerflow/agents/middlewares/todo_middleware.py:47-100
class TodoMiddleware(TodoListMiddleware):
    """Extends TodoListMiddleware with `write_todos` context-loss detection."""

    @override
    def before_model(self, state: PlanningState, runtime: Runtime) -> dict[str, Any] | None:
        todos: list[Todo] = state.get("todos") or []
        if not todos:
            return None

        messages = state.get("messages") or []
        if _todos_in_messages(messages):
            # write_todos 仍在上下文可见，无需操作
            return None

        if _reminder_in_messages(messages):
            # 提醒已注入，尚未被截断
            return None

        # Todo 存在于 state 但原始 write_todos 调用已消失
        # 注入提醒 HumanMessage
        formatted = _format_todos(todos)
        reminder = HumanMessage(
            name="todo_reminder",
            content=f"<system_reminder>\nYour todo list from earlier is no longer visible...\n{formatted}\n</system_reminder>",
        )
        return {"messages": [reminder]}
```

**问题场景**：

```
【问题】SummarizationMiddleware 截断消息后：

┌─────────────────────────────────────────┐
│ 早期消息被截断，包含 write_todos 调用    │
│ (超出 context window)                   │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ state.todos 仍然存在                    │
│ 但 LLM 看不到 write_todos 调用          │
│ → LLM 不知道当前 todo 状态              │
└─────────────────────────────────────────┘

【解决方案】检测并注入提醒：

┌─────────────────────────────────────────┐
│ <system_reminder>                       │
│ Your todo list is no longer visible     │
│ but still active:                      │
│ - [pending] Task 1                     │
│ - [in_progress] Task 2                  │
│ Continue tracking and updating...        │
│ </system_reminder>                     │
└─────────────────────────────────────────┘
```

### 3.8 TokenUsageMiddleware

**源文件**：`deerflow/agents/middlewares/token_usage_middleware.py`

**作用**：记录 LLM token 使用量

**使用钩子**：`after_model` / `aafter_model`

```python
# deerflow/agents/middlewares/token_usage_middleware.py:13-37
class TokenUsageMiddleware(AgentMiddleware):
    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._log_usage(state)

    def _log_usage(self, state: AgentState) -> None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        usage = getattr(last, "usage_metadata", None)
        if usage:
            logger.info(
                "LLM token usage: input=%s output=%s total=%s",
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
                usage.get("total_tokens", "?"),
            )
        return None
```

**日志输出示例**：

```
LLM token usage: input=1200 output=450 total=1650
```

### 3.9 TitleMiddleware

**源文件**：`deerflow/agents/middlewares/title_middleware.py`

**作用**：在首次对话交换后自动生成对话标题

**使用钩子**：`after_model` / `aafter_model`

```python
# deerflow/agents/middlewares/title_middleware.py:103-149
class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    def _should_generate_title(self, state: TitleMiddlewareState) -> bool:
        config = get_title_config()
        if not config.enabled:
            return False
        if state.get("title"):
            return False
        messages = state.get("messages", [])
        if len(messages) < 2:
            return False
        user_messages = [m for m in messages if m.type == "human"]
        assistant_messages = [m for m in messages if m.type == "ai"]
        # 首次完整交换后生成标题
        return len(user_messages) == 1 and len(assistant_messages) >= 1

    @override
    def after_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        return self._generate_title_result(state)
```

**生成时机**：

```
消息序列：
[0] HumanMessage: "如何学习 Python？"
[1] AIMessage: "建议从基础开始..."
         │
         ▼
    条件触发：
    - user_messages == 1 ✓
    - assistant_messages >= 1 ✓
    - title 未生成 ✓
         │
         ▼
    调用 LLM 生成标题
         │
         ▼
    state.title = "如何学习 Python"
```

### 3.10 MemoryMiddleware

**源文件**：`deerflow/agents/middlewares/memory_middleware.py`

**作用**：在 Agent 执行后将对话加入记忆队列，供后续摘要

**使用钩子**：`after_agent`

```python
# deerflow/agents/middlewares/memory_middleware.py:86-149
class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState]):
    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        config = get_memory_config()
        if not config.enabled:
            return None

        thread_id = runtime.context.get("thread_id")
        messages = state.get("messages", [])
        filtered_messages = _filter_messages_for_memory(messages)

        # 过滤只保留用户输入和最终助手响应
        queue = get_memory_queue()
        queue.add(thread_id=thread_id, messages=filtered_messages, agent_name=self._agent_name)
        return None
```

**消息过滤规则**：

```
原始消息：
[0] HumanMessage: "你好"
[1] AIMessage(tool_calls=[...])  ← 过滤掉
[2] ToolMessage: {...}          ← 过滤掉
[3] AIMessage: "有什么可以帮助你"  ← 保留
[4] HumanMessage: "帮我写代码"
[5] AIMessage: "好的..."         ← 保留

过滤后：
[0] HumanMessage: "你好"
[3] AIMessage: "有什么可以帮助你"
[4] HumanMessage: "帮我写代码"
[5] AIMessage: "好的..."
```

### 3.11 ViewImageMiddleware

**源文件**：`deerflow/agents/middlewares/view_image_middleware.py`

**作用**：在 view_image 工具完成后注入图片详情消息

**使用钩子**：`before_model` / `abefore_model`

```python
# deerflow/agents/middlewares/view_image_middleware.py:128-187
class ViewImageMiddleware(AgentMiddleware[ViewImageMiddlewareState]):
    def _should_inject_image_message(self, state: ViewImageMiddlewareState) -> bool:
        # 检查最后一条 AIMessage 是否包含 view_image 工具调用
        # 检查所有工具调用是否已完成（有对应 ToolMessage）
        # 检查是否已注入过图片详情消息
        ...

    @override
    def before_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
        if not self._should_inject_image_message(state):
            return None

        # 创建包含 base64 图片数据的消息
        image_content = self._create_image_details_message(state)
        human_msg = HumanMessage(content=image_content)
        return {"messages": [human_msg]}
```

**执行流程**：

```
AIMessage(tool_calls=[{name: "view_image", ...}])
         │
         ▼
    ToolMessage 返回图片数据
         │
         ▼
    ViewImageMiddleware.before_model()
         │
         ▼
    注入 HumanMessage:
    ┌─────────────────────────────────────────┐
    │ Here are the images you've viewed:    │
    │                                         │
    │ - /tmp/screenshot.png (image/png)       │
    │   [base64 图片数据]                    │
    │                                         │
    │ (LLM 现在可以"看到"这些图片)            │
    └─────────────────────────────────────────┘
         │
         ▼
    LLM 可以分析这些图片
```

### 3.12 DeferredToolFilterMiddleware

**源文件**：`deerflow/agents/middlewares/deferred_tool_filter_middleware.py`

**作用**：从 LLM 绑定中过滤掉延迟加载的工具

**使用钩子**：`wrap_model_call` / `awrap_model_call`

```python
# deerflow/agents/middlewares/deferred_tool_filter_middleware.py:31-60
class DeferredToolFilterMiddleware(AgentMiddleware[AgentState]):
    def _filter_tools(self, request: ModelRequest) -> ModelRequest:
        from deerflow.tools.builtins.tool_search import get_deferred_registry

        registry = get_deferred_registry()
        if not registry:
            return request

        deferred_names = {e.name for e in registry.entries}
        active_tools = [t for t in request.tools if getattr(t, "name", None) not in deferred_names]

        if len(active_tools) < len(request.tools):
            logger.debug(f"Filtered {len(request.tools) - len(active_tools)} deferred tool schema(s)")

        return request.override(tools=active_tools)
```

**设计目的**：

```
ToolNode 持有所有工具（含延迟的 MCP 工具）
         │
         ▼
DeferredToolFilterMiddleware 从 request.tools 中过滤掉延迟工具
         │
         ▼
LLM 只看到活跃工具的 schema（节省 context token）
         │
         ▼
用户通过 tool_search 工具在运行时发现延迟工具
```

### 3.13 SubagentLimitMiddleware

**源文件**：`deerflow/agents/middlewares/subagent_limit_middleware.py`

**作用**：限制单次 LLM 响应中的并行 task 工具调用数量

**使用钩子**：`after_model` / `aafter_model`

```python
# deerflow/agents/middlewares/subagent_limit_middleware.py:40-67
class SubagentLimitMiddleware(AgentMiddleware[AgentState]):
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = _clamp_subagent_limit(max_concurrent)

    def _truncate_task_calls(self, state: AgentState) -> dict | None:
        last_msg = messages[-1]
        tool_calls = getattr(last_msg, "tool_calls", None)

        # 统计 task 工具调用数量
        task_indices = [i for i, tc in enumerate(tool_calls) if tc.get("name") == "task"]
        if len(task_indices) <= self.max_concurrent:
            return None

        # 丢弃超限的 task 调用
        indices_to_drop = set(task_indices[self.max_concurrent:])
        truncated_tool_calls = [tc for i, tc in enumerate(tool_calls) if i not in indices_to_drop]

        logger.warning(f"Truncated {len(indices_to_drop)} excess task tool call(s)")
        return {"messages": [last_msg.model_copy(update={"tool_calls": truncated_tool_calls})]}
```

**示例**：

```
LLM 生成 5 个 task 工具调用：
[AIMessage(tool_calls=[
    {name: "task", args: {agent: "researcher"}},  ← 保留
    {name: "task", args: {agent: "coder"}},       ← 保留
    {name: "task", args: {agent: "reviewer"}},    ← 保留
    {name: "task", args: {agent: "writer"}},     ← 丢弃
    {name: "task", args: {agent: "tester"}},     ← 丢弃
])]

max_concurrent=3，丢弃最后 2 个
```

### 3.14 LoopDetectionMiddleware

**源文件**：`deerflow/agents/middlewares/loop_detection_middleware.py`

**作用**：检测并打破重复工具调用循环

**使用钩子**：`after_model` / `aafter_model`

```python
# deerflow/agents/middlewares/loop_detection_middleware.py:117-217
class LoopDetectionMiddleware(AgentMiddleware[AgentState]):
    def __init__(self, warn_threshold=3, hard_limit=5, window_size=20, max_tracked_threads=100):
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        ...

    def _track_and_check(self, state: AgentState, runtime: Runtime) -> tuple[str | None, bool]:
        call_hash = _hash_tool_calls(tool_calls)

        # 跟踪哈希，检测循环
        count = history.count(call_hash)

        if count >= self.hard_limit:
            return _HARD_STOP_MSG, True  # 强制停止

        if count >= self.warn_threshold:
            return _WARNING_MSG, False   # 注入警告

        return None, False
```

**检测策略**：

```
1. 对工具调用（name + args）计算哈希
2. 在滑动窗口中跟踪历史哈希
3. 阈值触发：
   - warn_threshold=3: 注入警告消息
   - hard_limit=5: 剥离所有 tool_calls，强制输出文本
```

**WARNING 消息**：

```
[LOOP DETECTED] You are repeating the same tool calls. 
Stop calling tools and produce your final answer now.
```

**HARD STOP 消息**：

```
[FORCED STOP] Repeated tool calls exceeded the safety limit. 
Producing final answer with results collected so far.
```

### 3.15 ClarificationMiddleware

**源文件**：`deerflow/agents/middlewares/clarification_middleware.py`

**作用**：拦截 `ask_clarification` 工具调用，中断执行向用户提问

**使用钩子**：`wrap_tool_call` / `awrap_tool_call`

```python
# deerflow/agents/middlewares/clarification_middleware.py:131-173
class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        if request.tool_call.get("name") != "ask_clarification":
            return handler(request)

        return self._handle_clarification(request)

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        args = request.tool_call.get("args", {})
        formatted_message = self._format_clarification_message(args)

        return Command(
            update={"messages": [ToolMessage(content=formatted_message, ...)]},
            goto=END,  # 中断执行
        )
```

**执行流程**：

```
LLM 调用 ask_clarification 工具
         │
         ▼
ClarificationMiddleware 拦截
         │
         ▼
┌─────────────────────────────────────────┐
│ 格式化澄清消息                          │
│                                         │
│ 🤔 你的需求有点模糊：                    │
│    请选择：                             │
│    1. Option A                         │
│    2. Option B                         │
└─────────────────────────────────────────┘
         │
         ▼
Command(goto=END)  →  中断执行，等待用户响应
```

**为什么是最后一个中间件**：

注释说明：
> ClarificationMiddleware should always be last

因为它需要在所有其他处理完成后（包括 ToolErrorHandlingMiddleware），最后拦截 ask_clarification 工具调用。

## 4. 完整执行时序图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        LangGraph Agent Loop                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   用户消息 + 上传文件                                                    │
│         │                                                               │
│         ▼                                                               │
│   ═══════════════════════════════════════════════════════════════════   │
│   before_agent 阶段（按数组顺序进入）                                   │
│   ═══════════════════════════════════════════════════════════════════   │
│                                                                         │
│   [0] ThreadDataMiddleware.before_agent()                               │
│        → 准备 thread_data 路径信息                                       │
│        → state.thread_data = {workspace_path, uploads_path, ...}      │
│                          │                                               │
│                          ▼                                               │
│   [1] UploadsMiddleware.before_agent()                                  │
│        → 注入 <uploaded_files> 块到用户消息                              │
│        → state.messages 更新                                            │
│                          │                                               │
│                          ▼                                               │
│   [2] SandboxMiddleware.before_agent()                                  │
│        → lazy_init=True: 跳过（延迟到工具调用）                          │
│        → lazy_init=False: 获取沙箱                                       │
│        → state.sandbox = {sandbox_id}                                  │
│                                                                         │
│   ═══════════════════════════════════════════════════════════════════   │
│   Model 调用阶段                                                        │
│   ═══════════════════════════════════════════════════════════════════   │
│                                                                         │
│   [3] DanglingToolCallMiddleware.awrap_model_call()                     │
│        → 修复悬空的 tool_calls（用户中断导致）                            │
│                          │                                               │
│                          ▼                                               │
│   [6] TodoMiddleware.abefore_model() ← (条件启用)                      │
│        → 检测 todo 上下文丢失，注入提醒                                  │
│                          │                                               │
│                          ▼                                               │
│   [11] ViewImageMiddleware.abefore_model() ← (条件启用)                │
│        → 检测 view_image 完成，注入图片详情消息                          │
│                          │                                               │
│                          ▼                                               │
│   [12] DeferredToolFilterMiddleware.awrap_model_call() ← (条件启用)    │
│        → 过滤延迟工具的 schema，不发给 LLM                              │
│                          │                                               │
│                          ▼                                               │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                      Model (LLM)                                │   │
│   │   → 分析上下文 + 上传文件 + todos + 图片 + 工具列表              │   │
│   │   → 生成最终响应 或 工具调用                                     │   │
│   └────────────────────────────────────────────────────────────────┘   │
│                          │                                               │
│   ═══════════════════════════════════════════════════════════════════   │
│   after_model 阶段（逆序退出）                                          │
│   ═══════════════════════════════════════════════════════════════════   │
│                                                                         │
│   [14] LoopDetectionMiddleware.after_model()                            │
│        → 检测循环，warn_threshold=3 注入警告                            │
│        → hard_limit=5 强制剥离 tool_calls                              │
│                          │                                               │
│                          ▼                                               │
│   [13] SubagentLimitMiddleware.after_model() ← (条件启用)               │
│        → 限制 task 工具调用数量（默认 max=3）                            │
│                          │                                               │
│                          ▼                                               │
│   [8] TokenUsageMiddleware.after_model() ← (条件启用)                  │
│        → 记录 token 使用量日志                                          │
│                          │                                               │
│                          ▼                                               │
│   [9] TitleMiddleware.after_model()                                     │
│        → 首次交换后生成对话标题                                          │
│                                                                         │
│   ═══════════════════════════════════════════════════════════════════   │
│   工具调用阶段（awrap_tool_call）                                        │
│   ═══════════════════════════════════════════════════════════════════   │
│                                                                         │
│   LLM 生成工具调用 ─────────────────────────────────────────────────   │
│                          │                                               │
│                          ▼                                               │
│   [4] GuardrailMiddleware.awrap_tool_call() ← (条件启用)              │
│        → 安全审查，allow=False → 错误 ToolMessage                       │
│                          │                                               │
│                          ▼                                               │
│   [5] ToolErrorHandlingMiddleware.awrap_tool_call()                    │
│        → 捕获异常 → 错误 ToolMessage 让 Agent 继续                      │
│                          │                                               │
│                          ▼                                               │
│   [15] ClarificationMiddleware.awrap_tool_call()                        │
│        → 拦截 ask_clarification → Command(goto=END) 中断                │
│                                                                         │
│   ═══════════════════════════════════════════════════════════════════   │
│   after_agent 阶段                                                     │
│   ═══════════════════════════════════════════════════════════════════   │
│                                                                         │
│   [2] SandboxMiddleware.after_agent()                                   │
│        → release(sandbox_id)                                            │
│                          │                                               │
│                          ▼                                               │
│   [10] MemoryMiddleware.after_agent() ← (条件启用)                     │
│        → 将对话加入记忆队列                                             │
│                          │                                               │
│                          ▼                                               │
│   Agent 继续下一轮循环或返回最终响应                                      │
                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## 5. 中间件数据流

### 5.1 状态更新机制

```
before_agent 返回 dict ──► 合并到 AgentState ──► 传递给下一个中间件

示例:
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  ThreadDataMiddleware.before_agent() 返回:                    │
│    {"thread_data": {"workspace_path": "...", ...}}           │
│                                                              │
│  UploadsMiddleware.before_agent() 返回:                      │
│    {"uploaded_files": [...], "messages": [...]}              │
│                                                              │
│  SandboxMiddleware.before_agent() 返回:                      │
│    {"sandbox": {"sandbox_id": "sb-xxx"}}                    │
│                                                              │
│  最终 state 合并:                                            │
│    {                                                          │
│      "thread_data": {...},                                   │
│      "messages": [...],                                      │
│      "sandbox": {...},                                      │
│      ...                                                    │
│    }                                                        │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 中间件与 ToolNode 关系

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ToolNode 执行工具                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ToolNode 接收到 ToolCallRequest                                      │
│         │                                                               │
│         ▼                                                               │
│   ┌──────────────────────────────────────────────────────────────────┐ │
│   │ [0] ThreadDataMiddleware                                          │ │
│   │     (不处理工具调用，直接传递)                                    │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│         │                                                               │
│         ▼                                                               │
│   ┌──────────────────────────────────────────────────────────────────┐ │
│   │ [1] UploadsMiddleware                                            │ │
│   │     (不处理工具调用，直接传递)                                    │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│         │                                                               │
│         ▼                                                               │
│   ┌──────────────────────────────────────────────────────────────────┐ │
│   │ [2] SandboxMiddleware (懒加载时此时才获取沙箱)                    │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│         │                                                               │
│         ▼                                                               │
│   ┌──────────────────────────────────────────────────────────────────┐ │
│   │ [3] DanglingToolCallMiddleware                                   │ │
│   │     (不处理工具调用，直接传递)                                    │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│         │                                                               │
│         ▼                                                               │
│   ┌──────────────────────────────────────────────────────────────────┐ │
│   │ [4] GuardrailMiddleware (如果启用)                               │ │
│   │     → 审查 allow? → True: 继续，False: 返回错误                   │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│         │                                                               │
│         ▼                                                               │
│   ┌──────────────────────────────────────────────────────────────────┐ │
│   │ [5] ToolErrorHandlingMiddleware                                  │ │
│   │     → try/except 捕获异常                                          │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│         │                                                               │
│         ▼                                                               │
│   ┌──────────────────────────────────────────────────────────────────┐ │
│   │ [15] ClarificationMiddleware (最后一个)                          │ │
│   │     → 拦截 ask_clarification → Command(goto=END)                 │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│         │                                                               │
│         ▼                                                               │
│   ┌──────────────────────────────────────────────────────────────────┐ │
│   │                    实际工具执行                                    │ │
│   └──────────────────────────────────────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## 6. 配置与启用

### 6.1 config.yaml 中的相关配置

```yaml
# guardrails 配置（默认禁用）
guardrails:
  enabled: false
  fail_closed: true
  # provider:
  #   use: deerflow.guardrails.builtin:AllowlistProvider
  #   config:
  #     denied_tools: ["bash", "write_file"]

# sandbox 配置（默认启用 LocalSandboxProvider）
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider

# memory 配置
memory:
  enabled: false

# summarization 配置
summarization:
  enabled: false

# title 配置
title:
  enabled: false
```

### 6.2 中间件启用条件

| 索引 | 中间件 | 始终启用 | 启用条件 |
|-----|--------|---------|---------|
| 0 | ThreadDataMiddleware | ✅ | - |
| 1 | UploadsMiddleware | ✅ | - |
| 2 | SandboxMiddleware | ✅ | - |
| 3 | DanglingToolCallMiddleware | ✅ | - |
| 4 | GuardrailMiddleware | ❌ | `config.guardrails.enabled=true` |
| 5 | ToolErrorHandlingMiddleware | ✅ | - |
| 6 | SummarizationMiddleware | ❌ | `config.summarization.enabled=true` |
| 7 | TodoMiddleware | ❌ | `config.is_plan_mode=true` |
| 8 | TokenUsageMiddleware | ❌ | `config.token_usage.enabled=true` |
| 9 | TitleMiddleware | ✅ | - |
| 10 | MemoryMiddleware | ❌ | `config.memory.enabled=true` |
| 11 | ViewImageMiddleware | ❌ | `model.supports_vision=true` |
| 12 | DeferredToolFilterMiddleware | ❌ | `config.tool_search.enabled=true` |
| 13 | SubagentLimitMiddleware | ❌ | `config.subagent_enabled=true` |
| 14 | LoopDetectionMiddleware | ✅ | - |
| 15 | ClarificationMiddleware | ✅ | - |

### 6.3 config.yaml 完整配置示例

```yaml
# config.yaml

# Guardrails - 工具调用安全审查
guardrails:
  enabled: false
  fail_closed: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: ["bash"]

# Summarization - 消息摘要压缩
summarization:
  enabled: false
  trigger_threshold: 20
  max_tokens: 2000

# Title - 对话标题生成
title:
  enabled: false
  model_name: xxx
  prompt_template: "..."
  max_words: 5
  max_chars: 50

# Memory - 记忆机制
memory:
  enabled: false

# Tool Search - 延迟工具加载
tool_search:
  enabled: false
```

### 6.4 运行时配置

部分中间件通过 `RunnableConfig` 动态启用：

```python
config = {
    "configurable": {
        "is_plan_mode": False,         # TodoMiddleware
        "subagent_enabled": False,     # SubagentLimitMiddleware
        "max_concurrent_subagents": 3, # SubagentLimitMiddleware
        "thinking_enabled": True,       # 模型思考
        "model_name": "xxx",           # 模型名称
    }
}
``` |

## 7. 关键设计决策

### 7.1 懒加载策略

ThreadDataMiddleware 和 SandboxMiddleware 默认使用 `lazy_init=True`：

- **优点**：快速启动，目录/沙箱按需创建
- **缺点**：第一次工具调用略有延迟

### 7.2 异常处理策略

ToolErrorHandlingMiddleware 选择**吞掉异常返回错误消息**而不是抛出：
- Agent 可以选择其他工具继续执行
- 不会因为单个工具失败导致整个 run 中断

### 7.3 DanglingToolCallMiddleware 使用 wrap_model_call

选择 `wrap_model_call` 而不是 `before_model`：
- `before_model` + reducer 会把补丁追加到消息列表末尾
- `wrap_model_call` 可以把补丁插入到**正确的位置**（悬空的 AIMessage 之后）

### 7.4 GuardrailMiddleware 的 fail_closed

```python
if self.fail_closed:
    decision = GuardrailDecision(allow=False, reasons=[...])
else:
    return await handler(request)
```

- **fail_closed=True（默认）**：Provider 出错默认拒绝
- **fail_closed=False**：Provider 出错时放行（带警告日志）

### 7.5 ClarificationMiddleware 必须是最后一个

```python
# 注释明确说明顺序要求
# ClarificationMiddleware should always be last
middlewares.append(ClarificationMiddleware())
```

原因：
1. 其他中间件可能修改消息或状态
2. ClarificationMiddleware 需要看到最终的 `ask_clarification` 调用
3. 它返回 `Command(goto=END)` 中断执行，必须最后处理

### 7.6 为什么用 HumanMessage 而不是 SystemMessage 注入循环警告？

```python
# LoopDetectionMiddleware 中注入警告的方式
return {"messages": [HumanMessage(content=warning)]}
```

原因：
> Anthropic models require system messages only at the start of the conversation; injecting one mid-conversation crashes langchain_anthropic's `_format_messages()`. HumanMessage works with all providers.

使用 `HumanMessage` 兼容性更好。

### 7.7 MemoryMiddleware 为什么在 after_agent 而不是在 after_model？

```python
class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState]):
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        # 将对话加入记忆队列
        queue.add(thread_id=thread_id, messages=filtered_messages, agent_name=self._agent_name)
        return None
```

原因：
1. `after_model` 只看到单个 turn 的结果
2. `after_agent` 看到完整的 agent 执行结果（包括所有工具调用）
3. 需要完整的上下文来生成有意义的记忆摘要

### 7.8 ViewImageMiddleware 为什么在 before_model 注入消息？

```python
@override
def before_model(self, state: ViewImageMiddlewareState, runtime: Runtime) -> dict | None:
    # 在 LLM 调用前注入图片详情
    return {"messages": [human_msg]}
```

原因：
1. 需要在 LLM 看到图片内容后才能分析
2. view_image 工具完成后的 ToolMessage 已经在消息历史中
3. 注入 HumanMessage 让 LLM 主动分析图片

### 7.9 循环检测使用哈希而不是精确匹配

```python
def _hash_tool_calls(tool_calls: list[dict]) -> str:
    # 排序确保顺序无关
    normalized.sort(key=lambda tc: (tc["name"], json.dumps(tc["args"], sort_keys=True)))
    blob = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()[:12]
```

原因：
1. 相同工具调用以不同顺序执行应被视为同一循环
2. 截断 context window 后消息顺序可能变化
3. 哈希碰撞概率低（12字符 MD5）

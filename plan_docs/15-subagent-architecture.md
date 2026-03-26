# Subagent 架构文档

## 目录

1. [概述](#1-概述)
2. [核心组件与源码位置](#2-核心组件与源码位置)
3. [Subagent的创建过程](#3-subagent的创建过程)
4. [Subagent的使用方式](#4-subagent的使用方式)
5. [执行流程详解](#5-执行流程详解)
6. [Subagent的协作机制](#6-subagent的协作机制)
7. [Subagent生命周期](#7-subagent生命周期)
8. [Subagent解决的问题与好处](#8-subagent解决的问题与好处)

---

## 1. 概述

Subagent（子代理）系统是DeerFlow中用于将复杂任务委托给专门化agent执行的机制。当lead agent（主代理）调用`task`工具时，系统会创建一个独立的SubagentExecutor来执行任务，该任务在后台线程池中运行，并通过流式事件将进度返回给前端。

### 1.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    DeerFlow Backend                                       │
│                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │                              Lead Agent (主代理)                                    │   │
│  │                                                                                   │   │
│  │  ┌─────────────────────────────────────────────────────────────────────────────┐│   │
│  │  │                         Middleware Chain                                     ││   │
│  │  │  ... → SubagentLimitMiddleware → LoopDetectionMiddleware → Clarification...  ││   │
│  │  └─────────────────────────────────────────────────────────────────────────────┘│   │
│  │                                                                                   │   │
│  │  ┌──────────────────┐                                                            │   │
│  │  │  task_tool       │ ────────────────────────────────────────────────────────┐ │   │
│  │  │  (tool="task")   │                                                             │ │   │
│  │  └──────────────────┘                                                             │ │   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                              │                                           │
│                                              │ 调用 task_tool                             │
│                                              ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │                           Subagent System                                         │   │
│  │                                                                                   │   │
│  │  ┌─────────────────────────────────────────────────────────────────────────────┐│   │
│  │  │                     task_tool.py (第60-195行)                                ││   │
│  │  │                                                                             ││   │
│  │  │  1. get_subagent_config(subagent_type)     → 获取配置                        ││   │
│  │  │  2. get_available_tools(subagent_enabled=False)  → 过滤工具                  ││   │
│  │  │  3. SubagentExecutor(...)              → 创建执行器                        ││   │
│  │  │  4. executor.execute_async(prompt, task_id=tool_call_id)  → 启动后台执行   ││   │
│  │  │  5. while True: get_background_task_result() + 5s轮询  → 等待完成          ││   │
│  │  │  6. writer({"type": "task_started|running|completed", ...})  → 流式事件   ││   │
│  │  └─────────────────────────────────────────────────────────────────────────────┘│   │
│  │                                              │                                     │   │
│  │                                              │ execute_async()                    │   │
│  │                                              ▼                                     │   │
│  │  ┌─────────────────────────────────────────────────────────────────────────────┐│   │
│  │  │                 executor.py:391-453  execute_async()                         ││   │
│  │  │                                                                             ││   │
│  │  │   _background_tasks[task_id] = SubagentResult(PENDING)                       ││   │
│  │  │                                              │                               ││   │
│  │  │                                              ▼                               ││   │
│  │  │   _scheduler_pool.submit(run_task)  ──────────────────────────────────────┐ │   │
│  │  │                                                                     │       │ │   │
│  │  │   run_task():                                                  │       │       │ │   │
│  │  │     status → RUNNING                                         │       │       │ │   │
│  │  │     _execution_pool.submit(execute, task, result_holder)      │       │       │ │   │
│  │  │                                                             ▼       │       │ │   │
│  │  │   execute() (同步包装)                                       execute()        │ │   │
│  │  │     asyncio.run(_aexecute())  ←──────────────────────────── _aexecute()      │ │   │
│  │  │                                                             │                │ │   │
│  │  │                                                             ▼                │ │   │
│  │  │   ┌───────────────────────────────────────────────────────────────────────┐│   │   │
│  │  │   │                    _aexecute() (异步核心)                               ││   │   │
│  │  │   │                                                                       ││   │   │
│  │  │   │   agent = _create_agent()                                             ││   │   │
│  │  │   │   state = _build_initial_state(task)                                   ││   │   │
│  │  │   │   async for chunk in agent.astream(state, stream_mode="values"):      ││   │   │
│  │  │   │       # 捕获 AI messages                                              ││   │   │
│  │  │   │       result.ai_messages.append(...)                                  ││   │   │
│  │  │   │   result.result = last_ai_message.content                              ││   │   │
│  │  │   └───────────────────────────────────────────────────────────────────────┘│   │   │
│  │  └─────────────────────────────────────────────────────────────────────────────┘│   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│  │                 Global State (executor.py:66-75)                                 │   │
│  │                                                                                  │   │
│  │   _background_tasks: dict[str, SubagentResult]  ← 全局后台任务存储               │   │
│  │   _background_tasks_lock: threading.Lock    ← 线程安全锁                          │   │
│  │   _scheduler_pool: ThreadPoolExecutor(3)   ← 调度线程池                         │   │
│  │   _execution_pool: ThreadPoolExecutor(3)   ← 执行线程池                         │   │
│  └─────────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 关键设计决策

| 决策 | 说明 | 源码位置 |
|------|------|---------|
| `tool_call_id`作为`task_id` | 便于追踪，将subagent状态关联到原始tool call | `task_tool.py:117` |
| 双线程池 | 调度(execution分离，scheduler可快速响应，execution支持超时 | `executor.py:71,75` |
| `asyncio.run()`在线程池执行 | ThreadPoolExecutor没有event loop，但MCP工具是async | `executor.py:374` |
| 后台执行+轮询 | 避免阻塞LLM响应，允许实时流式事件 | `task_tool.py:132-195` |
| Subagent不包含task工具 | `subagent_enabled=False`防止递归嵌套 | `task_tool.py:102` |

---

## 2. 核心组件与源码位置

| 组件 | 文件路径 | 关键行号 | 职责 |
|------|---------|---------|------|
| `task_tool` | `tools/builtins/task_tool.py` | 21-195 | 调用入口，轮询等待 |
| `SubagentExecutor` | `subagents/executor.py` | 123-453 | 执行引擎 |
| `SubagentConfig` | `subagents/config.py` | 6-28 | 配置数据结构 |
| `SubagentResult` | `subagents/executor.py` | 36-63 | 结果数据结构 |
| `SubagentStatus` | `subagents/executor.py` | 26-33 | 状态枚举 |
| `SubagentLimitMiddleware` | `agents/middlewares/subagent_limit_middleware.py` | 24-75 | 并发限制 |
| `build_subagent_runtime_middlewares` | `agents/middlewares/tool_error_handling_middleware.py` | 131-137 | subagent中间件构建 |
| `BUILTIN_SUBAGENTS` | `subagents/builtins/__init__.py` | 12-15 | 内置注册表 |
| `get_available_tools` | `tools/tools.py` | 23-114 | 工具获取（含subagent_enabled控制）|

---

## 3. Subagent的创建过程

### 3.1 入口：task_tool

**源码：`tools/builtins/task_tool.py:21-117`**

```python
@tool("task", parse_docstring=True)
def task_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    prompt: str,
    subagent_type: Literal["general-purpose", "bash"],
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_turns: int | None = None,
) -> str:
    # 第61行：获取subagent配置
    config = get_subagent_config(subagent_type)
    if config is None:
        return f"Error: Unknown subagent type '{subagent_type}'. Available: general-purpose, bash"

    # 第68-76行：应用配置覆盖（如skills、max_turns）
    overrides: dict = {}
    skills_section = get_skills_prompt_section()
    if skills_section:
        overrides["system_prompt"] = config.system_prompt + "\n\n" + skills_section
    if max_turns is not None:
        overrides["max_turns"] = max_turns
    if overrides:
        config = replace(config, **overrides)

    # 第78-95行：从runtime提取parent上下文
    sandbox_state = None
    thread_data = None
    thread_id = None
    parent_model = None
    trace_id = None
    if runtime is not None:
        sandbox_state = runtime.state.get("sandbox")
        thread_data = runtime.state.get("thread_data")
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        metadata = runtime.config.get("metadata", {})
        parent_model = metadata.get("model_name")
        trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]

    # 第102行：获取工具（subagent_enabled=False，不包含task_tool）
    tools = get_available_tools(model_name=parent_model, subagent_enabled=False)

    # 第105-113行：创建SubagentExecutor
    executor = SubagentExecutor(
        config=config,
        tools=tools,
        parent_model=parent_model,
        sandbox_state=sandbox_state,
        thread_data=thread_data,
        thread_id=thread_id,
        trace_id=trace_id,
    )

    # 第117行：启动后台执行，使用tool_call_id作为task_id
    task_id = executor.execute_async(prompt, task_id=tool_call_id)
```

### 3.2 工具可见性控制

**源码：`tools/tools.py:47-52`**

```python
builtin_tools = BUILTIN_TOOLS.copy()

# 只有启用subagent_enabled时，才将task_tool添加到工具列表
if subagent_enabled:
    builtin_tools.extend(SUBAGENT_TOOLS)  # SUBAGENT_TOOLS = [task_tool]
    logger.info("Including subagent tools (task)")
```

**关键点：**
- Lead agent创建时：`subagent_enabled=True` → 可使用`task`工具
- Subagent创建时：`subagent_enabled=False` → **看不到**`task`工具

### 3.3 SubagentExecutor初始化

**源码：`subagents/executor.py:126-162`**

```python
class SubagentExecutor:
    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        parent_model: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
    ):
        self.config = config
        self.parent_model = parent_model
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.thread_id = thread_id
        # 如果没有传入trace_id，则生成一个8位UUID
        self.trace_id = trace_id or str(uuid.uuid4())[:8]

        # 根据config过滤工具
        self.tools = _filter_tools(
            tools,
            config.tools,           # allowed list（None表示全部）
            config.disallowed_tools, # deny list（默认["task"]）
        )

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")
```

### 3.4 工具过滤逻辑

**源码：`executor.py:78-105`**

```python
def _filter_tools(
    all_tools: list[BaseTool],
    allowed: list[str] | None,
    disallowed: list[str] | None,
) -> list[BaseTool]:
    filtered = all_tools

    # 如果指定了allowed list，只包含列表中的工具
    if allowed is not None:
        allowed_set = set(allowed)
        filtered = [t for t in filtered if t.name in allowed_set]

    # 应用deny list，排除指定的工具
    if disallowed is not None:
        disallowed_set = set(disallowed)
        filtered = [t for t in filtered if t.name not in disallowed_set]

    return filtered
```

### 3.5 创建Agent实例

**源码：`executor.py:164-180`**

```python
def _create_agent(self):
    """创建agent实例"""
    # 解析模型名称（inherit表示使用parent的模型）
    model_name = _get_model_name(self.config, self.parent_model)
    model = create_chat_model(name=model_name, thinking_enabled=False)

    # 复用lead agent的运行时中间件
    from deerflow.agents.middlewares.tool_error_handling_middleware import (
        build_subagent_runtime_middlewares
    )
    middlewares = build_subagent_runtime_middlewares(lazy_init=True)

    return create_agent(
        model=model,
        tools=self.tools,
        middleware=middlewares,
        system_prompt=self.config.system_prompt,
        state_schema=ThreadState,
    )
```

---

## 4. Subagent的使用方式

### 4.1 内置Subagent类型

#### 4.1.1 general-purpose

**源码：`subagents/builtins/general_purpose.py:5-47`**

```python
GENERAL_PURPOSE_CONFIG = SubagentConfig(
    name="general-purpose",
    description="""A capable agent for complex, multi-step tasks that require both exploration and action.
    ...省略描述...""",
    system_prompt="""You are a general-purpose subagent working on a delegated task...
    <guidelines>
    - Focus on completing the delegated task efficiently
    - Use available tools as needed to accomplish the goal
    ...
    </guidelines>""",
    tools=None,  # 继承父agent的全部工具
    disallowed_tools=["task", "ask_clarification", "present_files"],  # 防止嵌套
    model="inherit",
    max_turns=50,
)
```

#### 4.1.2 bash

**源码：`subagents/builtins/bash_agent.py:5-46`**

```python
BASH_AGENT_CONFIG = SubagentConfig(
    name="bash",
    description="""Command execution specialist for running bash commands...""",
    system_prompt="""You are a bash command execution specialist...""",
    # 仅允许5个sandbox工具
    tools=["bash", "ls", "read_file", "write_file", "str_replace"],
    disallowed_tools=["task", "ask_clarification", "present_files"],
    model="inherit",
    max_turns=30,  # bash任务通常更快
)
```

### 4.2 配置注册与覆盖

**源码：`subagents/registry.py:12-34`**

```python
def get_subagent_config(name: str) -> SubagentConfig | None:
    # 先从内置注册表获取
    config = BUILTIN_SUBAGENTS.get(name)
    if config is None:
        return None

    # 应用config.yaml中的覆盖（特别是timeout）
    from deerflow.config.subagents_config import get_subagents_app_config
    app_config = get_subagents_app_config()
    effective_timeout = app_config.get_timeout_for(name)
    if effective_timeout != config.timeout_seconds:
        logger.debug(f"Subagent '{name}': timeout overridden by config.yaml ...")
        config = replace(config, timeout_seconds=effective_timeout)

    return config
```

**config.yaml覆盖示例：**

```yaml
subagents:
  timeout_seconds: 900        # 默认超时15分钟
  agents:
    bash:
      timeout_seconds: 300    # bash任务3分钟
```

---

## 5. 执行流程详解

### 5.1 整体流程时序图

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Lead Agent  │    │  task_tool   │    │  Scheduler   │    │  Executor    │
│              │    │              │    │    Pool       │    │    Pool      │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │                   │
       │ 调用task_tool      │                   │                   │
       │──────────────────→│                   │                   │
       │                   │                   │                   │
       │                   │ get_subagent_config()                  │
       │                   │──→ BUILTIN_SUBAGENTS                  │
       │                   │←── SubagentConfig                     │
       │                   │                   │                   │
       │                   │ get_available_tools(subagent_enabled=False)│
       │                   │──→ tools (不含task_tool)              │
       │                   │                   │                   │
       │                   │ SubagentExecutor()                    │
       │                   │                   │                   │
       │                   │ execute_async(prompt, task_id=tool_call_id)
       │                   │──────────────────→│                   │
       │                   │                   │                   │
       │                   │  _background_tasks[task_id] = PENDING │
       │                   │                   │                   │
       │                   │  _scheduler_pool.submit(run_task)     │
       │                   │                   │                   │
       │                   │                   │  run_task():     │
       │                   │                   │    status=RUNNING│
       │                   │                   │─────────────────→│
       │                   │                   │                   │
       │                   │                   │  _execution_pool │
       │                   │                   │  .submit(execute)│
       │                   │                   │                   │
       │                   │                   │                   │ asyncio.run
       │                   │                   │                   │ (_aexecute)
       │                   │                   │                   │
       │                   │                   │                   │ agent.astream()
       │                   │                   │                   │ 捕获AI messages
       │                   │                   │                   │
       │                   │  get_background_   │                   │
       │ 5s轮询←───────────│  task_result()    │                   │
       │                   │──────────────────→│                   │
       │                   │                   │  status=RUNNING  │
       │                   │                   │←──────────────────│
       │                   │                   │                   │
       │                   │                   │                   │ COMPLETED/
       │                   │                   │                   │ FAILED/
       │                   │                   │                   │ TIMED_OUT
       │                   │                   │                   │
       │  返回结果          │                   │                   │
       │←──────────────────│                   │                   │
       │                   │                   │                   │
```

### 5.2 后台执行：execute_async

**源码：`subagents/executor.py:391-453`**

```python
def execute_async(self, task: str, task_id: str | None = None) -> str:
    # 使用tool_call_id作为task_id，便于追踪
    if task_id is None:
        task_id = str(uuid.uuid4())[:8]

    # 创建PENDING状态的result
    result = SubagentResult(
        task_id=task_id,
        trace_id=self.trace_id,
        status=SubagentStatus.PENDING,
    )

    # 存入全局_background_tasks字典
    with _background_tasks_lock:
        _background_tasks[task_id] = result

    # 提交到scheduler pool
    def run_task():
        with _background_tasks_lock:
            _background_tasks[task_id].status = SubagentStatus.RUNNING
            _background_tasks[task_id].started_at = datetime.now()
            result_holder = _background_tasks[task_id]

        try:
            # 提交到execution pool执行，带超时
            execution_future: Future = _execution_pool.submit(
                self.execute, task, result_holder
            )
            try:
                # 等待执行结果（带超时）
                exec_result = execution_future.result(
                    timeout=self.config.timeout_seconds
                )
                # 更新结果到全局字典
                with _background_tasks_lock:
                    _background_tasks[task_id].status = exec_result.status
                    _background_tasks[task_id].result = exec_result.result
                    _background_tasks[task_id].error = exec_result.error
                    _background_tasks[task_id].completed_at = datetime.now()
                    _background_tasks[task_id].ai_messages = exec_result.ai_messages
            except FuturesTimeoutError:
                # 处理超时
                with _background_tasks_lock:
                    _background_tasks[task_id].status = SubagentStatus.TIMED_OUT
                    _background_tasks[task_id].error = f"Execution timed out after {self.config.timeout_seconds} seconds"
                    _background_tasks[task_id].completed_at = datetime.now()
                execution_future.cancel()
        except Exception as e:
            with _background_tasks_lock:
                _background_tasks[task_id].status = SubagentStatus.FAILED
                _background_tasks[task_id].error = str(e)
                _background_tasks[task_id].completed_at = datetime.now()

    _scheduler_pool.submit(run_task)
    return task_id
```

### 5.3 同步执行包装

**源码：`executor.py:351-389`**

```python
def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
    """同步执行包装器"""
    # 在线程池中运行asyncio.run()来执行异步代码
    # 原因：
    # 1. MCP工具是async-only的
    # 2. ThreadPoolExecutor没有event loop
    try:
        return asyncio.run(self._aexecute(task, result_holder))
    except Exception as e:
        logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed")
        # 处理asyncio.run()失败的情况（如已在async上下文中）
        ...
```

### 5.4 异步执行核心：_aexecute

**源码：`executor.py:203-349`**

```python
async def _aexecute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
    if result_holder is not None:
        result = result_holder
    else:
        task_id = str(uuid.uuid4())[:8]
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )

    try:
        # 创建agent和初始状态
        agent = self._create_agent()
        state = self._build_initial_state(task)

        # 构建运行配置
        run_config: RunnableConfig = {
            "recursion_limit": self.config.max_turns,  # 最大轮次
        }
        context = {}
        if self.thread_id:
            run_config["configurable"] = {"thread_id": self.thread_id}
            context["thread_id"] = self.thread_id

        # 使用astream进行流式执行，捕获每个AI消息
        final_state = None
        async for chunk in agent.astream(
            state, config=run_config, context=context, stream_mode="values"
        ):
            final_state = chunk
            messages = chunk.get("messages", [])
            if messages:
                last_message = messages[-1]
                if isinstance(last_message, AIMessage):
                    message_dict = last_message.model_dump()
                    # 去重检查
                    message_id = message_dict.get("id")
                    is_duplicate = False
                    if message_id:
                        is_duplicate = any(
                            msg.get("id") == message_id for msg in result.ai_messages
                        )
                    else:
                        is_duplicate = message_dict in result.ai_messages

                    if not is_duplicate:
                        result.ai_messages.append(message_dict)

        # 从final_state提取最终结果
        if final_state is None:
            result.result = "No response generated"
        else:
            messages = final_state.get("messages", [])
            # 找到最后一个AIMessage
            last_ai_message = None
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    last_ai_message = msg
                    break

            if last_ai_message is not None:
                content = last_ai_message.content
                # 处理str或list类型的content
                if isinstance(content, str):
                    result.result = content
                elif isinstance(content, list):
                    # 从content blocks提取text
                    text_parts = []
                    pending_str_parts = []
                    for block in content:
                        if isinstance(block, str):
                            pending_str_parts.append(block)
                        elif isinstance(block, dict):
                            if pending_str_parts:
                                text_parts.append("".join(pending_str_parts))
                                pending_str_parts.clear()
                            text_val = block.get("text")
                            if isinstance(text_val, str):
                                text_parts.append(text_val)
                    if pending_str_parts:
                        text_parts.append("".join(pending_str_parts))
                    result.result = "\n".join(text_parts) if text_parts else "No text content"
                else:
                    result.result = str(content)

        result.status = SubagentStatus.COMPLETED
        result.completed_at = datetime.now()

    except Exception as e:
        logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
        result.status = SubagentStatus.FAILED
        result.error = str(e)
        result.completed_at = datetime.now()

    return result
```

### 5.5 task_tool的轮询等待

**源码：`task_tool.py:128-195`**

```python
writer = get_stream_writer()
# 发送任务开始事件
writer({"type": "task_started", "task_id": task_id, "description": description})

while True:
    # 从全局_background_tasks获取当前状态
    result = get_background_task_result(task_id)

    if result is None:
        writer({"type": "task_failed", "task_id": task_id, "error": "Task disappeared"})
        cleanup_background_task(task_id)
        return f"Error: Task {task_id} disappeared from background tasks"

    # 检测新AI消息，发送task_running事件
    current_message_count = len(result.ai_messages)
    if current_message_count > last_message_count:
        for i in range(last_message_count, current_message_count):
            writer({
                "type": "task_running",
                "task_id": task_id,
                "message": result.ai_messages[i],
                "message_index": i + 1,
                "total_messages": current_message_count,
            })
        last_message_count = current_message_count

    # 检查最终状态
    if result.status == SubagentStatus.COMPLETED:
        writer({"type": "task_completed", "task_id": task_id, "result": result.result})
        cleanup_background_task(task_id)
        return f"Task Succeeded. Result: {result.result}"
    elif result.status == SubagentStatus.FAILED:
        writer({"type": "task_failed", "task_id": task_id, "error": result.error})
        cleanup_background_task(task_id)
        return f"Task failed. Error: {result.error}"
    elif result.status == SubagentStatus.TIMED_OUT:
        writer({"type": "task_timed_out", "task_id": task_id, "error": result.error})
        cleanup_background_task(task_id)
        return f"Task timed out. Error: {result.error}"

    # 还在运行，5秒后继续轮询
    time.sleep(5)
    poll_count += 1

    # 安全网：超过最大轮询次数也返回超时
    if poll_count > max_poll_count:
        writer({"type": "task_timed_out", "task_id": task_id})
        return f"Task polling timed out after {timeout_minutes} minutes..."
```

### 5.6 双线程池设计

**源码：`executor.py:70-75`**

```python
# 全局调度线程池：负责接收任务、状态更新、快速响应
_scheduler_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-scheduler-")

# 全局执行线程池：负责实际subagent执行，支持超时控制
_execution_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-exec-")
```

| 线程池 | 职责 | 特点 |
|--------|------|------|
| `_scheduler_pool` | 接收任务、更新状态 | 3 workers，快速响应，不阻塞 |
| `_execution_pool` | 执行agent.astream() | 3 workers，支持超时 |

**设计原因：**
1. 调度和执行分离，避免相互阻塞
2. `asyncio.run()`在ThreadPoolExecutor中需要新event loop
3. 超时控制在execution_pool层面实现

---

## 6. Subagent的协作机制

### 6.1 与Lead Agent的状态共享

**源码：`executor.py:182-201`**

```python
def _build_initial_state(self, task: str) -> dict[str, Any]:
    """构建agent执行的初始状态"""
    state: dict[str, Any] = {
        "messages": [HumanMessage(content=task)],  # 只有task作为初始消息
    }

    # 从parent传递sandbox和thread数据
    if self.sandbox_state is not None:
        state["sandbox"] = self.sandbox_state
    if self.thread_data is not None:
        state["thread_data"] = self.thread_data

    return state
```

### 6.2 分布式追踪

通过`trace_id`将lead agent和subagent的日志关联：

```python
# task_tool.py:95
trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]

# executor.py:153
self.trace_id = trace_id or str(uuid.uuid4())[:8]

# 日志中使用
logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting...")
```

### 6.3 并发数量限制

**源码：`agents/middlewares/subagent_limit_middleware.py:24-67`**

```python
class SubagentLimitMiddleware(AgentMiddleware[AgentState]):
    """当LLM单次响应生成超过max_concurrent个task调用时，只保留前几个"""

    def _truncate_task_calls(self, state: AgentState) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        # 统计task工具调用
        task_indices = [
            i for i, tc in enumerate(tool_calls)
            if tc.get("name") == "task"
        ]
        if len(task_indices) <= self.max_concurrent:
            return None

        # 截断多余的task调用
        indices_to_drop = set(task_indices[self.max_concurrent:])
        truncated_tool_calls = [
            tc for i, tc in enumerate(tool_calls)
            if i not in indices_to_drop
        ]

        dropped_count = len(indices_to_drop)
        logger.warning(f"Truncated {dropped_count} excess task tool call(s)...")

        updated_msg = last_msg.model_copy(update={"tool_calls": truncated_tool_calls})
        return {"messages": [updated_msg]}
```

**添加到lead agent的时机：**

**源码：`agents/lead_agent/agent.py:254-258`**

```python
# 只有subagent_enabled=True时才添加
subagent_enabled = config.get("configurable", {}).get("subagent_enabled", False)
if subagent_enabled:
    max_concurrent_subagents = config.get("configurable", {}).get("max_concurrent_subagents", 3)
    middlewares.append(SubagentLimitMiddleware(max_concurrent=max_concurrent_subagents))
```

### 6.4 共享中间件

**源码：`tool_error_handling_middleware.py:131-137`**

```python
def build_subagent_runtime_middlewares(*, lazy_init: bool = True):
    """构建subagent专用的运行时中间件"""
    return _build_runtime_middlewares(
        include_uploads=False,        # subagent不处理文件上传
        include_dangling_tool_call_patch=False,
    )
```

Subagent与Lead Agent共享的中间件：
- `ThreadDataMiddleware`
- `SandboxMiddleware`
- `ToolErrorHandlingMiddleware`
- `GuardrailMiddleware`（如果启用）

---

## 7. Subagent生命周期

### 7.1 状态流转图

```
                                    ┌─────────────────┐
                                    │                 │
                                    │  User uploads   │
                                    │  /workspace     │
                                    │                 │
                                    └────────┬────────┘
                                             │
                                             ▼
┌──────────┐      ┌──────────┐      ┌──────────────┐      ┌────────────┐
│ PENDING  │ ───→ │ RUNNING  │ ───→ │  COMPLETED    │      │  FAILED    │
└──────────┘      └──────────┘      └──────────────┘      └────────────┘
     │                │                    │                   │
     │                │                    │                   └──→ (返回错误)
     │                │                    │                      
     │                │                    └──→ cleanup_background_task()
     │                │                              (清理_global_tasks)
     │                │
     │                └──→ TIMED_OUT (超时)
     │                          │
     │                          └──→ (记录超时时长)
     │
     └── task_tool调用
         execute_async()
         
     cleanup_background_task()
     在终态时调用，防止内存泄漏
```

### 7.2 状态定义

**源码：`executor.py:26-33`**

```python
class SubagentStatus(Enum):
    PENDING = "pending"      # 已创建，等待scheduler调度
    RUNNING = "running"      # 正在执行agent.astream()
    COMPLETED = "completed"  # 正常完成
    FAILED = "failed"        # 执行过程中异常
    TIMED_OUT = "timed_out"  # 超过timeout_seconds
```

### 7.3 超时控制

**三层超时保护：**

1. **ThreadPoolExecutor超时**（`executor.py:430`）
   ```python
   execution_future.result(timeout=self.config.timeout_seconds)
   ```
   默认900秒（15分钟）

2. **Polling安全网**（`task_tool.py:191`）
   ```python
   max_poll_count = (config.timeout_seconds + 60) // 5
   if poll_count > max_poll_count:
       return f"Task polling timed out after {timeout_minutes} minutes..."
   ```

3. **Future取消**（`executor.py:443-444`）
   ```python
   execution_future.cancel()  # 尽力取消，不保证成功
   ```

### 7.4 资源清理

**源码：`executor.py:482-516`**

```python
def cleanup_background_task(task_id: str) -> None:
    """从_background_tasks中移除已完成的任务，防止内存泄漏"""
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result is None:
            return

        # 只在终态时清理，避免与后台执行的竞态条件
        is_terminal_status = result.status in {
            SubagentStatus.COMPLETED,
            SubagentStatus.FAILED,
            SubagentStatus.TIMED_OUT,
        }
        if is_terminal_status or result.completed_at is not None:
            del _background_tasks[task_id]
            logger.debug("Cleaned up background task: %s", task_id)
```

---

## 8. Subagent解决的问题与好处

### 8.1 解决的问题

#### 8.1.1 上下文隔离

**问题：** 复杂任务的长工具调用历史会污染lead agent的context window。

**解决方案：** Subagent有独立的message历史，任务完成后只返回简洁的结果摘要。

```
Lead Agent Context:
┌─────────────────────────────────────────┐
│  messages: [                            │
│    HumanMessage("分析这个代码库"),       │
│    AIMessage("我将委托给subagent..."),   │
│    ToolMessage(task_result)  ← 只有结果  │
│  ]                                      │
└─────────────────────────────────────────┘

Subagent Context (独立):
┌─────────────────────────────────────────┐
│  messages: [                            │
│    HumanMessage(task_prompt),           │
│    AIMessage(thinking...),              │
│    ToolMessage(bash_results...),        │
│    ... (长历史，不影响lead agent)       │
│  ]                                      │
└─────────────────────────────────────────┘
```

#### 8.1.2 防止递归嵌套

**问题：** Subagent不应该能创建自己的subagent，导致无限递归。

**解决方案：**
```python
# 1. 工具获取时排除task_tool
tools = get_available_tools(subagent_enabled=False)

# 2. config中显式禁用
disallowed_tools=["task", "ask_clarification", "present_files"]
```

#### 8.1.3 资源控制

| 资源类型 | 控制方式 | 源码位置 |
|---------|---------|---------|
| 工具范围 | `tools`/`disallowed_tools`过滤 | `executor.py:78-105` |
| 最大轮次 | `max_turns`参数 | `executor.py:232` |
| 执行超时 | `timeout_seconds` | `executor.py:430` |
| 并发数量 | `SubagentLimitMiddleware` | `agent.py:254-258` |

#### 8.1.4 后台执行与流式事件

**问题：** 长时间运行的任务会阻塞LLM响应。

**解决方案：** 后台执行 + 5秒轮询 + 流式事件

```
前端可实时显示：
1. task_started - 任务开始
2. task_running (多次) - 每个AI消息
3. task_completed/failed/timed_out - 最终状态
```

### 8.2 带来的好处

#### 8.2.1 并行执行

```
时间线 ─────────────────────────────────────────────────────────────→

Lead Agent:    ├─ 调用task ─┬─ 等待 ─┬─ 处理结果 ─┤
                    │        │          │
Subagent 1:              ├─ 运行中 ─┤
                              │
Subagent 2:                ├─ 运行中 ─┤
```

#### 8.2.2 专用agent类型

`bash` subagent专门优化：
```python
tools=["bash", "ls", "read_file", "write_file", "str_replace"]
max_turns=30  # bash任务更快完成
```

#### 8.2.3 配置灵活性

```yaml
# config.yaml
subagents:
  timeout_seconds: 900      # 默认15分钟
  agents:
    bash:
      timeout_seconds: 300  # bash 5分钟
    general-purpose:
      timeout_seconds: 1200 # 复杂任务 20分钟
```

#### 8.2.4 统一错误处理

通过`ToolErrorHandlingMiddleware`，工具异常被捕获并转换为错误消息，不会导致整个执行崩溃：
```python
content = f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. Continue with available context..."
```

---

## 附录：关键数据结构

### SubagentConfig

**源码：`subagents/config.py:6-28`**

```python
@dataclass
class SubagentConfig:
    name: str                           # 唯一标识符
    description: str                    # 何时使用此subagent
    system_prompt: str                  # 系统提示
    tools: list[str] | None = None    # 允许的工具（None=全部）
    disallowed_tools: list[str] | None = field(default_factory=lambda: ["task"])
                                        # 禁用的工具
    model: str = "inherit"             # 模型（inherit=用parent的）
    max_turns: int = 50                # 最大轮次
    timeout_seconds: int = 900         # 超时（秒）
```

### SubagentResult

**源码：`executor.py:36-63`**

```python
@dataclass
class SubagentResult:
    task_id: str                       # 任务ID
    trace_id: str                      # 追踪ID
    status: SubagentStatus            # 当前状态
    result: str | None = None         # 最终结果
    error: str | None = None          # 错误信息
    started_at: datetime | None = None
    completed_at: datetime | None = None
    ai_messages: list[dict[str, Any]] | None = None  # 所有AI消息
```

---

## 附录：完整交互流程详解

### A.1 完整时序图 - Lead Agent 与 Subagent 交互

```
════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
                                         【完整协作流程】
════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                                  前端                                                          │
  │                                            (WebSocket 连接)                                                    │
  └─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                         ▲                                    ▲                                    ▲
                         │ task_started                      │ task_running                    │ task_completed
                         │ (带 task_id)                       │ (带 ai_message)                 │ (带 result)
                         │                                    │                                    │
    ╔════════════════════╩════════════════════════════════════╩════════════════════════════════════════════════╗
    ║                         【 Lead Agent 主线程 】 (异步事件循环)                                              ║
    ╠════════════════════════════════════════════════════════════════════════════════════════════════════════════╣
    ║                                                                                                            ║
    ║   [1] model.invoke() ──► LLM 返回带 tool_calls 的 AIMessage                                               ║
    ║                 │                                                                                         ║
    ║                 ▼                                                                                         ║
    ║   [2] tools_node 执行工具                                                                                 ║
    ║                 │                                                                                         ║
    ║                 ▼                                                                                         ║
    ║   ┌───────────────────────────────────────────────────────────────────────────────────────────────────┐   ║
    ║   │  task_tool() 函数内部:                                                                              │   ║
    ║   │                                                                                                    │   ║
    ║   │   ┌─────────────────────────────────────────────────────────────────────────────────────────────┐ │   ║
    ║   │   │ [A] executor.execute_async(prompt, task_id)  ─────────────────────────────────────────────┐  │ │   ║
    ║   │   │           │                                                                        │  │ │   ║
    ║   │   │           ▼                                                                        │  │ │   ║
    ║   │   │   ┌─────────────────────────────────────────────────────────────────────────────────────┐ │  │ │   ║
    ║   │   │   │ 1. 创建 SubagentResult，status=PENDING，存入 _background_tasks                       │ │  │ │   ║
    ║   │   │   │ 2. _scheduler_pool.submit(run_task)  ──────────────────────────────────────────────┐ │  │ │   ║
    ║   │   │   │    return task_id (立即返回)                                                        │ │  │ │   ║
    ║   │   │   └─────────────────────────────────────────────────────────────────────────────────────┘ │  │ │   ║
    ║   │   └─────────────────────────────────────────────────────────────────────────────────────────────┘ │   ║
    ║   │                                                                                                    │   ║
    ║   │   ┌─────────────────────────────────────────────────────────────────────────────────────────────┐ │   ║
    ║   │   │ [B] writer({"type": "task_started", "task_id": task_id})  ──────────────────────────► 前端  │ │   ║
    ║   │   └─────────────────────────────────────────────────────────────────────────────────────────────┘ │   ║
    ║   │                                                                                                    │   ║
    ║   │   ┌─────────────────────────────────────────────────────────────────────────────────────────────┐ │   ║
    ║   │   │ [C] while True:  ────────────────────────────────────────────────────────────────────────┐  │ │   ║
    ║   │   │           │                                                                              │  │ │   ║
    ║   │   │           ▼                                                                              │  │ │   ║
    ║   │   │   ┌─────────────────────────────────────────────────────────────────────────────────────┐│  │ │   ║
    ║   │   │   │ result = _background_tasks[task_id]  ◄──────────────────────────【消费者读取】──────┼──┼─┤ │   ║
    ║   │   │   │           │                                                【共享存储】              │  │ │   ║
    ║   │   │   │           │                                                                              │  │ │   ║
    ║   │   │   │           ├── result.ai_messages: [...] ◄─── 【消费者读取 ai_messages】                 │  │ │   ║
    ║   │   │   │           │                          【这些消息是 Executor 生产者写入的】               │  │ │   ║
    ║   │   │   │           │                                                                              │  │ │   ║
    ║   │   │   │           ├── len(result.ai_messages) > last_count  ──► 有新消息                      │  │ │   ║
    ║   │   │   │           │           │                                                               │  │ │   ║
    ║   │   │   │           │           ▼                                                               │  │ │   ║
    ║   │   │   │           │   writer({"type": "task_running", "message": new_msg}) ──────────► 前端   │  │ │   ║
    ║   │   │   │           │                                                                              │  │ │   ║
    ║   │   │   │           ├── result.status == COMPLETED ──► writer(task_completed) ──► return       │  │ │   ║
    ║   │   │   │           │                                                                              │  │ │   ║
    ║   │   │   │           └── sleep(5) ──► 继续轮询                                                      │  │ │   ║
    ║   │   │   └─────────────────────────────────────────────────────────────────────────────────────┘│  │ │   ║
    ║   │   └─────────────────────────────────────────────────────────────────────────────────────────────┘ │   ║
    ║   │                                                                                                    │   ║
    ║   │   ┌─────────────────────────────────────────────────────────────────────────────────────────────┐ │   ║
    ║   │   │ [D] return ToolMessage("Task Succeeded. Result: ...")  ──► 回到 Lead Agent 流程            │ │   ║
    ║   │   └─────────────────────────────────────────────────────────────────────────────────────────────┘ │   ║
    ║   └───────────────────────────────────────────────────────────────────────────────────────────────────┘   ║
    ║                 │                                                                                         ║
    ║                 ▼                                                                                         ║
    ║   [3] model.invoke() 处理 ToolMessage ──► 返回最终回复给用户                                               ║
    ║                                                                                                            ║
    ╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
                        │
                        │ submit(run_task)
                        ▼
    ╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
    ║                   【 共享存储: _background_tasks[task_id]  】                                           ║
    ║                                              ◄──────────────────────────────────────────────────────────     ║
    ║                                              │                                                             ║
    ║          ┌──────────────────────────────────┴──────────────────────────────────┐                           ║
    ║          │                                  │                                  │                          ║
    ║          ▼                                  ▼                                  ▼                          ║
    ║   【生产者写入】                    【生产者写入】                    【消费者读取】                    ║
    ║   Scheduler 写入                   Executor 写入                      TaskTool 读取                    ║
    ║   status, started_at               ai_messages, result                 ai_messages                    ║
    ║                                                                                                            ║
    ║   ┌───────────────────────────────────────────────────────────────────────────────────────────────────┐     ║
    ║   │ SubagentResult 共享对象 (通过 result_holder 引用共享)                                              │     ║
    ║   │                                                                                                    │     ║
    ║   │   task_id: str          = "tool_call_xxx"                                                          │     ║
    ║   │   trace_id: str         = "abc123"                                                                 │     ║
    ║   │   status: Enum         ◄── Scheduler 写入: PENDING►RUNNING►COMPLETED                            │     ║
    ║   │   result: str|None     ◄── Executor 写入: 最终结果字符串                                           │     ║
    ║   │   error: str|None      ◄── Executor 写入: 错误信息                                                │     ║
    ║   │   started_at: datetime  ◄── Scheduler 写入                                                        │     ║
    ║   │   completed_at: datetime◄── Scheduler 写入                                                         │     ║
    ║   │   ai_messages: List[dict] ◄── Executor 实时写入 ◄── TaskTool 轮询读取                              │     ║
    ║   │        │                                                                                          │     ║
    ║   │        ├── {id: "msg1", content: "...", ...}  ◄── Executor 调用 agent.astream() 时                  │     ║
    ║   │        │                                    每次产生新消息就 append 进来                            │     ║
    ║   │        ├── {id: "msg2", content: "...", ...}                                                       │     ║
    ║   │        └── ...                                                                                     │     ║
    ║   └───────────────────────────────────────────────────────────────────────────────────────────────────┘     ║
    ╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
                        │
                        ▼
    ╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
    ║                         【 调度线程池: _scheduler_pool (max=3) 】                                         ║
    ║                                              【Scheduler】                                                  ║
    ╠════════════════════════════════════════════════════════════════════════════════════════════════════════════════╣
    ║                                                                                                            ║
    ║   run_task() 执行:                                                                                        ║
    ║   ┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐   ║
    ║   │ ① 【写】更新状态                                                                                     │   ║
    ║   │    _background_tasks[task_id].status = RUNNING                                                      │   ║
    ║   │    _background_tasks[task_id].started_at = datetime.now()                                             │   ║
    ║   │          │                                                                                          │   ║
    ║   │          ▼                                                                                          │   ║
    ║   │ ② 【提交】到执行线程池                                                                               │   ║
    ║   │    _execution_pool.submit(self.execute, task, result_holder)                                           │   ║
    ║   │          │                                                                                          │   ║
    ║   │          ▼                                                                                          │   ║
    ║   │ ③ 【阻塞等待】执行结果                                                                               │   ║
    ║   │    exec_result = execution_future.result(timeout=timeout_seconds)                                     │   ║
    ║   │          │                                                                                          │   ║
    ║   │          ├── 成功 ──► ④ 【写】status=COMPLETED, result=exec_result.result                           │   ║
    ║   │          │                ai_messages, completed_at                                                   │   ║
    ║   │          │                                                                                          │   ║
    ║   │          ├── 超时 ──► ④ 【写】status=TIMED_OUT, error="timed out..."                                │   ║
    ║   │          │                execution_future.cancel()                                                    │   ║
    ║   │          └── 异常 ──► ④ 【写】status=FAILED, error=str(e)                                           │   ║
    ║   └─────────────────────────────────────────────────────────────────────────────────────────────────────┘   ║
    ╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
                        │
                        │ self.execute(task, result_holder)
                        ▼
    ╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
    ║                         【 执行线程池: _execution_pool (max=3) 】                                         ║
    ║                                              【Executor】                                                   ║
    ╠════════════════════════════════════════════════════════════════════════════════════════════════════════════════╣
    ║                                                                                                            ║
    ║   execute() 执行:                                                                                          ║
    ║   ┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐   ║
    ║   │  【关键】在独立线程中创建事件循环                                                                     │   ║
    ║   │  return asyncio.run(self._aexecute(task, result_holder))                                              │   ║
    ║   └─────────────────────────────────────────────────────────────────────────────────────────────────────┘   ║
    ║                        │                                                                                  ║
    ║                        ▼                                                                                  ║
    ║   _aexecute() 异步执行:                                                                                    ║
    ║   ┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐   ║
    ║   │                                                                                                        │   ║
    ║   │   1. agent = self._create_agent()  创建 Subagent 实例                                                  │   ║
    ║   │   2. state = {"messages": [HumanMessage(prompt)]}                                                       │   ║
    ║   │   3.                                                                                                  │   ║
    ║   │   4. async for chunk in agent.astream(state, stream_mode="values"):                                      │   ║
    ║   │          │                                                                                           │   ║
    ║   │          ▼                                                                                           │   ║
    ║   │      ┌─────────────────────────────────────────────────────────────────────────────────────────────┐ │   ║
    ║   │      │ 每次迭代，提取 AI message:                                                               │ │   ║
    ║   │      │     messages = chunk.get("messages", [])                                                │ │   ║
    ║   │      │     last_message = messages[-1]  (如果是 AIMessage)                                        │ │   ║
    ║   │      │                                                                                             │ │   ║
    ║   │      │     message_dict = last_message.model_dump()                                               │ │   ║
    ║   │      │                                                                                             │ │   ║
    ║   │      │  【生产者写入】                                                                             │ │   ║
    ║   │      │     result_holder.ai_messages.append(message_dict)  ◄── 关键：实时写入共享存储！             │ │   ║
    ║   │      │           │                                                                               │ │   ║
    ║   │      │           │  ◄── 此时 TaskTool 在另一个线程轮询，可以读取到这个新消息                     │ │   ║
    ║   │      └─────────────────────────────────────────────────────────────────────────────────────────────┘ │   ║
    ║   │   5.                                                                                                  │   ║
    ║   │   6. 执行完成，提取最终 result:                                                                        │   ║
    ║   │        result_holder.result = final_content  【生产者写入】                                           │   ║
    ║   │        result_holder.status = COMPLETED   【生产者写入】                                              │   ║
    ║   │                                                                                                        │   ║
    ║   │   7. return result_holder  (带最终状态)                                                                │   ║
    ║   │                                                                                                        │   ║
    ║   └─────────────────────────────────────────────────────────────────────────────────────────────────────┘   ║
    ║                                                                                                            ║
    ╚═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
```

### A.2 消息流与状态流转详解

#### 生产者-消费者模型

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           完整消息流                                       │
└────────────────────────────────────────────────────────────────────────────┘

  Lead Agent                    共享存储                      Executor
      │                           │                            │
      │  [A] execute_async()       │                            │
      │  ─────────────────────────►│  创建 result (PENDING)      │
      │                           │                            │
      │                           │◄───────────────────────────│  run_task()
      │                           │  status = RUNNING          │
      │                           │                            │
      │                           │◄───────────────────────────│  asyncio.run(
      │                           │                            │    agent.astream()
      │                           │                            │      每产生一条 AI msg:
      │                           │  ai_messages.append(msg)   │◄────────────────
      │                           │◄───────────────────────────│    )
      │                           │                            │
      │  [C] 轮询读取 ◄───────────│  result.ai_messages       │
      │  有新消息!                 │                            │
      │  writer(task_running) ────►│  前端收到进度              │
      │                           │                            │
      │                           │◄───────────────────────────│  status = COMPLETED
      │                           │  result = final_result     │  return result
      │  [D] COMPLETED 检测       │                            │
      │  ◄────────────────────────│  status == COMPLETED       │
      │  return ToolMessage        │                            │
      │                           │                            │
      ▼                           ▼                            ▼
  继续 Lead Agent 流程           完成                         线程结束
```

### A.3 状态流转详解

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                          【状态流转图】                                                │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────┐       ┌──────────┐       ┌──────────────┐       ┌────────────┐       ┌─────────────┐
  │  PENDING │ ────► │ RUNNING  │ ────► │   COMPLETED   │       │   FAILED   │       │  TIMED_OUT  │
  └──────────┘       └──────────┘       └──────────────┘       └────────────┘       └─────────────┘
       │                 │                    │                    │                    │
       │                 │                    │                    │                    │
       │                 │                    │                    │                    │
       │                 │                    ▼                    │                    ▼
       │                 │              cleanup()                 │              cleanup()
       │                 │              (清理)                    │              (清理)
       │                 │                    │                    │                    │
       │                 ▼                    │                    │                    │
       │           ┌──────────┐               │                    │                    │
       │           │ TIMED_OUT│               │                    │                    │
       │           │ (也可从  │               │                    │                    │
       │           │  RUNNING │               │                    │                    │
       │           │ 直接到达)│               │                    │                    │
       │           └──────────┘               │                    │                    │
       │                 │                    │                    │                    │
       │                 ▼                    ▼                    ▼                    ▼
       │                 └──► cleanup() ◄─────┴────────────────────┴────────────────────┘
       │                                   │
       │                                   ▼
       │                         _background_tasks[task_id] 被删除
       │                         (防止内存泄漏)
       │
       ▼
  task_tool 调用
  execute_async()


  ═══════════════════════════════════════════════════════════════════════════════════════════════
                                    【状态写入者】
  ═══════════════════════════════════════════════════════════════════════════════════════════════

  状态          写入者           位置
  ─────────────────────────────────────────
  PENDING    → TaskTool         task_tool.py (execute_async 入口)
  RUNNING    → Scheduler        executor.py (run_task 内部)
  COMPLETED  → Scheduler        executor.py (run_task 内部，exec_result 成功)
  FAILED     → Scheduler        executor.py (run_task 内部，捕获异常)
  TIMED_OUT  → Scheduler        executor.py (run_task 内部，超时异常)


  ═══════════════════════════════════════════════════════════════════════════════════════════════
                                    【ai_messages 流转】
  ═══════════════════════════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │  Executor (生产者)                                                                        │
  │                                                                                           │
  │    _aexecute() 中的循环:                                                                  │
  │        async for chunk in agent.astream(state, ...):                                        │
  │            last_message = chunk["messages"][-1]                                           │
  │            if isinstance(last_message, AIMessage):                                         │
  │                result_holder.ai_messages.append(last_message.model_dump())  ◄── 写入     │
  │                                                                                           │
  └─────────────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              │ ai_messages 列表增长
                                              ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │  TaskTool (消费者)                                                                        │
  │                                                                                           │
  │    while True 轮询:                                                                       │
  │        result = _background_tasks[task_id]  ◄─── 读取共享引用                             │
  │        current_count = len(result.ai_messages)                                             │
  │        if current_count > last_count:                                                     │
  │            # 有新消息，发送给前端                                                          │
  │            for i in range(last_count, current_count):                                     │
  │                writer({"type": "task_running", "message": result.ai_messages[i]})          │
  │        last_count = current_count                                                         │
  │        sleep(5)                                                                           │
  │                                                                                           │
  └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### A.4 为什么需要两个线程池

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                          【双线程池设计】                                            │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────┐     ┌─────────────────────────────────────┐
  │     _scheduler_pool (max_workers=3)  │     │     _execution_pool (max_workers=3)  │
  │                                      │     │                                      │
  │         【调度线程】                  │     │         【执行线程】                  │
  │                                      │     │                                      │
  │  职责:                               │     │  职责:                               │
  │  1. 接收 execute_async() 调用         │     │  1. 运行 asyncio.run(_aexecute)      │
  │  2. 更新状态 (PENDING → RUNNING)      │     │  2. 执行 agent.astream()             │
  │  3. 提交到 execution_pool             │     │  3. 写入 ai_messages                 │
  │  4. 阻塞等待执行结果 (带超时)          │     │  4. 提取最终 result                 │
  │  5. 更新最终状态                      │     │  5. 支持长时间运行                    │
  │                                      │     │                                      │
  │  特点:                               │     │  特点:                               │
  │  • 响应速度快，不做实际执行           │     │  • 可阻塞等待（asyncio.run）          │
  │  • 可并发调度多个任务                 │     │  • 执行时间可能很长                   │
  │  • result(timeout) 会阻塞            │     │  • 不阻塞调度器                      │
  │                                      │     │                                      │
  └─────────────────────────────────────┘     └─────────────────────────────────────┘
                    │                                    ▲
                    │         submit(execute, ...)      │
                    └──────────────────────────────────┘


  ═══════════════════════════════════════════════════════════════════════════════════════════════
                                    【关键设计原因】
  ═══════════════════════════════════════════════════════════════════════════════════════════════

  问题: result(timeout) 是阻塞调用，如果在主线程执行会怎样？

  答案: 如果只有单一调度线程:

  时间线 ─────────────────────────────────────────────────────────────►

  主线程:
    task_tool() → run_task() → result(timeout=60s) → [阻塞 60 秒!]
                                    ↑
                                    这 60 秒期间:
                                    ❌ Lead Agent 事件循环被阻塞
                                    ❌ 无法处理其他请求
                                    ❌ 无法流式输出
                                    ❌ 用户感觉程序"卡死"

  而使用双线程池:

  scheduler 线程:    [提交任务] → [等待 60s] → [完成]              ← 不阻塞主线程
                              ↑
                              这期间 scheduler 可以继续处理其他任务

  executor 线程:                    [执行 60s] → [完成]            ← 独立执行
```

### A.5 前端事件流

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                          【前端事件流】                                                │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
  │ task_started│         │ task_running│         │ task_running│         │task_completed│
  └──────┬──────┘         └──────┬──────┘         └──────┬──────┘         └──────┬──────┘
         │                        │                        │                        │
         │ task_id                │ message_index: 1       │ message_index: 2       │ result: "..."
         │ description             │ total_messages: 2      │ total_messages: 2      │
         │                        │ message: {...}          │ message: {...}          │
         ▼                        ▼                        ▼                        ▼

  ┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  TaskTool 中的代码:                                                                                     │
  └────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  writer({"type": "task_started", "task_id": task_id, "description": description})
       │
       ▼
  while True:
       │
       ├─► result = get_background_task_result(task_id)
       │
       ├─► if len(result.ai_messages) > last_count:
       │        for i in range(last_count, len(result.ai_messages)):
       │            writer({
       │                "type": "task_running",
       │                "task_id": task_id,
       │                "message": result.ai_messages[i],
       │                "message_index": i + 1,
       │                "total_messages": len(result.ai_messages)
       │            })
       │
       ├─► if result.status == COMPLETED:
       │        writer({"type": "task_completed", "task_id": task_id, "result": result.result})
       │        break
       │
       └─► sleep(5)
```

### A.6 完整代码路径追踪

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                          【调用链追踪】                                                │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Lead Agent
      │
      ├─► model.invoke() → LLM 返回 AIMessage(tool_calls=[task])
      │
      ├─► tools_node 执行 tools
      │       │
      │       └─► task_tool() [task_tool.py:21-195]
      │               │
      │               ├─► get_subagent_config(subagent_type) [registry.py]
      │               │
      │               ├─► get_available_tools(subagent_enabled=False) [tools.py]
      │               │
      │               ├─► SubagentExecutor(...) [executor.py:123-162]
      │               │
      │               ├─► executor.execute_async(prompt, task_id) [executor.py:391-453]
      │               │       │
      │               │       ├─► 创建 SubagentResult(status=PENDING)
      │               │       ├─► _background_tasks[task_id] = result
      │               │       └─► _scheduler_pool.submit(run_task)
      │               │               │
      │               │               └─► run_task() [executor.py:418-451]
      │               │                       │
      │               │                       ├─► status = RUNNING (写入共享存储)
      │               │                       │
      │               │                       ├─► _execution_pool.submit(execute, task, result_holder)
      │               │                       │       │
      │               │                       │       └─► execute() [executor.py:351-389]
      │               │                       │               │
      │               │                       │               └─► asyncio.run(_aexecute()) [executor.py:203-349]
      │               │                       │                       │
      │               │                       │                       ├─► agent = _create_agent()
      │               │                       │                       │
      │               │                       │                       ├─► async for chunk in agent.astream(state):
      │               │                       │                       │       │
      │               │                       │                       │       ├─► result.ai_messages.append(msg)
      │               │                       │                       │       │         ↑
      │               │                       │                       │       │         │
      │               │                       │                       │       │         │ (这是 ai_messages 被写入的地方)
      │               │                       │                       │       │
      │               │                       │                       │       └─► result.result = final_content
      │               │                       │                       │         result.status = COMPLETED
      │               │                       │                       │
      │               │                       ├─► exec_result = execution_future.result(timeout)
      │               │                       │       │
      │               │                       │       └─► 读取执行结果
      │               │                       │
      │               └─► writer({"type": "task_started", ...}) [task_tool.py:128-130]
      │                       │
      │                       └─► while True: [task_tool.py:132-195]
      │                               │
      │                               ├─► result = _background_tasks[task_id]
      │                               │       │
      │                               │       │  ◄── 读取 ai_messages (此时 Executor 已写入)
      │                               │       │
      │                               ├─► if len(result.ai_messages) > last_count:
      │                               │       │
      │                               │       └─► writer({"type": "task_running", "message": ...})
      │                               │               │
      │                               │               └─► 前端收到中间消息
      │                               │
      │                               ├─► if result.status == COMPLETED:
      │                               │       │
      │                               │       └─► writer({"type": "task_completed", ...})
      │                               │               │
      │                               │               └─► return ToolMessage(...)
      │                               │
      │                               └─► sleep(5) → 继续轮询
      │
      └─► model.invoke() 处理 ToolMessage → 返回最终回复
```

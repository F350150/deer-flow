# LangChain 与 LangGraph 核心类与接口详解

> 本文档详细介绍 DeerFlow 项目中使用的 LangChain 和 LangGraph 核心类与接口，涵盖其设计原理、API 签名、使用场景及代码示例。

---

## 目录

1. [概述](#1-概述)
2. [Agent 系统](#2-agent-系统)
3. [消息类型体系](#3-消息类型体系)
4. [工具系统](#4-工具系统)
   4.9. [MCP 客户端](#49-mcp-客户端)
   4.10. [工具格式转换](#410-工具格式转换)
   4.11. [延迟工具注册表](#411-延迟工具注册表)
5. [中间件系统](#5-中间件系统)
6. [状态管理与 State Schema](#6-状态管理与-state-schema)
7. [控制流与状态更新](#7-控制流与状态更新)
8. [检查点与持久化](#8-检查点与持久化)
9. [运行时配置](#9-运行时配置)
10. [流式输出](#10-流式输出)
11. [模型与输出处理](#11-模型与输出处理)
12. [追踪与监控](#12-追踪与监控)

---

## 1. 概述

### 1.1 LangChain 与 LangGraph 的关系

LangChain 是一个用于构建 LLM 应用的通用框架，而 LangGraph 是 LangChain 的扩展，专注于构建有状态、可持久化、多 actor 的复杂 Agent 系统。

```
┌─────────────────────────────────────────────────────────────────┐
│                        LangChain Ecosystem                       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                      LangChain Core                         │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │  │
│  │  │   Messages   │  │   Tools     │  │   Chat Models   │   │  │
│  │  │  (AIMessage, │  │ (@tool,     │  │ (BaseChatModel)│   │  │
│  │  │  HumanMsg)   │  │  BaseTool)  │  │                 │   │  │
│  │  └──────────────┘  └──────────────┘  └─────────────────┘   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│                              ▼                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                       LangGraph                             │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │  │
│  │  │    Graph     │  │   Checkpoint │  │    Runtime      │   │  │
│  │  │  (StateGraph)│  │   (Saver)    │  │  (Middleware)   │   │  │
│  │  └──────────────┘  └──────────────┘  └─────────────────┘   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│                              ▼                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    LangChain Agents                         │  │
│  │  ┌──────────────────────────────────────────────────────┐ │  │
│  │  │              create_agent()                            │ │  │
│  │  │  - Combines Model + Tools + Middleware + StateSchema  │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 DeerFlow 中的核心依赖映射

| 功能模块 | LangChain 类/接口 | LangGraph 类/接口 |
|---------|------------------|------------------|
| Agent 创建 | `create_agent`, `AgentState` | - |
| 中间件 | `AgentMiddleware`, `SummarizationMiddleware` | `Runtime` |
| 消息 | `AIMessage`, `HumanMessage`, `ToolMessage` | - |
| 工具 | `@tool`, `BaseTool`, `StructuredTool` | `ToolRuntime`, `ToolCallRequest` |
| 状态更新 | - | `Command`, `END` |
| 持久化 | - | `Checkpointer`, `InMemorySaver`, `SqliteSaver` |
| 配置 | `RunnableConfig` | `get_config`, `get_stream_writer` |

---

## 2. Agent 系统

### 2.1 `create_agent` — Agent 工厂函数

**来源**: `langchain.agents`

**模块路径**: `langchain.agents.create_agent`

**作用**: LangChain Agents 的核心工厂函数，用于创建配置好的 Agent 实例。该函数封装了模型、工具、中间件和状态 schema 的绑定逻辑。

**函数签名**:

```python
def create_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool | ToolLike],
    middleware: Sequence[AgentMiddleware] | None = None,
    *,
    system_prompt: str | None = None,
    state_schema: type[AgentState] | None = None,
    checkpointer: Checkpointer | None = None,
    debug: bool = False,
    interrupt_before_ Tool: Sequence[str] | None = None,
    interrupt_after_Tool: Sequence[str] | None = None,
    response_generation_ Tool: str | None = None,
    parallel_tool_calls: bool = True,
) -> AgentExecutor:
```

**参数详解**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `model` | `BaseChatModel` | 是 | 聊天模型实例，负责生成响应 |
| `tools` | `Sequence[BaseTool \| ToolLike]` | 是 | Agent 可调用的工具列表 |
| `middleware` | `Sequence[AgentMiddleware] \| None` | 否 | 中间件链，默认为 None |
| `system_prompt` | `str \| None` | 否 | 系统提示词模板 |
| `state_schema` | `type[AgentState] \| None` | 否 | 状态类型定义，默认为 `AgentState` |
| `checkpointer` | `Checkpointer \| None` | 否 | 状态持久化检查点 |
| `debug` | `bool` | 否 | 开启调试模式 |
| `interrupt_before_tool` | `Sequence[str] \| None` | 否 | 工具执行前中断点 |
| `interrupt_after_tool` | `Sequence[str] \| None` | 否 | 工具执行后中断点 |
| `response_generation_tool` | `str \| None` | 否 | 响应生成专用工具名 |
| `parallel_tool_calls` | `bool` | 否 | 是否并行执行工具调用 |

**返回值**: `AgentExecutor` — 可执行 Agent 实例

**DeerFlow 使用示例** (`deerflow/agents/lead_agent/agent.py:337`):

```python
return create_agent(
    model=create_chat_model(
        name=model_name,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort
    ),
    tools=get_available_tools(
        model_name=model_name,
        groups=agent_config.tool_groups if agent_config else None,
        subagent_enabled=subagent_enabled
    ),
    middleware=_build_middlewares(config, model_name=model_name, agent_name=agent_name),
    system_prompt=apply_prompt_template(
        subagent_enabled=subagent_enabled,
        max_concurrent_subagents=max_concurrent_subagents,
        agent_name=agent_name
    ),
    state_schema=ThreadState,
)
```

**执行流程图**:

```
                          create_agent()
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │    AgentExecutor         │
                    │                         │
                    │  ┌───────────────────┐ │
                    │  │  Middleware Chain  │ │
                    │  │  ┌─────────────┐  │ │
                    │  │  │Middleware #1│  │ │
                    │  │  ├─────────────┤  │ │
                    │  │  │Middleware #2│  │ │
                    │  │  ├─────────────┤  │ │
                    │  │  │   ...      │  │ │
                    │  │  └─────────────┘  │ │
                    │  └───────────────────┘ │
                    │           │            │
                    │           ▼            │
                    │  ┌───────────────────┐ │
                    │  │  Model + Tools    │ │
                    │  │                   │ │
                    │  │  BaseChatModel    │ │
                    │  │  + BaseTool[]      │ │
                    │  └───────────────────┘ │
                    │           │            │
                    │           ▼            │
                    │  ┌───────────────────┐ │
                    │  │   State Manager   │ │
                    │  │   (AgentState)    │ │
                    │  │   + Checkpointer  │ │
                    │  └───────────────────┘ │
                    └─────────────────────────┘
                                  │
                                  ▼
                          agent.stream(state, config)
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │    Execution Loop       │
                    │                         │
                    │  1. before_agent        │
                    │  2. before_model        │
                    │  3. Model Call          │
                    │  4. after_model         │
                    │  5. wrap_tool_call      │
                    │  6. Tool Execution      │
                    │  7. after_agent         │
                    │  8. goto (END or loop) │
                    └─────────────────────────┘
```

---

### 2.2 `AgentState` — Agent 状态基类

**来源**: `langchain.agents`

**模块路径**: `langchain.agents.AgentState`

**作用**: 所有 Agent 状态的基类，继承自 Python 的 `TypedDict`，提供了类型安全的状态定义。LangChain Agents 使用 `AgentState` 作为状态的基础结构。

**类型定义**:

```python
# langchain/agents/__init__.py
class AgentState(TypedDict):
    """Base state for all agents."""
    
    # The message history
    messages: Annotated[list[BaseMessage], add_messages]
    
    # Optional agent memory
    memory: NotRequired[dict[str, Any]]
```

**核心字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | `Annotated[list[BaseMessage], add_messages]` | 消息历史，使用 `add_messages` reducer 进行合并 |
| `memory` | `NotRequired[dict[str, Any]]` | Agent 内存（可选） |

**`add_messages` Reducer 函数**:

```python
def add_messages(existing: list[BaseMessage], new: list[BaseMessage]) -> list[BaseMessage]:
    """Reducer function for merging messages.
    
    Appends new messages to existing list, avoiding duplicates based on message ID.
    """
    existing_ids = {msg.id for msg in existing if hasattr(msg, 'id')}
    for msg in new:
        if hasattr(msg, 'id') and msg.id in existing_ids:
            continue
        existing.append(msg)
    return existing
```

**DeerFlow 扩展示例** (`deerflow/agents/thread_state.py`):

```python
from typing import Annotated, NotRequired, TypedDict
from langchain.agents import AgentState

class SandboxState(TypedDict):
    """沙箱环境状态"""
    sandbox_id: NotRequired[str | None]

class ThreadDataState(TypedDict):
    """线程数据状态"""
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]

class ViewedImageData(TypedDict):
    """已查看图片数据"""
    base64: str
    mime_type: str

def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Artifact 列表合并 reducer — 去重并保留顺序"""
    if existing is None:
        return new or []
    if new is None:
        return existing
    return list(dict.fromkeys(existing + new))

def merge_viewed_images(
    existing: dict[str, ViewedImageData] | None,
    new: dict[str, ViewedImageData] | None
) -> dict[str, ViewedImageData]:
    """已查看图片合并 reducer — 空字典 {} 表示清空"""
    if existing is None:
        return new or {}
    if new is None:
        return existing
    if len(new) == 0:
        return {}  # 空字典清空所有图片
    return {**existing, **new}

class ThreadState(AgentState):
    """DeerFlow 主状态定义，继承 AgentState"""
    
    # 沙箱相关
    sandbox: NotRequired[SandboxState | None]
    
    # 线程数据
    thread_data: NotRequired[ThreadDataState | None]
    
    # 对话标题
    title: NotRequired[str | None]
    
    # 产物文件列表（带合并 reducer）
    artifacts: Annotated[list[str], merge_artifacts]
    
    # Todo 列表
    todos: NotRequired[list | None]
    
    # 已上传文件
    uploaded_files: NotRequired[list[dict] | None]
    
    # 已查看图片
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]
```

**状态合并机制**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    State Merge Flow                              │
│                                                                  │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐     │
│  │  Existing   │      │   Update    │      │    Result   │     │
│  │   State     │ ───► │   (Command) │ ───► │   (Merged)  │     │
│  │             │      │             │      │             │     │
│  │ messages:   │      │ messages:   │      │ messages:   │     │
│  │   [A, B]   │      │   [C, D]    │      │ [A, B, C, D]│     │
│  │             │      │             │      │             │     │
│  │ artifacts: │      │ artifacts: │      │ artifacts:  │     │
│  │   [f1]    │      │   [f2, f1]  │      │  [f1, f2]   │     │
│  └─────────────┘      └─────────────┘      └─────────────┘     │
│                                                                  │
│                    (dict.fromkeys preserves order + dedup)       │
└─────────────────────────────────────────────────────────────────┘
```

---

### 2.3 `AgentExecutor` — Agent 执行器

**来源**: `langchain.agents`

**作用**: `create_agent()` 返回的实际执行类型，负责运行 Agent 的主循环。

**核心方法**:

```python
class AgentExecutor:
    """Executes an agent with tools and middleware."""
    
    def stream(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        context: dict[str, Any] | None = None,
        stream_mode: str = "values",
    ) -> Generator[dict[str, Any], None, None]:
        """Execute the agent with streaming."""
        ...
    
    async def astream(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        context: dict[str, Any] | None = None,
        stream_mode: str = "values",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Async version of stream."""
        ...
    
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
    ) -> dict[str, Any]:
        """Execute the agent without streaming."""
        ...
```

**DeerFlow 调用示例** (`deerflow/client.py:358`):

```python
state = {"messages": [HumanMessage(content=message)]}
context = {"thread_id": thread_id}
if self._agent_name:
    context["agent_name"] = self._agent_name

for chunk in self._agent.stream(state, config=config, context=context, stream_mode="values"):
    messages = chunk.get("messages", [])
    for msg in messages:
        # 处理消息...
```

---

## 3. 消息类型体系

### 3.1 消息类层次结构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Message Class Hierarchy                     │
│                                                                  │
│                        ┌──────────────┐                         │
│                        │  BaseMessage │                         │
│                        │              │                         │
│                        │ +content: str│                         │
│                        │ +additional_kwargs: dict               │
│                        │ +type: str   │                         │
│                        │ +name: str | None                      │
│                        │ +id: str | None                        │
│                        └──────┬───────┘                         │
│                               │                                  │
│          ┌────────────────────┼────────────────────┐            │
│          │                    │                    │            │
│          ▼                    ▼                    ▼            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ HumanMessage │    │  AIMessage   │    │ToolMessage  │      │
│  │              │    │              │    │              │      │
│  │ type="human"│    │ type="ai"    │    │ type="tool"  │      │
│  └──────────────┘    └──────┬───────┘    └──────┬───────┘      │
│                             │                    │             │
│                             ▼                    ▼             │
│                    ┌──────────────┐    ┌──────────────┐      │
│                    │AIMessageChunk│    │ SystemMessage│      │
│                    │(streaming)   │    │              │      │
│                    └──────────────┘    │ type="system"│      │
│                                         └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 `BaseMessage` — 消息基类

**来源**: `langchain_core.messages`

**模块路径**: `langchain_core.messages.BaseMessage`

**类型定义**:

```python
class BaseMessage(BaseModel):
    """Base class for all messages."""
    
    content: str = Field(description="The content of the message")
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    
    @property
    def type(self) -> str:
        """Returns the type of the message."""
        return "base"
    
    @property
    def id(self) -> str | None:
        """Returns the unique ID of the message."""
        return getattr(self, "_id", None)
    
    def pretty_repr(self) -> str: ...
    def pretty_print(self) -> None: ...
```

### 3.3 `HumanMessage` — 人类消息

**来源**: `langchain_core.messages`

**模块路径**: `langchain_core.messages.HumanMessage`

**类型定义**:

```python
class HumanMessage(BaseMessage):
    """A message from a human / user."""
    
    @property
    def type(self) -> str:
        return "human"
    
    def __init__(
        self,
        content: str,
        **kwargs,
    ):
        super().__init__(content=content, **kwargs)
```

**构造参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `content` | `str` | 消息内容 |
| `name` | `str \| None` | 发送者名称（可选） |
| `**kwargs` | - | 其他 BaseMessage 参数 |

**使用示例** (`deerflow/client.py:350`):

```python
state = {"messages": [HumanMessage(content=message)]}
```

### 3.4 `AIMessage` — AI 消息

**来源**: `langchain_core.messages`

**模块路径**: `langchain_core.messages.AIMessage`

**类型定义**:

```python
class AIMessage(BaseMessage):
    """A message from an AI / LLM."""
    
    content: str | list[ContentBlock] = Field(default="")
    tool_calls: list[ToolCall] = Field(default_factory=list)
    invalid_tool_calls: list[InvalidToolCall] = Field(default_factory=list)
    usage_metadata: dict[str, Any] = Field(default_factory=dict)
    
    @property
    def type(self) -> str:
        return "ai"
```

**ToolCall 结构**:

```python
class ToolCall(TypedDict):
    """A tool call to be made by the AI."""
    
    name: str           # 工具名称
    args: dict[str, Any]  # 工具参数
    id: str | None      # 工具调用 ID
    type: Literal["tool_call"] = "tool_call"
```

**usage_metadata 结构**:

```python
{
    "input_tokens": int,
    "output_tokens": int,
    "total_tokens": int,
    "input_token_details": dict,  # 可选
    "output_token_details": dict,  # 可选
}
```

**DeerFlow 使用示例** (`deerflow/client.py:368`):

```python
if isinstance(msg, AIMessage):
    usage = getattr(msg, "usage_metadata", None)
    if usage:
        cumulative_usage["input_tokens"] += usage.get("input_tokens", 0) or 0
        cumulative_usage["output_tokens"] += usage.get("output_tokens", 0) or 0
        cumulative_usage["total_tokens"] += usage.get("total_tokens", 0) or 0
    
    if msg.tool_calls:
        yield StreamEvent(
            type="messages-tuple",
            data={
                "type": "ai",
                "content": "",
                "id": msg_id,
                "tool_calls": [
                    {"name": tc["name"], "args": tc["args"], "id": tc.get("id")}
                    for tc in msg.tool_calls
                ],
            },
        )
```

### 3.5 `ToolMessage` — 工具消息

**来源**: `langchain_core.messages`

**模块路径**: `langchain_core.messages.ToolMessage`

**类型定义**:

```python
class ToolMessage(BaseMessage):
    """A message returned by a tool execution."""
    
    tool_call_id: str = Field(description="The ID of the tool call this message responds to")
    name: str = Field(description="The name of the tool that was executed")
    status: Literal["success", "error"] | str = Field(default="success")
    
    @property
    def type(self) -> str:
        return "tool"
```

**构造参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `content` | `str` | 工具执行结果内容 |
| `tool_call_id` | `str` | 对应 AI 消息中的 tool_call ID |
| `name` | `str` | 工具名称 |
| `status` | `str` | 执行状态 (`"success"` 或 `"error"`) |

**DeerFlow 使用示例** (`deerflow/tools/builtins/setup_agent_tool.py:51`):

```python
return Command(
    update={
        "created_agent_name": agent_name,
        "messages": [
            ToolMessage(
                content=f"Agent '{agent_name}' created successfully!",
                tool_call_id=runtime.tool_call_id
            )
        ],
    }
)
```

### 3.6 `SystemMessage` — 系统消息

**来源**: `langchain_core.messages`

**模块路径**: `langchain_core.messages.SystemMessage`

**类型定义**:

```python
class SystemMessage(BaseMessage):
    """A system message for providing instructions to the AI."""
    
    @property
    def type(self) -> str:
        return "system"
```

### 3.7 `AIMessageChunk` — AI 消息流式块

**来源**: `langchain_core.messages`

**模块路径**: `langchain_core.messages.AIMessageChunk`

**类型定义**:

```python
class AIMessageChunk(AIMessage):
    """A chunk of an AI message, used for streaming."""
    
    finish_reason: str | None = None
    usage_chunk: dict[str, Any] | None = None
    
    def __add__(self, other: AIMessageChunk) -> AIMessageChunk:
        """Concatenate two chunks into one."""
        ...
```

**用途**: 在流式输出时，表示 AI 消息的增量块，最终可合并为完整的 `AIMessage`。

---

## 4. 工具系统

### 4.1 工具类层次结构

```
┌─────────────────────────────────────────────────────────────────┐
│                      Tool Class Hierarchy                        │
│                                                                  │
│                      ┌──────────────┐                            │
│                      │   BaseTool   │                            │
│                      │              │                            │
│                      │ +name: str   │                            │
│                      │ +description │                            │
│                      │ +args_schema │                            │
│                      │ +return_direct│                            │
│                      │ +is_async: bool                           │
│                      │              │                            │
│                      │ +invoke()    │                            │
│                      │ +ainvoke()   │                            │
│                      │ +stream()    │                            │
│                      └──────┬───────┘                            │
│                             │                                     │
│                             ▼                                     │
│                      ┌──────────────┐                            │
│                      │StructuredTool│                            │
│                      │              │                            │
│                      │ +from_function()│                         │
│                      │ +coroutine    │                            │
│                      └──────────────┘                            │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              Tool Creation Methods                           │ │
│  │                                                             │ │
│  │  1. @tool decorator                                         │ │
│  │  2. StructuredTool.from_function()                          │ │
│  │  3. BaseTool directly                                       │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 `tool` 装饰器

**来源**: `langchain_core.tools` / `langchain.tools`

**模块路径**: `langchain_core.tools.tool`

**作用**: 简化工具定义的装饰器，将 Python 函数自动转换为 `StructuredTool` 实例。

**函数签名**:

```python
def tool(
    name: str | None = None,
    *,
    description: str | None = None,
    args_schema: type[BaseModel] | None = None,
    parse_docstring: bool = False,
    infer_schema: bool = True,
    return_direct: bool = False,
    coroutine: Callable[..., Any] | None = None,
) -> Callable[[F], StructuredTool]:
    """Create a tool from a function."""
    ...
```

**参数详解**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `str \| None` | 工具名称，默认使用函数名 |
| `description` | `str \| None` | 工具描述，默认使用 docstring |
| `args_schema` | `type[BaseModel] \| None` | 参数 Pydantic 模型 |
| `parse_docstring` | `bool` | 是否解析 Google 风格 docstring |
| `infer_schema` | `bool` | 是否自动推断参数类型 |
| `return_direct` | `bool` | 是否直接返回结果给用户 |
| `coroutine` | `Callable \| None` | 异步实现函数 |

**基本用法** (`deerflow/tools/builtins/setup_agent_tool.py:14`):

```python
@tool
def setup_agent(
    soul: str,
    description: str,
    runtime: ToolRuntime,
) -> Command:
    """Setup the custom DeerFlow agent.
    
    Args:
        soul: Full SOUL.md content defining the agent's personality and behavior.
        description: One-line description of what the agent does.
    """
    agent_name: str | None = runtime.context.get("agent_name") if runtime.context else None
    # ... 实现
    return Command(update={"created_agent_name": agent_name, ...})
```

**带 docstring 解析的用法** (`deerflow/tools/builtins/task_tool.py:21`):

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
    """Delegate a task to a specialized subagent that runs in its own context.
    
    Subagents help you:
    - Preserve context by keeping exploration and implementation separate
    - Handle complex multi-step tasks autonomously
    
    Args:
        description: A short description of the task. ALWAYS PROVIDE THIS PARAMETER FIRST.
        prompt: The task description for the subagent.
        subagent_type: The type of subagent to use.
        max_turns: Optional maximum number of agent turns.
    """
    # 实现...
```

**装饰器工作原理**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    @tool Decorator Flow                          │
│                                                                  │
│  ┌─────────────────┐                                            │
│  │  Python Function │                                           │
│  │                 │                                            │
│  │ def my_tool(   │                                            │
│  │     arg1: str, │                                           │
│  │     arg2: int  │                                           │
│  │ ) -> str:      │                                           │
│  │     ...        │                                           │
│  └────────┬────────┘                                            │
│           │ @tool()                                             │
│           ▼                                                      │
│  ┌─────────────────┐                                            │
│  │ StructuredTool  │                                            │
│  │                 │                                            │
│  │ name: "my_tool" │                                           │
│  │ description: ... │                                           │
│  │ args_schema:    │                                           │
│  │   MyToolInput   │                                           │
│  │                 │                                            │
│  │ .invoke() ──►   │                                           │
│  │   my_tool()     │                                           │
│  └─────────────────┘                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 `BaseTool` — 工具基类

**来源**: `langchain_core.tools`

**类型定义**:

```python
class BaseTool(BaseModel, ABC):
    """Base class for all tools."""
    
    name: str = Field(description="The unique name of the tool")
    description: str = Field(description="A description of the tool")
    args_schema: type[BaseModel] = Field(default=DefaultToolInput)
    return_direct: bool = Field(default=False)
    verbose: bool = Field(default=False)
    callbacks: Callbacks = Field(default=None, exclude=True)
    tags: list[str] | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
    handle_tool_error: bool | str | Callable = Field(default=False)
    
    @abstractmethod
    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """Synchronous tool execution."""
        ...
    
    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        """Async tool execution. Default implementation calls _run."""
        ...
    
    def invoke(self, input: Any, config: RunnableConfig | None = None) -> Any:
        """Execute the tool with given input."""
        ...
    
    async def ainvoke(self, input: Any, config: RunnableConfig | None = None) -> Any:
        """Async version of invoke."""
        ...
```

### 4.4 `StructuredTool` — 结构化工具

**来源**: `langchain_core.tools`

**类型定义**:

```python
class StructuredTool(BaseTool):
    """A tool with a structured input schema."""
    
    description: str = Field(description="The description of the tool")
    args_schema: type[BaseModel] = Field(description="The input schema")
    func: Callable[..., Any] | None = Field(default=None, exclude=True)
    coroutine: Callable[..., Awaitable[Any]] | None = Field(default=None, exclude=True)
    
    @classmethod
    def from_function(
        cls,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        args_schema: type[BaseModel] | None = None,
        return_direct: bool = False,
        coroutine: Callable[..., Awaitable[Any]] | None = None,
    ) -> StructuredTool:
        """Create a StructuredTool from a function."""
        ...
```

**DeerFlow 创建工具示例** (`deerflow/tools/builtins/invoke_acp_agent_tool.py:203`):

```python
return StructuredTool.from_function(
    name="invoke_acp_agent",
    description=description,
    coroutine=_invoke,  # 异步函数
    args_schema=_InvokeACPAgentInput,  # Pydantic 输入模型
)
```

### 4.5 `ToolRuntime` — 工具运行时

**来源**: `langgraph.prebuilt`

**模块路径**: `langgraph.prebuilt.ToolRuntime`

**类型定义**:

```python
class ToolRuntime(Generic[ContextT, StateT]):
    """Runtime context for tool execution."""
    
    config: RunnableConfig
    """运行时配置，包含 configurable 等信息"""
    
    context: ContextT
    """运行时上下文（如 thread_id, agent_name 等）"""
    
    state: StateT
    """当前 Agent 状态快照"""
    
    tool_call_id: str
    """当前工具调用的唯一 ID"""
    
    def node_name(self) -> str:
        """Returns the name of the current node in the graph."""
        ...
```

**泛型参数**:

| 参数 | 说明 |
|------|------|
| `ContextT` | 上下文类型，默认 `dict[str, Any]` |
| `StateT` | 状态类型，默认 `AgentState` |

**DeerFlow 使用示例** (`deerflow/tools/builtins/setup_agent_tool.py:18`):

```python
@tool
def setup_agent(
    soul: str,
    description: str,
    runtime: ToolRuntime,  # 自动注入
) -> Command:
    """Setup the custom DeerFlow agent."""
    
    # 从 runtime 获取上下文
    agent_name: str | None = runtime.context.get("agent_name") if runtime.context else None
    
    # 从 runtime 获取状态
    sandbox_id = runtime.state.get("sandbox", {}).get("sandbox_id")
    
    # 使用 tool_call_id 构造响应
    return Command(
        update={
            "created_agent_name": agent_name,
            "messages": [
                ToolMessage(
                    content=f"Agent created!",
                    tool_call_id=runtime.tool_call_id
                )
            ],
        }
    )
```

**TaskTool 中的完整用法** (`deerflow/tools/builtins/task_tool.py:78`):

```python
if runtime is not None:
    # 从 runtime 获取子代理所需的上下文
    sandbox_state = runtime.state.get("sandbox")
    thread_data = runtime.state.get("thread_data")
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    
    # 从 metadata 获取追踪信息
    metadata = runtime.config.get("metadata", {})
    parent_model = metadata.get("model_name")
    trace_id = metadata.get("trace_id") or str(uuid.uuid4())[:8]
```

### 4.6 `ToolCallRequest` — 工具调用请求

**来源**: `langgraph.prebuilt.tool_node`

**类型定义**:

```python
class ToolCallRequest(TypedDict):
    """A request to execute a tool call."""
    
    tool_call: ToolCall
    """The tool call to execute"""
    
    tool_call_id: str
    """The unique ID of this tool call"""
    
    name: str
    """The name of the tool"""
    
    args: dict[str, Any]
    """The arguments to pass to the tool"""
```

**ToolCall 结构**:

```python
class ToolCall(TypedDict):
    """A tool call from an AI message."""
    
    name: str
    """The name of the tool"""
    
    args: dict[str, Any]
    """The arguments to pass to the tool"""
    
    id: str | None
    """The unique ID of this tool call"""
    
    type: Literal["tool_call"] = "tool_call"
```

**DeerFlow 中间件拦截示例** (`deerflow/guardrails/middleware.py:54`):

```python
def wrap_tool_call(
    self,
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    # 从请求中提取工具信息
    gr = self._build_request(request)
    # request.tool_call 包含 {name, args, id}
    # request.tool_call_id 是当前调用的 ID
    tool_name = request.tool_call.get("name", "")
    tool_input = request.tool_call.get("args", {})
    
    try:
        decision = self.provider.evaluate(gr)
    except GraphBubbleUp:
        raise  # 保留控制流信号
    except Exception:
        decision = GuardrailDecision(allow=False, ...)
    
    if not decision.allow:
        return self._build_denied_message(request, decision)
    
    return handler(request)  # 继续正常执行
```

### 4.7 注入参数标记

#### `InjectedToolCallId`

**来源**: `langchain.tools`

**作用**: 标记 tool_call_id 参数由系统自动注入。

```python
from langchain.tools import InjectedToolCallId
from typing import Annotated

@tool
def my_tool(
    tool_call_id: Annotated[str, InjectedToolCallId],  # 自动注入
    user_input: str,  # 用户提供
):
    # tool_call_id 会自动被填充
    return f"Called with {tool_call_id}"
```

#### `InjectedToolArg`

**来源**: `langchain.tools`

**作用**: 标记指定名称的参数由系统自动注入。

```python
from langchain.tools import InjectedToolArg, ToolRuntime

@tool
def my_tool(
    runtime: Annotated[ToolRuntime, InjectedToolArg("runtime")],  # 注入 runtime
    task: str,
):
    thread_id = runtime.context.get("thread_id")
    return f"Thread: {thread_id}, Task: {task}"
```

### 4.8 工具执行流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    Tool Execution Flow                            │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 1. Model generates AIMessage with tool_calls             │   │
│  │                                                          │   │
│  │    AIMessage.tool_calls = [                              │   │
│  │        {name: "search", args: {query: "..."}, id: "1"},  │   │
│  │        {name: "calc", args: {expr: "..."}, id: "2"}     │   │
│  │    ]                                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 2. Middleware wrap_tool_call() intercepts                │   │
│  │                                                          │   │
│  │    middleware.wrap_tool_call(request, handler)           │   │
│  │                                                          │   │
│  │    - GuardrailMiddleware: evaluate before execution      │   │
│  │    - ToolErrorHandlingMiddleware: catch exceptions       │   │
│  │    - ClarificationMiddleware: intercept special tools   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 3. Tool execution via ToolNode                           │   │
│  │                                                          │   │
│  │    ToolMessage = tool.invoke(tool_call)                  │   │
│  │                                                          │   │
│  │    @tool                                                  │   │
│  │    def search(query: str) -> str:                        │   │
│  │        return f"Results for: {query}"                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 4. ToolMessage added to state                            │   │
│  │                                                          │   │
│  │    state["messages"].append(ToolMessage(                 │   │
│  │        content=result,                                    │   │
│  │        tool_call_id=tool_call.id,                         │   │
│  │        name=tool_call.name                                │   │
│  │    ))                                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 5. Loop continues with next model call                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4.9 MCP 客户端

### 4.9.1 `MultiServerMCPClient` — 多服务器 MCP 客户端

**来源**: `langchain_mcp_adapters.client`

**模块路径**: `langchain_mcp_adapters.client.MultiServerMCPClient`

**作用**: LangChain 提供的 MCP (Model Context Protocol) 客户端，用于连接多个 MCP 服务器并获取其提供的工具。

**类型定义**:

```python
class MultiServerMCPClient:
    """Client for connecting to multiple MCP servers.
    
    Manages connections to multiple MCP servers simultaneously,
    aggregates tools from all servers, and provides a unified
    interface for tool invocation.
    """
    
    def __init__(
        self,
        servers: dict[str, dict[str, Any]],
        *,
        tool_interceptors: list[Callable] | None = None,
        tool_name_prefix: bool = True,
        timeout: float = 60.0,
        **kwargs: Any,
    ):
        """Initialize the multi-server MCP client.
        
        Args:
            servers: Dict mapping server name -> server configuration.
                     Each config should include 'transport' and transport-specific params.
            tool_interceptors: Optional list of tool interceptors for modifying
                              tool behavior (e.g., OAuth injection).
            tool_name_prefix: If True, prefix tool names with server name (servername__toolname).
            timeout: Default timeout for tool invocations in seconds.
            **kwargs: Additional arguments passed to underlying transport.
        """
        ...
    
    async def get_tools(self) -> list[BaseTool]:
        """Get all tools from all configured MCP servers.
        
        Returns:
            List of BaseTool instances from all servers.
        """
        ...
    
    async def close(self) -> None:
        """Close all server connections."""
        ...
```

**DeerFlow 使用** (`deerflow/mcp/tools.py:98`):

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async def get_mcp_tools() -> list[BaseTool]:
    # 构建服务器配置
    servers_config = build_servers_config(extensions_config)
    
    if not servers_config:
        return []
    
    # 配置 OAuth 拦截器
    tool_interceptors = []
    oauth_interceptor = build_oauth_tool_interceptor(extensions_config)
    if oauth_interceptor is not None:
        tool_interceptors.append(oauth_interceptor)
    
    # 创建 MCP 客户端
    client = MultiServerMCPClient(
        servers_config,
        tool_interceptors=tool_interceptors,
        tool_name_prefix=True  # 工具名添加服务器前缀
    )
    
    # 获取所有工具
    tools = await client.get_tools()
    
    # 为同步调用打补丁
    for tool in tools:
        if getattr(tool, "func", None) is None and getattr(tool, "coroutine", None) is not None:
            tool.func = _make_sync_tool_wrapper(tool.coroutine, tool.name)
    
    return tools
```

### 4.9.2 MCP 服务器配置构建

**DeerFlow 实现** (`deerflow/mcp/client.py`):

```python
def build_server_params(server_name: str, config: McpServerConfig) -> dict[str, Any]:
    """Build server parameters for MultiServerMCPClient."""
    
    transport_type = config.type or "stdio"
    params: dict[str, Any] = {"transport": transport_type}
    
    if transport_type == "stdio":
        # 标准输入/输出传输
        params["command"] = config.command
        params["args"] = config.args
        if config.env:
            params["env"] = config.env
    
    elif transport_type in ("sse", "http"):
        # HTTP/SSE 传输
        params["url"] = config.url
        if config.headers:
            params["headers"] = config.headers
    
    return params

def build_servers_config(extensions_config: ExtensionsConfig) -> dict[str, dict[str, Any]]:
    """Build servers configuration for MultiServerMCPClient."""
    
    enabled_servers = extensions_config.get_enabled_mcp_servers()
    servers_config = {}
    
    for server_name, server_config in enabled_servers.items():
        servers_config[server_name] = build_server_params(server_name, server_config)
    
    return servers_config
```

**支持的传输类型**:

| 传输类型 | 参数 | 说明 |
|---------|------|------|
| `stdio` | `command`, `args`, `env` | 通过标准输入/输出通信 |
| `sse` | `url`, `headers` | Server-Sent Events 传输 |
| `http` | `url`, `headers` | HTTP 请求/响应传输 |

### 4.9.3 MCP 工具拦截器 — `tool_interceptors`

**作用**: 在工具调用前后拦截并修改行为，如注入 OAuth 认证头。

**接口定义**:

```python
# 拦截器签名
async def tool_interceptor(
    request: Any,      # 工具调用请求
    handler: Callable # 原始处理器
) -> Any:              # 处理结果
    # 在调用前/后修改请求或响应
    return await handler(request)
```

### 4.9.4 `OAuthTokenManager` — OAuth 令牌管理器

**来源**: DeerFlow 自实现 (`deerflow/mcp/oauth.py`)

**作用**: 为 MCP HTTP/SSE 服务器自动获取、缓存和刷新 OAuth 令牌。

```python
class OAuthTokenManager:
    """Acquire/cache/refresh OAuth tokens for MCP servers."""
    
    def __init__(self, oauth_by_server: dict[str, McpOAuthConfig]):
        self._oauth_by_server = oauth_by_server
        self._tokens: dict[str, _OAuthToken] = {}  # 缓存的令牌
        self._locks: dict[str, asyncio.Lock] = {
            name: asyncio.Lock() for name in oauth_by_server
        }
    
    async def get_authorization_header(self, server_name: str) -> str | None:
        """获取指定服务器的 Authorization 头。
        
        如果令牌已过期，自动刷新。
        """
        oauth = self._oauth_by_server.get(server_name)
        if not oauth:
            return None
        
        token = self._tokens.get(server_name)
        if token and not self._is_expiring(token, oauth):
            return f"{token.token_type} {token.access_token}"
        
        # 双重检查锁定
        lock = self._locks[server_name]
        async with lock:
            token = self._tokens.get(server_name)
            if token and not self._is_expiring(token, oauth):
                return f"{token.token_type} {token.access_token}"
            
            # 刷新令牌
            fresh = await self._fetch_token(oauth)
            self._tokens[server_name] = fresh
            return f"{fresh.token_type} {fresh.access_token}"
    
    async def _fetch_token(self, oauth: McpOAuthConfig) -> _OAuthToken:
        """从 OAuth 服务器获取新令牌。"""
        data = {
            "grant_type": oauth.grant_type,
            **oauth.extra_token_params,
        }
        
        if oauth.scope:
            data["scope"] = oauth.scope
        if oauth.audience:
            data["audience"] = oauth.audience
        
        # client_credentials 或 refresh_token 模式
        if oauth.grant_type == "client_credentials":
            data["client_id"] = oauth.client_id
            data["client_secret"] = oauth.client_secret
        elif oauth.grant_type == "refresh_token":
            data["refresh_token"] = oauth.refresh_token
            if oauth.client_id:
                data["client_id"] = oauth.client_id
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(oauth.token_url, data=data)
            response.raise_for_status()
            payload = response.json()
        
        return _OAuthToken(
            access_token=payload.get(oauth.token_field),
            token_type=str(payload.get(oauth.token_type_field, "Bearer")),
            expires_at=datetime.now(UTC) + timedelta(seconds=payload.get("expires_in", 3600))
        )
```

### 4.9.5 MCP OAuth 拦截器构建

```python
def build_oauth_tool_interceptor(extensions_config: ExtensionsConfig) -> Any | None:
    """构建注入 OAuth Authorization 头的工具拦截器。"""
    token_manager = OAuthTokenManager.from_extensions_config(extensions_config)
    if not token_manager.has_oauth_servers():
        return None
    
    async def oauth_interceptor(request: Any, handler: Any) -> Any:
        header = await token_manager.get_authorization_header(request.server_name)
        if not header:
            return await handler(request)
        
        # 注入 Authorization 头
        updated_headers = dict(request.headers or {})
        updated_headers["Authorization"] = header
        return await handler(request.override(headers=updated_headers))
    
    return oauth_interceptor
```

### 4.9.6 MCP 完整集成流程

```
┌─────────────────────────────────────────────────────────────────┐
│                  MCP Tool Loading Flow                            │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 1. Load Extensions Config                                 │   │
│  │                                                          │   │
│  │    extensions_config = ExtensionsConfig.from_file()       │   │
│  │    ├── mcp_servers:                                       │   │
│  │    │   ├── github: {type: "stdio", command: "npx", ...}  │   │
│  │    │   └── filesystem: {type: "http", url: "http://..."} │   │
│  │    └── oauth:                                             │   │
│  │        └── github: {grant_type: "client_credentials", ...} │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 2. Build Servers Config                                  │   │
│  │                                                          │   │
│  │    servers_config = build_servers_config(extensions)      │   │
│  │    ├── github: {transport: "stdio", command: "npx", ...} │   │
│  │    └── filesystem: {transport: "http", url: "http://"}  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 3. Build OAuth Interceptors (if needed)                   │   │
│  │                                                          │   │
│  │    token_manager = OAuthTokenManager.from_config(ext)     │   │
│  │    oauth_interceptor = build_oauth_tool_interceptor(ext)  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 4. Create MultiServerMCPClient                           │   │
│  │                                                          │   │
│  │    client = MultiServerMCPClient(                         │   │
│  │        servers=servers_config,                            │   │
│  │        tool_interceptors=[oauth_interceptor],             │   │
│  │        tool_name_prefix=True                             │   │
│  │    )                                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 5. Get Tools from All Servers                             │   │
│  │                                                          │   │
│  │    tools = await client.get_tools()                       │   │
│  │    # [github__create_issue, github__list_repos,           │   │
│  │    #  filesystem__read_file, ...]                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 6. Patch for Sync Invocation                             │   │
│  │                                                          │   │
│  │    for tool in tools:                                     │   │
│  │        if tool.coroutine and not tool.func:              │   │
│  │            tool.func = sync_wrapper(tool.coroutine)      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 4.9.7 MCP OAuth 配置结构

```python
# McpOAuthConfig 结构
class McpOAuthConfig:
    """OAuth configuration for an MCP server."""
    
    enabled: bool = False
    grant_type: Literal["client_credentials", "refresh_token"]
    token_url: str
    
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    
    scope: str | None = None
    audience: str | None = None
    
    # 令牌字段配置
    token_field: str = "access_token"
    token_type_field: str = "token_type"
    expires_in_field: str = "expires_in"
    default_token_type: str = "Bearer"
    
    # 刷新策略
    refresh_skew_seconds: int = 30  # 提前多少秒刷新
    
    # 额外参数
    extra_token_params: dict[str, str] = {}
```

### 4.9.8 MCP 服务器配置示例 (config.yaml)

```yaml
mcpServers:
  github:
    enabled: true
    type: stdio
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
  
  filesystem:
    enabled: true
    type: http
    url: http://localhost:3000/mcp
    headers:
      Authorization: "Bearer ${FILESYSTEM_TOKEN}"
  
  search:
    enabled: true
    type: sse
    url: http://localhost:8080/sse
    oauth:
      enabled: true
      grant_type: client_credentials
      token_url: https://auth.example.com/oauth/token
      client_id: "${SEARCH_CLIENT_ID}"
      client_secret: "${SEARCH_CLIENT_SECRET}"
      scope: "search:read"
```

---

## 4.10 工具格式转换

### 4.10.1 `convert_to_openai_function` — 工具转 OpenAI 函数格式

**来源**: `langchain_core.utils.function_calling`

**作用**: 将 LangChain `BaseTool` 转换为 OpenAI function calling 格式的字典。

**函数签名**:

```python
def convert_to_openai_function(
    tool: BaseTool | dict[str, Any],
    *,
    include_null_parameters: bool = True,
) -> dict[str, Any]:
    """Convert a LangChain tool to OpenAI function format.
    
    Args:
        tool: A LangChain BaseTool instance or a dict with tool definition.
        include_null_parameters: Whether to include null parameters.
    
    Returns:
        A dict in OpenAI function format:
        {
            "name": str,
            "description": str,
            "parameters": {
                "type": "object",
                "properties": {...},
                "required": [...]
            }
        }
    """
    ...
```

**DeerFlow 使用** (`deerflow/tools/builtins/tool_search.py:174`):

```python
from langchain_core.utils.function_calling import convert_to_openai_function

def search_deferred_tools(
    query: str,
    registry: DeferredToolRegistry,
) -> list[dict]:
    """搜索匹配的工具并返回 OpenAI 函数格式定义。"""
    matched = registry.search(query)
    tool_defs = [
        convert_to_openai_function(t.tool) 
        for t in matched[:MAX_RESULTS]
    ]
    return tool_defs
```

**OpenAI 函数格式结构**:

```python
{
    "name": "tool_name",           # 工具名称
    "description": "What it does",  # 工具描述
    "parameters": {                 # JSON Schema 格式
        "type": "object",
        "properties": {
            "arg1": {
                "type": "string",
                "description": "Description of arg1"
            }
        },
        "required": ["arg1"]
    }
}
```

### 4.10.2 `RunnableBinding` — 可绑定 Runnable

**来源**: `langchain_core.runnables`

**作用**: 创建一个绑定了参数或其他配置的 `Runnable`，可以多次调用而不需要重复传递相同参数。

**类型定义**:

```python
class RunnableBinding(Runnable[Input, Output]):
    """A Runnable that has bound arguments.
    
    Allows binding fixed kwargs to a Runnable, creating a new Runnable
    that can be called without specifying those kwargs each time.
    """
    
    bound: Runnable[Any, Any]
    """The underlying Runnable to bind arguments to."""
    
    kwargs: dict[str, Any]
    """The keyword arguments to bind."""
    
    config: RunnableConfig | None = None
    """Optional configuration to bind."""
    
    def __init__(
        self,
        bound: Runnable[Any, Any],
        *,
        kwargs: dict[str, Any] | None = None,
        config: RunnableConfig | None = None,
        **other_kwargs: Any,
    ):
        ...
    
    def invoke(self, input: Input, config: RunnableConfig | None = None, **kwargs: Any) -> Output:
        """Invoke with input and merged kwargs."""
        ...
    
    def batch(self, inputs: list[Input], config: RunnableConfig | None = None, **kwargs: Any) -> list[Output]:
        """Batch invoke with merged kwargs."""
        ...
```

**DeerFlow 使用** (`deerflow/models/openai_codex_provider.py:396`):

```python
from langchain_core.runnables import RunnableBinding

def bind_tools(self, tools: list, **kwargs: Any) -> RunnableBinding:
    """绑定工具到模型调用。"""
    
    formatted_tools = []
    for tool in tools:
        if isinstance(tool, BaseTool):
            fn = convert_to_openai_function(tool)
            formatted_tools.append({
                "type": "function",
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })
        elif isinstance(tool, dict):
            # 处理预格式化的工具
            ...
    
    # 返回绑定了工具的 RunnableBinding
    return RunnableBinding(
        bound=self,
        kwargs={"tools": formatted_tools},
        **kwargs
    )
```

**使用场景**:

```
┌─────────────────────────────────────────────────────────────────┐
│              RunnableBinding Usage Pattern                       │
│                                                                  │
│  Without Binding:                                                │
│                                                                  │
│    model.invoke(messages, tools=[tool1, tool2])  # 每次指定     │
│    model.invoke(messages, tools=[tool1, tool2])  # 重复指定     │
│                                                                  │
│  With RunnableBinding:                                           │
│                                                                  │
│    bound_model = model.bind_tools([tool1, tool2])               │
│    bound_model.invoke(messages)  # 不需要再指定 tools          │
│    bound_model.invoke(messages)  # 复用绑定                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.10.3 工具转换与绑定的完整流程

```
┌─────────────────────────────────────────────────────────────────┐
│         Tool Binding Flow (DeerFlow Codex Provider)              │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 1. Tools come from agent config                           │   │
│  │                                                          │   │
│  │    tools = get_available_tools(...)  # list[BaseTool]  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 2. Convert to OpenAI function format                      │   │
│  │                                                          │   │
│  │    for tool in tools:                                    │   │
│  │        fn = convert_to_openai_function(tool)              │   │
│  │        formatted = {                                     │   │
│  │            "type": "function",                           │   │
│  │            "name": fn["name"],                           │   │
│  │            "description": fn.get("description", ""),     │   │
│  │            "parameters": fn.get("parameters", {})        │   │
│  │        }                                                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 3. Create RunnableBinding with tools                      │   │
│  │                                                          │   │
│  │    bound_model = RunnableBinding(                        │   │
│  │        bound=codex_model,                                 │   │
│  │        kwargs={"tools": formatted_tools}                 │   │
│  │    )                                                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 4. Invoke bound model (tools auto-included)               │   │
│  │                                                          │   │
│  │    result = bound_model.invoke(messages)                  │   │
│  │    # messages + tools sent to API together               │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4.11 延迟工具注册表

### 4.11.1 `DeferredToolRegistry` — 延迟工具注册表

**来源**: DeerFlow 自实现 (`deerflow/tools/builtins/tool_search.py`)

**作用**: 管理延迟加载的工具注册表，支持通过正则表达式搜索工具名称和描述。

```python
@dataclass
class DeferredToolEntry:
    """延迟工具的轻量级元数据。"""
    
    name: str           # 工具名称
    description: str    # 工具描述
    tool: BaseTool     # 完整工具对象，仅在搜索匹配时返回


class DeferredToolRegistry:
    """可按正则表达式搜索的延迟工具注册表。"""
    
    def __init__(self):
        self._tools: dict[str, DeferredToolEntry] = {}
        self._lock = threading.Lock()
    
    def register(self, tool: BaseTool) -> None:
        """注册一个延迟工具。"""
        with self._lock:
            self._tools[tool.name] = DeferredToolEntry(
                name=tool.name,
                description=tool.description,
                tool=tool,
            )
    
    def search(self, pattern: str) -> list[DeferredToolEntry]:
        """按正则表达式搜索匹配的工具。"""
        regex = re.compile(pattern, re.IGNORECASE)
        matches = []
        
        with self._lock:
            for entry in self._tools.values():
                if regex.search(entry.name) or regex.search(entry.description):
                    matches.append(entry)
        
        return matches
    
    def get(self, name: str) -> DeferredToolEntry | None:
        """按名称获取工具条目。"""
        return self._tools.get(name)
    
    def list_all(self) -> list[DeferredToolEntry]:
        """列出所有注册的工具。"""
        with self._lock:
            return list(self._tools.values())
```

### 4.11.2 延迟工具搜索流程

```
┌─────────────────────────────────────────────────────────────────┐
│              Deferred Tool Search Flow                            │
│                                                                  │
│  Agent sees in context:                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ <available-deferred-tools>                               │   │
│  │ - search_api: Search the web for information            │   │
│  │ - image_gen: Generate images from descriptions           │   │
│  │ - code_exec: Execute code in a sandbox                  │   │
│  │ </available-deferred-tools>                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Agent calls tool_search(query="code")                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Registry.search("code") matches:                          │   │
│  │ - code_exec: Execute code in a sandbox                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Return OpenAI function definitions:                       │   │
│  │ [convert_to_openai_function(code_exec.tool), ...]        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Agent can now call code_exec with full schema             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. 中间件系统

### 5.1 `AgentMiddleware` — 中间件基类

**来源**: `langchain.agents.middleware`

**模块路径**: `langchain.agents.middleware.AgentMiddleware`

**类型定义**:

```python
class AgentMiddleware(Generic[StateT], ABC):
    """Base class for agent middleware."""
    
    state_schema: type[StateT] | None = None
    
    def before_agent(
        self,
        state: StateT,
        runtime: Runtime,
    ) -> dict | None:
        """Called before the agent processes a turn.
        
        Return a state update dict to modify state before agent execution.
        """
        return None
    
    def after_agent(
        self,
        state: StateT,
        runtime: Runtime,
    ) -> dict | None:
        """Called after the agent finishes a turn."""
        return None
    
    def before_model(
        self,
        state: StateT,
        runtime: Runtime,
    ) -> dict | None:
        """Called before the model is called.
        
        Return a state update dict to modify the model input.
        """
        return None
    
    def after_model(
        self,
        state: StateT,
        runtime: Runtime,
    ) -> dict | None:
        """Called after the model responds.
        
        Return a state update dict to modify the model output.
        """
        return None
    
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Called around each tool execution.
        
        Wrap the handler to intercept tool calls.
        """
        return handler(request)
    
    # Async versions
    async def abefore_agent(...) -> dict | None: ...
    async def aafter_agent(...) -> dict | None: ...
    async def abefore_model(...) -> dict | None: ...
    async def aafter_model(...) -> dict | None: ...
    async def awrap_tool_call(...) -> ToolMessage | Command: ...
```

**DeerFlow 中间件继承示例** (`deerflow/guardrails/middleware.py:20`):

```python
class GuardrailMiddleware(AgentMiddleware[AgentState]):
    """评估工具调用，拒绝不符合策略的请求"""
    
    def __init__(self, provider: GuardrailProvider, *, fail_closed: bool = True, passport: str | None = None):
        self.provider = provider
        self.fail_closed = fail_closed
        self.passport = passport
    
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        # 构建评估请求
        gr = self._build_request(request)
        
        try:
            decision = self.provider.evaluate(gr)
        except GraphBubbleUp:
            raise  # 保留 LangGraph 控制流信号
        except Exception:
            if self.fail_closed:
                decision = GuardrailDecision(allow=False, ...)
            else:
                return handler(request)
        
        if not decision.allow:
            return self._build_denied_message(request, decision)
        
        return handler(request)
```

### 5.2 生命周期钩子详解

#### `before_agent` / `abefore_agent`

**调用时机**: Agent 处理一个回合之前

**典型用途**:
- 初始化沙箱环境
- 设置线程数据
- 注入初始上下文

**示例** (`deerflow/sandbox/middleware.py:52`):

```python
def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
    if self._lazy_init:
        return super().before_agent(state, runtime)
    
    if "sandbox" not in state or state["sandbox"] is None:
        thread_id = (runtime.context or {}).get("thread_id")
        if thread_id is None:
            return super().before_agent(state, runtime)
        
        sandbox_id = self._acquire_sandbox(thread_id)
        return {"sandbox": {"sandbox_id": sandbox_id}}
    
    return super().before_agent(state, runtime)
```

#### `after_agent` / `aafter_agent`

**调用时机**: Agent 完成一个回合之后

**典型用途**:
- 清理资源
- 释放沙箱
- 记录执行统计

**示例** (`deerflow/sandbox/middleware.py:68`):

```python
def after_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
    sandbox = state.get("sandbox")
    if sandbox is not None:
        sandbox_id = sandbox["sandbox_id"]
        get_sandbox_provider().release(sandbox_id)
        return None
    
    if (runtime.context or {}).get("sandbox_id") is not None:
        sandbox_id = runtime.context.get("sandbox_id")
        get_sandbox_provider().release(sandbox_id)
        return None
    
    return super().after_agent(state, runtime)
```

#### `before_model` / `abefore_model`

**调用时机**: 模型调用之前

**典型用途**:
- 修改提示词
- 注入系统消息
- 添加上下文

**示例** (`deerflow/agents/middlewares/todo_middleware.py:57`):

```python
def before_model(
    self,
    state: PlanningState,
    runtime: Runtime,
) -> dict[str, Any] | None:
    """检测 todo 是否仍在上下文窗口中"""
    todos: list[Todo] = state.get("todos") or []
    if not todos:
        return None
    
    messages = state.get("messages") or []
    if _todos_in_messages(messages):
        return None  # write_todos 仍在上下文中
    
    if _reminder_in_messages(messages):
        return None  # 提醒已注入
    
    # 注入提醒消息
    formatted = _format_todos(todos)
    reminder = HumanMessage(
        name="todo_reminder",
        content=f"<system_reminder>\nYour todo list...\n</system_reminder>",
    )
    return {"messages": [reminder]}
```

#### `after_model` / `aafter_model`

**调用时机**: 模型调用之后

**典型用途**:
- 检测循环调用
- 注入警告消息
- 修改模型输出

**示例** (`deerflow/agents/middlewares/loop_detection_middleware.py:212`):

```python
def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
    warning, hard_stop = self._track_and_check(state, runtime)
    
    if hard_stop:
        # 强制停止：剥离 tool_calls
        messages = state.get("messages", [])
        last_msg = messages[-1]
        stripped_msg = last_msg.model_copy(
            update={
                "tool_calls": [],
                "content": (last_msg.content or "") + f"\n\n{_HARD_STOP_MSG}",
            }
        )
        return {"messages": [stripped_msg]}
    
    if warning:
        # 注入警告
        return {"messages": [HumanMessage(content=warning)]}
    
    return None
```

#### `wrap_tool_call` / `awrap_tool_call`

**调用时机**: 每个工具调用前后

**典型用途**:
- 工具权限检查
- 错误处理
- 工具调用拦截

**示例** (`deerflow/agents/middlewares/clarification_middleware.py:132`):

```python
def wrap_tool_call(
    self,
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    # 检查是否为 clarification 工具
    if request.tool_call.get("name") != "ask_clarification":
        return handler(request)  # 正常执行
    
    return self._handle_clarification(request)  # 拦截处理
```

### 5.3 中间件执行顺序

```
┌─────────────────────────────────────────────────────────────────┐
│                  Middleware Execution Order                      │
│                                                                  │
│  Agent Stream Flow:                                              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ before_agent ──► [Middleware #1] ──► [Middleware #2]     │    │
│  │                      │                │                  │    │
│  │                      ▼                ▼                  │    │
│  │                 before_model    before_model            │    │
│  │                      │                │                  │    │
│  │                      ▼                ▼                  │    │
│  │                 [Model Call]    [Model Call]             │    │
│  │                      │                │                  │    │
│  │                      ▼                ▼                  │    │
│  │                 after_model     after_model             │    │
│  │                      │                │                  │    │
│  │                      ▼                ▼                  │    │
│  │           wrap_tool_call ◄───────────┘                  │    │
│  │                      │                                   │    │
│  │                      ▼                                   │    │
│  │              [Tool Execution]                            │    │
│  │                      │                                   │    │
│  │                      ▼                                   │    │
│  │           after_agent ◄──────────────────────────────────│    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  Middleware Chain (DeerFlow):                                    │
│                                                                  │
│  1. ThreadDataMiddleware     - 线程数据初始化                   │
│  2. UploadsMiddleware        - 上传文件处理                      │
│  3. SandboxMiddleware        - 沙箱环境管理                      │
│  4. SummarizationMiddleware  - 上下文截断                        │
│  5. TodoListMiddleware       - 任务列表管理                      │
│  6. TokenUsageMiddleware      - Token 统计                        │
│  7. TitleMiddleware          - 标题生成                          │
│  8. MemoryMiddleware         - 记忆管理                          │
│  9. ViewImageMiddleware       - 图片查看                         │
│  10. DeferredToolFilterMiddleware - 工具过滤                     │
│  11. SubagentLimitMiddleware  - 子代理限制                       │
│  12. LoopDetectionMiddleware  - 循环检测                         │
│  13. ClarificationMiddleware  - 澄清请求                         │
│  14. ToolErrorHandlingMiddleware - 错误处理                       │
│  15. GuardrailMiddleware      - 安全防护                         │
└─────────────────────────────────────────────────────────────────┘
```

### 5.4 `SummarizationMiddleware` — 上下文截断中间件

**来源**: `langchain.agents.middleware`

**作用**: 当对话历史过长时，自动对早期消息进行摘要，保留关键信息同时减少 token 消耗。

**DeerFlow 配置示例** (`deerflow/agents/lead_agent/agent.py:41`):

```python
def _create_summarization_middleware() -> SummarizationMiddleware | None:
    config = get_summarization_config()
    
    if not config.enabled:
        return None
    
    # 配置触发条件
    trigger = None
    if config.trigger is not None:
        if isinstance(config.trigger, list):
            trigger = [t.to_tuple() for t in config.trigger]
        else:
            trigger = config.trigger.to_tuple()
    
    # 配置保留内容
    keep = config.keep.to_tuple()
    
    # 创建摘要模型
    if config.model_name:
        model = create_chat_model(name=config.model_name, thinking_enabled=False)
    else:
        model = create_chat_model(thinking_enabled=False)
    
    kwargs = {
        "model": model,
        "trigger": trigger,
        "keep": keep,
    }
    
    if config.trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = config.trim_tokens_to_summarize
    
    if config.summary_prompt is not None:
        kwargs["summary_prompt"] = config.summary_prompt
    
    return SummarizationMiddleware(**kwargs)
```

### 5.5 `TodoListMiddleware` — 任务列表中间件

**来源**: `langchain.agents.middleware`

**作用**: 提供 `write_todos` 工具，让 Agent 能够创建和管理结构化任务列表。

**Todo 数据结构** (`langchain.agents.middleware.todo.Todo`):

```python
class Todo(TypedDict):
    """A todo item in the planning state."""
    
    id: str           # 唯一 ID
    content: str      # 任务描述
    status: Literal["pending", "in_progress", "completed"]
    priority: Literal["low", "medium", "high"] | None = None
```

**PlanningState 结构**:

```python
class PlanningState(AgentState):
    """State for agents with todo list support."""
    
    todos: NotRequired[list[Todo] | None]
```

**DeerFlow 扩展** (`deerflow/agents/middlewares/todo_middleware.py`):

```python
class TodoMiddleware(TodoListMiddleware):
    """扩展 TodoListMiddleware，检测上下文丢失"""
    
    def before_model(
        self,
        state: PlanningState,
        runtime: Runtime,
    ) -> dict[str, Any] | None:
        """当消息历史被截断时，检测 todo 丢失并注入提醒"""
        todos = state.get("todos") or []
        if not todos:
            return None
        
        messages = state.get("messages") or []
        
        # 检测 write_todos 是否仍在可见上下文中
        if _todos_in_messages(messages):
            return None
        
        # 检测是否已有提醒
        if _reminder_in_messages(messages):
            return None
        
        # 注入提醒消息
        formatted = _format_todos(todos)
        reminder = HumanMessage(
            name="todo_reminder",
            content=(
                "<system_reminder>\n"
                "Your todo list from earlier is no longer visible...\n"
                f"{formatted}\n"
                "Continue tracking and updating this todo list.\n"
                "</system_reminder>"
            ),
        )
        return {"messages": [reminder]}
```

---

## 6. 状态管理与 State Schema

### 6.1 状态模式设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                State Schema Design Principles                    │
│                                                                  │
│  1. Inherit from AgentState                                     │
│     ┌─────────────────────────────────────────┐                 │
│     │ AgentState (from langchain.agents)      │                 │
│     │  └── messages: Annotated[list, reducer] │                 │
│     └─────────────────────────────────────────┘                 │
│                       │                                          │
│                       ▼                                          │
│     ┌─────────────────────────────────────────┐                 │
│     │ ThreadState (DeerFlow custom)           │                 │
│     │  └── + sandbox, thread_data, artifacts  │                 │
│     └─────────────────────────────────────────┘                 │
│                                                                  │
│  2. Use Annotated for merge-able fields                          │
│                                                                  │
│     artifacts: Annotated[list[str], merge_artifacts]             │
│                                                                  │
│  3. Use NotRequired for optional fields                          │
│                                                                  │
│     title: NotRequired[str | None]                              │
│                                                                  │
│  4. Reducer functions control merge behavior                    │
│                                                                  │
│     def merge_artifacts(existing, new):                         │
│         return list(dict.fromkeys(existing + new))              │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 状态合并规则

| 字段类型 | 合并策略 | 示例 |
|---------|---------|------|
| `list` + Annotated[reducer] | 调用 reducer 函数 | `artifacts: Annotated[list[str], merge_artifacts]` |
| `dict` + Annotated[reducer] | 调用 reducer 函数 | `viewed_images: Annotated[dict, merge_viewed_images]` |
| 普通字段 | 直接覆盖 | `title = "new title"` |
| `NotRequired[T]` | 仅在提供值时更新 | `todos: NotRequired[list]` |

### 6.3 完整状态流

```
┌─────────────────────────────────────────────────────────────────┐
│                     State Update Flow                             │
│                                                                  │
│  ┌─────────────┐                                                │
│  │    State    │                                                │
│  │             │                                                │
│  │ messages:   │                                                │
│  │ [H, A, T]  │                                                │
│  │             │                                                │
│  │ artifacts: │                                                │
│  │ [f1, f2]   │                                                │
│  │             │                                                │
│  │ todos:     │                                                │
│  │ [t1, t2]   │                                                │
│  └──────┬──────┘                                                │
│         │                                                        │
│         │ Command(update={...})                                 │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Reducers                               │   │
│  │                                                           │   │
│  │  messages: add_messages(existing, new)                     │   │
│  │             └── append with dedup by ID                   │   │
│  │                                                           │   │
│  │  artifacts: merge_artifacts(existing, new)                 │   │
│  │             └── concat + dict.fromkeys dedup              │   │
│  │                                                           │   │
│  │  viewed_images: merge_viewed_images(existing, new)         │   │
│  │             └── dict merge, {} means clear                │   │
│  │                                                           │   │
│  │  title: lambda e, n: n  (last write wins)                  │   │
│  │                                                           │   │
│  │  todos: lambda e, n: n  (last write wins)                 │   │
│  │                                                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────┐                                                │
│  │    New      │                                                │
│  │   State     │                                                │
│  │             │                                                │
│  │ messages:   │                                                │
│  │ [H, A, T,   │                                                │
│  │  H2, A2, T2]│                                                │
│  │             │                                                │
│  │ artifacts:  │                                                │
│  │ [f1, f2,    │                                                │
│  │  f3, f4]    │                                                │
│  │             │                                                │
│  │ todos:     │                                                │
│  │ [t1, t2,    │                                                │
│  │  t3]        │                                                │
│  └─────────────┘                                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 控制流与状态更新

### 7.1 `Command` — 状态更新与跳转指令

**来源**: `langgraph.types`

**模块路径**: `langgraph.types.Command`

**作用**: 在工具或中间件中返回，用于更新状态和控制执行流程。

**类型定义**:

```python
class Command(Generic[UpdateType]):
    """A command to update state and control graph execution."""
    
    update: UpdateType | None = None
    """State update to merge into the current state."""
    
    goto: str | Sequence[str] | None = None
    """Where to go next in the graph. None means continue normally."""
    
    resume: Any | None = None
    """Value to resume with if this is a interrupt resumption."""
    
    graph: Literal["appliance"] | None = None
    """Which graph to execute in. None means current graph."""
    
    def __init__(
        self,
        update: UpdateType | None = None,
        goto: str | Sequence[str] | None = None,
        resume: Any | None = None,
    ):
        ...
```

**`goto` 参数详解**:

| 值 | 行为 |
|---|------|
| `None` | 继续正常执行流程 |
| `END` | 结束当前回合 |
| `"node_name"` | 跳转到指定节点 |
| `["node1", "node2"]` | 并行跳转到多个节点 |

**DeerFlow 使用示例 1** — 工具返回并中断 (`deerflow/tools/builtins/setup_agent_tool.py:48`):

```python
return Command(
    update={
        "created_agent_name": agent_name,
        "messages": [
            ToolMessage(
                content=f"Agent '{agent_name}' created successfully!",
                tool_call_id=runtime.tool_call_id
            )
        ],
    }
)
# goto=None 表示继续正常执行
```

**DeerFlow 使用示例 2** — 工具返回并中断等待用户 (`deerflow/agents/middlewares/clarification_middleware.py:126`):

```python
return Command(
    update={"messages": [tool_message]},
    goto=END,  # 中断执行，等待用户响应
)
```

**DeerFlow 使用示例 3** — 条件跳转 (`deerflow/tools/builtins/present_file_tool.py`):

```python
# 根据条件决定是否中断
if should_interrupt:
    return Command(update={"artifacts": [path]}, goto=END)
return Command(update={"artifacts": [path]})
```

### 7.2 `END` — 结束节点

**来源**: `langgraph.graph`

**模块路径**: `langgraph.graph.END`

**作用**: 表示图执行的结束。

```python
END = "__end__"
```

**使用场景**: 在 `Command.goto` 中使用，表示中断当前执行并结束回合。

### 7.3 `GraphBubbleUp` — 控制流信号

**来源**: `langgraph.errors`

**作用**: 在中间件中重新抛出，用于保留 LangGraph 的控制流信号（如 `interrupt`、`pause`、`resume`）。

**类型定义**:

```python
class GraphBubbleUp(Exception):
    """An exception that bubbles up through the graph without stopping execution.
    
    Used to signal control flow decisions (interrupt, pause, resume) without
    aborting the graph execution.
    """
    
    value: Any = None
    
    def __init__(self, value: Any = None):
        self.value = value
        super().__init__(str(value) if value else "")
```

**使用示例** (`deerflow/guardrails/middleware.py:63`):

```python
def wrap_tool_call(
    self,
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    try:
        decision = self.provider.evaluate(gr)
    except GraphBubbleUp:
        # Preserve LangGraph control-flow signals (interrupt/pause/resume).
        raise  # 重新抛出，保留信号
    except Exception:
        # 处理评估异常
        if self.fail_closed:
            decision = GuardrailDecision(allow=False, ...)
        else:
            return handler(request)
    
    if not decision.allow:
        return self._build_denied_message(request, decision)
    
    return handler(request)
```

### 7.4 `GraphInterrupt` — 图中断

**来源**: `langgraph.errors`

**作用**: 用于中断图执行的异常。

```python
class GraphInterrupt(Exception):
    """An interrupt that stops graph execution.
    
    Unlike GraphBubbleUp, this stops execution entirely until resumed.
    """
    
    resume_value: Any = None
```

---

## 8. 检查点与持久化

### 8.1 `Checkpointer` — 检查点接口

**来源**: `langgraph.types`

**模块路径**: `langgraph.types.Checkpointer`

**作用**: 定义状态持久化的接口，支持多轮对话的状态恢复。

**类型定义**:

```python
class Checkpointer(ABC, Generic[StateT]):
    """Interface for state persistence across conversation turns."""
    
    @abstractmethod
    def get(
        self,
        config: RunnableConfig,
    ) -> dict[str, Any] | None:
        """Get the state for a given config (thread_id)."""
        ...
    
    @abstractmethod
    def put(
        self,
        config: RunnableConfig,
        state: StateT,
    ) -> RunnableConfig:
        """Save state for a given config."""
        ...
    
    @abstractmethod
    def get_next_version(
        self,
        version: str | None,
        config: RunnableConfig,
    ) -> str:
        """Get the next version for a given config."""
        ...
```

### 8.2 `InMemorySaver` — 内存检查点

**来源**: `langgraph.checkpoint.memory`

**作用**: 将状态存储在内存中，适合开发、测试或单进程环境。

**类型定义**:

```python
class InMemorySaver(Checkpointer):
    """In-memory checkpointer.
    
    Stores state in a dictionary. Data is lost on process restart.
    """
    
    def __init__(self):
        self._checkpoints: dict[str, dict] = {}
        self._metadata: dict[str, dict] = {}
```

**DeerFlow 使用** (`deerflow/agents/checkpointer/provider.py:148`):

```python
from langgraph.checkpoint.memory import InMemorySaver

def get_checkpointer() -> Checkpointer:
    global _checkpointer, _checkpointer_ctx
    
    # ... 配置检查
    if config is None:
        from langgraph.checkpoint.memory import InMemorySaver
        _checkpointer = InMemorySaver()
        return _checkpointer
```

### 8.3 `SqliteSaver` — SQLite 检查点

**来源**: `langgraph.checkpoint.sqlite`

**作用**: 基于 SQLite 的持久化存储，数据存储在本地文件。

**类型定义**:

```python
class SqliteSaver(Checkpointer):
    """SQLite-based checkpointer."""
    
    @classmethod
    def from_conn_string(cls, conn_str: str) -> SqliteSaver:
        """Create from a connection string."""
        ...
    
    def setup(self) -> None:
        """Initialize the database schema."""
        ...
    
    def get(self, config: RunnableConfig) -> dict | None: ...
    def put(self, config: RunnableConfig, state: dict) -> RunnableConfig: ...
```

**DeerFlow 使用** (`deerflow/agents/checkpointer/provider.py:76`):

```python
from langgraph.checkpoint.sqlite import SqliteSaver

if config.type == "sqlite":
    from langgraph.checkpoint.sqlite import SqliteSaver
    
    conn_str = _resolve_sqlite_conn_str(config.connection_string or "store.db")
    with SqliteSaver.from_conn_string(conn_str) as saver:
        saver.setup()
        yield saver
```

### 8.4 `AsyncSqliteSaver` — 异步 SQLite 检查点

**来源**: `langgraph.checkpoint.sqlite.aio`

**作用**: `SqliteSaver` 的异步版本。

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
```

### 8.5 `PostgresSaver` — PostgreSQL 检查点

**来源**: `langgraph.checkpoint.postgres`

**作用**: 基于 PostgreSQL 的生产级持久化存储，支持高并发和分布式部署。

**类型定义**:

```python
class PostgresSaver(Checkpointer):
    """PostgreSQL-based checkpointer."""
    
    @classmethod
    def from_conn_string(cls, conn_str: str) -> PostgresSaver:
        """Create from a PostgreSQL connection string."""
        ...
    
    def setup(self) -> None:
        """Initialize the database schema."""
        ...
```

**DeerFlow 使用** (`deerflow/agents/checkpointer/provider.py:88`):

```python
if config.type == "postgres":
    from langgraph.checkpoint.postgres import PostgresSaver
    
    if not config.connection_string:
        raise ValueError(POSTGRES_CONN_REQUIRED)
    
    with PostgresSaver.from_conn_string(config.connection_string) as saver:
        saver.setup()
        yield saver
```

### 8.6 `AsyncPostgresSaver` — 异步 PostgreSQL 检查点

**来源**: `langgraph.checkpoint.postgres.aio`

**作用**: `PostgresSaver` 的异步版本。

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
```

### 8.7 检查点使用流程

```
┌─────────────────────────────────────────────────────────────────┐
│                 Checkpoint Usage Flow                            │
│                                                                  │
│  1. Create Checkpointer                                          │
│     ┌─────────────────────────────────────────┐                 │
│     │  checkpointer = InMemorySaver()         │                 │
│     │  # or SqliteSaver / PostgresSaver       │                 │
│     └─────────────────────────────────────────┘                 │
│                                                                  │
│  2. Create Agent with Checkpointer                               │
│     ┌─────────────────────────────────────────┐                 │
│     │  agent = create_agent(                   │                 │
│     │      ...                                 │                 │
│     │      checkpointer=checkpointer,          │                 │
│     │  )                                       │                 │
│     └─────────────────────────────────────────┘                 │
│                                                                  │
│  3. Invoke with thread_id                                        │
│     ┌─────────────────────────────────────────┐                 │
│     │  config = RunnableConfig(               │                 │
│     │      configurable={"thread_id": "t1"}   │                 │
│     │  )                                       │                 │
│     │                                          │                 │
│     │  agent.invoke(state, config=config)      │                 │
│     └─────────────────────────────────────────┘                 │
│                                                                  │
│  4. Checkpointer stores state                                    │
│     ┌─────────────────────────────────────────┐                 │
│     │  checkpointer.put(config, state)        │                 │
│     │                                          │                 │
│     │  Storage:                               │                 │
│     │    thread_id=t1                          │                 │
│     │      └── checkpoint_001: {messages, ...} │                 │
│     │      └── checkpoint_002: {messages, ...} │                 │
│     └─────────────────────────────────────────┘                 │
│                                                                  │
│  5. Next invocation with same thread_id                          │
│     ┌─────────────────────────────────────────┐                 │
│     │  # State is automatically restored       │                 │
│     │  agent.invoke(state, config=config)      │                 │
│     │                                          │                 │
│     │  # Internal: state = checkpointer.get(config)              │
│     └─────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. 运行时配置

### 9.1 `RunnableConfig` — 运行配置

**来源**: `langchain_core.runnables`

**模块路径**: `langchain_core.runnables.RunnableConfig`

**作用**: 封装 Agent 运行时的配置参数。

**类型定义**:

```python
class RunnableConfig(TypedDict, total=False):
    """Configuration for a Runnable."""
    
    # 最大递归深度
    recursion_limit: int
    
    # 可配置参数（thread_id, model_name 等）
    configurable: dict[str, Any]
    
    # 元数据
    metadata: dict[str, Any]
    
    # 回调处理器
    callbacks: Callbacks
    
    # 标签
    tags: list[str] | None
    
    # 是否展开
    expandable: bool | None
    
    # 最大并发
    max_concurrency: int | None
```

**DeerFlow 使用** (`deerflow/client.py:185`):

```python
def _get_runnable_config(self, thread_id: str, **overrides) -> RunnableConfig:
    """构建 RunnableConfig"""
    configurable = {
        "thread_id": thread_id,
        "model_name": overrides.get("model_name", self._model_name),
        "thinking_enabled": overrides.get("thinking_enabled", self._thinking_enabled),
        "is_plan_mode": overrides.get("plan_mode", self._plan_mode),
        "subagent_enabled": overrides.get("subagent_enabled", self._subagent_enabled),
    }
    return RunnableConfig(
        configurable=configurable,
        recursion_limit=overrides.get("recursion_limit", 100),
    )
```

### 9.2 `Runtime` — 中间件运行时上下文

**来源**: `langgraph.runtime`

**作用**: 在中间件钩子中提供运行时上下文信息。

**类型定义**:

```python
class Runtime:
    """Runtime context available in middleware hooks."""
    
    config: RunnableConfig
    """当前运行的配置"""
    
    context: dict[str, Any]
    """运行时上下文（如 thread_id, agent_name 等）"""
```

**DeerFlow 使用** (`deerflow/sandbox/middleware.py:52`):

```python
def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
    thread_id = (runtime.context or {}).get("thread_id")
    if thread_id is None:
        return super().before_agent(state, runtime)
    
    sandbox_id = self._acquire_sandbox(thread_id)
    return {"sandbox": {"sandbox_id": sandbox_id}}
```

### 9.3 `ContextT` — 上下文类型参数

**来源**: `langgraph.typing`

**作用**: `ToolRuntime` 的泛型类型参数，定义上下文类型。

```python
from langgraph.typing import ContextT

# ToolRuntime[ContextT, StateT]
# ContextT 默认是 dict[str, Any]
# StateT 默认是 AgentState
```

---

## 10. 流式输出

### 10.1 `get_stream_writer` — 流式写入器

**来源**: `langgraph.config`

**作用**: 获取用于流式输出的写入器。

**函数签名**:

```python
def get_stream_writer() -> Callable[[dict], None]:
    """Get the stream writer for the current execution context."""
    ...
```

**DeerFlow 使用** (`deerflow/tools/builtins/task_tool.py:128`):

```python
from langgraph.config import get_stream_writer

writer = get_stream_writer()

# 发送任务开始事件
writer({"type": "task_started", "task_id": task_id, "description": description})

# 发送任务运行中消息
writer({
    "type": "task_running",
    "task_id": task_id,
    "message": message,
    "message_index": index,
    "total_messages": total,
})

# 发送任务完成事件
writer({"type": "task_completed", "task_id": task_id, "result": result})
```

### 10.2 `get_config` — 获取配置

**来源**: `langgraph.config`

**作用**: 获取当前执行配置。

```python
from langgraph.config import get_config

config = get_config()
# config 包含当前 runnable 配置
```

---

## 11. 模型与输出处理

### 11.1 `BaseChatModel` — 聊天模型基类

**来源**: `langchain.chat_models` / `langchain_core.language_models.chat_models`

**模块路径**: `langchain_core.language_models.chat_models.BaseChatModel`

**作用**: 所有聊天模型的基类。

**核心方法**:

```python
class BaseChatModel(BaseModel, ABC):
    """Base class for chat models."""
    
    @abstractmethod
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate a chat response."""
        ...
    
    @abstractmethod
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async version of _generate."""
        ...
    
    def stream(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Stream the response."""
        ...
```

### 11.2 `ChatResult` — 聊天结果

**来源**: `langchain_core.outputs`

**类型定义**:

```python
class ChatResult(TypedDict):
    """Result of a chat model generation."""
    
    generation_info: dict[str, Any] | None
    """Raw response metadata"""
    
    llm_output: dict[str, Any] | None
    """Deprecated, use generation_info"""
    
    generations: list[ChatGeneration]
    """List of generated responses"""
```

### 11.3 `ChatGeneration` — 聊天生成

**来源**: `langchain_core.outputs`

**类型定义**:

```python
class ChatGeneration(TypedDict):
    """A single chat generation."""
    
    text: str
    """The generated text content"""
    
    message: BaseMessage
    """The full message object"""
    
    generation_info: dict[str, Any] | None
    """Additional generation info"""
    
    type: Literal["ChatGeneration"] = "ChatGeneration"
```

### 11.4 `LanguageModelInput` — 模型输入

**来源**: `langchain_core.language_models`

**类型定义**:

```python
LanguageModelInput = str | list[BaseMessage] | dict[str, Any]
"""Input to a chat model."""
```

---

## 12. 追踪与监控

### 12.1 `LangChainTracer` — LangSmith 追踪

**来源**: `langchain_core.tracers.langchain`

**作用**: 将执行过程追踪到 LangSmith 平台。

**DeerFlow 使用** (`deerflow/models/factory.py:84`):

```python
from langchain_core.tracers.langchain import LangChainTracer

if is_tracing_enabled():
    tracing_config = get_tracing_config()
    tracer = LangChainTracer(
        project_name=tracing_config.project,
    )
    existing_callbacks = model_instance.callbacks or []
    model_instance.callbacks = [*existing_callbacks, tracer]
```

---

## 附录 A: 完整类型引用表

### LangChain Core

| 类/接口 | 模块路径 | 说明 |
|---------|---------|------|
| `create_agent` | `langchain.agents` | Agent 工厂函数 |
| `AgentState` | `langchain.agents` | Agent 状态基类 |
| `AgentMiddleware` | `langchain.agents.middleware` | 中间件基类 |
| `SummarizationMiddleware` | `langchain.agents.middleware` | 摘要中间件 |
| `TodoListMiddleware` | `langchain.agents.middleware` | Todo 列表中间件 |
| `PlanningState` | `langchain.agents.middleware.todo` | 规划状态 |
| `Todo` | `langchain.agents.middleware.todo` | Todo 项类型 |
| `BaseMessage` | `langchain_core.messages` | 消息基类 |
| `AIMessage` | `langchain_core.messages` | AI 消息 |
| `HumanMessage` | `langchain_core.messages` | 人类消息 |
| `ToolMessage` | `langchain_core.messages` | 工具消息 |
| `SystemMessage` | `langchain_core.messages` | 系统消息 |
| `AIMessageChunk` | `langchain_core.messages` | AI 消息块（流式） |
| `RunnableConfig` | `langchain_core.runnables` | 运行配置 |
| `tool` | `langchain_core.tools` | 工具装饰器 |
| `BaseTool` | `langchain_core.tools` | 工具基类 |
| `StructuredTool` | `langchain_core.tools` | 结构化工具 |
| `InjectedToolCallId` | `langchain.tools` | 工具调用 ID 注入 |
| `InjectedToolArg` | `langchain.tools` | 工具参数注入 |
| `LanguageModelInput` | `langchain_core.language_models` | 模型输入类型 |
| `BaseChatModel` | `langchain_core.language_models.chat_models` | 聊天模型基类 |
| `ChatGeneration` | `langchain_core.outputs` | 聊天生成 |
| `ChatGenerationChunk` | `langchain_core.outputs` | 聊天生成块 |
| `ChatResult` | `langchain_core.outputs` | 聊天结果 |
| `CallbackManagerForLLMRun` | `langchain_core.callbacks` | LLM 回调管理器 |
| `LangChainTracer` | `langchain_core.tracers.langchain` | LangSmith 追踪器 |

### LangGraph

| 类/接口 | 模块路径 | 说明 |
|---------|---------|------|
| `Command` | `langgraph.types` | 状态更新与控制指令 |
| `Checkpointer` | `langgraph.types` | 检查点接口 |
| `ToolRuntime` | `langgraph.prebuilt` | 工具运行时 |
| `ToolCallRequest` | `langgraph.prebuilt.tool_node` | 工具调用请求 |
| `GraphBubbleUp` | `langgraph.errors` | 控制流信号 |
| `GraphInterrupt` | `langgraph.errors` | 图中断异常 |
| `Runtime` | `langgraph.runtime` | 运行时上下文 |
| `END` | `langgraph.graph` | 结束节点标记 |
| `get_config` | `langgraph.config` | 获取配置 |
| `get_stream_writer` | `langgraph.config` | 获取流写入器 |
| `ContextT` | `langgraph.typing` | 上下文类型参数 |
| `InMemorySaver` | `langgraph.checkpoint.memory` | 内存检查点 |
| `SqliteSaver` | `langgraph.checkpoint.sqlite` | SQLite 检查点 |
| `AsyncSqliteSaver` | `langgraph.checkpoint.sqlite.aio` | 异步 SQLite 检查点 |
| `PostgresSaver` | `langgraph.checkpoint.postgres` | PostgreSQL 检查点 |
| `AsyncPostgresSaver` | `langgraph.checkpoint.postgres.aio` | 异步 PostgreSQL 检查点 |

---

## 附录 B: 依赖版本参考

```
langchain-core >= 0.3.0
langchain >= 0.3.0
langgraph >= 0.2.0
langgraph-checkpoint >= 2.0.0
langgraph-checkpoint-sqlite >= 2.0.0
langgraph-checkpoint-postgres >= 2.0.0
```

---

*文档生成时间: 2026-04-01*

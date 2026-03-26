# 02 - Phase 2: Agent 核心实现

> 预计时间: 5-7 天
> 
> **⭐⭐⭐⭐⭐ 本计划最核心的阶段！**
> 
> 本阶段目标：深入理解 DeerFlow 的核心 Agent 机制：ThreadState、Lead Agent、Middleware Chain

---

## 2.1 核心文件位置

```
backend/packages/harness/deerflow/agents/
├── lead_agent/                      # 主 Agent 工厂
│   ├── __init__.py
│   ├── agent.py                     # make_lead_agent() - 核心入口
│   ├── prompt.py                    # 系统提示词
│   └── __pycache__/
├── middlewares/                     # 13 个中间件
│   ├── __init__.py
│   ├── base.py                     # 中间件基类
│   ├── thread_data.py              # 线程数据处理
│   ├── uploads.py                  # 文件上传处理
│   ├── sandbox.py                  # 沙箱环境切换
│   ├── summarization.py            # 长对话摘要
│   ├── todo.py                     # TodoList 管理
│   ├── title.py                    # 生成对话标题
│   ├── memory.py                    # 记忆提取
│   ├── view_image.py               # 图片查看
│   ├── clarification.py            # 澄清问题处理
│   ├── guardrails.py               # 安全护栏
│   ├── token_usage.py              # Token 统计
│   └── reasoning_effort.py         # 推理强度
├── subagents/                      # SubAgent 委托系统
│   ├── __init__.py
│   ├── executor.py                 # SubAgent 执行器
│   └── registry.py                 # SubAgent 注册表
├── thread_state.py                 # ThreadState 数据结构
└── memory/                         # 记忆系统
    ├── __init__.py
    ├── extraction.py               # 记忆提取
    ├── queue.py                    # 记忆队列
    ├── updater.py                  # 记忆更新
    └── prompts.py                  # 记忆相关提示词
```

---

## 2.2 Step 1: 理解 ThreadState

**文件**: `backend/packages/harness/deerflow/agents/thread_state.py`

### 什么是 ThreadState？

ThreadState 是 Agent 的**状态容器**，定义了 Agent 在执行过程中需要维护的所有状态。类似于 React 的 useState，但它是**不可变的**。

### 核心代码解析

```python
from typing import TypedDict, Annotated
from langgraph.graph import add_messages

class ThreadState(TypedDict):
    """所有 Agent 状态都存储在这里"""
    
    # 消息列表 - 使用 add_messages reducer 实现追加
    messages: Annotated[list[BaseMessage], add_messages]
    
    # 线程标识
    thread_id: str
    user_id: str
    
    # 沙箱配置
    sandbox_type: str  # "local" | "docker" | "kubernetes"
    
    # 任务状态
    task: str | None
    result: str | None
    
    # 中间件数据 (key-value 存储)
    upload_ids: list[str]
    todo_list: list[dict]
    artifacts: list[str]
    
    # 模型配置
    model_name: str | None
    thinking_enabled: bool
    
    # 子 Agent 配置
    subagent_enabled: bool
    max_concurrent_subagents: int
    
    # 其他运行时状态
    title: str | None
    summarization_triggered: bool
    pending_clarification: dict | None
```

### 关键概念: Annotated + Reducer

```python
messages: Annotated[list[BaseMessage], add_messages]
```

这里使用了 LangGraph 的 **Annotated + Reducer** 模式：

| 概念 | 解释 |
|------|------|
| `Annotated` | 类型注解，给类型添加元数据 |
| `add_messages` | Reducer 函数，定义如何合并状态 |

### add_messages Reducer 详解

```python
from langgraph.graph import add_messages

# add_messages 的行为：
# - 新消息追加到列表末尾
# - 如果消息有 ID，更新已存在的消息
# - 支持多轮对话的状态累积

# 示例：
old_messages = [msg1, msg2]
new_messages = [msg3]
result = add_messages(old_messages, new_messages)
# result = [msg1, msg2, msg3]
```

### 为什么使用 Reducer 而不是直接修改？

| 方式 | 优点 | 缺点 |
|------|------|------|
| 直接修改 (`list.append()`) | 简单 | 无历史、难回滚、难调试 |
| Reducer (`add_messages`) | 可追踪、可回滚、利于 checkpoint | 需要定义合并规则 |

LangGraph 的 Checkpointing 机制依赖 Reducer 来实现状态的保存和恢复。

### 自定义 Reducer 示例

```python
from typing import TypedDict, Annotated
from operator import add

class CounterState(TypedDict):
    count: Annotated[int, add]  # 每次更新会累加
    history: Annotated[list[int], add_messages]  # 消息追加
```

---

## 2.3 Step 2: 理解 Lead Agent

**文件**: `backend/packages/harness/deerflow/agents/lead_agent/agent.py`

### 什么是 Lead Agent？

Lead Agent 是 DeerFlow 的**主控 Agent**，负责：
1. 接收用户消息
2. 分解复杂任务
3. 调度 SubAgent 执行
4. 调用工具
5. 返回响应

### make_lead_agent 函数解析

```python
def make_lead_agent(
    config: RunnableConfig,
) -> CompiledStateGraph:
    """创建 Lead Agent 的工厂函数"""
    
    # 1. 从 config 中提取参数
    cfg = config.get("configurable", {})
    thinking_enabled = cfg.get("thinking_enabled", True)
    reasoning_effort = cfg.get("reasoning_effort", None)
    requested_model_name = cfg.get("model_name") or cfg.get("model")
    subagent_enabled = cfg.get("subagent_enabled", False)
    max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
    agent_name = cfg.get("agent_name")  # 自定义 Agent 名称
    
    # 2. 解析模型配置
    agent_config = load_agent_config(agent_name) if agent_name else None
    agent_model_name = agent_config.model if agent_config else _resolve_model_name()
    model_name = requested_model_name or agent_model_name
    
    # 3. 创建 Chat Model
    model = create_chat_model(
        name=model_name,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )
    
    # 4. 获取可用工具
    tools = get_available_tools(
        model_name=model_name,
        subagent_enabled=subagent_enabled,
    )
    
    # 5. 构建中间件链
    middleware = _build_middlewares(config, model_name=model_name)
    
    # 6. 生成系统提示词
    system_prompt = apply_prompt_template(
        agent_name=agent_name,
        subagent_enabled=subagent_enabled,
        max_concurrent_subagents=max_concurrent_subagents,
    )
    
    # 7. 创建并返回 StateGraph
    return create_agent(
        model=model,
        tools=tools,
        middleware=middleware,
        system_prompt=system_prompt,
        state_schema=ThreadState,
    )
```

### create_agent 函数解析

```python
def create_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool | ToolNode],
    middleware: list[AgentMiddleware],
    system_prompt: str,
    state_schema: type,
) -> CompiledStateGraph:
    """构建 LangGraph StateGraph"""
    
    # 1. 创建空图
    builder = StateGraph(state_schema)
    
    # 2. 添加节点
    builder.add_node("agent", agent_node)
    
    # 3. 设置入口点
    builder.set_entry_point("agent")
    
    # 4. 添加条件边 (判断是否继续)
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "continue": "agent",  # 继续执行
            "end": END,           # 结束
        }
    )
    
    # 5. 编译图 (注入中间件)
    graph = builder.compile(middleware=middleware)
    
    return graph
```

### LangGraph StateGraph 概念

```
┌─────────────────────────────────────────┐
│              StateGraph                  │
│                                          │
│  ┌──────────┐                            │
│  │  START   │                            │
│  └────┬─────┘                            │
│       ↓                                    │
│  ┌──────────┐                            │
│  │  agent   │ ←── 系统提示词 + 模型       │
│  │  node    │                            │
│  └────┬─────┘                            │
│       ↓ should_continue()                │
│  ┌─────────────────┐                     │
│  │  continue?      │                     │
│  └────┬───────┬────┘                     │
│       ↓       ↓                          │
│      yes      no                         │
│       ↓       ↓                          │
│   [agent]    [END]                       │
│                                          │
│  Middleware 在编译时注入                   │
└─────────────────────────────────────────┘
```

### Agent Node 的执行逻辑

```python
def agent_node(state: ThreadState) -> dict:
    """Agent 节点的核心逻辑"""
    
    # 1. 获取当前消息
    messages = state["messages"]
    
    # 2. 调用模型 (带工具绑定)
    response = model.bind_tools(tools).invoke(messages)
    
    # 3. 返回增量更新 (不是全量状态!)
    return {"messages": [response]}
```

### interrupt_before / interrupt_after

DeerFlow 支持 **Human-in-the-Loop** 模式：

| 参数 | 作用 |
|------|------|
| `interrupt_before` | 在执行某个节点前暂停，等待人类确认 |
| `interrupt_after` | 在执行某个节点后暂停，等待人类确认 |

```python
# 示例：在调用工具前暂停
graph = builder.compile(
    interrupt_before=["tools"],
    middleware=middleware,
)
```

---

## 2.4 Step 3: Middleware Chain

**文件**: `backend/packages/harness/deerflow/agents/middlewares/`

### 什么是 Middleware？

Middleware 是**拦截 Agent 执行的钩子**，类似于 Express.js 的中间件或 Django 的 Middleware。

### DeerFlow 的 13 个中间件

| 顺序 | Middleware | 作用 | 重要性 |
|------|------------|------|--------|
| 1 | thread_data | 线程数据处理 | ⭐⭐⭐ |
| 2 | uploads | 文件上传处理 | ⭐⭐⭐ |
| 3 | sandbox | 沙箱环境切换 | ⭐⭐⭐⭐ |
| 4 | summarization | 长对话自动摘要 | ⭐⭐⭐⭐ |
| 5 | todo | TodoList 管理 | ⭐⭐⭐ |
| 6 | title | 生成对话标题 | ⭐⭐⭐ |
| 7 | memory | 记忆提取和存储 | ⭐⭐⭐⭐ |
| 8 | view_image | 图片查看处理 | ⭐⭐⭐ |
| 9 | clarification | 澄清问题处理 | ⭐⭐⭐⭐ |
| 10 | guardrails | 安全护栏 | ⭐⭐⭐ |
| 11 | token_usage | Token 统计 | ⭐⭐⭐ |
| 12 | reasoning_effort | 推理强度控制 | ⭐⭐⭐ |
| 13 | ... | 其他 | ⭐⭐⭐ |

### Middleware 基类

```python
from abc import ABC, abstractmethod
from typing import Any, TypeVar

StateT = TypeVar("StateT")

class AgentMiddleware(ABC):
    """中间件基类"""
    
    @abstractmethod
    def __call__(
        self,
        state: StateT,
        config: RunnableConfig,
    ) -> StateT:
        """处理状态并返回（可以修改状态）"""
        pass
```

### Middleware 执行流程

```
用户消息
    ↓
┌─────────────────────────────────────────┐
│  Middleware 1 (thread_data)            │
│    - 可能修改 state                      │
│    - 可能执行副作用                       │
│    ↓                                    │
│  Middleware 2 (uploads)                 │
│    ↓                                    │
│  Middleware 3 (sandbox)                 │
│    ↓                                    │
│  ...                                    │
│    ↓                                    │
│  Agent Node 执行                          │
│    ↓                                    │
│  Middleware N (返回前处理)               │
└─────────────────────────────────────────┘
    ↓
返回响应给用户
```

### Sandbox Middleware 详解

```python
# backend/packages/harness/deerflow/agents/middlewares/sandbox.py

class SandboxMiddleware(AgentMiddleware):
    """切换沙箱执行环境"""
    
    def __call__(
        self,
        state: ThreadState,
        config: RunnableConfig,
    ) -> ThreadState:
        # 1. 检查 sandbox_type
        sandbox_type = state.get("sandbox_type", "local")
        
        # 2. 根据类型初始化沙箱
        if sandbox_type == "docker":
            sandbox = DockerSandboxProvider()
        elif sandbox_type == "kubernetes":
            sandbox = KubernetesSandboxProvider()
        else:
            sandbox = LocalSandboxProvider()
        
        # 3. 更新状态（传递沙箱实例）
        state["sandbox"] = sandbox
        
        return state
```

### 自定义 Middleware 示例

```python
class LoggingMiddleware(AgentMiddleware):
    """记录所有请求的中间件"""
    
    def __call__(
        self,
        state: ThreadState,
        config: RunnableConfig,
    ) -> ThreadState:
        # 1. 记录请求
        logger.info(f"User message: {state['messages'][-1]}")
        
        # 2. 添加时间戳
        state["request_time"] = datetime.now().isoformat()
        
        # 3. 继续执行链
        return state
```

---

## 2.5 SubAgent 系统

**文件**: `backend/packages/harness/deerflow/subagents/`

### 什么是 SubAgent？

SubAgent 是**被 Lead Agent 调用的子任务执行者**，用于并行处理复杂任务的子任务。

### 内置 SubAgent 类型

| 类型 | 用途 |
|------|------|
| `general-purpose` | 通用任务（搜索、分析、代码等） |
| `bash` | 执行 Bash 命令 |

### SubAgent 执行流程

```
Lead Agent
    ↓ 分解任务
SubAgent 1 ─┐
SubAgent 2 ─┼─ 并行执行 (最多 3 个)
SubAgent 3 ─┘
    ↓
收集结果
    ↓
Lead Agent 汇总
    ↓
返回给用户
```

### SubAgent 调用示例

在系统提示词中，Agent 会看到这样的指令：

```xml
<subagent_system>
You are running with subagent capabilities enabled. Your role is a task orchestrator:
1. DECOMPOSE: Break complex tasks into parallel sub-tasks
2. DELEGATE: Launch multiple subagents simultaneously
3. SYNTHESIZE: Collect and integrate results

**HARD CONCURRENCY LIMIT: MAXIMUM 3 `task` CALLS PER RESPONSE.**
</subagent_system>
```

### task 工具调用

```python
# Agent 调用 SubAgent 的方式
task(
    description="Research Tesla stock performance",
    prompt="Find recent news about Tesla stock",
    subagent_type="general-purpose"
)
```

---

## 2.6 系统提示词解析

**文件**: `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`

### 提示词结构

```python
SYSTEM_PROMPT_TEMPLATE = """
<role>
You are {agent_name}, an open-source super agent.
</role>

{soul}                    <!-- Agent 个性化 -->

{memory_context}          <!-- 记忆上下文 -->

<thinking_style>
- Think concisely and strategically
- PRIORITY CHECK: If anything is unclear, ask for clarification FIRST
</thinking_style>

<clarification_system>
**WORKFLOW PRIORITY: CLARIFY → PLAN → ACT**
1. FIRST: Analyze the request
2. SECOND: If unclear, call `ask_clarification` tool
3. THIRD: Only after clarifications resolved, proceed
</clarification_system>

{skills_section}          <!-- 可用 Skills -->

{subagent_section}        <!-- SubAgent 配置 -->

<working_directory>
- User uploads: `/mnt/user-data/uploads`
- User workspace: `/mnt/user-data/workspace`
- Output files: `/mnt/user-data/outputs`
</working_directory>

<response_style>
- Clear and Concise
- Natural Tone
- Action-Oriented
</response_style>
"""
```

### 动态参数替换

```python
prompt = SYSTEM_PROMPT_TEMPLATE.format(
    agent_name=agent_name or "DeerFlow 2.0",  # 默认名称
    soul=get_agent_soul(agent_name),
    skills_section=get_skills_prompt_section(),
    memory_context=_get_memory_context(agent_name),
    subagent_section=_build_subagent_section(max_concurrent),
)
```

---

## 2.7 学习目标检查清单

- [ ] 理解 ThreadState 的数据结构
- [ ] 理解 Annotated + Reducer 模式
- [ ] 理解 add_messages 的合并逻辑
- [ ] 理解 Lead Agent 的创建流程
- [ ] 理解 LangGraph StateGraph 的构建方式
- [ ] 理解 Middleware Chain 的执行机制
- [ ] 理解 SubAgent 的并行调度
- [ ] 理解系统提示词的结构

---

## 2.8 实践任务

### 任务 1: 绘制 Agent 执行流程图

用 Mermaid 或手绘，绘制从用户发送消息到收到响应的完整流程，包括：
1. Middleware 链
2. Agent Node
3. 条件边判断
4. SubAgent 调度（如果有）

### 任务 2: 阅读一个 Middleware 的完整实现

选择一个 Middleware（如 sandbox.py 或 memory.py），完整阅读并理解其实现。

### 任务 3: 修改系统提示词

修改 `prompt.py` 中的提示词模板，添加或修改一些指令，然后观察 Agent 行为变化。

### 任务 4: 尝试禁用 SubAgent

通过修改配置或代码，禁用 SubAgent 功能，观察 Agent 行为如何变化。

---

## 2.9 关键源码阅读顺序

```
1. thread_state.py - 状态定义
2. lead_agent/prompt.py - 提示词生成
3. lead_agent/agent.py - Agent 创建
4. middlewares/base.py - 中间件基类
5. middlewares/sandbox.py - 沙箱中间件
6. subagents/executor.py - SubAgent 执行
```

---

## 2.10 下一步

**[03-Phase 3: Skills 系统](./03-phase3-skills-system.md)**

学习 DeerFlow 的 Skill 系统，如何通过 Skill 扩展 Agent 能力。

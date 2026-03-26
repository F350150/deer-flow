# DeerFlow 后端架构详解

## 目录

1. [设计理念与架构概览](#1-设计理念与架构概览)
2. [4+1视图详解](#2-41视图详解)
3. [Agent创建完整流程](#3-agent创建完整流程)
4. [配置系统](#4-配置系统)
5. [模型系统](#5-模型系统)
6. [工具系统](#6-工具系统)
7. [中间件系统](#7-中间件系统)
8. [提示词模板系统](#8-提示词模板系统)
9. [记忆系统](#9-记忆系统)
10. [沙箱系统](#10-沙箱系统)
11. [Checkpoint系统](#11-checkpoint系统)
12. [子Agent系统](#12-子agent系统)
13. [客户端调用流程](#13-客户端调用流程)

---

## 1. 设计理念与架构概览

### 1.1 设计理念

DeerFlow是一个基于LangGraph的AI Agent框架，其核心设计理念包括：

**模块化与可组合性**
- 每个功能都是独立的模块（工具、中间件、记忆、沙箱等）
- 通过配置和中间件链的方式灵活组合
- 遵循"约定大于配置"的原则

**多层抽象**
```
用户请求 → Gateway → Agent → 中间件链 → 工具 → 沙箱
                ↓
            Checkpoint (状态持久化)
```

**运行时灵活性**
- 大多数组件支持懒加载（lazy_init），避免启动时开销
- 配置热重载，无需重启即可更新配置
- 多种沙箱、Checkpoint存储后端可插拔

### 1.2 核心组件关系图

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    用户请求                                             │
│                                         │                                              │
└─────────────────────────────────────────┼──────────────────────────────────────────────┘
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              DeerFlowClient / Gateway                                  │
│                                                                                       │
│  • 解析请求参数 (model_name, thread_id, thinking_enabled等)                            │
│  • 构建 RunnableConfig (configurable字典)                                              │
│  • 管理Agent生命周期 (按配置变化重新创建)                                             │
│  • 处理流式响应 (Event Generator)                                                       │
│                                                                                       │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              make_lead_agent(config)                                    │
│                                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              五大核心组件                                        │ │
│  │                                                                                 │ │
│  │   ┌───────────────────┐    ┌───────────────────┐    ┌───────────────────┐     │ │
│  │   │      Model        │    │      Tools        │    │      Prompt       │     │ │
│  │   │   (LLM大脑)       │    │    (能力扩展)     │    │     (指令)        │     │ │
│  │   │                   │    │                   │    │                   │     │ │
│  │   │ create_chat_model │    │get_available_tools│    │apply_prompt_templ │     │ │
│  │   │    │              │    │    │            │    │    │              │     │ │
│  │   │    ▼              │    │    ▼            │    │    ▼              │     │ │
│  │   │ AppConfig.models  │    │ AppConfig.tools  │    │ Soul + Memory     │     │ │
│  │   │ + thinking配置      │    │ + MCP工具       │    │ + Skills          │     │ │
│  │   │ + reasoning_effort │    │ + ACP工具       │    │ + Subagent Section │     │ │
│  │   │ + LangSmith追踪    │    │ + 内置工具      │    │ + Deferred Tools   │     │ │
│  │   └───────────────────┘    └───────────────────┘    └───────────────────┘     │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                          │                                              │
│                                          ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         Middleware Chain (16个中间件)                               │ │
│  │                                                                                 │ │
│  │   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐        │ │
│  │   │Thread-  │→  │Sandbox  │→  │Uploads  │→  │Dangling │→  │ Guard-  │   ...   │ │
│  │   │Data     │   │         │   │         │   │ToolCall │   │ rail    │        │ │
│  │   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘        │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                          │                                              │
│                                          ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                            ThreadState (状态Schema)                               │ │
│  │                                                                                 │ │
│  │   sandbox: SandboxState      # 沙箱ID和状态                                       │ │
│  │   thread_data: ThreadDataState  # 工作目录路径                                    │ │
│  │   title: str                # 对话标题                                           │ │
│  │   artifacts: list[str]      # 产物列表 (合并去重)                                │ │
│  │   todos: list              # 待办事项                                            │ │
│  │   uploaded_files: list      # 上传文件列表                                        │ │
│  │   viewed_images: dict       # 查看过的图片                                        │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                          │                                              │
└─────────────────────────────────────────┼──────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              LangGraph Agent 执行循环                                    │
│                                                                                       │
│      ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐           │
│      │  Model   │ ───▶  │ Middleware│ ───▶  │   Tool   │ ───▶  │  State   │           │
│      │   Call   │ ◀──── │   Chain  │ ◀────  │  Result  │ ◀────  │  Update  │           │
│      └──────────┘      └──────────┘      └──────────┘      └──────────┘           │
│                                                                                       │
│           │                    │                    │                                   │
│           │                    │                    │                                   │
│           ▼                    ▼                    ▼                                   │
│    ┌────────────┐      ┌────────────┐      ┌────────────┐                            │
│    │ TokenUsage │      │ LoopDetect │      │  Memory    │                            │
│    │ Middleware │      │ Middleware  │      │  Update    │                            │
│    └────────────┘      └────────────┘      └────────────┘                            │
│                                                                                       │
│                         ┌─────────────────────────────┐                                 │
│                         │      Checkpointer          │                                 │
│                         │  memory / sqlite / postgres │                                 │
│                         │   (每个step后保存状态)      │                                 │
│                         └─────────────────────────────┘                                 │
│                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 4+1视图详解

### 2.1 逻辑视图（Logic View）

**关注点**：系统的功能组织和组件关系

**核心组件层次**

```
第一层：接口层
├── DeerFlowClient (Python嵌入式客户端)
├── Gateway API (FastAPI HTTP服务)
└── LangGraph Server (可选的LangGraph Server模式)

第二层：Agent编排层
├── make_lead_agent()        # Agent工厂函数
├── _build_middlewares()   # 中间件链构建
└── apply_prompt_template() # 提示词组装

第三层：核心服务层
├── create_chat_model()     # 模型工厂
├── get_available_tools()   # 工具获取
├── SandboxProvider        # 沙箱抽象
└── MemoryUpdater          # 记忆更新

第四层：数据持久层
├── Checkpointer            # 状态持久化
├── Memory Storage         # 记忆存储
└── Config Storage         # 配置存储
```

**组件协作协议**

```
DeerFlowClient                Agent                    Middleware
     │                          │                          │
     │──── chat() ────────────▶│                          │
     │                          │                          │
     │    _get_runnable_config()│                          │
     │◀─────── RunnableConfig ───│                          │
     │                          │                          │
     │    _ensure_agent()      │                          │
     │──── create_agent() ────▶│                          │
     │                          │                          │
     │                          │◀─── middleware chain ─────│
     │                          │                          │
     │    stream() / invoke()  │                          │
     │─────────────────────────▶│                          │
     │                          │                          │
     │                          │──── after_model() ─────▶│
     │                          │◀─── state update ───────│
     │                          │                          │
     │                          │──── before_tool() ──────▶│
     │                          │◀─── tool result ────────│
     │                          │                          │
     │◀───── Event Stream ─────│                          │
     │                          │                          │
```

### 2.2 开发视图（Development View）

**源码目录结构及职责**

```
backend/packages/harness/deerflow/
│
├── agents/                          # Agent核心模块
│   ├── lead_agent/                  # Lead Agent入口
│   │   ├── agent.py                 # make_lead_agent() - Agent创建工厂
│   │   └── prompt.py               # apply_prompt_template() - 提示词模板
│   │
│   ├── middlewares/                # 中间件系统 (16个中间件)
│   │   ├── __init__.py
│   │   ├── thread_data_middleware.py       # 提供thread_id
│   │   ├── sandbox/
│   │   │   ├── __init__.py
│   │   │   └── middleware.py               # SandboxMiddleware - 沙箱生命周期
│   │   ├── uploads_middleware.py           # 文件上传处理
│   │   ├── dangling_tool_call_middleware.py # 修复缺失ToolMessage
│   │   ├── summarization_middleware.py     # 上下文摘要 (LangChain内置)
│   │   ├── todo_middleware.py             # TodoList待办事项
│   │   ├── token_usage_middleware.py      # Token统计
│   │   ├── title_middleware.py            # 标题生成
│   │   ├── memory_middleware.py           # 记忆更新队列
│   │   ├── view_image_middleware.py       # 图片查看
│   │   ├── deferred_tool_filter_middleware.py # 延迟工具过滤
│   │   ├── subagent_limit_middleware.py   # 子Agent并发限制
│   │   ├── loop_detection_middleware.py   # 循环检测
│   │   ├── clarification_middleware.py    # 澄清拦截
│   │   └── tool_error_handling_middleware.py # 工具错误处理
│   │
│   ├── memory/                      # 记忆系统
│   │   ├── __init__.py
│   │   ├── updater.py               # MemoryUpdater - LLM更新记忆
│   │   ├── queue.py                # MemoryUpdateQueue - 防抖队列
│   │   ├── prompt.py               # 记忆更新提示词模板
│   │   └── memory_config.py         # 记忆配置
│   │
│   ├── checkpointer/               # Checkpoint持久化
│   │   ├── __init__.py
│   │   ├── provider.py             # 同步Checkpointer (单例/上下文管理器)
│   │   ├── async_provider.py       # 异步Checkpointer (异步上下文管理器)
│   │   └── checkpointer_config.py  # Checkpoint配置
│   │
│   └── thread_state.py             # ThreadState状态Schema定义
│
├── models/                          # 模型系统
│   ├── __init__.py                 # create_chat_model工厂函数导出
│   ├── factory.py                  # create_chat_model() - 模型创建工厂
│   ├── claude_provider.py          # Claude模型实现
│   ├── openai_codex_provider.py    # OpenAI Codex模型
│   ├── patched_openai.py           # 修补的OpenAI模型
│   ├── patched_minimax.py          # MiniMax模型
│   ├── patched_deepseek.py         # DeepSeek模型
│   └── credential_loader.py        # 凭证加载
│
├── tools/                           # 工具系统
│   ├── __init__.py                # get_available_tools()导出
│   ├── tools.py                    # get_available_tools() - 工具获取
│   ├── builtins/                   # 内置工具
│   │   ├── __init__.py
│   │   ├── task_tool.py           # task_tool - 子Agent调用入口
│   │   ├── clarification_tool.py   # ask_clarification_tool - 澄清请求
│   │   ├── present_file_tool.py   # present_file - 文件展示
│   │   ├── view_image_tool.py    # view_image - 图片查看
│   │   ├── setup_agent_tool.py   # setup_agent - Agent设置
│   │   ├── tool_search.py        # 延迟工具搜索
│   │   └── invoke_acp_agent_tool.py # ACP Agent调用
│   └── mcp/                        # MCP工具支持
│       ├── __init__.py
│       ├── tools.py               # MCP工具获取
│       ├── client.py             # MCP客户端
│       └── cache.py              # MCP工具缓存
│
├── config/                          # 配置系统
│   ├── __init__.py
│   ├── app_config.py              # AppConfig主配置 + 热重载
│   ├── model_config.py            # 模型配置
│   ├── tool_config.py             # 工具配置
│   ├── sandbox_config.py           # 沙箱配置
│   ├── skills_config.py           # 技能配置
│   ├── memory_config.py           # 记忆配置
│   ├── checkpointer_config.py     # Checkpoint配置
│   ├── subagents_config.py        # 子Agent配置
│   ├── extensions_config.py       # MCP/ACP扩展配置
│   ├── guardrails_config.py      # 安全护栏配置
│   ├── summarization_config.py    # 摘要配置
│   ├── title_config.py           # 标题配置
│   ├── token_usage_config.py     # Token统计配置
│   ├── tool_search_config.py     # 延迟搜索配置
│   ├── acp_config.py             # ACP Agent配置
│   ├── agents_config.py          # Agent配置 (SOUL.md等)
│   ├── paths.py                  # 路径解析
│   └── tracing_config.py         # LangSmith追踪配置
│
├── subagents/                      # 子Agent系统
│   ├── __init__.py
│   ├── executor.py                # SubagentExecutor - 执行引擎
│   ├── config.py                 # SubagentConfig配置
│   ├── registry.py               # 子Agent注册表
│   └── builtins/                 # 内置子Agent
│       ├── __init__.py
│       ├── general_purpose.py    # general-purpose子Agent
│       └── bash_agent.py         # bash子Agent
│
├── sandbox/                        # 沙箱系统
│   ├── __init__.py
│   ├── sandbox.py                # Sandbox抽象基类
│   ├── sandbox_provider.py       # SandboxProvider抽象
│   ├── local/                    # 本地沙箱实现
│   │   └── local_sandbox.py
│   ├── exceptions.py             # 沙箱异常
│   ├── middleware.py             # 沙箱中间件 (在middlewares/)
│   └── tools.py                 # 沙箱工具 (bash, ls, read_file等)
│
├── skills/                        # 技能系统
│   ├── __init__.py
│   ├── loader.py                 # 技能加载
│   └── installer.py              # 技能安装
│
├── uploads/                       # 文件上传系统
│   ├── __init__.py
│   └── manager.py                # 上传管理
│
├── reflection/                    # 反射工具
│   └── resolve.py                # 动态类解析
│
├── guardrails/                    # 安全护栏
│   ├── __init__.py
│   ├── middleware.py             # GuardrailMiddleware
│   └── *.py                     # 各种护栏实现
│
├── client.py                     # DeerFlowClient嵌入式客户端
└── main.py                      # CLI入口
```

### 2.3 进程/线程视图（Process/Thread View）

**多线程架构**

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    Main Process                                         │
│                                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              Main Thread                                          │ │
│  │                                                                                 │ │
│  │  FastAPI / DeerFlowClient                                                       │ │
│  │       │                                                                         │ │
│  │       ├── HTTP Request Handler                                                  │ │
│  │       │       │                                                                 │ │
│  │       │       ▼                                                                 │ │
│  │       │  ┌─────────────────────────────────────────────────────────────────┐ │ │
│  │       │  │              Agent Execution (sync/async)                          │ │ │
│  │       │  │                                                                  │ │ │
│  │       │  │   make_lead_agent(config)                                         │ │ │
│  │       │  │          │                                                         │ │ │
│  │       │  │          ▼                                                         │ │ │
│  │       │  │   create_agent(model, tools, middleware, prompt, state)           │ │ │
│  │       │  │          │                                                         │ │ │
│  │       │  │          ▼                                                         │ │ │
│  │       │  │   LangGraph Graph.astream() / ainvoke()                          │ │ │
│  │       │  │          │                                                         │ │ │
│  │       │  │          ├──▶ Middleware Chain (同步调用)                           │ │ │
│  │       │  │          │                                                         │ │ │
│  │       │  │          └──▶ Checkpointer (每个step后保存)                         │ │ │
│  │       │  │                                                                  │ │ │
│  │       │  └─────────────────────────────────────────────────────────────────┘ │ │
│  │       │                                                                             │ │
│  └───────┼─────────────────────────────────────────────────────────────────────────────┘ │
│          │                                                                             │
│          │ (后台线程，由threading模块管理)                                                 │
│          ▼                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                    Background Threads (系统管理)                                   │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │          _scheduler_pool (ThreadPoolExecutor, 3 workers)                 │   │ │
│  │  │                                                                          │   │ │
│  │  │   职责: 接收task_tool请求，更新状态，不阻塞                               │   │ │
│  │  │                                                                          │   │ │
│  │  │   run_task():                                                           │   │ │
│  │  │     1. 更新task状态为RUNNING                                             │   │ │
│  │  │     2. 提交到_execution_pool执行                                          │   │ │
│  │  │     3. 设置started_at时间戳                                              │   │ │
│  │  │                                                                          │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │          _execution_pool (ThreadPoolExecutor, 3 workers)                  │   │ │
│  │  │                                                                          │   │ │
│  │  │   职责: 执行Subagent，支持超时控制                                        │   │ │
│  │  │                                                                          │   │ │
│  │  │   execute():                                                            │   │ │
│  │  │     1. asyncio.run(_aexecute())                                          │   │ │
│  │  │     2. 创建SubagentExecutor                                              │   │ │
│  │  │     3. 调用agent.astream()                                              │   │ │
│  │  │                                                                          │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │  │          MemoryUpdateQueue (防抖线程)                                      │   │ │
│  │  │                                                                          │   │ │
│  │  │   职责: 延迟处理记忆更新，批量合并                                         │   │ │
│  │  │                                                                          │   │ │
│  │  │   _process_queue():                                                     │   │ │
│  │  │     1. 等待debounce_seconds (默认30秒)                                   │   │ │
│  │  │     2. 批量处理队列中的记忆更新                                           │   │ │
│  │  │     3. 调用MemoryUpdater.update_memory()                                 │   │ │
│  │  │                                                                          │   │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘   │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

**线程安全机制**

```python
# 1. 全局任务存储 - 线程安全
_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

# 2. 记忆更新队列 - 线程安全
class MemoryUpdateQueue:
    _lock = threading.Lock()
    _timer: threading.Timer | None = None

# 3. Loop检测中间件 - 线程安全
class LoopDetectionMiddleware:
    _lock = threading.Lock()
    _history: OrderedDict[str, list[str]]  # 按线程追踪
```

### 2.4 部署视图（Deployment View）

**典型部署架构**

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   Deployment View                                        │
│                                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────────┐     │
│   │                            开发者机器 (Local Dev)                            │     │
│   │                                                                             │     │
│   │   DeerFlowClient (Python SDK)                                               │     │
│   │         │                                                                   │     │
│   │         ▼                                                                   │     │
│   │   InMemorySaver (Checkpointer)                                              │     │
│   │   Local Sandbox                                                             │     │
│   │   config.yaml                                                              │     │
│   │                                                                             │     │
│   └─────────────────────────────────────────────────────────────────────────────┘     │
│                                          │                                            │
│                                          │ (内网/云)                                  │
│                                          ▼                                            │
│   ┌─────────────────────────────────────────────────────────────────────────────┐     │
│   │                              生产环境 (Production)                            │     │
│   │                                                                             │     │
│   │   ┌─────────────────────────────────────────────────────────────────┐     │     │
│   │   │                     Load Balancer / API Gateway                   │     │     │
│   │   └────────────────────────────┬────────────────────────────────────┘     │     │
│   │                                │                                             │     │
│   │         ┌─────────────────────┼─────────────────────┐                       │     │
│   │         │                     │                     │                       │     │
│   │         ▼                     ▼                     ▼                       │     │
│   │   ┌──────────┐          ┌──────────┐          ┌──────────┐              │     │
│   │   │ Instance │          │ Instance │          │ Instance │              │     │
│   │   │    1    │          │    2    │          │    N    │              │     │
│   │   └────┬─────┘          └────┬─────┘          └────┬─────┘              │     │
│   │        │                     │                     │                     │     │
│   │        └─────────────────────┼─────────────────────┘                     │     │
│   │                              │                                             │     │
│   │                              ▼                                             │     │
│   │   ┌─────────────────────────────────────────────────────────────────┐     │     │
│   │   │                    共享存储层                                      │     │     │
│   │   │                                                                  │     │     │
│   │   │   ┌─────────────────┐  ┌─────────────────┐  ┌───────────────┐   │     │     │
│   │   │   │  SQLite / Pg    │  │  File Storage   │  │   Redis      │   │     │     │
│   │   │   │  (Checkpoint)  │  │  (Memory.json) │  │  (可选缓存)  │   │     │     │
│   │   │   └─────────────────┘  └─────────────────┘  └───────────────┘   │     │     │
│   │   │                                                                  │     │     │
│   │   └─────────────────────────────────────────────────────────────────┘     │     │
│   │                                                                             │     │
│   │   ┌─────────────────────────────────────────────────────────────────┐     │     │
│   │   │                     Sandbox Provider                               │     │     │
│   │   │                                                                  │     │     │
│   │   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │     │     │
│   │   │   │   Local    │  │ Container   │  │     Remote             │ │     │     │
│   │   │   │  Sandbox   │  │  Sandbox   │  │  Sandbox (K8s/Docker)  │ │     │     │
│   │   │   │  (默认)    │  │  (可选)    │  │     (可选)             │ │     │     │
│   │   │   └─────────────┘  └─────────────┘  └─────────────────────────┘ │     │     │
│   │   │                                                                  │     │     │
│   │   └─────────────────────────────────────────────────────────────────┘     │     │
│   │                                                                             │     │
│   └─────────────────────────────────────────────────────────────────────────────┘     │
│                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.5 场景视图（Scenarios View）

**场景1: 用户发起对话请求**

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        场景1: 用户发起对话请求                                            │
│                                                                                       │
│  1. 用户发送消息                                                                       │
│       │                                                                              │
│       ▼                                                                              │
│  2. DeerFlowClient._get_runnable_config()                                            │
│       │  构建RunnableConfig，包含thread_id, model_name, thinking_enabled等               │
│       ▼                                                                              │
│  3. DeerFlowClient._ensure_agent()                                                    │
│       │  检查配置是否变化，决定是否重新创建Agent                                        │
│       ▼                                                                              │
│  4. make_lead_agent(config)                                                          │
│       │  创建Agent的5个核心组件                                                        │
│       ▼                                                                              │
│  5. create_agent(model, tools, middleware, prompt, state_schema)                        │
│       │  调用LangGraph创建Agent                                                        │
│       ▼                                                                              │
│  6. graph.astream(events)                                                            │
│       │  流式执行，每个step产生事件                                                     │
│       ▼                                                                              │
│  7. Checkpointer保存状态                                                              │
│       │  每个step后自动保存(thread_id作为key)                                          │
│       ▼                                                                              │
│  8. 返回Event给客户端                                                                 │
│          ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                           │
│          │ values     │  │messages-    │  │   end      │                           │
│          │ (状态快照)  │  │tuple        │  │  (结束)    │                           │
│          └─────────────┘  └─────────────┘  └─────────────┘                           │
│                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

**场景2: Agent调用子Agent**

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        场景2: Agent调用子Agent (task_tool)                               │
│                                                                                       │
│  1. Lead Agent决定调用task_tool                                                        │
│       │                                                                              │
│       ▼                                                                              │
│  2. SubagentLimitMiddleware检查                                                        │
│       │  如果超过max_concurrent(默认3)，截断多余的task调用                             │
│       ▼                                                                              │
│  3. task_tool.execute()                                                                │
│       │  ├── get_subagent_config() → 获取配置                                         │
│       │  ├── get_available_tools(subagent_enabled=False) → 过滤工具                    │
│       │  └── SubagentExecutor(...) → 创建执行器                                        │
│       ▼                                                                              │
│  4. executor.execute_async()                                                           │
│       │  ├── 创建SubagentResult(PENDING)                                              │
│       │  ├── _background_tasks[task_id] = result                                      │
│       │  └── _scheduler_pool.submit(run_task)                                        │
│       ▼                                                                              │
│  5. run_task() (在_scheduler_pool执行)                                                 │
│       │  ├── 更新状态为RUNNING                                                        │
│       │  └── _execution_pool.submit(execute, task, result_holder)                     │
│       ▼                                                                              │
│  6. execute() (在_execution_pool执行)                                                 │
│       │  └── asyncio.run(_aexecute())                                                  │
│       ▼                                                                              │
│  7. _aexecute() (异步核心)                                                             │
│       │  ├── _create_agent() → 创建Subagent                                          │
│       │  ├── _build_initial_state(task) → 构建初始状态                                 │
│       │  └── async for chunk in agent.astream(): → 流式执行                           │
│       ▼                                                                              │
│  8. task_tool轮询等待                                                                  │
│       │  while True:                                                                 │
│       │    result = get_background_task_result(task_id)                               │
│       │    writer({"type": "task_started/running/completed", ...})                   │
│       │    if result.status == COMPLETED: break                                       │
│       │    time.sleep(5)                                                              │
│       ▼                                                                              │
│  9. 返回结果给Lead Agent                                                                │
│       │  "Task Succeeded. Result: ..."                                               │
│       ▼                                                                              │
│  10. Lead Agent整合结果继续执行                                                         │
│                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

**场景3: 记忆更新流程**

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        场景3: 记忆更新流程                                               │
│                                                                                       │
│  1. Agent执行完成，MemoryMiddleware.after_agent()被调用                                  │
│       │                                                                              │
│       ▼                                                                              │
│  2. 消息过滤                                                                          │
│       │  _filter_messages_for_memory()                                                │
│       │  ├── 保留: HumanMessage (用户输入)                                             │
│       │  ├── 保留: AIMessage无tool_calls (最终响应)                                   │
│       │  └── 过滤: ToolMessage, 带tool_calls的AIMessage                              │
│       ▼                                                                              │
│  3. 队列添加                                                                          │
│       │  MemoryUpdateQueue.add(thread_id, filtered_messages)                             │
│       │  ├── 用thread_id去重(同一会话的更新合并)                                       │
│       │  └── 重置debounce_timer                                                       │
│       ▼                                                                              │
│  4. 等待debounce (默认30秒)                                                           │
│       │                                                                              │
│       ▼                                                                              │
│  5. _process_queue() (批量处理)                                                       │
│       │  ├── 获取所有待处理的ConversationContext                                        │
│       │  └── 遍历调用MemoryUpdater.update_memory()                                    │
│       ▼                                                                              │
│  6. MemoryUpdater.update_memory()                                                     │
│       │  ├── 获取当前记忆 (get_memory_data)                                           │
│       │  ├── 格式化对话 (format_conversation_for_update)                               │
│       │  ├── 构建提示词 (MEMORY_UPDATE_PROMPT)                                       │
│       │  ├── 调用LLM生成更新 (create_chat_model + invoke)                            │
│       │  ├── 解析JSON响应                                                            │
│       │  ├── 应用更新到memory_data                                                   │
│       │  └── 保存到文件 (_save_memory_to_file)                                        │
│       ▼                                                                              │
│  7. 记忆注入到下次提示词                                                              │
│       │  apply_prompt_template() → _get_memory_context()                              │
│       │  └── <memory>{记忆内容}</memory>                                             │
│                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Agent创建完整流程

### 3.1 make_lead_agent() 函数详解

**源码：`agents/lead_agent/agent.py:268-343`**

这是DeerFlow后端的核心入口函数。让我逐行解释：

```python
def make_lead_agent(config: RunnableConfig):
    # ============ 步骤1: 懒加载导入 ============
    # 避免循环依赖，延迟到函数调用时才导入
    from deerflow.tools import get_available_tools
    from deerflow.tools.builtins import setup_agent

    # ============ 步骤2: 解析configurable参数 ============
    # 这些参数来自客户端请求或配置
    cfg = config.get("configurable", {})

    # 思考模式 - Claude专属功能，允许模型进行extended thinking
    thinking_enabled = cfg.get("thinking_enabled", True)
    
    # 推理强度 - 针对Codex模型，可选 low/medium/high/xhigh
    reasoning_effort = cfg.get("reasoning_effort", None)
    
    # 模型名称 - 可从请求覆盖
    requested_model_name: str | None = cfg.get("model_name") or cfg.get("model")
    
    # 计划模式 - 启用TodoList中间件
    is_plan_mode = cfg.get("is_plan_mode", False)
    
    # 子Agent开关 - 允许Agent委托任务给subagent
    subagent_enabled = cfg.get("subagent_enabled", False)
    
    # 子Agent最大并发数 - 防止资源耗尽
    max_concurrent_subagents = cfg.get("max_concurrent_subagents", 3)
    
    # 引导模式 - 用于自定义Agent创建流程
    is_bootstrap = cfg.get("is_bootstrap", False)
    
    # Agent名称 - 支持多Agent个性化
    agent_name = cfg.get("agent_name")

    # ============ 步骤3: 加载Agent配置 ============
    # Agent配置定义在agents/目录下，支持SOUL.md个性化
    agent_config = load_agent_config(agent_name) if not is_bootstrap else None

    # ============ 步骤4: 模型名称解析 ============
    # 优先级: 请求指定 > Agent配置 > 全局默认
    agent_model_name = agent_config.model if agent_config and agent_config.model else _resolve_model_name()
    model_name = requested_model_name or agent_model_name

    # ============ 步骤5: 获取AppConfig ============
    # AppConfig是全局单例，支持热重载
    app_config = get_app_config()
    model_config = app_config.get_model_config(model_name) if model_name else None

    # ============ 步骤6: 思考模式兼容性检查 ============
    # 如果模型不支持思考但请求启用了，发出警告并禁用
    if thinking_enabled and not model_config.supports_thinking:
        logger.warning(f"Thinking mode is enabled but model '{model_name}' does not support it...")
        thinking_enabled = False

    # ============ 步骤7: 注入LangSmith追踪元数据 ============
    # 用于分布式追踪
    config["metadata"].update({
        "agent_name": agent_name or "default",
        "model_name": model_name or "default",
        "thinking_enabled": thinking_enabled,
        "reasoning_effort": reasoning_effort,
        "is_plan_mode": is_plan_mode,
        "subagent_enabled": subagent_enabled,
    })

    # ============ 步骤8: 创建Agent ============
    if is_bootstrap:
        # 引导模式: 最小化配置，用于Agent创建流程
        return create_agent(
            model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
            tools=get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled) + [setup_agent],
            middleware=_build_middlewares(config, model_name=model_name),
            system_prompt=apply_prompt_template(subagent_enabled=subagent_enabled, ..., available_skills=set(["bootstrap"])),
            state_schema=ThreadState,
        )

    # 默认Lead Agent: 完整配置
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

### 3.2 模型名称解析机制

**设计意图**：支持多层级的模型选择：
1. 用户请求可以指定模型
2. 每个Agent可以有自己的默认模型
3. 全局配置提供最终fallback

```python
def _resolve_model_name(requested_model_name: str | None = None) -> str:
    """模型名称解析 - 三级优先级"""
    app_config = get_app_config()
    
    # 默认使用config.yaml中的第一个模型
    default_model_name = app_config.models[0].name if app_config.models else None
    
    # 如果请求的模型在配置中存在，优先使用
    if requested_model_name and app_config.get_model_config(requested_model_name):
        return requested_model_name
    
    # 否则使用默认模型
    return default_model_name
```

### 3.3 create_agent的五个核心参数

**LangGraph的create_agent是一个工厂函数**，它将以下5个核心组件组合成一个可执行的Agent：

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                        create_agent 核心参数                                              │
│                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              model                                                │ │
│  │                                                                                 │ │
│  │   BaseChatModel实例                                                             │ │
│  │                                                                                 │ │
│  │   来源: create_chat_model(name, thinking_enabled, reasoning_effort)            │ │
│  │                                                                                 │ │
│  │   包含:                                                                             │ │
│  │   • API凭证和端点配置                                                            │ │
│  │   • 模型参数 (temperature, max_tokens等)                                          │ │
│  │   • 思考模式配置 (when_thinking_enabled)                                          │ │
│  │   • LangSmith追踪器                                                              │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              tools                                               │ │
│  │                                                                                 │ │
│  │   list[BaseTool]                                                               │ │
│  │                                                                                 │ │
│  │   来源: get_available_tools()                                                    │ │
│  │                                                                                 │ │
│  │   组成:                                                                             │ │
│  │   • 配置工具 (config.tools)                                                      │ │
│  │   • 内置工具 (present_file, ask_clarification)                                   │ │
│  │   • task_tool (当subagent_enabled=True)                                        │ │
│  │   • MCP工具 (来自MCP服务器)                                                     │ │
│  │   • ACP工具 (invoke_acp_agent)                                                  │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           middleware                                             │ │
│  │                                                                                 │ │
│  │   list[AgentMiddleware]                                                        │ │
│  │                                                                                 │ │
│  │   来源: _build_middlewares()                                                    │ │
│  │                                                                                 │ │
│  │   作用: 拦截Agent执行循环的各个阶段，添加横切关注点                               │ │
│  │   • before_agent / after_agent                                                  │ │
│  │   • before_model / after_model                                                 │ │
│  │   • before_tool / after_tool                                                    │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           system_prompt                                          │ │
│  │                                                                                 │ │
│  │   str                                                                              │ │
│  │                                                                                 │ │
│  │   来源: apply_prompt_template()                                                 │ │
│  │                                                                                 │ │
│  │   组成:                                                                             │ │
│  │   • <role> - Agent角色定义                                                       │ │
│  │   • <soul> - Agent个性 (SOUL.md)                                                │ │
│  │   • <memory> - 记忆上下文                                                      │ │
│  │   • <thinking_style> - 思考风格                                                │ │
│  │   • <clarification_system> - 澄清系统                                           │ │
│  │   • <skill_system> - 技能系统                                                  │ │
│  │   • <subagent_system> - 子Agent系统 (当启用时)                                  │ │
│  │   • <working_directory> - 工作目录                                              │ │
│  │   • <response_style> - 响应风格                                                 │ │
│  │   • <citations> - 引用规则                                                      │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                          state_schema                                            │ │
│  │                                                                                 │ │
│  │   TypedDict / Pydantic Model                                                   │ │
│  │                                                                                 │ │
│  │   来源: ThreadState (agents/thread_state.py)                                    │ │
│  │                                                                                 │ │
│  │   定义:                                                                             │ │
│  │   class ThreadState(AgentState):                                                │ │
│  │       sandbox: SandboxState | None           # 沙箱状态                          │ │
│  │       thread_data: ThreadDataState | None    # 线程数据                          │ │
│  │       title: str | None                  # 对话标题                               │ │
│  │       artifacts: Annotated[list, merge]      # 产物列表                           │ │
│  │       todos: list | None                   # 待办事项                              │ │
│  │       uploaded_files: list | None         # 上传文件                             │ │
│  │       viewed_images: Annotated[dict, merge]  # 查看过的图片                       │ │
│  │                                                                                 │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 配置系统

### 4.1 AppConfig与热重载机制

**设计意图**：DeerFlow采用"约定大于配置"的设计，大部分功能有合理的默认值。同时支持配置热重载，无需重启应用即可生效。

**核心机制**

```python
# 全局变量
_app_config: AppConfig | None = None          # 配置单例
_app_config_path: Path | None = None           # 配置文件路径
_app_config_mtime: float | None = None         # 文件修改时间
_app_config_is_custom = False                  # 是否为手动设置

def get_app_config() -> AppConfig:
    """
    获取配置单例。
    
    热重载触发条件 (满足任一):
    1. _app_config is None - 首次调用
    2. _app_config_path != resolved_path - 路径变化
    3. _app_config_mtime != current_mtime - 文件被修改
    """
    global _app_config, _app_config_path, _app_config_mtime

    # 如果是手动设置的配置，不自动重载
    if _app_config is not None and _app_config_is_custom:
        return _app_config

    resolved_path = AppConfig.resolve_config_path()
    current_mtime = _get_config_mtime(resolved_path)

    should_reload = (
        _app_config is None or
        _app_config_path != resolved_path or
        _app_config_mtime != current_mtime
    )

    if should_reload:
        _load_and_cache_app_config(str(resolved_path))

    return _app_config
```

### 4.2 配置加载流程

```
config.yaml (YAML文件)
    │
    ▼
AppConfig.from_file()
    │
    ├──► yaml.safe_load() → Python字典
    │
    ├──► resolve_env_variables()  ──────────────────┐
    │    递归处理字典，将 "$ENV_VAR" 替换为         │
    │    环境变量值                                 │
    │                                                │
    │◀───────────────────────────────────────────────┘
    │
    ├──► _check_config_version()
    │    检查用户配置版本 vs 示例配置版本
    │    如果落后，发出警告提示升级
    │
    ├──► load_xxx_config_from_dict()  (多个)
    │    • load_title_config_from_dict()
    │    • load_summarization_config_from_dict()
    │    • load_memory_config_from_dict()
    │    • load_subagents_config_from_dict()
    │    • load_tool_search_config_from_dict()
    │    • load_guardrails_config_from_dict()
    │    • load_checkpointer_config_from_dict()
    │    • load_acp_config_from_dict()
    │
    ├──► ExtensionsConfig.from_file()
    │    MCP服务器配置从独立文件加载
    │
    └──► Pydantic model_validate()
         数据验证和类型转换
              │
              ▼
         AppConfig Instance
```

### 4.3 配置结构详解

```python
class AppConfig(BaseModel):
    """主配置类 - 包含所有子配置"""
    
    # 日志级别
    log_level: str = "info"
    
    # Token使用统计
    token_usage: TokenUsageConfig
    
    # 模型列表 (支持多模型)
    models: list[ModelConfig]
    
    # 沙箱配置
    sandbox: SandboxConfig
    
    # 工具列表
    tools: list[ToolConfig]
    
    # 工具组
    tool_groups: list[ToolGroupConfig]
    
    # 技能配置
    skills: SkillsConfig
    
    # 扩展配置 (MCP/ACP)
    extensions: ExtensionsConfig
    
    # 延迟工具搜索
    tool_search: ToolSearchConfig
    
    # Checkpoint持久化 (可选)
    checkpointer: CheckpointerConfig | None
```

---

## 5. 模型系统

### 5.1 create_chat_model工厂函数

**设计意图**：统一管理多模型创建，处理模型间的差异（thinking模式、reasoning_effort等），自动附加追踪器。

```python
def create_chat_model(
    name: str | None = None,
    thinking_enabled: bool = False,
    **kwargs
) -> BaseChatModel:
    # ============ 步骤1: 获取模型配置 ============
    config = get_app_config()
    
    # 默认使用第一个配置的模型
    if name is None:
        name = config.models[0].name
    
    model_config = config.get_model_config(name)
    model_class = resolve_class(model_config.use, BaseChatModel)

    # ============ 步骤2: 提取模型参灵敏 ============
    # 排除元数据字段，保留实际构造参数
    model_settings_from_config = model_config.model_dump(
        exclude={
            "use", "name", "display_name", "description",
            "supports_thinking", "supports_reasoning_effort",
            "when_thinking_enabled", "thinking", "supports_vision"
        }
    )

    # ============ 步骤3: 处理thinking模式 ============
    # thinking模式是Claude的特性，需要特殊配置
    effective_wte = {...}  # 合并when_thinking_enabled和thinking
    
    if thinking_enabled:
        # 启用thinking
        if effective_wte:
            model_settings_from_config.update(effective_wte)
    else:
        # 禁用thinking
        if "extra_body" in effective_wte:
            kwargs["extra_body"]["thinking"]["type"] = "disabled"
        elif "thinking" in effective_wte:
            kwargs["thinking"]["type"] = "disabled"

    # ============ 步骤4: 处理reasoning_effort (Codex) ============
    if issubclass(model_class, CodexChatModel):
        if thinking_enabled:
            model_settings_from_config["reasoning_effort"] = explicit_effort or "medium"
        else:
            model_settings_from_config["reasoning_effort"] = "none"

    # ============ 步骤5: 创建模型实例 ============
    model_instance = model_class(**kwargs, **model_settings_from_config)

    # ============ 步骤6: 附加LangSmith追踪器 ============
    if is_tracing_enabled():
        tracer = LangChainTracer(project_name=tracing_config.project)
        model_instance.callbacks = [*existing_callbacks, tracer]

    return model_instance
```

### 5.2 模型配置结构

```python
class ModelConfig(BaseModel):
    """单个模型的配置"""
    
    name: str                           # 模型标识符
    use: str                          # 模型类路径
                                   # 如 "deerflow.models.ClaudeChatModel"
    
    # 能力标志
    supports_thinking: bool            # 是否支持extended thinking
    supports_reasoning_effort: bool    # 是否支持reasoning_effort (Codex)
    supports_vision: bool              # 是否支持视觉输入
    
    # Thinking模式专用配置
    when_thinking_enabled: dict | None  # 启用thinking时的参数覆盖
    thinking: dict | None              # thinking快捷配置
    
    # 其他模型参数 (temperature, max_tokens等)
    # ... 可变字段
```

### 5.3 为什么需要模型工厂

```
直接使用模型类的问题:
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│  # 问题1: 不同模型有不同的构造参数                                                        │
│  ClaudeChatModel(api_key=..., model="claude-3-5-sonnet", thinking={"type": "enabled"})  │
│  OpenAIChatModel(api_key=..., model="gpt-4o", ...)                                      │
│                                                                                         │
│  # 问题2: thinking配置方式不统一                                                        │
│  # Claude: thinking参数直接传递                                                        │
│  # OpenAI: thinking在extra_body中嵌套                                                  │
│                                                                                         │
│  # 问题3: 缺少全局追踪能力                                                             │
│                                                                                         │
│  # 解决方案: 工厂函数统一封装                                                            │
│  create_chat_model(name="claude", thinking_enabled=True)                                │
│      │                                                                                  │
│      ├──► 统一入口                                                                    │
│      ├──► 配置驱动                                                                    │
│      ├──► 自动处理thinking差异                                                         │
│      └──► 自动附加LangSmith追踪                                                        │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 工具系统

### 6.1 get_available_tools() 完整流程

**设计意图**：工具系统采用可插拔架构，支持内置工具、配置工具、MCP工具、ACP工具等多种来源，通过参数控制不同场景下应该暴露哪些工具。

```python
def get_available_tools(
    groups: list[str] | None = None,        # 工具组过滤
    include_mcp: bool = True,                # 是否包含MCP工具
    model_name: str | None = None,           # 用于vision工具判断
    subagent_enabled: bool = False,          # 子Agent开关
) -> list[BaseTool]:
    config = get_app_config()

    # ============ 第1步: 从配置加载工具 ============
    # 使用反射动态实例化工具类
    # config.tools 是 list[ToolConfig]，每个包含 name, use, group
    loaded_tools = [
        resolve_variable(tool.use, BaseTool)
        for tool in config.tools
        if groups is None or tool.group in groups
    ]

    # ============ 第2步: 添加内置工具 ============
    builtin_tools = BUILTIN_TOOLS.copy()  # [present_file_tool, ask_clarification_tool]

    # ============ 关键设计: subagent_enabled控制 ============
    # Lead Agent: subagent_enabled=True → 包含task_tool
    # Subagent: subagent_enabled=False → 不包含task_tool (防止嵌套)
    if subagent_enabled:
        builtin_tools.extend(SUBAGENT_TOOLS)  # [task_tool]

    # ============ 第3步: 添加视觉工具 ============
    # 只有支持vision的模型才添加view_image_tool
    if model_config.supports_vision:
        builtin_tools.append(view_image_tool)

    # ============ 第4步: 加载MCP工具 ============
    # MCP工具来自外部MCP服务器，按需加载
    mcp_tools = []
    if include_mcp:
        extensions_config = ExtensionsConfig.from_file()
        if extensions_config.get_enabled_mcp_servers():
            mcp_tools = get_cached_mcp_tools()
            
            # 当启用tool_search时，延迟加载
            if config.tool_search.enabled:
                # 注册到延迟注册表
                registry = DeferredToolRegistry()
                for t in mcp_tools:
                    registry.register(t)
                set_deferred_registry(registry)
                builtin_tools.append(tool_search_tool)

    # ============ 第5步: 添加ACP工具 ============
    # ACP (Agent Coding Partner) 是外部Agent
    acp_tools = []
    if get_acp_agents():
        acp_tools.append(build_invoke_acp_agent_tool(acp_agents))

    # ============ 返回合并列表 ============
    # 顺序: 配置工具 → 内置工具 → MCP工具 → ACP工具
    return loaded_tools + builtin_tools + mcp_tools + acp_tools
```

### 6.2 工具可见性控制

这是DeerFlow的一个关键设计，用于防止子Agent嵌套调用：

```
Lead Agent视角:
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│  get_available_tools(subagent_enabled=True)                                             │
│                                                                                         │
│  返回工具列表:                                                                            │
│  ├── [配置工具1, 配置工具2, ...]                                                         │
│  ├── [present_file_tool]                                                                │
│  ├── [ask_clarification_tool]                                                           │
│  ├── [task_tool]           ← subagent_enabled=True时包含                                │
│  ├── [view_image_tool]     ← 如果模型支持vision                                         │
│  ├── [MCP工具...]                                                                      │
│  └── [invoke_acp_agent]                                                                │
│                                                                                         │
│  结果: Lead Agent可以看到并使用task_tool                                                 │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

Subagent视角:
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│  get_available_tools(subagent_enabled=False)                                             │
│                                                                                         │
│  返回工具列表:                                                                            │
│  ├── [配置工具1, 配置工具2, ...]                                                         │
│  ├── [present_file_tool]                                                                │
│  ├── [ask_clarification_tool]                                                           │
│  ├── [view_image_tool]     ← vision工具仍可见                                           │
│  ├── [MCP工具...]                                                                      │
│  └── [invoke_acp_agent]                                                                │
│                                                                                         │
│  注意: task_tool被排除                                                                   │
│                                                                                         │
│  结果: Subagent无法看到task_tool，无法创建嵌套的subagent                                  │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 MCP工具加载机制

```python
async def get_mcp_tools() -> list[BaseTool]:
    """
    MCP工具异步加载流程
    """
    # 1. 读取MCP服务器配置
    extensions_config = ExtensionsConfig.from_file()
    
    # 2. 构建MultiServerMCPClient
    # 支持同时连接多个MCP服务器
    client = MultiServerMCPClient(
        servers=extensions_config.mcp_servers
    )
    
    # 3. 获取所有工具
    tools = await client.get_tools()
    
    # 4. 缓存到内存
    _cached_mcp_tools = tools
    
    # 5. 包装异步工具为同步调用
    # MCP工具原本是异步的，但Agent工具调用是同步的
    return [AsyncToSyncTool(t) for t in tools]
```

---

## 7. 中间件系统

### 7.1 中间件架构概述

**设计意图**：中间件是一种横切关注点的实现方式。在Agent执行循环中，开发者可以通过添加中间件来拦截各个阶段(pre_agent, after_model, before_tool等)，实现日志、监控、错误处理等功能，而无需修改核心逻辑。

**LangGraph Agent执行循环**

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                          LangGraph Agent 执行循环                                        │
│                                                                                       │
│      ┌─────────────────────────────────────────────────────────────────────────┐     │
│      │                         before_agent()                                   │     │
│      │    (Agent执行前调用，可修改状态或注入数据)                                    │     │
│      └────────────────────────────────┬────────────────────────────────────────┘     │
│                                       │                                              │
│                                       ▼                                              │
│      ┌─────────────────────────────────────────────────────────────────────────┐     │
│      │                          Model Call                                       │     │
│      │                                                                             │     │
│      │    ┌────────────────────────────────────────────────────────────────┐ │     │
│      │    │                      before_model()                              │ │     │
│      │    │   (模型调用前，可修改输入)                                          │ │     │
│      │    └────────────────────────────────┬───────────────────────────────┘ │     │
│      │                                     │                                   │     │
│      │                                     ▼                                   │     │
│      │                        ┌───────────────────┐                           │     │
│      │                        │   LLM Inference    │                           │     │
│      │                        └───────────────────┘                           │     │
│      │                                     │                                   │     │
│      │                                     ▼                                   │     │
│      │    ┌────────────────────────────────────────────────────────────────┐ │     │
│      │    │                     after_model()                               │ │     │
│      │    │   (模型调用后，可修改输出或注入提醒)                               │ │     │
│      │    └────────────────────────────────┬───────────────────────────────┘ │     │
│      │                                     │                                   │     │
│      └─────────────────────────────────────┼───────────────────────────────────┘     │
│                                            │                                          │
│                                            ▼                                          │
│      ┌─────────────────────────────────────────────────────────────────────────┐     │
│      │                         Tool Execution                                  │     │
│      │                                                                             │     │
│      │    for each tool_call:                                                   │     │
│      │        ┌───────────────────────────────────────────────────────────┐  │     │
│      │        │                    before_tool()                          │  │     │
│      │        │     (工具执行前，可修改参数或注入数据)                           │  │     │
│      │        └────────────────────────────────┬──────────────────────────┘  │     │
│      │                                         │                               │     │
│      │                                         ▼                               │     │
│      │                        ┌────────────────────────┐                       │     │
│      │                        │   Tool Execution       │                       │     │
│      │                        └────────────────────────┘                       │     │
│      │                                         │                               │     │
│      │                                         ▼                               │     │
│      │        ┌───────────────────────────────────────────────────────────┐  │     │
│      │        │                    after_tool()                            │  │     │
│      │        │     (工具执行后，可修改结果)                                   │  │     │
│      │        └────────────────────────────────┬──────────────────────────┘  │     │
│      │                                         │                               │     │
│      └─────────────────────────────────────────┼───────────────────────────────┘     │
│                                                │                                       │
│                                                ▼                                       │
│      ┌─────────────────────────────────────────────────────────────────────────┐     │
│      │                       after_agent()                                     │     │
│      │    (Agent执行后，可修改最终状态或触发副作用)                               │     │
│      └────────────────────────────────┬────────────────────────────────────────┘     │
│                                       │                                              │
│                                       │ (循环直到达到recursion_limit或结束)          │
│                                       ▼                                              │
│                                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 中间件执行顺序及设计决策

**源码注释揭示的设计意图（agent.py:198-207）**

```python
# 中间件顺序注释 - 每个顺序都有其原因
# 1. ThreadDataMiddleware - 必须在SandboxMiddleware之前
#    原因: SandboxMiddleware可能需要thread_id来管理沙箱生命周期
#
# 2. UploadsMiddleware - 在ThreadDataMiddleware之后
#    原因: 需要thread_id来定位用户上传目录
#
# 3. DanglingToolCallMiddleware - 在模型看到历史之前修复缺失的ToolMessage
#    原因: 防止模型因为缺少tool结果而产生幻觉
#
# 4. SummarizationMiddleware - 尽早进行摘要减少后续处理的上下文
#    原因: 减少中间件的上下文处理量
#
# 5. TodoListMiddleware - 在ClarificationMiddleware之前
#    原因: 允许在澄清流程中管理待办事项
#
# 6. TitleMiddleware - 在第一次交换后生成标题
#    原因: 需要至少一轮对话才能生成有意义的标题
#
# 7. MemoryMiddleware - 在TitleMiddleware之后
#    原因: 记忆应该基于已生成标题的对话
#
# 8. ViewImageMiddleware - 在ClarificationMiddleware之前
#    原因: 需要在LLM看到图片详情前注入
#
# 9. ToolErrorHandlingMiddleware - 在ClarificationMiddleware之前
#    原因: 工具异常应该先被转换为ToolMessage
#
# 10. ClarificationMiddleware - 最后
#     原因: 拦截所有澄清请求到用户
```

### 7.3 关键中间件详解

#### 7.3.1 SandboxMiddleware - 沙箱生命周期管理

```python
class SandboxMiddleware(AgentMiddleware):
    """
    沙箱中间件管理Agent的沙箱环境生命周期
    
    两种初始化模式:
    1. lazy_init=True (默认): 第一次工具调用时才获取沙箱
       - 优点: 如果Agent不需要沙箱工具，避免提前分配资源
       - 缺点: 首次工具调用会有延迟
    
    2. lazy_init=False: Agent调用前就获取沙箱
       - 优点: 第一次工具调用更快
       - 缺点: 即使不用沙箱也会分配
    """
    
    def before_agent(self, state, runtime):
        if self._lazy_init:
            return  # 跳过，等待工具调用
        # 立即获取沙箱
        sandbox_id = self._acquire_sandbox(thread_id)
        return {"sandbox": {"sandbox_id": sandbox_id}}
    
    def after_agent(self, state, runtime):
        # 释放沙箱
        get_sandbox_provider().release(sandbox_id)
```

#### 7.3.2 LoopDetectionMiddleware - 循环检测

```python
class LoopDetectionMiddleware:
    """
    检测并打破重复工具调用循环
    
    防止情况: Agent反复调用同一工具集，无法自行停止
    
    检测策略:
    1. 用MD5哈希追踪 (工具名 + 参数) 的序列
    2. 滑动窗口追踪最近20次调用
    3. 每轮检查是否有重复模式
    
    处理方式:
    • 3次重复 → 注入警告消息
    • 5次重复 → 强制停止，剥离所有tool_calls
    """
    
    # 使用LRU缓存追踪多个线程
    _history: OrderedDict[str, list[str]]  # thread_id -> [hash序列]
    _warned: dict[str, set[str]]          # thread_id -> 已警告的hash集合
```

#### 7.3.3 MemoryMiddleware - 记忆管理

```python
class MemoryMiddleware:
    """
    记忆中间件 - 将对话加入记忆更新队列
    
    特点:
    1. 仅在after_agent时触发，不阻塞主流程
    2. 过滤消息只保留用户输入和最终响应
    3. 通过防抖队列延迟批量处理
    """
    
    def after_agent(self, state, runtime):
        # 获取对话消息
        messages = state.get("messages", [])
        
        # 过滤
        filtered = _filter_messages_for_memory(messages)
        
        # 加入队列 (不会立即处理)
        queue.add(thread_id, filtered, agent_name=self._agent_name)
```

#### 7.3.4 ClarificationMiddleware - 澄清拦截

```python
class ClarificationMiddleware:
    """
    澄清中间件 - 拦截ask_clarification工具调用
    
    流程:
    1. 拦截ask_clarification工具调用
    2. 提取问题参数
    3. 格式化为用户友好的消息
    4. 返回Command(goto=END)中断执行
    5. 前端检测到END，提取问题呈现给用户
    6. 用户响应后继续执行
    """
    
    def wrap_tool_call(self, request, handler):
        if request.tool_call.get("name") != "ask_clarification":
            return handler(request)  # 正常执行
        
        # 拦截并返回中断命令
        return Command(
            update={"messages": [formatted_tool_message]},
            goto=END  # 跳到结束，等待用户输入
        )
```

---

## 8. 提示词模板系统

### 8.1 apply_prompt_template() 函数

**设计意图**：提示词由多个动态组件构成，每个组件根据配置和运行时状态决定是否包含。

```python
def apply_prompt_template(
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
    agent_name: str | None = None,
    available_skills: set[str] | None = None
) -> str:
    # ============ 第1步: 获取记忆上下文 ============
    # 从memory.json加载，注入到<memory>标签
    memory_context = _get_memory_context(agent_name)

    # ============ 第2步: 构建子Agent章节 ============
    # 仅当subagent_enabled=True时包含
    subagent_section = _build_subagent_section(max_concurrent) if subagent_enabled else ""

    # ============ 第3步: 获取技能章节 ============
    # 从skills/目录加载所有启用的技能
    skills_section = get_skills_prompt_section(available_skills)

    # ============ 第4步: 获取延迟工具章节 ============
    # 当tool_search启用时，显示可用的延迟工具名
    deferred_tools_section = get_deferred_tools_prompt_section()

    # ============ 第5步: 构建ACP章节 ============
    # 当配置了ACP agents时，包含使用说明
    acp_section = _build_acp_section()

    # ============ 第6步: 格式化模板 ============
    return SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=agent_name or "DeerFlow 2.0",
        soul=get_agent_soul(agent_name),          # SOUL.md内容
        skills_section=skills_section,              # 技能列表
        deferred_tools_section=deferred_tools_section,
        memory_context=memory_context,            # 记忆
        subagent_section=subagent_section,          # 子Agent说明
        ...
    )
```

### 8.2 提示词模板结构

```
SYSTEM_PROMPT_TEMPLATE
│
├── <role>
│   └── Agent角色定义 "You are {agent_name}..."
│
├── <soul>
│   └── Agent个性 (从SOUL.md加载，可选)
│
├── <memory>
│   └── 记忆上下文 (从memory.json加载，可选)
│
├── <thinking_style>
│   ├── 标准思考指令
│   └── {subagent_thinking} (当启用时添加)
│
├── <clarification_system>
│   └── 何时需要请求用户澄清的规则
│
├── <skill_system>
│   ├── 技能使用说明
│   └── <available_skills>...</available_skills>
│       └── 技能列表 (从skills/目录加载)
│
├── <available-deferred-tools>
│   └── MCP工具名列表 (当tool_search启用时)
│
├── <subagent_system> (当启用时)
│   ├── 并行执行策略
│   ├── 最大并发数限制
│   └── 使用示例
│
├── <working_directory>
│   ├── 工作目录路径
│   ├── 文件操作规则
│   └── {acp_section}
│
├── <response_style>
│   └── 响应风格指南
│
├── <citations>
│   └── 引用格式规则
│
├── <critical_reminders>
│   ├── 澄清优先规则
│   ├── 技能优先规则
│   └── {subagent_reminder} (当启用时)
│
└── <current_date>
    └── 当前日期时间
```

---

## 9. 记忆系统

### 9.1 记忆数据模型

```python
{
    "version": "1.0",
    "lastUpdated": "2024-01-15T10:30:00Z",
    
    # 用户信息
    "user": {
        "workContext": {
            "summary": "用户从事Python开发，关注AI Agent技术",
            "updatedAt": "2024-01-15T10:30:00Z"
        },
        "personalContext": {
            "summary": "喜欢简洁的代码风格",
            "updatedAt": "2024-01-10T08:00:00Z"
        },
        "topOfMind": {
            "summary": "当前项目需要实现多Agent协作",
            "updatedAt": "2024-01-15T10:30:00Z"
        }
    },
    
    # 历史信息
    "history": {
        "recentMonths": {"summary": "最近在研究LangGraph", "updatedAt": "..."},
        "earlierContext": {"summary": "早期使用过AutoGPT", "updatedAt": "..."},
        "longTermBackground": {"summary": "有10年编程经验", "updatedAt": "..."}
    },
    
    # 事实列表 (按置信度排序)
    "facts": [
        {
            "id": "fact_abc123",
            "content": "用户使用Claude作为主要模型",
            "category": "preference",  # preference|knowledge|context|behavior|goal
            "confidence": 0.85,
            "createdAt": "2024-01-15T10:30:00Z",
            "source": "thread_xyz789"
        }
    ]
}
```

### 9.2 记忆更新流程详解

```
对话结束
    │
    ▼
MemoryMiddleware.after_agent()
    │
    ├──► 提取 messages
    │
    ▼
_filter_messages_for_memory()
    │
    ├──► 保留: HumanMessage
    ├──► 保留: AIMessage without tool_calls
    └──► 过滤: ToolMessage, AIMessage with tool_calls
    │
    ▼
MemoryUpdateQueue.add()
    │
    ├──► 用thread_id去重 (同会话合并)
    │
    ▼
_debounce_timer 重置 (默认30秒)
    │
    │ (等待其他可能加入的更新)
    │
    ▼
_process_queue() (批量处理)
    │
    ▼
MemoryUpdater.update_memory()
    │
    ├──► get_memory_data() → 加载memory.json
    │
    ├──► format_conversation_for_update()
    │    将对话格式化为:
    │    """
    │    Conversation:
    │    User: xxx
    │    Assistant: xxx
    │    ...
    │    """
    │
    ├──► 构建提示词
    │    MEMORY_UPDATE_PROMPT.format(
    │        current_memory=json.dumps(memory),
    │        conversation=formatted
    │    )
    │
    ├──► create_chat_model() + invoke()
    │
    ├──► 解析LLM响应 (JSON)
    │
    ├──► _apply_updates()
    │    ├── 更新 user.{workContext,personalContext,topOfMind}
    │    ├── 更新 history.{recentMonths,earlierContext,longTermBackground}
    │    ├── 添加新facts (如果confidence >= 阈值)
    │    └── 删除过时facts
    │
    ├──► _strip_upload_mentions_from_memory()
    │    移除关于文件上传的事实 (会话级，不应持久化)
    │
    ▼
_save_memory_to_file()
    │
    └──► 原子写入 memory.json
```

### 9.3 记忆注入流程

```
下次对话开始
    │
    ▼
apply_prompt_template()
    │
    ▼
_get_memory_context(agent_name)
    │
    ├──► get_memory_data(agent_name)
    │    └── 读取 memory.json
    │
    ├──► format_memory_for_injection()
    │    └── 截断到 max_injection_tokens (默认2000)
    │
    ▼
返回格式化的<memory>标签
    │
    ▼
插入到SYSTEM_PROMPT_TEMPLATE
    │
    ▼
Agent创建时注入到system_prompt
```

---

## 10. 沙箱系统

### 10.1 沙箱抽象架构

```
SandboxProvider (抽象工厂)
    │
    ├──► acquire(thread_id) → sandbox_id
    │    获取或创建一个沙箱实例
    │
    ├──► get(sandbox_id) → Sandbox
    │    根据ID获取沙箱
    │
    └──► release(sandbox_id)
         释放沙箱资源

Sandbox (抽象基类)
    │
    ├──► execute_command(command) → stdout/stderr
    │    执行bash命令
    │
    ├──► read_file(path) → content
    │    读取文件
    │
    ├──► write_file(path, content)
    │    写入文件
    │
    ├──► list_dir(path, max_depth) → [files]
    │    列出目录
    │
    └──► update_file(path, binary_content)
         更新二进制文件
```

### 10.2 路径映射机制

**设计意图**：在容器化环境中，用户工作空间可能是隔离的。通过虚拟路径映射，Agent可以使用统一的路径访问实际存储。

```
Agent视角 (虚拟路径)              实际存储位置
────────────────────────────      ────────────────────

/mnt/user-data/uploads/*    →   /var/data/threads/{thread_id}/uploads/
/mnt/user-data/workspace/*   →   /var/data/threads/{thread_id}/workspace/
/mnt/user-data/outputs/*     →   /var/data/threads/{thread_id}/outputs/
/mnt/skills/*               →   /opt/deer-flow/skills/ (只读)
/mnt/acp-workspace/*        →   /opt/deer-flow/acp-workspace/ (只读)
```

### 10.3 SandboxMiddleware生命周期

```python
class SandboxMiddleware:
    """
    沙箱中间件的生命周期管理
    
    关键设计:
    1. 沙箱按thread_id隔离 - 不同会话使用不同沙箱
    2. 沙箱在会话内复用 - 不要每次工具调用都创建/销毁
    3. 懒获取(lazy_init) - 第一次工具调用时才获取
    """
    
    # 获取时机
    before_agent(): 
        if not lazy_init:
            sandbox_id = provider.acquire(thread_id)
            return {"sandbox": {"sandbox_id": sandbox_id}}
    
    # 释放时机  
    after_agent():
        provider.release(sandbox_id)
```

---

## 11. Checkpoint系统

### 11.1 Checkpoint的作用

**Checkpoint是LangGraph的状态持久化机制**，它允许:

1. **多轮对话**: 保存对话历史，下次请求恢复
2. **并发安全**: 同一thread_id的请求串行化
3. **故障恢复**: 应用崩溃后可恢复状态

```
无Checkpointer:
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│  Request 1 ───────────────────▶ Agent ───────────────────▶ Response 1                 │
│                                  │                                                    │
│                                  ✗ (崩溃)                                               │
│                                                                                         │
│  Request 2 ───────────────────▶ Agent ───────────────────▶ Response 2                 │
│                                  (无法恢复Request 1的状态)                              │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

有Checkpointer:
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│  Request 1 ───────────────▶ Agent ───────────────▶ Response 1                       │
│                                  │                                                 │
│                                  ▼                                                 │
│                            Checkpoint保存                                             │
│                            (thread_id: "user123")                                    │
│                                  │                                                 │
│                                  ✗ (崩溃)                                             │
│                                                                                         │
│  Request 2 ───────────────▶ Agent                                                         │
│                              │                                                         │
│                              ▼                                                         │
│                        Checkpoint加载                                                 │
│                        (恢复Request 1的状态)                                           │
│                              │                                                         │
│                              ▼                                                         │
│                        Agent ───────────────▶ Response 2                               │
│                        (上下文包含Request 1的消息)                                     │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 11.2 三种Checkpoint存储后端

```python
# 1. Memory (默认，开发用)
InMemorySaver()
# 优点: 无需额外配置
# 缺点: 进程退出即丢失

# 2. SQLite (单机持久化)
SqliteSaver.from_conn_string("store.db")
# 优点: 文件级持久化，简单
# 缺点: 不支持多进程

# 3. PostgreSQL (生产环境)
PostgresSaver.from_conn_string("postgresql://user:pass@host/db")
# 优点: 支持多进程/多实例
# 缺点: 需要数据库服务
```

### 11.3 同步 vs 异步 Checkpointer

```python
# 同步Checkpointer (CLI/单进程)
from deerflow.agents.checkpointer import get_checkpointer

checkpointer = get_checkpointer()  # 全局单例
graph.invoke(input, config={"configurable": {"thread_id": "1"}})

# 异步Checkpointer (FastAPI/多进程)
from deerflow.agents.checkpointer.async_provider import make_checkpointer

async with make_checkpointer() as checkpointer:
    await graph.ainvoke(input, config={"configurable": {"thread_id": "1"}})
```

---

## 12. 子Agent系统

### 12.1 task_tool执行流程

**源码核心（task_tool.py:60-195）**

```python
@tool("task", parse_docstring=True)
def task_tool(
    runtime,          # Agent运行时
    description,      # 任务描述 (日志用)
    prompt,           # 任务提示
    subagent_type,    # "general-purpose" | "bash"
    tool_call_id,     # 工具调用ID (用作task_id)
    max_turns,        # 最大轮次 (覆盖配置)
) -> str:
    # ============ 第1步: 获取子Agent配置 ============
    config = get_subagent_config(subagent_type)
    
    # ============ 第2步: 应用运行时覆盖 ============
    overrides = {}
    
    # 注入技能到系统提示
    if skills := get_skills_prompt_section():
        overrides["system_prompt"] = config.system_prompt + "\n\n" + skills
    
    # 覆盖最大轮次
    if max_turns is not None:
        overrides["max_turns"] = max_turns
    
    if overrides:
        config = replace(config, **overrides)

    # ============ 第3步: 提取Parent上下文 ============
    # 从runtime获取父Agent的状态
    sandbox_state = runtime.state.get("sandbox")
    thread_data = runtime.state.get("thread_data")
    thread_id = runtime.context.get("thread_id")
    parent_model = runtime.config.get("metadata", {}).get("model_name")

    # ============ 第4步: 获取工具列表 ============
    # 关键: subagent_enabled=False，不包含task_tool
    tools = get_available_tools(
        model_name=parent_model,
        subagent_enabled=False  # 防止嵌套
    )

    # ============ 第5步: 创建执行器 ============
    executor = SubagentExecutor(
        config=config,
        tools=tools,
        parent_model=parent_model,
        sandbox_state=sandbox_state,
        thread_data=thread_data,
        thread_id=thread_id,
        trace_id=trace_id,
    )

    # ============ 第6步: 启动后台执行 ============
    task_id = executor.execute_async(prompt, task_id=tool_call_id)

    # ============ 第7步: 轮询等待完成 ============
    # task_tool是同步函数，内部等待subagent完成
    while True:
        result = get_background_task_result(task_id)
        
        # 发送流式事件
        writer({"type": "task_started", ...})
        
        # 检查AI消息，发送task_running
        for new_msg in result.ai_messages[last_msg_count:]:
            writer({"type": "task_running", "message": new_msg, ...})
        
        # 检查终态
        if result.status == COMPLETED:
            return f"Task Succeeded. Result: {result.result}"
        
        time.sleep(5)
```

### 12.2 SubagentExecutor执行引擎

```python
class SubagentExecutor:
    """子Agent执行引擎"""
    
    def execute_async(self, task: str, task_id: str | None = None) -> str:
        """
        异步执行入口
        返回task_id用于后续查询
        """
        # 创建PENDING状态的result
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING
        )
        
        # 全局存储
        _background_tasks[task_id] = result
        
        # 提交到调度线程池
        def run_task():
            # 更新状态
            _background_tasks[task_id].status = RUNNING
            
            # 提交到执行线程池
            _execution_pool.submit(
                self.execute,      # 同步包装
                task,
                result_holder
            )
        
        _scheduler_pool.submit(run_task)
        return task_id
    
    def execute(self, task: str, result_holder) -> SubagentResult:
        """
        同步执行包装
        在线程池中运行asyncio.run()
        """
        return asyncio.run(self._aexecute(task, result_holder))
    
    async def _aexecute(self, task: str, result_holder) -> SubagentResult:
        """
        异步执行核心
        """
        # 创建agent
        agent = self._create_agent()
        
        # 构建初始状态
        state = self._build_initial_state(task)
        
        # 流式执行
        final_state = None
        async for chunk in agent.astream(state, stream_mode="values"):
            final_state = chunk
            
            # 捕获AI消息
            if new_msg := chunk.get("messages", [])[-1]:
                if isinstance(new_msg, AIMessage):
                    result.ai_messages.append(new_msg.model_dump())
        
        # 提取结果
        result.result = final_state["messages"][-1].content
        result.status = COMPLETED
        return result
```

### 12.3 双线程池设计

```
_scheduler_pool (3 workers)                    _execution_pool (3 workers)
─────────────────────────                      ─────────────────────────
职责: 快速响应，不阻塞                         职责: 执行subagent，支持超时

                                                   ┌─────────────────────┐
┌──────────────┐                                 │  Subagent 1         │
│ task_tool     │                                 │  (asyncio.run)      │
│ 调用execute_  │                                 └──────────┬──────────┘
│ async()       │                                            │
└──────┬───────┘                                            │
       │                                                    ▼
       │  提交run_task                   ┌─────────────────────────────┐
       ▼                               │  executor.execute()          │
┌──────────────┐                      │  asyncio.run(_aexecute())   │
│ run_task():  │                      └──────────┬──────────────────────┘
│  - 更新状态  │                                   │
│  - 提交到    │                                   ▼
│    execution │                     ┌─────────────────────────────┐
│    _pool     │                     │  _aexecute()                │
└──────────────┘                     │  - agent.astream()         │
                                     │  - 捕获AI messages         │
                                     │  - 返回result              │
                                     └─────────────────────────────┘
```

---

## 13. 客户端调用流程

### 13.1 DeerFlowClient架构

```python
class DeerFlowClient:
    """
    嵌入式Python客户端
    提供直接程序化访问，无需HTTP服务
    """
    
    def __init__(
        self,
        config_path=None,           # 配置文件路径
        checkpointer=None,         # Checkpointer实例
        model_name=None,           # 模型覆盖
        thinking_enabled=True,     # 思考模式
        subagent_enabled=False,    # 子Agent开关
        plan_mode=False,           # 计划模式
        agent_name=None,           # Agent名称
    ):
        # 懒加载Agent
        self._agent = None
        self._agent_config_key = None
    
    def _ensure_agent(self, config):
        """
        按需创建/重建Agent
        
        当配置参数变化时重新创建Agent:
        - model_name
        - thinking_enabled
        - is_plan_mode
        - subagent_enabled
        """
        key = (
            cfg.get("model_name"),
            cfg.get("thinking_enabled"),
            cfg.get("is_plan_mode"),
            cfg.get("subagent_enabled"),
        )
        
        if self._agent is not None and self._agent_config_key == key:
            return  # 配置没变，复用现有Agent
        
        # 创建新Agent
        self._agent = create_agent(
            model=create_chat_model(...),
            tools=get_available_tools(...),
            middleware=_build_middlewares(...),
            system_prompt=apply_prompt_template(...),
            state_schema=ThreadState,
            checkpointer=self._checkpointer,
        )
        self._agent_config_key = key
    
    def _get_runnable_config(self, thread_id, **overrides):
        """
        构建RunnableConfig
        包含configurable字典
        """
        return RunnableConfig(
            configurable={
                "thread_id": thread_id,
                "model_name": overrides.get("model_name", self._model_name),
                "thinking_enabled": overrides.get("thinking_enabled", self._thinking_enabled),
                ...
            },
            recursion_limit=overrides.get("recursion_limit", 100),
        )
```

### 13.2 聊天完整流程

```python
def chat(self, message: str, thread_id: str = "default", **kwargs):
    """发送消息并获取响应"""
    
    # 1. 确保Agent已创建
    config = self._get_runnable_config(thread_id, **kwargs)
    self._ensure_agent(config)
    
    # 2. 构建输入
    from langchain_core.messages import HumanMessage
    input_ = {"messages": [HumanMessage(content=message)]}
    
    # 3. 执行
    output = self._agent.invoke(input_, config=config)
    
    # 4. 提取响应
    return output["messages"][-1].content

def stream(self, message: str, thread_id: str = "default", **kwargs):
    """流式响应"""
    
    config = self._get_runnable_config(thread_id, **kwargs)
    self._ensure_agent(config)
    
    input_ = {"messages": [HumanMessage(content=message)]}
    
    # 返回生成器
    for event in self._agent.astream_events(input_, config=config):
        if event["event"] == "on_chain_end":
            # 处理输出
            yield event["data"]
```

---

文档已创建至 `plan_docs/16-backend-architecture.md`，包含：

1. **设计理念** - 模块化、多层抽象、运行时灵活性
2. **4+1视图详解** - 逻辑/开发/进程/部署/场景视图，每个视图都有详细图表和解释
3. **Agent创建流程** - `make_lead_agent()`逐行解析
4. **配置系统** - AppConfig热重载机制
5. **模型系统** - create_chat_model工厂函数
6. **工具系统** - get_available_tools完整流程
7. **中间件系统** - 16个中间件及执行顺序设计
8. **提示词模板** - 8个动态组件
9. **记忆系统** - 数据结构、更新流程、注入流程
10. **沙箱系统** - 路径映射、生命周期
11. **Checkpoint** - 状态持久化
12. **子Agent系统** - task_tool → executor完整链路
13. **客户端调用** - DeerFlowClient架构

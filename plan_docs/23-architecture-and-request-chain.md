# DeerFlow 完整架构文档 & 请求处理链路

> **生成时间**: 2026-04-11  
> **适用版本**: deer-flow v0.1.0 (LangGraph-based AI Agent System)

---

## 目录

1. [系统总体架构](#1-系统总体架构)
2. [目录结构全景](#2-目录结构全景)
3. [四大进程及其职责](#3-四大进程及其职责)
4. [请求路由：Nginx 反向代理](#4-请求路由nginx-反向代理)
5. [Gateway API 全部路由及处理链路](#5-gateway-api-全部路由及处理链路)
6. [LangGraph Server 请求处理链路](#6-langgraph-server-请求处理链路)
7. [核心 Agent 构建链路](#7-核心-agent-构建链路)
8. [中间件链详解](#8-中间件链详解)
9. [工具系统架构](#9-工具系统架构)
10. [子代理(Subagent)架构](#10-子代理subagent架构)
11. [IM Channel 消息链路](#11-im-channel-消息链路)
12. [配置系统](#12-配置系统)
13. [关键数据流图](#13-关键数据流图)

---

## 1. 系统总体架构

DeerFlow 是一个基于 **LangGraph** 的 AI Agent 系统，采用 **4 进程 + Nginx 反向代理** 的微服务架构：

```
┌─────────────────────────────────────────────────────────┐
│                    Nginx (:2026)                        │
│              统一入口 / 反向代理 / CORS                  │
├─────────┬──────────────┬──────────────┬─────────────────┤
│         │              │              │                 │
│   Frontend (:3000)  Gateway (:8001)  LangGraph (:2024) │
│   Next.js Web UI    FastAPI REST     LangGraph Server   │
│                     自定义 API        Agent 执行引擎     │
│                     配置管理/文件管理  (SSE 流式输出)     │
└─────────┴──────────────┴──────────────┴─────────────────┘
```

### 核心设计原则

- **前后端分离**: Next.js 前端 + Python 后端
- **API 网关模式**: Gateway 处理自定义 REST API, LangGraph Server 处理 Agent 对话
- **Nginx 统一路由**: 所有请求经过 `:2026` 端口，按 URI 前缀路由到不同后端
- **中间件链**: Agent 执行时经过一系列可插拔中间件进行增强
- **Sandbox 隔离**: 代码执行在隔离的沙箱环境中运行

---

## 2. 目录结构全景

```
deer-flow/
├── backend/                         # 后端代码 (Python)
│   ├── app/                         # FastAPI 网关应用
│   │   ├── gateway/                 # API 网关
│   │   │   ├── app.py               # FastAPI app 入口 (create_app)
│   │   │   ├── config.py            # 网关配置 (host/port/cors)
│   │   │   ├── path_utils.py        # 路径转换工具
│   │   │   └── routers/             # API 路由模块
│   │   │       ├── agents.py        # /api/agents - Agent CRUD
│   │   │       ├── artifacts.py     # /api/threads/{id}/artifacts - 产物下载
│   │   │       ├── channels.py      # /api/channels - IM 频道管理
│   │   │       ├── mcp.py           # /api/mcp/config - MCP 配置
│   │   │       ├── memory.py        # /api/memory - 记忆系统
│   │   │       ├── models.py        # /api/models - 模型列表
│   │   │       ├── skills.py        # /api/skills - 技能管理
│   │   │       ├── suggestions.py   # /api/threads/{id}/suggestions - 建议生成
│   │   │       ├── threads.py       # /api/threads/{id} - 线程管理
│   │   │       └── uploads.py       # /api/threads/{id}/uploads - 文件上传
│   │   └── channels/                # IM 频道系统
│   │       ├── base.py              # 频道基类
│   │       ├── feishu.py            # 飞书频道
│   │       ├── manager.py           # 频道消息调度器
│   │       ├── message_bus.py       # 消息总线
│   │       ├── service.py           # 频道服务管理
│   │       ├── slack.py             # Slack 频道
│   │       ├── store.py             # 频道状态存储
│   │       └── telegram.py          # Telegram 频道
│   │
│   ├── packages/harness/deerflow/   # 核心 Harness 包 (LangGraph Agent 逻辑)
│   │   ├── agents/                  # Agent 系统
│   │   │   ├── __init__.py          # 导出 make_lead_agent 等
│   │   │   ├── thread_state.py      # ThreadState 状态模型
│   │   │   ├── lead_agent/          # 主 Agent
│   │   │   │   ├── agent.py         # make_lead_agent() 构建函数
│   │   │   │   └── prompt.py        # 系统提示词模板
│   │   │   ├── middlewares/         # 中间件链 (13 个)
│   │   │   │   ├── clarification_middleware.py
│   │   │   │   ├── dangling_tool_call_middleware.py
│   │   │   │   ├── deferred_tool_filter_middleware.py
│   │   │   │   ├── loop_detection_middleware.py
│   │   │   │   ├── memory_middleware.py
│   │   │   │   ├── subagent_limit_middleware.py
│   │   │   │   ├── thread_data_middleware.py
│   │   │   │   ├── title_middleware.py
│   │   │   │   ├── todo_middleware.py
│   │   │   │   ├── token_usage_middleware.py
│   │   │   │   ├── tool_error_handling_middleware.py
│   │   │   │   ├── uploads_middleware.py
│   │   │   │   └── view_image_middleware.py
│   │   │   ├── memory/              # 记忆系统
│   │   │   │   ├── prompt.py        # 记忆注入 prompt
│   │   │   │   ├── queue.py         # 记忆更新队列
│   │   │   │   └── updater.py       # 记忆数据读写
│   │   │   └── checkpointer/        # 对话状态持久化
│   │   │
│   │   ├── client.py                # DeerFlowClient (嵌入式客户端, 无需HTTP)
│   │   ├── config/                  # 配置系统 (19 个配置模块)
│   │   ├── guardrails/              # 安全护栏
│   │   ├── mcp/                     # MCP 工具集成
│   │   │   ├── cache.py             # MCP 工具缓存
│   │   │   ├── client.py            # MCP 客户端
│   │   │   ├── oauth.py             # MCP OAuth 认证
│   │   │   └── tools.py             # MCP 工具加载
│   │   ├── models/                  # LLM 模型工厂
│   │   │   ├── factory.py           # create_chat_model()
│   │   │   ├── credential_loader.py # 凭证加载器
│   │   │   └── ...                  # 各厂商适配器
│   │   ├── sandbox/                 # 沙箱执行环境
│   │   │   ├── sandbox_provider.py  # 沙箱提供器
│   │   │   ├── middleware.py        # 沙箱中间件
│   │   │   └── tools.py             # 沙箱工具 (run_code 等)
│   │   ├── skills/                  # 技能系统
│   │   ├── subagents/               # 子代理系统
│   │   │   ├── executor.py          # SubagentExecutor
│   │   │   ├── config.py            # 子代理配置
│   │   │   └── registry.py          # 子代理注册表
│   │   ├── tools/                   # 工具系统
│   │   │   ├── tools.py             # get_available_tools()
│   │   │   └── builtins/            # 内置工具
│   │   │       ├── clarification_tool.py
│   │   │       ├── present_file_tool.py
│   │   │       ├── task_tool.py     # 子代理任务工具
│   │   │       ├── tool_search.py   # 工具搜索 (延迟加载)
│   │   │       ├── view_image_tool.py
│   │   │       ├── invoke_acp_agent_tool.py
│   │   │       └── setup_agent_tool.py
│   │   ├── uploads/                 # 文件上传管理
│   │   └── utils/                   # 工具函数
│   │
│   ├── debug.py                     # 调试脚本 (直接运行 agent)
│   ├── langgraph.json               # LangGraph Server 配置
│   ├── tests/                       # 测试文件 (64 个)
│   └── pyproject.toml               # Python 项目配置
│
├── frontend/                        # 前端 (Next.js)
├── docker/                          # Docker & Nginx 配置
│   └── nginx/
│       ├── nginx.conf               # 生产环境 nginx
│       └── nginx.local.conf         # 开发环境 nginx
├── config.yaml                      # 主配置文件
├── extensions_config.json           # MCP + Skills 扩展配置
├── scripts/                         # 启动/部署脚本
│   └── serve.sh                     # 启动所有服务
└── skills/                          # 技能定义目录
```

---

## 3. 四大进程及其职责

### 3.1 Nginx 反向代理 (端口 2026)

| 职责 | 说明 |
|------|------|
| 统一入口 | 所有外部请求通过 `:2026` 进入 |
| 路由分发 | 按 URI 前缀路由到不同后端 |
| CORS 管理 | 统一处理跨域头 |
| SSE 支持 | LangGraph 流式响应的代理 |

### 3.2 Gateway API (端口 8001)

| 职责 | 说明 |
|------|------|
| 自定义 REST API | 模型、技能、记忆、MCP 等配置管理 |
| 文件管理 | 文件上传、产物下载、线程数据清理 |
| Agent CRUD | 自定义 Agent 的创建/更新/删除 |
| IM 频道 | 飞书/Slack/Telegram 集成 |
| 建议生成 | 生成对话跟进建议 |

### 3.3 LangGraph Server (端口 2024)

| 职责 | 说明 |
|------|------|
| Agent 执行 | 主 Agent (lead_agent) 的创建和执行 |
| SSE 流式输出 | 实时流式输出 Agent 响应 |
| 状态持久化 | 通过 checkpointer 保存对话状态 |
| 工具调用 | 执行各种工具（sandbox、MCP、内置等）|

### 3.4 Frontend (端口 3000)

| 职责 | 说明 |
|------|------|
| Web UI | 用户交互界面 |
| SSE 消费 | 接收并渲染流式响应 |
| 配置界面 | 模型、技能、MCP 的前端管理 |

---

## 4. 请求路由：Nginx 反向代理

### 路由规则表

| 请求 URI 前缀 | 目标后端 | 说明 |
|---------------|---------|------|
| `/api/langgraph/*` | LangGraph `:2024` | rewrite 去除前缀后转发 |
| `/api/models` | Gateway `:8001` | 模型管理 |
| `/api/memory` | Gateway `:8001` | 记忆管理 |
| `/api/mcp` | Gateway `:8001` | MCP 配置 |
| `/api/skills` | Gateway `:8001` | 技能管理 |
| `/api/agents` | Gateway `:8001` | Agent CRUD |
| `/api/threads/{id}/uploads` | Gateway `:8001` | 文件上传 (100MB限制) |
| `/api/threads/*` | Gateway `:8001` | 产物/线程/建议 |
| `/docs`, `/redoc`, `/openapi.json` | Gateway `:8001` | API 文档 |
| `/health` | Gateway `:8001` | 健康检查 |
| `/*` (其他) | Frontend `:3000` | 前端页面 |

### 完整请求流转

```
用户浏览器
    │
    ▼
Nginx (:2026)  ─── OPTIONS ──▶ 204 (CORS preflight)
    │
    ├── /api/langgraph/* ──▶ LangGraph (:2024) [rewrite 去除 /api/langgraph 前缀]
    │                           │
    │                           ▼
    │                      LangGraph 标准 API:
    │                        POST /threads/{id}/runs/stream  (对话流式)
    │                        POST /threads                   (创建线程)
    │                        DELETE /threads/{id}            (删除线程)
    │                        ...
    │
    ├── /api/models ──▶ Gateway (:8001) /api/models
    ├── /api/memory ──▶ Gateway (:8001) /api/memory
    ├── /api/mcp    ──▶ Gateway (:8001) /api/mcp/config
    ├── /api/skills ──▶ Gateway (:8001) /api/skills
    ├── /api/agents ──▶ Gateway (:8001) /api/agents
    ├── /api/threads/*/uploads ──▶ Gateway (:8001) /api/threads/*/uploads
    ├── /api/threads/* ──▶ Gateway (:8001) /api/threads/*
    │
    └── /* ──▶ Frontend (:3000) (Next.js 页面)
```

---

## 5. Gateway API 全部路由及处理链路

### 5.1 Health Check

```
GET /health
    └── 直接返回 {"status": "healthy", "service": "deer-flow-gateway"}
```

### 5.2 Models API (模型管理)

```
GET  /api/models
    └── get_app_config()
        └── 遍历 config.models → ModelsListResponse

GET  /api/models/{model_name}
    └── config.get_model_config(model_name) → ModelResponse / 404
```

**处理链路详解：**
```
Request → FastAPI Router → get_app_config() → 读取全局 AppConfig 单例
  → AppConfig.models (从 config.yaml 解析的模型列表)
  → 返回: {name, model, display_name, description, supports_thinking, supports_reasoning_effort}
```

### 5.3 Memory API (记忆管理)

```
GET  /api/memory
    └── get_memory_data() → 读取 .deer-flow/memory.json → MemoryResponse

POST /api/memory/reload
    └── reload_memory_data() → 强制从文件重新加载并刷新缓存

GET  /api/memory/config
    └── get_memory_config() → 从 config.yaml 读取记忆配置

GET  /api/memory/status
    └── get_memory_config() + get_memory_data() → {config, data}
```

**处理链路详解：**
```
GET /api/memory
    → get_memory_data()
        → 检查内存缓存 (_cached_memory_data)
        → 如缓存为空: 读取 .deer-flow/memory.json
        → 返回: {version, lastUpdated, user{workContext,personalContext,topOfMind},
                  history{recentMonths,earlierContext,longTermBackground}, facts[]}
```

### 5.4 MCP API (MCP 配置管理)

```
GET  /api/mcp/config
    └── get_extensions_config()
        → 读取 extensions_config.json
        → 返回 {mcp_servers: {name: {enabled, type, command, args, env, url, ...}}}

PUT  /api/mcp/config
    └── 接收 McpConfigUpdateRequest
        → 保留 skills 配置
        → 写入 extensions_config.json
        → reload_extensions_config()
        → 返回更新后的配置
```

**处理链路详解：**
```
PUT /api/mcp/config
    → 解析 McpConfigUpdateRequest{mcp_servers: {name: McpServerConfigResponse}}
    → ExtensionsConfig.resolve_config_path() → 查找配置文件位置
    → get_extensions_config() → 获取当前配置 (保留 skills 配置)
    → 构建 config_data: {mcpServers: {...}, skills: {...}}
    → 写入文件: json.dump(config_data, config_path)
    → reload_extensions_config() → 刷新全局缓存
    → 注意: LangGraph Server (独立进程) 通过文件 mtime 检测变更自动重新初始化 MCP 工具
```

### 5.5 Skills API (技能管理)

```
GET  /api/skills
    └── load_skills(enabled_only=False)
        → 扫描 skills/ 目录下的 public/ 和 custom/ 子目录
        → 结合 extensions_config.json 中的 enabled 状态
        → 返回 [{name, description, license, category, enabled}]

GET  /api/skills/{skill_name}
    └── load_skills() → 找到同名 skill → SkillResponse / 404

PUT  /api/skills/{skill_name}
    └── 接收 {enabled: bool}
        → 写入 extensions_config.json
        → reload_extensions_config()
        → 重新加载 skills → 返回更新后的 skill

POST /api/skills/install
    └── 接收 {thread_id, path}
        → resolve_thread_virtual_path() → 解析虚拟路径到实际路径
        → install_skill_from_archive() → 从 .skill (ZIP) 安装
```

### 5.6 Agents API (自定义 Agent CRUD)

```
GET    /api/agents        → list_custom_agents() → 列出 .deer-flow/agents/ 下所有自定义 agent
GET    /api/agents/check?name=xxx → 检查 agent 名称是否可用
GET    /api/agents/{name} → load_agent_config(name) + 读取 SOUL.md → AgentResponse
POST   /api/agents        → 创建 agent 目录 + config.yaml + SOUL.md
PUT    /api/agents/{name} → 更新 config.yaml 和/或 SOUL.md
DELETE /api/agents/{name} → shutil.rmtree(agent_dir)
```

**处理链路详解（创建 Agent）：**
```
POST /api/agents
    → 验证名称: ^[A-Za-z0-9-]+$
    → 标准化: name.lower()
    → 检查目录: get_paths().agent_dir(name) 是否已存在 → 409 Conflict
    → 创建目录: .deer-flow/agents/{name}/
    → 写入 config.yaml: {name, description, model, tool_groups}
    → 写入 SOUL.md: agent 人格描述
    → load_agent_config(name) → 返回 AgentResponse
    → 失败时自动清理: shutil.rmtree(agent_dir)
```

### 5.7 User Profile API

```
GET  /api/user-profile → 读取 .deer-flow/USER.md → {content} / {content: null}
PUT  /api/user-profile → 写入 .deer-flow/USER.md
```

### 5.8 Artifacts API (产物下载)

```
GET /api/threads/{thread_id}/artifacts/{path:path}
    └── resolve_thread_virtual_path(thread_id, path)
        → 虚拟路径映射: mnt/user-data/* → 实际文件系统路径
        → 特殊处理: .skill/ 路径 → 从 ZIP 中提取文件
        → MIME 类型检测:
            - HTML/XHTML/SVG → 强制下载 (安全)
            - text/* → PlainTextResponse
            - 其他 → 根据 ?download=true/false 决定
```

### 5.9 Uploads API (文件上传)

```
POST   /api/threads/{thread_id}/uploads
    └── 文件验证 + 保存到 uploads 目录
        → 可转换格式 (PDF/PPTX/XLSX/DOCX) → 自动转 Markdown
        → 同步到沙箱 (非 local 模式)
        → 返回 {filename, size, path, virtual_path, artifact_url}

GET    /api/threads/{thread_id}/uploads/list
    └── list_files_in_dir() + enrich_file_listing()

DELETE /api/threads/{thread_id}/uploads/{filename}
    └── delete_file_safe()
```

### 5.10 Threads API (线程数据清理)

```
DELETE /api/threads/{thread_id}
    └── get_paths().delete_thread_dir(thread_id)
        → 删除线程本地文件数据 (不删除 LangGraph 线程状态)
```

### 5.11 Suggestions API (建议生成)

```
POST /api/threads/{thread_id}/suggestions
    └── 接收 {messages, n, model_name}
        → _format_conversation(messages) → 格式化对话
        → create_chat_model() → 创建 LLM 实例
        → 生成 prompt → model.invoke() → 解析 JSON 数组
        → 返回 {suggestions: ["问题1", "问题2", ...]}
```

### 5.12 Channels API (IM 频道管理)

```
GET  /api/channels/     → get_channel_service() → service.get_status()
POST /api/channels/{name}/restart → service.restart_channel(name)
```

---

## 6. LangGraph Server 请求处理链路

LangGraph Server 是标准的 LangGraph 服务，配置在 `langgraph.json` 中：

```json
{
  "graphs": {
    "lead_agent": "deerflow.agents:make_lead_agent"
  },
  "checkpointer": {
    "path": "./packages/harness/deerflow/agents/checkpointer/async_provider.py:make_checkpointer"
  }
}
```

### 核心对话请求链路

```
前端/客户端
    │
    ▼
POST /api/langgraph/threads/{thread_id}/runs/stream
    │
    ├── Nginx (:2026) rewrite → POST /threads/{thread_id}/runs/stream
    │
    ▼
LangGraph Server (:2024)
    │
    ├── 1. 解析请求参数
    │       {
    │         "assistant_id": "lead_agent",
    │         "input": {"messages": [{"role": "human", "content": "..."}]},
    │         "config": {
    │           "configurable": {
    │             "model_name": "gpt-4",
    │             "thinking_enabled": true,
    │             "is_plan_mode": false,
    │             "subagent_enabled": false,
    │             "agent_name": null
    │           }
    │         },
    │         "stream_mode": ["values", "messages"]
    │       }
    │
    ├── 2. 调用 make_lead_agent(config)  ← 关键入口
    │       │
    │       ├── 解析 model_name, 解析 agent_config
    │       ├── 构建中间件链 _build_middlewares()
    │       ├── 获取可用工具 get_available_tools()
    │       ├── 构建系统 prompt apply_prompt_template()
    │       └── create_agent(model, tools, middleware, system_prompt, state_schema)
    │
    ├── 3. 加载 checkpointer (对话状态持久化)
    │
    ├── 4. Agent 执行循环 (stream_mode="values")
    │       │
    │       ├── 中间件前处理 (pre-process)
    │       ├── LLM 调用
    │       ├── 工具调用 (如果有)
    │       ├── 中间件后处理 (post-process)
    │       ├── yield SSE events
    │       └── 循环直到 Agent 决定停止
    │
    └── 5. SSE 流式返回
            event: values
            data: {"messages": [...], "title": "...", "artifacts": [...]}

            event: messages
            data: [{"type": "ai", "content": "..."}]

            event: end
            data: {}
```

---

## 7. 核心 Agent 构建链路

### make_lead_agent(config) 详解

```python
def make_lead_agent(config: RunnableConfig):
    """
    调用时机: 每次新的对话请求 LangGraph Server 都会调用
    文件位置: backend/packages/harness/deerflow/agents/lead_agent/agent.py
    """

    # 1. 解析运行时配置
    cfg = config.get("configurable", {})
    thinking_enabled = cfg.get("thinking_enabled", True)
    model_name = cfg.get("model_name")
    is_plan_mode = cfg.get("is_plan_mode", False)
    subagent_enabled = cfg.get("subagent_enabled", False)
    agent_name = cfg.get("agent_name")

    # 2. 解析自定义 Agent 配置
    agent_config = load_agent_config(agent_name)
    # 自定义 Agent 有自己的 model → 优先使用
    agent_model_name = agent_config.model or _resolve_model_name()
    model_name = requested_model_name or agent_model_name

    # 3. 创建 LLM 模型
    model = create_chat_model(name=model_name, thinking_enabled=thinking_enabled)

    # 4. 获取工具列表
    tools = get_available_tools(
        model_name=model_name,
        groups=agent_config.tool_groups,  # 自定义 Agent 可限制工具组
        subagent_enabled=subagent_enabled
    )

    # 5. 构建中间件链
    middlewares = _build_middlewares(config, model_name, agent_name)

    # 6. 生成系统 Prompt
    system_prompt = apply_prompt_template(
        subagent_enabled=subagent_enabled,
        agent_name=agent_name
    )

    # 7. 创建 Agent Graph
    return create_agent(
        model=model,
        tools=tools,
        middleware=middlewares,
        system_prompt=system_prompt,
        state_schema=ThreadState
    )
```

### ThreadState 状态模型

```python
class ThreadState(AgentState):
    """Agent Graph 的状态，每次请求都会传递和更新"""
    # AgentState 包含 messages: list[BaseMessage]
    sandbox: SandboxState | None         # 沙箱状态 {sandbox_id}
    thread_data: ThreadDataState | None  # 线程数据路径
    title: str | None                    # 对话标题 (自动生成)
    artifacts: list[str]                 # 产物列表 (可合并去重)
    todos: list | None                   # Todo 列表 (plan mode)
    uploaded_files: list[dict] | None    # 上传的文件信息
    viewed_images: dict[str, ViewedImageData]  # 已查看的图片 (base64)
```

---

## 8. 中间件链详解

中间件在 Agent 每次调用 LLM 和工具时都会执行。**顺序非常重要**：

```
请求进入 Agent
    │
    ▼ (越上面越先执行 pre-process)
┌───────────────────────────────────────────────────────┐
│  build_lead_runtime_middlewares() — 运行时基础中间件   │
│    ├── ThreadDataMiddleware     — 初始化线程数据目录    │
│    ├── UploadsMiddleware        — 注入文件上传信息      │
│    ├── DanglingToolCallMiddleware — 修复缺失的 ToolMsg │
│    └── SandboxMiddleware        — 沙箱生命周期管理      │
│    └── ToolErrorHandlingMiddleware — 转换工具调用异常  │
├───────────────────────────────────────────────────────┤
│  SummarizationMiddleware (可选) — 历史消息摘要         │
│  TodoMiddleware (plan_mode)    — Todo 列表管理         │
│  TokenUsageMiddleware          — Token 使用量追踪      │
│  TitleMiddleware               — 自动生成对话标题       │
│  MemoryMiddleware              — 记忆注入和更新        │
│  ViewImageMiddleware (vision)  — 图片 base64 注入      │
│  DeferredToolFilterMiddleware  — 工具搜索过滤          │
│  SubagentLimitMiddleware       — 子代理并发数限制       │
│  LoopDetectionMiddleware       — 循环检测和中断        │
│  ClarificationMiddleware (末尾) — 澄清请求拦截        │
└───────────────────────────────────────────────────────┘
    │
    ▼ (post-process 逆序执行)
```

### 各中间件职责

| 中间件 | 文件 | 职责 |
|--------|------|------|
| **ThreadDataMiddleware** | `thread_data_middleware.py` | 初始化线程的 workspace/uploads/outputs 目录路径 |
| **UploadsMiddleware** | `uploads_middleware.py` | 将上传文件信息注入到 Agent 上下文中 |
| **DanglingToolCallMiddleware** | `dangling_tool_call_middleware.py` | 检测并修复缺少 ToolMessage 回复的 AIMessage |
| **SandboxMiddleware** | (sandbox) | 管理沙箱实例的生命周期 (acquire/release) |
| **ToolErrorHandlingMiddleware**| `tool_error_handling_middleware.py` | 拦截工具异常，转换为带有堆栈状态的 `ToolMessage` 防止控制流崩溃 |
| **SummarizationMiddleware** | (langchain) | 当消息历史过长时自动摘要压缩 |
| **TodoMiddleware** | `todo_middleware.py` | Plan Mode 下管理 TODO 列表 |
| **TokenUsageMiddleware** | `token_usage_middleware.py` | 追踪 token 使用量 |
| **TitleMiddleware** | `title_middleware.py` | 第一次回复后自动生成对话标题 |
| **MemoryMiddleware** | `memory_middleware.py` | 在 prompt 中注入记忆数据，对话后异步更新记忆 |
| **ViewImageMiddleware** | `view_image_middleware.py` | 将图片文件转为 base64 注入到消息中 |
| **DeferredToolFilterMiddleware** | `deferred_tool_filter_middleware.py` | 启用 tool_search 时隐藏延迟加载的工具 |
| **SubagentLimitMiddleware** | `subagent_limit_middleware.py` | 限制并发子代理数量 |
| **LoopDetectionMiddleware** | `loop_detection_middleware.py` | 检测重复工具调用循环并注入中断消息 |
| **ClarificationMiddleware** | `clarification_middleware.py` | 拦截 `ask_clarification` 工具调用 |
| **GuardrailMiddleware** | `guardrail_middleware.py` | 安全拦截护栏 (在 Sandbox 和所有工具之前拦截高危操作) |

---

## 9. 工具系统架构

### 工具加载链路

```
get_available_tools()
    │
    ├── 1. 配置工具: config.yaml → tools 列表
    │       resolve_variable(tool.use) → 动态导入 (reflection)
    │       可按 group 过滤 (agent_config.tool_groups)
    │
    ├── 2. 内置工具 (始终包含):
    │       ├── present_file_tool  — 文件展示
    │       └── ask_clarification_tool — 澄清请求
    │
    ├── 3. 条件工具:
    │       ├── view_image_tool    — 当模型支持 vision 时
    │       ├── task_tool          — 当 subagent_enabled=True 时
    │       └── tool_search_tool   — 当 tool_search.enabled=True 时
    │
    ├── 4. MCP 工具:
    │       └── ExtensionsConfig.from_file() → get_cached_mcp_tools()
    │           → 从 MCP 服务器动态获取工具 (支持 stdio/sse/http)
    │           → tool_search 启用时注册到延迟加载 registry
    │
    └── 5. ACP 工具:
            └── get_acp_agents() → build_invoke_acp_agent_tool()
                → 调用外部 ACP Agent
```

### 工具类型总览

| 类型 | 来源 | 示例 |
|------|------|------|
| 配置工具 | config.yaml `tools` 段 | sandbox tools (run_code 等) |
| 内置工具 | `tools/builtins/` | present_file, ask_clarification |
| 视觉工具 | 模型能力检测 | view_image |
| 子代理工具 | 运行时开关 | task (创建子任务) |
| MCP 工具 | MCP Server | GitHub, Filesystem 等 |
| ACP 工具 | 外部 Agent | invoke_acp_agent |

---

## 10. 子代理(Subagent)架构

```
Lead Agent (主 Agent)
    │
    ├── 调用 task_tool(title, description)
    │       │
    │       ├── 解析 subagent 配置: SubagentConfig
    │       ├── 创建 SubagentExecutor
    │       ├── 过滤工具 (allowed/disallowed)
    │       └── executor.execute_async(task)
    │               │
    │               ├── 提交到 _scheduler_pool (ThreadPoolExecutor)
    │               ├── 在 _execution_pool 中运行
    │               ├── 创建子 Agent (create_agent)
    │               │     └── 使用 build_subagent_runtime_middlewares()
    │               ├── agent.astream() 执行
    │               │     └── 收集 AI messages
    │               └── 支持超时 (config.timeout_seconds)
    │
    ├── task_tool 轮询结果:
    │       └── get_background_task_result(task_id)
    │           → 等待完成后返回结果
    │           → cleanup_background_task(task_id) 清理
    │
    └── 子代理结果回传给主 Agent 继续推理
```

### 并发控制

- **SubagentLimitMiddleware**: 限制 Lead Agent 一次发起的最大并发子任务数
- **MAX_CONCURRENT_SUBAGENTS**: 默认 3
- **超时机制**: 每个子代理有独立超时时间

---

## 11. IM Channel 消息链路

```
IM 平台 (飞书/Slack/Telegram)
    │
    ▼
Channel 实例 (FeishuChannel / SlackChannel / TelegramChannel)
    │
    ├── 接收消息 → 解析 → MessageBus.publish()
    │
    ▼
ChannelManager (调度器)
    │
    ├── MessageBus.subscribe() → 接收消息
    ├── ChannelStore → 管理会话映射 (IM 会话 → LangGraph 线程)
    ├── 调用 LangGraph API (http://localhost:2024)
    │     POST /threads/{thread_id}/runs/stream
    ├── 收集 SSE 流式响应
    └── 通过 Channel 实例回复 IM 平台
```

---

## 12. 配置系统

### 配置文件层次

```
config.yaml (主配置)
    ├── models:          → ModelConfig[]      (模型列表)
    ├── tools:           → ToolConfig[]       (工具配置)
    ├── sandbox:         → SandboxConfig      (沙箱配置)
    ├── memory:          → MemoryConfig       (记忆配置)
    ├── guardrails:      → GuardrailsConfig   (安全护栏)
    ├── subagents:       → SubagentsConfig    (子代理配置)
    ├── checkpointer:    → CheckpointerConfig (持久化配置)
    ├── summarization:   → SummarizationConfig(摘要配置)
    ├── title:           → TitleConfig        (标题生成配置)
    ├── token_usage:     → TokenUsageConfig   (token 追踪)
    ├── tool_search:     → ToolSearchConfig   (工具搜索)
    ├── tracing:         → TracingConfig      (分布式追踪)
    ├── skills:          → SkillsConfig       (技能配置)
    └── channels:        → dict               (IM 频道配置)

extensions_config.json (扩展配置)
    ├── mcpServers:      → {name: McpServerConfig}
    └── skills:          → {name: {enabled: bool}}
```

### 配置加载链路

```
get_app_config()
    └── _load_config()
        ├── 1. 环境变量: DEER_FLOW_CONFIG_PATH
        ├── 2. 相对路径: config.yaml, ../config.yaml
        └── 3. 解析 YAML → AppConfig (Pydantic BaseModel)
```

---

## 13. 关键数据流图

### 典型对话请求完整链路

```
用户在前端输入消息
    │
    ▼
Frontend (Next.js)
    │  POST /api/langgraph/threads/{thread_id}/runs/stream
    │  body: {assistant_id: "lead_agent", input: {messages: [...]}, config: {...}}
    │
    ▼
Nginx (:2026)
    │  rewrite /api/langgraph/* → /*
    │
    ▼
LangGraph Server (:2024)
    │  POST /threads/{thread_id}/runs/stream
    │
    ├── 1. make_lead_agent(config)
    │       ├── _resolve_model_name()     → 确定模型
    │       ├── load_agent_config()       → 加载自定义 agent 配置
    │       ├── create_chat_model()       → 创建 LLM 实例
    │       ├── get_available_tools()     → 加载所有工具
    │       ├── _build_middlewares()      → 构建中间件链
    │       ├── apply_prompt_template()   → 生成系统 prompt
    │       └── create_agent()            → 创建 LangGraph Agent
    │
    ├── 2. checkpointer 加载历史状态
    │
    ├── 3. Agent 执行循环
    │       ┌──────────────────────────────────────────────┐
    │       │  中间件 pre-process:                          │
    │       │    ThreadData → Uploads → DanglingToolCall   │
    │       │    → Sandbox → Summarization → Todo          │
    │       │    → TokenUsage → Title → Memory             │
    │       │    → ViewImage → DeferredToolFilter          │
    │       │    → SubagentLimit → LoopDetection           │
    │       │    → Clarification                           │
    │       ├──────────────────────────────────────────────┤
    │       │  LLM 调用 (model.invoke)                     │
    │       │    → 生成文本回复 / 工具调用请求              │
    │       ├──────────────────────────────────────────────┤
    │       │  工具执行 (如果有 tool_calls):                │
    │       │    → sandbox.run_code() / MCP调用 /          │
    │       │      present_file() / task() / ...           │
    │       ├──────────────────────────────────────────────┤
    │       │  中间件 post-process (逆序)                   │
    │       │    → 记忆更新 → Token 统计 → 标题生成        │
    │       └──────────────────────────────────────────────┘
    │       │  (循环直到 Agent 停止或达到 recursion_limit)
    │
    └── 4. SSE 流式返回
            event: values
            data: {"messages": [...], "title": "...", "artifacts": [...]}

            event: messages
            data: [AIMessage, ToolMessage, ...]

            event: end
```

### DeerFlowClient (嵌入式客户端) 链路

```python
# 无需启动任何服务，直接在 Python 进程中使用
client = DeerFlowClient(model_name="gpt-4")

# stream() 方法链路:
client.stream("hello", thread_id="t1")
    │
    ├── _get_runnable_config(thread_id) → RunnableConfig
    ├── _ensure_agent(config)
    │     ├── 检查配置 key 是否变化
    │     └── create_agent(model, tools, middleware, system_prompt, state_schema, checkpointer)
    ├── agent.stream(state, config, context, stream_mode="values")
    │     └── yield StreamEvent(type="messages-tuple" | "values" | "end")
    └── 最终: yield StreamEvent(type="end", data={usage: {...}})
```

---

## 附录：环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DEER_FLOW_CONFIG_PATH` | - | 自定义 config.yaml 路径 |
| `DEER_FLOW_EXTENSIONS_CONFIG_PATH` | - | 自定义 extensions_config.json 路径 |
| `GATEWAY_HOST` | `0.0.0.0` | Gateway 监听地址 |
| `GATEWAY_PORT` | `8001` | Gateway 监听端口 |
| `CORS_ORIGINS` | `http://localhost:3000` | CORS 允许的来源 |
| `LANGGRAPH_LOG_LEVEL` | `info` | LangGraph 日志级别 |

## 附录：端口分配

| 端口 | 服务 | 说明 |
|------|------|------|
| 2026 | Nginx | 统一入口 |
| 2024 | LangGraph Server | Agent 执行引擎 |
| 8001 | Gateway API | 自定义 REST API |
| 3000 | Frontend | Next.js Web UI |

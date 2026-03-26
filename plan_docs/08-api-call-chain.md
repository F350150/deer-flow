# DeerFlow API 调用链条详解

> 当用户在 UI 输入 "hello" 并发送时，完整触发的 5 个 API 接口分析

---

## 1. 架构概述

### 1.1 组件架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         生产环境请求路径（Docker Compose）                     │
│                                                                              │
│   ┌──────────┐         ┌──────────────────────────────────────────────┐   │
│   │  浏览器   │────────▶│            Nginx (:2026)                       │   │
│   └──────────┘         │                                               │   │
│                         │  路由规则：                                      │   │
│                         │    /           → Frontend :3000 (Next.js)     │   │
│                         │    /api/langgraph/* → LangGraph Server :2024  │   │
│                         │    /api/*       → Gateway API :8001            │   │
│                         └──────────────────────────────────────────────┘   │
│                                           │                                 │
│                      ┌────────────────────┼────────────────────┐           │
│                      │                    │                    │           │
│                      ▼                    ▼                    ▼           │
│                ┌───────────┐        ┌───────────┐        ┌───────────┐   │
│                │  Frontend │        │ LangGraph │        │  Gateway  │   │
│                │ (Next.js) │        │  Server   │        │    API    │   │
│                │  :3000    │        │  :2024    │        │  :8001    │   │
│                └───────────┘        └───────────┘        └───────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 组件职责

| 组件 | 职责 | 运行时位置 |
|------|------|-----------|
| **浏览器** | 运行 JS 代码，发送请求，渲染页面 | 用户本地 |
| **Nginx** | 反向代理，路由分发 | Docker 容器 |
| **Frontend (Next.js)** | 渲染页面，返回静态资源 | Docker 容器 |
| **LangGraph Server** | 接收请求，加载 Agent，执行图，返回 SSE | Docker 容器 |
| **Gateway API** | 处理辅助功能（suggestions、文件等） | Docker 容器 |

### 1.3 Nginx 路由规则

Nginx 是生产环境的**统一入口**，负责将请求路由到不同的后端服务：

```nginx
# docker/nginx/nginx.conf

# 默认路由 → Next.js 生产服务器
location / {
    proxy_pass http://frontend:3000;
}

# LangGraph API（路径重写后转发）
location /api/langgraph/ {
    rewrite ^/api/langgraph/(.*) /$1 break;
    proxy_pass http://langgraph:2024;
}

# Gateway API
location /api/ {
    proxy_pass http://gateway:8001;
}
```

**路径重写解释**：
- 请求：`POST /api/langgraph/threads`
- 重写后：`POST /threads`（去掉了 `/api/langgraph` 前缀）
- 这样 LangGraph Server 收到的路径就是 `/threads`

### 1.4 API 端点映射表

| 前端调用路径 | 最终目标 | 实际路径 | 作用 |
|-------------|---------|---------|------|
| `/api/langgraph/threads` | LangGraph Server | `/threads` | 创建 Thread |
| `/api/langgraph/threads/search` | LangGraph Server | `/threads/search` | 搜索 Threads |
| `/api/langgraph/threads/{id}/runs/stream` | LangGraph Server | `/threads/{id}/runs/stream` | **核心**：流式消息交互 |
| `/api/threads/{id}/suggestions` | Gateway API | `/api/threads/{id}/suggestions` | 生成后续问题建议 |
| `/api/langgraph/threads/{id}/history` | LangGraph Server | `/threads/{id}/history` | 获取历史消息 |

---

## 2. 请求完整流程

### 2.1 用户输入到 AI 响应的完整链路

```
┌──────────┐      ┌──────────┐      ┌──────────┐      ┌─────────────┐
│   用户   │      │  浏览器  │      │  Nginx   │      │ LangGraph   │
│          │      │ (执行JS) │      │  :2026   │      │   Server    │
│          │      │          │      │          │      │   :2024     │
└──────────┘      └──────────┘      └──────────┘      └─────────────┘
     │                 │                 │                    │
     │ 1.输入消息     │                 │                    │
     │───────────────▶│                 │                    │
     │                 │                 │                    │
     │ 2.JS调用SDK    │                 │                    │
     │                 │ POST /api/langgraph/threads/{id}/runs/stream │
     │                 │──────────────────────────────────────────────▶│
     │                 │                 │                    │
     │                 │                 │ 3.路径重写         │
     │                 │                 │ /api/langgraph/*→/*│
     │                 │                 │──────────────────▶│
     │                 │                 │                    │
     │                 │                 │     4.执行Agent   │
     │                 │                 │     - GLM-4.7     │
     │                 │                 │     - Middlewares │
     │                 │                 │     - Tools       │
     │                 │                 │     - Checkpointer │
     │                 │                 │                    │
     │                 │     5.SSE响应   │                    │
     │◀────────────────────────────────│◀────────────────────│
     │                 │                    │
     ▼                 ▼                    ▼
```

### 2.2 每一步详细说明

| 步骤 | 从哪里 → 到哪里 | 做什么 |
|------|----------------|--------|
| **1** | 用户 → 浏览器 | 用户在输入框输入消息，点击发送 |
| **2** | 浏览器内部 | JS 中的 `sendMessage()` 调用 `thread.submit()` |
| **3** | 浏览器 → Nginx | SDK 发起 `POST /api/langgraph/threads/{id}/runs/stream` |
| **4** | Nginx → LangGraph Server | 路径重写 `/api/langgraph/*` → `/*`，反向代理到 `:2024` |
| **5** | LangGraph Server → Lead Agent | 加载 Agent，执行图（LLM 调用等） |
| **6** | Lead Agent → GLM-4.7 | 调用大语言模型生成回复 |
| **7** | Lead Agent → Middlewares | 中间件处理（日志、循环检测等） |
| **8** | Lead Agent → Tools/Skills | 如需工具调用，执行工具 |
| **9** | Lead Agent → Checkpointer | 保存状态到内存/SQLite/PostgreSQL |
| **10** | LangGraph Server → Nginx | SSE 流式响应 (`event: values`) |
| **11** | Nginx → 浏览器 | 转发 SSE 流式响应 |
| **12** | 浏览器内部 | JS 回调 `onUpdateEvent()` 更新 UI |
| **13** | 浏览器 → 用户 | 页面显示 AI 回复 |

---

## 3. 核心技术基础

### 3.1 Starlette 框架

Starlette 是 Python 的**轻量级 ASGI 框架**（ASGI = Asynchronous Server Gateway Interface）。

#### 为什么需要 ASGI？

| 方案 | 问题 |
|------|------|
| CGI | 每个请求一个新进程，效率低 |
| WSGI (Flask/Django) | 同步，不支持长连接 |
| ASGI | 异步，支持长连接/WebSocket |

#### 常见 Python Web 框架对比

| 框架 | 同步/异步 | 特点 | 作者 |
|------|----------|------|------|
| Flask | 同步 | 简单灵活 | Armin Ronacher |
| Django | 同步 | 全功能 ORM 内置 | Django 基金会 |
| FastAPI | 异步 | 类型安全、自动文档 | Sebastián Ramírez |
| **Starlette** | 异步 | 轻量、ASGI 原生 | Tom Christie |

#### FastAPI 与 Starlette 的关系

```
FastAPI 底层 ＝ Starlette ＋ Pydantic

FastAPI(app) 内部创建了 Starlette(app)
所以直接用 Starlette 也可以写 Web 应用
```

#### Starlette 基本用法

```python
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

async def homepage(request):
    return JSONResponse({"message": "Hello"})

app = Starlette(routes=[
    Route("/", homepage, methods=["GET"]),
])

# 运行：uvicorn main:app --host 0.0.0.0 --port 8000
```

#### Starlette 核心组件

| 组件 | 说明 |
|------|------|
| `Starlette(routes=[...])` | 创建应用 |
| `Route("/path", func)` | 路由定义 |
| `Mount("/prefix", routes=[...])` | 子路由组 |
| `request.json()` | 获取请求体 |
| `JSONResponse({...})` | 返回 JSON |

#### Starlette 工作原理

```
HTTP 请求
    │
    ▼
ASGI Server (uvicorn/hypercorn) 接收
    │
    ▼
ASGI 协议转换
    │
    ▼
Starlette.app() 处理请求
    │
    ├─→ 路由匹配 (Route)
    ├─→ 中间件处理 (Middleware)
    └─→ 调用 endpoint 函数
    │
    ▼
ASGI 协议转换响应
    │
    ▼
返回给客户端
```

#### LangGraph Server 中的 Starlette

LangGraph Server 基于 Starlette 构建，API 路由风格一致：

```python
# LangGraph 路由定义
ApiRoute("/threads", endpoint=create_thread, methods=["POST"])

# 相当于 Starlette 的
Route("/threads", endpoint=create_thread, methods=["POST"])
```

**为什么 LangGraph 用 Starlette？**
1. Starlette 更轻量，没有 FastAPI 的 Pydantic 依赖
2. LangGraph 需要高度自定义 ASGI 行为
3. Starlette 更接近底层，灵活度高

---

### 3.2 Checkpointer 存储层

**Checkpointer = 状态持久化层**，负责存储 Thread 的状态（messages、artifacts、todos 等）。

#### 工作示意图

```
create_thread() 创建 Thread
        ↓
Threads.put() 把 Thread 存入存储
        ↓
存储可以是：内存、SQLite、PostgreSQL、MongoDB 等
```

#### 存储层定义位置

**`Threads.put()` 不是 DeerFlow 写的**，它是 **LangGraph Server 官方基础设施**：

```python
# langgraph_api/api/threads.py
iter = await Threads.put(conn, thread_id, metadata=..., ttl=...)
```

| 模式 | 来源 |
|------|------|
| In-memory | `langgraph_runtime_inmem.ops.Threads` |
| Postgres/GRPC | `langgraph_api.grpc.ops.Threads` |

#### 支持的存储类型

| 类型 | 配置值 | 特点 |
|------|--------|------|
| **内存** | `type: memory` | 进程重启后丢失，开发用 |
| **SQLite** | `type: sqlite` | 单进程，文件持久化 |
| **PostgreSQL** | `type: postgres` | 多进程生产推荐 |

#### 配置方式

**方式 A：config.yaml（推荐）**

```yaml
checkpointer:
  type: sqlite
  connection_string: ".deer-flow/checkpoints.db"
```

**方式 B：langgraph.json（LangGraph Server 级别）**

```json
{
  "checkpointer": {
    "path": "./packages/harness/deerflow/agents/checkpointer/async_provider.py:make_checkpointer"
  }
}
```

#### 默认行为详解

**当 config.yaml 中没有配置 checkpointer 时，DeerFlow 的默认行为是什么？**

**1. 默认值：checkpointer 为 None**

```python
# packages/harness/deerflow/config/app_config.py:43
class AppConfig(BaseModel):
    checkpointer: CheckpointerConfig | None = Field(default=None)
```

`config.yaml` 中没有 `checkpointer` 配置项时，`AppConfig.checkpointer` 为 `None`。

**2. 代码中的判断逻辑**

异步路径（LangGraph Server 使用）：

```python
# packages/harness/deerflow/agents/checkpointer/async_provider.py:100-106
@contextlib.asynccontextmanager
async def make_checkpointer() -> AsyncIterator[Checkpointer]:
    config = get_app_config()

    if config.checkpointer is None:      # ← 没有配置时走这里
        from langgraph.checkpoint.memory import InMemorySaver
        yield InMemorySaver()             # ← 返回内存存储
        return

    async with _async_checkpointer(config.checkpointer) as saver:
        yield saver
```

同步路径（DeerFlowClient 使用）：

```python
# packages/harness/deerflow/agents/checkpointer/provider.py:147-152
config = get_checkpointer_config()

if config is None:
    from langgraph.checkpoint.memory import InMemorySaver
    logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
    _checkpointer = InMemorySaver()      # ← 返回内存存储
    return _checkpointer
```

**3. 结论：默认行为**

| 场景 | 默认 checkpointer | 持久化 | 说明 |
|------|-------------------|--------|------|
| **DeerFlowClient** (嵌入式) | `InMemorySaver` | ❌ 进程重启丢失 | sync singleton |
| **LangGraph Server** (HTTP) | `InMemorySaver` | ❌ 进程重启丢失 | async context manager |

**一句话总结**：DeerFlow 默认**不持久化**状态，进程重启后所有 Thread 数据丢失。

---

### 3.3 Thread 数据结构

**Thread（会话线程）= AI 对话的上下文容器**

```
┌─────────────────────────────────────────────────────────────┐
│  Thread 数据结构                                             │
│                                                              │
│  thread_id: "6ac61487-4921-4693-8c84-4220b405cbd5"        │
│  created_at: "2026-03-29T10:00:00.000Z"                    │
│  status: "idle" | "busy" | "interrupted"                   │
│                                                              │
│  values: {                                                   │
│      "title": "hello",         ← 对话标题                   │
│      "messages": [             ← 完整的对话历史             │
│          {"type": "human", "content": "hello"},            │
│          {"type": "ai", "content": "Hi! How can I help?"}  │
│      ],                                                     │
│      "artifacts": [],       ← Agent 产生的文件列表          │
│      "todos": []            ← Agent 创建的任务列表          │
│  }                                                          │
└─────────────────────────────────────────────────────────────┘
```

**ThreadState 完整字段**：

```python
# packages/harness/deerflow/agents/thread_state.py
class ThreadState(AgentState):
    messages: list[Message]              # 对话消息列表
    artifacts: list[str]                 # 生成的文件路径
    todos: list                          # 任务列表
    title: str | None                     # 对话标题
    sandbox: SandboxState | None         # 沙箱信息
    thread_data: ThreadDataState | None   # 线程数据（路径等）
    uploaded_files: list[dict] | None    # 上传的文件
    viewed_images: dict                  # 查看的图片
```

**Thread 的核心作用**：
1. **存储对话历史** - 让 AI 理解对话上下文
2. **保存 AI 产生的内容** - artifacts（文件）、todos（任务）
3. **支持多轮对话** - 用户可以基于之前的对话继续交流

---

### 3.4 路由机制详解

#### 概念：路由 = 电话总机接线员

```
                    ┌─────────────────┐
  POST /threads ───▶│    路由表        │
                    │                 │
  GET /threads ───▶│  /threads  ────▶ create_thread()
                    │                 │
  DELETE /threads ─▶│  /threads/{id} ─▶ delete_thread()
                    │                 │
                    └─────────────────┘
```

路由的工作：**看到请求的 URL + HTTP 方法 → 决定调用哪个函数**

#### 与 Flask/FastAPI 对比理解

```python
# Flask/FastAPI 风格
@app.post("/threads")
def create_thread():
    return {"thread_id": "123"}

# LangGraph 风格（Starlette 框架）
ApiRoute("/threads", endpoint=create_thread, methods=["POST"])
#        ↑ URL路径   ↑ 处理函数    ↑ HTTP 方法
```

#### 路由注册

```python
# langgraph_api/api/threads.py
threads_routes: list[BaseRoute] = [
    ApiRoute("/threads", endpoint=create_thread, methods=["POST"]),
    ApiRoute("/threads/search", endpoint=search_threads, methods=["POST"]),
    ApiRoute("/threads/{thread_id}", endpoint=get_thread, methods=["GET"]),
    ApiRoute("/threads/{thread_id}", endpoint=delete_thread, methods=["DELETE"]),
]
```

#### 路由挂载

```python
# langgraph_api/server.py
protected_mount = Mount(
    "",
    routes=protected_routes,  # 包含 threads_routes
    middleware=middleware_for_protected_routes,
)

# 相当于 Flask: app.register_blueprint(bp, url_prefix="/...")
```

---

## 4. 各 API 详解

### 4.1 `POST /api/langgraph/threads` - 创建 Thread

**含义**：创建新的 Thread（会话线程）

**调用时机**：
- 当用户发送第一条消息时
- 当用户执行 `/new` 命令时

**调用链**：

```
Frontend: thread.submit() [frontend/src/core/threads/hooks.ts:347]
    │
    ▼
useStream() [frontend/src/core/threads/hooks.ts:113]
    │
    ▼
getAPIClient() [frontend/src/core/api/api-client.ts:10]
    │
    ▼
client.threads.create() [SDK]
    │
    ▼
POST /api/langgraph/threads
    │
    ▼
Nginx 重写 → /threads
    │
    ▼
Starlette 路由匹配: ApiRoute("/threads") → create_thread
    │
    ▼
create_thread() 内部处理:
    1. 解析请求 JSON body
    2. 生成 UUID (thread_id)
    3. Threads.put() 存储到 Checkpointer
    4. 返回 Thread 对象
```

**请求/响应**：

```http
POST /api/langgraph/threads
Content-Type: application/json

{}
```

```json
// 响应
{
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-07-18T18:35:15.540834+00:00",
  "updated_at": "2024-07-18T18:35:15.540834+00:00",
  "state_updated_at": "2024-07-18T18:35:15.540834+00:00",
  "metadata": {},
  "config": {},
  "status": "idle",
  "values": {},
  "interrupts": {}
}
```

---

### 4.2 `POST /api/langgraph/threads/search` - 搜索 Threads

**含义**：搜索/列出已存在的 Threads

**调用时机**：
- 页面加载时获取 thread 列表
- 刷新 thread 列表

**调用链**：

```
Frontend: useThreads() [frontend/src/core/threads/hooks.ts:413]
    │
    ▼
apiClient.threads.search() [frontend/src/core/threads/hooks.ts:432]
    │
    ▼
POST /api/langgraph/threads/search
    │
    ▼
Nginx → LangGraph Server
    │
    ▼
search_threads() → Checkpointer 查询
    │
    ▼
返回 thread 数组
```

**请求/响应**：

```http
POST /api/langgraph/threads/search
Content-Type: application/json

{
  "limit": 50,
  "sortBy": "updated_at",
  "sortOrder": "desc",
  "select": ["thread_id", "updated_at", "values"]
}
```

```json
// 响应
[
  {
    "thread_id": "6ac61487-4921-4693-8c84-4220b405cbd5",
    "updated_at": "2026-03-29T10:00:00.000Z",
    "values": { "title": "hello" }
  }
]
```

---

### 4.3 `POST /api/langgraph/threads/{id}/runs/stream` - 流式消息交互

**含义**：流式发送消息到 Agent 并接收 SSE 流式响应

**这是最核心的 API**，负责与 Agent 的实际交互。

#### 架构调用链

**Nginx 是生产环境的统一入口**：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         生产环境请求路径（Docker）                            │
│                                                                              │
│   ┌──────────┐         ┌──────────────────────────────────────────────┐   │
│   │  浏览器   │────────▶│            Nginx (:2026)                       │   │
│   └──────────┘         │                                               │   │
│                         │  路由规则：                                      │   │
│                         │    /           → Frontend :3000 (Next.js)     │   │
│                         │    /api/langgraph/* → LangGraph Server :2024  │   │
│                         │    /api/*       → Gateway API :8001            │   │
│                         └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**浏览器、Nginx、Next.js 的分工**：

```
1. 浏览器请求 http://localhost:2026/
           │
           ▼
2. Nginx 收到请求，路由分发
           │
           ├── /api/langgraph/* → 转发到 LangGraph Server :2024
           ├── /api/*          → 转发到 Gateway API :8001
           │
           └── / 及其他       → 转发到 Frontend 容器 :3000
                                    │
                                    ▼
                              Next.js 生产服务器
                              (pnpm start)
                                    │
                                    ├── 渲染页面，返回 HTML
                                    └── 返回 JS/CSS 静态资源

3. 浏览器收到 HTML/JS，执行 JavaScript
           │
           ▼
4. React 运行在浏览器中，页面渲染完成
           │
           ▼
5. 用户交互触发，JS 中的 LangGraph SDK 发起 API 请求（也到 Nginx）
```

#### 代码调用链

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              前端 (Next.js)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  sendMessage() [frontend/src/core/threads/hooks.ts:202]                    │
│       │                                                                     │
│       ▼                                                                     │
│  thread.submit() [frontend/src/core/threads/hooks.ts:347]                   │
│       │                                                                     │
│       ▼                                                                     │
│  useStreamLGP.submit() [@langchain/langgraph-sdk]                          │
│       │                                                                     │
│       ├─── 首次对话: client.threads.create() ─────────────────────────────┐  │
│       │                              创建新 Thread                          │  │
│       │                                                                     │  │
│       ▼                                                                     │  │
│  client.runs.stream() ───────────────────────────────────────────────────┘  │
│       │                                                                     │
│       ▼                                                                     │
│  POST /api/langgraph/threads/{id}/runs/stream                              │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LangGraph Server (:2024)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  stream_run() [langgraph_api/api/runs.py]                                   │
│       │                                                                     │
│       ▼                                                                     │
│  Runs.Stream.subscribe()  ←─ 订阅 stream channel 用于实时推送                 │
│       │                                                                     │
│       ▼                                                                     │
│  create_valid_run()                                                         │
│       │                                                                     │
│       ├─── 加载 graph: "deerflow.agents:make_lead_agent"                      │
│       │                                                                     │
│       ▼                                                                     │
│  make_lead_agent(config)                                                    │
│       │                                                                     │
│       ├─── 解析配置: model_name, thinking_enabled, is_plan_mode 等          │
│       ├─── create_chat_model() → GLM-4.7                                    │
│       ├─── get_available_tools() → 获取工具列表                             │
│       ├─── _build_middlewares() → 构建中间件链                              │
│       │                                                                     │
│       ▼                                                                     │
│  create_agent() → 创建可执行的 Agent                                         │
│       │                                                                     │
│       ▼                                                                     │
│  Agent 执行 + 流式返回                                                       │
│       │                                                                     │
│       ▼                                                                     │
│  EventSourceResponse (SSE)                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SSE 流式响应                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  event: messages-tuple                                                       │
│  data: [{"type": "ai", "content": "Hello!"}]                                │
│                                                                              │
│  event: values                                                               │
│  data: {"messages": [...], "title": "hello", "artifacts": [], "todos": []} │
│                                                                              │
│  event: end                                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              前端回调处理                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  onUpdateEvent(data) → 更新 thread 状态，触发 UI 渲染                        │
│  onLangChainEvent(event) → 处理 tool_end 等事件                              │
│  onFinish(state) → 完成处理，可能触发 suggestions 生成                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 首次对话 vs 后续对话的差异

| 方面 | 首次对话 | 后续对话 |
|------|---------|---------|
| **Thread 创建** | `useStreamLGP.submit()` 内部先调用 `POST /threads` 创建 | 复用已有 thread_id |
| **状态加载** | Checkpointer 返回空状态 `{}` | Checkpointer 加载历史 messages |
| **messages 内容** | 只有当前用户消息 + AI 回复 | 包含所有历史 + 新消息 |
| **Title 生成** | `TitleMiddleware` 生成对话标题 | 使用已有的 title |
| **Middleware 行为** | 部分 middleware 跳过初始化逻辑 | 全部 middleware 正常执行 |

**首次对话的 Thread 状态变化**：

```
Before (空状态):
values = {
    "title": null,
    "messages": [],
    "artifacts": [],
    "todos": []
}

After (首次消息后):
values = {
    "title": "hello",           ← TitleMiddleware 生成
    "messages": [
        {"type": "human", "content": "hello"},
        {"type": "ai", "content": "Hi! How can I help?"}
    ],
    "artifacts": [],
    "todos": []
}
```

**后续对话的 Thread 状态变化**：

```
Before (已有状态):
values = {
    "title": "hello",
    "messages": [
        {"type": "human", "content": "hello"},
        {"type": "ai", "content": "Hi!"}
    ],
    ...
}

After (追加新消息后):
values = {
    "title": "hello",           ← 保持不变
    "messages": [
        {"type": "human", "content": "hello"},
        {"type": "ai", "content": "Hi!"},
        {"type": "human", "content": "帮我写代码"},
        {"type": "ai", "content": "好的，我来帮你..."}  ← 追加，不是替换
    ],
    ...
}
```

**关键点**：
- Thread 不会重建，每次只是在 messages 末尾追加
- AI 可以看到完整的对话历史（messages 列表）
- artifacts 和 todos 是累加的（通过 `merge_artifacts` reducer）

#### Lead Agent 中间件链

```
用户消息输入
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Middleware Chain (按顺序执行)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. ToolErrorHandlingMiddleware     - 工具错误处理                            │
│  2. SummarizationMiddleware        - 长对话摘要 (可选)                       │
│  3. TodoListMiddleware            - Plan 模式的待办列表                      │
│  4. TokenUsageMiddleware           - Token 用量统计                           │
│  5. TitleMiddleware                - 生成对话标题 (仅首次)                    │
│  6. MemoryMiddleware               - 记忆管理                                │
│  7. ViewImageMiddleware            - 图片处理                                │
│  8. DeferredToolFilterMiddleware   - 延迟工具过滤                            │
│  9. SubagentLimitMiddleware        - 子代理数量限制                          │
│ 10. LoopDetectionMiddleware        - 循环检测                                │
│ 11. ClarificationMiddleware        - 需求澄清                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LLM (GLM-4.7)                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  输入: 完整 messages 列表 + system prompt                                   │
│  输出: AI 响应文本 / 工具调用                                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         状态更新 + 持久化                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ThreadState 更新:                                                           │
│    - messages: 追加 AI 回复                                                  │
│    - artifacts: 可能追加新文件路径                                            │
│    - todos: 可能更新任务状态                                                 │
│    - title: 可能更新 (如为空)                                                │
│                                                                              │
│  Checkpointer 持久化:                                                        │
│    - InMemorySaver: 存内存                                                  │
│    - SqliteSaver: 存文件                                                    │
│    - PostgresSaver: 存数据库                                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 请求/响应示例

**请求示例**：

```http
POST /api/langgraph/threads/6ac61487-4921-4693-8c84-4220b405cbd5/runs/stream
Content-Type: application/json

{
  "assistantId": "lead_agent",
  "input": {
    "messages": [{"type": "human", "content": [{"type": "text", "text": "hello"}]}]
  },
  "config": { "recursion_limit": 1000 },
  "streamMode": ["messages-tuple", "values"]
}
```

**流式响应**：

```
event: messages-tuple
data: [{"type": "ai", "content": "Hello! How can I help you?"}]

event: values
data: {"messages": [...], "title": "hello", "artifacts": [], "todos": []}

event: end
data: {}
```

---

### 4.3.1 `make_lead_agent()` 工厂调用链详解（每条消息触发 2 次）

每条用户消息会触发 **2 次** `make_lead_agent()` 工厂函数调用，分别来自 `POST /runs/stream` 和 `POST /history` 两个入口。

#### 调用链概览

```
用户发送消息
    │
    ├──► POST /runs/stream (access_context="threads.create_run")
    │        langgraph_api/api/runs.py:284-308
    │              │
    │              ▼
    │        stream_run()
    │              │
    │              ▼
    │        astream_state() ──► get_graph(access_context="threads.create_run")
    │              │            langgraph_api/stream.py:165-175
    │              │                  │
    │              │                  ▼
    │              │            is_factory(graph_id) @ langgraph_api/graph.py:216
    │              │                  │
    │              │                  ▼
    │              │            invoke_factory() @ langgraph_api/graph.py:240
    │              │                  │
    │              │                  ▼
    │              │            is_for_execution() @ _factory_utils.py:147-148
    │              │                  │  (决定是否执行为主 agent)
    │              │                  ▼
    │              │            make_lead_agent() @ deerflow/agents/lead_agent/agent.py:300-309
    │
    └──► POST /history (access_context="threads.read")
             langgraph_api/api/threads.py:554-557 (路由)
                   │
                   ▼
             get_thread_history_post()
             langgraph_api/api/threads.py:354-377
                   │
                   ▼
             Threads.State.list() ──► get_graph(access_context="threads.read")
                   │                  langgraph_runtime_inmem/ops.py:1877
                   │                        │
                   │                        ▼
                   │                  is_factory(graph_id) @ langgraph_api/graph.py:216
                   │                        │
                   │                        ▼
                   │                  invoke_factory() @ langgraph_api/graph.py:240
                   │                        │
                   │                        ▼
                   │                  is_for_execution() @ _factory_utils.py:147-148
                   │                        │  (决定是否执行为主 agent)
                   │                        ▼
                   │                  make_lead_agent() @ deerflow/agents/lead_agent/agent.py:300-309
```

#### 关键源码分析

**1. 路由定义**

`POST /runs/stream` 路由：
```python
# langgraph_api/api/runs.py:938
router.add_api_route(
    "/runs/stream",
    stream_run,
    methods=["POST"],
    ...
)
```

`POST /history` 路由：
```python
# langgraph_api/api/threads.py:554-557
router.add_api_route(
    "/{thread_id}/history",
    get_thread_history_post,
    methods=["POST"],
    ...
)
```

**2. stream_run() 调用 get_graph**

```python
# langgraph_api/api/runs.py:284-308
async def stream_run(...):
    ...
    async for event in astream_state(
        assistant_id=assistant_id,
        thread_id=thread_id,
        run_id=run_id,
        access_context="threads.create_run",  # <-- 关键：access_context
        ...
    ):
        yield event
```

**3. get_thread_history_post() 调用 Threads.State.list**

```python
# langgraph_api/api/threads.py:354-377
async def get_thread_history_post(...):
    ...
    return await Threads.State.list(
        thread_id=thread_id,
        ...
        access_context="threads.read",  # <-- 关键：access_context
    )
```

**4. astream_state() 调用 get_graph**

```python
# langgraph_api/stream.py:165-175
async def astream_state(...):
    ...
    graph = await get_graph(
        graph_id=assistant_id,
        access_context=access_context,  # "threads.create_run"
    )
    ...
```

**5. Threads.State.list() 调用 get_graph**

```python
# langgraph_runtime_inmem/ops.py:1877-1883
class State:
    @classmethod
    async def list(cls, ..., access_context: str = None, ...):
        ...
        graph = await get_graph(
            graph_id=assistant_id,
            access_context=access_context,  # "threads.read"
        )
```

**6. get_graph() 中的 is_factory() 检查**

```python
# langgraph_api/graph.py:216-240
async def get_graph(graph_id, access_context, ...):
    ...
    if is_factory(graph_id):  # line 216 - 检查是否是工厂
        kwargs = await invoke_factory(  # line 240 - 调用工厂
            graph_id=graph_id,
            access_context=access_context,
            ...
        )
        ...
```

**7. invoke_factory() 实现**

```python
# langgraph_api/_factory_utils.py:173-184
async def invoke_factory(graph_id, access_context, ...):
    factory_fn = FACTORY_KWARGS[graph_id]["factory_fn"]
    factory_kwargs = await factory_fn(
        access_context=access_context,
        ...
    )
    return factory_kwargs
```

**8. is_for_execution() 判断逻辑**

```python
# langgraph_api/_factory_utils.py:147-148
def is_for_execution(access_context: str) -> bool:
    return access_context == "threads.create_run"
```

**注意**：`is_for_execution()` 虽然根据 `access_context` 决定是否"执行"为主 agent，但 **工厂函数本身仍会被调用**，因为 `invoke_factory()` 在 `get_graph()` 的 line 240 无条件执行。

**9. make_lead_agent() 工厂函数**

```python
# deerflow/agents/lead_agent/agent.py:300-309
def make_lead_agent(access_context: str, **kwargs) -> dict:
    logger.info(
        "make_lead_agent() called",
        access_context=access_context,
        ...
    )
    ...
    return {
        "graph": lead_agent,
        ...
    }
```

#### 总结

| 入口 | access_context | is_for_execution | 是否调用工厂 |
|------|----------------|------------------|-------------|
| `POST /runs/stream` | `threads.create_run` | `True` | ✅ 是 |
| `POST /history` | `threads.read` | `False` | ✅ 是 |

**核心发现**：`access_context` 只控制 `is_for_execution()` 的返回值（决定是否作为主 agent 执行），但 **不阻止** `invoke_factory()` 的调用。因此每条消息都会触发 **2 次** `make_lead_agent()` 调用。

---

### 4.4 `POST /api/threads/{id}/suggestions` - 生成后续问题建议

**含义**：基于对话历史生成后续问题建议

**这是 Gateway API，不是 LangGraph API**

**调用链**：

```
Frontend: Agent 响应完成
    │
    ▼
POST /api/threads/{id}/suggestions
    │
    ▼
Nginx → Gateway API :8001
    │
    ▼
┌────────────────────────────────────────┐
│         Gateway API 内部               │
│                                        │
│  suggestions.py:generate_suggestions()  │
│                                        │
│  1. 接收对话历史 messages              │
│  2. 调用 create_chat_model()          │
│  3. 使用 LLM 生成 3-5 个建议问题      │
│  4. 解析 LLM 返回的 JSON 数组         │
│  5. 清理和截断                        │
└────────────────────────────────────────┘
    │
    ▼
返回 SuggestionsResponse
```

**核心逻辑**：

```python
prompt = (
    "You are generating follow-up questions...\n"
    f"Based on the conversation below, produce EXACTLY {n} short questions...\n"
    "Conversation:\n"
    f"{conversation}\n"
)

model = create_chat_model(name=request.model_name, thinking_enabled=False)
response = model.invoke(prompt)
suggestions = _parse_json_string_list(response.content) or []
```

**请求/响应**：

```http
POST /api/threads/6ac61487-4921-4693-8c84-4220b405cbd5/suggestions
Content-Type: application/json

{
  "messages": [
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "Hello! How can I help you?"}
  ],
  "n": 3
}
```

```json
{
  "suggestions": [
    "What can you help me with?",
    "Tell me about yourself",
    "How do I use this app?"
  ]
}
```

---

### 4.5 `POST /api/langgraph/threads/{id}/history` - 获取历史消息

**含义**：获取 Thread 的完整历史消息

**调用时机**：
- 页面加载时恢复历史消息
- 切换 thread 时加载历史

**调用链**：

```
Frontend: 加载 thread 页面
    │
    ▼
useStream() [frontend/src/core/threads/hooks.ts:113]
    │
    ▼
SDK 内部: 获取 thread 历史
    │
    ▼
POST /api/langgraph/threads/{id}/history
    │
    ▼
Checkpointer 读取 thread 状态历史
    │
    ▼
返回历史消息数组
```

**响应**：

```json
{
  "messages": [
    {"type": "human", "content": "hello", "id": "msg1"},
    {"type": "ai", "content": "Hello! How can I help you?", "id": "msg2"}
  ]
}
```

---

## 5. 前端代码如何到达浏览器

### 5.1 开发环境 vs 生产环境

| 环境 | 请求路径 | 说明 |
|------|---------|------|
| **开发环境** | 浏览器 → `localhost:3000` → Next.js | Next.js Dev Server 处理所有请求 |
| **生产环境** | 浏览器 → `localhost:2026` → Nginx → 后端服务 | Nginx 反向代理所有请求 |

### 5.2 Next.js 生产服务器

**Next.js `pnpm start` 不是静态文件服务器，而是运行在 Node.js 上的生产服务器**

```
Nginx (:2026)
    │
    └── / 路由 → proxy_pass http://frontend:3000
                    │
                    ▼
              Next.js (pnpm start)
                    │
                    ├── 渲染页面 → 返回 HTML
                    └── 返回 JS/CSS 静态资源
```

### 5.3 React 代码执行流程

**核心概念：Next.js 把 React 组件编译成 JavaScript，浏览器执行 JS 来渲染页面**

```
浏览器请求页面
    │
    ▼
Nginx → Frontend :3000 (Next.js)
    │
    ├── 路由匹配: /workspace/chats/[thread_id]
    ├── 渲染 React 组件 (Server Components)
    └── 返回 HTML + JS bundle URL
    │
    ▼
浏览器下载并执行 JavaScript
    │
    ▼
React 初始化 → 路由匹配 → ChatPage 组件渲染
    │
    ▼
用户看到页面（消息列表、输入框）
    │
    ▼
用户输入文字，点击发送
    │
    ▼
InputBox 组件调用 onSubmit={handleSubmit}
    │
    ▼
handleSubmit 调用 sendMessage(threadId, message)
    │
    ▼
sendMessage 内部调用 thread.submit()
    │
    ▼
thread.submit() 调用 client.runs.stream()
    │
    ▼
发起 HTTP 请求到后端
```

### 5.4 浏览器如何知道调用 sendMessage()？

```typescript
// page.tsx - 开发者写的代码
export default function ChatPage() {
  const [thread, sendMessage, isUploading] = useThreadStream({ ... });
  
  const handleSubmit = (message) => {
    sendMessage(threadId, message);  // ← 这是开发者写的
  };
  
  return <InputBox onSubmit={handleSubmit} />;
}
```

**编译后的 JavaScript（在浏览器中执行）**：

```javascript
// 同样的逻辑，浏览器执行
function ChatPage() {
  const [thread, sendMessage] = useThreadStream({ ... });
  
  function handleSubmit(message) {
    sendMessage(threadId, message);
  }
  
  return React.createElement(InputBox, { onSubmit: handleSubmit });
}
```

### 5.5 React 的工作方式

```
1. 组件定义 → useThreadStream() → 返回 sendMessage

2. 组件渲染 → React.createElement() → 生成虚拟 DOM

3. 虚拟 DOM → 真实 DOM 更新 → 用户看到页面

4. 用户交互 → 事件触发 → 回调函数执行
```

**总结**：Next.js 把 TypeScript/React 代码编译成 JavaScript，浏览器下载并执行这些 JS，React 框架负责渲染组件和处理用户交互。开发者写的 `useThreadStream` 和 `sendMessage` 都是普通的 JavaScript 函数，编译后浏览器直接执行。

---

## 6. 端到端完整流程

```
用户输入 "hello" 并发送
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. thread.submit() → threads.create()                            │
│    确保存在 thread_id                                            │
│    API: POST /api/langgraph/threads                             │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. client.runs.stream() - 核心交互                              │
│    发送消息并接收流式响应                                         │
│    API: POST /api/langgraph/threads/{id}/runs/stream            │
│                                                                 │
│    内部: Lead Agent → GLM-4.7 → Middleware → Skills → Sandbox   │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. useStream.onFinish() 回调                                    │
│    更新 UI 状态，触发 suggestions 生成                           │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. POST /api/threads/{id}/suggestions                           │
│    Gateway API 调用 LLM 生成推荐问题                            │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. 前端显示:                                                     │
│    - AI 回复文本                                                 │
│    - 推荐问题列表                                                │
│    - 更新 thread 列表                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 如何观察 Thread 内容？

### 7.1 日志打印

DeerFlow 在多个关键位置打印 Thread 相关信息：

```python
# app/channels/manager.py
logger.info("[Manager] new thread created on LangGraph Server: thread_id=%s", thread_id)
logger.info("[Manager] reusing thread: thread_id=%s", thread_id)
logger.info("[Manager] invoking runs.wait(thread_id=%s, text=%r)", thread_id, msg.text)

# app/gateway/routers/threads.py
logger.info("Deleted local thread data for %s", thread_id)

# packages/harness/deerflow/agents/checkpointer/provider.py
logger.info("Checkpointer: using InMemorySaver (in-process, not persistent)")
logger.info("Checkpointer: using SqliteSaver (%s)", conn_str)
```

**启用 DEBUG 日志查看更多**：

```bash
# 在 .env 或 docker-compose.yaml 中设置
LOG_LEVEL=DEBUG
```

### 7.2 代码调试

**在 Python 代码中打印 Thread 状态**：

```python
# 获取当前 checkpointer
from deerflow.agents.checkpointer import get_checkpointer

checkpointer = get_checkpointer()

# 查看所有 thread（InMemorySaver）
if hasattr(checkpointer, '_storage'):
    print(checkpointer._storage)
    # {'thread-1': {'values': {...}, 'metadata': {...}}}

# 查看 SqliteSaver
import sqlite3
conn = sqlite3.connect('.deer-flow/checkpoints.db')
cursor = conn.execute("SELECT * FROM checkpoint_blobs LIMIT 10")
```

**使用 LangGraph SDK 查看 Thread**：

```python
from langgraph_sdk import get_client

client = get_client(url="http://localhost:2024")

# 获取单个 thread
thread = await client.threads.get("thread-id")
print(thread)

# 获取 thread 历史
history = await client.threads.history("thread-id")
print(history)

# 获取当前状态
state = await client.threads.get_state("thread-id")
print(state)
```

### 7.3 LangSmith 观测

LangSmith 是 LangChain 官方提供的调试和观测平台。

**启用 LangSmith**：

```bash
# 在 .env 中配置
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-api-key
LANGSMITH_PROJECT=deer-flow
```

**LangSmith 可以看到**：
- 每次 LLM 调用的输入/输出
- Tool 执行的调用链
- Thread 完整对话历史
- Token 使用量统计
- 端到端延迟分析

**访问地址**：https://smith.langchain.com/

---

## 8. 关键源码文件索引

### 8.1 LangGraph 官方包（第三方）

> 安装在虚拟环境的 `site-packages/` 目录下

| 功能 | 路径 |
|------|------|
| threads API 路由定义 | `langgraph_api/api/threads.py` |
| runs API（流式等） | `langgraph_api/api/runs.py` |
| Server 启动和挂载 | `langgraph_api/server.py` |
| ApiRoute 路由类 | `langgraph_api/route.py` |
| Thread 数据模型 | `langgraph_api/schema.py` |
| SDK ThreadsClient | `langgraph_sdk/_async/threads.py` |

### 8.2 DeerFlow 项目文件

| 功能 | 路径 |
|------|------|
| 前端 API Client | `frontend/src/core/api/api-client.ts` |
| Thread Hooks | `frontend/src/core/threads/hooks.ts` |
| Gateway Suggestions | `app/gateway/routers/suggestions.py` |
| Gateway Threads | `app/gateway/routers/threads.py` |
| Channel Manager | `app/channels/manager.py` |
| Lead Agent | `packages/harness/deerflow/agents/lead_agent/agent.py` |
| Checkpointer 配置 | `packages/harness/deerflow/config/checkpointer_config.py` |
| Checkpointer Provider | `packages/harness/deerflow/agents/checkpointer/async_provider.py` |
| Thread State | `packages/harness/deerflow/agents/thread_state.py` |
| Nginx Config | `docker/nginx/nginx.conf` |

---

## 9. 总结

| API | 服务 | 作用 |
|-----|------|------|
| `POST /api/langgraph/threads` | LangGraph Server | 创建新会话线程 |
| `POST /api/langgraph/threads/search` | LangGraph Server | 搜索/列出线程列表 |
| `POST /api/langgraph/threads/{id}/runs/stream` | LangGraph Server | **核心**：发送消息并流式响应 |
| `POST /api/threads/{id}/suggestions` | Gateway API | 生成后续问题建议 |
| `POST /api/langgraph/threads/{id}/history` | LangGraph Server | 获取线程历史消息 |

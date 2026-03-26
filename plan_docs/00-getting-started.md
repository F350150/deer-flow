# 00 - 如何学习 DeerFlow：从 make dev 开始

> **重要提示**：学习 DeerFlow 的最佳起点是理解 `make dev` 的完整执行流程。
>
> 本文档将帮助你：
> 1. 理解 `make dev` 到底做了什么
> 2. 追踪每个服务的启动过程
> 3. 找到每个阶段对应的源码
> 4. 知道如何深入学习每个部分

---

## 1.0 执行 `make dev` 之前发生了什么

### 1.1 检查 .env 文件

**目的**：加载环境变量（API keys 等敏感信息）

**源文件**：`scripts/serve.sh` 第 12-17 行

```bash
# serve.sh
if [ -f "$REPO_ROOT/.env" ]; then
    set -a              # 自动导出所有变量
    source "$REPO_ROOT/.env"  # 加载 .env 文件
    set +a
fi
```

**你的 .env 文件内容**：
```bash
GLM_API_KEY=
```

**学习要点**：
- `.env` 文件不被 git 追踪（见 `.gitignore`）
- 环境变量如何注入到配置中（`$GLM_API_KEY` 在 `config.yaml` 中引用）

---

### 1.2 检查 config.yaml

**目的**：确保配置文件存在

**源文件**：`scripts/serve.sh` 第 71-86 行

```bash
# serve.sh
if ! { \
        [ -n "$DEER_FLOW_CONFIG_PATH" ] && [ -f "$DEER_FLOW_CONFIG_PATH" ] || \
        [ -f backend/config.yaml ] || \
        [ -f config.yaml ]; \
    }; then
    echo "✗ No DeerFlow config file found."
    exit 1
fi
```

**配置查找顺序**：
1. `$DEER_FLOW_CONFIG_PATH` 环境变量
2. `backend/config.yaml`
3. `./config.yaml`

---

### 1.3 自动升级配置

**目的**：合并配置文件的最新字段

**源文件**：`scripts/serve.sh` 第 90 行

```bash
"$REPO_ROOT/scripts/config-upgrade.sh"
```

**源文件**：`scripts/config-upgrade.sh`

```bash
# 使用 Python 读取 config.yaml 和 config.example.yaml
# 合并缺失的字段
# 备份原文件为 config.yaml.bak
```

**学习要点**：
- `config.example.yaml` 是模板
- `config.yaml` 是你的实际配置
- `config_version: 3` 用于检测过时的配置

---

## 2.0 四个服务启动详解

### 2.1 服务启动总览

```
make dev
    ↓
scripts/serve.sh --dev
    ↓
    ┌─────────────────────────────────────────────┐
    │  Step 1: LangGraph Server (端口 2024)       │
    │  Step 2: Gateway API (端口 8001)            │
    │  Step 3: Frontend (端口 3000)               │
    │  Step 4: Nginx (端口 2026)                   │
    └─────────────────────────────────────────────┘
```

---

### 2.2 Step 1: LangGraph Server (端口 2024)

**命令**：`scripts/serve.sh` 第 135 行

```bash
(cd backend && NO_COLOR=1 uv run langgraph dev \
    --no-browser --allow-blocking --server-log-level $LANGGRAPH_LOG_LEVEL \
    $LANGGRAPH_EXTRA_FLAGS > ../logs/langgraph.log 2>&1) &
```

**发生了什么**：

```
1. cd backend
   ↓
2. uv run langgraph dev
   ↓
3. 启动 LangGraph 开发服务器
   ↓
4. 读取 config.yaml 加载 Agent 配置
   ↓
5. 等待端口 2024 就绪
```

**关键源文件**：

| 文件 | 作用 |
|------|------|
| `backend/langgraph.json` | LangGraph 服务器配置 |
| `backend/packages/harness/deerflow/agents/lead_agent/agent.py` | Agent 创建入口 |
| `backend/packages/harness/deerflow/config/app_config.py` | 配置加载 |

**学习要点**：
- `langgraph dev` 是 LangGraph CLI 命令
- 实际执行的是 `packages/harness/deerflow/agents/lead_agent/agent.py` 中的 `make_lead_agent`
- 日志输出到 `logs/langgraph.log`

**日志示例**：
```
# logs/langgraph.log
[2026-03-27 10:00:00] Create Agent(default) -> thinking_enabled: True, model_name: glm-4.7
```

---

### 2.3 Step 2: Gateway API (端口 8001)

**命令**：`scripts/serve.sh` 第 148 行

```bash
(cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app \
    --host 0.0.0.0 --port 8001 $GATEWAY_EXTRA_FLAGS \
    > ../logs/gateway.log 2>&1) &
```

**发生了什么**：

```
1. cd backend
   ↓
2. PYTHONPATH=. (设置 Python 路径)
   ↓
3. uv run uvicorn (运行 FastAPI 应用)
   ↓
4. 加载 app.gateway.app:app
   ↓
5. 等待端口 8001 就绪
```

**关键源文件**：

| 文件 | 作用 |
|------|------|
| `backend/app/gateway/app.py` | FastAPI 应用入口 |
| `backend/app/gateway/routers/` | REST API 路由 |
| `backend/packages/harness/deerflow/config/` | 配置加载 |

**Gateway API 路由**：

```
app/gateway/app.py (主应用)
    ↓
routers/
    ├── threads.py      # 线程管理 (/api/threads)
    ├── models.py       # 模型配置 (/api/models)
    ├── skills.py       # Skills 管理 (/api/skills)
    ├── uploads.py      # 文件上传 (/api/uploads)
    ├── artifacts.py    # Artifact 管理
    ├── mcp.py          # MCP 服务器配置
    └── suggestions.py  # 建议 API
```

**学习要点**：
- Gateway API 是纯 REST API
- 不参与 Agent 执行，只提供管理功能
- 使用 FastAPI + uvicorn

---

### 2.4 Step 3: Frontend (端口 3000)

**命令**：`scripts/serve.sh` 第 162 行

```bash
(cd frontend && pnpm run dev > ../logs/frontend.log 2>&1) &
```

**发生了什么**：

```
1. cd frontend
   ↓
2. pnpm run dev (Next.js 开发服务器)
   ↓
3. 启动 Next.js (React)
   ↓
4. 等待端口 3000 就绪
```

**关键源文件**：

| 文件 | 作用 |
|------|------|
| `frontend/src/core/api/api-client.ts` | LangGraph API 封装 |
| `frontend/src/core/threads/hooks.ts` | Thread 管理和 SSE 流 |
| `frontend/src/components/workspace/input-box.tsx` | 消息输入框 |
| `frontend/src/app/workspace/chats/[thread_id]/page.tsx` | 主聊天页面 |

**前端请求流程**：

```
用户输入消息
    ↓
InputBox 组件 (input-box.tsx)
    ↓
useThread hook (hooks.ts)
    ↓
api-client.ts (封装 LangGraph SDK)
    ↓
发送 SSE 请求到 LangGraph Server
    ↓
解析 SSE 流，更新 UI
```

---

### 2.5 Step 4: Nginx (端口 2026)

**命令**：`scripts/serve.sh` 第 171 行

```bash
nginx -g 'daemon off;' -c "$REPO_ROOT/docker/nginx/nginx.local.conf" \
    -p "$REPO_ROOT" > logs/nginx.log 2>&1 &
```

**发生了什么**：

```
1. 加载 Nginx 配置
   ↓
2. 监听端口 2026
   ↓
3. 路由请求到后端服务
```

**Nginx 配置解析**：`docker/nginx/nginx.local.conf`

```nginx
upstream langgraph {
    server localhost:2024;
}

upstream gateway {
    server localhost:8001;
}

upstream frontend {
    server localhost:3000;
}

server {
    listen 2026;

    # Agent 请求 (SSE 流式)
    location /api/langgraph/ {
        proxy_pass http://langgraph;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
    }

    # REST API 请求
    location /api/ {
        proxy_pass http://gateway;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
    }

    # 前端静态资源
    location / {
        proxy_pass http://frontend;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
    }
}
```

---

## 3.0 用户发送消息的完整流程

### 3.1 请求流程图

```
┌─────────┐
│ Browser │
└────┬────┘
     │ http://localhost:2026
     ↓
┌─────────┐
│  Nginx  │ (端口 2026)
└────┬────┘
     │
     ├─────────────────────────────────────────────┐
     │                                             │
     ↓                                             ↓
┌─────────┐                               ┌─────────────┐
│Frontend │                               │  Gateway    │
│ :3000   │                               │   :8001     │
│(Next.js)│                               │  (FastAPI)  │
└─────────┘                               └─────────────┘
     ↑                                             │
     │                                             │ REST API
     │                                             │ (模型配置等)
     │                                             ↓
     │                                    ┌─────────────┐
     │                                    │ config.yaml │
     │                                    └─────────────┘
     │
     │ SSE 流
     │
┌─────────┐
│LangGraph│
│ :2024   │
└────┬────┘
     │
     ├──────────────────────────────────────────────┐
     │                                              │
     ↓                                              ↓
┌─────────┐                                  ┌─────────────┐
│Lead     │                                  │   GLM-4.7   │
│ Agent   │ ──────────────────────────────→ │   API       │
└─────────┘                                  └─────────────┘
     │
     │ 工具调用
     ↓
┌─────────┐
│Sandbox  │
│(Local)  │
└─────────┘
```

### 3.2 时序图

```
用户           Frontend       Nginx        LangGraph       GLM-4.7
 │                │            │              │              │
 │ 输入消息       │            │              │              │
 │──────────────→│            │              │              │
 │                │            │              │              │
 │                │ /api/langgraph/...       │              │
 │                │───────────→│              │              │
 │                │            │ 转发 SSE     │              │
 │                │            │─────────────→│              │
 │                │            │              │              │
 │                │            │              │ invoke()     │
 │                │            │              │─────────────→│
 │                │            │              │              │
 │                │            │              │ 响应 token   │
 │                │            │              │←─────────────│
 │                │            │              │              │
 │                │            │   SSE 事件   │              │
 │                │   SSE 事件 │←─────────────│              │
 │                │←───────────│              │              │
 │                │            │              │              │
 │ 实时渲染        │            │              │              │
 │←───────────────│            │              │              │
 │                │            │              │              │
```

---

## 4.0 如何深入学习每个部分

### 4.1 学习路线图

```
Phase 1: 理解请求流程 (1-2 天)
    │
    ├→ 理解 Nginx 路由配置
    │       └→ docker/nginx/nginx.local.conf
    │
    ├→ 理解四服务架构
    │       └→ scripts/serve.sh
    │
    └→ 理解请求流程
            └→ 下面的"最小请求追踪练习"

Phase 2: Agent 核心 (5-7 天) ← 最重要
    │
    ├→ ThreadState 数据结构
    │       └→ packages/harness/deerflow/agents/thread_state.py
    │
    ├→ Lead Agent 创建
    │       └→ packages/harness/deerflow/agents/lead_agent/agent.py
    │
    ├→ 系统提示词
    │       └→ packages/harness/deerflow/agents/lead_agent/prompt.py
    │
    └→ Middleware Chain
            └→ packages/harness/deerflow/agents/middlewares/

Phase 3: 前端交互 (3-5 天)
    │
    ├→ API 客户端
    │       └→ frontend/src/core/api/api-client.ts
    │
    ├→ Thread Hooks
    │       └→ frontend/src/core/threads/hooks.ts
    │
    └→ SSE 流处理
            └→ frontend/src/core/threads/hooks.ts

Phase 4: Sandbox 执行 (5-7 天)
    │
    ├→ Sandbox 架构
    │       └→ packages/harness/deerflow/sandbox/
    │
    └→ 内置工具
            └→ packages/harness/deerflow/sandbox/tools.py
```

---

### 4.2 最小请求追踪练习

**目的**：追踪一条消息从发送到响应的完整流程

**步骤**：

1. **启动项目**
   ```bash
   make dev
   ```

2. **打开浏览器 DevTools**
   - Network 标签
   - 勾选 "Preserve log"

3. **发送简单消息**
   ```text
   你好
   ```

4. **追踪请求**

   你应该看到以下请求：

   | 请求 | 端口 | 作用 |
   |------|------|------|
   | `POST /api/langgraph/threads/xxx/runs` | 2026 → 2024 | 发送消息 |
   | `GET /api/langgraph/threads/xxx` | 2026 → 2024 | 获取状态 |
   | `GET /api/models` | 2026 → 8001 | 获取模型列表 |

5. **阅读源码**

   根据你看到的请求，阅读对应源码：

   ```bash
   # 查看 LangGraph Server 如何处理请求
   cat backend/packages/harness/deerflow/agents/lead_agent/agent.py

   # 查看 API 客户端
   cat frontend/src/core/api/api-client.ts

   # 查看 SSE 处理
   cat frontend/src/core/threads/hooks.ts
   ```

---

### 4.3 关键断点调试

**后端断点**：

```python
# backend/packages/harness/deerflow/agents/lead_agent/agent.py
# 在 make_lead_agent 函数中添加断点

def make_lead_agent(config: RunnableConfig):
    import pdb; pdb.set_trace()  # 添加这行
    # ...
```

**前端断点**：

```typescript
// frontend/src/core/threads/hooks.ts
// 在 stream 回调中添加断点

for await (const event of stream) {
    debugger;  // 添加这行
    console.log(event);
}
```

---

## 5.0 源码阅读顺序建议

### 5.1 按请求流程阅读

```
1. Nginx 配置 (理解路由)
   └→ docker/nginx/nginx.local.conf

2. 启动脚本 (理解服务)
   └→ scripts/serve.sh

3. LangGraph Server (理解 Agent)
   └→ backend/packages/harness/deerflow/agents/lead_agent/agent.py
   └→ backend/packages/harness/deerflow/agents/thread_state.py

4. 系统提示词 (理解行为)
   └→ backend/packages/harness/deerflow/agents/lead_agent/prompt.py

5. 前端交互 (理解前后端通信)
   └→ frontend/src/core/api/api-client.ts
   └→ frontend/src/core/threads/hooks.ts
```

### 5.2 按重要性阅读

```
⭐⭐⭐⭐⭐ 必须掌握
   ├→ thread_state.py (状态定义)
   ├→ agent.py (Agent 创建)
   └→ prompt.py (提示词)

⭐⭐⭐⭐ 建议掌握
   ├→ sandbox.py (沙箱执行)
   ├→ middleware base.py (中间件机制)
   └→ api-client.ts (前端 API)

⭐⭐⭐ 了解即可
   ├→ Gateway routers (REST API)
   ├→ Memory system (记忆系统)
   └→ MCP integration (MCP 协议)
```

---

## 6.0 常见问题排查

### 6.1 端口被占用

```bash
# 查找占用端口的进程
lsof -i :2024
lsof -i :8001
lsof -i :3000
lsof -i :2026

# 停止占用进程
kill -9 <PID>
```

### 6.2 查看日志

```bash
# 查看所有日志
tail -f logs/*.log

# 查看特定日志
tail -f logs/langgraph.log
tail -f logs/gateway.log
tail -f logs/frontend.log
```

### 6.3 重启单个服务

```bash
# 停止所有服务
make stop

# 只启动 LangGraph
cd backend && uv run langgraph dev

# 只启动 Gateway
cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --port 8001
```

---

## 7.0 练习题

### 练习 1: 追踪配置加载

**问题**: GLM-4.7 的 API Key 是如何从 `.env` 传递到 `config.yaml`，最终被 LangGraph 使用的？

**提示**:
1. 查看 `scripts/serve.sh` 如何加载 .env
2. 查看 `config.yaml` 中 `$GLM_API_KEY` 的引用
3. 查看 `app_config.py` 中 `resolve_env_variables` 方法

### 练习 2: 追踪消息流程

**问题**: 用户发送"你好"，消息是如何到达 Agent 并返回的？

**提示**:
1. 在 `frontend/src/core/threads/hooks.ts` 中找到 `sendMessage` 函数
2. 追踪 `client.runs.stream` 调用
3. 在后端找到 Agent 处理入口

### 练习 3: 修改 Nginx 路由

**问题**: 如何添加一个新的路由 `/api/custom` 到 Gateway API？

**提示**:
1. 查看 `docker/nginx/nginx.local.conf`
2. 添加新的 `location /api/custom` 块
3. 重启 Nginx 测试

---

## 8.0 下一步

现在你已经理解了 `make dev` 的完整流程，接下来：

**[01-Phase 1: 项目整体架构](./01-phase1-architecture.md)**

深入学习三服务架构和 Nginx 路由配置。

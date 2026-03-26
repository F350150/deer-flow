# 详解前后端联动

> 深入解析 DeerFlow 项目中前端与后端（LangGraph Server、Gateway API）之间的通信机制、数据流转和集成模式

---

## 1. 架构概述

### 1.1 三层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户浏览器 (Browser)                         │
│                           React 19 + Next.js                         │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│    Nginx      │       │    Nginx      │       │    Nginx      │
│   Port 2026   │       │   Port 2026   │       │   Port 2026   │
│ (统一入口)    │       │ (统一入口)    │       │ (统一入口)    │
└───────┬───────┘       └───────┬───────┘       └───────┬───────┘
        │                       │                       │
        │ /api/langgraph/*      │ /api/*                │ /*
        ▼                       ▼                       ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│  LangGraph    │       │   Gateway     │       │   Frontend    │
│   Server      │       │    API        │       │   Dev Server  │
│   :2024       │       │   :8001       │       │   :3000       │
└───────┬───────┘       └───────┬───────┘       └───────────────┘
        │                       │
        │                       │
        ▼                       ▼
┌───────────────┐       ┌───────────────┐
│  Checkpointer │       │   文件系统    │
│  (状态持久化) │       │   (.deer-flow)│
└───────────────┘       └───────────────┘
```

### 1.2 前端的两套 API 客户端

```typescript
// 1. LangGraph SDK - 与 LangGraph Server 通信
// core/api/api-client.ts
import { Client as LangGraphClient } from "@langchain/langgraph-sdk";
const langgraphClient = new LangGraphClient({ apiUrl: getLangGraphBaseURL() });

// 2. Fetch API - 与 Gateway API 通信
// 直接使用 fetch 或 axios
const response = await fetch(`${getBackendBaseURL()}/api/threads/${threadId}`, {
  method: "DELETE",
});
```

---

## 2. API 端点映射

### 2.1 LangGraph Server API (Port 2024)

| 前端调用 | Nginx 路由 | 最终路径 | 用途 |
|----------|-----------|---------|------|
| `POST /api/langgraph/threads` | `/api/langgraph/*` → `:2024` | `/threads` | 创建 thread |
| `POST /api/langgraph/threads/search` | → `:2024` | `/threads/search` | 搜索 threads |
| `GET /api/langgraph/threads/{id}` | → `:2024` | `/threads/{id}` | 获取 thread |
| `DELETE /api/langgraph/threads/{id}` | → `:2024` | `/threads/{id}` | 删除 thread |
| `POST /api/langgraph/threads/{id}/runs/stream` | → `:2024` | `/threads/{id}/runs/stream` | **流式发送消息** |
| `POST /api/langgraph/threads/{id}/history` | → `:2024` | `/threads/{id}/history` | 获取历史 |

### 2.2 Gateway API (Port 8001)

| 前端调用 | Nginx 路由 | 路由定义 | 用途 |
|----------|-----------|---------|------|
| `POST /api/threads/{id}/suggestions` | `/api/*` → `:8001` | `suggestions.py` | 生成后续问题 |
| `DELETE /api/threads/{id}` | → `:8001` | `threads.py` | 删除本地文件 |
| `POST /api/threads/{id}/uploads` | → `:8001` | `uploads.py` | 上传文件 |
| `GET /api/models` | → `:8001` | `models.py` | 获取模型列表 |
| `GET /api/skills` | → `:8001` | `skills.py` | 获取 skills |
| `GET /api/memory` | → `:8001` | `memory.py` | 获取记忆 |

---

## 3. 核心联动流程

### 3.1 发送消息完整流程

```
用户输入 "hello" 并点击发送
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 前端 (React 组件)                                                │
│                                                                 │
│ components/workspace/chats/chat-box.tsx                         │
│   └─→ useThreadStream().sendMessage(threadId, message)          │
│         │                                                        │
│         ▼                                                        │
│ core/threads/hooks.ts:sendMessage()                             │
│   │                                                            │
│   ├─→ 1. 文件上传（如有）                                        │
│   │     POST /api/threads/{id}/uploads → Gateway API           │
│   │                                                            │
│   └─→ 2. 提交消息                                               │
│         thread.submit({ messages: [...] }, { config, context }) │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ LangGraph SDK Client                                             │
│                                                                 │
│ core/api/api-client.ts                                          │
│   └─→ client.runs.stream(threadId, assistantId, payload)        │
│         │                                                        │
│         ▼                                                        │
│ POST /api/langgraph/threads/{threadId}/runs/stream              │
│   Content-Type: application/json                                 │
│   {                                                              │
│     "assistantId": "lead_agent",                                 │
│     "input": { "messages": [...] },                             │
│     "config": { "recursion_limit": 1000 },                      │
│     "streamMode": ["messages-tuple", "values"]                  │
│   }                                                              │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ Nginx 路由转发                                                   │
│                                                                 │
│ location /api/langgraph/ {                                       │
│     rewrite ^/api/langgraph/(.*) /$1 break;                     │
│     proxy_pass http://langgraph;  # → :2024                      │
│ }                                                                │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ LangGraph Server (:2024)                                        │
│                                                                 │
│ 1. 接收请求                                                      │
│ 2. 加载 Thread 状态（Checkpointer）                              │
│ 3. 执行 Lead Agent 图                                            │
│    - 输入预处理                                                  │
│    - 调用 LLM (GLM-4.7)                                          │
│    - Middleware Chain                                            │
│    - Tools / Skills 执行                                        │
│    - Sandbox 执行（如需）                                        │
│ 4. 流式返回 SSE 响应                                             │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼ (SSE Stream)
┌─────────────────────────────────────────────────────────────────┐
│ 前端接收流式响应                                                 │
│                                                                 │
│ core/threads/hooks.ts:useStream()                                │
│   │                                                            │
│   ├─→ onCreated(meta)        # Thread 创建时                   │
│   ├─→ onLangChainEvent()     # LLM 事件（如 tool_end）          │
│   ├─→ onUpdateEvent()        # 状态更新（messages, artifacts） │
│   ├─→ onCustomEvent()        # 自定义事件（如 task_running）    │
│   └─→ onFinish()             # 完成时                          │
│         │                                                        │
│         ▼                                                        │
│   更新 TanStack Query 缓存                                       │
│   触发组件重新渲染                                                │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 生成后续问题建议                                                 │
│                                                                 │
│ POST /api/threads/{threadId}/suggestions → Gateway API :8001   │
│   { "messages": [...], "n": 3 }                                │
│                                                                 │
│ Gateway 调用 create_chat_model()                                │
│   └─→ LLM 生成建议问题                                          │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Thread 生命周期管理

```
┌─────────────────┐
│  用户打开页面    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. 获取 Thread 列表                                               │
│    useThreads() → GET /api/langgraph/threads/search              │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 选择/创建 Thread                                               │
│                                                                 │
│ 情况 A: 选择已有 Thread                                          │
│   └─→ 加载历史消息                                               │
│       GET /api/langgraph/threads/{id}/history                    │
│                                                                 │
│ 情况 B: 新建 Thread                                               │
│   └─→ POST /api/langgraph/threads                               │
│       (在首次发送消息时触发)                                      │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. 发送消息                                                       │
│    POST /api/langgraph/threads/{id}/runs/stream                  │
│    (SSE 流式响应)                                                │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Thread 状态更新                                                │
│                                                                 │
│ - Checkpointer 保存状态                                          │
│ - AssistantId: "lead_agent"                                      │
│ - Values: { title, messages, artifacts, todos }                │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. 删除 Thread (可选)                                            │
│                                                                 │
│ 前端: useDeleteThread()                                          │
│   ├─→ DELETE /api/langgraph/threads/{id}  (LangGraph Server)  │
│   └─→ DELETE /api/threads/{id}            (Gateway API)         │
│       - LangGraph thread 删除 (状态)                            │
│       - 本地文件系统清理 (.deer-flow/threads/{id}/)             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 数据模型映射

### 4.1 Thread 数据结构

```typescript
// LangGraph SDK 返回的 Thread 类型
interface Thread<T = Record<string, unknown>> {
  thread_id: string;
  created_at: string;
  updated_at: string;
  metadata?: T;
}

// DeerFlow 的 AgentThreadState
interface AgentThreadState {
  title: string;           // 对话标题
  messages: Message[];     // 消息列表
  artifacts: string[];    // 文件路径列表
  todos?: Todo[];         // 任务列表
}
```

### 4.2 Message 数据结构

```typescript
// LangChain Message 类型
interface Message {
  type: "human" | "ai" | "system" | "tool";
  id: string;
  content: string | ContentBlock[];
  name?: string;          // tool 消息需要
  tool_call_id?: string;  // tool 消息需要
}

type ContentBlock =
  | { type: "text"; text: string }
  | { type: "image"; source: { type: "base64"; media_type: string; data: string } }
  | { type: "tool_result"; tool: { id: string; name: string }; content: string }
  // ...
```

### 4.3 前后端字段对应

| 前端 (TypeScript) | 后端 (Python) | 说明 |
|------------------|--------------|------|
| `Message.type` | `Message.type` | `human`, `ai`, `tool` |
| `Message.content` | `Message.content` | 消息内容 |
| `AgentThreadState.title` | `ThreadState.title` | 对话标题 |
| `AgentThreadState.messages` | `ThreadState.messages` | 消息列表 |
| `AgentThreadState.artifacts` | `ThreadState.artifacts` | 文件列表 |
| `AgentThreadState.todos` | `ThreadState.todos` | 任务列表 |

---

## 5. 流式响应机制

### 5.1 SSE (Server-Sent Events)

LangGraph 使用 SSE 进行流式传输：

```typescript
// 请求头
POST /api/langgraph/threads/{id}/runs/stream
Accept: text/event-stream
Content-Type: application/json

// 响应流格式
event: messages-tuple
data: [{"type":"human","content":"hello"}]

event: values
data: {"messages":[...],"title":"hello","artifacts":[]}

event: end
data: {}
```

### 5.2 streamMode 选项

```typescript
// core/threads/hooks.ts:572
client.runs.stream(threadId, assistantId, {
  input: { messages: [...] },
  streamMode: ["messages-tuple", "values"],  // 两种模式
});

// - messages-tuple: 增量消息更新
// - values: 完整状态快照
```

### 5.3 前端流式处理

```typescript
// core/threads/hooks.ts 回调处理
onLangChainEvent(event) {
  if (event.event === "on_tool_end") {
    // 工具执行完成
    listeners.current.onToolEnd?.({ name: event.name, data: event.data });
  }
}

onUpdateEvent(data) {
  // values 模式更新
  const updates = Object.values(data || {});
  for (const update of updates) {
    if (update && "title" in update) {
      // 更新 thread 标题
    }
  }
}
```

---

## 6. TanStack Query 缓存策略

### 6.1 缓存失效机制

```typescript
// 发送消息成功后
onFinish(state) {
  // 立即失效 threads 列表缓存，触发重新获取
  void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
}

// 删除 thread 后
onSuccess(_, { threadId }) {
  // 乐观更新：直接从缓存移除
  queryClient.setQueriesData(
    { queryKey: ["threads", "search"] },
    (oldData) => oldData?.filter((t) => t.thread_id !== threadId)
  );
}
```

### 6.2 缓存 Key 设计

```typescript
// 线程列表缓存
queryKey: ["threads", "search", { limit: 50, sortBy: "updated_at" }]

// 单个线程详情缓存
queryKey: ["thread", threadId]

// 模型列表缓存
queryKey: ["models"]
```

---

## 7. 错误处理与重试

### 7.1 前端错误处理

```typescript
// core/threads/hooks.ts:175
onError(error) {
  setOptimisticMessages([]);  // 清除乐观消息
  toast.error(getStreamErrorMessage(error));  // 显示错误 toast
}
```

### 7.2 重连机制

```typescript
// core/threads/hooks.ts:117
const thread = useStream<AgentThreadState>({
  client: getAPIClient(isMock),
  threadId: onStreamThreadId,
  reconnectOnMount: true,  // 挂载时自动重连
  fetchStateHistory: { limit: 1 },  // 重连后获取最近状态
});
```

---

## 8. 文件上传流程

```
用户选择文件
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ PromptInput 组件                                                 │
│   └─→ onSend({ text: "hello", files: [File1, File2] })          │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ useThreadStream.sendMessage()                                   │
│                                                                 │
│ if (files.length > 0) {                                         │
│   const uploadResponse = await uploadFiles(threadId, files);   │
│   // POST /api/threads/{id}/uploads → Gateway API              │
│ }                                                               │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ Gateway API 处理 (uploads.py)                                    │
│                                                                 │
│ 1. 保存文件到 .deer-flow/threads/{id}/uploads/                 │
│ 2. 返回文件元信息:                                               │
│    { filename, size, virtual_path, mime_type }                  │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│ 发送消息给 LangGraph                                             │
│                                                                 │
│ thread.submit(                                                  │
│   { messages: [{ content: [..., { type: "file", ... }] }] },   │
│   { context: { files: [...] } }                                 │
│ )                                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. 跨服务通信时序图

```
Browser                    Frontend              Nginx              LangGraph         Gateway
  │                          │                    │                    │                │
  │──点击发送消息───────────▶│                    │                    │                │
  │                          │                    │                    │                │
  │                          │──POST threads──────▶│                    │                │
  │                          │                    │──POST threads──────▶│                │
  │                          │                    │                    │                │
  │                          │◀───201 Created─────│                    │                │
  │                          │◀───201 Created─────│                    │                │
  │                          │                    │                    │                │
  │                          │                    │◀──SSE Stream───────│                │
  │                          │◀──SSE Stream───────│                    │                │
  │                          │                    │                    │                │
  │                          │──POST suggestions─────────────────────▶│                │
  │                          │                    │                    │◀──201 OK───────│
  │                          │◀──201 OK────────────────────────────────│                │
  │                          │                    │                    │                │
  │◀──消息显示───────────────│                    │                    │                │
  │                          │                    │                    │                │
```

---

## 10. 实战：从前端到后端的完整追踪

### 场景：用户在 UI 发送 "hello"

| 步骤 | 文件位置 | 关键代码 | 说明 |
|------|---------|---------|------|
| 1 | `components/workspace/chats/chat-box.tsx` | `<PromptInput onSend={...}>` | 用户输入 |
| 2 | `core/threads/hooks.ts:202` | `sendMessage = useCallback(...)` | 发送处理 |
| 3 | `core/threads/hooks.ts:347` | `thread.submit({ messages })` | 提交到 SDK |
| 4 | `core/api/api-client.ts:14` | `client.runs.stream(...)` | SDK 流式调用 |
| 5 | `docker/nginx/nginx.conf` | `proxy_pass http://langgraph` | Nginx 路由 |
| 6 | `backend/langgraph.json` | `"lead_agent": "..."` | 加载 Agent |
| 7 | `packages/harness/deerflow/agents/lead_agent/agent.py` | `make_lead_agent()` | 创建 Agent |
| 8 | LangGraph SDK | `POST /runs/stream` | 实际 HTTP 请求 |
| 9 | Nginx → LangGraph Server | SSE 响应 | 流式数据 |
| 10 | `hooks.ts:onUpdateEvent` | 更新状态 | 前端回调 |
| 11 | `hooks.ts:onFinish` | 刷新缓存 | 触发 suggestions |

---

## 11. 调试技巧

### 11.1 查看网络请求

```bash
# 在浏览器 DevTools 中
# 1. Network 标签
# 2. 过滤器: /api/langgraph/ 或 /api/threads
# 3. 勾选 "Preserve log" 保留请求历史
```

### 11.2 查看 LangGraph SDK 日志

```typescript
// 在 api-client.ts 中启用调试
const client = new LangGraphClient({
  apiUrl: getLangGraphBaseURL(),
  verbose: true,  // 启用详细日志
});
```

### 11.3 直接调用 API

```bash
# 创建 thread
curl -X POST http://localhost:2024/threads

# 发送消息（流式）
curl -X POST http://localhost:2024/threads/{id}/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"assistantId":"lead_agent","input":{"messages":[{"type":"human","content":"hello"}]}}'

# 生成建议
curl -X POST http://localhost:8001/api/threads/{id}/suggestions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}],"n":3}'
```

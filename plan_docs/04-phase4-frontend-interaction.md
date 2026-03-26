# 04 - Phase 4: Frontend 与 Agent 交互

> 预计时间: 3-5 天
> 
> 本阶段目标：理解 DeerFlow 前端如何与后端 Agent 交互，包括 Streaming SSE、Thread 管理、消息处理

---

## 4.1 核心交互流程

### 完整请求流程

```
┌─────────────┐     HTTP/SSE      ┌─────────────────┐
│  Browser    │ ←──────────────→ │  Nginx :2026    │
│  (React)    │                  │                 │
└─────────────┘                  └────────┬────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │                     │                     │
                    ↓                     ↓                     ↓
           ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
           │   Frontend   │     │   Gateway    │     │  LangGraph   │
           │   :3000      │     │   API :8001  │     │  Server:2024 │
           └──────────────┘     └──────────────┘     └──────┬───────┘
                                                            │
                                                            ↓
                                                   ┌──────────────┐
                                                   │  Lead Agent  │
                                                   │   (GLM-4.7)  │
                                                   └──────────────┘
```

### Streaming SSE 流程

```
用户输入 "帮我分析苹果公司"
    ↓
Frontend 发送 POST /api/langgraph/threads/{thread_id}/runs
    ↓
LangGraph Server 返回 SSE 流
    ↓
SSE 事件类型:
    - thread_started
    - checkpoint
    - task_started
    - task_completed
    - checkpoint (中间状态)
    - thread_completed
    ↓
Frontend 解析 SSE 并实时渲染
```

---

## 4.2 核心文件

### 前端核心文件

```
frontend/src/
├── core/
│   ├── api/
│   │   └── api-client.ts          # LangGraph API 封装 ⭐⭐⭐
│   ├── threads/
│   │   ├── hooks.ts               # Thread 管理 + Streaming ⭐⭐⭐
│   │   └── types.ts               # Thread 类型定义
│   └── messages/
│       └── message-list.tsx        # 消息列表渲染
├── components/
│   └── workspace/
│       ├── input-box.tsx           # 消息输入框 ⭐⭐⭐
│       └── messages/
│           └── message-list-item.tsx # 单条消息渲染
└── app/
    └── workspace/
        └── chats/
            └── [thread_id]/
                └── page.tsx        # 主聊天页面
```

---

## 4.3 LangGraph Client SDK

**文件**: `frontend/src/core/api/api-client.ts`

### SDK 封装

```typescript
import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

function createCompatibleClient(isMock?: boolean): LangGraphClient {
  const client = new LangGraphClient({
    apiUrl: getLangGraphBaseURL(isMock),
  });

  // 封装 runs.stream 方法，添加流式处理
  const originalRunStream = client.runs.stream.bind(client.runs);
  client.runs.stream = ((threadId, assistantId, payload) =>
    originalRunStream(
      threadId,
      assistantId,
      sanitizeRunStreamOptions(payload),
    )) as typeof client.runs.stream;

  return client;
}
```

### 使用示例

```typescript
import { getAPIClient } from "@/core/api/api-client";

// 获取客户端
const client = getAPIClient();

// 创建线程
const thread = await client.threads.create({
  metadata: { agent_name: "default" },
});

// 发送消息并获取流
const stream = await client.runs.stream(
  thread.thread_id,
  "assistant",  // assistant ID
  {
    input: { messages: [{ role: "user", content: "Hello!" }] },
    config: {
      configurable: {
        model_name: "glm-4.7",
        thinking_enabled: true,
      },
    },
  }
);

// 遍历 SSE 事件
for await (const event of stream) {
  console.log(event);
}
```

---

## 4.4 Thread 管理

**文件**: `frontend/src/core/threads/hooks.ts`

### Thread 概念

**Thread（线程）** 是 DeerFlow 中的**会话管理单位**，类似于 ChatGPT 的 conversation。每个 Thread 有独立的：
- 消息历史
- 状态（title, artifacts, todos）
- 模型配置

### Thread 状态

```typescript
// frontend/src/core/threads/types.ts

interface AgentThreadState extends Record<string, unknown> {
  title: string;              // 对话标题
  messages: Message[];         // 消息列表
  artifacts: string[];        // 生成的文件
  todos?: Todo[];             // 待办事项
}

interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  agent_name?: string;
  mode?: "flash" | "thinking" | "pro" | "ultra";
}
```

### Thread Hook

```typescript
// frontend/src/core/threads/hooks.ts

export function useThread(threadId: string) {
  // 获取线程数据
  const { data: thread, isLoading } = useQuery({
    queryKey: ["thread", threadId],
    queryFn: () => client.threads.get(threadId),
  });

  // 发送消息
  const sendMessage = async (content: string, context: AgentThreadContext) => {
    const stream = await client.runs.stream(
      threadId,
      "assistant",
      {
        input: { messages: [{ role: "user", content }] },
        config: { configurable: context },
      }
    );

    return stream;
  };

  return { thread, sendMessage, isLoading };
}
```

---

## 4.5 SSE 流式处理

### SSE 事件类型

LangGraph Server 返回的 SSE 事件：

```typescript
// 事件类型
type SSEEvent =
  | { event: "thread_started"; data: { thread_id: string } }
  | { event: "task_started"; data: { task_id: string; name: string } }
  | { event: "task_completed"; data: { task_id: string; result: any } }
  | { event: "checkpoint"; data: AgentThreadState }  // 中间状态
  | { event: "thread_completed"; data: { thread_id: string } }
  | { event: "error"; data: { error: string } };
```

### 流式处理示例

```typescript
async function handleStream(stream: any) {
  for await (const event of stream) {
    switch (event.event) {
      case "thread_started":
        console.log("Thread started:", event.data.thread_id);
        break;

      case "checkpoint":
        // 更新 UI 状态
        setThreadState(event.data);
        break;

      case "task_started":
        console.log("Task started:", event.data.name);
        break;

      case "task_completed":
        console.log("Task completed:", event.data.result);
        break;

      case "thread_completed":
        console.log("Thread completed!");
        break;

      case "error":
        console.error("Error:", event.data.error);
        break;
    }
  }
}
```

---

## 4.6 消息输入框组件

**文件**: `frontend/src/components/workspace/input-box.tsx`

### 组件结构

```typescript
export function InputBox({
  context,           // AgentThreadContext
  onSubmit,          // 提交回调
  threadId,          // 线程 ID
}: {
  context: AgentThreadContext;
  onSubmit: (message: PromptInputMessage) => void;
  threadId: string;
}) {
  // 模式选择
  const supportThinking = selectedModel?.supports_thinking ?? false;

  // 模式切换
  const handleModeSelect = (mode: InputMode) => {
    onContextChange?.({
      ...context,
      mode: getResolvedMode(mode, supportThinking),
    });
  };

  // 提交处理
  const handleSubmit = async (prompt: string) => {
    onSubmit({ role: "user", content: prompt });
  };

  return (
    <div>
      {/* 模式选择下拉菜单 */}
      <ModeSelector
        mode={context.mode}
        onSelect={handleModeSelect}
      />

      {/* 消息输入框 */}
      <PromptInput
        onSubmit={handleSubmit}
      />
    </div>
  );
}
```

### 模式切换

```typescript
// 模式类型
type InputMode = "flash" | "thinking" | "pro" | "ultra";

function getResolvedMode(mode: InputMode, supportsThinking: boolean): InputMode {
  // 如果模型不支持 thinking，只能用 flash
  if (!supportsThinking && mode !== "flash") {
    return "flash";
  }
  return mode;
}
```

---

## 4.7 消息渲染

**文件**: `frontend/src/components/workspace/messages/message-list-item.tsx`

### 消息类型

```typescript
interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  name?: string;           // 模型名称
  artifacts?: any[];       // 生成的内容
  tool_calls?: ToolCall[];  // 工具调用
  tool_call_chat?: any;    // 工具结果
}
```

### 消息渲染逻辑

```typescript
export function MessageListItem({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  return (
    <div className={isUser ? "user-message" : "assistant-message"}>
      {isUser && <UserAvatar />}
      {isAssistant && <AssistantAvatar name={message.name} />}

      <div className="message-content">
        {/* 渲染消息内容 */}
        <Markdown content={message.content} />

        {/* 渲染工具调用 */}
        {message.tool_calls?.map((call) => (
          <ToolCall key={call.id} call={call} />
        ))}

        {/* 渲染 Artifacts */}
        {message.artifacts?.map((artifact) => (
          <Artifact key={artifact.id} artifact={artifact} />
        ))}
      </div>
    </div>
  );
}
```

---

## 4.8 API 路由

### Gateway API 路由

| 路由 | 方法 | 作用 |
|------|------|------|
| `/api/threads` | GET | 获取线程列表 |
| `/api/threads` | POST | 创建新线程 |
| `/api/threads/{id}` | GET | 获取线程详情 |
| `/api/threads/{id}` | DELETE | 删除线程 |
| `/api/models` | GET | 获取可用模型 |
| `/api/skills` | GET | 获取可用 Skills |
| `/api/uploads` | POST | 上传文件 |
| `/api/mcp` | GET | MCP 服务器配置 |

### LangGraph API 路由

| 路由 | 方法 | 作用 |
|------|------|------|
| `/api/langgraph/threads` | POST | 创建线程 |
| `/api/langgraph/threads/{id}/runs` | POST | 发送消息 |
| `/api/langgraph/threads/{id}/runs/stream` | GET | SSE 流 |

---

## 4.9 状态管理

### TanStack Query 使用

```typescript
// 获取线程列表
const { data: threads } = useQuery({
  queryKey: ["threads"],
  queryFn: () => client.threads.list(),
});

// 创建新线程
const { mutate: createThread } = useMutation({
  mutationFn: (metadata: any) => client.threads.create({ metadata }),
  onSuccess: (thread) => {
    // 跳转到新线程
    router.push(`/workspace/chats/${thread.thread_id}`);
  },
});

// 发送消息
const { mutate: sendMessage } = useMutation({
  mutationFn: (params: { threadId: string; input: any }) =>
    client.runs.stream(params.threadId, "assistant", params.input),
  onSuccess: (stream) => {
    handleStream(stream);
  },
});
```

---

## 4.10 实践任务

### 任务 1: 追踪消息流程

在浏览器 DevTools 中查看 Network 请求，追踪从发送消息到收到响应的完整请求流程。

### 任务 2: 添加自定义日志

在 `api-client.ts` 中添加日志，记录所有 SSE 事件，理解每个事件的含义。

### 任务 3: 修改消息渲染

尝试修改消息渲染样式，观察前端变化。

---

## 4.11 学习目标检查清单

- [ ] 理解 SSE 流式传输原理
- [ ] 理解 Thread 和 Message 的关系
- [ ] 理解 LangGraph SDK 的使用方式
- [ ] 理解消息的渲染流程
- [ ] 理解模式切换（flash/pro/ultra）的状态管理

---

## 4.12 下一步

**[05-Phase 5: Sandbox 执行和安全机制](./05-phase5-sandbox.md)**

学习 DeerFlow 的 Sandbox 执行系统，了解代码如何安全隔离执行。

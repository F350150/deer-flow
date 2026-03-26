# 详解前端架构

> 深入解析 DeerFlow 前端项目的架构设计、技术栈和核心模块

---

## 1. 技术栈概览

| 类别 | 技术 | 版本 | 作用 |
|------|------|------|------|
| **框架** | Next.js | 16.x | React 全栈框架 |
| **UI 库** | React | 19.x | 组件化 UI |
| **类型** | TypeScript | 5.8.x | 类型安全 |
| **样式** | Tailwind CSS | 4.x | 原子化 CSS |
| **状态管理** | TanStack Query | 5.x | 服务端状态管理 |
| **Agent SDK** | @langchain/langgraph-sdk | 1.5.x | 与 LangGraph Server 通信 |
| **AI UI** | Vercel AI SDK | 6.x | AI 元素渲染 |
| **状态库** | Zustand / React Context | - | 客户端状态 |
| **包管理** | pnpm | 10.26.x | 依赖管理 |
| **代码规范** | ESLint + Prettier | - | 代码质量 |

---

## 2. 项目结构

```
frontend/src/
├── app/                        # Next.js App Router（页面路由）
│   ├── page.tsx                 # 落地页 /
│   ├── layout.tsx               # 根布局
│   ├── workspace/              # 工作区（主要功能）
│   │   └── chats/[thread_id]/
│   │       └── page.tsx        # 聊天页面 /workspace/chats/{thread_id}
│   └── mock/                   # Mock 数据（开发/测试用）
│
├── components/                 # React 组件
│   ├── ui/                     # Shadcn UI 基础组件（自动生成）
│   ├── ai-elements/             # Vercel AI SDK 元素（自动生成）
│   ├── workspace/              # 工作区组件
│   │   ├── messages/           # 消息相关
│   │   ├── artifacts/          # 文件/产物相关
│   │   ├── settings/           # 设置页面
│   │   └── chats/              # 聊天相关
│   └── landing/                # 落地页组件
│
├── core/                       # 核心业务逻辑（重点！）
│   ├── api/                    # API 客户端
│   ├── threads/                # Thread 管理（状态 + Hooks）
│   ├── messages/               # 消息处理
│   ├── artifacts/              # 文件产物管理
│   ├── skills/                 # Skills 系统
│   ├── models/                 # 模型配置
│   ├── memory/                 # 记忆系统
│   ├── uploads/                # 文件上传
│   ├── config/                 # 配置
│   └── i18n/                   # 国际化
│
├── hooks/                      # 共享 React Hooks
├── lib/                        # 工具函数
├── styles/                     # 全局样式
└── server/                     # 服务端代码（better-auth）
```

---

## 3. 核心模块详解

### 3.1 API 层 (`core/api/`)

#### API Client 初始化

```typescript
// core/api/api-client.ts
import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

function createCompatibleClient(isMock?: boolean): LangGraphClient {
  const client = new LangGraphClient({
    apiUrl: getLangGraphBaseURL(isMock),  // http://localhost:2026/api/langgraph
  });

  // 包装 runs.stream 方法，添加流式处理逻辑
  const originalRunStream = client.runs.stream.bind(client.runs);
  client.runs.stream = ((threadId, assistantId, payload) =>
    originalRunStream(threadId, assistantId, sanitizeRunStreamOptions(payload))
  ) as typeof client.runs.stream;

  return client;
}

let _singleton: LangGraphClient | null = null;
export function getAPIClient(isMock?: boolean): LangGraphClient {
  _singleton ??= createCompatibleClient(isMock);
  return _singleton;
}
```

**关键点**：
- 使用**单例模式**，全局只有一个 client 实例
- `apiUrl` 指向 **Nginx**（由 Nginx 转发到 LangGraph Server）
- 包装 `runs.stream` 方法用于流式数据处理

#### URL 配置

```typescript
// core/config/index.ts
export function getLangGraphBaseURL(isMock?: boolean) {
  if (env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    return new URL(env.NEXT_PUBLIC_LANGGRAPH_BASE_URL, window.location.origin).toString();
  } else if (isMock) {
    return `${window.location.origin}/mock/api`;
  } else {
    return `${window.location.origin}/api/langgraph`;  // Nginx 代理
  }
}
```

### 3.2 Thread 管理 (`core/threads/`)

#### Hooks 架构

```
hooks.ts
├── useThreadStream()     - 核心：发送消息 + 流式接收
├── useThreads()           - 获取 thread 列表
├── useDeleteThread()      - 删除 thread
└── useRenameThread()      - 重命名 thread
```

#### 核心 Hook: useThreadStream

```typescript
// core/threads/hooks.ts:58
export function useThreadStream({
  threadId,
  context,
  isMock,
  onStart,
  onFinish,
  onToolEnd,
}: ThreadStreamOptions) {
  const [onStreamThreadId, setOnStreamThreadId] = useState(() => threadId);
  const threadIdRef = useRef<string | null>(threadId ?? null);

  // 使用 @langchain/langgraph-sdk 的 useStream
  const thread = useStream<AgentThreadState>({
    client: getAPIClient(isMock),
    assistantId: "lead_agent",
    threadId: onStreamThreadId,
    reconnectOnMount: true,
    fetchStateHistory: { limit: 1 },
    onCreated(meta) {
      handleStreamStart(meta.thread_id);  // thread 创建时回调
      setOnStreamThreadId(meta.thread_id);
    },
    onLangChainEvent(event) {
      if (event.event === "on_tool_end") {
        listeners.current.onToolEnd?.({ name: event.name, data: event.data });
      }
    },
    onUpdateEvent(data) {
      // 流式更新时回调
    },
    onFinish(state) {
      listeners.current.onFinish?.(state.values);
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });

  // 发送消息
  const sendMessage = useCallback(async (threadId, message, extraContext) => {
    // 1. 文件上传
    // 2. thread.submit() 发送消息
    await thread.submit(
      { messages: [...] },
      { config: {...}, context: {...} }
    );
  }, [thread, ...]);

  return [mergedThread, sendMessage, isUploading] as const;
}
```

#### 类型定义

```typescript
// core/threads/types.ts
import type { Message, Thread } from "@langchain/langgraph-sdk";

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
}

export interface AgentThread extends Thread<AgentThreadState> {}

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
}
```

### 3.3 TanStack Query 状态管理

#### 服务端状态 vs 客户端状态

| 类型 | 工具 | 示例 |
|------|------|------|
| **服务端状态** | TanStack Query | threads 列表、消息历史 |
| **客户端状态** | useState / Context | UI 状态、主题、语言 |
| **持久化状态** | localStorage | 用户设置 |

#### useQuery 示例

```typescript
// core/threads/hooks.ts:413
export function useThreads(params) {
  const apiClient = getAPIClient();
  
  return useQuery<AgentThread[]>({
    queryKey: ["threads", "search", params],  // 缓存 key
    queryFn: async () => {
      // 分页获取 threads
      const response = await apiClient.threads.search<AgentThreadState>(params);
      return response as AgentThread[];
    },
    refetchOnWindowFocus: false,  // 失焦不自动刷新
  });
}
```

#### useMutation 示例

```typescript
// core/threads/hooks.ts:479
export function useDeleteThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  
  return useMutation({
    mutationFn: async ({ threadId }: { threadId: string }) => {
      // 1. 删除 LangGraph thread
      await apiClient.threads.delete(threadId);
      // 2. 删除本地数据
      await fetch(`${getBackendBaseURL()}/api/threads/${threadId}`, {
        method: "DELETE",
      });
    },
    onSuccess(_, { threadId }) {
      // 乐观更新：直接修改缓存
      queryClient.setQueriesData(
        { queryKey: ["threads", "search"] },
        (oldData) => oldData?.filter((t) => t.thread_id !== threadId)
      );
    },
    onSettled() {
      // 重新获取最新数据
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });
}
```

---

## 4. Next.js App Router 架构

### 4.1 Server Components vs Client Components

```
Server Components (默认)
├── 在服务端渲染
├── 支持 async/await
├── 不能用 useState, useEffect
├── 适合数据获取、布局
│
└── Client Components ("use client")
    ├── 在客户端渲染
    ├── 可以用所有 React API
    ├── 适合交互组件
    └── 父组件可以是 Server Component
```

### 4.2 路由结构

```typescript
// app/workspace/chats/[thread_id]/page.tsx
// 动态路由 [thread_id]

import { ThreadPage } from "./thread-page";

export default function Page({ params }: { params: Promise<{ thread_id: string }> }) {
  return <ThreadPage params={params} />;
}
```

### 4.3 布局系统

```typescript
// app/layout.tsx - 根布局
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>  // TanStack Query Provider
      </body>
    </html>
  );
}
```

---

## 5. 组件架构

### 5.1 组件分类

```
components/
├── ui/                    # Shadcn UI（基础组件库）
│   ├── button.tsx
│   ├── dialog.tsx
│   └── ...
│
├── ai-elements/           # Vercel AI SDK（AI 特定组件）
│   ├── message.tsx        # 消息气泡
│   ├── artifact.tsx       # 文件展示
│   ├── suggestion.tsx     # 建议问题
│   └── ...
│
├── workspace/             # 业务组件
│   ├── messages/
│   │   ├── message-list.tsx    # 消息列表
│   │   └── message-list-item.tsx # 单条消息
│   ├── artifacts/
│   │   └── artifact-file-list.tsx
│   ├── settings/
│   │   ├── settings-dialog.tsx
│   │   └── ...
│   └── chats/
│       └── chat-box.tsx
│
└── landing/               # 落地页组件
```

### 5.2 Chat 组件结构

```typescript
// components/workspace/chats/chat-box.tsx
"use client";

export function ChatBox() {
  const [thread, sendMessage, isUploading] = useThreadStream({
    threadId: currentThreadId,
    context: settings,
    onStart: (id) => { ... },
    onFinish: (state) => { ... },
  });

  return (
    <div className="flex flex-col h-full">
      <MessageList messages={thread.messages} />
      <PromptInput
        onSend={(message) => sendMessage(threadId, message)}
        disabled={isUploading}
      />
    </div>
  );
}
```

---

## 6. 样式系统

### 6.1 Tailwind CSS 4

```typescript
// 使用 cn() 合并类名
import { cn } from "@/lib/utils";

<div className={cn(
  "p-4 rounded-lg",           // 基础样式
  isActive && "bg-blue-100",  // 条件样式
  className                   // 自定义覆盖
)} />
```

### 6.2 CSS 变量主题

```typescript
// styles/globals.css
@import "tailwindcss";

:root {
  --background: #ffffff;
  --foreground: #000000;
}

.dark {
  --background: #0a0a0a;
  --foreground: #ededed;
}
```

---

## 7. 国际化 (i18n)

```typescript
// core/i18n/hooks.ts
export function useI18n() {
  const locale = useLocale();  // 获取当前语言
  return {
    t: (key: string) => translations[locale][key],  // 翻译函数
  };
}

// 使用
const { t } = useI18n();
return <button>{t("common.submit")}</button>;
```

翻译文件位于 `core/i18n/locales/`，支持 en-US 和 zh-CN。

---

## 8. 环境变量

```typescript
// env.js
import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  client: {
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: z.string().url().optional(),
    NEXT_PUBLIC_BACKEND_BASE_URL: z.string().url().optional(),
  },
  // ...
});
```

使用：

```bash
# .env.local
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://localhost:2026/api/langgraph
NEXT_PUBLIC_BACKEND_BASE_URL=http://localhost:8001
```

---

## 9. 核心数据流

```
用户输入 "hello"
        │
        ▼
┌─────────────────────────┐
│ PromptInput 组件         │
│ (components/ai-elements) │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ sendMessage()           │
│ (core/threads/hooks.ts) │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ thread.submit()         │
│ → client.runs.stream()  │
│ (core/api/api-client.ts)│
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ LangGraph Server        │
│ (POST /runs/stream)     │
└───────────┬─────────────┘
            │
            ▼ (SSE Stream)
┌─────────────────────────┐
│ onUpdateEvent() 回调    │
│ 更新 thread.messages    │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ TanStack Query 缓存更新  │
│ 触发组件重新渲染         │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ MessageList 组件渲染     │
└─────────────────────────┘
```

---

## 10. 关键文件索引

| 功能 | 文件路径 |
|------|---------|
| API Client 单例 | `core/api/api-client.ts` |
| Thread Stream Hook | `core/threads/hooks.ts` |
| Thread 类型定义 | `core/threads/types.ts` |
| URL 配置 | `core/config/index.ts` |
| Chat 组件 | `components/workspace/chats/chat-box.tsx` |
| 消息列表 | `components/workspace/messages/message-list.tsx` |
| 全局布局 | `app/layout.tsx` |
| 聊天页面 | `app/workspace/chats/[thread_id]/page.tsx` |
| 国际化 | `core/i18n/hooks.ts` |
| 环境变量 | `env.js` |

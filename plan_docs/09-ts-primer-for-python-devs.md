# 带我入门 TypeScript

> 本文档专为有 Python 后端开发经验的同学设计，帮助快速理解 TypeScript 在 DeerFlow 前端项目中的核心用法

---

## 1. TypeScript vs Python 基础对比

| 概念 | Python | TypeScript |
|------|--------|------------|
| 类型声明 | 动态类型（可选 type hints） | `let x: string = "hello"` |
| 接口 | `class` 或 `Protocol` | `interface` 或 `type` |
| 空值 | `None` | `null` / `undefined` |
| 泛型 | `List[T]`, `Dict[K, V]` | `Array<T>`, `Map<K, V>` |
| 可选参数 | `def f(x=None)` | `f(x?: string)` 或 `f(x: string \| undefined)` |
| 类型导入 | `from typing import List` | `import { type List }` 或 `import type { List }` |

---

## 2. 核心类型语法

### 2.1 基本类型注解

```typescript
// 字符串
let name: string = "DeerFlow";

// 数字
let count: number = 42;

// 布尔
let enabled: boolean = true;

// 数组
let names: string[] = ["Alice", "Bob"];
let scores: Array<number> = [1, 2, 3];  // 泛型语法

// 对象
let user: { name: string; age: number } = { name: "Alice", age: 25 };
```

### 2.2 接口（Interface）

```typescript
// 定义接口（类似 Python 的 dataclass 或 Pydantic Model）
interface User {
  name: string;
  age: number;
  email?: string;  // 可选字段（类似 Optional[str]）
}

// 使用
const user: User = { name: "Alice", age: 25 };
```

### 2.3 类型别名（Type Alias）

```typescript
// 类似 Python 的 TypeAlias 或 typing.NewType
type UserId = string;
type Config = Record<string, unknown>;  // 类似 Dict[str, Any]

// 联合类型（类似 Union）
type Result = Success | Error;
type StringOrNumber = string | number;
```

### 2.4 泛型（Generics）

```typescript
// 类似 Python 的泛型 T
function identity<T>(arg: T): T {
  return arg;
}

// 带约束的泛型
function getProperty<T, K extends keyof T>(obj: T, key: K): T[K] {
  return obj[key];
}

// 使用
const name = getProperty({ name: "Alice", age: 25 }, "name");  // string
```

### 2.5 函数类型

```typescript
// 普通函数
function add(a: number, b: number): number {
  return a + b;
}

// 箭头函数
const add = (a: number, b: number): number => a + b;

// 可选参数
function greet(name: string, greeting?: string): string {
  return greeting ? `${greeting}, ${name}!` : `Hello, ${name}!`;
}

// 默认参数
function greet(name: string, greeting: string = "Hello"): string {
  return `${greeting}, ${name}!`;
}

// rest 参数
function sum(...numbers: number[]): number {
  return numbers.reduce((a, b) => a + b, 0);
}
```

---

## 3. React/Next.js 中的 TypeScript

### 3.1 React 组件

```typescript
// 函数式组件（类似 Python 的 Flask/Jinja2 模板或 FastAPI 的 HTMLResponse）
import React from "react";

// Props 接口（类似 Flask 的 template context）
interface ButtonProps {
  label: string;
  onClick: () => void;  // 回调函数类型
  disabled?: boolean;
}

// 组件定义
export function Button({ label, onClick, disabled = false }: ButtonProps) {
  return (
    <button onClick={onClick} disabled={disabled}>
      {label}
    </button>
  );
}
```

### 3.2 Hook 类型

```typescript
// useState 泛型（类似 Python 的 State 类型注解）
const [count, setCount] = useState<number>(0);

// useRef（类似 Python 的 mutable 变量引用）
const timerRef = useRef<NodeJS.Timeout | null>(null);

// useCallback（类似 Python 的 @lru_cache，缓存函数）
const handleClick = useCallback(() => {
  console.log("Clicked!");
}, []);  // 依赖数组，类似 use_effect 的 deps
```

### 3.3 泛型 Hook 示例

```typescript
// 自定义泛型 Hook
function useLocalStorage<T>(key: string, initialValue: T) {
  const [storedValue, setStoredValue] = useState<T>(() => {
    if (typeof window === "undefined") return initialValue;
    const item = window.localStorage.getItem(key);
    return item ? JSON.parse(item) : initialValue;
  });

  const setValue = (value: T | ((val: T) => T)) => {
    // ...
  };

  return [storedValue, setValue] as const;
}

// 使用
const [name, setName] = useLocalStorage<string>("name", "Alice");
```

---

## 4. Next.js App Router 特定语法

### 4.1 Server Components vs Client Components

```typescript
// 默认是 Server Component（服务端组件）
// 文件顶部的 "use client" 声明使其成为 Client Component

// app/page.tsx - Server Component（默认）
export default function HomePage() {
  return <h1>Welcome!</h1>;
}

// components/Button.tsx - Client Component
"use client";  // 必须声明

import { useState } from "react";

export function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>;
}
```

### 4.2 async/await 在 Server Components 中

```typescript
// app/users/page.tsx - Server Component 支持 async/await
// 类似 Python 的 FastAPI 路由处理器
import { db } from "@/lib/db";

export default async function UsersPage() {
  // 直接 await 数据库查询（类似 FastAPI 的依赖注入）
  const users = await db.getUsers();

  return (
    <ul>
      {users.map((user) => (
        <li key={user.id}>{user.name}</li>  // 必须加 key
      ))}
    </ul>
  );
}
```

---

## 5. 常用的 TypeScript 模式

### 5.1 条件类型

```typescript
// 提取函数返回类型
type Result = Awaited<Promise<string>>;  // string

// 提取 Props 类型
type ButtonProps = React.ComponentProps<typeof Button>;
```

### 5.2 Record 和 Map

```typescript
// Record（类似 Dict）
const users: Record<string, User> = {
  "alice": { name: "Alice", age: 25 },
  "bob": { name: "Bob", age: 30 },
};

// Map
const userMap = new Map<string, User>();
userMap.set("alice", { name: "Alice", age: 25 });
```

### 5.3 模块导入

```typescript
// 默认导入
import React from "react";

// 命名导入（类似 Python 的 from x import y）
import { useState, useEffect } from "react";

// 类型导入（编译时移除，不影响运行时）
import type { User } from "./types";
import { type User, userToString } from "./types";  // 混合

// 重命名导入
import { useState as useStateReact } from "react";

// 路径别名 @/ 指向 src/
import { getAPIClient } from "@/core/api";
```

---

## 6. DeerFlow 项目中的常见类型模式

### 6.1 API 响应类型

```typescript
// 来自 @langchain/langgraph-sdk 的类型
import type { Message, Thread } from "@langchain/langgraph-sdk";

// 自定义类型继承
export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  todos?: Todo[];
}

export interface AgentThread extends Thread<AgentThreadState> {}
```

### 6.2 Pydantic 模型对应的 TS 类型

```typescript
// Python: class SuggestionsRequest(BaseModel)
//                  messages: list[SuggestionMessage]
//                  n: int = 3

// TypeScript:
interface SuggestionMessage {
  role: string;
  content: string;
}

interface SuggestionsRequest {
  messages: SuggestionMessage[];
  n: number;
}
```

### 6.3 React Query 的类型

```typescript
// useQuery 返回类型
const { data, isLoading, error } = useQuery({
  queryKey: ["threads", "search"],
  queryFn: async () => {
    const response = await apiClient.threads.search();
    return response;
  },
});

// data 类型自动推断
// isLoading 和 error 是 boolean
```

---

## 7. 类型守卫和类型收窄

```typescript
// 类型守卫函数（类似 Python 的 isinstance）
function isString(value: unknown): value is string {
  return typeof value === "string";
}

// 使用
function process(value: unknown) {
  if (isString(value)) {
    // 这里是 string 类型
    console.log(value.toUpperCase());
  }
}

// 可null类型检查
function greet(name: string | null | undefined) {
  if (name != null) {
    // 这里是 string（排除 null 和 undefined）
    console.log(`Hello, ${name}!`);
  }
}
```

---

## 8. 快速对照表

| Python 写法 | TypeScript 写法 |
|------------|----------------|
| `x: int = 5` | `let x: number = 5;` |
| `def f(x: str) -> int` | `function f(x: string): number` |
| `Optional[str]` | `string \| undefined` |
| `Union[A, B]` | `A \| B` |
| `List[int]` | `number[]` 或 `Array<number>` |
| `Dict[str, Any]` | `Record<string, unknown>` |
| `class Foo:` | `class Foo {}` 或 `interface Foo {}` |
| `@dataclass` | `interface` 或 `type` |
| `*args, **kwargs` | `...args: any[]`, `...kwargs: Record<string, any>` |
| `isinstance(x, str)` | `typeof x === "string"` 或 `x is string` |
| `None` | `null` 或 `undefined` |

---

## 9. 推荐的 TS 资源

- [TypeScript 官方文档](https://www.typescriptlang.org/docs/)
- [TypeScript Deep Dive（免费电子书）](https://basarat.gitbook.io/typescript/)
- [React TypeScript Cheatsheet](https://react-typescript-cheatsheet.netlify.app/)

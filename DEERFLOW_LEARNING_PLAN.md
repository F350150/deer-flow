# DeerFlow Agent 学习计划

## 项目概述

**DeerFlow** 是字节跳动开源的**全能型 Agent 框架**，基于 LangGraph + LangChain 构建，版本 2.0 完全重写。它通过编排 sub-agents、memory 和 sandboxes 来完成复杂任务。

**核心技术栈**：
- **后端**: Python 3.12+, LangGraph, LangChain, FastAPI
- **前端**: Next.js 16, React 19, TypeScript, TanStack Query
- **架构**: 微服务 + Nginx 反向代理

---

## 学习阶段总览

| 阶段 | 预计时间 | 目标 |
|------|----------|------|
| Phase 1 | 3-5 天 | 掌握项目整体架构和核心概念 |
| Phase 2 | 5-7 天 | 深入学习 Agent 核心实现 |
| Phase 3 | 5-7 天 | 掌握 Skills 系统和工具集成 |
| Phase 4 | 3-5 天 | 学习 Frontend 与 Agent 的交互 |
| Phase 5 | 5-7 天 | 掌握 Sandbox 执行和安全机制 |
| Phase 6 | 3-5 天 | 进阶主题：Memory、MCP、Channels |

---

## Phase 1: 项目整体架构

### 1.1 必读文档 (建议 3-5 天)

**先读这些文档来建立全局观**：

1. `README.md` - 项目整体介绍
2. `backend/CLAUDE.md` - 后端架构详解 (523 行)
3. `frontend/CLAUDE.md` - 前端架构
4. `Install.md` - 安装指南

### 1.2 核心架构理解

```
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (Port 2026)                        │
│              统一反向代理入口                                │
│  /api/langgraph/*  →  LangGraph Server (2024)              │
│  /api/*            →  Gateway API (8001)                   │
│  /*                →  Frontend (3000)                       │
└─────────────────────────────────────────────────────────────┘
```

**三个核心服务**：
1. **LangGraph Server (2024)** - Agent 运行时，负责 Agent 执行
2. **Gateway API (8001)** - FastAPI REST API，负责模型配置、MCP、文件上传等
3. **Frontend (3000)** - Next.js 前端，用户交互界面

### 1.3 学习目标

- [ ] 理解三服务架构及通信方式
- [ ] 理解 Nginx 如何做路由分发
- [ ] 能够本地启动完整项目 `make dev`
- [ ] 理解 deer-flow 是如何基于 LangGraph 构建的

### 1.4 实践任务

```bash
# 1. 克隆并启动项目
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
make dev

# 2. 访问 http://localhost:2026 体验完整功能
# 3. 尝试发送一个简单问题，观察 Agent 如何响应
```

---

## Phase 2: Agent 核心实现

### 2.1 核心文件位置

```
backend/packages/harness/deerflow/agents/
├── lead_agent/           # 主 Agent 工厂
│   └── agent.py          # make_lead_agent() - 核心！
├── middlewares/          # 13 个中间件
│   ├── thread_data.py
│   ├── sandbox.py
│   ├── memory.py
│   └── ...
├── thread_state.py       # ThreadState 数据结构
└── subagents/            # SubAgent 委托系统
```

### 2.2 学习路径

#### Step 1: 理解 ThreadState (2 天)

**文件**: `backend/packages/harness/deerflow/agents/thread_state.py`

```python
# 核心数据结构，所有 Agent 状态都存储在这里
class ThreadState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    thread_id: str
    user_id: str
    sandbox_type: str  # local | docker | kubernetes
    # ... 更多字段
```

**重点理解**：
- `add_messages` reducer 如何实现消息追加
- custom reducers 的使用场景
- ThreadState 如何在整个 Middleware Chain 中传递

#### Step 2: 理解 Lead Agent (3 天)

**文件**: `backend/packages/harness/deerflow/agents/lead_agent/agent.py`

```python
def make_lead_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool | ToolNode],
    interrupt_before: Sequence[str] | None = None,
    interrupt_after: Sequence[str] | None = None,
    checkpoint_ns: str = "",
):
    # 这是一个 LangGraph StateGraph
    # 定义节点、边、中间件
}
```

**重点理解**：
- LangGraph StateGraph 的构建方式
- 如何将 tools 绑定到 Agent
- interrupt_before/after 的作用（human-in-the-loop）
- Middleware Chain 如何嵌入 Agent 执行流程

#### Step 3: Middleware Chain (3 天)

**文件**: `backend/packages/harness/deerflow/agents/middlewares/`

13 个中间件的处理顺序和职责：

| Middleware | 作用 |
|------------|------|
| thread_data | 线程数据处理 |
| uploads | 文件上传处理 |
| sandbox | 沙箱执行环境切换 |
| summarization | 长对话自动摘要 |
| todo | TodoList 管理 |
| title | 生成对话标题 |
| memory | 记忆提取和存储 |
| view_image | 图片查看处理 |
| clarification | 澄清问题处理 |

**重点理解**：
- Middleware 的注册和执行顺序
- 如何在 Middleware 中修改 ThreadState
- Middleware 之间的数据流如何传递

### 2.3 实践任务

- [ ] 绘制 Agent 执行流程图
- [ ] 理解一个 Middleware 的完整实现
- [ ] 尝试修改某个 Middleware 的行为

---

## Phase 3: Skills 系统

### 3.1 Skills 架构

```
skills/
└── public/                    # 内置 Skills (19个)
    ├── deep-research/        # 深度研究
    ├── report-generation/    # 报告生成
    ├── slide-creation/       # PPT 制作
    ├── web-page/             # 网页生成
    ├── image-generation/     # 图片生成
    ├── video-generation/     # 视频生成
    ├── data-analysis/        # 数据分析
    ├── chart-visualization/  # 图表可视化
    └── ...
```

### 3.2 Skill 文件结构

每个 Skill 包含：
- `SKILL.md` - Skill 定义文件
- `prompt.*.md` - 各阶段 prompt
- `scripts/` - 执行脚本
- `requirements/` - 依赖配置

### 3.3 学习路径

1. **理解 Skill 定义** - 读 `skills/public/deep-research/SKILL.md`
2. **理解 Skill 加载机制** - 看 `backend/packages/harness/deerflow/skills/`
3. **理解 Skill 如何被 Agent 调用** - 看 `deerflow/agents/lead_agent/prompt.py`

### 3.4 实践任务

- [ ] 阅读 3 个以上 Skills 的实现
- [ ] 创建自己的自定义 Skill
- [ ] 理解 Skill 与 Agent Tool 的区别

---

## Phase 4: Frontend 与 Agent 交互

### 4.1 核心交互流程

```
User Input → Frontend → LangGraph Server (SSE) → Agent 执行 → Streaming 响应 → Frontend 渲染
```

### 4.2 核心文件

| 文件 | 作用 |
|------|------|
| `frontend/src/core/api/api-client.ts` | LangGraph API 封装 |
| `frontend/src/core/threads/hooks.ts` | Thread 管理 + Streaming |
| `frontend/src/components/workspace/input-box.tsx` | 消息输入框 |

### 4.3 学习路径

1. **理解 Streaming** - SSE (Server-Sent Events) 在 Agent 中的应用
2. **理解 Thread 概念** - 多轮对话如何管理
3. **理解 Message 处理** - AI 消息如何渲染

### 4.4 实践任务

- [ ] 实现一个简单的 Agent 调用
- [ ] 理解 Streaming 响应的解析
- [ ] 修改前端组件样式

---

## Phase 5: Sandbox 执行

### 5.1 Sandbox 架构

```
deerflow/sandbox/
├── base.py              # 基础 Sandbox 类
├── local.py             # 本地执行
├── docker.py            # Docker 容器执行
└── kubernetes.py         # K8s 集群执行
```

### 5.2 虚拟路径映射

```
/mnt/user-data/workspace/{thread_id}   # 工作目录
/mnt/user-data/uploads/{thread_id}    # 上传文件
/mnt/user-data/outputs/{thread_id}    # 输出文件
```

### 5.3 内置工具

| Tool | 作用 |
|------|------|
| bash | 执行 Bash 命令 |
| ls | 列出目录 |
| read_file | 读取文件 |
| write_file | 写入文件 |
| str_replace | 编辑文件 |

### 5.4 实践任务

- [ ] 理解 Local Sandbox 和 Docker Sandbox 的区别
- [ ] 尝试在对话中让 Agent 执行代码
- [ ] 理解安全隔离机制

---

## Phase 6: 进阶主题

### 6.1 Memory System

**位置**: `backend/packages/harness/deerflow/agents/memory/`

- 自动从对话中提取关键信息
- 跨会话持久化
- 降低 LLM 调用频率

### 6.2 MCP (Model Context Protocol)

**位置**: `backend/packages/harness/deerflow/mcp/`

- 支持第三方工具服务器
- OAuth 认证
- 工具缓存

### 6.3 IM Channels

**位置**: `backend/app/channels/`

- Telegram Bot
- Slack Bot
- Feishu/Lark Bot

---

## Phase 7: 实战项目 + 简历准备

### 7.1 推荐实战项目

#### 项目 1: 自定义 Skill 开发
开发一个特定领域的 Research Skill，体现对 Skills 系统的理解。

#### 项目 2: 自定义 Middleware
实现一个日志记录或性能监控的 Middleware。

#### 项目 3: 自定义 Tool
基于 MCP 协议集成一个外部工具。

### 7.2 简历撰写建议

**DeerFlow 项目描述模板**：

> **DeerFlow Agent 框架贡献者/学习者**
>
> - 基于 LangGraph + LangChain 构建的字节跳动开源 Agent 框架学习
> - 深入研究了 Multi-Agent 架构设计，包括 Lead Agent、SubAgent 协作机制
> - 掌握 Middleware Chain 设计模式，实现了 13 个中间件的协调调度
> - 理解 Skill 系统架构，能够自定义开发 Agent Skills
> - 熟悉 Sandbox 安全执行机制，了解 Local/Docker/Kubernetes 三种执行环境
> - 学习并实践了 Memory System、MCP 协议等高级特性
>
> **技术栈**: Python, LangGraph, LangChain, FastAPI, Next.js, TypeScript, Docker

### 7.3 面试准备

**高频问题**：

1. **LangGraph 的优势是什么？相比 LangChain Agent**
   - 图结构更清晰，便于可视化
   - 支持 Checkpointing（状态保存/恢复）
   - 支持 Interrupt（human-in-the-loop）
   - 更细粒度的控制流

2. **DeerFlow 的 Middleware Chain 如何工作？**
   - 参考 Phase 2 的 Middleware 机制

3. **Sandbox 安全隔离如何实现？**
   - 参考 Phase 5 的 Sandbox 架构

4. **如何设计一个自定义 Skill？**
   - 参考 Phase 3 的 Skill 格式

---

## 推荐学习顺序

```
Week 1: 环境搭建 + 整体架构理解
  ↓
Week 2-3: Agent 核心实现 (Phase 2)
  ↓
Week 4: Skills 系统 (Phase 3)
  ↓
Week 5: Frontend 交互 (Phase 4)
  ↓
Week 6: Sandbox 和安全机制 (Phase 5)
  ↓
Week 7-8: 进阶主题 + 实战项目 (Phase 6-7)
```

---

## 学习资源

1. **官方文档**
   - LangGraph 文档: https://langchain-ai.github.io/langgraph/
   - LangChain 文档: https://python.langchain.com/

2. **DeerFlow 相关**
   - 项目 GitHub: https://github.com/bytedance/deer-flow
   - `backend/docs/ARCHITECTURE.md` - 详细架构文档

3. **推荐阅读源码顺序**
   1. `backend/packages/harness/deerflow/agents/thread_state.py`
   2. `backend/packages/harness/deerflow/agents/lead_agent/agent.py`
   3. `backend/packages/harness/deerflow/agents/middlewares/sandbox.py`
   4. `backend/packages/harness/deerflow/tools/builtins/`
   5. `frontend/src/core/threads/hooks.ts`

---

## 关键文件索引

| 分类 | 文件路径 | 重要性 |
|------|----------|--------|
| 主 Agent | `packages/harness/deerflow/agents/lead_agent/agent.py` | ⭐⭐⭐⭐⭐ |
| 状态管理 | `packages/harness/deerflow/agents/thread_state.py` | ⭐⭐⭐⭐⭐ |
| Sandbox | `packages/harness/deerflow/sandbox/*.py` | ⭐⭐⭐⭐ |
| Middleware | `packages/harness/deerflow/agents/middlewares/*.py` | ⭐⭐⭐⭐ |
| Skills | `packages/harness/deerflow/skills/*.py` | ⭐⭐⭐⭐ |
| 配置 | `packages/harness/deerflow/config/*.py` | ⭐⭐⭐ |
| 前端 API | `frontend/src/core/api/api-client.ts` | ⭐⭐⭐⭐ |
| 前端 Thread | `frontend/src/core/threads/hooks.ts` | ⭐⭐⭐⭐ |

---

*Last Updated: 2026-03-26*
*Generated for DeerFlow Learning*

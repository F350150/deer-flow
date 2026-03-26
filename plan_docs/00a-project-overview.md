# 00 - 项目概述

## 1.1 DeerFlow 是什么

**DeerFlow (Deep Exploration and Efficient Research Flow)** 是字节跳动开源的超级 Agent 框架，基于 LangGraph 和 LangChain 构建。它的核心目标是**通过编排多个子 Agent、记忆系统和沙箱执行环境来完成复杂任务**。

### 版本说明
- **Version 2.0** 是完全重写的新版本，与 v1 没有共享代码
- 如果你在学习或贡献代码，请确保使用的是 v2 版本

### 与传统 LangChain Agent 的区别

| 特性 | 传统 LangChain Agent | DeerFlow |
|------|---------------------|----------|
| 架构 | 单 Agent | Multi-Agent (Lead + SubAgents) |
| 状态管理 | 简单 | Checkpointing + Middleware Chain |
| 工具调用 | 直接调用 | Skill 系统 + 渐进式加载 |
| 执行环境 | 直接执行 | Sandbox 隔离 (Local/Docker/K8s) |
| 记忆系统 | 无 | Memory System + 跨会话持久化 |

---

## 1.2 核心技术栈

### 后端技术栈

```
Python 3.12+
    │
    ├── LangGraph (0.1.x)      # Agent 编排框架，图结构定义工作流
    ├── LangChain (0.3.x)      # LLM 交互封装
    │       └── langchain-core
    ├── FastAPI (0.115.x)     # REST API 框架
    ├── Pydantic (2.x)        # 数据验证
    ├── uvicorn                # ASGI 服务器
    └── UV                     # Python 包管理器
```

### 前端技术栈

```
Node.js 22+
    │
    ├── Next.js 16.1.7         # React 框架 (App Router)
    ├── React 19.0.0          # UI 库
    ├── TypeScript 5.8.2       # 类型系统
    ├── TanStack Query 5.x     # 服务端状态管理
    ├── @langchain/langgraph-sdk  # LangGraph 前端 SDK
    ├── Tailwind CSS 4.x      # 样式
    └── Radix UI + shadcn/ui  # UI 组件库
```

### 基础设施

```
Nginx (端口 2026)           # 反向代理，统一入口
LangGraph Server (端口 2024)  # Agent 运行时
Gateway API (端口 8001)      # REST API
Frontend (端口 3000)         # Next.js 开发服务器
```

---

## 1.3 核心特性

### 1. Multi-Agent 架构
- **Lead Agent**: 主控 Agent，负责接收用户请求、分解任务、调度子 Agent
- **SubAgents**: 执行具体任务的子 Agent（如 general-purpose、bash）
- 支持最多 **3 个并发子 Agent**（可配置）

### 2. Middleware Chain (中间件链)
13 个中间件按顺序执行，处理横切关注点：
- 线程数据处理
- 文件上传
- 沙箱切换
- 长对话摘要
- Todo 管理
- 标题生成
- 记忆提取
- 图片查看
- 澄清问题处理

### 3. Skills 系统
- **渐进式加载**: Skill 只在需要时才加载
- **19 个内置 Skills**: deep-research, report-generation, slide-creation 等
- **自定义 Skill**: 用户可扩展

### 4. Sandbox 执行
- **Local**: 本地直接执行
- **Docker**: 容器隔离执行
- **Kubernetes**: 集群环境执行
- 虚拟路径映射: `/mnt/user-data/{workspace,uploads,outputs}`

### 5. Memory System
- 自动从对话中提取关键信息
- 跨会话持久化
- 降低 LLM 调用频率

### 6. MCP (Model Context Protocol)
- 支持第三方工具服务器
- OAuth 认证
- 工具缓存

---

## 1.4 项目目录结构

```
deer-flow/
├── README.md                    # 项目主文档
├── Install.md                   # 安装指南
├── Makefile                     # 构建命令
├── config.example.yaml          # 配置模板
├── extensions_config.example.json # 扩展配置模板
│
├── backend/                     # Python 后端
│   ├── packages/
│   │   └── harness/             # deerflow-harness 包 (可发布)
│   │       └── deerflow/
│   │           ├── agents/       # Agent 系统
│   │           ├── sandbox/      # 沙箱执行
│   │           ├── subagents/    # 子 Agent
│   │           ├── tools/        # 工具
│   │           ├── mcp/          # MCP 协议
│   │           ├── models/       # 模型工厂
│   │           ├── skills/       # Skills 系统
│   │           └── config/       # 配置
│   ├── app/                     # 应用层 (不可发布)
│   │   ├── gateway/             # FastAPI 网关
│   │   └── channels/           # IM 集成 (Telegram/Slack/Feishu)
│   └── tests/                   # 测试 (66 个测试文件)
│
├── frontend/                    # Next.js 前端
│   ├── src/
│   │   ├── app/                # App Router
│   │   ├── components/         # React 组件
│   │   ├── core/               # 核心业务逻辑
│   │   └── hooks/              # React Hooks
│   └── package.json
│
├── skills/                      # Agent Skills
│   └── public/                 # 内置 Skills (19个)
│       ├── deep-research/
│       ├── report-generation/
│       └── ...
│
├── scripts/                     # 构建脚本
├── docs/                        # 额外文档
└── docker/                      # Docker 配置
```

---

## 1.5 三服务架构详解

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Nginx (Port 2026)                           │
│               统一反向代理入口，所有请求通过这里                        │
│  ┌──────────────┬───────────────┬──────────────┐                     │
│  │/api/langgraph│  /api/*       │  /*          │                     │
│  │     ↓        │      ↓        │     ↓       │                     │
│  │ LangGraph    │  Gateway API  │  Frontend   │                     │
│  │ Server:2024  │  :8001        │  :3000      │                     │
│  └──────────────┴───────────────┴──────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```

### LangGraph Server (端口 2024)
- **职责**: Agent 运行时，负责执行 Agent 逻辑
- **核心**: 基于 LangGraph 的 StateGraph
- **通信**: SSE (Server-Sent Events) 流式响应

### Gateway API (端口 8001)
- **职责**: REST API，提供模型配置、MCP、文件上传等
- **框架**: FastAPI + uvicorn
- **路由**: `/api/models/`, `/api/mcp/`, `/api/skills/` 等

### Frontend (端口 3000)
- **职责**: 用户交互界面
- **框架**: Next.js (App Router)
- **状态管理**: TanStack Query + React Context

---

## 1.6 快速体验

```bash
# 1. 克隆项目
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow

# 2. 生成配置
make config

# 3. 配置 API Key (编辑 .env 或 config.yaml)
# GLM_API_KEY=your-api-key

# 4. 安装依赖并启动
make install
make dev

# 5. 访问 http://localhost:2026
```

---

## 1.7 下一步

现在你已经了解了 DeerFlow 的基本概念，接下来进入：

**[01-Phase 1: 项目整体架构](./01-phase1-architecture.md)**

深入学习三服务架构、Nginx 路由、配置文件等。

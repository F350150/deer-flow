# DeerFlow Agent 学习计划 - 总览

> 本学习计划专为希望学习 Agent 开发并将其写入简历的同学设计

## 项目简介

**DeerFlow (Deep Exploration and Efficient Research Flow)** 是字节跳动开源的**全能型 Agent 框架**，基于 LangGraph + LangChain 构建，版本 2.0 完全重写。它通过编排 sub-agents、memory 和 sandboxes 来完成复杂任务。

**为什么学习 DeerFlow？**
- 字节跳动出品，有大厂背书
- 基于主流的 LangGraph/LangChain
- 代码质量高，架构设计优秀
- 涵盖 Agent 核心概念：Multi-Agent、Middleware、Skills、Memory、Sandbox

---

## 学习阶段总览

| 阶段 | 预计时间 | 主题 | 重要性 |
|------|----------|------|--------|
| Phase 1 | 3-5 天 | 项目整体架构 | ⭐⭐⭐ |
| Phase 2 | 5-7 天 | Agent 核心实现 | ⭐⭐⭐⭐⭐ |
| Phase 3 | 5-7 天 | Skills 系统 | ⭐⭐⭐⭐ |
| Phase 4 | 3-5 天 | Frontend 与 Agent 交互 | ⭐⭐⭐⭐ |
| Phase 5 | 5-7 天 | Sandbox 执行和安全机制 | ⭐⭐⭐⭐ |
| Phase 6 | 3-5 天 | 进阶主题：Memory、MCP、Channels | ⭐⭐⭐ |
| Phase 7 | 持续 | 实战项目 + 简历准备 | ⭐⭐⭐⭐⭐ |

---

## 推荐学习顺序

```
Week 1: 环境搭建 + 整体架构理解
  ↓
Week 2-3: Agent 核心实现 (Phase 2) - 最重要！
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

## 核心技术栈

### 后端
- **Python 3.12+** - 主语言
- **LangGraph** - Agent 编排框架
- **LangChain** - LLM 交互
- **FastAPI** - REST API

### 前端
- **Next.js 16** - React 框架
- **React 19** - UI 库
- **TypeScript** - 类型安全
- **TanStack Query** - 服务端状态管理

### 基础设施
- **Nginx** - 反向代理 (端口 2026)
- **Docker** - 容器化

---

## 关键文件索引

| 分类 | 文件路径 | 重要性 |
|------|----------|--------|
| 主 Agent | `packages/harness/deerflow/agents/lead_agent/agent.py` | ⭐⭐⭐⭐⭐ |
| 状态管理 | `packages/harness/deerflow/agents/thread_state.py` | ⭐⭐⭐⭐⭐ |
| 系统提示词 | `packages/harness/deerflow/agents/lead_agent/prompt.py` | ⭐⭐⭐⭐⭐ |
| Sandbox | `packages/harness/deerflow/sandbox/*.py` | ⭐⭐⭐⭐ |
| Middleware | `packages/harness/deerflow/agents/middlewares/*.py` | ⭐⭐⭐⭐ |
| Skills | `packages/harness/deerflow/skills/*.py` | ⭐⭐⭐⭐ |
| 配置系统 | `packages/harness/deerflow/config/*.py` | ⭐⭐⭐ |
| 前端 API | `frontend/src/core/api/api-client.ts` | ⭐⭐⭐⭐ |
| 前端 Thread | `frontend/src/core/threads/hooks.ts` | ⭐⭐⭐⭐ |

---

## 各阶段文档

- [00-Getting Started: 从 make dev 开始](./00-getting-started.md) ← **推荐先读这个**
- [00a-项目概述](./00a-project-overview.md)
- [01-Phase 1: 项目整体架构](./01-phase1-architecture.md)
- [02-Phase 2: Agent 核心实现](./02-phase2-agent-core.md)
- [03-Phase 3: Skills 系统](./03-phase3-skills-system.md)
- [04-Phase 4: Frontend 与 Agent 交互](./04-phase4-frontend-interaction.md)
- [05-Phase 5: Sandbox 执行和安全机制](./05-phase5-sandbox.md)
- [06-Phase 6: 进阶主题](./06-phase6-advanced.md)
- [07-Phase 7: 实战项目与简历准备](./07-phase7-project-resume.md)

---

## 学习资源

### 官方文档
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [LangChain 文档](https://python.langchain.com/)
- [DeerFlow GitHub](https://github.com/bytedance/deer-flow)

### 项目内文档
- `README.md` - 项目整体介绍
- `backend/CLAUDE.md` - 后端架构详解
- `frontend/CLAUDE.md` - 前端架构
- `backend/docs/ARCHITECTURE.md` - 详细架构文档

---

*Last Updated: 2026-03-27*

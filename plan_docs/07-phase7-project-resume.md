# 07 - Phase 7: 实战项目与简历准备

> 预计时间: 持续实践
> 
> 本阶段目标：通过 DeerFlow 做实战项目，掌握核心技能，并准备简历

---

## 7.1 推荐实战项目

### 项目 1: 自定义 Skill 开发

**目标**: 开发一个特定领域的 Research Skill

**选择领域**:
- 股票分析
- 技术文档生成
- 论文研究
- 代码审查

**实现步骤**:

```
1. 创建 Skill 目录
   mkdir -p skills/custom/my-research/
   
2. 编写 SKILL.md
   - 定义描述
   - 制定工作流程
   - 指定所需工具
   
3. 编写 prompt 模板
   - system.md
   - user.md
   
4. 测试 Skill
   - 在 DeerFlow 中触发
   - 观察行为
   - 迭代改进
```

**验收标准**:
- [ ] Skill 能被正确加载
- [ ] 工作流程符合预期
- [ ] 输出质量良好

**项目产出**:
```
skills/custom/
└── my-research/
    ├── SKILL.md
    └── prompt/
        ├── system.md
        └── user.md
```

---

### 项目 2: 自定义 Middleware

**目标**: 实现一个日志记录或监控 Middleware

**示例: 请求日志 Middleware**

```python
# backend/packages/harness/deerflow/agents/middlewares/my_logger.py

import logging
from datetime import datetime
from typing import TypeVar

StateT = TypeVar("StateT", bound=ThreadState)

logger = logging.getLogger(__name__)

class MyLoggerMiddleware:
    """自定义日志中间件"""
    
    def __init__(self, log_file: str = "logs/agent.log"):
        self.log_file = log_file
    
    def __call__(
        self,
        state: ThreadState,
        config: RunnableConfig,
    ) -> ThreadState:
        # 1. 记录请求信息
        timestamp = datetime.now().isoformat()
        thread_id = state.get("thread_id", "unknown")
        message_count = len(state.get("messages", []))
        
        log_entry = f"[{timestamp}] thread={thread_id} messages={message_count}\n"
        
        with open(self.log_file, "a") as f:
            f.write(log_entry)
        
        # 2. 添加时间戳到状态
        state["last_log_time"] = timestamp
        
        return state
```

**验收标准**:
- [ ] Middleware 正确注册
- [ ] 日志正确写入
- [ ] 不影响 Agent 执行

---

### 项目 3: MCP 工具集成

**目标**: 集成一个外部工具到 DeerFlow

**示例: 集成 GitHub MCP Server**

```json
// extensions_config.json
{
  "mcp_servers": [
    {
      "name": "github",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "$GITHUB_TOKEN"
      }
    }
  ]
}
```

**验收标准**:
- [ ] MCP Server 正常启动
- [ ] Agent 能调用 GitHub 工具
- [ ] OAuth 认证正常

---

### 项目 4: 自定义 Tool

**目标**: 开发一个新的内置 Tool

**示例: 天气查询 Tool**

```python
# backend/packages/harness/deerflow/tools/weather.py

from langchain_core.tools import tool

@tool
def get_weather(location: str, unit: str = "celsius") -> str:
    """获取天气信息
    
    Args:
        location: 城市名称，如 "北京"
        unit: 温度单位，"celsius" 或 "fahrenheit"
    
    Returns:
        天气信息描述
    """
    import requests
    
    # 调用天气 API（这里用示例）
    # 实际项目中应该使用真实的天气 API
    response = requests.get(
        f"https://api.weather.example.com",
        params={"location": location, "unit": unit}
    )
    
    data = response.json()
    return f"{location}天气：{data['temp']}°{unit[0].upper()}，{data['condition']}"
```

**验收标准**:
- [ ] Tool 正确注册
- [ ] Tool 能被 Agent 调用
- [ ] 返回正确结果

---

## 7.2 简历撰写指南

### DeerFlow 项目描述模板

**❌ 错误示例**:
```
学习了 DeerFlow 框架，用它做了一个 AI Agent 项目。
```

**✅ 正确示例**:

```
DeerFlow Agent 框架学习与实践

项目描述：
- 研究字节跳动开源的 DeerFlow 2.0 Agent 框架，基于 LangGraph + LangChain
- 深入理解 Multi-Agent 架构设计：Lead Agent 负责任务分解，SubAgent 并行执行
- 掌握 Middleware Chain 设计模式：实现日志记录、性能监控等中间件
- 理解 Skill 系统架构：开发自定义 Skill（股票分析/技术文档生成）
- 熟悉 Sandbox 安全执行机制：掌握 Local/Docker/Kubernetes 三种执行环境
- 学习 Memory System：实现跨会话用户偏好记忆

技术栈：Python, LangGraph, LangChain, FastAPI, Next.js, TypeScript, Docker
```

### 面试高频问题

#### Q1: LangGraph 的优势是什么？

**参考答案**:

LangGraph 相比 LangChain Agent 的优势：

1. **图结构更清晰**
   - 工作流以图的形式定义，便于可视化和理解
   - 节点=功能，边=控制流

2. **支持 Checkpointing**
   - 可以保存/恢复状态
   - 支持 Human-in-the-Loop

3. **支持 Interrupt**
   - 可以在节点执行前后中断
   - 等待人工确认后再继续

4. **更细粒度的控制流**
   - 条件边（if-else）
   - 循环（while）
   - 并行分支

#### Q2: DeerFlow 的 Middleware Chain 如何工作？

**参考答案**:

DeerFlow 的 Middleware Chain 是**按顺序执行的钩子链**：

1. 每个 Middleware 实现 `__call__` 方法
2. Middleware 可以修改 ThreadState
3. 按顺序执行，形成链式调用
4. 13 个 Middleware 各司其职（sandbox、memory、todo 等）

#### Q3: Sandbox 安全隔离如何实现？

**参考答案**:

1. **三层隔离**:
   - Local：无隔离，直接执行
   - Docker：容器隔离
   - Kubernetes：Pod + 资源限制

2. **路径映射**:
   - 虚拟路径 `/mnt/user-data/*` 映射到实际目录
   - 防止路径遍历攻击

3. **命令限制**:
   - 禁止危险命令
   - 超时控制
   - 资源配额

#### Q4: 如何设计一个自定义 Skill？

**参考答案**:

1. **创建目录结构**:
   ```
   skills/custom/my-skill/
   ├── SKILL.md
   └── prompt/
   ```

2. **编写 SKILL.md**:
   - 定义名称、描述
   - 说明何时使用
   - 指定输入输出
   - 制定工作流程

3. **编写 prompt 模板**:
   - system.md: 系统提示词
   - user.md: 用户提示词模板

4. **测试迭代**

---

## 7.3 技术深度检查清单

### 必须掌握

- [ ] **ThreadState 数据结构** - 能解释 `Annotated` + `add_messages` 的作用
- [ ] **Lead Agent 创建流程** - 能描述 `make_lead_agent` 的主要步骤
- [ ] **Middleware Chain 机制** - 能说明 Middleware 的执行顺序和作用
- [ ] **SubAgent 并行调度** - 能解释最多 3 个并发的限制原因
- [ ] **Sandbox 三种环境** - 能比较 Local/Docker/K8s 的区别

### 理解即可

- [ ] Memory System 架构
- [ ] MCP 协议集成
- [ ] IM Channels 实现
- [ ] Guardrails 机制

---

## 7.4 项目成果展示

### GitHub README 模板

```markdown
# My DeerFlow Skill - [领域]

## 简介

这是一个为 DeerFlow Agent 框架开发的 [领域] Skill，能够...

## 功能

- 功能 1
- 功能 2
- 功能 3

## 工作流程

1. 收集用户需求
2. 搜索相关信息
3. 分析整理
4. 生成报告

## 使用方法

```bash
# 克隆 DeerFlow
git clone https://github.com/bytedance/deer-flow.git

# 复制 Skill
cp -r my-skill deer-flow/skills/custom/

# 启动 DeerFlow
make dev
```

## 技术栈

- Python
- LangGraph
- LangChain

## 参考

- [DeerFlow 官方仓库](https://github.com/bytedance/deer-flow)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
```

---

## 7.5 下一步

恭喜你完成 DeerFlow 学习计划！

**后续建议**:

1. **持续贡献**: 向 DeerFlow 提交 PR
2. **深入研究**: 阅读 LangGraph/LangChain 源码
3. **拓展应用**: 将 DeerFlow 集成到你的项目中
4. **分享经验**: 写博客分享学习心得

**资源链接**:

- [DeerFlow GitHub](https://github.com/bytedance/deer-flow)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [LangChain 文档](https://python.langchain.com/)
- [项目学习计划](../DEERFLOW_LEARNING_PLAN.md)
```

---

## 7.6 学习计划总结

```
✅ Phase 1: 项目整体架构 (3-5 天)
✅ Phase 2: Agent 核心实现 (5-7 天) ← 最重要
✅ Phase 3: Skills 系统 (5-7 天)
✅ Phase 4: Frontend 与 Agent 交互 (3-5 天)
✅ Phase 5: Sandbox 执行和安全机制 (5-7 天)
✅ Phase 6: 进阶主题 (3-5 天)
✅ Phase 7: 实战项目与简历准备 (持续)

总计: 约 4-6 周
```

---

*Last Updated: 2026-03-27*
*恭喜完成 DeerFlow 学习计划！*

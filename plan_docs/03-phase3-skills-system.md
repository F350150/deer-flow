# 03 - Phase 3: Skills 系统

> 预计时间: 5-7 天
> 
> 本阶段目标：理解 DeerFlow 的 Skill 系统架构、内置 Skills、自定义 Skill 开发

---

## 3.1 Skills 概述

### 什么是 Skill？

**Skill** 是 DeerFlow 中的**任务特定的工作流优化模块**。它包含最佳实践、框架和额外资源引用，帮助 Agent 更高效地完成特定类型的任务。

### Skill vs Tool vs SubAgent

| 概念 | 粒度 | 调用方式 | 用途 |
|------|------|----------|------|
| **Tool** | 原子操作 | 直接调用 | 文件读写、bash 命令等 |
| **Skill** | 工作流 | 渐进式加载 | 研究报告、PPT 生成等 |
| **SubAgent** | 子任务 | 任务委托 | 独立执行复杂子任务 |

### Skill 的特点

1. **渐进式加载**: Skill 只在需要时才加载完整内容
2. **工作流封装**: 包含完成特定任务的最佳实践
3. **可扩展**: 支持用户自定义 Skill
4. **声明式**: 通过 SKILL.md 文件定义

---

## 3.2 内置 Skills 列表

**位置**: `skills/public/`

DeerFlow 内置了 **19 个 Skills**：

| Skill 名称 | 用途 |
|------------|------|
| `deep-research` | 深度研究报告 |
| `report-generation` | 报告生成 |
| `slide-creation` | PPT/幻灯片制作 |
| `web-page` | 网页生成 |
| `image-generation` | 图片生成 |
| `video-generation` | 视频生成 |
| `ppt-generation` | PPT 生成 |
| `podcast-generation` | 播客生成 |
| `data-analysis` | 数据分析 |
| `chart-visualization` | 图表可视化 |
| `frontend-design` | 前端设计 |
| `github-deep-research` | GitHub 深度研究 |
| `consulting-analysis` | 咨询分析 |
| `find-skills` | 查找 Skills |
| `skill-creator` | 创建 Skill |
| `web-design-guidelines` | Web 设计指南 |
| `surprise-me` | 随机惊喜 |
| `vercel-deploy-claimable` | Vercel 部署 |
| `claude-to-deerflow` | Claude 到 DeerFlow 迁移 |

---

## 3.3 Skill 文件结构

每个 Skill 都有标准的目录结构：

```
skills/public/deep-research/
├── SKILL.md              # Skill 定义文件 (必须)
├── prompt/
│   ├── system.md         # 系统提示词
│   ├── user.md           # 用户提示词模板
│   └── ...
├── scripts/              # 执行脚本 (可选)
│   └── generate_report.py
├── requirements/         # Python 依赖 (可选)
│   └── requirements.txt
└── assets/               # 静态资源 (可选)
    └── template.html
```

### SKILL.md 详解

这是 Skill 的**核心定义文件**：

```markdown
# Deep Research Skill

## 描述
用于进行深度研究任务的 Skill，能够搜索、分析、整合多个来源的信息。

## 何时使用
当用户请求进行深入研究、分析报告、市场调研等时应加载此 Skill。

## 输入
- 研究主题
- 研究范围和深度
- 信息来源偏好

## 输出
结构化的研究报告，包含：
- 执行摘要
- 详细分析
- 数据支撑
- 引用来源

## 使用的工具
- web_search: 搜索网络信息
- web_fetch: 获取网页内容
- read_file: 读取本地文件

## 工作流程
1. 理解研究目标和范围
2. 制定研究计划
3. 收集信息（并行搜索多个来源）
4. 分析和整合信息
5. 生成报告

## 最佳实践
- 使用多个信息源交叉验证
- 引用要包含 URL
- 保持客观中立
```

### Skill 的元数据

```yaml
# SKILL.md 中的关键元数据

# 名称（必须）
skill_name: deep-research

# 描述（必须）- 简短描述，用于在提示词中列出
description: 用于进行深度研究任务的 Skill

# 何时使用 - 帮助 Agent 判断何时加载
use_when:
  - 研究
  - 调研
  - 分析报告

# 输入输出格式
input_format: markdown
output_format: markdown
```

---

## 3.4 Skill 加载机制

**文件**: `backend/packages/harness/deerflow/skills/`

### Skill 加载流程

```
1. 用户发送请求
   ↓
2. Agent 分析请求，判断需要哪个 Skill
   ↓
3. Agent 调用 read_file 读取 Skill 的 SKILL.md
   ↓
4. 解析 Skill 定义，理解工作流程
   ↓
5. 按照 Skill 定义执行任务
   ↓
6. 使用 Skill 指定的工具组合
```

### Skill 在提示词中的引用

在系统提示词中，Agent 会看到可用的 Skills 列表：

```xml
<skill_system>
You have access to skills that provide optimized workflows...

Available Skills:
<skill>
    <name>deep-research</name>
    <description>用于进行深度研究...</description>
    <location>/mnt/skills/public/deep-research/SKILL.md</location>
</skill>

Progressive Loading Pattern:
1. When user query matches a skill's use case, call `read_file` on the skill's main file
2. Read and understand the skill's workflow
3. Follow the skill's instructions precisely
</skill_system>
```

### Skill 注册表

```python
# backend/packages/harness/deerflow/skills/registry.py

class SkillRegistry:
    """Skill 注册表，管理所有可用的 Skills"""
    
    def __init__(self):
        self._skills: dict[str, Skill] = {}
    
    def register(self, skill: Skill) -> None:
        """注册一个 Skill"""
        self._skills[skill.name] = skill
    
    def get(self, name: str) -> Skill | None:
        """获取指定名称的 Skill"""
        return self._skills.get(name)
    
    def list_all(self) -> list[Skill]:
        """列出所有注册的 Skills"""
        return list(self._skills.values())
    
    def list_enabled(self) -> list[Skill]:
        """列出所有启用的 Skills"""
        return [s for s in self._skills.values() if s.enabled]
```

---

## 3.5 Skill 定义类

```python
# backend/packages/harness/deerflow/skills/skill.py

from dataclasses import dataclass
from pathlib import Path

@dataclass
class Skill:
    """Skill 的数据结构"""
    
    name: str                           # 唯一标识
    description: str                    # 简短描述
    path: Path                          # Skill 目录路径
    enabled: bool = True               # 是否启用
    
    @property
    def main_file(self) -> Path:
        """主文件路径"""
        return self.path / "SKILL.md"
    
    @property
    def scripts_dir(self) -> Path:
        """脚本目录"""
        return self.path / "scripts"
    
    @property
    def requirements_file(self) -> Path | None:
        """依赖文件路径"""
        req = self.path / "requirements.txt"
        return req if req.exists() else None
    
    def get_container_file_path(self, base_path: str) -> str:
        """获取容器内的文件路径"""
        return f"{base_path}/public/{self.name}/SKILL.md"
```

---

## 3.6 自定义 Skill 开发

### 开发流程

```
1. 创建 Skill 目录结构
2. 编写 SKILL.md 定义文件
3. 编写 prompt 模板（可选）
4. 编写脚本（可选）
5. 配置依赖（可选）
6. 测试 Skill
```

### 示例：创建 "股票分析" Skill

#### Step 1: 创建目录

```bash
mkdir -p skills/custom/stock-analysis/
mkdir -p skills/custom/stock-analysis/prompt
mkdir -p skills/custom/stock-analysis/scripts
```

#### Step 2: 编写 SKILL.md

```markdown
# Stock Analysis Skill

## 描述
用于分析股票走势、财务数据和市场情绪的 Skill。

## 何时使用
- 用户询问股票投资建议
- 用户要求分析特定股票
- 用户想要了解公司财务状况

## 输入
- 股票代码或公司名称
- 分析时间范围
- 分析深度（简单/详细）

## 输出
股票分析报告，包含：
- 基本面分析
- 技术面分析
- 市场情绪
- 风险评估
- 投资建议

## 使用的工具
- web_search: 搜索股票相关信息
- web_fetch: 获取财经数据
- read_file: 读取本地财务文件

## 工作流程
1. 收集股票基本信息
2. 获取财务数据
3. 分析历史价格走势
4. 评估市场情绪
5. 生成分析报告

## 注意事项
- 不提供具体的买卖建议
- 强调投资风险
- 数据来源要可靠
```

#### Step 3: 编写 prompt 模板（可选）

```markdown
# prompt/analyze.md

## 分析模板

### 股票信息
- 公司名称: {company_name}
- 股票代码: {stock_code}
- 分析时间: {analysis_date}

### 分析内容
{analysis_content}

### 风险提示
{ risk_warning }
```

#### Step 4: 配置 Skill（可选）

如果 Skill 需要额外配置，可以在 `config.yaml` 或 `extensions_config.json` 中配置：

```json
// extensions_config.json
{
  "skills": {
    "stock-analysis": {
      "enabled": true,
      "data_sources": ["yfinance", "alpha_vantage"],
      "default_depth": "detailed"
    }
  }
}
```

---

## 3.7 Skill 加载配置

### config.yaml 中的配置

```yaml
skills:
  # Skill 文件的基础路径
  container_path: /mnt/skills
  
  # 内置 Skills 路径
  public_path: ./skills/public
  
  # 自定义 Skills 路径
  custom_path: ./skills/custom
  
  # 是否启用所有 Skills
  enabled: true
```

### 禁用特定 Skill

```yaml
skills:
  disabled:
    - image-generation  # 禁用图片生成
    - video-generation   # 禁用视频生成
```

---

## 3.8 Skill 与 Agent Tool 的区别

### Tool（工具）

```python
# Tool 是原子操作，直接被 Agent 调用
tools = [
    bash,           # 执行命令
    read_file,      # 读取文件
    write_file,     # 写入文件
    web_search,     # 网络搜索
]
```

### Skill（技能）

```python
# Skill 是工作流，告诉 Agent 如何完成特定任务
# Skill 本身不是工具，而是指导 Agent 使用工具的框架

# 例如 deep-research Skill 会指导 Agent:
# 1. 使用 web_search 搜索多个来源
# 2. 使用 web_fetch 获取详细内容
# 3. 综合分析生成报告
```

### SubAgent（子代理）

```python
# SubAgent 是独立的工作单元，有自己的完整执行环境
task(
    description="Research Tesla financials",
    subagent_type="general-purpose"  # 使用通用子代理
)
```

### 组合使用示例

```
用户请求: "帮我研究一下苹果公司的投资价值"

Lead Agent 分析后决定:
1. 加载 "stock-analysis" Skill
2. 使用 SubAgent 并行搜索多个来源
3. 使用 web_search, web_fetch 等 Tool
4. 综合结果生成报告
```

---

## 3.9 实践任务

### 任务 1: 阅读 3 个内置 Skill

选择 3 个不同的内置 Skill（如 deep-research、report-generation、slide-creation），完整阅读它们的 SKILL.md，理解其设计思路。

### 任务 2: 创建自定义 Skill

创建一个 "技术文档生成" Skill，包含：
- SKILL.md 定义文件
- prompt 模板
- 工作流程说明

### 任务 3: 调试 Skill 加载

在 DeerFlow 中触发一个需要 Skill 的请求，使用日志追踪 Skill 是如何被加载和执行的。

---

## 3.10 学习目标检查清单

- [ ] 理解 Skill 与 Tool 的区别
- [ ] 理解 Skill 的渐进式加载机制
- [ ] 理解 SKILL.md 的结构和字段
- [ ] 能够阅读内置 Skill 的实现
- [ ] 能够创建自定义 Skill
- [ ] 理解 Skill 在提示词中的引用方式

---

## 3.11 相关源码文件

| 文件 | 作用 |
|------|------|
| `packages/harness/deerflow/skills/__init__.py` | Skill 模块入口 |
| `packages/harness/deerflow/skills/loader.py` | Skill 加载器 |
| `packages/harness/deerflow/skills/registry.py` | Skill 注册表 |
| `packages/harness/deerflow/skills/skill.py` | Skill 数据类 |
| `packages/harness/deerflow/agents/lead_agent/prompt.py` | 提示词中的 Skill 引用 |

---

## 3.12 下一步

**[04-Phase 4: Frontend 与 Agent 交互](./04-phase4-frontend-interaction.md)**

学习 DeerFlow 前端如何与后端 Agent 交互：Streaming、SSE、Thread 管理。

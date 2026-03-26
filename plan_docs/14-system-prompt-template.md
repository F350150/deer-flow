# System Prompt 模板详解

## 1. 概述

DeerFlow 的 `apply_prompt_template()` 函数负责动态生成 Agent 的 system prompt。它将多个组件（角色定义、记忆、技能、子代理配置等）组装成一个完整的提示词。

```python
# deerflow/agents/lead_agent/agent.py:337-342
return create_agent(
    model=create_chat_model(...),
    tools=get_available_tools(...),
    middleware=_build_middlewares(...),
    system_prompt=apply_prompt_template(
        subagent_enabled=subagent_enabled,
        max_concurrent_subagents=max_concurrent_subagents,
        agent_name=agent_name
    ),
    state_schema=ThreadState,
)
```

## 2. apply_prompt_template 函数解析

### 2.1 函数签名

```python
# deerflow/agents/lead_agent/prompt.py:468-516
def apply_prompt_template(
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
    *,
    agent_name: str | None = None,
    available_skills: set[str] | None = None,
) -> str:
```

### 2.2 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `subagent_enabled` | bool | 是否启用子代理模式 |
| `max_concurrent_subagents` | int | 最大并发子代理数量（默认 3） |
| `agent_name` | str \| None | Agent 名称，用于加载个性化配置 |
| `available_skills` | set[str] \| None | 可用技能集合，None 表示全部 |

### 2.3 返回值

返回完整的 system prompt 字符串，包含以下组件的动态组合。

## 3. Prompt 组装流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     apply_prompt_template()                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────────┐     │
│  │ memory_context │ +  │ soul          │ +  │ skills_section    │     │
│  │ (记忆上下文)   │    │ (Agent 灵魂)  │    │ (技能列表)        │     │
│  └───────────────┘    └───────────────┘    └───────────────────┘     │
│         │                   │                   │                       │
│         └───────────────────┴─────────────────┘                       │
│                             │                                          │
│                             ▼                                          │
│              ┌──────────────────────────────┐                       │
│              │    SYSTEM_PROMPT_TEMPLATE     │                       │
│              │         (主模板)              │                       │
│              └──────────────────────────────┘                       │
│                             │                                          │
│                             ▼                                          │
│         ┌──────────────────────────────────────────┐                 │
│         │         动态组件注入                      │                 │
│         │                                          │                 │
│         │  {soul}           → Agent Soul          │                 │
│         │  {memory_context} → 记忆上下文           │                 │
│         │  {skills_section} → 技能说明              │                 │
│         │  {deferred_tools_section} → 延迟工具列表 │                 │
│         │  {subagent_section} → 子代理配置         │                 │
│         │  {acp_section}     → ACP Agent 配置     │                 │
│         └──────────────────────────────────────────┘                 │
│                             │                                          │
│                             ▼                                          │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  <role> Agent 角色定义 </role>                             │     │
│  │  <soul> Agent 个性 </soul>                                 │     │
│  │  <memory> 用户记忆上下文 </memory>                         │     │
│  │  <thinking_style> 思考风格指导 </thinking_style>           │     │
│  │  <clarification_system> 澄清系统 </clarification_system>   │     │
│  │  <skill_system> 技能系统 </skill_system>                 │     │
│  │  <available-deferred-tools> 延迟工具 </available-deferred-tools>│  │
│  │  <subagent_system> 子代理系统 </subagent_system>          │     │
│  │  <working_directory> 工作目录 </working_directory>         │     │
│  │  <response_style> 响应风格 </response_style>              │     │
│  │  <citations> 引用规范 </citations>                         │     │
│  │  <critical_reminders> 关键提醒 </critical_reminders>      │     │
│  │  <current_date> 当前日期 </current_date>                   │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## 4. SYSTEM_PROMPT_TEMPLATE 主体结构

```python
# deerflow/agents/lead_agent/prompt.py:150-336
SYSTEM_PROMPT_TEMPLATE = """
<role>
You are {agent_name}, an open-source super agent.
</role>

{soul}
{memory_context}

<thinking_style>
- Think concisely and strategically about the user's request BEFORE taking action
- Break down the task: What is clear? What is ambiguous? What is missing?
- **PRIORITY CHECK**: If anything is unclear, missing, or has multiple interpretations,
  you MUST ask for clarification FIRST - do NOT proceed with work
{subagent_thinking}
- Never write down your full final answer or report in thinking process, but only outline
- CRITICAL: After thinking, you MUST provide your actual response to the user
- Your response must contain the actual answer, not just a reference to what you thought about
</thinking_style>

<clarification_system>
**WORKFLOW PRIORITY: CLARIFY → PLAN → ACT**
...
</clarification_system>

{skills_section}

{deferred_tools_section}

{subagent_section}

<working_directory existed="true">
- User uploads: `/mnt/user-data/uploads`
- User workspace: `/mnt/user-data/workspace`
- Output files: `/mnt/user-data/outputs`
{acp_section}
</working_directory>

<response_style>
...
</response_style>

<citations>
...
</citations>

<critical_reminders>
- **Clarification First**: ALWAYS clarify unclear/missing/ambiguous requirements BEFORE starting work
{subagent_reminder}
- Skill First: Always load the relevant skill before starting **complex** tasks.
- Progressive Loading: Load resources incrementally as referenced in skills
...
</critical_reminders>
"""
```

## 5. 动态组件详解

### 5.1 记忆上下文（memory_context）

```python
# deerflow/agents/lead_agent/prompt.py:339-368
def _get_memory_context(agent_name: str | None = None) -> str:
    """Get memory context for injection into system prompt."""
    config = get_memory_config()
    if not config.enabled or not config.injection_enabled:
        return ""

    memory_data = get_memory_data(agent_name)
    memory_content = format_memory_for_injection(memory_data, max_tokens=config.max_injection_tokens)

    return f"""<memory>
{memory_content}
</memory>
"""
```

**格式化后的记忆结构**：

```
<memory>
User Context:
- Work: Senior engineer at ByteDance, working on DeerFlow
- Personal: Prefers concise responses
- Current Focus: Debugging MCP tool integration

History:
- Recent: Explored LangGraph middleware architecture
- Earlier: Built similar agent systems for internal use

Facts:
- [preference | 0.95] Prefers Python over other languages
- [knowledge | 0.90] Expert in LangChain framework
</memory>
```

**Token 限制**：
- 使用 `tiktoken` 精确计数
- 超过 `max_injection_tokens` 时截断

### 5.2 Agent Soul（灵魂配置）

```python
# deerflow/agents/lead_agent/prompt.py:415-420
def get_agent_soul(agent_name: str | None) -> str:
    soul = load_agent_soul(agent_name)
    if soul:
        return f"<soul>\n{soul}\n</soul>\n"
    return ""
```

从 `agents/{agent_name}/SOUL.md` 文件加载 Agent 个性配置。

**示例 SOUL.md**：

```
You are a thoughtful and precise AI assistant.
You always verify information before stating it as fact.
You prefer actionable advice over theoretical explanations.
```

**输出格式**：

```
<soul>
You are a thoughtful and precise AI assistant.
You always verify information before stating it as fact.
</soul>
```

### 5.3 技能系统（skills_section）

```python
# deerflow/agents/lead_agent/prompt.py:371-412
def get_skills_prompt_section(available_skills: set[str] | None = None) -> str:
    skills = load_skills(enabled_only=True)
    if available_skills is not None:
        skills = [skill for skill in skills if skill.name in available_skills]

    skill_items = "\n".join(
        f"""    <skill>
        <name>{skill.name}</name>
        <description>{skill.description}</description>
        <location>{skill.get_container_file_path(container_base_path)}</location>
    </skill>""" for skill in skills
    )

    return f"""<skill_system>
You have access to skills that provide optimized workflows for specific tasks.

**Progressive Loading Pattern:**
1. When a user query matches a skill's use case, immediately call `read_file` on the skill's main file
2. Read and understand the skill's workflow and instructions
3. Follow the skill's instructions precisely

<available_skills>
{skill_items}
</available_skills>
</skill_system>"""
```

**输出示例**：

```
<skill_system>
You have access to skills that provide optimized workflows for specific tasks.

**Progressive Loading Pattern:**
...

<available_skills>
    <skill>
        <name>github-deep-research</name>
        <description>Deep research on GitHub repositories</description>
        <location>/mnt/skills/public/github-deep-research/SKILL.md</location>
    </skill>
    <skill>
        <name>code-review</name>
        <description>Automated code review workflow</description>
        <location>/mnt/skills/public/code-review/SKILL.md</location>
    </skill>
</available_skills>
</skill_system>
```

### 5.4 延迟工具（deferred_tools_section）

```python
# deerflow/agents/lead_agent/prompt.py:423-445
def get_deferred_tools_prompt_section() -> str:
    if not get_app_config().tool_search.enabled:
        return ""

    registry = get_deferred_registry()
    if not registry:
        return ""

    names = "\n".join(e.name for e in registry.entries)
    return f"<available-deferred-tools>\n{names}\n</available-deferred-tools>"
```

**输出示例**：

```
<available-deferred-tools>
mcp_github_issues
mcp_github_commits
mcp_filesystem_read
</available-deferred-tools>
```

### 5.5 子代理系统（subagent_section）

```python
# deerflow/agents/lead_agent/prompt.py:7-147
def _build_subagent_section(max_concurrent: int) -> str:
    n = max_concurrent
    return f"""<subagent_system>
**🚀 SUBAGENT MODE ACTIVE - DECOMPOSE, DELEGATE, SYNTHESIZE**

You are running with subagent capabilities enabled. Your role is to be a **task orchestrator**:
1. **DECOMPOSE**: Break complex tasks into parallel sub-tasks
2. **DELEGATE**: Launch multiple subagents simultaneously using parallel `task` calls
3. **SYNTHESIZE**: Collect and integrate results into a coherent answer

**⛔ HARD CONCURRENCY LIMIT: MAXIMUM {n} `task` CALLS PER RESPONSE.**

... [详细内容见子代理文档]
</subagent_system>"""
```

**关键特性**：

1. **硬限制**：`max {n} task calls per response`，超出被丢弃
2. **批量执行**：超过 `{n}` 个子任务时必须分批
3. **示例指导**：提供完整的并行执行示例

### 5.6 ACP Section（ACP Agent 配置）

```python
# deerflow/agents/lead_agent/prompt.py:448-465
def _build_acp_section() -> str:
    agents = get_acp_agents()
    if not agents:
        return ""

    return (
        "\n**ACP Agent Tasks (invoke_acp_agent):**\n"
        "- ACP agents run in their own workspace — NOT in `/mnt/user-data/`\n"
        "- When writing prompts for ACP agents, describe the task only\n"
        "- ACP agent results are accessible at `/mnt/acp-workspace/`"
    )
```

## 6. 完整组装流程

```python
# deerflow/agents/lead_agent/prompt.py:468-516
def apply_prompt_template(...):
    # 1. 获取记忆上下文
    memory_context = _get_memory_context(agent_name)

    # 2. 构建子代理配置
    n = max_concurrent_subagents
    subagent_section = _build_subagent_section(n) if subagent_enabled else ""

    # 3. 子代理提醒
    subagent_reminder = (
        f"- **Orchestrator Mode**: max {n} `task` calls per response.\n"
        if subagent_enabled
        else ""
    )

    # 4. 子代理思考指导
    subagent_thinking = (
        f"- **DECOMPOSITION CHECK**: If count > {n}, plan batches of ≤{n}.\n"
        if subagent_enabled
        else ""
    )

    # 5. 获取技能列表
    skills_section = get_skills_prompt_section(available_skills)

    # 6. 获取延迟工具
    deferred_tools_section = get_deferred_tools_prompt_section()

    # 7. 获取 ACP 配置
    acp_section = _build_acp_section()

    # 8. 组装完整 prompt
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=agent_name or "DeerFlow 2.0",
        soul=get_agent_soul(agent_name),
        skills_section=skills_section,
        deferred_tools_section=deferred_tools_section,
        memory_context=memory_context,
        subagent_section=subagent_section,
        subagent_reminder=subagent_reminder,
        subagent_thinking=subagent_thinking,
        acp_section=acp_section,
    )

    return prompt + f"\n<current_date>{datetime.now().strftime('%Y-%m-%d, %A')}</current_date>"
```

## 7. 运行时参数的影响

### 7.1 subagent_enabled=True vs False

```
┌─────────────────────────────────────────────────────────────┐
│                  subagent_enabled=True                       │
├─────────────────────────────────────────────────────────────┤
│ • 子代理系统块启用（_build_subagent_section）                 │
│ • subagent_reminder 注入到 <critical_reminders>           │
│ • subagent_thinking 注入到 <thinking_style>              │
│ • 可用技能限制由 available_skills 参数控制                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  subagent_enabled=False                    │
├─────────────────────────────────────────────────────────────┤
│ • 子代理系统块为空                                         │
│ • subagent_reminder 为空                                   │
│ • subagent_thinking 为空                                   │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 max_concurrent_subagents 的作用

```python
# 影响 1: 子代理系统块的硬限制
"⛔ HARD CONCURRENCY LIMIT: MAXIMUM {n} `task` CALLS PER RESPONSE."

# 影响 2: critical_reminders 中的提醒
f"**HARD LIMIT: max {n} `task` calls per response.**"

# 影响 3: thinking_style 中的分解指导
f"If count > {n}, you MUST plan batches of ≤{n} and only launch the FIRST batch now."

# 影响 4: 子代理示例中的批量划分
"Turn 1: Launch first batch of {n}"
"Turn 2: Launch remaining batch (after first batch completes)"
```

## 8. 好处总结

### 8.1 模块化设计

```
┌─────────────────────────────────────────────────────────────┐
│  好处 1: 模块化 + 可组合                                   │
├─────────────────────────────────────────────────────────────┤
│  • 每个组件（记忆、技能、子代理）独立管理                  │
│  • 通过参数控制是否启用，灵活组合                          │
│  • 便于单独测试和调试每个组件                              │
│                                                             │
│  apply_prompt_template(                                   │
│      subagent_enabled=...,   ← 控制子代理组件              │
│      max_concurrent=...,    ← 控制并发数量                │
│      agent_name=...,        ← 控制 Agent 个性             │
│      available_skills=...   ← 控制技能列表                │
│  )                                                        │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 按需加载，避免 Token 浪费

```
┌─────────────────────────────────────────────────────────────┐
│  好处 2: 条件渲染节省 Token                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  if subagent_enabled:                                      │
│      subagent_section = _build_subagent_section(n)         │
│  else:                                                     │
│      subagent_section = ""  ← 不生成，不占用 Token          │
│                                                             │
│  if memory_config.enabled:                                │
│      memory_context = get_memory_context()                 │
│  else:                                                    │
│      memory_context = ""  ← 不生成，不占用 Token            │
│                                                             │
│  if tool_search.enabled:                                  │
│      deferred_tools = get_deferred_tools()                 │
│  else:                                                    │
│      deferred_tools = ""                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.3 运行时灵活配置

```
┌─────────────────────────────────────────────────────────────┐
│  好处 3: 运行时参数动态调整                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  create_agent(                                            │
│      ...                                                   │
│      system_prompt=apply_prompt_template(                 │
│          subagent_enabled=subagent_enabled,  ← 运行时决定  │
│          max_concurrent_subagents=max_concurrent_subagents,  │
│          agent_name=agent_name,                            │
│      ),                                                    │
│  )                                                        │
│                                                             │
│  同一个函数，不同运行时参数 → 不同 prompt                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.4 Agent 个性化支持

```
┌─────────────────────────────────────────────────────────────┐
│  好处 4: 支持多 Agent 个性化                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  agent_name = "researcher"                                 │
│  → get_agent_soul("researcher")                           │
│  → 加载 agents/researcher/SOUL.md                          │
│  → <soul>...researcher 个性配置...</soul>                 │
│                                                             │
│  agent_name = "coder"                                      │
│  → get_agent_soul("coder")                                │
│  → 加载 agents/coder/SOUL.md                               │
│  → <soul>...coder 个性配置...</soul>                      │
│                                                             │
│  不同的 agent 可以有不同的"灵魂"                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.5 技能渐进式加载

```
┌─────────────────────────────────────────────────────────────┐
│  好处 5: 技能按需渐进加载                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Prompt 中只列出技能元信息（名称、描述、路径）          │
│     <skill>                                                │
│         <name>code-review</name>                          │
│         <description>Automated code review workflow</description>│
│         <location>/mnt/skills/public/code-review/SKILL.md</location>│
│     </skill>                                               │
│                                                             │
│  2. Agent 遇到匹配场景时，读取技能文件                     │
│     → read_file("/mnt/skills/public/code-review/SKILL.md")│
│                                                             │
│  3. 按技能文件中的指令执行                                  │
│                                                             │
│  好处: 不需要把所有技能内容都放在 prompt 中                 │
│        大幅节省 Token，只在需要时加载                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.6 记忆上下文注入

```
┌─────────────────────────────────────────────────────────────┐
│  好处 6: 用户记忆个性化                                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  <memory>                                                  │
│  User Context:                                            │
│  - Work: Senior engineer at ByteDance                      │
│  - Preferences: Prefers concise responses                  │
│                                                             │
│  History:                                                  │
│  - Recent: Explored LangGraph middleware                   │
│  - Earlier: Built similar agent systems                     │
│                                                             │
│  Facts:                                                    │
│  - [preference | 0.95] Uses Python as primary language   │
│  </memory>                                                 │
│                                                             │
│  Agent 可以感知用户背景，提供个性化服务                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.7 子代理并发控制

```
┌─────────────────────────────────────────────────────────────┐
│  好处 7: 子代理并发硬限制                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  apply_prompt_template(subagent_enabled=True, max_concurrent_subagents=3)
│                                                             │
│  → 子代理系统块包含:                                       │
│    "⛔ HARD CONCURRENCY LIMIT: MAXIMUM 3 `task` CALLS"   │
│                                                             │
│  → critical_reminders 提醒:                                │
│    "HARD LIMIT: max 3 `task` calls per response."         │
│                                                             │
│  → thinking_style 指导:                                    │
│    "DECOMPOSITION CHECK: If count > 3, plan batches..."    │
│                                                             │
│  防止 Agent 无限制调用子代理导致资源耗尽                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 9. 完整 Prompt 示例

```
<role>
You are DeerFlow 2.0, an open-source super agent.
</role>

<soul>
You are a thoughtful and precise AI assistant that always verifies information.
</soul>

<memory>
User Context:
- Work: Senior engineer at ByteDance
- Current Focus: Debugging MCP tool integration

Facts:
- [knowledge | 0.95] Expert in LangChain framework
</memory>

<thinking_style>
- Think concisely and strategically about the user's request BEFORE taking action
- Break down the task: What is clear? What is ambiguous? What is missing?
- **PRIORITY CHECK**: If anything is unclear, you MUST ask for clarification FIRST
- DECOMPOSITION CHECK: If count > 3, plan batches of ≤3.
</thinking_style>

<clarification_system>
**WORKFLOW PRIORITY: CLARIFY → PLAN → ACT**
1. FIRST: Analyze the request in thinking
2. SECOND: If clarification is needed, call `ask_clarification` IMMEDIATELY
3. THIRD: Only after clarifications resolved, proceed with planning
...
</clarification_system>

<skill_system>
You have access to skills that provide optimized workflows.

<available_skills>
    <skill>
        <name>github-deep-research</name>
        <description>Deep research on GitHub repositories</description>
        <location>/mnt/skills/public/github-deep-research/SKILL.md</location>
    </skill>
</available_skills>
</skill_system>

<available-deferred-tools>
mcp_github_issues
mcp_github_commits
</available-deferred-tools>

<subagent_system>
**🚀 SUBAGENT MODE ACTIVE - DECOMPOSE, DELEGATE, SYNTHESIZE**

⛔ HARD CONCURRENCY LIMIT: MAXIMUM 3 `task` CALLS PER RESPONSE.
...
</subagent_system>

<working_directory existed="true">
- User uploads: `/mnt/user-data/uploads`
- User workspace: `/mnt/user-data/workspace`
- Output files: `/mnt/user-data/outputs`

**ACP Agent Tasks:**
- ACP agents run in their own workspace — NOT in `/mnt/user-data/`
</working_directory>

<response_style>
- Clear and Concise: Avoid over-formatting unless requested
- Natural Tone: Use paragraphs and prose, not bullet points by default
</response_style>

<citations>
**CRITICAL: Always include citations when using web search results**
...
</citations>

<critical_reminders>
- **Clarification First**: ALWAYS clarify unclear/missing/ambiguous requirements BEFORE starting work
- **Orchestrator Mode**: HARD LIMIT: max 3 `task` calls per response.
- Skill First: Always load the relevant skill before starting **complex** tasks.
</critical_reminders>

<current_date>2026-03-31, Tuesday</current_date>
```

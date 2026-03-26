# 06 - Phase 6: 进阶主题

> 预计时间: 3-5 天
> 
> 本阶段目标：理解 DeerFlow 的进阶特性：Memory System、MCP 协议、IM Channels

---

## 6.1 Memory System

**位置**: `backend/packages/harness/deerflow/agents/memory/`

### 什么是 Memory System？

Memory System 是 DeerFlow 的**跨会话持久化记忆系统**，能够：
- 自动从对话中提取关键信息
- 跨会话记住用户偏好
- 降低 LLM 调用频率

### 架构

```
┌──────────────────────────────────────────────────────┐
│                   Memory System                       │
│                                                       │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐ │
│  │ Extraction  │ → │    Queue    │ → │   Updater   │ │
│  │  提取器      │   │   队列      │   │   更新器     │ │
│  └─────────────┘   └─────────────┘   └─────────────┘ │
│         ↑                                    ↓         │
│         └────────────── Memory Store ←───────┘         │
│                                                       │
│              ↓ 注入到系统提示词                         │
│       ┌─────────────┐                                │
│       │ Lead Agent   │                                │
│       └─────────────┘                                │
└──────────────────────────────────────────────────────┘
```

### 核心文件

| 文件 | 作用 |
|------|------|
| `extraction.py` | 从对话中提取关键信息 |
| `queue.py` | 记忆队列管理 |
| `updater.py` | 记忆更新逻辑 |
| `prompts.py` | 记忆相关提示词 |

### 提取器

```python
# backend/packages/harness/deerflow/agents/memory/extraction.py

def extract_memory(messages: list[BaseMessage]) -> dict[str, Any]:
    """从对话历史中提取关键信息"""
    
    prompt = f"""
从以下对话中提取关键信息：

{messages}

提取以下类型的记忆：
1. 用户偏好（喜欢什么、不喜欢什么）
2. 重要事实（姓名、工作、位置等）
3. 正在进行的事项
4. 特殊要求或约束

以 JSON 格式返回：
{{
    "preferences": {{...}},
    "facts": {{...}},
    "tasks": [...],
    "constraints": [...]
}}
"""
    
    response = llm.invoke(prompt)
    return parse_json(response)
```

### 记忆注入

```python
# backend/packages/harness/deerflow/agents/memory/updater.py

def format_memory_for_injection(memory_data: dict) -> str:
    """格式化记忆用于注入到提示词"""
    
    return f"""
<memory>
## User Preferences
{memory_data.get('preferences', {})}

## Important Facts
{memory_data.get('facts', {})}

## Ongoing Tasks
{memory_data.get('tasks', [])}

## Constraints
{memory_data.get('constraints', [])}
</memory>
"""
```

---

## 6.2 MCP (Model Context Protocol)

**位置**: `backend/packages/harness/deerflow/mcp/`

### 什么是 MCP？

MCP 是 **Model Context Protocol** 的缩写，是一种**第三方工具集成协议**。通过 MCP，DeerFlow 可以调用外部工具服务器。

### MCP 架构

```
┌─────────────┐         ┌─────────────────┐
│  DeerFlow   │ ←──────→ │   MCP Server    │
│   Agent     │  MCP     │  (外部工具服务)  │
└─────────────┘         └─────────────────┘
                              ↑
                              │
                    ┌──────────────┐
                    │   Tools      │
                    │ (文件系统、   │
                    │  数据库等)   │
                    └──────────────┘
```

### MCP 配置

```json
// extensions_config.json
{
  "mcp_servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {}
    },
    {
      "name": "github",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "xxx"
      }
    }
  ]
}
```

### MCP 工具调用流程

```
1. Agent 需要使用 MCP 工具
   ↓
2. 向 MCP Server 发送请求
   ↓
3. MCP Server 执行工具
   ↓
4. 返回结果给 Agent
```

### OAuth 支持

```python
# MCP 支持 OAuth 认证流程
class MCPOAuthProvider:
    """MCP OAuth 提供者"""
    
    def get_access_token(self) -> str:
        """获取访问令牌"""
        # 支持 client_credentials 和 refresh_token 模式
        pass
    
    def refresh_token(self) -> str:
        """刷新令牌"""
        pass
```

---

## 6.3 IM Channels

**位置**: `backend/app/channels/`

### 支持的平台

| 平台 | 协议 | 文件 |
|------|------|------|
| Telegram | Bot API (Long Polling) | `telegram.py` |
| Slack | Socket Mode | `slack.py` |
| Feishu/Lark | WebSocket | `feishu.py` |

### Channel 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      IM Platform                             │
│  (Telegram / Slack / Feishu)                                │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                    Channel Manager                           │
│                   (channels/manager.py)                      │
│                                                              │
│  - 统一消息格式                                              │
│  - 会话管理                                                   │
│  - 事件分发                                                   │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────┐
│                    DeerFlow Agent                            │
└─────────────────────────────────────────────────────────────┘
```

### Telegram Bot

```python
# backend/app/channels/telegram.py

class TelegramBot:
    """Telegram Bot 集成"""
    
    def __init__(self, token: str):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
    
    async def start(self):
        """启动 Bot (Long Polling)"""
        offset = 0
        while True:
            updates = await self.get_updates(offset)
            for update in updates:
                await self.handle_update(update)
                offset = update["update_id"] + 1
    
    async def handle_update(self, update: dict):
        """处理更新"""
        message = update["message"]
        chat_id = message["chat"]["id"]
        text = message["text"]
        
        # 转发给 Agent
        response = await agent.process_message(text)
        
        # 发送回复
        await self.send_message(chat_id, response)
```

### Slack Bot

```python
# backend/app/channels/slack.py

class SlackBot:
    """Slack Bot 集成 (Socket Mode)"""
    
    def __init__(self, bot_token: str, app_token: str):
        self.bot_token = bot_token
        self.app_token = app_token
        self.socket = None
    
    async def start(self):
        """启动 Socket Mode"""
        from slack_sdk.socket_mode import SocketModeClient
        
        self.socket = SocketModeClient(
            app_token=self.app_token,
            web_client=WebClient(token=self.bot_token),
        )
        
        self.socket.socket_mode_request_listeners.append(
            self.handle_event
        )
        await self.socket.connect()
    
    async def handle_event(self, client, event):
        """处理 Slack 事件"""
        if event["type"] == "message":
            await agent.process_message(event["text"])
```

### Feishu Bot

```python
# backend/app/channels/feishu.py

class FeishuBot:
    """飞书/Lark Bot 集成 (WebSocket)"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.ws_client = None
    
    async def start(self):
        """启动 WebSocket 连接"""
        from lark_oapi.adapter.websocket import WebSocketClient
        
        self.ws_client = WebSocketClient(
            self.app_id,
            self.app_secret,
        )
        
        self.ws_client.event_register(self.handle_event)
        await self.ws_client.start()
```

---

## 6.4 Guardrails 系统

**位置**: `backend/packages/harness/deerflow/guardrails/`

### 什么是 Guardrails？

Guardrails 是**安全护栏系统**，用于：
- 内容过滤
- 输入验证
- 输出检查

### 内置 Provider

```python
# backend/packages/harness/deerflow/guardrails/builtin.py

class AllowlistProvider:
    """白名单护栏"""
    
    def validate(self, content: str) -> bool:
        """检查内容是否在白名单中"""
        return content in self.allowlist

class BlocklistProvider:
    """黑名单护栏"""
    
    def validate(self, content: str) -> bool:
        """检查内容是否包含敏感词"""
        return not any(word in content.lower() 
                      for word in self.blocklist)
```

### Guardrails 配置

```yaml
# config.yaml
guardrails:
  enabled: true
  providers:
    - use: deerflow.guardrails.builtin:AllowlistProvider
      config:
        allowlist:
          - safe_word1
          - safe_word2
    - use: deerflow.guardrails.builtin:BlocklistProvider
      config:
        blocklist:
          - sensitive_word1
```

---

## 6.5 Checkpointing

### 什么是 Checkpointing？

Checkpointing 是 LangGraph 的**状态保存/恢复机制**，允许：
- 中断 Agent 执行
- 保存状态
- 恢复执行

### DeerFlow 中的用途

| 场景 | 作用 |
|------|------|
| Human-in-the-Loop | 保存状态，等待人工确认 |
| 超时处理 | 中断后恢复 |
| 错误恢复 | 出错后可回滚 |

### Checkpointer 配置

```yaml
# config.yaml
checkpointer:
  use: langgraph.checkpoint.memory:MemorySaver
  # 或使用数据库
  # use: langgraph.checkpoint.postgres:PostgresSaver
```

---

## 6.6 学习目标检查清单

- [ ] 理解 Memory System 的架构
- [ ] 理解 MCP 协议的作用
- [ ] 理解 IM Channels 的三种集成方式
- [ ] 理解 Guardrails 机制
- [ ] 理解 Checkpointing 用途

---

## 6.7 相关文件

| 组件 | 文件位置 |
|------|----------|
| Memory | `packages/harness/deerflow/agents/memory/` |
| MCP | `packages/harness/deerflow/mcp/` |
| Channels | `app/channels/` |
| Guardrails | `packages/harness/deerflow/guardrails/` |

---

## 6.8 下一步

**[07-Phase 7: 实战项目与简历准备](./07-phase7-project-resume.md)**

学习如何通过 DeerFlow 做实战项目，并准备简历。

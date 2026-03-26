# MCP 工具与鉴权架构详解

## 1. 概述

DeerFlow 使用 **Model Context Protocol (MCP)** 来扩展 Agent 的工具能力。MCP 允许通过标准化的协议连接外部服务（如 GitHub、文件系统、数据库等），为 LLM Agent 提供丰富的工具调用能力。

## 2. 配置文件

### 2.1 配置文件位置（优先级从高到低）

1. `config_path` 参数
2. `DEER_FLOW_EXTENSIONS_CONFIG_PATH` 环境变量
3. `./extensions_config.json`
4. `../extensions_config.json`
5. `./mcp_config.json`（向后兼容）
6. `../mcp_config.json`（向后兼容）

源码位置：`deerflow/config/extensions_config.py:70-117`

### 2.2 配置结构

```json
{
  "mcpServers": {
    "server-name": {
      "enabled": true,
      "type": "stdio | sse | http",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
      "url": "https://api.example.com/mcp",
      "headers": {"Authorization": "Bearer $TOKEN"},
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.example.com/oauth/token",
        "grant_type": "client_credentials | refresh_token",
        "client_id": "client-id",
        "client_secret": "$CLIENT_SECRET",
        "refresh_token": "$REFRESH_TOKEN",
        "scope": "read write",
        "audience": "https://api.example.com",
        "token_field": "access_token",
        "token_type_field": "token_type",
        "expires_in_field": "expires_in",
        "default_token_type": "Bearer",
        "refresh_skew_seconds": 60,
        "extra_token_params": {}
      },
      "description": "Human-readable description"
    }
  },
  "skills": {
    "skill-name": {"enabled": true}
  }
}
```

源码位置：`deerflow/config/extensions_config.py:11-67`

### 2.3 环境变量替换

配置文件中支持 `$VAR` 语法引用环境变量：

```python
# deerflow/config/extensions_config.py:147-175
env: {"GITHUB_TOKEN": "$GITHUB_TOKEN"}  # $GITHUB_TOKEN 会被替换为实际环境变量值
```

## 3. 核心数据结构

### 3.1 McpOAuthConfig

```python
# deerflow/config/extensions_config.py:11-31
class McpOAuthConfig(BaseModel):
    enabled: bool = True
    token_url: str  # OAuth token endpoint
    grant_type: Literal["client_credentials", "refresh_token"] = "client_credentials"
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    scope: str | None = None
    audience: str | None = None
    token_field: str = "access_token"           # token 响应中的字段名
    token_type_field: str = "token_type"        # token 类型字段名
    expires_in_field: str = "expires_in"        # 过期时间字段名
    default_token_type: str = "Bearer"
    refresh_skew_seconds: int = 60              # 提前多少秒刷新
    extra_token_params: dict[str, str] = {}    # 额外参数
```

### 3.2 McpServerConfig

```python
# deerflow/config/extensions_config.py:34-46
class McpServerConfig(BaseModel):
    enabled: bool = True
    type: str = "stdio"                        # stdio | sse | http
    command: str | None = None                 # stdio 命令
    args: list[str] = []                       # 命令参数
    env: dict[str, str] = {}                   # 环境变量
    url: str | None = None                     # sse/http URL
    headers: dict[str, str] = {}               # HTTP headers
    oauth: McpOAuthConfig | None = None        # OAuth 配置
    description: str = ""
```

## 4. MCP 工具加载流程

### 4.1 整体调用链

```
get_available_tools()
    │
    ├──► ExtensionsConfig.from_file()           # 读取配置
    │    deerflow/config/extensions_config.py:120
    │
    ├──► get_cached_mcp_tools()                # 获取缓存的工具
    │    deerflow/mcp/cache.py:82
    │         │
    │         ├──► _is_cache_stale()           # 检查配置 mtime
    │         │    deerflow/mcp/cache.py:31
    │         │
    │         └──► initialize_mcp_tools()      # 懒加载初始化
    │              deerflow/mcp/cache.py:56
    │                   │
    │                   └──► get_mcp_tools()  # 加载 MCP 工具
    │                        deerflow/mcp/tools.py:56
    │                             │
    │                             ├──► ExtensionsConfig.from_file()
    │                             ├──► build_servers_config()
    │                             ├──► get_initial_oauth_headers()
    │                             ├──► build_oauth_tool_interceptor()
    │                             └──► MultiServerMCPClient.get_tools()
```

### 4.2 工具加载入口

```python
# deerflow/tools/tools.py:64-98
mcp_tools = []
if include_mcp:
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.cache import get_cached_mcp_tools

    extensions_config = ExtensionsConfig.from_file()
    if extensions_config.get_enabled_mcp_servers():
        mcp_tools = get_cached_mcp_tools()

        # 当 tool_search 启用时，注册到延迟注册表
        if config.tool_search.enabled:
            registry = DeferredToolRegistry()
            for t in mcp_tools:
                registry.register(t)
            set_deferred_registry(registry)
            builtin_tools.append(tool_search_tool)
```

### 4.3 核心加载函数

```python
# deerflow/mcp/tools.py:56-113
async def get_mcp_tools() -> list[BaseTool]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    # 1. 读取最新配置（每次都从文件读取）
    extensions_config = ExtensionsConfig.from_file()
    servers_config = build_servers_config(extensions_config)

    # 2. 获取初始 OAuth headers
    initial_oauth_headers = await get_initial_oauth_headers(extensions_config)
    for server_name, auth_header in initial_oauth_headers.items():
        if server_name not in servers_config:
            continue
        if servers_config[server_name].get("transport") in ("sse", "http"):
            servers_config[server_name].setdefault("headers", {})["Authorization"] = auth_header

    # 3. 构建 OAuth 拦截器
    tool_interceptors = []
    oauth_interceptor = build_oauth_tool_interceptor(extensions_config)
    if oauth_interceptor is not None:
        tool_interceptors.append(oauth_interceptor)

    # 4. 创建 MCP 客户端并获取工具
    client = MultiServerMCPClient(
        servers_config,
        tool_interceptors=tool_interceptors,
        tool_name_prefix=True
    )
    tools = await client.get_tools()

    # 5. 为异步工具添加同步包装器
    for tool in tools:
        if getattr(tool, "func", None) is None and getattr(tool, "coroutine", None) is not None:
            tool.func = _make_sync_tool_wrapper(tool.coroutine, tool.name)

    return tools
```

## 5. 服务参数构建

### 5.1 stdio 传输

```python
# deerflow/mcp/client.py:11-32
def build_server_params(server_name: str, config: McpServerConfig) -> dict[str, Any]:
    transport_type = config.type or "stdio"
    params: dict[str, Any] = {"transport": transport_type}

    if transport_type == "stdio":
        params["command"] = config.command
        params["args"] = config.args
        if config.env:
            params["env"] = config.env
    elif transport_type in ("sse", "http"):
        params["url"] = config.url
        if config.headers:
            params["headers"] = config.headers

    return params
```

### 5.2 sse/http 传输

```python
# deerflow/mcp/client.py:32-40
elif transport_type in ("sse", "http"):
    params["url"] = config.url
    if config.headers:
        params["headers"] = config.headers
```

## 6. OAuth 鉴权流程

### 6.1 OAuthTokenManager

```python
# deerflow/mcp/oauth.py:25-119
class OAuthTokenManager:
    def __init__(self, oauth_by_server: dict[str, McpOAuthConfig]):
        self._oauth_by_server = oauth_by_server
        self._tokens: dict[str, _OAuthToken] = {}      # token 缓存
        self._locks: dict[str, asyncio.Lock] = {}       # 每个服务器的锁

    async def get_authorization_header(self, server_name: str) -> str | None:
        oauth = self._oauth_by_server.get(server_name)
        if not oauth:
            return None

        # 检查缓存
        token = self._tokens.get(server_name)
        if token and not self._is_expiring(token, oauth):
            return f"{token.token_type} {token.access_token}"

        # 双检锁
        lock = self._locks[server_name]
        async with lock:
            token = self._tokens.get(server_name)
            if token and not self._is_expiring(token, oauth):
                return f"{token.token_type} {token.access_token}"

            # 获取新 token
            fresh = await self._fetch_token(oauth)
            self._tokens[server_name] = fresh
            return f"{fresh.token_type} {fresh.access_token}"
```

### 6.2 Token 获取

```python
# deerflow/mcp/oauth.py:72-119
async def _fetch_token(self, oauth: McpOAuthConfig) -> _OAuthToken:
    data: dict[str, str] = {
        "grant_type": oauth.grant_type,
        **oauth.extra_token_params,
    }

    if oauth.scope:
        data["scope"] = oauth.scope
    if oauth.audience:
        data["audience"] = oauth.audience

    # client_credentials 模式
    if oauth.grant_type == "client_credentials":
        data["client_id"] = oauth.client_id
        data["client_secret"] = oauth.client_secret

    # refresh_token 模式
    elif oauth.grant_type == "refresh_token":
        data["refresh_token"] = oauth.refresh_token
        if oauth.client_id:
            data["client_id"] = oauth.client_id
        if oauth.client_secret:
            data["client_secret"] = oauth.client_secret

    # 发送 token 请求
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(oauth.token_url, data=data)
        response.raise_for_status()
        payload = response.json()

    # 解析响应
    access_token = payload.get(oauth.token_field)
    token_type = str(payload.get(oauth.token_type_field, oauth.default_token_type))
    expires_in = int(payload.get(oauth.expires_in_field, 3600))
    expires_at = datetime.now(UTC) + timedelta(seconds=max(expires_in, 1))

    return _OAuthToken(access_token=access_token, token_type=token_type, expires_at=expires_at)
```

### 6.3 OAuth 拦截器

```python
# deerflow/mcp/oauth.py:122-137
def build_oauth_tool_interceptor(extensions_config: ExtensionsConfig) -> Any | None:
    token_manager = OAuthTokenManager.from_extensions_config(extensions_config)
    if not token_manager.has_oauth_servers():
        return None

    async def oauth_interceptor(request: Any, handler: Any) -> Any:
        header = await token_manager.get_authorization_header(request.server_name)
        if not header:
            return await handler(request)

        updated_headers = dict(request.headers or {})
        updated_headers["Authorization"] = header
        return await handler(request.override(headers=updated_headers))

    return oauth_interceptor
```

## 7. 缓存机制

### 7.1 缓存结构

```python
# deerflow/mcp/cache.py:11-14
_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
_initialization_lock = asyncio.Lock()
_config_mtime: float | None = None  # 配置文件修改时间
```

### 7.2 基于 mtime 的缓存失效

```python
# deerflow/mcp/cache.py:31-53
def _is_cache_stale() -> bool:
    global _config_mtime

    if not _cache_initialized:
        return False

    current_mtime = _get_config_mtime()

    # 无法获取 mtime 时不失效
    if _config_mtime is None or current_mtime is None:
        return False

    # 配置修改时间变化则失效
    if current_mtime > _config_mtime:
        logger.info(f"MCP config file has been modified (mtime: {_config_mtime} -> {current_mtime}), cache is stale")
        return True

    return False
```

### 7.3 懒加载初始化

```python
# deerflow/mcp/cache.py:82-126
def get_cached_mcp_tools() -> list[BaseTool]:
    global _cache_initialized

    # 检查缓存是否过期
    if _is_cache_stale():
        reset_mcp_tools_cache()

    if not _cache_initialized:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在线程池中运行初始化
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, initialize_mcp_tools())
                    future.result()
            else:
                loop.run_until_complete(initialize_mcp_tools())
        except RuntimeError:
            asyncio.run(initialize_mcp_tools())
        except Exception as e:
            logger.error(f"Failed to lazy-initialize MCP tools: {e}")
            return []

    return _mcp_tools_cache or []
```

## 8. 同步工具包装器

MCP 工具可能是异步的，但 DeerFlow 的某些客户端是同步调用的。`_make_sync_tool_wrapper` 解决了这个问题：

```python
# deerflow/mcp/tools.py:25-53
def _make_sync_tool_wrapper(coro: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop is not None and loop.is_running():
                # 在线程池中运行协程
                future = _SYNC_TOOL_EXECUTOR.submit(asyncio.run, coro(*args, **kwargs))
                return future.result()
            else:
                return asyncio.run(coro(*args, **kwargs))
        except Exception as e:
            logger.error(f"Error invoking MCP tool '{tool_name}' via sync wrapper: {e}", exc_info=True)
            raise

    return sync_wrapper
```

## 9. API 端点

### 9.1 获取 MCP 配置

```
GET /api/mcp/config
```

返回所有 MCP 服务器配置（包括禁用的）：

```json
{
  "mcp_servers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "ghp_xxx"},
      "description": "GitHub MCP server"
    }
  }
}
```

源码位置：`backend/app/gateway/routers/mcp.py:66-95`

### 9.2 更新 MCP 配置

```
PUT /api/mcp/config
```

请求体：

```json
{
  "mcp_servers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}
    }
  }
}
```

响应：返回更新后的完整配置。

注意：Gateway API 和 LangGraph Server 是独立进程。配置更新后，Gateway API 立即生效，但 LangGraph Server 通过 `mtime` 检测配置文件变化自动重新加载。

源码位置：`backend/app/gateway/routers/mcp.py:98-169`

## 10. 完整配置示例

### 10.1 stdio 类型（GitHub）

```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "$GITHUB_TOKEN"
      },
      "description": "GitHub operations via MCP"
    }
  }
}
```

### 10.2 HTTP 类型 + OAuth

```json
{
  "mcpServers": {
    "secure-api": {
      "enabled": true,
      "type": "http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "X-API-Key": "$API_KEY"
      },
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.example.com/oauth/token",
        "grant_type": "client_credentials",
        "client_id": "$OAUTH_CLIENT_ID",
        "client_secret": "$OAUTH_CLIENT_SECRET",
        "scope": "read write",
        "refresh_skew_seconds": 60
      },
      "description": "Secure API with OAuth authentication"
    }
  }
}
```

### 10.3 SSE 类型 + OAuth

```json
{
  "mcpServers": {
    "eventsource": {
      "enabled": true,
      "type": "sse",
      "url": "https://events.example.com/mcp",
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.example.com/oauth/token",
        "grant_type": "refresh_token",
        "refresh_token": "$REFRESH_TOKEN",
        "client_id": "$OAUTH_CLIENT_ID"
      }
    }
  }
}
```

## 11. 关键设计决策

### 11.1 为什么每次都从文件读取配置？

```python
# deerflow/mcp/tools.py:68-72
# NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
# to always read the latest configuration from disk. This ensures that changes
# made through the Gateway API (which runs in a separate process) are immediately
# reflected when initializing MCP tools.
extensions_config = ExtensionsConfig.from_file()
```

Gateway API 和 LangGraph Server 是两个独立进程。Gateway API 通过 API 更新配置，但 LangGraph Server 不知道配置已更改。通过每次从文件读取 + mtime 检测，可以确保配置变更被自动感知。

### 11.2 为什么需要同步包装器？

MCP 工具可能是异步的，但 DeerFlow 的某些组件（如 `deerflow client`）是同步调用的。`_make_sync_tool_wrapper` 在已有事件循环时使用线程池执行协程，避免嵌套事件循环问题。

### 11.3 OAuth token 缓存策略

- 使用 `refresh_skew_seconds` 提前刷新，避免竞态
- 双检锁模式确保线程安全
- `token_type` 默认为 "Bearer"

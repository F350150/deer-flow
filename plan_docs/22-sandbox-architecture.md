# Sandbox 完整架构详解

## 1. 概述

本文档详细解析 DeerFlow 中 Sandbox（沙箱）系统的完整架构，重点讲解 `before_agent` 和 `after_agent` 生命周期钩子在 Sandbox 生命周期管理中的作用。

---

## 2. Sandbox 核心组件

### 2.1 核心文件结构

```
backend/packages/harness/deerflow/
├── sandbox/
│   ├── sandbox.py                    # 抽象基类 Sandbox
│   ├── sandbox_provider.py            # 抽象基类 SandboxProvider + 单例管理
│   ├── tools.py                      # 内置工具 (bash, ls, read_file, write_file)
│   ├── middleware.py                 # SandboxMiddleware ⭐
│   ├── exceptions.py                 # 异常定义
│   ├── local/
│   │   ├── local_sandbox.py           # 本地执行实现
│   │   └── local_sandbox_provider.py  # 本地 Provider
│   └── community/
│       └── aio_sandbox/
│           ├── aio_sandbox.py         # AIO Sandbox 实现
│           ├── aio_sandbox_provider.py # AIO Sandbox Provider ⭐
│           ├── backend.py             # 后端抽象
│           ├── local_backend.py       # 本地 Docker 容器后端
│           └── remote_backend.py       # K8s/远程后端
```

### 2.2 Sandbox 抽象基类

```python
# sandbox/sandbox.py
class Sandbox(ABC):
    """所有 Sandbox 实现的抽象基类"""
    
    @abstractmethod
    def execute_command(self, command: str) -> str:
        """在沙箱中执行 bash 命令"""
        pass
    
    @abstractmethod
    def read_file(self, path: str) -> str:
        """读取文件内容"""
        pass
    
    @abstractmethod
    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """列出目录内容"""
        pass
    
    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """写入文件"""
        pass
```

### 2.3 SandboxProvider 抽象基类

```python
# sandbox/sandbox_provider.py
class SandboxProvider(ABC):
    """Sandbox 实例的工厂和生命周期管理器"""
    
    @abstractmethod
    def acquire(self, thread_id: str | None = None) -> str:
        """获取沙箱实例，返回 sandbox_id"""
        pass
    
    @abstractmethod
    def get(self, sandbox_id: str) -> Sandbox | None:
        """根据 ID 获取沙箱实例"""
        pass
    
    @abstractmethod
    def release(self, sandbox_id: str) -> None:
        """释放沙箱（放入暖池复用）"""
        pass
```

---

## 3. before_agent 和 after_agent 详解

### 3.1 AgentMiddleware 生命周期钩子

`AgentMiddleware` 是 LangChain 定义的 Agent 执行拦截器基类，提供多个生命周期钩子：

| 阶段 | 方法 | 作用 |
|------|------|------|
| Agent 执行前 | `before_agent` / `abefore_agent` | 初始化资源、设置状态 |
| 模型调用前 | `before_model` / `abefore_model` | 修改请求/消息 |
| 模型调用后 | `after_model` / `aafter_model` | 处理响应 |
| 工具调用时 | `wrap_tool_call` / `awrap_tool_call` | 拦截工具执行 |
| Agent 执行后 | `after_agent` / `aafter_agent` | 清理资源 |

### 3.2 中间件调用顺序

多个中间件按数组顺序组合，**形成嵌套结构**：

```
middlewares = [
    MiddlewareA,  # [0] 最外层 - 先进入，后退出
    MiddlewareB,  # [1] 中间层
    MiddlewareC,  # [2] 最内层 - 后进入，先退出
]
```

执行流程：

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent 执行流程                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ MiddlewareA.before_agent()                             │   │
│   │   │                                                     │   │
│   │   ▼                                                     │   │
│   │   ┌─────────────────────────────────────────────────┐   │   │
│   │   │ MiddlewareB.before_agent()                        │   │   │
│   │   │   │                                              │   │   │
│   │   │   ▼                                              │   │   │
│   │   │   ┌──────────────────────────────────────────┐   │   │   │
│   │   │   │ MiddlewareC.before_agent()               │   │   │   │
│   │   │   │   │                                     │   │   │   │
│   │   │   │   ▼                                     │   │   │   │
│   │   │   │   [Model + Tools 执行]                   │   │   │   │
│   │   │   │   │                                     │   │   │   │
│   │   │   │   ▼                                     │   │   │   │
│   │   │   │ MiddlewareC.after_agent()                │   │   │   │
│   │   │   └──────────────────────────────────────────┘   │   │   │
│   │   │   │                                              │   │   │
│   │   │   ▼                                              │   │   │
│   │   │ MiddlewareB.after_agent()                         │   │   │
│   │   └─────────────────────────────────────────────────┘   │   │
│   │   │                                                     │   │
│   │   ▼                                                     │   │
│   │ MiddlewareA.after_agent()                                │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. SandboxMiddleware 详解

### 4.1 源码分析

```python
# sandbox/middleware.py

class SandboxMiddleware(AgentMiddleware[SandboxMiddlewareState]):
    """管理 Sandbox 生命周期"""
    
    state_schema = SandboxMiddlewareState
    
    def __init__(self, lazy_init: bool = True):
        """
        Args:
            lazy_init: 
                - True (默认): 延迟到第一个工具调用时才获取 sandbox
                - False: 在 before_agent 时立即获取 sandbox
        """
        super().__init__()
        self._lazy_init = lazy_init
    
    def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        """在 Agent 执行前调用"""
        
        # lazy_init=True 时跳过，延迟到工具调用时
        if self._lazy_init:
            return super().before_agent(state, runtime)
        
        # lazy_init=False 时立即获取 sandbox
        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = (runtime.context or {}).get("thread_id")
            if thread_id is None:
                return super().before_agent(state, runtime)
            
            # 从 Provider 获取 sandbox
            sandbox_id = self._acquire_sandbox(thread_id)
            return {"sandbox": {"sandbox_id": sandbox_id}}
        
        return super().before_agent(state, runtime)
    
    def after_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        """在 Agent 执行后调用 - 释放 Sandbox"""
        
        # 优先从 state 获取 sandbox_id
        sandbox = state.get("sandbox")
        if sandbox is not None:
            sandbox_id = sandbox["sandbox_id"]
            logger.info(f"Releasing sandbox {sandbox_id}")
            get_sandbox_provider().release(sandbox_id)
            return None
        
        # 备用：从 runtime.context 获取
        if (runtime.context or {}).get("sandbox_id") is not None:
            sandbox_id = runtime.context.get("sandbox_id")
            logger.info(f"Releasing sandbox {sandbox_id} from context")
            get_sandbox_provider().release(sandbox_id)
            return None
        
        return super().after_agent(state, runtime)
```

### 4.2 before_agent 执行时机详解

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          before_agent 执行时机                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  用户请求                                                                   │
│      │                                                                      │
│      ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Agent.stream() / invoke()                                            │    │
│  │     │                                                               │    │
│  │     ▼                                                               │    │
│  │ ┌───────────────────────────────────────────────────────────────┐  │    │
│  │ │ 遍历 middlewares，调用 before_agent()                           │  │    │
│  │ └───────────────────────────────────────────────────────────────┘  │    │
│  │     │                                                               │    │
│  │     ▼                                                               │    │
│  │ [Agent 执行: Model 调用 Tools]                                       │    │
│  │     │                                                               │    │
│  │     ▼                                                               │    │
│  │ ┌───────────────────────────────────────────────────────────────┐  │    │
│  │ │ 遍历 middlewares，调用 after_agent() (逆序)                    │  │    │
│  │ └───────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**懒加载模式 (`lazy_init=True`)**:

```python
# 第一次工具调用时
tool = bash_tool(...)
    │
    ▼
ensure_sandbox_initialized(runtime)
    │
    ├── 检查 runtime.state["sandbox"] 是否存在
    │       │
    │       ├── 已存在 → 直接返回
    │       │
    │       └── 不存在 → 调用 provider.acquire(thread_id)
    │
    ▼
sandbox_id = provider.acquire(thread_id)
```

### 4.3 after_agent 执行时机详解

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          after_agent 执行时机                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Agent 完成所有处理后（正常/异常都会执行）                                     │
│      │                                                                      │
│      ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ for middleware in reversed(middlewares):                            │    │
│  │     middleware.after_agent(state, runtime)                          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  逆序执行是因为：                                                            │
│  - 中间件按 [A, B, C] 顺序定义                                               │
│  - before_agent 按 A→B→C 顺序执行（C 最内层最后执行）                         │
│  - after_agent 按 C→B→A 顺序执行（C 最内层最先执行）                          │
│  - 保证嵌套结构的正确清理顺序                                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**`release()` 不等于销毁**:

```python
# AioSandboxProvider.release() 实现
def release(self, sandbox_id: str) -> None:
    # 1. 从活跃字典移除
    self._sandboxes.pop(sandbox_id, None)
    
    # 2. 放入暖池（warm pool）- 容器继续运行
    if sandbox_id not in self._warm_pool:
        self._warm_pool[sandbox_id] = (info, time.time())
    
    # 容器保持运行，可快速复用
```

**暖池机制**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Sandbox 生命周期                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  acquire() ──────────────────────────────────────────────────────────────   │
│      │                                                                      │
│      │  ┌─────────────────────────────────────────────────────────────┐      │
│      │  │ Layer 1: 进程内缓存                                         │      │
│      │  │ if thread_id in _thread_sandboxes:                          │      │
│      │  │     return existing sandbox_id  # 快速路径                   │      │
│      │  └─────────────────────────────────────────────────────────────┘      │
│      │                                                                      │
│      │  ┌─────────────────────────────────────────────────────────────┐      │
│      │  │ Layer 2: 暖池复用                                            │      │
│      │  │ if sandbox_id in _warm_pool:                                │      │
│      │  │     reclaim from warm_pool  # 无冷启动                       │      │
│      │  └─────────────────────────────────────────────────────────────┘      │
│      │                                                                      │
│      │  ┌─────────────────────────────────────────────────────────────┐      │
│      │  │ Layer 3: 跨进程锁 + 创建新容器                               │      │
│      │  │ _backend.create() → Docker/K8s 创建容器                      │      │
│      │  └─────────────────────────────────────────────────────────────┘      │
│      │                                                                      │
│      ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Active Sandbox ←────────────────────── _sandboxes[sandbox_id]        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│      │                                                                      │
│      ▼                                                                      │
│  release() ─────────────────────────────────────────────────────────────   │
│      │                                                                      │
│      ▼                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Warm Pool (容器仍运行) ←────────────────── _warm_pool[sandbox_id]     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│      │                                                                      │
│      ├── 同一 thread 下次请求 → 从暖池快速复用                               │
│      │                                                                      │
│      └── 空闲超时 → 销毁容器                                               │
│                  │                                                         │
│                  ▼                                                         │
│              destroy()                                                      │
│                  │                                                         │
│                  ▼                                                         │
│              容器停止 + 删除资源                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 完整调用链

### 5.1 工具调用完整流程

```
用户: "帮我执行 ls /tmp"
    │
    ▼
Agent.stream() / invoke()
    │
    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ before_agent 阶段                                                          │
│                                                                            │
│ ThreadDataMiddleware.before_agent()                                        │
│   → 设置 thread_data (路径信息)                                            │
│                                                                            │
│ SandboxMiddleware.before_agent()                                           │
│   → lazy_init=True 时跳过，延迟到工具调用                                  │
└───────────────────────────────────────────────────────────────────────────┘
    │
    ▼
[Model 决定调用 bash_tool]
    │
    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ 工具执行阶段                                                               │
│                                                                            │
│ ToolErrorHandlingMiddleware.awrap_tool_call()                             │
│   → 捕获工具异常，转换为错误消息                                            │
│                                                                            │
│ bash_tool(runtime, command="ls /tmp")                                      │
│   │                                                                        │
│   ▼                                                                        │
│ ensure_sandbox_initialized(runtime)                                        │
│   │                                                                        │
│   ├── 检查 runtime.state["sandbox"]                                       │
│   │       │                                                               │
│   │       └── 不存在 → provider.acquire(thread_id)                         │
│   │               │                                                       │
│   │               ▼                                                       │
│   │           AioSandboxProvider.acquire(thread_id)                       │
│   │               │                                                       │
│   │               ├── 进程内缓存检查                                        │
│   │               ├── 暖池检查                                              │
│   │               └── 跨进程锁 → 创建新容器                                 │
│   │                                                                        │
│   ▼                                                                        │
│ sandbox.execute_command("ls /tmp")                                        │
│   │                                                                        │
│   ▼                                                                        │
│ AioSandbox.execute_command(command)                                       │
│   → HTTP POST {base_url}/execute {"command": "ls /tmp"}                   │
│   → 返回执行结果                                                           │
└───────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ after_agent 阶段                                                           │
│                                                                            │
│ MemoryMiddleware.after_agent()                                            │
│   → 队列化对话用于记忆更新                                                 │
│                                                                            │
│ SandboxMiddleware.after_agent()                                           │
│   → provider.release(sandbox_id)  # 放入暖池，不是销毁                      │
│                                                                            │
└───────────────────────────────────────────────────────────────────────────┘
    │
    ▼
返回结果给用户
```

### 5.2 关键函数详解

**ensure_sandbox_initialized()**:

```python
def ensure_sandbox_initialized(runtime: ToolRuntime) -> Sandbox:
    """确保 sandbox 已初始化，懒加载获取"""
    
    # 1. 检查是否已有 sandbox
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is not None:
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is not None:
            sandbox = get_sandbox_provider().get(sandbox_id)
            if sandbox is not None:
                return sandbox  # 复用已有
    
    # 2. 懒加载获取
    thread_id = runtime.context.get("thread_id")
    if thread_id is None:
        raise SandboxRuntimeError("Thread ID not available")
    
    # 3. 从 Provider 获取
    sandbox_id = get_sandbox_provider().acquire(thread_id)
    
    # 4. 保存到 runtime.state（跨工具调用复用）
    runtime.state["sandbox"] = {"sandbox_id": sandbox_id}
    
    return get_sandbox_provider().get(sandbox_id)
```

**AioSandboxProvider.acquire()**:

```python
def acquire(self, thread_id: str | None = None) -> str:
    """获取 sandbox，三层缓存机制"""
    
    # Layer 1: 进程内缓存（最快）
    if thread_id:
        with self._lock:
            if thread_id in self._thread_sandboxes:
                existing_id = self._thread_sandboxes[thread_id]
                if existing_id in self._sandboxes:
                    self._last_activity[existing_id] = time.time()
                    return existing_id
    
    # Layer 2: 暖池复用（无冷启动）
    if thread_id:
        sandbox_id = self._deterministic_sandbox_id(thread_id)
        with self._lock:
            if sandbox_id in self._warm_pool:
                info, _ = self._warm_pool.pop(sandbox_id)
                sandbox = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
                self._sandboxes[sandbox_id] = sandbox
                self._last_activity[sandbox_id] = time.time()
                self._thread_sandboxes[thread_id] = sandbox_id
                return sandbox_id
    
    # Layer 3: 跨进程锁 + 创建新容器
    if thread_id:
        return self._discover_or_create_with_lock(thread_id, sandbox_id)
    
    return self._create_sandbox(thread_id, str(uuid.uuid4())[:8])
```

---

## 6. Sandbox 与 Middleware 交互

### 6.1 Middleware 组合顺序

DeerFlow 的 Lead Agent 使用以下中间件顺序：

```python
# agent.py:208-265
def _build_middlewares(config, model_name, agent_name):
    middlewares = build_lead_runtime_middlewares(lazy_init=True)
    # build_lead_runtime_middlewares 返回:
    # [
    #     ThreadDataMiddleware(lazy_init=True),   # [0] 最外层
    #     SandboxMiddleware(lazy_init=True),       # [1]
    #     ToolErrorHandlingMiddleware(),           # [2] 最内层
    # ]
    
    # 以下按需添加...
    middlewares.append(SummarizationMiddleware())  # 上下文压缩
    middlewares.append(TodoListMiddleware())       # 任务列表
    middlewares.append(TokenUsageMiddleware())     # Token 统计
    middlewares.append(TitleMiddleware())           # 标题生成
    middlewares.append(MemoryMiddleware())          # 记忆更新
    middlewares.append(ViewImageMiddleware())       # 图片处理
    middlewares.append(SubagentLimitMiddleware())  # 子代理限制
    middlewares.append(LoopDetectionMiddleware())  # 循环检测
    middlewares.append(ClarificationMiddleware()) # 澄清请求
```

### 6.2 ThreadDataMiddleware.before_agent

```python
# thread_data_middleware.py

def before_agent(self, state: ThreadDataMiddlewareState, runtime: Runtime) -> dict | None:
    """准备线程数据目录"""
    
    thread_id = runtime.context.get("thread_id")
    
    if self._lazy_init:
        # 懒加载：只计算路径，不创建目录
        paths = self._get_thread_paths(thread_id)
    else:
        # 立即创建目录
        paths = self._create_thread_directories(thread_id)
    
    return {
        "thread_data": {
            **paths,
        }
    }
```

**注意**: `ThreadDataMiddleware` 必须在 `SandboxMiddleware` 之前，因为后者依赖 `thread_id` 来获取 sandbox。

---

## 7. 虚拟路径映射

### 7.1 路径映射规则

```
宿主机                              容器内 (AIO Sandbox)
────────────────────────────────────────────────────────────────
{base_dir}/threads/{thread_id}/user-data/workspace
                            →  /mnt/user-data/workspace
{base_dir}/threads/{thread_id}/user-data/uploads
                            →  /mnt/user-data/uploads
{base_dir}/threads/{thread_id}/user-data/outputs
                            →  /mnt/user-data/outputs
{skills_path}                →  /mnt/skills (只读)
{acp_workspace_dir}         →  /mnt/acp-workspace (只读)
```

### 7.2 本地开发时的 DooD 模式

当 DeerFlow 运行在 Docker 容器内时，使用 DooD (Docker-out-of-Docker) 模式：

```python
# aio_sandbox_provider.py

def _get_thread_mounts(thread_id: str) -> list[tuple[str, str, bool]]:
    """获取容器挂载配置"""
    
    # host_paths 使用 DEER_FLOW_HOST_BASE_DIR
    # 使得 host 侧的 Docker daemon 可以解析路径
    host_paths = Paths(base_dir=paths.host_base_dir)
    
    return [
        (str(host_paths.sandbox_work_dir(thread_id)), 
         f"{VIRTUAL_PATH_PREFIX}/workspace", False),
        # ...
    ]
```

---

## 8. 关键配置

### 8.1 config.yaml 中的 sandbox 配置

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  
  # AIO Sandbox 配置
  image: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
  port: 8080
  container_prefix: deer-flow-sandbox
  idle_timeout: 600  # 10分钟空闲后释放
  replicas: 3         # 最大并发容器数
  
  # 本地挂载卷
  mounts:
    - host_path: /path/on/host
      container_path: /path/in/container
      read_only: false
  
  # 环境变量
  environment:
    NODE_ENV: production
    API_KEY: $MY_API_KEY
  
  # K8s 模式配置
  provisioner_url: http://provisioner:8002  # 远程供应器模式
```

### 8.2 懒加载 vs 立即初始化

```python
# 懒加载 (lazy_init=True) - 默认
SandboxMiddleware(lazy_init=True)

# 行为:
# - before_agent(): 不获取 sandbox
# - 第一个工具调用时: ensure_sandbox_initialized() → acquire()
# - 优点: 如果没有工具调用，避免创建容器

# 立即初始化 (lazy_init=False)
SandboxMiddleware(lazy_init=False)

# 行为:
# - before_agent(): 立即 acquire()
# - 缺点: 即使不使用工具，也会创建容器
# - 适用场景: 需要在 agent 执行前确保容器就绪
```

---

## 9. 状态流转总结

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           状态流转图                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  runtime.state                    runtime.context                            │
│  ┌─────────────────────┐          ┌─────────────────────┐                   │
│  │ thread_data: {...}  │          │ thread_id: "abc123" │                   │
│  │ sandbox: None       │          │ sandbox_id: None    │                   │
│  └─────────────────────┘          └─────────────────────┘                   │
│           │                                │                                 │
│           │ before_agent()                 │ before_agent()                  │
│           ▼                                ▼                                 │
│  ┌─────────────────────┐          ┌─────────────────────┐                   │
│  │ thread_data: {...}  │          │ thread_id: "abc123" │                   │
│  │ sandbox: {sandbox_id}│         │ sandbox_id: "abc123"│ ← acquire()后     │
│  └─────────────────────┘          └─────────────────────┘                   │
│           │                                │                                 │
│           │ 工具调用...                     │ 工具调用...                      │
│           ▼                                ▼                                 │
│  ┌─────────────────────┐          ┌─────────────────────┐                   │
│  │ thread_data: {...}  │          │ thread_id: "abc123" │                   │
│  │ sandbox: {sandbox_id}│          │ sandbox_id: "abc123"│                   │
│  └─────────────────────┘          └─────────────────────┘                   │
│           │                                │                                 │
│           │ after_agent()                  │ after_agent()                   │
│           ▼                                ▼                                 │
│  ┌─────────────────────┐          ┌─────────────────────┐                   │
│  │ thread_data: {...}  │          │ thread_id: "abc123" │                   │
│  │ sandbox: {sandbox_id}│         │ sandbox_id: None    │ ← release()后     │
│  └─────────────────────┘          └─────────────────────┘                   │
│                                                                              │
│  provider._sandboxes:          provider._warm_pool:                          │
│  ┌─────────────────────┐       ┌─────────────────────┐                      │
│  │ sandbox_id: Sandbox │       │ sandbox_id: (info,ts)│                      │
│  └─────────────────────┘       └─────────────────────┘                      │
│           │                                │                                 │
│           │ release()                       │ 空闲超时                       │
│           ▼                                ▼                                 │
│      移到 warm_pool                    destroy()                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. 异常处理

### 10.1 工具异常处理链

```python
# tool_error_handling_middleware.py

class ToolErrorHandlingMiddleware:
    """将工具异常转换为错误消息"""
    
    def awrap_tool_call(self, request, handler):
        try:
            return await handler(request)  # 执行工具
        except GraphBubbleUp:
            raise  # LangGraph 控制流信号，保持传递
        except Exception as exc:
            # 捕获异常，转换为 ToolMessage
            return ToolMessage(
                content=f"Error: Tool '{tool_name}' failed: {exc}",
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
            )
```

### 10.2 Sandbox 异常

```python
# sandbox/exceptions.py

class SandboxError(Exception):
    """Sandbox 基类异常"""

class SandboxNotFoundError(SandboxError):
    """Sandbox 不存在"""

class SandboxRuntimeError(SandboxError):
    """Sandbox 运行时错误"""
```

---

## 11. 相关文件索引

| 文件 | 作用 |
|------|------|
| `sandbox/sandbox.py` | Sandbox 抽象基类 |
| `sandbox/sandbox_provider.py` | SandboxProvider 抽象基类 + 单例管理 |
| `sandbox/middleware.py` | SandboxMiddleware（生命周期管理）⭐ |
| `sandbox/tools.py` | 内置工具实现 (bash, ls, read_file, write_file) |
| `sandbox/local/local_sandbox_provider.py` | 本地 Sandbox Provider |
| `sandbox/community/aio_sandbox/aio_sandbox_provider.py` | AIO Sandbox Provider（生产用）⭐ |
| `sandbox/community/aio_sandbox/aio_sandbox.py` | AIO Sandbox HTTP 客户端 |
| `agents/middlewares/thread_data_middleware.py` | 线程数据目录管理 |
| `agents/middlewares/memory_middleware.py` | 记忆更新（after_agent） |
| `agents/lead_agent/agent.py` | 中间件链构建 |

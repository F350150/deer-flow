# 05 - Phase 5: Sandbox 执行和安全机制

> 预计时间: 5-7 天
> 
> 本阶段目标：理解 DeerFlow 的 Sandbox 执行系统，包括 Local/Docker/Kubernetes 三种执行环境、虚拟路径映射、安全隔离机制

---

## 5.1 Sandbox 概述

### 什么是 Sandbox？

**Sandbox（沙箱）** 是 DeerFlow 中**执行用户代码的隔离环境**。当 Agent 需要执行 bash 命令、读写文件时，都会在 Sandbox 中运行。

### 为什么需要 Sandbox？

| 问题 | 解决方案 |
|------|----------|
| 用户代码可能有害 | 隔离环境执行 |
| 防止污染主机环境 | 容器/虚拟机隔离 |
| 资源限制 | 配额和超时控制 |
| 文件系统隔离 | 虚拟路径映射 |

### DeerFlow 的三种 Sandbox

| 类型 | 环境 | 隔离程度 | 适用场景 |
|------|------|----------|----------|
| **Local** | 本地直接执行 | 无隔离 | 开发调试 |
| **Docker** | Docker 容器 | 进程级隔离 | 生产环境（单节点） |
| **Kubernetes** | K8s Pod | 容器 + 资源限制 | 生产环境（集群） |

---

## 5.2 Sandbox 架构

### 核心文件

```
backend/packages/harness/deerflow/sandbox/
├── __init__.py
├── base.py                  # 基类定义 ⭐⭐⭐
├── local.py                 # 本地执行
├── docker.py                # Docker 执行
├── kubernetes.py            # K8s 执行
├── tools.py                 # 内置工具 (bash, ls, read_file...)
└── provisioner/             # K8s 供应器
    ├── __init__.py
    ├── kubeconfig.py
    └── client.py
```

### Sandbox 基类

```python
# backend/packages/harness/deerflow/sandbox/base.py

from abc import ABC, abstractmethod
from typing import Any

class SandboxProvider(ABC):
    """Sandbox 抽象基类"""
    
    @abstractmethod
    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300,
        **kwargs,
    ) -> tuple[int, str, str]:
        """
        执行命令
        
        Returns:
            (exit_code, stdout, stderr)
        """
        pass
    
    @abstractmethod
    def get_workspace_path(self, thread_id: str) -> str:
        """获取工作区路径"""
        pass
    
    @abstractmethod
    def cleanup(self, thread_id: str) -> None:
        """清理线程资源"""
        pass
```

---

## 5.3 Local Sandbox

### 实现

```python
# backend/packages/harness/deerflow/sandbox/local.py

class LocalSandboxProvider(SandboxProvider):
    """本地执行沙箱（无隔离）"""
    
    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300,
        **kwargs,
    ) -> tuple[int, str, str]:
        """直接在本地执行命令"""
        
        import subprocess
        
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        return result.returncode, result.stdout, result.stderr
    
    def get_workspace_path(self, thread_id: str) -> str:
        # 返回本地临时目录
        return f"/tmp/deerflow/{thread_id}"
```

### 特点

- **优点**: 简单、无额外资源开销
- **缺点**: 无隔离、可能污染主机
- **适用**: 开发调试

---

## 5.4 Docker Sandbox

### 实现

```python
# backend/packages/harness/deerflow/sandbox/docker.py

class DockerSandboxProvider(SandboxProvider):
    """Docker 容器沙箱"""
    
    def __init__(self):
        self.container_name_prefix = "deerflow-sandbox"
    
    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300,
        **kwargs,
    ) -> tuple[int, str, str]:
        """在 Docker 容器中执行命令"""
        
        import docker
        
        client = docker.from_env()
        
        # 创建临时容器
        container = client.containers.run(
            "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest",
            f"bash -c '{command}'",
            detach=True,
            volumes={
                self.get_workspace_path(thread_id): {
                    "bind": "/mnt/user-data",
                    "mode": "rw",
                }
            },
            working_dir=cwd or "/mnt/user-data",
            mem_limit="2g",
            cpu_period=100000,
            cpu_quota=50000,  # 50% CPU
        )
        
        try:
            # 等待执行完成
            result = container.wait(timeout=timeout)
            stdout = container.logs(stdout=True, stderr=False).decode()
            stderr = container.logs(stdout=False, stderr=True).decode()
            return result["StatusCode"], stdout, stderr
        finally:
            container.remove(force=True)
```

### 特点

- **优点**: 进程级隔离、环境一致
- **缺点**: 启动慢、资源占用
- **适用**: 生产环境（单节点）

---

## 5.5 Kubernetes Sandbox

### 实现

```python
# backend/packages/harness/deerflow/sandbox/kubernetes.py

class KubernetesSandboxProvider(SandboxProvider):
    """Kubernetes Pod 沙箱"""
    
    def __init__(self, kubeconfig: str | None = None):
        from kubernetes import client, config
        
        if kubeconfig:
            config.load_kube_config(kubeconfig)
        else:
            config.load_incluster_config()
        
        self.core_v1 = client.CoreV1Api()
        self.batch_v1 = client.BatchV1Api()
        self.namespace = "default"
    
    def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 300,
        **kwargs,
    ) -> tuple[int, str, str]:
        """在 K8s Pod 中执行命令"""
        
        pod_name = f"deerflow-sandbox-{thread_id}"
        
        # 创建 Pod
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": pod_name},
            "spec": {
                "containers": [{
                    "name": "sandbox",
                    "image": "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest",
                    "command": ["bash", "-c", command],
                    "resources": {"limits": {"memory": "2Gi", "cpu": "500m"}},
                }],
                "restartPolicy": "Never",
            },
        }
        
        self.core_v1.create_namespaced_pod(self.namespace, pod_manifest)
        
        try:
            # 等待 Pod 完成
            while True:
                pod = self.core_v1.read_namespaced_pod(pod_name, self.namespace)
                if pod.status.phase == "Succeeded":
                    logs = self.core_v1.read_namespaced_pod_log(pod_name, self.namespace)
                    return 0, logs, ""
                elif pod.status.phase == "Failed":
                    logs = self.core_v1.read_namespaced_pod_log(pod_name, self.namespace)
                    return 1, "", logs
                time.sleep(1)
        finally:
            self.core_v1.delete_namespaced_pod(pod_name, {})
```

---

## 5.6 虚拟路径映射

### 路径结构

```
宿主机                            容器内
─────────────────────────────────────────────────
$WORKSPACE/{thread_id}    →    /mnt/user-data/workspace/{thread_id}
$UPLOADS/{thread_id}     →    /mnt/user-data/uploads/{thread_id}
$OUTPUTS/{thread_id}      →    /mnt/user-data/outputs/{thread_id}
```

### 路径隔离

每个线程（thread_id）有独立的目录：

```
/tmp/deerflow/                    # Local Sandbox 根目录
├── thread_abc123/
│   ├── workspace/                 # 工作目录
│   ├── uploads/                  # 上传文件
│   └── outputs/                   # 输出文件
├── thread_def456/
│   └── ...
```

### 工作目录配置

```yaml
# config.yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  
  # Local Sandbox 配置
  local:
    workspace_root: /tmp/deerflow
  
  # Docker Sandbox 配置
  docker:
    image: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
    workspace_root: /mnt/user-data
    memory_limit: 2g
    cpu_limit: 0.5
```

---

## 5.7 内置工具

**文件**: `backend/packages/harness/deerflow/sandbox/tools.py`

### 工具列表

| 工具 | 功能 |
|------|------|
| `bash` | 执行 Bash 命令 |
| `ls` | 列出目录 |
| `read_file` | 读取文件 |
| `write_file` | 写入文件 |
| `str_replace` | 编辑文件（sed 风格） |

### bash 工具

```python
def bash_tool(command: str, timeout: int = 60) -> str:
    """执行 bash 命令"""
    
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    
    if result.returncode != 0:
        raise ValueError(f"Command failed: {result.stderr}")
    
    return result.stdout
```

### read_file 工具

```python
def read_file(path: str) -> str:
    """读取文件内容"""
    
    # 安全检查：防止路径遍历
    safe_path = Path(path).resolve()
    if ".." in path or not safe_path.exists():
        raise ValueError(f"Invalid path: {path}")
    
    return safe_path.read_text()
```

### write_file 工具

```python
def write_file(path: str, content: str) -> str:
    """写入文件"""
    
    safe_path = Path(path).resolve()
    
    # 安全检查：只能在 workspace 内
    if not str(safe_path).startswith("/mnt/user-data"):
        raise ValueError(f"Write not allowed outside workspace: {path}")
    
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_text(content)
    
    return f"Written to {path}"
```

---

## 5.8 安全机制

### 路径遍历防护

```python
def safe_path(path: str, workspace_root: str) -> Path:
    """安全路径解析，防止 .. 路径遍历"""
    
    resolved = (Path(workspace_root) / path).resolve()
    
    # 确保解析后的路径在 workspace 内
    if not str(resolved).startswith(workspace_root):
        raise ValueError(f"Path traversal attempt: {path}")
    
    return resolved
```

### 命令限制

```python
# 系统提示词中的命令限制
"""
**Command Restrictions:**
- DO NOT run interactive commands (vim, nano, etc.)
- DO NOT run commands that require TTY (sudo, ssh, etc.)
- DO NOT modify system files (/etc, /usr, etc.)
- DO NOT run apt-get, yum, or package managers directly
- DO NOT run processes in the background (use & carefully)
"""
```

### 超时控制

```python
def execute_with_timeout(command: str, timeout: int = 60) -> str:
    """带超时的执行"""
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        raise ValueError(f"Command timed out after {timeout}s")
```

### 资源限制

```yaml
# Docker 资源限制
docker:
  memory_limit: 2g      # 最大内存
  cpu_limit: 0.5        # CPU 核心数
  pids_limit: 100       # 进程数限制

# Kubernetes 资源限制
kubernetes:
  resources:
    limits:
      memory: 2Gi
      cpu: 500m
    requests:
      memory: 1Gi
      cpu: 250m
```

---

## 5.9 Sandbox Middleware

**文件**: `backend/packages/harness/deerflow/agents/middlewares/sandbox.py`

### 中间件作用

```python
class SandboxMiddleware(AgentMiddleware):
    """在执行前切换 Sandbox 环境"""
    
    def __call__(
        self,
        state: ThreadState,
        config: RunnableConfig,
    ) -> ThreadState:
        # 1. 获取配置的 sandbox 类型
        sandbox_type = config.get("configurable", {}).get(
            "sandbox_type", "local"
        )
        
        # 2. 创建对应的 Sandbox Provider
        if sandbox_type == "docker":
            sandbox = DockerSandboxProvider()
        elif sandbox_type == "kubernetes":
            sandbox = KubernetesSandboxProvider()
        else:
            sandbox = LocalSandboxProvider()
        
        # 3. 注入到状态中
        state["sandbox"] = sandbox
        state["sandbox_type"] = sandbox_type
        
        # 4. 设置工作目录
        thread_id = state["thread_id"]
        state["workspace_path"] = sandbox.get_workspace_path(thread_id)
        
        return state
```

---

## 5.10 实践任务

### 任务 1: 观察 Local Sandbox 执行

在对话中让 Agent 执行 `ls -la /tmp`，观察输出路径。

### 任务 2: 理解路径映射

上传一个文件，观察它在容器内的路径变化。

### 任务 3: 测试安全机制

尝试让 Agent 执行危险命令（如 `rm -rf /`），观察 Sandbox 如何阻止。

---

## 5.11 学习目标检查清单

- [ ] 理解三种 Sandbox 的区别
- [ ] 理解虚拟路径映射机制
- [ ] 理解 Local/Docker/K8s 的实现差异
- [ ] 理解内置工具的功能
- [ ] 理解安全机制（路径遍历、命令限制、资源限制）
- [ ] 理解 Sandbox Middleware 的作用

---

## 5.12 相关源码文件

| 文件 | 作用 |
|------|------|
| `packages/harness/deerflow/sandbox/base.py` | Sandbox 基类 |
| `packages/harness/deerflow/sandbox/local.py` | 本地执行 |
| `packages/harness/deerflow/sandbox/docker.py` | Docker 执行 |
| `packages/harness/deerflow/sandbox/kubernetes.py` | K8s 执行 |
| `packages/harness/deerflow/sandbox/tools.py` | 内置工具 |
| `packages/harness/deerflow/agents/middlewares/sandbox.py` | Sandbox 中间件 |

---

## 5.13 下一步

**[06-Phase 6: 进阶主题](./06-phase6-advanced.md)**

学习 Memory System、MCP 协议、IM Channels 等进阶主题。

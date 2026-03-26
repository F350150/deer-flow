# 01 - Phase 1: 项目整体架构

> 预计时间: 3-5 天
> 
> 本阶段目标：理解 DeerFlow 的整体架构，包括三服务架构、Nginx 路由、配置系统

---

## 1.1 必读文档

在学习源码之前，请先阅读以下文档建立全局观：

| 文档 | 行数 | 内容 |
|------|------|------|
| `README.md` | ~595 行 | 项目整体介绍、安装方式、快速开始 |
| `backend/CLAUDE.md` | ~523 行 | 后端架构、开发指南、设计决策 |
| `frontend/CLAUDE.md` | ~ | 前端架构、组件结构 |
| `Install.md` | ~ | 详细安装指南 |

### 阅读顺序建议

```
1. README.md (快速浏览，了解项目是什么)
2. backend/CLAUDE.md (重点阅读，理解后端架构)
3. frontend/CLAUDE.md (浏览，理解前端架构)
4. Install.md (如果安装遇到问题)
```

---

## 1.2 三服务架构详解

### 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Nginx (Port 2026)                           │
│                                                                         │
│    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│    │/api/langgraph│  │   /api/*     │  │     /*       │              │
│    │     ↓        │  │      ↓       │  │      ↓       │              │
│    │ LangGraph    │  │  Gateway API  │  │   Frontend   │              │
│    │ Server       │  │              │  │              │              │
│    │ :2024        │  │   :8001      │  │    :3000     │              │
│    └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

### 为什么需要三服务架构？

| 服务 | 职责 | 为什么独立 |
|------|------|-----------|
| **Nginx** | 反向代理、负载均衡、SSL | 统一入口、便于扩展 |
| **LangGraph Server** | Agent 执行、状态管理 | 计算密集，需要独立扩展 |
| **Gateway API** | REST API、数据管理 | IO 密集，与 Agent 解耦 |
| **Frontend** | UI 交互 | 前端独立开发部署 |

### 请求流程示例

**用户发送消息的完整流程**:

```
1. 用户在浏览器输入: http://localhost:2026
   ↓
2. Nginx 接收请求 (端口 2026)
   ↓
3. Nginx 路由判断:
   - /api/langgraph/* → 转发到 LangGraph Server:2024
   - /api/* → 转发到 Gateway API:8001
   - /* → 转发到 Frontend:3000
   ↓
4. 假设请求是 /api/langgraph/threads/xxx/runs
   ↓
5. LangGraph Server 执行 Agent 逻辑
   ↓
6. Agent 调用 GLM-4.7 模型
   ↓
7. 流式响应通过 SSE 返回
   ↓
8. 前端渲染消息
```

---

## 1.3 Nginx 配置详解

### 配置文件位置
- 开发环境: `docker/nginx/nginx.local.conf`
- 生产环境: `docker/nginx/nginx.conf`

### 核心配置解析

```nginx
# docker/nginx/nginx.local.conf

worker_processes 1;
events {
    worker_connections 1024;
}

http {
    upstream langgraph {
        server localhost:2024;
    }
    
    upstream gateway {
        server localhost:8001;
    }
    
    upstream frontend {
        server localhost:3000;
    }
    
    server {
        listen 2026;
        
        location /api/langgraph/ {
            proxy_pass http://langgraph;
            # SSE 流式响应需要这些配置
            proxy_http_version 1.1;
            proxy_set_header Connection '';
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
        
        location /api/ {
            proxy_pass http://gateway;
            proxy_http_version 1.1;
            proxy_set_header Connection '';
        }
        
        location / {
            proxy_pass http://frontend;
            proxy_http_version 1.1;
            proxy_set_header Connection '';
        }
    }
}
```

### 关键配置说明

| 配置 | 作用 |
|------|------|
| `proxy_http_version 1.1` | 启用 HTTP/1.1，支持长连接 |
| `proxy_set_header Connection ''` | 清除 Connection 头，支持 SSE |
| `proxy_pass http://langgraph` | 反向代理到上游服务 |

---

## 1.4 配置系统详解

### 配置文件结构

```
deer-flow/
├── config.yaml                    # 主配置文件
├── extensions_config.example.json # MCP 和 Skills 扩展配置
├── .env                           # 环境变量 (API keys)
└── backend/
    └── packages/harness/deerflow/config/  # 配置加载代码
```

### config.yaml 结构

```yaml
# 配置文件版本 (用于检测过时的配置)
config_version: 3

# 日志级别
log_level: info

# Token 使用统计
token_usage:
  enabled: false

# 模型配置 (最重要!)
models:
  - name: glm-4.7              # 模型标识名
    display_name: GLM-4.7      # 显示名称
    use: langchain_openai:ChatOpenAI  # LangChain 类路径
    model: glm-4-0520          # 模型名称
    api_key: $GLM_API_KEY      # 环境变量引用
    base_url: https://open.bigmodel.cn/api/paas/v4
    max_tokens: 4096
    temperature: 0.7
    supports_thinking: true
    supports_vision: true

# 沙箱配置
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider

# 工具配置
tools:
  - name: web
  - name: bash
  - name: read_file
  # ...

# Skills 配置
skills:
  container_path: /mnt/skills
  public_path: ./skills/public
  custom_path: ./skills/custom

# 扩展配置 (MCP 服务器等)
extensions:
  mcp_servers: []
```

### 配置加载流程

```
config.yaml (YAML 文件)
    ↓
AppConfig.from_file()  [app_config.py]
    ↓
YAML → Pydantic 模型
    ↓
环境变量替换 ($GLM_API_KEY → 实际值)
    ↓
全局配置对象 (get_app_config())
```

### 关键配置类

| 类 | 文件 | 作用 |
|----|------|------|
| `AppConfig` | `app_config.py` | 根配置 |
| `ModelConfig` | `model_config.py` | 模型配置 |
| `SandboxConfig` | `sandbox_config.py` | 沙箱配置 |
| `ToolConfig` | `tool_config.py` | 工具配置 |
| `SkillsConfig` | `skills_config.py` | Skills 配置 |

---

## 1.5 环境变量系统

### .env 文件

```bash
# API Keys
GLM_API_KEY=your-api-key-here

# 可选: CORS 跨域配置
# CORS_ORIGINS=http://localhost:3000

# 可选: 其他服务 API Keys
# OPENAI_API_KEY=xxx
# DEEPSEEK_API_KEY=xxx
```

### 环境变量在配置中的使用

```yaml
# config.yaml
api_key: $GLM_API_KEY

# 系统会自动替换为 .env 中的值
```

### 环境变量加载流程

```
scripts/serve.sh
    ↓
if [ -f .env ]; then
    set -a          # 自动导出
    source .env     # 加载所有变量
    set +a
fi
    ↓
启动服务时所有环境变量已设置
```

---

## 1.6 Makefile 命令详解

### 开发命令

| 命令 | 作用 |
|------|------|
| `make config` | 生成 config.yaml |
| `make config-upgrade` | 升级配置文件 |
| `make check` | 检查依赖工具 |
| `make install` | 安装所有依赖 |
| `make dev` | 启动开发服务器 |
| `make dev-daemon` | 后台启动 |
| `make start` | 生产模式启动 |
| `make stop` | 停止服务 |
| `make clean` | 清理临时文件 |

### Docker 命令

| 命令 | 作用 |
|------|------|
| `make docker-init` | 初始化 Docker 环境 |
| `make docker-start` | 启动 Docker 服务 |
| `make docker-stop` | 停止 Docker 服务 |
| `make up` | 生产 Docker 部署 |
| `make down` | 停止生产 Docker |

### make dev 执行流程

```bash
make dev
    ↓
Makefile: 调用 ./scripts/serve.sh --dev
    ↓
serve.sh:
    1. 加载 .env 环境变量
    2. 检查 config.yaml 是否存在
    3. 停止已有服务 (pkill)
    4. 启动 LangGraph Server (后台)
    5. 等待端口 2024 就绪
    6. 启动 Gateway API (后台)
    7. 等待端口 8001 就绪
    8. 启动 Frontend (后台)
    9. 等待端口 3000 就绪
    10. 启动 Nginx (后台)
    11. 等待端口 2026 就绪
    12. 打印访问信息
    13. 阻塞等待 (Ctrl+C 退出)
```

---

## 1.7 服务端口汇总

| 端口 | 服务 | 用途 |
|------|------|------|
| 2026 | Nginx | 统一入口，外部访问用此端口 |
| 2024 | LangGraph Server | Agent 运行时 |
| 8001 | Gateway API | REST API |
| 3000 | Frontend | Next.js 开发服务器 |

---

## 1.8 学习目标检查清单

- [ ] 理解三服务架构及通信方式
- [ ] 理解 Nginx 如何做路由分发
- [ ] 理解 config.yaml 的主要配置项
- [ ] 理解 .env 环境变量的作用
- [ ] 能够使用 `make dev` 启动项目
- [ ] 能够排查启动失败的问题

---

## 1.9 实践任务

### 任务 1: 绘制完整请求流程图

绘制从用户在浏览器输入 URL 到看到响应结果的完整流程图，包括 Nginx 路由、各服务交互等。

### 任务 2: 修改 Nginx 配置

尝试修改 `docker/nginx/nginx.local.conf`，添加日志记录，然后重启 Nginx 观察效果。

### 任务 3: 配置多个模型

在 `config.yaml` 中配置多个模型（如 OpenAI、DeepSeek），理解多模型配置方式。

---

## 1.10 下一步

**[02-Phase 2: Agent 核心实现](./02-phase2-agent-core.md)**

深入学习 DeerFlow 的核心：ThreadState、Lead Agent、Middleware Chain。

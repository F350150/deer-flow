#!/usr/bin/env python
"""
DeerFlow 全接口 API 测试脚本 — 用于通过 API 调用调试源码。

支持两种运行方式:

1. 直接运行（推荐调试用）:
    cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py
    cd backend && PYTHONPATH=. uv run python tests/test_api_debug.py --module langgraph

2. pytest 运行（PyCharm 右键 Run/Debug）:
    cd backend && PYTHONPATH=. uv run pytest tests/test_api_debug.py -v -s
    cd backend && PYTHONPATH=. uv run pytest tests/test_api_debug.py::test_langgraph -v -s

可选参数 (仅直接运行模式):
    --gateway  http://localhost:8001   Gateway 地址
    --langgraph http://localhost:2024  LangGraph 地址
    --module   <name>                  只运行指定模块

注意:
    运行前请确保对应服务已启动。
    Gateway API 测试需要 Gateway (:8001) 运行。
    LangGraph 测试需要 LangGraph Server (:2024) 运行。

在 PyCharm / VS Code 中以 Debug 模式运行此脚本，并在
backend/app/gateway/routers/*.py 或 backend/packages/harness/deerflow/ 中设置断点，
即可跟踪每个请求的完整处理链路。
"""

import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import httpx

# ──────────────────────────────────────────────────────────────
# 配置 — 可通过环境变量覆盖
# ──────────────────────────────────────────────────────────────

GATEWAY_URL = os.environ.get("TEST_GATEWAY_URL", "http://localhost:8001")
LANGGRAPH_URL = os.environ.get("TEST_LANGGRAPH_URL", "http://localhost:2024")
REQUEST_TIMEOUT = 30.0  # 普通请求超时(秒)
STREAM_TIMEOUT = 120.0  # 流式请求超时(秒)


# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────

class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def _header(title: str):
    """打印分组标题"""
    print(f"\n{'='*70}")
    print(f"  {Colors.BOLD}{Colors.CYAN}{title}{Colors.END}")
    print(f"{'='*70}")


def _subheader(title: str):
    """打印子标题"""
    print(f"\n  {Colors.BOLD}▸ {title}{Colors.END}")


def _success(msg: str):
    print(f"    {Colors.GREEN}✓{Colors.END} {msg}")


def _fail(msg: str):
    print(f"    {Colors.RED}✗{Colors.END} {msg}")


def _info(msg: str):
    print(f"    {Colors.YELLOW}ℹ{Colors.END} {msg}")


def _print_response(resp: httpx.Response, max_body: int = 2000):
    """打印 HTTP 响应摘要"""
    status_color = Colors.GREEN if resp.status_code < 400 else Colors.RED
    print(f"    {status_color}HTTP {resp.status_code}{Colors.END}  {resp.request.method} {resp.request.url}")
    body = resp.text
    if len(body) > max_body:
        body = body[:max_body] + f"\n... (truncated, total {len(resp.text)} chars)"
    if body.strip():
        try:
            parsed = json.loads(body)
            body = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            pass
        for line in body.split("\n"):
            print(f"      {line}")


def _assert_status(resp: httpx.Response, expected: int, label: str = ""):
    """断言 HTTP 状态码"""
    if resp.status_code == expected:
        _success(f"{label} → HTTP {resp.status_code}")
    else:
        _fail(f"{label} → 期望 HTTP {expected}, 实际 HTTP {resp.status_code}")
        _print_response(resp)
    return resp.status_code == expected


# ──────────────────────────────────────────────────────────────
# 测试模块: Health Check
# ──────────────────────────────────────────────────────────────

def test_health():
    """
    测试健康检查接口。

    链路:
      GET /health → FastAPI app → 直接返回 {"status": "healthy"}
    """
    gw = GATEWAY_URL
    _header("Health Check")

    _subheader("GET /health")
    resp = httpx.get(f"{gw}/health", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "健康检查")
    _print_response(resp)


# ──────────────────────────────────────────────────────────────
# 测试模块: Models API
# ──────────────────────────────────────────────────────────────

def test_models():
    """
    测试模型管理接口。

    链路:
      GET /api/models
        → routers/models.py: list_models()
        → deerflow.config.get_app_config()
          → 解析 config.yaml → AppConfig
        → 遍历 config.models
        → 返回 ModelsListResponse

      GET /api/models/{model_name}
        → config.get_model_config(model_name)
        → 返回 ModelResponse / 404
    """
    gw = GATEWAY_URL
    _header("Models API — 模型管理")

    # 1. 列出所有模型
    _subheader("GET /api/models — 列出所有模型")
    resp = httpx.get(f"{gw}/api/models", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "列出模型")
    _print_response(resp)

    models = resp.json().get("models", [])
    _info(f"共 {len(models)} 个模型")

    # 2. 获取特定模型详情
    if models:
        first_model = models[0]["name"]
        _subheader(f"GET /api/models/{first_model} — 获取模型详情")
        resp = httpx.get(f"{gw}/api/models/{first_model}", timeout=REQUEST_TIMEOUT)
        _assert_status(resp, 200, f"获取模型 '{first_model}'")
        _print_response(resp)

    # 3. 获取不存在的模型 → 404
    _subheader("GET /api/models/nonexistent-model — 不存在的模型 → 404")
    resp = httpx.get(f"{gw}/api/models/nonexistent-model", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 404, "不存在的模型")
    _print_response(resp)


# ──────────────────────────────────────────────────────────────
# 测试模块: Memory API
# ──────────────────────────────────────────────────────────────

def test_memory():
    """
    测试记忆系统接口。

    链路:
      GET /api/memory
        → routers/memory.py: get_memory()
        → deerflow.agents.memory.updater.get_memory_data()
          → 读取 .deer-flow/memory.json (带缓存)
        → 返回 MemoryResponse

      POST /api/memory/reload
        → reload_memory_data()
          → 强制从文件重新读取

      GET /api/memory/config
        → deerflow.config.memory_config.get_memory_config()
          → 从 config.yaml 读取 memory 配置

      GET /api/memory/status
        → get_memory_config() + get_memory_data()
    """
    gw = GATEWAY_URL
    _header("Memory API — 记忆系统")

    # 1. 获取记忆数据
    _subheader("GET /api/memory — 获取记忆数据")
    resp = httpx.get(f"{gw}/api/memory", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "获取记忆数据")
    _print_response(resp)

    # 2. 重新加载记忆
    _subheader("POST /api/memory/reload — 重新加载记忆")
    resp = httpx.post(f"{gw}/api/memory/reload", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "重新加载记忆")
    _print_response(resp)

    # 3. 获取记忆配置
    _subheader("GET /api/memory/config — 获取记忆配置")
    resp = httpx.get(f"{gw}/api/memory/config", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "获取记忆配置")
    _print_response(resp)

    # 4. 获取记忆状态
    _subheader("GET /api/memory/status — 获取记忆状态(配置+数据)")
    resp = httpx.get(f"{gw}/api/memory/status", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "获取记忆状态")
    _print_response(resp)


# ──────────────────────────────────────────────────────────────
# 测试模块: MCP API
# ──────────────────────────────────────────────────────────────

def test_mcp():
    """
    测试 MCP 配置管理接口。

    链路:
      GET /api/mcp/config
        → routers/mcp.py: get_mcp_configuration()
        → deerflow.config.extensions_config.get_extensions_config()
          → 读取 extensions_config.json
        → 返回 McpConfigResponse

      PUT /api/mcp/config
        → 接收 McpConfigUpdateRequest
        → 写入 extensions_config.json (保留 skills)
        → reload_extensions_config()
        → 返回更新后的配置
    """
    gw = GATEWAY_URL
    _header("MCP API — MCP 配置管理")

    # 1. 获取 MCP 配置
    _subheader("GET /api/mcp/config — 获取当前 MCP 配置")
    resp = httpx.get(f"{gw}/api/mcp/config", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "获取 MCP 配置")
    _print_response(resp)

    original_config = resp.json()
    mcp_servers = original_config.get("mcp_servers", {})
    _info(f"当前 MCP 服务器数量: {len(mcp_servers)}")
    for name in mcp_servers:
        _info(f"  - {name} (enabled={mcp_servers[name].get('enabled', True)})")

    # 2. PUT MCP 配置 (回写当前配置，不做破坏性修改)
    _subheader("PUT /api/mcp/config — 回写当前配置(非破坏性)")
    resp = httpx.put(
        f"{gw}/api/mcp/config",
        json={"mcp_servers": mcp_servers},
        timeout=REQUEST_TIMEOUT,
    )
    _assert_status(resp, 200, "回写 MCP 配置")
    _print_response(resp)


# ──────────────────────────────────────────────────────────────
# 测试模块: Skills API
# ──────────────────────────────────────────────────────────────

def test_skills():
    """
    测试技能管理接口。

    链路:
      GET /api/skills
        → routers/skills.py: list_skills()
        → deerflow.skills.load_skills(enabled_only=False)
          → 扫描 skills/public/ 和 skills/custom/
          → 结合 extensions_config.json 判断 enabled 状态
        → 返回 SkillsListResponse

      GET /api/skills/{skill_name}
        → load_skills() → 找同名 → SkillResponse / 404

      PUT /api/skills/{skill_name}
        → 写入 extensions_config.json
        → reload_extensions_config()
    """
    gw = GATEWAY_URL
    _header("Skills API — 技能管理")

    # 1. 列出所有技能
    _subheader("GET /api/skills — 列出所有技能")
    resp = httpx.get(f"{gw}/api/skills", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "列出技能")
    _print_response(resp)

    skills = resp.json().get("skills", [])
    _info(f"共 {len(skills)} 个技能")

    # 2. 获取特定技能
    if skills:
        first_skill = skills[0]["name"]
        _subheader(f"GET /api/skills/{first_skill} — 获取技能详情")
        resp = httpx.get(f"{gw}/api/skills/{first_skill}", timeout=REQUEST_TIMEOUT)
        _assert_status(resp, 200, f"获取技能 '{first_skill}'")
        _print_response(resp)

        # 3. 更新技能启用状态 (toggle 后恢复)
        current_enabled = skills[0].get("enabled", True)
        _subheader(f"PUT /api/skills/{first_skill} — 切换 enabled → {not current_enabled}")
        resp = httpx.put(
            f"{gw}/api/skills/{first_skill}",
            json={"enabled": not current_enabled},
            timeout=REQUEST_TIMEOUT,
        )
        _assert_status(resp, 200, f"切换 '{first_skill}' enabled")
        _print_response(resp)

        # 恢复原状态
        _subheader(f"PUT /api/skills/{first_skill} — 恢复 enabled → {current_enabled}")
        resp = httpx.put(
            f"{gw}/api/skills/{first_skill}",
            json={"enabled": current_enabled},
            timeout=REQUEST_TIMEOUT,
        )
        _assert_status(resp, 200, f"恢复 '{first_skill}' enabled")

    # 4. 获取不存在的技能 → 404
    _subheader("GET /api/skills/nonexistent-skill — 不存在的技能 → 404")
    resp = httpx.get(f"{gw}/api/skills/nonexistent-skill", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 404, "不存在的技能")


# ──────────────────────────────────────────────────────────────
# 测试模块: Agents API
# ──────────────────────────────────────────────────────────────

def test_agents():
    """
    测试自定义 Agent CRUD 接口。

    链路:
      GET /api/agents
        → routers/agents.py: list_agents()
        → deerflow.config.agents_config.list_custom_agents()
          → 扫描 .deer-flow/agents/*/config.yaml
        → 返回 AgentsListResponse

      POST /api/agents
        → 验证名称 → 创建目录 → 写入 config.yaml + SOUL.md
        → load_agent_config() → 返回 AgentResponse

      GET /api/agents/{name}
        → load_agent_config() + load_agent_soul()
        → 返回 AgentResponse (含 SOUL.md 内容)

      PUT /api/agents/{name}
        → 更新 config.yaml 和/或 SOUL.md

      DELETE /api/agents/{name}
        → shutil.rmtree(agent_dir)
    """
    gw = GATEWAY_URL
    _header("Agents API — 自定义 Agent CRUD")

    test_agent_name = f"test-agent-{uuid.uuid4().hex[:6]}"

    # 1. 列出所有 agent
    _subheader("GET /api/agents — 列出所有自定义 Agent")
    resp = httpx.get(f"{gw}/api/agents", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "列出 Agents")
    _print_response(resp)

    agents_before = resp.json().get("agents", [])
    _info(f"当前共 {len(agents_before)} 个自定义 Agent")

    # 2. 检查名称可用性
    _subheader(f"GET /api/agents/check?name={test_agent_name} — 检查名称可用性")
    resp = httpx.get(f"{gw}/api/agents/check", params={"name": test_agent_name}, timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "检查名称可用性")
    _print_response(resp)

    # 3. 创建 agent
    _subheader(f"POST /api/agents — 创建 Agent '{test_agent_name}'")
    resp = httpx.post(
        f"{gw}/api/agents",
        json={
            "name": test_agent_name,
            "description": "API 测试创建的临时 Agent",
            "model": None,
            "tool_groups": None,
            "soul": "# Test Agent\nYou are a helpful test assistant.",
        },
        timeout=REQUEST_TIMEOUT,
    )
    _assert_status(resp, 201, f"创建 Agent '{test_agent_name}'")
    _print_response(resp)

    # 4. 获取刚创建的 agent
    _subheader(f"GET /api/agents/{test_agent_name} — 获取 Agent 详情 (含 SOUL.md)")
    resp = httpx.get(f"{gw}/api/agents/{test_agent_name}", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, f"获取 Agent '{test_agent_name}'")
    _print_response(resp)

    # 5. 重复创建 → 409
    _subheader("POST /api/agents — 重复创建 → 409 Conflict")
    resp = httpx.post(
        f"{gw}/api/agents",
        json={"name": test_agent_name, "soul": "dup"},
        timeout=REQUEST_TIMEOUT,
    )
    _assert_status(resp, 409, "重复创建 Agent")

    # 6. 更新 agent
    _subheader(f"PUT /api/agents/{test_agent_name} — 更新 Agent")
    resp = httpx.put(
        f"{gw}/api/agents/{test_agent_name}",
        json={
            "description": "Updated description via API test",
            "soul": "# Updated Test Agent\nYou are a SUPER helpful test assistant.",
        },
        timeout=REQUEST_TIMEOUT,
    )
    _assert_status(resp, 200, f"更新 Agent '{test_agent_name}'")
    _print_response(resp)

    # 7. 名称检查已存在
    _subheader(f"GET /api/agents/check?name={test_agent_name} — 名称已被占用")
    resp = httpx.get(f"{gw}/api/agents/check", params={"name": test_agent_name}, timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "名称已被占用")
    available = resp.json().get("available", True)
    if not available:
        _success("available=False，名称已被占用")
    else:
        _fail("available 应该为 False")

    # 8. 非法名称 → 422
    _subheader("GET /api/agents/check?name=bad name! — 非法名称 → 422")
    resp = httpx.get(f"{gw}/api/agents/check", params={"name": "bad name!"}, timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 422, "非法 Agent 名称")

    # 9. 删除 agent
    _subheader(f"DELETE /api/agents/{test_agent_name} — 删除 Agent")
    resp = httpx.delete(f"{gw}/api/agents/{test_agent_name}", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 204, f"删除 Agent '{test_agent_name}'")

    # 10. 删除不存在的 agent → 404
    _subheader(f"DELETE /api/agents/{test_agent_name} — 已删除的 Agent → 404")
    resp = httpx.delete(f"{gw}/api/agents/{test_agent_name}", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 404, "已删除的 Agent → 404")

    # 11. 获取不存在的 agent → 404
    _subheader(f"GET /api/agents/{test_agent_name} — 已删除的 Agent → 404")
    resp = httpx.get(f"{gw}/api/agents/{test_agent_name}", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 404, "已删除的 Agent → 404")


# ──────────────────────────────────────────────────────────────
# 测试模块: User Profile API
# ──────────────────────────────────────────────────────────────

def test_user_profile():
    """
    测试用户画像接口。

    链路:
      GET /api/user-profile
        → routers/agents.py: get_user_profile()
        → 读取 .deer-flow/USER.md
        → 返回 {content: str | null}

      PUT /api/user-profile
        → 写入 .deer-flow/USER.md
        → 返回 {content: str}
    """
    gw = GATEWAY_URL
    _header("User Profile API — 用户画像")

    # 1. 获取当前用户画像
    _subheader("GET /api/user-profile — 获取用户画像")
    resp = httpx.get(f"{gw}/api/user-profile", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "获取用户画像")
    _print_response(resp)
    original_content = resp.json().get("content")

    # 2. 更新用户画像
    test_content = f"# Test User Profile\nUpdated at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    _subheader("PUT /api/user-profile — 更新用户画像")
    resp = httpx.put(
        f"{gw}/api/user-profile",
        json={"content": test_content},
        timeout=REQUEST_TIMEOUT,
    )
    _assert_status(resp, 200, "更新用户画像")
    _print_response(resp)

    # 3. 恢复原状态
    if original_content is not None:
        _subheader("PUT /api/user-profile — 恢复原用户画像")
        resp = httpx.put(
            f"{gw}/api/user-profile",
            json={"content": original_content},
            timeout=REQUEST_TIMEOUT,
        )
        _assert_status(resp, 200, "恢复用户画像")


# ──────────────────────────────────────────────────────────────
# 测试模块: Uploads API
# ──────────────────────────────────────────────────────────────

def test_uploads():
    """
    测试文件上传接口。

    链路:
      POST /api/threads/{thread_id}/uploads
        → routers/uploads.py: upload_files()
        → ensure_uploads_dir(thread_id) → 创建目录
        → normalize_filename() → 安全文件名
        → 保存文件 + 可选 markdown 转换
        → sandbox 同步 (非 local 模式)
        → 返回 UploadResponse

      GET /api/threads/{thread_id}/uploads/list
        → get_uploads_dir() → list_files_in_dir()

      DELETE /api/threads/{thread_id}/uploads/{filename}
        → delete_file_safe()
    """
    gw = GATEWAY_URL
    _header("Uploads API — 文件上传管理")

    thread_id = f"test-thread-{uuid.uuid4().hex[:8]}"

    # 创建临时测试文件
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="deerflow_test_")
    tmp.write("This is a test file for DeerFlow API debugging.\n" * 5)
    tmp.close()

    try:
        # 1. 上传文件
        _subheader(f"POST /api/threads/{thread_id}/uploads — 上传文件")
        with open(tmp.name, "rb") as f:
            resp = httpx.post(
                f"{gw}/api/threads/{thread_id}/uploads",
                files=[("files", ("test_upload.txt", f, "text/plain"))],
                timeout=REQUEST_TIMEOUT,
            )
        _assert_status(resp, 200, "上传文件")
        _print_response(resp)

        # 2. 列出上传的文件
        _subheader(f"GET /api/threads/{thread_id}/uploads/list — 列出上传文件")
        resp = httpx.get(f"{gw}/api/threads/{thread_id}/uploads/list", timeout=REQUEST_TIMEOUT)
        _assert_status(resp, 200, "列出上传文件")
        _print_response(resp)

        # 3. 删除上传的文件
        _subheader(f"DELETE /api/threads/{thread_id}/uploads/test_upload.txt — 删除文件")
        resp = httpx.delete(
            f"{gw}/api/threads/{thread_id}/uploads/test_upload.txt",
            timeout=REQUEST_TIMEOUT,
        )
        _assert_status(resp, 200, "删除上传文件")
        _print_response(resp)

        # 4. 删除不存在的文件 → 404
        _subheader(f"DELETE /api/threads/{thread_id}/uploads/nonexistent.txt — 不存在 → 404")
        resp = httpx.delete(
            f"{gw}/api/threads/{thread_id}/uploads/nonexistent.txt",
            timeout=REQUEST_TIMEOUT,
        )
        _assert_status(resp, 404, "文件不存在 → 404")

    finally:
        Path(tmp.name).unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────
# 测试模块: Artifacts API
# ──────────────────────────────────────────────────────────────

def test_artifacts():
    """
    测试产物下载接口。

    链路:
      GET /api/threads/{thread_id}/artifacts/{path:path}
        → routers/artifacts.py: get_artifact()
        → resolve_thread_virtual_path(thread_id, path)
          → 虚拟路径 → 实际文件系统路径
        → 检查 .skill/ → ZIP 内部文件提取
        → MIME 类型检测 → 返回 FileResponse/PlainTextResponse
    """
    gw = GATEWAY_URL
    _header("Artifacts API — 产物下载")

    thread_id = f"test-thread-{uuid.uuid4().hex[:8]}"

    # 尝试获取一个不存在的产物 → 404
    _subheader(f"GET /api/threads/{thread_id}/artifacts/mnt/user-data/outputs/test.txt — 不存在 → 404")
    resp = httpx.get(
        f"{gw}/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/test.txt",
        timeout=REQUEST_TIMEOUT,
    )
    _assert_status(resp, 404, "产物不存在 → 404")

    # 先上传一个文件，然后通过 artifacts 路径下载
    _subheader(f"POST /api/threads/{thread_id}/uploads — 上传测试产物文件")
    content = "Artifact content for download test."
    resp = httpx.post(
        f"{gw}/api/threads/{thread_id}/uploads",
        files=[("files", ("artifact_test.txt", content.encode(), "text/plain"))],
        timeout=REQUEST_TIMEOUT,
    )
    if _assert_status(resp, 200, "上传测试产物"):
        files_data = resp.json().get("files", [])
        if files_data:
            virtual_path = files_data[0].get("virtual_path", "")
            if virtual_path:
                _subheader(f"GET /api/threads/{thread_id}/artifacts/{virtual_path} — 下载产物")
                resp = httpx.get(
                    f"{gw}/api/threads/{thread_id}/artifacts/{virtual_path}",
                    timeout=REQUEST_TIMEOUT,
                )
                _assert_status(resp, 200, "下载产物文件")
                _info(f"返回内容长度: {len(resp.content)} bytes")
                _info(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")

                # 带 download=true 下载
                _subheader(f"GET .../{virtual_path}?download=true — 强制下载模式")
                resp = httpx.get(
                    f"{gw}/api/threads/{thread_id}/artifacts/{virtual_path}",
                    params={"download": "true"},
                    timeout=REQUEST_TIMEOUT,
                )
                _assert_status(resp, 200, "强制下载模式")
                cd_header = resp.headers.get("content-disposition", "")
                _info(f"Content-Disposition: {cd_header}")


# ──────────────────────────────────────────────────────────────
# 测试模块: Threads API
# ──────────────────────────────────────────────────────────────

def test_threads():
    """
    测试线程数据管理接口。

    链路:
      DELETE /api/threads/{thread_id}
        → routers/threads.py: delete_thread_data()
        → get_paths().delete_thread_dir(thread_id)
          → 删除本地文件系统中的线程数据
          → 不影响 LangGraph 线程状态
    """
    gw = GATEWAY_URL
    _header("Threads API — 线程数据管理")

    # 先创建一些数据
    thread_id = f"test-thread-{uuid.uuid4().hex[:8]}"

    _subheader(f"POST /api/threads/{thread_id}/uploads — 先上传文件创建线程数据")
    resp = httpx.post(
        f"{gw}/api/threads/{thread_id}/uploads",
        files=[("files", ("thread_test.txt", b"test data", "text/plain"))],
        timeout=REQUEST_TIMEOUT,
    )
    _assert_status(resp, 200, "创建线程数据")

    # 删除线程本地数据
    _subheader(f"DELETE /api/threads/{thread_id} — 删除线程本地数据")
    resp = httpx.delete(f"{gw}/api/threads/{thread_id}", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "删除线程数据")
    _print_response(resp)


# ──────────────────────────────────────────────────────────────
# 测试模块: Suggestions API
# ──────────────────────────────────────────────────────────────

def test_suggestions():
    """
    测试建议生成接口。

    链路:
      POST /api/threads/{thread_id}/suggestions
        → routers/suggestions.py: generate_suggestions()
        → _format_conversation(messages) → 格式化对话
        → create_chat_model(name, thinking_enabled=False) → 创建 LLM
        → 构造 prompt → model.invoke() → 解析 JSON 数组
        → 返回 SuggestionsResponse

    注意: 此接口需要有效的 LLM API Key 才能返回实际建议。
          如果模型调用失败，返回 {"suggestions": []}。
    """
    gw = GATEWAY_URL
    _header("Suggestions API — 建议生成")

    thread_id = f"test-thread-{uuid.uuid4().hex[:8]}"

    # 1. 空消息 → 空建议
    _subheader(f"POST /api/threads/{thread_id}/suggestions — 空消息 → 空建议")
    resp = httpx.post(
        f"{gw}/api/threads/{thread_id}/suggestions",
        json={"messages": [], "n": 3},
        timeout=REQUEST_TIMEOUT,
    )
    _assert_status(resp, 200, "空消息请求")
    _print_response(resp)

    # 2. 有消息内容 → 生成建议 (依赖 LLM)
    _subheader(f"POST /api/threads/{thread_id}/suggestions — 生成跟进建议")
    resp = httpx.post(
        f"{gw}/api/threads/{thread_id}/suggestions",
        json={
            "messages": [
                {"role": "user", "content": "什么是 LangGraph？"},
                {"role": "assistant", "content": "LangGraph 是一个用于构建有状态 AI Agent 的框架..."},
            ],
            "n": 3,
        },
        timeout=STREAM_TIMEOUT,  # LLM 调用可能较慢
    )
    _assert_status(resp, 200, "生成跟进建议")
    _print_response(resp)
    suggestions = resp.json().get("suggestions", [])
    _info(f"生成了 {len(suggestions)} 个建议")


# ──────────────────────────────────────────────────────────────
# 测试模块: Channels API
# ──────────────────────────────────────────────────────────────

def test_channels():
    """
    测试 IM 频道管理接口。

    链路:
      GET /api/channels/
        → routers/channels.py: get_channels_status()
        → get_channel_service()
          → 如果服务未启动 → {service_running: false, channels: {}}
          → 如果服务已启动 → service.get_status()

      POST /api/channels/{name}/restart
        → get_channel_service()
        → service.restart_channel(name)
    """
    gw = GATEWAY_URL
    _header("Channels API — IM 频道管理")

    # 1. 获取频道状态
    _subheader("GET /api/channels/ — 获取频道状态")
    resp = httpx.get(f"{gw}/api/channels/", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "获取频道状态")
    _print_response(resp)

    # 2. 重启不存在的频道 (可能 503)
    _subheader("POST /api/channels/nonexistent/restart — 重启不存在的频道")
    resp = httpx.post(f"{gw}/api/channels/nonexistent/restart", timeout=REQUEST_TIMEOUT)
    _info(f"HTTP {resp.status_code} (503 = 服务未运行, 200 = 结果)")
    _print_response(resp)


# ──────────────────────────────────────────────────────────────
# 测试模块: LangGraph API (Agent 对话)
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
# LangGraph 辅助函数
# ──────────────────────────────────────────────────────────────

def _lg_check_available() -> bool:
    """检查 LangGraph Server 是否可达"""
    lg = LANGGRAPH_URL
    try:
        resp = httpx.get(f"{lg}/ok", timeout=5)
        if resp.status_code != 200:
            _info(f"LangGraph Server 不可达 ({lg}), 跳过测试")
            return False
        return True
    except Exception:
        _info(f"LangGraph Server 不可达 ({lg}), 跳过测试")
        _info("请通过 'make dev' 或 'cd backend && uv run langgraph dev' 启动 LangGraph Server")
        return False


def _lg_create_thread() -> str | None:
    """创建一个新线程，返回 thread_id"""
    lg = LANGGRAPH_URL
    resp = httpx.post(f"{lg}/threads", json={}, timeout=REQUEST_TIMEOUT)
    if not _assert_status(resp, 200, "创建线程"):
        return None
    thread_id = resp.json().get("thread_id")
    _info(f"线程 ID: {thread_id}")
    return thread_id


def _lg_delete_thread(thread_id: str):
    """删除线程"""
    lg = LANGGRAPH_URL
    resp = httpx.delete(f"{lg}/threads/{thread_id}", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 204, f"删除线程 {thread_id[:8]}...")


def _lg_stream_chat(
    thread_id: str,
    message: str,
    *,
    config_overrides: dict | None = None,
    stream_mode: list[str] | None = None,
    label: str = "流式对话",
) -> dict:
    """
    向指定线程发送消息并通过 SSE 流式接收回复。

    返回值:
        {
            "success": bool,
            "event_count": int,
            "last_ai_text": str,
            "tool_calls": list[dict],    # 所有工具调用
            "all_events": list[dict],    # 所有 SSE 数据事件 (原始 JSON)
        }
    """
    lg = LANGGRAPH_URL

    configurable = {"thinking_enabled": False}
    if config_overrides:
        configurable.update(config_overrides)

    result = {
        "success": False,
        "event_count": 0,
        "last_ai_text": "",
        "tool_calls": [],
        "all_events": [],
    }

    _subheader(f"POST /threads/{thread_id}/runs/stream — {label}")
    _info(f"发送消息: '{message[:80]}{'...' if len(message) > 80 else ''}'")
    _info(f"配置: {json.dumps(configurable, ensure_ascii=False)}")

    try:
        with httpx.stream(
            "POST",
            f"{lg}/threads/{thread_id}/runs/stream",
            json={
                "assistant_id": "lead_agent",
                "input": {
                    "messages": [{"role": "human", "content": message}]
                },
                "config": {"configurable": configurable},
                "stream_mode": stream_mode or ["values"],
            },
            timeout=httpx.Timeout(STREAM_TIMEOUT, connect=10.0),
        ) as stream:
            _success(f"SSE 连接建立 HTTP {stream.status_code}")

            for line in stream.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    result["event_count"] += 1
                    data_str = line[5:].strip()
                    try:
                        data = json.loads(data_str)
                        result["all_events"].append(data)

                        # 提取 AI 消息和工具调用
                        messages = data.get("messages", [])
                        for msg in messages:
                            if not isinstance(msg, dict):
                                continue
                            if msg.get("type") == "ai":
                                content = msg.get("content", "")
                                if isinstance(content, str) and content.strip():
                                    result["last_ai_text"] = content
                                elif isinstance(content, list):
                                    texts = [
                                        b.get("text", "") if isinstance(b, dict) else str(b)
                                        for b in content
                                    ]
                                    t = "\n".join(t for t in texts if t)
                                    if t:
                                        result["last_ai_text"] = t
                                # 收集工具调用
                                for tc in msg.get("tool_calls", []):
                                    result["tool_calls"].append(tc)
                    except json.JSONDecodeError:
                        pass

        _info(f"收到 {result['event_count']} 个 SSE 事件")
        if result["last_ai_text"]:
            _success(f"Agent 回复: {result['last_ai_text'][:300]}")
        else:
            _info("未在 SSE 中捕获到 AI 文本")
        if result["tool_calls"]:
            _info(f"工具调用: {len(result['tool_calls'])} 次")
            for tc in result["tool_calls"]:
                _info(f"  → {tc.get('name', 'unknown')}({json.dumps(tc.get('args', {}), ensure_ascii=False)[:100]})")
        result["success"] = True

    except httpx.ReadTimeout:
        _fail("SSE 流超时")
    except Exception as e:
        _fail(f"SSE 请求失败: {e}")

    return result


def _lg_get_state(thread_id: str) -> dict | None:
    """获取线程状态并打印摘要"""
    lg = LANGGRAPH_URL
    _subheader(f"GET /threads/{thread_id}/state — 获取线程状态")
    resp = httpx.get(f"{lg}/threads/{thread_id}/state", timeout=REQUEST_TIMEOUT)
    if not _assert_status(resp, 200, "获取线程状态"):
        return None

    state = resp.json()
    values = state.get("values", {})
    messages = values.get("messages", [])
    title = values.get("title")
    todos = values.get("todos")
    artifacts = values.get("artifacts", [])
    thread_data = values.get("thread_data")
    sandbox = values.get("sandbox")
    viewed_images = values.get("viewed_images", {})
    uploaded_files = values.get("uploaded_files")

    _info(f"消息数量: {len(messages)}")
    if title:
        _info(f"对话标题: {title}")
    if todos:
        _info(f"Todo 列表: {json.dumps(todos, ensure_ascii=False)[:200]}")
    if artifacts:
        _info(f"产物: {artifacts}")
    if thread_data:
        _info(f"线程数据路径: workspace={thread_data.get('workspace_path', 'N/A')}")
    if sandbox:
        _info(f"沙箱状态: {sandbox}")
    if viewed_images:
        _info(f"已查看图片: {list(viewed_images.keys())}")
    if uploaded_files:
        _info(f"上传文件: {json.dumps(uploaded_files, ensure_ascii=False)[:200]}")

    # 打印消息摘要
    for i, msg in enumerate(messages):
        msg_type = msg.get("type", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            preview = content[:80]
        elif isinstance(content, list):
            preview = str(content)[:80]
        else:
            preview = str(content)[:80]
        _info(f"  msg[{i}] {msg_type}: {preview}")

    return state


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 1 — 基础对话 + Assistants + 线程生命周期
# ──────────────────────────────────────────────────────────────

def test_langgraph_basic():
    """
    测试 1: 基础对话、Assistants 搜索、线程生命周期管理。

    覆盖:
      - POST /threads                      → 创建线程
      - POST /assistants/search            → 搜索 assistants
      - POST /threads/{id}/runs/stream     → 基础流式对话 (thinking_enabled=False)
      - GET  /threads/{id}/state           → 获取线程完整状态
      - GET  /threads/{id}                 → 获取线程元信息
      - GET  /threads/{id}/runs            → 列出 runs
      - DELETE /threads/{id}               → 删除线程

    链路:
      make_lead_agent(config) → _resolve_model_name() → create_chat_model(thinking_enabled=False)
      → get_available_tools() → _build_middlewares() → apply_prompt_template()
      → create_agent() → agent.astream() → SSE events

    验证的中间件:
      ThreadDataMiddleware, TitleMiddleware, MemoryMiddleware, LoopDetectionMiddleware
    """
    lg = LANGGRAPH_URL
    _header("LangGraph 1 — 基础对话 + 线程生命周期")

    if not _lg_check_available():
        return

    # 1. 创建线程
    _subheader("POST /threads — 创建新线程")
    thread_id = _lg_create_thread()
    if not thread_id:
        return

    # 2. 搜索 assistants
    _subheader("POST /assistants/search — 搜索可用 assistants")
    resp = httpx.post(f"{lg}/assistants/search", json={"limit": 10}, timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "搜索 assistants")
    assistants = resp.json()
    _info(f"可用 assistants 数量: {len(assistants) if isinstance(assistants, list) else 'N/A'}")
    for a in (assistants if isinstance(assistants, list) else []):
        _info(f"  → {a.get('assistant_id', '?')} / graph: {a.get('graph_id', '?')}")

    # 3. 基础流式对话
    result = _lg_stream_chat(
        thread_id,
        "你好，请用一句话简短地自我介绍一下。",
        label="基础对话 (thinking_enabled=False)",
    )

    # 4. 获取线程完整状态 — 验证 TitleMiddleware 生成了标题
    state = _lg_get_state(thread_id)
    if state:
        values = state.get("values", {})
        if values.get("title"):
            _success("TitleMiddleware 生效 — 自动生成了对话标题")
        else:
            _info("标题未生成 (可能首条消息不触发)")

    # 5. 获取线程元信息
    _subheader(f"GET /threads/{thread_id} — 线程元信息")
    resp = httpx.get(f"{lg}/threads/{thread_id}", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "获取线程元信息")
    meta = resp.json()
    _info(f"状态: {meta.get('status')}")
    _info(f"metadata: {json.dumps(meta.get('metadata', {}), ensure_ascii=False)}")

    # 6. 列出 runs
    _subheader(f"GET /threads/{thread_id}/runs — 列出 runs")
    resp = httpx.get(f"{lg}/threads/{thread_id}/runs", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "列出 runs")
    runs = resp.json() if resp.status_code == 200 else []
    _info(f"运行次数: {len(runs) if isinstance(runs, list) else 'N/A'}")

    # 7. 删除线程
    _subheader(f"DELETE /threads/{thread_id} — 删除线程")
    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 2 — 多轮对话 + 上下文保持
# ──────────────────────────────────────────────────────────────

def test_langgraph_multiturn():
    """
    测试 2: 多轮对话，验证上下文在同一个 thread 中保持。

    覆盖:
      - 同一 thread 发送两条消息
      - 第二条消息引用第一条的内容
      - 验证 Agent 能够记住上下文

    链路:
      第一轮: HumanMessage → Agent 回复 (checkpointer 保存 state)
      第二轮: HumanMessage → 加载历史 state → Agent 基于历史上下文回复

    验证的中间件:
      ThreadDataMiddleware, TitleMiddleware, MemoryMiddleware, SummarizationMiddleware (if long)
    """
    _header("LangGraph 2 — 多轮对话 + 上下文保持")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    # 第一轮
    _lg_stream_chat(
        thread_id,
        "我叫小明，我最喜欢的编程语言是 Rust。请记住这些信息。",
        label="第一轮 — 提供个人信息",
    )

    # 第二轮 — 引用第一轮内容
    result = _lg_stream_chat(
        thread_id,
        "请问我叫什么名字？我最喜欢什么编程语言？",
        label="第二轮 — 测试上下文保持",
    )

    # 验证上下文保持
    if result["success"] and result["last_ai_text"]:
        text = result["last_ai_text"].lower()
        if "小明" in text or "rust" in text.lower():
            _success("上下文保持验证通过 — Agent 记住了之前的信息")
        else:
            _info(f"Agent 可能未引用之前的信息，回复: {result['last_ai_text'][:200]}")

    # 检查状态 — 此时应该有 4 条消息 (2 human + 2 ai)
    state = _lg_get_state(thread_id)
    if state:
        msg_count = len(state.get("values", {}).get("messages", []))
        if msg_count >= 4:
            _success(f"多轮消息累积正确 — 共 {msg_count} 条消息")
        else:
            _info(f"消息数量: {msg_count} (预期 >= 4)")

    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 3 — Thinking 模式
# ──────────────────────────────────────────────────────────────

def test_langgraph_thinking():
    """
    测试 3: Thinking 模式 (扩展推理)。

    覆盖:
      - thinking_enabled=True
      - 验证模型是否支持 thinking 模式
      - 如果模型不支持，应自动 fallback 到非 thinking 模式

    链路:
      make_lead_agent(config):
        → cfg["thinking_enabled"] = True
        → model_config.supports_thinking 检查
        → 如果不支持: logger.warning + fallback thinking_enabled=False
        → create_chat_model(thinking_enabled=True/False)

    日志标志:
      "Thinking mode is enabled but model '...' does not support it; fallback to non-thinking mode."
    """
    _header("LangGraph 3 — Thinking 模式 (扩展推理)")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    result = _lg_stream_chat(
        thread_id,
        "请解释什么是递归，用一句话总结。",
        config_overrides={"thinking_enabled": True},
        label="Thinking 模式对话",
    )

    if result["success"]:
        _success("Thinking 模式请求完成 (如果模型不支持会自动 fallback)")

    _lg_get_state(thread_id)
    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 4 — Plan 模式 (Todo 列表)
# ──────────────────────────────────────────────────────────────

def test_langgraph_plan_mode():
    """
    测试 4: Plan 模式，激活 TodoMiddleware。

    覆盖:
      - is_plan_mode=True
      - Agent 应使用 write_todos 工具创建任务列表
      - ThreadState.todos 字段应被填充

    链路:
      make_lead_agent(config):
        → cfg["is_plan_mode"] = True
        → _build_middlewares():
          → _create_todo_list_middleware(is_plan_mode=True)
          → TodoMiddleware(system_prompt=..., tool_description=...)
        → apply_prompt_template() — 注入 <todo_list_system> 提示

    验证:
      GET /threads/{id}/state → values.todos 非空
    """
    _header("LangGraph 4 — Plan 模式 (Todo 列表)")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    result = _lg_stream_chat(
        thread_id,
        "请帮我制定一个学习 Python 的计划，包括：1. 学习基础语法 2. 学习数据结构 3. 做一个项目 4. 学习高级特性。",
        config_overrides={"is_plan_mode": True, "thinking_enabled": False},
        label="Plan 模式 — 触发 TodoMiddleware",
    )

    # 检查 state 中的 todos
    state = _lg_get_state(thread_id)
    if state:
        values = state.get("values", {})
        todos = values.get("todos")
        if todos:
            _success(f"TodoMiddleware 生效 — 生成了 {len(todos)} 个 Todo 项")
            for i, todo in enumerate(todos[:5]):
                _info(f"  [{i}] {json.dumps(todo, ensure_ascii=False)[:100]}")
        else:
            _info("todos 为空 (Agent 可能未使用 write_todos 工具，这取决于模型判断)")

    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 5 — 工具调用 (代码执行)
# ──────────────────────────────────────────────────────────────

def test_langgraph_tool_calling():
    """
    测试 5: 触发工具调用，验证 Agent 的代码执行能力。

    覆盖:
      - 发送需要代码执行的请求
      - 验证 Agent 是否调用了 sandbox 工具 (run_code / run_command)
      - 验证 ThreadState 中 sandbox / artifacts 字段

    链路:
      Agent 推理 → 决定调用 run_code 工具
        → SandboxMiddleware: 获取/创建沙箱实例
        → sandbox.tools.run_code(code="...", language="python")
        → 返回执行结果
        → Agent 基于工具结果继续推理

    验证的中间件:
      ThreadDataMiddleware, SandboxMiddleware, DanglingToolCallMiddleware,
      LoopDetectionMiddleware
    """
    _header("LangGraph 5 — 工具调用 (代码执行)")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    result = _lg_stream_chat(
        thread_id,
        "请用 Python 计算斐波那契数列的前 10 项，运行代码并告诉我结果。",
        config_overrides={"thinking_enabled": False},
        label="代码执行 — 触发 run_code 工具",
    )

    if result["tool_calls"]:
        tool_names = [tc.get("name") for tc in result["tool_calls"]]
        _success(f"Agent 调用了工具: {tool_names}")
        sandbox_tools = [n for n in tool_names if n and ("run" in n.lower() or "code" in n.lower() or "bash" in n.lower())]
        if sandbox_tools:
            _success(f"沙箱工具被调用: {sandbox_tools}")
    else:
        _info("未捕获到工具调用 (可能在 SSE 事件格式中未包含)")

    # 检查线程状态
    state = _lg_get_state(thread_id)
    if state:
        values = state.get("values", {})
        # 检查是否有工具消息
        tool_msgs = [m for m in values.get("messages", []) if m.get("type") == "tool"]
        if tool_msgs:
            _success(f"检测到 {len(tool_msgs)} 条工具执行结果消息")
            for tm in tool_msgs[:3]:
                tool_name = tm.get("name", "unknown")
                content_preview = str(tm.get("content", ""))[:150]
                _info(f"  → {tool_name}: {content_preview}")
        if values.get("sandbox"):
            _info(f"沙箱状态: {values['sandbox']}")

    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 6 — Subagent 模式
# ──────────────────────────────────────────────────────────────

def test_langgraph_subagent():
    """
    测试 6: Subagent 模式，启用子代理分解任务。

    覆盖:
      - subagent_enabled=True
      - Agent 应获得 task 工具
      - 系统 prompt 注入 <subagent_system> 段

    链路:
      make_lead_agent(config):
        → cfg["subagent_enabled"] = True
        → get_available_tools(subagent_enabled=True)
          → SUBAGENT_TOOLS = [task_tool] 被加入工具列表
        → _build_middlewares():
          → SubagentLimitMiddleware(max_concurrent=3)
        → apply_prompt_template(subagent_enabled=True)
          → 注入 <subagent_system> 提示

    注意: Agent 是否真正使用 task 工具取决于模型判断（小任务可能直接执行）
    """
    _header("LangGraph 6 — Subagent 模式 (子代理)")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    result = _lg_stream_chat(
        thread_id,
        "请简要对比 Python 和 JavaScript 的优缺点，一句话总结即可。",
        config_overrides={
            "subagent_enabled": True,
            "max_concurrent_subagents": 3,
            "thinking_enabled": False,
        },
        label="Subagent 模式 — 子代理功能",
    )

    if result["success"]:
        _success("Subagent 模式请求完成")
        task_calls = [tc for tc in result["tool_calls"] if tc.get("name") == "task"]
        if task_calls:
            _success(f"Agent 使用了 task 工具创建了 {len(task_calls)} 个子任务")
        else:
            _info("Agent 未使用 task 工具 (小任务可能直接执行，这是正常行为)")

    _lg_get_state(thread_id)
    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 7 — 自定义 Agent
# ──────────────────────────────────────────────────────────────

def test_langgraph_custom_agent():
    """
    测试 7: 使用自定义 Agent 进行对话。

    覆盖:
      - 先通过 Gateway 创建一个自定义 Agent
      - 然后在 LangGraph 中使用 agent_name 指定该 Agent
      - 验证 Agent 使用了自定义 SOUL.md 的人格

    链路:
      make_lead_agent(config):
        → cfg["agent_name"] = "test-custom-xxx"
        → load_agent_config("test-custom-xxx")
          → 读取 .deer-flow/agents/test-custom-xxx/config.yaml
        → agent_config.model → 自定义模型 (或 null 使用默认)
        → agent_config.tool_groups → 工具过滤
        → apply_prompt_template(agent_name="test-custom-xxx")
          → get_agent_soul("test-custom-xxx") → 读取 SOUL.md
          → _get_memory_context("test-custom-xxx") → Agent专属记忆
    """
    gw = GATEWAY_URL
    _header("LangGraph 7 — 自定义 Agent 对话")

    if not _lg_check_available():
        return

    # 1. 先通过 Gateway 创建自定义 Agent
    test_agent_name = f"test-agent-lg-{uuid.uuid4().hex[:6]}"
    _subheader(f"准备: 通过 Gateway 创建自定义 Agent '{test_agent_name}'")
    resp = httpx.post(
        f"{gw}/api/agents",
        json={
            "name": test_agent_name,
            "description": "LangGraph 测试用自定义 Agent",
            "model": None,  # 使用默认模型
            "tool_groups": None,
            "soul": "# 海盗船长 Agent\n你是一个友好的海盗船长，说话时偶尔会加入 '啊呀' 和 '宝藏' 等海盗风格的词语。",
        },
        timeout=REQUEST_TIMEOUT,
    )
    if not _assert_status(resp, 201, f"创建自定义 Agent '{test_agent_name}'"):
        _info("无法创建自定义 Agent，跳过此测试")
        return

    try:
        # 2. 使用自定义 Agent 对话
        thread_id = _lg_create_thread()
        if not thread_id:
            return

        result = _lg_stream_chat(
            thread_id,
            "你好，请自我介绍一下。",
            config_overrides={
                "agent_name": test_agent_name,
                "thinking_enabled": False,
            },
            label=f"自定义 Agent '{test_agent_name}' 对话",
        )

        if result["success"] and result["last_ai_text"]:
            _success("自定义 Agent 对话完成")
            # 检查是否有海盗风格
            text = result["last_ai_text"]
            if any(kw in text for kw in ["海盗", "船长", "宝藏", "啊呀"]):
                _success("SOUL.md 人格注入验证通过 — 回复包含海盗风格")
            else:
                _info(f"SOUL.md 可能未完全影响回复风格 (取决于模型): {text[:200]}")

        _lg_get_state(thread_id)
        _lg_delete_thread(thread_id)

    finally:
        # 3. 清理: 删除自定义 Agent
        _subheader(f"清理: 删除自定义 Agent '{test_agent_name}'")
        resp = httpx.delete(f"{gw}/api/agents/{test_agent_name}", timeout=REQUEST_TIMEOUT)
        _assert_status(resp, 204, "删除自定义 Agent")


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 8 — 文件上传 + 上下文引用
# ──────────────────────────────────────────────────────────────

def test_langgraph_file_upload():
    """
    测试 8: 上传文件后在对话中引用。

    覆盖:
      - 通过 Gateway 上传文件到线程
      - 然后在 LangGraph 对话中引用上传的文件
      - 验证 UploadsMiddleware 注入了文件信息

    链路:
      Gateway: POST /api/threads/{id}/uploads → 保存文件到 uploads 目录
      LangGraph:
        → UploadsMiddleware (pre-process):
          → 检测 thread_data.uploads_path 下的文件
          → 将文件列表注入到 <uploaded_files> 上下文中
        → Agent 看到上传文件信息 → 可以使用 read_file 工具读取
    """
    gw = GATEWAY_URL
    _header("LangGraph 8 — 文件上传 + 上下文引用")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    # 1. 上传文件
    _subheader(f"POST /api/threads/{thread_id}/uploads — 上传测试文件")
    file_content = """# 测试数据
- 项目名称: DeerFlow
- 版本: 2.0
- 语言: Python
- 框架: LangGraph
"""
    resp = httpx.post(
        f"{gw}/api/threads/{thread_id}/uploads",
        files=[("files", ("project_info.md", file_content.encode("utf-8"), "text/markdown"))],
        timeout=REQUEST_TIMEOUT,
    )
    if _assert_status(resp, 200, "上传文件"):
        _print_response(resp)

    # 2. 对话中引用文件
    result = _lg_stream_chat(
        thread_id,
        "请读取我上传的文件，告诉我项目名称和版本号。",
        config_overrides={"thinking_enabled": False},
        label="引用上传文件对话",
    )

    if result["success"]:
        _success("文件上传+对话完成")
        if result["tool_calls"]:
            read_calls = [tc for tc in result["tool_calls"] if "read" in tc.get("name", "").lower()]
            if read_calls:
                _success(f"Agent 调用了文件读取工具: {[tc['name'] for tc in read_calls]}")

    _lg_get_state(thread_id)
    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 9 — 多种 stream_mode
# ──────────────────────────────────────────────────────────────

def test_langgraph_stream_modes():
    """
    测试 9: 不同的 SSE stream_mode 输出格式。

    覆盖:
      - stream_mode=["values"]     → 每次返回完整 state 快照
      - stream_mode=["messages"]   → 返回消息 tuple (增量)
      - stream_mode=["values", "messages"] → 同时返回两种格式

    这些 stream_mode 由 LangGraph 框架处理，不同的前端可能需要不同的模式:
      - values: 适合需要完整状态的场景 (如状态面板)
      - messages: 适合逐 token 渲染的场景 (如聊天界面)
    """
    _header("LangGraph 9 — 多种 stream_mode 输出格式")

    if not _lg_check_available():
        return

    # stream_mode=["values"]
    thread_id = _lg_create_thread()
    if thread_id:
        result = _lg_stream_chat(
            thread_id,
            "说 'hello'",
            stream_mode=["values"],
            label="stream_mode=['values'] — 完整 state 快照",
        )
        if result["success"]:
            _success(f"values 模式: {result['event_count']} 个事件")
        _lg_delete_thread(thread_id)

    # stream_mode=["messages"]
    thread_id = _lg_create_thread()
    if thread_id:
        result = _lg_stream_chat(
            thread_id,
            "说 'hello'",
            stream_mode=["messages"],
            label="stream_mode=['messages'] — 消息增量",
        )
        if result["success"]:
            _success(f"messages 模式: {result['event_count']} 个事件")
        _lg_delete_thread(thread_id)

    # stream_mode=["values", "messages"]
    thread_id = _lg_create_thread()
    if thread_id:
        result = _lg_stream_chat(
            thread_id,
            "说 'hello'",
            stream_mode=["values", "messages"],
            label="stream_mode=['values','messages'] — 混合模式",
        )
        if result["success"]:
            _success(f"混合模式: {result['event_count']} 个事件")
        _lg_delete_thread(thread_id)



# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 10 — reasoning_effort 参数
# ──────────────────────────────────────────────────────────────

def test_langgraph_reasoning_effort():
    """
    测试 10: reasoning_effort 参数 (控制推理深度)。

    覆盖:
      - reasoning_effort="low" / "medium" / "high"
      - 部分模型支持此参数 (如 o1/o3)

    链路:
      make_lead_agent(config):
        → cfg["reasoning_effort"] = "low"
        → create_chat_model(reasoning_effort="low")
        → 传递给底层模型 API
    """
    _header("LangGraph 10 — reasoning_effort 参数")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    result = _lg_stream_chat(
        thread_id,
        "1+1 等于几？",
        config_overrides={
            "thinking_enabled": False,
            "reasoning_effort": "low",
        },
        label="reasoning_effort='low' — 低推理深度",
    )

    if result["success"]:
        _success("reasoning_effort 参数传递成功 (是否生效取决于模型支持)")

    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 11 — 显式指定模型 (model_name 覆盖)
# ──────────────────────────────────────────────────────────────

def test_langgraph_model_override():
    """
    测试 11: 通过 model_name 或 model 参数显式指定运行时模型。

    覆盖:
      - config.configurable.model_name = "xxx"
      - config.configurable.model = "xxx"
      - 不存在的模型名 → fallback 到默认模型并 logger.warning

    链路:
      make_lead_agent(config):
        → requested_model_name = cfg.get("model_name") or cfg.get("model")
        → _resolve_model_name(requested_model_name)
          → 如果存在于 config → 使用该模型
          → 如果不存在 → logger.warning + fallback 默认模型
        → create_chat_model(name=model_name)

    断点位置:
      agent.py:_resolve_model_name()
      agent.py:268 (make_lead_agent 入口)
    """
    _header("LangGraph 11 — 显式指定模型 (model_name/model)")

    if not _lg_check_available():
        return

    # 11a. 获取可用模型列表
    gw = GATEWAY_URL
    _subheader("GET /api/models — 获取可用模型")
    resp = httpx.get(f"{gw}/api/models", timeout=REQUEST_TIMEOUT)
    models = resp.json().get("models", []) if resp.status_code == 200 else []
    model_names = [m["name"] for m in models]
    _info(f"可用模型: {model_names}")

    # 11b. 使用 model_name 显式指定
    if model_names:
        target_model = model_names[0]
        thread_id = _lg_create_thread()
        if thread_id:
            result = _lg_stream_chat(
                thread_id,
                "说 'OK'",
                config_overrides={
                    "model_name": target_model,
                    "thinking_enabled": False,
                },
                label=f"model_name='{target_model}' — 显式指定模型",
            )
            if result["success"]:
                _success(f"显式指定模型 '{target_model}' 请求成功")
            _lg_delete_thread(thread_id)

    # 11c. 使用 model 参数 (另一种写法)
    if model_names:
        target_model = model_names[0]
        thread_id = _lg_create_thread()
        if thread_id:
            result = _lg_stream_chat(
                thread_id,
                "说 'OK'",
                config_overrides={
                    "model": target_model,
                    "thinking_enabled": False,
                },
                label=f"model='{target_model}' — model 参数写法",
            )
            if result["success"]:
                _success(f"model 参数写法请求成功")
            _lg_delete_thread(thread_id)

    # 11d. 不存在的模型 → fallback 默认
    thread_id = _lg_create_thread()
    if thread_id:
        result = _lg_stream_chat(
            thread_id,
            "说 'OK'",
            config_overrides={
                "model_name": "nonexistent-model-xyz-999",
                "thinking_enabled": False,
            },
            label="model_name='nonexistent' — 不存在的模型 → fallback",
        )
        if result["success"]:
            _success("不存在的模型成功 fallback 到默认模型")
            _info("在 LangGraph Server 日志中应看到 warning: \"Model 'nonexistent-model-xyz-999' not found\"")
        _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 12 — Web Search 工具
# ──────────────────────────────────────────────────────────────

def test_langgraph_web_search():
    """
    测试 12: 触发 web_search 工具调用。

    覆盖:
      - 发送需要网络搜索的请求
      - 验证 Agent 调用了 web_search 或 web_fetch 工具
      - 验证返回内容包含引用

    链路:
      Agent 推理 → 决定调用 web_search 工具
        → deerflow.community.tavily.tools:web_search_tool
          → Tavily API 搜索
        → 返回搜索结果
        → Agent 基于搜索结果生成带引用的回复

    工具列表 (config.yaml group=web):
      - web_search_tool (Tavily)
      - web_fetch_tool (Jina)
      - image_search_tool

    注意: 需要配置 TAVILY_API_KEY 环境变量
    """
    _header("LangGraph 12 — Web Search 工具")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    result = _lg_stream_chat(
        thread_id,
        "请搜索一下今天的日期是几号，告诉我搜索结果。",
        config_overrides={"thinking_enabled": False},
        label="Web Search — 触发搜索工具",
    )

    if result["tool_calls"]:
        web_tools = [tc for tc in result["tool_calls"]
                     if tc.get("name") in ("web_search", "web_fetch", "image_search")]
        if web_tools:
            _success(f"Web 工具被调用: {[tc['name'] for tc in web_tools]}")
        else:
            tool_names = [tc.get("name") for tc in result["tool_calls"]]
            _info(f"调用了其他工具: {tool_names}")
    else:
        _info("未捕获到工具调用 (模型可能直接回答了)")

    state = _lg_get_state(thread_id)
    if state:
        # 检查是否有 web_search 工具消息
        tool_msgs = [m for m in state.get("values", {}).get("messages", [])
                     if m.get("type") == "tool" and m.get("name") in ("web_search", "web_fetch")]
        if tool_msgs:
            _success(f"检测到 {len(tool_msgs)} 条 web 工具结果消息")

    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 13 — Clarification 中断/恢复
# ──────────────────────────────────────────────────────────────

def test_langgraph_clarification():
    """
    测试 13: ask_clarification 工具触发中断，然后恢复对话。

    覆盖:
      - 发送模糊请求 → Agent 调用 ask_clarification
      - ClarificationMiddleware 拦截 → 中断执行 (Command goto=END)
      - 线程状态进入 interrupted 状态
      - 用户回复后恢复对话

    链路:
      Agent 推理 → 决定调用 ask_clarification(question=..., type=...)
        → ClarificationMiddleware.wrap_tool_call():
          → 检测 tool_call.name == "ask_clarification"
          → _format_clarification_message(args)
          → 返回 Command(update={messages: [ToolMessage]}, goto=END)
        → 线程中断 → 前端展示问题
      恢复:
        → 用户发送新消息 → Agent 继续基于澄清信息执行

    断点位置:
      clarification_middleware.py:_handle_clarification()
      clarification_middleware.py:wrap_tool_call()

    注意: 模型是否调用 ask_clarification 取决于其判断
    """
    _header("LangGraph 13 — Clarification 中断/恢复")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    # 发送模糊请求 — 期望 Agent 调用 ask_clarification
    result = _lg_stream_chat(
        thread_id,
        "帮我部署应用。",
        config_overrides={"thinking_enabled": False},
        label="模糊请求 — 期望触发 ask_clarification",
    )

    # 检查是否触发了 ask_clarification
    clarification_calls = [tc for tc in result["tool_calls"] if tc.get("name") == "ask_clarification"]
    if clarification_calls:
        _success(f"Agent 调用了 ask_clarification — 问题: {clarification_calls[0].get('args', {}).get('question', '')[:100]}")

        # 恢复对话 — 回答 clarification 问题
        result2 = _lg_stream_chat(
            thread_id,
            "部署到测试环境，使用 Docker。",
            config_overrides={"thinking_enabled": False},
            label="恢复对话 — 回答 clarification",
        )
        if result2["success"]:
            _success("Clarification 中断/恢复流程完成")
    else:
        _info("Agent 未调用 ask_clarification (模型可能直接处理了)")
        _info("提示: 在 clarification_middleware.py 设置断点验证该分支")

    _lg_get_state(thread_id)
    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 14 — Bootstrap 模式 (Agent 创建向导)
# ──────────────────────────────────────────────────────────────

def test_langgraph_bootstrap():
    """
    测试 14: Bootstrap 模式 — 用于创建新自定义 Agent 的特殊模式。

    覆盖:
      - is_bootstrap=True
      - Agent 获得 setup_agent 工具
      - 使用精简的 prompt (仅 bootstrap skill)
      - 不加载 agent_config

    链路:
      make_lead_agent(config):
        → cfg["is_bootstrap"] = True
        → agent_config = None (跳过 load_agent_config)
        → get_available_tools(...) + [setup_agent]
        → _build_middlewares() — 无 agent_name
        → apply_prompt_template(available_skills=set(["bootstrap"]))

    断点位置:
      agent.py:326 (is_bootstrap 分支)
    """
    _header("LangGraph 14 — Bootstrap 模式 (Agent 创建向导)")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    result = _lg_stream_chat(
        thread_id,
        "你现在处于 bootstrap 模式。请简单说 'bootstrap mode active'。",
        config_overrides={
            "is_bootstrap": True,
            "thinking_enabled": False,
        },
        label="Bootstrap 模式 — Agent 创建向导",
    )

    if result["success"]:
        _success("Bootstrap 模式请求完成")
        # 检查是否有 setup_agent 工具可用
        setup_calls = [tc for tc in result["tool_calls"] if tc.get("name") == "setup_agent"]
        if setup_calls:
            _success(f"Agent 使用了 setup_agent 工具")

    _lg_get_state(thread_id)
    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 15 — 错误处理分支
# ──────────────────────────────────────────────────────────────

def test_langgraph_error_handling():
    """
    测试 15: 各种错误处理分支。

    覆盖:
      - 发送到不存在的 thread → 404/422
      - 不存在的 assistant_id → 错误
      - 空消息 → 边界行为
      - 无效 configurable 参数 → 容错

    链路:
      LangGraph Server 请求验证:
        → thread 不存在 → 404
        → assistant_id 不匹配 → 422/500
        → 空 input → 可能正常处理或报错

    验证的中间件:
      ToolErrorHandlingMiddleware — 工具执行异常转为 error ToolMessage
      DanglingToolCallMiddleware — 孤立 tool_call 补丁
    """
    lg = LANGGRAPH_URL
    _header("LangGraph 15 — 错误处理分支")

    if not _lg_check_available():
        return

    # 15a. 获取不存在的线程状态 → 应返回错误
    _subheader("GET /threads/{nonexistent}/state — 不存在的线程")
    fake_thread = "00000000-0000-0000-0000-000000000000"
    resp = httpx.get(f"{lg}/threads/{fake_thread}/state", timeout=REQUEST_TIMEOUT)
    _info(f"HTTP {resp.status_code} (预期 404 或 422)")
    if resp.status_code >= 400:
        _success(f"不存在的线程正确返回 HTTP {resp.status_code}")
    else:
        _info(f"意外的成功响应 HTTP {resp.status_code}")

    # 15b. 无效的 assistant_id
    thread_id = _lg_create_thread()
    if thread_id:
        _subheader(f"POST /threads/{thread_id}/runs/stream — 无效 assistant_id")
        try:
            with httpx.stream(
                "POST",
                f"{lg}/threads/{thread_id}/runs/stream",
                json={
                    "assistant_id": "nonexistent_agent_xyz",
                    "input": {"messages": [{"role": "human", "content": "test"}]},
                    "stream_mode": ["values"],
                },
                timeout=httpx.Timeout(30, connect=5.0),
            ) as stream:
                _info(f"HTTP {stream.status_code}")
                if stream.status_code >= 400:
                    _success(f"无效 assistant_id 正确返回 HTTP {stream.status_code}")
                else:
                    # 读取 SSE 看是否有错误事件
                    for line in stream.iter_lines():
                        if line and "error" in line.lower():
                            _success(f"SSE 中检测到错误事件: {line[:100]}")
                            break
        except Exception as e:
            _info(f"请求异常 (预期行为): {e}")
        _lg_delete_thread(thread_id)

    # 15c. 空消息输入
    thread_id = _lg_create_thread()
    if thread_id:
        _subheader(f"POST /threads/{thread_id}/runs/stream — 空消息输入")
        try:
            with httpx.stream(
                "POST",
                f"{lg}/threads/{thread_id}/runs/stream",
                json={
                    "assistant_id": "lead_agent",
                    "input": {"messages": []},
                    "config": {"configurable": {"thinking_enabled": False}},
                    "stream_mode": ["values"],
                },
                timeout=httpx.Timeout(30, connect=5.0),
            ) as stream:
                _info(f"空消息 HTTP {stream.status_code}")
                event_count = 0
                for line in stream.iter_lines():
                    if line and line.startswith("data:"):
                        event_count += 1
                _info(f"收到 {event_count} 个 SSE 事件")
        except Exception as e:
            _info(f"空消息异常 (可能是预期行为): {e}")
        _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 16 — 线程搜索/历史 API
# ──────────────────────────────────────────────────────────────

def test_langgraph_thread_management():
    """
    测试 16: 线程搜索和历史管理 API。

    覆盖:
      - POST /threads/search — 搜索线程
      - GET  /threads/{id}/history — 获取状态历史
      - PATCH /threads/{id} — 更新线程元数据

    链路:
      LangGraph Server 内部:
        → threads/search → 查询 checkpointer storage
        → threads/{id}/history → 返回所有 checkpoint 快照
        → PATCH threads/{id} → 更新 metadata
    """
    lg = LANGGRAPH_URL
    _header("LangGraph 16 — 线程搜索/历史 API")

    if not _lg_check_available():
        return

    # 16a. 搜索线程
    _subheader("POST /threads/search — 搜索线程")
    resp = httpx.post(f"{lg}/threads/search", json={"limit": 5}, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 200:
        _assert_status(resp, 200, "搜索线程")
        threads = resp.json()
        _info(f"搜索到 {len(threads) if isinstance(threads, list) else 'N/A'} 个线程")
    else:
        _info(f"threads/search HTTP {resp.status_code} (部分版本可能不支持)")

    # 16b. 创建线程 → 对话 → 获取历史
    thread_id = _lg_create_thread()
    if not thread_id:
        return

    _lg_stream_chat(thread_id, "说 'hello'", label="发送消息以产生历史")

    _subheader(f"GET /threads/{thread_id}/history — 获取状态历史")
    resp = httpx.get(f"{lg}/threads/{thread_id}/history", timeout=REQUEST_TIMEOUT)
    if resp.status_code == 200:
        _assert_status(resp, 200, "获取线程历史")
        history = resp.json()
        if isinstance(history, list):
            _info(f"历史快照数量: {len(history)}")
            for i, snapshot in enumerate(history[:3]):
                checkpoint = snapshot.get("checkpoint", {})
                _info(f"  快照[{i}]: checkpoint_id={checkpoint.get('id', '?')[:16]}...")
        else:
            _info(f"历史格式: {type(history).__name__}")
    else:
        _info(f"history HTTP {resp.status_code} (部分版本可能不支持)")

    # 16c. 更新线程 metadata
    _subheader(f"PATCH /threads/{thread_id} — 更新线程 metadata")
    resp = httpx.patch(
        f"{lg}/threads/{thread_id}",
        json={"metadata": {"test_label": "api_test", "priority": "high"}},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 200:
        _assert_status(resp, 200, "更新线程 metadata")
        _print_response(resp)
    else:
        _info(f"PATCH HTTP {resp.status_code}")

    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: LangGraph 17 — 非流式 Run + Run 取消
# ──────────────────────────────────────────────────────────────

def test_langgraph_run_management():
    """
    测试 17: 非流式 Run 创建、等待、取消。

    覆盖:
      - POST /threads/{id}/runs       → 创建非流式 run (后台执行)
      - POST /threads/{id}/runs/wait  → 创建 run 并等待完成
      - GET  /threads/{id}/runs/{id}  → 获取 run 状态
      - POST /threads/{id}/runs/{id}/cancel → 取消运行中的 run

    链路:
      LangGraph Server:
        → /runs → 创建后台 run → 返回 run_id
        → /runs/wait → 创建 run → 轮询直到完成 → 返回结果
        → /runs/{id} → 查询 run 状态 (pending/running/done/error)
        → /runs/{id}/cancel → 发送取消信号
    """
    lg = LANGGRAPH_URL
    _header("LangGraph 17 — 非流式 Run + Run 管理")

    if not _lg_check_available():
        return

    thread_id = _lg_create_thread()
    if not thread_id:
        return

    # 17a. 非流式 run/wait (阻塞等待完成)
    _subheader(f"POST /threads/{thread_id}/runs/wait — 非流式 run (等待完成)")
    resp = httpx.post(
        f"{lg}/threads/{thread_id}/runs/wait",
        json={
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "human", "content": "说 'hello'"}]},
            "config": {"configurable": {"thinking_enabled": False}},
        },
        timeout=STREAM_TIMEOUT,
    )
    if resp.status_code == 200:
        _assert_status(resp, 200, "非流式 run/wait")
        result = resp.json()
        messages = result.get("messages", [])
        _info(f"返回 {len(messages)} 条消息")
        for msg in messages:
            if msg.get("type") == "ai":
                content = msg.get("content", "")
                if isinstance(content, str):
                    _info(f"AI 回复: {content[:200]}")
    else:
        _info(f"runs/wait HTTP {resp.status_code}")
        _print_response(resp)

    # 17b. 列出 runs
    _subheader(f"GET /threads/{thread_id}/runs — 列出 runs")
    resp = httpx.get(f"{lg}/threads/{thread_id}/runs", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "列出 runs")
    runs = resp.json() if resp.status_code == 200 else []
    _info(f"运行次数: {len(runs) if isinstance(runs, list) else 'N/A'}")

    # 17c. 获取单个 run 状态
    if isinstance(runs, list) and runs:
        run_id = runs[0].get("run_id")
        if run_id:
            _subheader(f"GET /threads/{thread_id}/runs/{run_id} — 获取 run 详情")
            resp = httpx.get(f"{lg}/threads/{thread_id}/runs/{run_id}", timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                _assert_status(resp, 200, "获取 run 详情")
                run_detail = resp.json()
                _info(f"run 状态: {run_detail.get('status')}")
                _info(f"run 创建时间: {run_detail.get('created_at')}")
            else:
                _info(f"获取 run HTTP {resp.status_code}")

    # 17d. 创建非流式 run (后台) + 取消
    _subheader(f"POST /threads/{thread_id}/runs — 创建后台 run")
    resp = httpx.post(
        f"{lg}/threads/{thread_id}/runs",
        json={
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "human", "content": "请写一篇 5000 字的论文关于人工智能的历史。"}]},
            "config": {"configurable": {"thinking_enabled": False}},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code in (200, 201, 202):
        run_data = resp.json()
        bg_run_id = run_data.get("run_id")
        _info(f"后台 run ID: {bg_run_id}")
        _info(f"run 状态: {run_data.get('status')}")

        if bg_run_id:
            # 短暂等待
            import time
            time.sleep(1)

            # 取消 run
            _subheader(f"POST /threads/{thread_id}/runs/{bg_run_id}/cancel — 取消 run")
            resp = httpx.post(
                f"{lg}/threads/{thread_id}/runs/{bg_run_id}/cancel",
                timeout=REQUEST_TIMEOUT,
            )
            _info(f"取消 run HTTP {resp.status_code}")
            if resp.status_code in (200, 202, 204):
                _success("Run 取消请求已发送")
            else:
                _info(f"取消可能已完成或不支持: {resp.status_code}")
    else:
        _info(f"后台 run HTTP {resp.status_code}")
        _print_response(resp)

    _lg_delete_thread(thread_id)


# ──────────────────────────────────────────────────────────────
# 测试: 组合入口 — 运行所有 LangGraph 子测试
# ──────────────────────────────────────────────────────────────

def test_langgraph():
    """
    LangGraph 全功能测试入口 — 依次运行所有子测试。

    子测试 (共 17 个):
      1.  基础对话 + 线程生命周期
      2.  多轮对话 + 上下文保持
      3.  Thinking 模式 (扩展推理)
      4.  Plan 模式 (Todo 列表)
      5.  工具调用 (代码执行 / Sandbox)
      6.  Subagent 模式 (子代理)
      7.  自定义 Agent (SOUL.md 人格)
      8.  文件上传 + 上下文引用
      9.  多种 stream_mode 输出格式
      10. reasoning_effort 参数
      11. 显式指定模型 (model_name/model 覆盖 + fallback)
      12. Web Search 工具
      13. Clarification 中断/恢复
      14. Bootstrap 模式 (Agent 创建向导)
      15. 错误处理分支 (无效线程/assistant/空消息)
      16. 线程搜索/历史 API
      17. 非流式 Run + Run 取消
    """
    _header("╔═══════════════════════════════════════════╗")
    _header("║   LangGraph 全功能测试 — 17 个子测试      ║")
    _header("╚═══════════════════════════════════════════╝")

    if not _lg_check_available():
        return

    subtests = [
        ("1. 基础对话", test_langgraph_basic),
        ("2. 多轮对话", test_langgraph_multiturn),
        ("3. Thinking 模式", test_langgraph_thinking),
        ("4. Plan 模式", test_langgraph_plan_mode),
        ("5. 工具调用", test_langgraph_tool_calling),
        ("6. Subagent 模式", test_langgraph_subagent),
        ("7. 自定义 Agent", test_langgraph_custom_agent),
        ("8. 文件上传", test_langgraph_file_upload),
        ("9. Stream 模式", test_langgraph_stream_modes),
        ("10. reasoning_effort", test_langgraph_reasoning_effort),
        ("11. 模型覆盖", test_langgraph_model_override),
        ("12. Web Search", test_langgraph_web_search),
        ("13. Clarification", test_langgraph_clarification),
        ("14. Bootstrap", test_langgraph_bootstrap),
        ("15. 错误处理", test_langgraph_error_handling),
        ("16. 线程管理", test_langgraph_thread_management),
        ("17. Run 管理", test_langgraph_run_management),
    ]

    for name, fn in subtests:
        try:
            fn()
            _success(f"子测试 {name} 完成")
        except Exception as e:
            _fail(f"子测试 {name} 异常: {e}")
            import traceback
            traceback.print_exc()


# ──────────────────────────────────────────────────────────────
# 测试模块: API Documentation
# ──────────────────────────────────────────────────────────────

def test_api_docs():
    """
    测试 API 文档端点。

    链路:
      GET /docs      → FastAPI Swagger UI (HTML)
      GET /redoc     → FastAPI ReDoc (HTML)
      GET /openapi.json → OpenAPI 3.0 Schema (JSON)
    """
    gw = GATEWAY_URL
    _header("API Documentation — 文档端点")

    # 1. Swagger UI
    _subheader("GET /docs — Swagger UI")
    resp = httpx.get(f"{gw}/docs", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "Swagger UI")
    _info(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")
    _info(f"Body size: {len(resp.content)} bytes")

    # 2. ReDoc
    _subheader("GET /redoc — ReDoc")
    resp = httpx.get(f"{gw}/redoc", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "ReDoc")
    _info(f"Body size: {len(resp.content)} bytes")

    # 3. OpenAPI Schema
    _subheader("GET /openapi.json — OpenAPI Schema")
    resp = httpx.get(f"{gw}/openapi.json", timeout=REQUEST_TIMEOUT)
    _assert_status(resp, 200, "OpenAPI Schema")
    schema = resp.json()
    paths = schema.get("paths", {})
    _info(f"API 路径数量: {len(paths)}")
    for path in sorted(paths.keys()):
        methods = ", ".join(m.upper() for m in paths[path].keys())
        _info(f"  {methods} {path}")


# ──────────────────────────────────────────────────────────────
# 主入口 (直接运行模式)
# ──────────────────────────────────────────────────────────────

MODULE_MAP = {
    "health": test_health,
    "models": test_models,
    "memory": test_memory,
    "mcp": test_mcp,
    "skills": test_skills,
    "agents": test_agents,
    "user_profile": test_user_profile,
    "uploads": test_uploads,
    "artifacts": test_artifacts,
    "threads": test_threads,
    "suggestions": test_suggestions,
    "channels": test_channels,
    "langgraph": test_langgraph,
    # LangGraph 子测试 (也能单独运行)
    # "lg_basic": test_langgraph_basic,
    # "lg_multiturn": test_langgraph_multiturn,
    # "lg_thinking": test_langgraph_thinking,
    # "lg_plan": test_langgraph_plan_mode,
    # "lg_tools": test_langgraph_tool_calling,
    # "lg_subagent": test_langgraph_subagent,
    # "lg_custom_agent": test_langgraph_custom_agent,
    # "lg_file_upload": test_langgraph_file_upload,
    # "lg_stream_modes": test_langgraph_stream_modes,
    # "lg_reasoning": test_langgraph_reasoning_effort,
    # "lg_model": test_langgraph_model_override,
    # "lg_search": test_langgraph_web_search,
    # "lg_clarification": test_langgraph_clarification,
    # "lg_bootstrap": test_langgraph_bootstrap,
    # "lg_error": test_langgraph_error_handling,
    # "lg_thread_mgmt": test_langgraph_thread_management,
    # "lg_run_mgmt": test_langgraph_run_management,
    "docs": test_api_docs,
}


def main():
    import argparse
    import sys

    global GATEWAY_URL, LANGGRAPH_URL

    parser = argparse.ArgumentParser(description="DeerFlow 全接口 API 测试脚本")
    parser.add_argument("--gateway", default=GATEWAY_URL, help=f"Gateway 地址 (默认: {GATEWAY_URL})")
    parser.add_argument("--langgraph", default=LANGGRAPH_URL, help=f"LangGraph 地址 (默认: {LANGGRAPH_URL})")
    parser.add_argument("--module", default="langgraph", choices=list(MODULE_MAP.keys()), help="只运行指定模块")
    args = parser.parse_args()

    GATEWAY_URL = args.gateway
    LANGGRAPH_URL = args.langgraph

    print(f"\n{Colors.BOLD}╔══════════════════════════════════════════════╗{Colors.END}")
    print(f"{Colors.BOLD}║     DeerFlow API 全接口测试脚本               ║{Colors.END}")
    print(f"{Colors.BOLD}╚══════════════════════════════════════════════╝{Colors.END}")
    print(f"  Gateway:    {GATEWAY_URL}")
    print(f"  LangGraph:  {LANGGRAPH_URL}")

    if args.module:
        print(f"  Module:     {args.module}")
        modules_to_run = {args.module: MODULE_MAP[args.module]}
    else:
        modules_to_run = MODULE_MAP

    # 检查 Gateway 是否可达
    try:
        resp = httpx.get(f"{GATEWAY_URL}/health", timeout=5)
        if resp.status_code == 200:
            _success(f"Gateway 可达: {GATEWAY_URL}")
        else:
            _fail(f"Gateway 返回状态码 {resp.status_code}")
    except Exception:
        _fail(f"Gateway 不可达: {GATEWAY_URL}")
        _info("请先启动 Gateway: cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001")
        if args.module != "langgraph":
            sys.exit(1)

    # 运行测试
    total = len(modules_to_run)
    for name, test_fn in modules_to_run.items():
        try:
            test_fn()
        except httpx.ConnectError:
            _fail(f"模块 '{name}' — 连接失败，服务不可达")
        except Exception as e:
            _fail(f"模块 '{name}' — 异常: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*70}")
    print(f"  {Colors.BOLD}{Colors.GREEN}全部测试完成！{Colors.END}")
    print(f"  共运行 {total} 个模块")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()

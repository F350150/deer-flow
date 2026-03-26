"""
测试脚本：组件隔离调试 (Component Debug)

此脚本用于不启动完整服务器的情况下，直接绕过 config.yaml，
实例化并调试底层由于配置不同而隔离的动态组件 (如各种沙箱实现、安全组件)。
"""

import logging
import asyncio
import uuid
import sys
import os

# 设置日志显示
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ComponentDebug")

# 添加模块路径，确保能导入后端代码
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "packages", "harness")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "packages", "core")))

from deerflow.sandbox.local import LocalSandboxProvider
from deerflow.community.aio_sandbox import AioSandboxProvider


def _print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f" {title}")
    print(f"{'=' * 60}")


def test_local_sandbox_direct():
    """直接实例化并测试本地沙箱 (无论 config.yaml 如何配置)"""
    _print_header("组件调试: LocalSandboxProvider (本地执行)")
    
    provider = LocalSandboxProvider()
    thread_id = f"test-thread-local-{uuid.uuid4().hex[:6]}"
    
    try:
        # 1. Acquire Sandbox
        sandbox_id = provider.acquire(thread_id)
        logger.info(f"Acquired local sandbox: {sandbox_id}")
        
        # 2. Get sandbox instance
        sandbox = provider.get(sandbox_id)
        if not sandbox:
            logger.error("Failed to get sandbox instance")
            return
            
        # 3. Code Execution Debug
        cmd = "echo 'Hello from Local Sandbox!'"
        logger.info(f"Running command: {cmd}")
        stdout = sandbox.execute_command(cmd)
        
        logger.info(f"Stdout:\n{stdout.strip()}")
             
    finally:
        logger.info(f"Shutting down local provider")
        pass


def test_aio_sandbox_direct():
    """直接实例化并测试 AIO Docker 沙箱 (需要本机有 Docker)"""
    _print_header("组件调试: AioSandboxProvider (Docker / AIO 隔离执行)")
    
    try:
        provider = AioSandboxProvider()
    except Exception as e:
        logger.error(f"无法初始化 AioSandboxProvider (可能未安装 Docker 或依赖缺失): {e}")
        return
        
    thread_id = f"test-thread-aio-{uuid.uuid4().hex[:6]}"
    sandbox_id = None
    
    try:
        # 1. Acquire Sandbox (这也将拉起 Docker 容器)
        logger.info(f"Acquiring AIO Sandbox (这可能需要几秒钟启动容器) ...")
        sandbox_id = provider.acquire(thread_id)
        logger.info(f"Acquired AIO Sandbox: {sandbox_id}")
        
        # 2. Get Sandbox
        sandbox = provider.get(sandbox_id)
        if not sandbox:
            logger.error("Failed to get sandbox instance")
            return
            
        # 3. Code Execution
        py_code = 'print("Hello from inside Docker Sandbox!")\\nimport os\\nprint("Env:", os.environ.get("NODE_ENV", "Not Set"))'
        logger.info("Executing python code inside AIO sandbox...")
        
        # 使用 execute_command 执行 python
        stdout = sandbox.execute_command(f"python3 -c '{py_code}'")
        
        logger.info(f"Stdout:\n{stdout.strip()}")
            
    except Exception as e:
        logger.error(f"AIO Sandbox Execution Failed: {e}")
    finally:
        if sandbox_id:
            logger.info("Destroying sandbox container...")
            provider.destroy(sandbox_id)
        logger.info("Shutting down AIO provider")
        try:
            provider.shutdown()
        except:
            pass


def main():
    print("DeerFlow 内部可配置组件 (Sandbox/Guardrails) 直接调用调试工具")
    print("此工具将绕过 API 网络层与 config.yaml 的限制直接测试核心组件。")
    print("您可以分别在这个脚本的函数中设置断点来深入理解组件源码。\n")
    
    # 1. 测本地沙箱
    test_local_sandbox_direct()
    
    # 2. 测Docker沙箱
    print("\n\n正在准备测试 Docker 沙箱。如果本地没有 Docker，此测试会抛出错误并跳过。")
    test_aio_sandbox_direct()
    
if __name__ == "__main__":
    main()

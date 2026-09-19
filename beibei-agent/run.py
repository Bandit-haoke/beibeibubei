"""
背备不悲 · beibei-agent 启动入口

PyCharm 里直接右键本文件 → Run 'run'，或命令行：
    D:\\conda-envs\\beibei\\python.exe run.py

不要用 uvicorn 命令行参数覆盖端口，端口统一由 .env 的 AGENT_PORT 控制。
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

# 确保以 beibei-agent 目录为工作目录，这样 .env 一定被读到
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    print("=" * 68)
    print("  背备不悲 · beibei-agent")
    print("=" * 68)
    print(f"  监听地址   : http://{settings.agent_host}:{settings.agent_port}")
    print(f"  接口文档   : http://{settings.agent_host}:{settings.agent_port}/docs")
    print(f"  MySQL      : {settings.mysql_host}:{settings.mysql_port}/{settings.mysql_db}")
    print(f"  Milvus     : {settings.milvus_host}:{settings.milvus_port}")
    print(f"  向量模型   : {settings.embedding_model} (dim={settings.embedding_dim})")
    print(f"  LLM        : {settings.llm_provider} / {settings.deepseek_model}")
    print(f"  上传目录   : {settings.upload_dir}")
    print("=" * 68)

    uvicorn.run(
        "app.main:app",
        host=settings.agent_host,
        port=settings.agent_port,
        reload=settings.debug,
        reload_dirs=[str(ROOT / "app")],
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

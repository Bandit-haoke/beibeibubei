"""
背备不悲 · beibei-agent 应用入口

定位：AI 能力层。只在内网（127.0.0.1:8000）暴露，由 Java 侧带 X-Internal-Token 调用。
浏览器永远不直连本服务。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.logging import get_logger, setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    logger.info("=" * 62)
    logger.info("背备不悲 · beibei-agent 启动中 ...")
    logger.info("=" * 62)

    # --- 上传目录 ---
    upload_path = Path(settings.upload_dir)
    try:
        upload_path.mkdir(parents=True, exist_ok=True)
        logger.info("上传目录就绪: %s", upload_path)
    except OSError as exc:
        logger.warning("上传目录不可用 %s: %s", upload_path, exc)

    # --- MySQL（失败不阻塞启动，便于逐步排障）---
    from app.db import milvus, mysql

    mysql_health = mysql.health()
    if mysql_health.get("ok"):
        logger.info(
            "✓ MySQL 就绪: %s · %d 张表",
            mysql_health.get("version"),
            mysql_health.get("tableCount", 0),
        )
    else:
        logger.warning(
            "✗ MySQL 未就绪: %s",
            mysql_health.get("error") or mysql_health.get("hint"),
        )

    # --- Milvus 连接与集合引导 ---
    milvus_health = milvus.health()
    if milvus_health.get("ok"):
        logger.info("✓ Milvus 就绪: %s", milvus_health.get("uri"))
        try:
            info = milvus.ensure_collection()
            logger.info(
                "  集合 %s %s，混合检索=%s",
                info["collection"],
                "已创建" if info["created"] else "已存在",
                "开启" if info["bm25"] else "关闭",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("  集合引导失败（不阻塞启动）: %s: %s", type(exc).__name__, exc)
    else:
        logger.warning("✗ Milvus 未就绪: %s", milvus_health.get("error"))

    logger.info("-" * 62)
    logger.info("服务地址: http://%s:%s", settings.agent_host, settings.agent_port)
    logger.info("接口文档: http://%s:%s/docs", settings.agent_host, settings.agent_port)
    logger.info("=" * 62)

    yield

    logger.info("beibei-agent 正在停止 ...")
    milvus.close_client()
    mysql.dispose_engine()
    logger.info("beibei-agent 已停止")


app = FastAPI(
    title="背备不悲 · AI 智能体",
    description="背得会 · 备得全 · 考不悲 —— 文档入库、知识点分类、出题、判分、语音转写",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# 本服务只监听 127.0.0.1，放开 CORS 纯粹是为了本机浏览器调试 /docs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未捕获异常 %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "msg": f"{type(exc).__name__}: {exc}", "data": None},
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, object]:
    return {
        "service": "beibei-agent",
        "name": "背备不悲 · AI 智能体",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/v1/health",
        "chunkCollection": settings.chunk_collection,
    }

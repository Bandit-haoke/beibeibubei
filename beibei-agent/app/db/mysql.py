"""
背备不悲 · MySQL 连接（与 Java 共用同一个 beibei 库）

分工：Java 独占写业务表（知识库/文档/题目/答卷/错题），
     Python 只写 AI 相关表（分块、标签、题目生成、判分明细、调用日志）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.mysql_url,
            pool_pre_ping=True,   # 断线自动重连（虚拟机休眠后常见）
            pool_recycle=3600,
            pool_size=5,
            max_overflow=10,
            echo=False,
            future=True,
        )
        logger.info(
            "MySQL 引擎已创建: %s:%s/%s",
            settings.mysql_host,
            settings.mysql_port,
            settings.mysql_db,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


def session_scope() -> Session:
    """用法： with session_scope() as s: ...  自动 commit / rollback / close"""
    return get_session_factory()()


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _session_factory = None


# ---------------------------------------------------------------------------
#  健康检查
# ---------------------------------------------------------------------------

EXPECTED_TABLES = [
    "bb_user", "bb_knowledge_base", "bb_document", "bb_doc_chunk", "bb_tag",
    "bb_chunk_tag", "bb_question", "bb_question_option", "bb_question_tag",
    "bb_paper", "bb_paper_item", "bb_exam_record", "bb_answer_item",
    "bb_mistake", "bb_review_log", "bb_ai_provider", "bb_model_route",
    "bb_prompt_template", "bb_ai_call_log", "bb_async_task", "bb_setting",
    # M6 模拟面试（docs/sql/interview.sql）
    "bb_resume", "bb_interview", "bb_interview_turn",
    # M7 面经（docs/sql/interview_note.sql）
    "bb_interview_note", "bb_interview_note_turn",
]


def health() -> dict[str, Any]:
    settings = get_settings()
    result: dict[str, Any] = {
        "ok": False,
        "host": f"{settings.mysql_host}:{settings.mysql_port}",
        "database": settings.mysql_db,
    }
    try:
        with get_engine().connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            found = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT TABLE_NAME FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA = :db"
                    ),
                    {"db": settings.mysql_db},
                )
            }
            missing = [t for t in EXPECTED_TABLES if t not in found]

            result.update(
                ok=len(missing) == 0,
                version=version,
                tableCount=len(found),
                expectedCount=len(EXPECTED_TABLES),
                missingTables=missing,
            )
            if missing:
                result["hint"] = (
                    f"缺少 {len(missing)} 张表，请执行 docs/sql/schema.sql 建表"
                )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["hint"] = "检查 MySQL 是否启动、密码是否正确、库 beibei 是否已创建"
    return result


def count_rows(table: str) -> int:
    with get_engine().connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0)

"""背备不悲 · v1 路由汇总"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    asr,
    grade,
    health,
    ingest,
    interview,
    interview_note,
    question,
    search,
    tags,
    vectors,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(ingest.router)
api_router.include_router(vectors.router)
api_router.include_router(search.router)
api_router.include_router(tags.router)
api_router.include_router(question.router)
api_router.include_router(grade.router)
api_router.include_router(asr.router)
api_router.include_router(interview.router)
api_router.include_router(interview_note.router)

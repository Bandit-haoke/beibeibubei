"""背备不悲 · 判分接口"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.security import verify_internal_token
from app.core.sse import stream_from_worker
from app.services.grading import run_grade

router = APIRouter(tags=["判分"])

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive",
               "X-Accel-Buffering": "no"}


class GradeRequest(BaseModel):
    """与 Java 侧 GradingRunner 的 payload 对应。"""

    taskId: int = 0
    examId: int


class AppealRequest(BaseModel):
    taskId: int = 0
    examId: int
    answerItemId: int
    appealReason: str = ""


@router.post("/grade", summary="交卷判分（SSE 推进度）")
async def grade(req: GradeRequest, _: None = Depends(verify_internal_token)) -> StreamingResponse:
    payload = req.model_dump()
    return StreamingResponse(
        stream_from_worker(lambda emit: run_grade(payload, emit)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/appeal-regrade", summary="申诉重判单题（SSE）")
async def appeal(req: AppealRequest, _: None = Depends(verify_internal_token)) -> StreamingResponse:
    payload = req.model_dump()
    return StreamingResponse(
        stream_from_worker(lambda emit: run_grade(payload, emit)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )

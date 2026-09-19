"""背备不悲 · 出题接口"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.security import verify_internal_token
from app.core.sse import stream_from_worker
from app.services.question_gen import (
    DIFF_LABEL,
    Q_TYPE_LABEL,
    run_generate,
)

router = APIRouter(tags=["出题"])

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive",
               "X-Accel-Buffering": "no"}


class GenerateRequest(BaseModel):
    """与 Java 侧 GenerationRunner 的 payload 字段一一对应。"""

    taskId: int = 0
    paperId: int = 0
    kbId: int
    count: int = Field(default=10, ge=1, le=60)
    tagIds: list[int] | None = None
    includeChildTags: bool = True
    qTypeRatio: dict[str, float] | None = None
    difficultyRatio: dict[str, float] | None = None
    selfCheck: bool = True
    providerId: int | None = None
    collection: str | None = None
    partition: str | None = None


@router.post("/generate-questions", summary="AI 出题（SSE 推进度）")
async def generate(req: GenerateRequest, _: None = Depends(verify_internal_token)) -> StreamingResponse:
    payload = req.model_dump()
    return StreamingResponse(
        stream_from_worker(lambda emit: run_generate(payload, emit)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/question-meta", summary="题型与难度字典（前端下拉用）")
def meta(_: None = Depends(verify_internal_token)) -> dict[str, Any]:
    return {
        "ok": True,
        "qTypes": [
            {"code": code, "value": value, "label": _type_label(code)}
            for code, value in sorted(Q_TYPE_LABEL.items())
        ],
        "difficulties": [{"value": k, "label": v} for k, v in DIFF_LABEL.items()],
        "defaultTypeRatio": {"SINGLE": 0.4, "JUDGE": 0.2, "BLANK": 0.2, "SHORT": 0.2},
        "defaultDifficultyRatio": {"EASY": 0.3, "MEDIUM": 0.5, "HARD": 0.2},
    }


_TYPE_LABELS = {
    "SINGLE": "单选题", "MULTI": "多选题", "JUDGE": "判断题", "BLANK": "填空题",
    "TERM": "名词解释", "SHORT": "简答题", "ESSAY": "论述题", "CODE": "代码题",
    "COMPARE": "对比辨析",
}


def _type_label(code: str) -> str:
    return _TYPE_LABELS.get(code, code)

"""背备不悲 · 面经接口

只有一个接口：
  - `/interview-note/generate`  上传完录音后，把整条「转写 → 分角色 → 清洗 → 成文」流水线
    跑起来。这是重活（一段 30 分钟的录音，转写本身就要几分钟），
    所以走 SSE 推进度，Java 侧建异步任务。

为什么会话里不在这里做上传：音频文件由 Java 落盘（复用 FileStorageService），
Python 只读文件路径 —— 这样文件生命周期只有一处管理，删面经时 Java 也删得干净。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.security import verify_internal_token
from app.core.sse import stream_from_worker
from app.services.interview_note import probe_lfasr, run_generate_note

logger = get_logger(__name__)

router = APIRouter(tags=["面经"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class GenerateRequest(BaseModel):
    taskId: int = 0
    noteId: int
    filePath: str = Field(default="", description="相对上传目录的路径，Java 落盘时写入")
    fileName: str = ""
    company: str = ""
    position: str = ""


class ProbeRequest(BaseModel):
    providerId: int | None = Field(default=None, description="要测的 AI 配置 id，留空则自动挑一条")


@router.post("/interview-note/probe", summary="测试语音转写凭据（只调 prepare，不消耗转写时长）")
def interview_note_probe(
    req: ProbeRequest, _: None = Depends(verify_internal_token)
) -> dict:
    return probe_lfasr(req.providerId)


@router.post("/interview-note/generate", summary="把面试录音整理成面经（SSE 推进度）")
async def interview_note_generate(
    req: GenerateRequest, _: None = Depends(verify_internal_token)
) -> StreamingResponse:
    payload = req.model_dump()
    logger.info("面经生成请求 noteId=%s file=%s", req.noteId, req.filePath or req.fileName)
    return StreamingResponse(
        stream_from_worker(lambda emit: run_generate_note(payload, emit)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )

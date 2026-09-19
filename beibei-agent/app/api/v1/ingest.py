"""背备不悲 · 文档入库接口（SSE 流式）"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.security import verify_internal_token
from app.core.sse import stream_from_worker
from app.services.ingest import run_ingest

router = APIRouter(tags=["入库"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # 关键：告诉 nginx / 反向代理不要缓冲，否则 SSE 会被攒着一起发
    "X-Accel-Buffering": "no",
}


class IngestRequest(BaseModel):
    """与 Java 侧 IngestRunner 的 payload 字段一一对应。"""

    taskId: int = 0
    kbId: int
    docId: int
    fileName: str = ""
    filePath: str | None = Field(default=None, description="文件绝对路径")
    textContent: str | None = Field(default=None, description="手动粘贴的文本，优先于 filePath")
    fileType: str = ""
    sourceType: int = 1
    collection: str | None = None
    partition: str | None = None
    chunkSize: int = 700
    chunkOverlap: int = 105


@router.post("/ingest", summary="解析文档并入库（SSE 推进度）")
async def ingest(req: IngestRequest, _: None = Depends(verify_internal_token)) -> StreamingResponse:
    payload = req.model_dump()
    return StreamingResponse(
        stream_from_worker(lambda emit: run_ingest(payload, emit)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )

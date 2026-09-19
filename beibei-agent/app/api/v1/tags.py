"""背备不悲 · 知识点接口"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text as sql_text

from app.core.security import verify_internal_token
from app.core.sse import stream_from_worker
from app.db.mysql import get_engine
from app.services.tagging import tagging_service

router = APIRouter(tags=["知识点"], prefix="/tags")

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive",
               "X-Accel-Buffering": "no"}


class ExtractRequest(BaseModel):
    taskId: int = 0
    kbId: int
    force: bool = False
    sampleText: str | None = None


@router.get("/tree", summary="知识点树")
def tree(kb_id: int = Query(alias="kbId"),
         _: None = Depends(verify_internal_token)) -> dict[str, Any]:
    tags = tagging_service.list_tags(kb_id)
    by_parent: dict[int, list[dict]] = {}
    for tag in tags:
        by_parent.setdefault(tag["parentId"], []).append(tag)

    def build(parent_id: int) -> list[dict]:
        out = []
        for node in by_parent.get(parent_id, []):
            out.append({
                "id": node["id"],
                "name": node["name"],
                "level": node["level"],
                "description": node["description"],
                "children": build(node["id"]),
            })
        return out

    return {"ok": True, "kbId": kb_id, "count": len(tags), "tree": build(0)}


@router.post("/extract", summary="让 AI 重新抽取知识点树（SSE）")
async def extract(req: ExtractRequest, _: None = Depends(verify_internal_token)) -> StreamingResponse:
    def work(emit) -> None:
        emit("progress", {"progress": 10, "stage": "正在准备文档大纲"})
        sample = req.sampleText or _sample_from_kb(req.kbId)
        kb_name = _kb_name(req.kbId)

        emit("progress", {"progress": 35, "stage": "正在调用大模型抽取知识点"})
        result = tagging_service.extract_tag_tree(req.kbId, kb_name, sample, force=req.force)

        if result.get("skipped"):
            emit("done", {
                "kbId": req.kbId, "created": 0, "skipped": True,
                "reason": result.get("reason", ""),
            })
            return

        emit("done", {
            "kbId": req.kbId, "created": result.get("created", 0), "skipped": False,
            "tagCount": _count_tags(req.kbId),
        })

    return StreamingResponse(stream_from_worker(work), media_type="text/event-stream",
                             headers=SSE_HEADERS)


def _sample_from_kb(kb_id: int) -> str:
    """没传 sampleText 时，从该知识库已入库的分块里拼一份大纲出来。"""
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                sql_text(
                    "SELECT section_path, content FROM bb_doc_chunk "
                    "WHERE kb_id = :kb ORDER BY doc_id, chunk_index LIMIT 120"
                ),
                {"kb": kb_id},
            ).fetchall()
    except Exception:  # noqa: BLE001
        return ""

    sections: list[str] = []
    bodies: list[str] = []
    for section, content in rows:
        if section and (not sections or sections[-1] != section):
            sections.append(section)
        if len("\n".join(bodies)) < 3000:
            bodies.append(content or "")

    return ("\n".join(dict.fromkeys(sections)) + "\n\n" + "\n".join(bodies))[:6000]


def _kb_name(kb_id: int) -> str:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sql_text("SELECT name FROM bb_knowledge_base WHERE id = :id"), {"id": kb_id}
            ).fetchone()
            return str(row[0]) if row else f"知识库{kb_id}"
    except Exception:  # noqa: BLE001
        return f"知识库{kb_id}"


def _count_tags(kb_id: int) -> int:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sql_text("SELECT COUNT(*) FROM bb_tag WHERE kb_id = :kb"), {"kb": kb_id}
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001
        return 0

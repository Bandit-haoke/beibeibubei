"""背备不悲 · 混合检索接口（检索调试页 + RAG 出题共用）"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text

from app.core.logging import get_logger
from app.core.security import verify_internal_token
from app.db.mysql import get_engine
from app.services.embedding import embedding_service
from app.services.vectorstore import vector_store

logger = get_logger(__name__)
router = APIRouter(tags=["检索"])


class SearchRequest(BaseModel):
    kbId: int
    query: str = Field(min_length=1, description="查询文本")
    topK: int = 8
    tagIds: list[int] | None = None
    docIds: list[int] | None = None
    enrich: bool = Field(default=True, description="是否回表补充分块定位信息与文档名")


@router.post("/search", summary="混合检索（稠密 + BM25 + RRF）")
def search(req: SearchRequest, _: None = Depends(verify_internal_token)) -> dict[str, Any]:
    try:
        query_vector = embedding_service.encode_one(req.query)
    except Exception as exc:  # noqa: BLE001
        # 向量模型没装/没加载时，退化为只用 BM25 的提示
        logger.warning("查询向量化失败：%s", exc)
        return {
            "ok": False,
            "error": f"向量模型不可用：{type(exc).__name__}: {exc}",
            "hint": "执行 pip install -r requirements-ai.txt 安装 torch 与 sentence-transformers",
            "hits": [],
        }

    hits = vector_store.search(
        req.kbId, req.query, query_vector,
        top_k=req.topK, tag_ids=req.tagIds, doc_ids=req.docIds,
    )

    if req.enrich and hits:
        _enrich(hits)

    return {
        "ok": True,
        "query": req.query,
        "kbId": req.kbId,
        "count": len(hits),
        "source": hits[0]["source"] if hits else "none",
        "hits": hits,
    }


def _enrich(hits: list[dict[str, Any]]) -> None:
    """把 pk 回表成 bb_doc_chunk / bb_document 的定位信息，前端才能展示出处。"""
    pks = [int(h["pk"]) for h in hits if h.get("pk") is not None]
    if not pks:
        return

    placeholders = ",".join(f":p{i}" for i in range(len(pks)))
    params = {f"p{i}": pk for i, pk in enumerate(pks)}

    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                sql_text(
                    f"SELECT c.id, c.chunk_index, c.page_no, c.section_path, "
                    f"       c.doc_id, d.file_name "
                    f"FROM bb_doc_chunk c LEFT JOIN bb_document d ON d.id = c.doc_id "
                    f"WHERE c.id IN ({placeholders})"
                ),
                params,
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.debug("回表补全失败：%s", exc)
        return

    info = {
        int(r[0]): {
            "chunkIndex": int(r[1] or 0),
            "pageNo": int(r[2] or 0),
            "sectionPath": r[3] or "",
            "docId": int(r[4] or 0),
            "fileName": r[5] or "",
        }
        for r in rows
    }

    for hit in hits:
        meta = info.get(int(hit["pk"])) if hit.get("pk") is not None else None
        if meta:
            hit.update(meta)


@router.post("/embed", summary="文本向量化（调试用）")
def embed(body: dict, _: None = Depends(verify_internal_token)) -> dict[str, Any]:
    texts = body.get("texts") or []
    if not isinstance(texts, list) or not texts:
        return {"ok": False, "error": "texts 不能为空"}
    try:
        vectors = embedding_service.encode([str(t) for t in texts])
        return {
            "ok": True,
            "count": len(vectors),
            "dim": len(vectors[0]) if vectors else 0,
            "preview": [round(v, 6) for v in (vectors[0][:8] if vectors else [])],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

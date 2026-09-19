"""
背备不悲 · 文档入库流水线

完整链路（每一步都会通过 SSE 汇报进度）：

   解析 → 分块 → 写 MySQL 分块表 → 抽知识点树 → 向量化 → 写 Milvus → 分块打标

设计原则：**关键路径不能因为 LLM 不可用而中断**。
抽知识点、分块打标这两步依赖大模型，没有 API Key 时会自动跳过并记日志，
文档照样完成解析与向量化，检索照样能用（只是没有知识点标签）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text as sql_text

from app.core.logging import get_logger
from app.core.sse import EmitFn
from app.db import milvus as milvus_db
from app.db.mysql import get_engine
from app.services.chunking import chunk_blocks
from app.services.embedding import embedding_service
from app.services.parsing import parse
from app.services.tagging import tagging_service
from app.services.vectorstore import vector_store

logger = get_logger(__name__)

EMBED_BATCH = 32


def run_ingest(payload: dict[str, Any], emit: EmitFn) -> None:
    """入库主流程。由 app/core/sse.py 放进子线程执行。"""
    task_id = int(payload.get("taskId") or 0)
    kb_id = int(payload.get("kbId") or 0)
    doc_id = int(payload.get("docId") or 0)
    file_name = payload.get("fileName") or ""
    file_path = payload.get("filePath")
    text_content = payload.get("textContent")
    file_type = (payload.get("fileType") or "").lower()
    chunk_size = int(payload.get("chunkSize") or 700)
    chunk_overlap = int(payload.get("chunkOverlap") or 105)

    logger.info("=== 开始入库 task=%s kb=%s doc=%s file=%s ===", task_id, kb_id, doc_id, file_name)

    try:
        # ---------------- 1. 解析 ----------------
        emit("progress", {"progress": 3, "stage": "正在读取文档"})
        parsed = parse(file_path=file_path, file_type=file_type,
                       text_content=text_content, file_name=file_name)

        if parsed.is_empty:
            raise ValueError("没能从文档里解析出任何文字。如果是扫描版 PDF 或照片，"
                             "请确认已安装 OCR 依赖（paddlepaddle / paddleocr）")

        emit("progress", {
            "progress": 15,
            "stage": f"解析完成：{parsed.page_count or '-'} 页 / {parsed.char_count} 字"
                     + ("（使用了 OCR）" if parsed.used_ocr else ""),
        })
        for warning in parsed.warnings[:5]:
            logger.warning("解析告警：%s", warning)

        # ---------------- 2. 分块 ----------------
        emit("progress", {"progress": 18, "stage": "正在切分文本"})
        chunks = chunk_blocks(parsed.blocks, target_size=chunk_size, overlap=chunk_overlap)
        if not chunks:
            raise ValueError("分块结果为空，文档内容可能异常")

        emit("progress", {"progress": 28, "stage": f"已切分为 {len(chunks)} 个分块"})

        # ---------------- 3. 清掉旧数据（支持重新解析） ----------------
        _clear_previous(kb_id, doc_id)

        # ---------------- 4. 写 MySQL 分块表 ----------------
        chunk_ids = _insert_chunks(kb_id, doc_id, chunks)
        logger.info("已写入 %d 条分块记录", len(chunk_ids))

        # ---------------- 5. 抽知识点树 ----------------
        emit("progress", {"progress": 35, "stage": "正在抽取知识点"})
        tag_result = tagging_service.extract_tag_tree(kb_id, _kb_name(kb_id), _outline_sample(parsed))
        if tag_result.get("skipped"):
            logger.info("知识点抽取被跳过：%s", tag_result.get("reason"))

        # ---------------- 6. 向量化 ----------------
        emit("progress", {"progress": 42, "stage": "正在向量化（首次会加载模型，可能要等十几秒）"})
        vectors = _embed_all(chunks, emit)

        # ---------------- 7. 分块打标（必须在写 Milvus 之前）----------------
        # ⚠️ 顺序很关键：Milvus 的 tag_ids 是标量字段，**只在 insert 时能写入**。
        # 集合 schema 没设 nullable / default_value，事后只 upsert tag_ids 会被拒绝：
        #   DataNotMatchException: Insert missed an field `vector`
        # 所以先打标拿到 tag_ids，再带着它一起入库，一次写对。
        emit("progress", {"progress": 86, "stage": "正在给分块打知识点标签"})
        tag_map = _tag_chunks(kb_id, chunk_ids, chunks, vectors, emit)

        # ---------------- 8. 写 Milvus ----------------
        emit("progress", {"progress": 92, "stage": "正在写入向量库"})
        rows = [
            {
                "pk": chunk_ids[i],
                "vector": vectors[i],
                "text": chunks[i].content,
                "doc_id": doc_id,
                "kb_id": kb_id,
                "chunk_index": chunks[i].index,
                "tag_ids": tag_map.get(chunk_ids[i], []),
            }
            for i in range(len(chunks))
            if i < len(vectors) and vectors[i]
        ]
        vector_store.ensure_collection()
        inserted = vector_store.insert_chunks(kb_id, rows)
        tag_count = len(tag_map)

        # ---------------- 9. 收尾 ----------------
        _update_document_stats(doc_id, len(chunks), parsed)

        has_sparse = vector_store._has_sparse()  # noqa: SLF001
        emit("done", {
            "docId": doc_id,
            "kbId": kb_id,
            "chunkCount": len(chunks),
            "vectorCount": inserted,
            "charCount": parsed.char_count,
            "pageCount": parsed.page_count,
            "tagCount": _count_tags(kb_id),
            "chunkTagCount": tag_count,
            "usedOcr": parsed.used_ocr,
            "hybridSearch": has_sparse,
            "degraded": not has_sparse,
        })
        logger.info("=== 入库完成 doc=%s 分块=%d 向量=%d ===", doc_id, len(chunks), inserted)

    except Exception as exc:  # noqa: BLE001
        logger.exception("入库失败 task=%s doc=%s", task_id, doc_id)
        emit("error", {"errorMsg": f"{type(exc).__name__}: {exc}", "docId": doc_id})


# ---------------------------------------------------------------------------
#  各步骤实现
# ---------------------------------------------------------------------------

def _clear_previous(kb_id: int, doc_id: int) -> None:
    """删除该文档已有的分块与向量（重新解析时用）。"""
    try:
        with get_engine().begin() as conn:
            deleted = conn.execute(
                sql_text("DELETE FROM bb_doc_chunk WHERE doc_id = :doc"), {"doc": doc_id}
            ).rowcount
        if deleted:
            logger.info("清理旧分块 %d 条", deleted)
            vector_store.delete_by_doc(kb_id, doc_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("清理旧数据失败（不阻塞）：%s", exc)


def _insert_chunks(kb_id: int, doc_id: int, chunks) -> list[int]:
    """写 bb_doc_chunk，返回自增主键列表（同时也是 Milvus 的 pk）。"""
    ids: list[int] = []
    with get_engine().begin() as conn:
        for chunk in chunks:
            result = conn.execute(
                sql_text(
                    "INSERT INTO bb_doc_chunk "
                    "(doc_id, kb_id, chunk_index, content, token_count, page_no, "
                    " section_path, char_start, char_end, milvus_pk) "
                    "VALUES (:doc, :kb, :idx, :content, :tokens, :page, "
                    " :section, :cs, :ce, 0)"
                ),
                {
                    "doc": doc_id, "kb": kb_id, "idx": chunk.index,
                    "content": chunk.content, "tokens": chunk.token_count,
                    "page": chunk.page_no or 0, "section": (chunk.section_path or "")[:500],
                    "cs": chunk.char_start, "ce": chunk.char_end,
                },
            )
            chunk_id = int(result.lastrowid)
            ids.append(chunk_id)
        # milvus_pk 与主键一致，回填一次方便对账
        if ids:
            conn.execute(
                sql_text("UPDATE bb_doc_chunk SET milvus_pk = id WHERE doc_id = :doc"),
                {"doc": doc_id},
            )
    return ids


def _embed_all(chunks, emit: EmitFn) -> list[list[float]]:
    """
    分批向量化，边做边报进度（42% → 85%）。

    ⚠️ **按长度排序后再分批**，这是 CPU 上的关键优化：
    sentence-transformers 会把一个批次里的所有文本 padding 到**本批最长**，
    而分块长度差得很远（实测最短 445 字、最长 2280 字）。
    不排序时，一个长块混进批次就会让同批 31 个短块白算几倍。
    排序后同批长度接近，padding 浪费能从 2 倍以上降到接近 1。

    结果是按原始顺序返回的，排序只影响批次划分，不影响向量与分块的对应关系。
    """
    total = len(chunks)
    if total == 0:
        return []

    order = sorted(range(total), key=lambda i: len(chunks[i].content))
    vectors: list[list[float]] = [[] for _ in range(total)]
    done = 0

    for start in range(0, total, EMBED_BATCH):
        indices = order[start:start + EMBED_BATCH]
        texts = [chunks[i].content for i in indices]

        batch_vectors = embedding_service.encode(texts, batch_size=len(texts))
        for k, index in enumerate(indices):
            if k < len(batch_vectors):
                vectors[index] = batch_vectors[k]

        done += len(indices)
        ratio = done / total
        emit("progress", {
            "progress": int(42 + 43 * ratio),
            "stage": f"正在向量化 {done}/{total} 块"
                     + (f"（本批最长 {max(len(t) for t in texts)} 字）" if total > 50 else ""),
        })

    return vectors


def _tag_chunks(kb_id: int, chunk_ids: list[int], chunks, vectors, emit: EmitFn) -> dict[int, list[int]]:
    """
    分块打标，返回 {chunkId: [tagId]}。

    注意：**不在这里写 Milvus**。tag_ids 会跟着分块向量在下一步一起 insert，
    因为 Milvus 集合没设 nullable，事后部分字段 upsert 会被拒绝。
    """
    if not tagging_service.has_tags(kb_id):
        logger.info("没有知识点，跳过分块打标")
        return {}

    items = [
        {"chunkId": chunk_ids[i], "content": chunks[i].content, "vector": vectors[i]}
        for i in range(min(len(chunk_ids), len(chunks), len(vectors)))
    ]

    def on_llm_progress(done: int, total: int) -> None:
        emit("progress", {
            "progress": min(90, int(86 + 4 * done / max(1, total))),
            "stage": f"大模型复核打标 {done}/{total}",
        })

    try:
        mapping = tagging_service.tag_chunks(kb_id, items, use_llm=True, emit_progress=on_llm_progress)
    except Exception as exc:  # noqa: BLE001
        logger.warning("分块打标失败（不阻塞入库）：%s", exc)
        return {}

    if not mapping:
        return {}

    tagging_service.save_chunk_tags(kb_id, mapping)
    return mapping


def _update_document_stats(doc_id: int, chunk_count: int, parsed) -> None:
    try:
        with get_engine().begin() as conn:
            conn.execute(
                sql_text(
                    "UPDATE bb_document SET chunk_count = :cc, char_count = :chc, "
                    "page_count = :pc, status = 2, error_msg = '' WHERE id = :id"
                ),
                {"cc": chunk_count, "chc": parsed.char_count, "pc": parsed.page_count, "id": doc_id},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("更新文档统计失败：%s", exc)


def _count_tags(kb_id: int) -> int:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sql_text("SELECT COUNT(*) FROM bb_tag WHERE kb_id = :kb"), {"kb": kb_id}
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001
        return 0


def _kb_name(kb_id: int) -> str:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sql_text("SELECT name FROM bb_knowledge_base WHERE id = :id"), {"id": kb_id}
            ).fetchone()
            return str(row[0]) if row else f"知识库{kb_id}"
    except Exception:  # noqa: BLE001
        return f"知识库{kb_id}"


def _outline_sample(parsed) -> str:
    """
    给知识点抽取用的样本：先用标题路径当大纲，不够再补正文。
    大纲比正文更能反映知识体系，而且省 token。
    """
    sections: list[str] = []
    for block in parsed.blocks:
        path = (block.section_path or "").strip()
        if path and (not sections or sections[-1] != path):
            sections.append(path)
    outline = "\n".join(dict.fromkeys(sections))

    if len(outline) >= 800:
        return outline[:6000]
    return (outline + "\n\n" + parsed.full_text[:6000])[:6000]

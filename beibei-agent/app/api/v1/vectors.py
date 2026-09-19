"""背备不悲 · 向量库运维接口（分区管理、按文档删除向量）"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import get_settings
from app.core.logging import get_logger
from app.core.security import verify_internal_token
from app.db import milvus as milvus_db

logger = get_logger(__name__)
router = APIRouter(tags=["向量库"], prefix="/vectors")


class PartitionRequest(BaseModel):
    collection: str | None = None
    partition: str | None = None
    kbId: int | None = None


class DeleteVectorsRequest(PartitionRequest):
    docId: int


def _resolve_collection(name: str | None) -> str:
    return name or get_settings().chunk_collection


def _resolve_partition(req: PartitionRequest) -> str | None:
    if req.partition:
        return req.partition
    if req.kbId is not None:
        return get_settings().partition(int(req.kbId))
    return None


@router.post("/ensure-partition", summary="确保分区存在（幂等）")
def ensure_partition(req: PartitionRequest, _: None = Depends(verify_internal_token)) -> dict:
    collection = _resolve_collection(req.collection)
    partition = _resolve_partition(req)
    if not partition:
        return {"ok": False, "error": "缺少 partition 或 kbId"}
    try:
        info = milvus_db.ensure_partition_named(collection, partition)
        return {"ok": True, **info}
    except Exception as exc:  # noqa: BLE001
        logger.warning("确保分区失败：%s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/drop-partition", summary="删除分区（连带分区内所有向量）")
def drop_partition(req: PartitionRequest, _: None = Depends(verify_internal_token)) -> dict:
    collection = _resolve_collection(req.collection)
    partition = _resolve_partition(req)
    if not partition:
        return {"ok": False, "error": "缺少 partition 或 kbId"}
    try:
        dropped = milvus_db.drop_partition_named(collection, partition)
        return {
            "ok": True, "collection": collection, "partition": partition, "dropped": dropped,
            "message": "" if dropped else "分区不存在，无需删除",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除分区失败：%s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/delete", summary="按 docId 删除向量")
def delete_vectors(req: DeleteVectorsRequest, _: None = Depends(verify_internal_token)) -> dict:
    collection = _resolve_collection(req.collection)
    partition = _resolve_partition(req)
    try:
        client = milvus_db.get_client()
        kwargs = {"collection_name": collection, "filter": f"doc_id == {int(req.docId)}"}
        if partition:
            kwargs["partition_name"] = partition
        result = client.delete(**kwargs)
        count = int(result.get("delete_count", 0) or 0) if isinstance(result, dict) else 0
        logger.info("已删除 doc_id=%s 的 %s 条向量", req.docId, count)
        return {"ok": True, "deleted": count, "docId": req.docId}
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除向量失败：%s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/stats", summary="向量库概览")
def stats(_: None = Depends(verify_internal_token)) -> dict:
    settings = get_settings()
    try:
        client = milvus_db.get_client()
        collections = list(client.list_collections())
        row_count = 0
        if settings.chunk_collection in collections:
            stat = client.get_collection_stats(collection_name=settings.chunk_collection)
            row_count = int(stat.get("row_count", 0) or 0)
        return {
            "ok": True,
            "uri": settings.milvus_uri,
            "collection": settings.chunk_collection,
            "collections": collections,
            "rowCount": row_count,
            "hybridSearch": milvus_db._collection_has_sparse(  # noqa: SLF001
                client, settings.chunk_collection) if settings.chunk_collection in collections else False,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
#  一致性校验
# ---------------------------------------------------------------------------

QUERY_PAGE = 16000


def _scan_consistency() -> dict:
    """
    比对 MySQL 分块表与 Milvus 向量：
      - orphan：Milvus 里有、MySQL 里没有 → 删文档时向量没清干净（占空间、污染检索）
      - missing：MySQL 里有、Milvus 里没有 → 入库中途失败（检索不到，需要重新解析）
      - misplaced：向量所在分区与它所属知识库对不上
    """
    from sqlalchemy import text as sql_text

    from app.db.mysql import get_engine

    settings = get_settings()
    client = milvus_db.get_client()
    collection = settings.chunk_collection

    with get_engine().connect() as conn:
        rows = conn.execute(sql_text("SELECT id, kb_id, doc_id FROM bb_doc_chunk")).fetchall()
    mysql_pks = {int(r[0]): (int(r[1]), int(r[2])) for r in rows}

    milvus_pks: dict[int, str] = {}
    partition_errors: list[str] = []

    if collection not in list(client.list_collections()):
        return {
            "ok": True, "collection": collection, "mysqlChunks": len(mysql_pks),
            "milvusVectors": 0, "orphanCount": 0, "missingCount": 0,
            "orphanPks": [], "missingPks": [], "partitionErrors": [],
            "hint": "向量集合尚未创建",
        }

    for partition in milvus_db.partition_names(collection):
        if partition.startswith("_"):
            continue
        offset = 0
        while True:
            try:
                batch = client.query(
                    collection_name=collection,
                    filter="",
                    output_fields=["pk"],
                    partition_names=[partition],
                    limit=QUERY_PAGE,
                    offset=offset,
                    # 必须用 Strong：默认的 Bounded 看不到刚刚 delete 掉的数据，
                    # 会让「清理孤儿向量」之后复查仍然报有孤儿（实际已经删了）
                    consistency_level="Strong",
                )
            except Exception as exc:  # noqa: BLE001
                partition_errors.append(f"{partition}: {type(exc).__name__}: {exc}")
                break
            if not batch:
                break
            for item in batch:
                pk = item.get("pk") if isinstance(item, dict) else None
                if pk is not None:
                    milvus_pks[int(pk)] = partition
            if len(batch) < QUERY_PAGE:
                break
            offset += QUERY_PAGE

    orphan = sorted(pk for pk in milvus_pks if pk not in mysql_pks)
    missing = sorted(pk for pk in mysql_pks if pk not in milvus_pks)
    misplaced = []
    for pk, partition in milvus_pks.items():
        if pk in mysql_pks:
            expected = settings.partition(mysql_pks[pk][0])
            if expected != partition:
                misplaced.append({"pk": pk, "actual": partition, "expected": expected})

    return {
        "ok": True,
        "collection": collection,
        "mysqlChunks": len(mysql_pks),
        "milvusVectors": len(milvus_pks),
        "orphanCount": len(orphan),
        "missingCount": len(missing),
        "misplacedCount": len(misplaced),
        # 只回前面若干条，避免响应过大
        "orphanPks": orphan[:100],
        "missingPks": missing[:100],
        "misplaced": misplaced[:50],
        "partitionErrors": partition_errors[:10],
        "healthy": not orphan and not missing and not misplaced and not partition_errors,
    }


@router.get("/consistency", summary="MySQL 分块 ↔ Milvus 向量 一致性校验")
def consistency(_: None = Depends(verify_internal_token)) -> dict:
    try:
        return _scan_consistency()
    except Exception as exc:  # noqa: BLE001
        logger.exception("一致性校验失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/consistency/repair", summary="清理孤儿向量")
def repair_consistency(_: None = Depends(verify_internal_token)) -> dict:
    """
    只删「MySQL 里已经没有对应分块」的向量。
    **不会**去补 missing —— 补向量要重新读原文、重新编码，属于「重新解析」的活，
    应该在文档管理页点「重新解析」，避免这里做出不可预期的结果。
    """
    try:
        report = _scan_consistency()
        if not report.get("ok"):
            return report

        orphan = report.get("orphanPks") or []
        deleted = 0
        settings = get_settings()
        client = milvus_db.get_client()
        if orphan:
            expr = "pk in [" + ",".join(str(int(p)) for p in orphan) + "]"
            try:
                result = client.delete(collection_name=settings.chunk_collection, filter=expr)
                deleted = int(result.get("delete_count", 0) or 0) if isinstance(result, dict) else 0
                # flush 后再复查，否则删除还在队列里没落盘
                client.flush(collection_name=settings.chunk_collection)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "deleted": 0}

        logger.info("一致性修复：清理孤儿向量 %d 条", deleted)
        after = _scan_consistency()
        return {"ok": True, "deleted": deleted, "after": after}
    except Exception as exc:  # noqa: BLE001
        logger.exception("一致性修复失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

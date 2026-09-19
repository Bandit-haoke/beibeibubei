"""
背备不悲 · Milvus 向量读写

集合结构（见 app/db/milvus.py）：
  pk (Int64) = bb_doc_chunk.id      主数据在 MySQL，Milvus 只是索引副本
  vector     = BGE-M3 稠密向量
  sparse     = BM25 稀疏向量，由 text 字段经 Function 自动生成
  text / doc_id / kb_id / chunk_index / tag_ids

检索：稠密 + BM25 双路召回，用 RRF 融合。RRF 不需要归一化两路分数，
对抗「向量分 0.9、BM25 分 12」这种量纲差异天然友好。
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger
from app.db import milvus as milvus_db

logger = get_logger(__name__)

# 每一路召回的候选数，最终融合后取 top_k
RECALL_LIMIT = 30


class VectorStore:

    # ---------------- 结构 ----------------

    def ensure_collection(self) -> dict[str, Any]:
        return milvus_db.ensure_collection()

    def ensure_partition(self, kb_id: int) -> str:
        return milvus_db.ensure_partition(kb_id)

    def drop_partition(self, kb_id: int) -> None:
        settings = get_settings()
        try:
            milvus_db.drop_partition_named(settings.chunk_collection, settings.partition(kb_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除分区失败（kb=%s）：%s", kb_id, exc)

    # ---------------- 写入 ----------------

    def insert_chunks(self, kb_id: int, rows: list[dict[str, Any]]) -> int:
        """
        写入分块向量。

        rows 每项：{pk, vector, text, doc_id, chunk_index, tag_ids}
        ⚠️ 不要传 sparse —— 它由 BM25 Function 从 text 自动生成。
        """
        if not rows:
            return 0

        settings = get_settings()
        client = milvus_db.get_client()
        # 分区必须先存在，否则 insert 会报 partition not found
        self.ensure_partition(kb_id)

        collection = settings.chunk_collection
        has_sparse = self._has_sparse()

        payload = []
        for row in rows:
            item = {
                "pk": int(row["pk"]),
                "vector": row["vector"],
                "text": (row["text"] or "")[:16000],
                "doc_id": int(row["doc_id"]),
                "kb_id": int(row["kb_id"]),
                "chunk_index": int(row["chunk_index"]),
                "tag_ids": [int(t) for t in (row.get("tag_ids") or [])][:16],
            }
            payload.append(item)

        # 分批插入，单批太大容易超时
        batch = 128
        inserted = 0
        for start in range(0, len(payload), batch):
            piece = payload[start:start + batch]
            try:
                client.insert(
                    collection_name=collection,
                    data=piece,
                    partition_name=settings.partition(kb_id),
                )
                inserted += len(piece)
            except Exception as exc:  # noqa: BLE001
                logger.error("写入 Milvus 失败（第 %d 批，共 %d 条）：%s", start // batch + 1, len(piece), exc)
                raise
        logger.info("已写入 Milvus %d 条向量（sparse=%s）", inserted, has_sparse)

        # 关键：Milvus 默认一致性是 Bounded，刚写入的数据可能还查不到。
        # 入库完成后主动 flush 一次，保证「传完就能搜到」。
        try:
            client.flush(collection_name=collection)
        except Exception as exc:  # noqa: BLE001
            logger.debug("flush 失败（不影响写入）：%s", exc)

        return inserted

    # ------------------------------------------------------------------
    #  ⚠️ 这里原本有一个 update_tag_ids()，用来在打标完成后回填 tag_ids 到 Milvus。
    #     实测行不通：集合 schema 的 vector / text 都是非 nullable 且无默认值，
    #     Milvus 拒绝只带部分字段的 upsert：
    #       DataNotMatchException: Insert missed an field `vector`
    #     现在的做法是「先打标、再带着 tag_ids 一起 insert」（见 ingest.py 第 7~8 步），
    #     一次写对，也不需要任何回填。
    # ------------------------------------------------------------------

    def delete_by_doc(self, kb_id: int, doc_id: int) -> int:
        settings = get_settings()
        client = milvus_db.get_client()
        try:
            result = client.delete(
                collection_name=settings.chunk_collection,
                filter=f"doc_id == {int(doc_id)}",
                partition_name=settings.partition(kb_id),
            )
            count = 0
            if isinstance(result, dict):
                count = int(result.get("delete_count", 0) or 0)
            logger.info("已从 Milvus 删除 doc_id=%s 的 %s 条向量", doc_id, count)
            return count
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除向量失败（doc_id=%s）：%s", doc_id, exc)
            return 0

    def delete_by_pks(self, kb_id: int, pks: list[int]) -> None:
        if not pks:
            return
        settings = get_settings()
        client = milvus_db.get_client()
        expr = "pk in [" + ",".join(str(int(p)) for p in pks) + "]"
        try:
            client.delete(collection_name=settings.chunk_collection, filter=expr,
                          partition_name=settings.partition(kb_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("按 pk 删除向量失败：%s", exc)

    # ---------------- 检索 ----------------

    def search(
        self,
        kb_id: int,
        query: str,
        query_vector: list[float],
        *,
        top_k: int | None = None,
        tag_ids: list[int] | None = None,
        doc_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        混合检索：稠密 + BM25，RRF 融合。
        BM25 不可用时自动退化为纯稠密检索。
        """
        settings = get_settings()
        top_k = top_k or settings.rag_top_k
        client = milvus_db.get_client()
        collection = settings.chunk_collection
        partition = settings.partition(kb_id)
        output_fields = ["pk", "text", "doc_id", "chunk_index", "tag_ids"]

        filter_expr = self._build_filter(tag_ids, doc_ids)

        has_sparse = self._has_sparse() and settings.rag_hybrid_enabled
        if not has_sparse:
            return self._dense_only(client, collection, partition, query_vector,
                                    top_k, output_fields, filter_expr)

        from pymilvus import AnnSearchRequest, RRFRanker

        try:
            dense_req = AnnSearchRequest(
                data=[query_vector],
                anns_field="vector",
                param={"metric_type": "COSINE", "params": {"ef": 128}},
                limit=RECALL_LIMIT,
                expr=filter_expr,
            )
            sparse_req = AnnSearchRequest(
                data=[query],
                anns_field="sparse",
                param={"metric_type": "BM25", "params": {}},
                limit=RECALL_LIMIT,
                expr=filter_expr,
            )
            results = client.hybrid_search(
                collection_name=collection,
                reqs=[dense_req, sparse_req],
                ranker=RRFRanker(k=settings.rag_rrf_k),
                limit=top_k,
                output_fields=output_fields,
                partition_names=[partition],
                # Strong：宁可慢一点，也要保证「刚上传的资料立刻能搜到」
                consistency_level="Strong",
            )
            return self._flatten(results, source="hybrid")
        except Exception as exc:  # noqa: BLE001
            logger.warning("混合检索失败，退回纯稠密检索：%s: %s", type(exc).__name__, exc)
            return self._dense_only(client, collection, partition, query_vector,
                                    top_k, output_fields, filter_expr)

    def _dense_only(self, client, collection, partition, query_vector, top_k,
                    output_fields, filter_expr) -> list[dict[str, Any]]:
        try:
            results = client.search(
                collection_name=collection,
                data=[query_vector],
                anns_field="vector",
                search_params={"metric_type": "COSINE", "params": {"ef": 128}},
                limit=top_k,
                output_fields=output_fields,
                partition_names=[partition],
                filter=filter_expr or "",
                consistency_level="Strong",
            )
            return self._flatten(results, source="dense")
        except Exception as exc:  # noqa: BLE001
            logger.error("检索失败：%s: %s", type(exc).__name__, exc)
            return []

    @staticmethod
    def _build_filter(tag_ids: list[int] | None, doc_ids: list[int] | None) -> str:
        clauses: list[str] = []
        if doc_ids:
            clauses.append("doc_id in [" + ",".join(str(int(d)) for d in doc_ids) + "]")
        if tag_ids:
            # Milvus 的数组字段用 array_contains_any 做交集匹配
            ids = ",".join(str(int(t)) for t in tag_ids)
            clauses.append(f"array_contains_any(tag_ids, [{ids}])")
        return " and ".join(clauses)

    @staticmethod
    def _flatten(results, *, source: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not results:
            return out
        for hit in results[0]:
            entity = hit.get("entity") if isinstance(hit, dict) else getattr(hit, "entity", None)
            if entity is None:
                continue
            getter = entity.get if isinstance(entity, dict) else (
                lambda k, e=entity: getattr(e, k, None))
            out.append({
                "pk": getter("pk"),
                "text": getter("text") or "",
                "docId": getter("doc_id"),
                "chunkIndex": getter("chunk_index"),
                "tagIds": list(getter("tag_ids") or []),
                "score": float(hit.get("distance", 0.0)) if isinstance(hit, dict)
                else float(getattr(hit, "distance", 0.0)),
                "source": source,
            })
        return out

    def _has_sparse(self) -> bool:
        settings = get_settings()
        try:
            client = milvus_db.get_client()
            if not client.has_collection(settings.chunk_collection):
                return False
            desc = client.describe_collection(collection_name=settings.chunk_collection)
            return any(f.get("name") == "sparse" for f in desc.get("fields", []))
        except Exception:  # noqa: BLE001
            return False

    # ---------------- 统计 ----------------

    def count(self, kb_id: int) -> int:
        settings = get_settings()
        client = milvus_db.get_client()
        try:
            stats = client.get_collection_stats(collection_name=settings.chunk_collection)
            return int(stats.get("row_count", 0) or 0)
        except Exception:  # noqa: BLE001
            return 0


vector_store = VectorStore()

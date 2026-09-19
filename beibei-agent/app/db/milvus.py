"""
背备不悲 · Milvus 连接与集合管理

集合设计（Milvus 2.5.23）：
  - 一个集合同时放稠密向量（BGE-M3）和 BM25 稀疏向量，混合检索在库内完成
  - 按 embedding 模型分集合（硬约束 1：换向量模型必须重建集合）
  - 按知识库分 partition（检索时指定，天然隔离、召回更准）

⚠️ pymilvus 必须是 2.5.x。3.x 面向 Milvus 3.0，连接 2.5.23 会不兼容。
"""

from __future__ import annotations

import logging
from typing import Any

from pymilvus import DataType, Function, FunctionType, MilvusClient

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: MilvusClient | None = None

TEXT_MAX_LEN = 16384
DEFAULT_PARTITION = "_default"


# ---------------------------------------------------------------------------
#  连接
# ---------------------------------------------------------------------------

def get_client() -> MilvusClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = MilvusClient(uri=settings.milvus_uri, timeout=10)
        logger.info("Milvus 已连接: %s", settings.milvus_uri)
    return _client


def close_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001
            pass
        _client = None


# ---------------------------------------------------------------------------
#  Schema 构建
# ---------------------------------------------------------------------------

def _build_schema(client: MilvusClient, with_bm25: bool):
    settings = get_settings()
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)

    schema.add_field("pk", DataType.INT64, is_primary=True, description="等于 bb_doc_chunk.milvus_pk")
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=settings.embedding_dim, description="BGE-M3 稠密向量")
    schema.add_field(
        "text",
        DataType.VARCHAR,
        max_length=TEXT_MAX_LEN,
        enable_analyzer=True,
        description="分块原文，BM25 分词用",
    )
    if with_bm25:
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR, description="BM25 稀疏向量，由 text 自动生成")
    schema.add_field("doc_id", DataType.INT64)
    schema.add_field("kb_id", DataType.INT64)
    schema.add_field("chunk_index", DataType.INT64)
    schema.add_field("tag_ids", DataType.ARRAY, element_type=DataType.INT64, max_capacity=16)

    if with_bm25:
        schema.add_function(
            Function(
                name="bm25_text",
                function_type=FunctionType.BM25,
                input_field_names=["text"],
                output_field_names=["sparse"],
            )
        )
    return schema


def _build_index_params(client: MilvusClient, with_bm25: bool):
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    if with_bm25:
        index_params.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={"bm25_k1": 1.2, "bm25_b": 0.75},
        )
    return index_params


def _collection_has_sparse(client: MilvusClient, name: str) -> bool:
    try:
        desc = client.describe_collection(collection_name=name)
        return any(f.get("name") == "sparse" for f in desc.get("fields", []))
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
#  集合引导
# ---------------------------------------------------------------------------

def ensure_collection() -> dict[str, Any]:
    """
    确保分块向量集合存在。优先创建「稠密 + BM25 稀疏」的混合检索集合，
    若当前 Milvus 版本不支持 BM25 Function，则自动降级为纯稠密检索。
    """
    settings = get_settings()
    client = get_client()
    name = settings.chunk_collection

    result: dict[str, Any] = {"collection": name, "created": False, "bm25": False, "degraded": False}

    if client.has_collection(name):
        result["bm25"] = _collection_has_sparse(client, name)
        result["created"] = False
        logger.info(
            "集合 %s 已存在（混合检索=%s）",
            name,
            "开启" if result["bm25"] else "关闭（纯稠密）",
        )
        return result

    # 优先：完整混合检索
    try:
        client.create_collection(
            collection_name=name,
            schema=_build_schema(client, with_bm25=True),
            index_params=_build_index_params(client, with_bm25=True),
            # Strong 一致性：单人本地库，宁可每次检索慢几毫秒，
            # 也要保证「刚上传的资料立刻能搜到」，避免用户以为没生效
            consistency_level="Strong",
        )
        result.update(created=True, bm25=True)
        logger.info("✓ 已创建集合 %s（稠密 BGE-M3 + BM25 稀疏，支持混合检索）", name)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("BM25 集合创建失败，将降级为纯稠密检索：%s: %s", type(exc).__name__, exc)
        # 清掉可能创建了一半的集合
        try:
            if client.has_collection(name):
                client.drop_collection(collection_name=name)
        except Exception:  # noqa: BLE001
            pass

    # 降级：纯稠密
    client.create_collection(
        collection_name=name,
        schema=_build_schema(client, with_bm25=False),
        index_params=_build_index_params(client, with_bm25=False),
        consistency_level="Strong",
    )
    result.update(created=True, bm25=False, degraded=True)
    logger.warning(
        "已创建集合 %s（纯稠密检索）。混合检索不可用，将退回 MySQL 关键词兜底", name
    )
    return result


def partition_names(collection: str | None = None) -> set[str]:
    """
    列出集合的分区名。

    ⚠️ 踩过的坑：MilvusClient.list_partitions() 返回的是 **List[str]**（分区名列表），
    不是 List[dict]。早期写成 {p.get("name") for p in ...} 会抛 AttributeError，
    被 except 吞掉后表现成「分区永远建不出来，写入时报 partition not found」。
    这里对 str / dict / 对象三种形态都做兼容。
    """
    settings = get_settings()
    name = collection or settings.chunk_collection
    client = get_client()
    try:
        raw = client.list_partitions(collection_name=name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("列出分区失败（%s）：%s", name, exc)
        return set()

    out: set[str] = set()
    for item in raw or []:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, dict):
            got = item.get("name") or item.get("partition_name")
            if got:
                out.add(str(got))
        else:
            got = getattr(item, "name", None) or getattr(item, "partition_name", None)
            if got:
                out.add(str(got))
    return out


def ensure_partition_named(collection: str, partition: str) -> dict[str, Any]:
    """确保指定集合里的指定分区存在（幂等）。"""
    client = get_client()
    if not client.has_collection(collection):
        ensure_collection()
        client = get_client()

    if partition in partition_names(collection):
        return {"collection": collection, "partition": partition, "created": False}

    client.create_partition(collection_name=collection, partition_name=partition)
    # 集合若处于 loaded 状态，新建的分区需要显式 load 才能被检索到
    try:
        client.load_partitions(collection_name=collection, partition_names=[partition])
    except Exception as exc:  # noqa: BLE001
        logger.debug("load_partitions(%s) 跳过：%s", partition, exc)

    logger.info("已创建 Milvus 分区 %s/%s", collection, partition)
    return {"collection": collection, "partition": partition, "created": True}


def drop_partition_named(collection: str, partition: str) -> bool:
    """
    删除分区（连带分区内向量）。删之前必须先 release，
    否则 Milvus 会报 "partition cannot be dropped, partition is loaded"。
    """
    client = get_client()
    if partition not in partition_names(collection):
        return False

    try:
        client.release_partitions(collection_name=collection, partition_names=[partition])
    except Exception as exc:  # noqa: BLE001
        logger.debug("release_partitions(%s) 失败，仍尝试删除：%s", partition, exc)

    client.drop_partition(collection_name=collection, partition_name=partition)
    logger.info("已删除 Milvus 分区 %s/%s", collection, partition)
    return True


def ensure_partition(kb_id: int) -> str:
    """为知识库创建分区（幂等）。失败只记日志，不中断入库流程。"""
    settings = get_settings()
    partition = settings.partition(kb_id)
    try:
        ensure_partition_named(settings.chunk_collection, partition)
    except Exception as exc:  # noqa: BLE001
        logger.warning("创建分区 %s 失败：%s: %s", partition, type(exc).__name__, exc)
    return partition


# ---------------------------------------------------------------------------
#  健康检查
# ---------------------------------------------------------------------------

def health() -> dict[str, Any]:
    settings = get_settings()
    result: dict[str, Any] = {
        "ok": False,
        "uri": settings.milvus_uri,
        "chunkCollection": settings.chunk_collection,
    }
    try:
        client = get_client()
        collections = list(client.list_collections())
        exists = settings.chunk_collection in collections
        result.update(
            ok=True,
            collections=collections,
            chunkCollectionExists=exists,
            hybridSearch=exists and _collection_has_sparse(client, settings.chunk_collection),
        )
        if not exists:
            result["hint"] = f"集合 {settings.chunk_collection} 尚未创建，将在首次入库时自动创建"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["hint"] = "检查 Milvus 是否运行、端口 19530 是否可达"
    return result

"""
背备不悲 · 知识点抽取与分块打标

两个能力：
  1. extract_tag_tree —— 把一份文档的大纲喂给 LLM，产出层级知识点树，落 bb_tag
  2. tag_chunks       —— 给每个分块挂知识点

打标有两条路，**默认走向量相似度**：
  - 向量法：把知识点名称+描述编码成向量，与分块向量算余弦相似度取 top-k。
    零 Token 成本、毫秒级、不需要 API Key，对「知识点名本身就是术语」的场景够用。
  - LLM 法：把候选知识点和分块原文给模型判断。更准，但每块一次调用，成本高。
    实现为「只对向量法置信度低于阈值的分块调用 LLM」，并且有调用次数上限。

没有配置 API Key 时，第 1 步会自动跳过（返回空树），整个入库流程照常跑完 ——
只是没有知识点标签，检索仍然可用。这样 M1 可以在拿到 Key 之前先验证链路。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text as sql_text

from app.core.logging import get_logger
from app.db.mysql import get_engine
from app.services.embedding import embedding_service
from app.services.llm import LlmError, llm_client
from app.services.prompts import prompt_service

logger = get_logger(__name__)

# 向量法置信度低于这个值才考虑交给 LLM 复核
LLM_FALLBACK_THRESHOLD = 0.45
# 单份文档最多多少次 LLM 打标调用（防止成本失控）
MAX_LLM_TAG_CALLS = 40
# 每个分块最多挂几个知识点
MAX_TAGS_PER_CHUNK = 3


class TaggingService:

    # ------------------------------------------------------------------
    #  1. 知识点树抽取
    # ------------------------------------------------------------------

    def has_tags(self, kb_id: int) -> bool:
        with get_engine().connect() as conn:
            row = conn.execute(
                sql_text("SELECT COUNT(*) FROM bb_tag WHERE kb_id = :kb"), {"kb": kb_id}
            ).fetchone()
            return bool(row and row[0])

    def extract_tag_tree(
        self,
        kb_id: int,
        kb_name: str,
        sample_text: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        让 LLM 抽取知识点树并落库。

        @return {"created": n, "skipped": bool, "reason": str}
        """
        if self.has_tags(kb_id) and not force:
            return {"created": 0, "skipped": True, "reason": "该知识库已有知识点，跳过抽取"}

        sample = (sample_text or "").strip()
        if len(sample) < 100:
            return {"created": 0, "skipped": True, "reason": "文档内容过少，不足以抽取知识点"}

        # 控制送进模型的内容量：优先给大纲，再补正文
        sample = sample[:6000]

        prompt = prompt_service.render("CLASSIFY_TAG", kb_name=kb_name, content=sample)

        try:
            data, result = llm_client.chat_json(
                [{"role": "user", "content": prompt}],
                task_type="CLASSIFY",
                biz_type="KB",
                biz_id=kb_id,
                temperature=0.3,
                max_tokens=4096,
            )
        except LlmError as exc:
            logger.warning("知识点抽取跳过（LLM 不可用）：%s", exc)
            return {"created": 0, "skipped": True, "reason": str(exc)}

        if force:
            self._delete_tags(kb_id)

        tags = data.get("tags") or []
        created = self._insert_tags(kb_id, tags, parent_id=0, level=1)
        logger.info("知识点抽取完成：kb=%s 新建 %d 个节点（LLM 用时 %d ms，%d tokens）",
                    kb_id, created, result.latency_ms, result.total_tokens)
        return {"created": created, "skipped": False, "reason": ""}

    def _delete_tags(self, kb_id: int) -> None:
        with get_engine().begin() as conn:
            conn.execute(sql_text("DELETE FROM bb_chunk_tag WHERE kb_id = :kb"), {"kb": kb_id})
            conn.execute(sql_text("DELETE FROM bb_tag WHERE kb_id = :kb"), {"kb": kb_id})

    def _insert_tags(self, kb_id: int, nodes: list[dict], parent_id: int, level: int) -> int:
        if not nodes or level > 3:
            return 0
        created = 0
        with get_engine().begin() as conn:
            for order, node in enumerate(nodes):
                name = str(node.get("name") or "").strip()[:100]
                if not name:
                    continue
                result = conn.execute(
                    sql_text(
                        "INSERT INTO bb_tag (kb_id, parent_id, name, level, sort_order, "
                        " description, origin, chunk_count, question_count) "
                        "VALUES (:kb, :pid, :name, :level, :order, :desc, 1, 0, 0)"
                    ),
                    {
                        "kb": kb_id, "pid": parent_id, "name": name, "level": level,
                        "order": order, "desc": str(node.get("description") or "")[:500],
                    },
                )
                created += 1
                tag_id = result.lastrowid
                children = node.get("children") or []
                if children and level < 3:
                    created += self._insert_tags_in(conn, kb_id, children, tag_id, level + 1)
        return created

    def _insert_tags_in(self, conn, kb_id: int, nodes: list[dict], parent_id: int, level: int) -> int:
        """在已有事务里递归插入子节点。"""
        if not nodes or level > 3:
            return 0
        created = 0
        for order, node in enumerate(nodes):
            name = str(node.get("name") or "").strip()[:100]
            if not name:
                continue
            result = conn.execute(
                sql_text(
                    "INSERT INTO bb_tag (kb_id, parent_id, name, level, sort_order, "
                    " description, origin, chunk_count, question_count) "
                    "VALUES (:kb, :pid, :name, :level, :order, :desc, 1, 0, 0)"
                ),
                {
                    "kb": kb_id, "pid": parent_id, "name": name, "level": level,
                    "order": order, "desc": str(node.get("description") or "")[:500],
                },
            )
            created += 1
            children = node.get("children") or []
            if children and level < 3:
                created += self._insert_tags_in(conn, kb_id, children, result.lastrowid, level + 1)
        return created

    # ------------------------------------------------------------------
    #  2. 分块打标
    # ------------------------------------------------------------------

    def list_tags(self, kb_id: int) -> list[dict[str, Any]]:
        with get_engine().connect() as conn:
            rows = conn.execute(
                sql_text(
                    "SELECT id, parent_id, name, level, description FROM bb_tag "
                    "WHERE kb_id = :kb ORDER BY level, sort_order, id"
                ),
                {"kb": kb_id},
            ).fetchall()
        return [
            {"id": int(r[0]), "parentId": int(r[1] or 0), "name": r[2],
             "level": int(r[3] or 1), "description": r[4] or ""}
            for r in rows
        ]

    def tag_chunks(
        self,
        kb_id: int,
        chunks: list[dict[str, Any]],
        *,
        use_llm: bool = True,
        emit_progress=None,
    ) -> dict[int, list[int]]:
        """
        给分块打标。

        chunks 每项：{chunkId, content, vector}
        @return {chunkId: [tagId, ...]}
        """
        tags = self.list_tags(kb_id)
        if not tags:
            logger.info("知识库 %s 没有知识点，跳过打标", kb_id)
            return {}
        if not chunks:
            return {}

        # 1) 知识点向量
        tag_texts = [f"{t['name']}。{t['description']}".strip("。") for t in tags]
        try:
            tag_vectors = embedding_service.encode(tag_texts, batch_size=32)
        except Exception as exc:  # noqa: BLE001
            logger.warning("知识点向量化失败，改用 LLM 打标：%s", exc)
            return self._tag_by_llm(kb_id, tags, chunks, emit_progress)

        # 2) 向量相似度取 top-k
        result: dict[int, list[int]] = {}
        low_confidence: list[dict[str, Any]] = []

        for chunk in chunks:
            vector = chunk.get("vector") or []
            if not vector:
                continue
            scored = [
                (self._dot(vector, tag_vectors[i]), tags[i]["id"])
                for i in range(len(tags))
            ]
            scored.sort(reverse=True)
            top = scored[:MAX_TAGS_PER_CHUNK]
            picked = [tag_id for score, tag_id in top if score >= 0.30]
            result[chunk["chunkId"]] = picked

            best = top[0][0] if top else 0.0
            if use_llm and best < LLM_FALLBACK_THRESHOLD:
                low_confidence.append(chunk)

        logger.info("向量打标完成：%d 块，其中 %d 块置信度低", len(result), len(low_confidence))

        # 3) 低置信度的交给 LLM 复核（有次数上限）
        if low_confidence and use_llm:
            refined = self._tag_by_llm(kb_id, tags, low_confidence[:MAX_LLM_TAG_CALLS], emit_progress)
            result.update(refined)

        return result

    def _tag_by_llm(
        self,
        kb_id: int,
        tags: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
        emit_progress=None,
    ) -> dict[int, list[int]]:
        candidate_text = "\n".join(
            f"{t['id']}: {t['name']} - {t['description']}" for t in tags
        )[:3000]
        valid_ids = {t["id"] for t in tags}

        out: dict[int, list[int]] = {}
        total = len(chunks)

        for index, chunk in enumerate(chunks):
            prompt = prompt_service.render(
                "CHUNK_TAG",
                candidate_tags=candidate_text,
                chunk_content=(chunk.get("content") or "")[:2500],
            )
            try:
                data, _ = llm_client.chat_json(
                    [{"role": "user", "content": prompt}],
                    task_type="CHUNK_TAG",
                    biz_type="CHUNK",
                    biz_id=int(chunk.get("chunkId") or 0),
                    temperature=0.1,
                    max_tokens=512,
                )
                picked = [int(t) for t in (data.get("tagIds") or []) if int(t) in valid_ids]
                out[chunk["chunkId"]] = picked[:MAX_TAGS_PER_CHUNK]
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM 打标失败（chunk=%s）：%s", chunk.get("chunkId"), exc)
                continue

            if emit_progress and (index % 5 == 0 or index == total - 1):
                emit_progress(index + 1, total)

        return out

    @staticmethod
    def _dot(a: list[float], b: list[float]) -> float:
        """两个已归一化向量的余弦相似度 = 点积。"""
        n = min(len(a), len(b))
        return sum(a[i] * b[i] for i in range(n))

    # ------------------------------------------------------------------
    #  3. 落库
    # ------------------------------------------------------------------

    def save_chunk_tags(self, kb_id: int, mapping: dict[int, list[int]]) -> int:
        """写 bb_chunk_tag，并回填 bb_tag.chunk_count。"""
        rows = [
            (chunk_id, tag_id, kb_id)
            for chunk_id, tag_ids in mapping.items()
            for tag_id in (tag_ids or [])
        ]
        if not rows:
            return 0

        with get_engine().begin() as conn:
            for chunk_id, tag_id, kb in rows:
                conn.execute(
                    sql_text(
                        "INSERT IGNORE INTO bb_chunk_tag (chunk_id, tag_id, kb_id, confidence) "
                        "VALUES (:c, :t, :k, 1.0)"
                    ),
                    {"c": chunk_id, "t": tag_id, "k": kb},
                )
            conn.execute(
                sql_text(
                    "UPDATE bb_tag t SET chunk_count = ("
                    "  SELECT COUNT(*) FROM bb_chunk_tag ct WHERE ct.tag_id = t.id"
                    ") WHERE t.kb_id = :kb"
                ),
                {"kb": kb_id},
            )
        logger.info("写入 %d 条分块-知识点关联", len(rows))
        return len(rows)


tagging_service = TaggingService()

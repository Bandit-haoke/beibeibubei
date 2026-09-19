"""
背备不悲 · AI 出题流水线

完整链路（每一步都会通过 SSE 汇报进度）：

   选材料（按知识点 RAG 检索）→ 分批调 LLM 出题 → 结构校验 → 自检防幻觉
   → 查重（向量相似度）→ 落库（bb_question / option / tag / paper_item）

关键设计：
  1. **分批出题**：一次要 30 道题会让 LLM 输出被截断，按 gen.batch_size（默认 5）分批
  2. **结构校验**：LLM 返回的 JSON 逐题校验，缺字段/选项数不对的直接丢弃
  3. **自检防幻觉**：把题目和它声称依据的原文一起喂给模型，问「答案能否从原文推出」
  4. **查重**：把已有题目的题干向量化，新题相似度超过阈值就丢弃
  5. **落库为草稿**：status=0（DRAFT），必须人工审核通过才变成 PUBLISHED
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text as sql_text

from app.core.logging import get_logger
from app.core.sse import EmitFn
from app.db.mysql import get_engine
from app.services.embedding import embedding_service
from app.services.llm import LlmError, llm_client
from app.services.prompts import prompt_service

logger = get_logger(__name__)

# 题型代码 → bb_question.q_type 的数字编码
Q_TYPE_CODE = {
    "SINGLE": 1, "MULTI": 2, "JUDGE": 3, "BLANK": 4, "TERM": 5,
    "SHORT": 6, "ESSAY": 7, "CODE": 8, "COMPARE": 9,
}
Q_TYPE_LABEL = {v: k for k, v in Q_TYPE_CODE.items()}

DIFF_CODE = {"EASY": 1, "MEDIUM": 2, "HARD": 3}
DIFF_LABEL = {1: "易", 2: "中", 3: "难"}

DEFAULT_TYPE_RATIO = {"SINGLE": 0.4, "JUDGE": 0.2, "BLANK": 0.2, "SHORT": 0.2}
DEFAULT_DIFF_RATIO = {"EASY": 0.3, "MEDIUM": 0.5, "HARD": 0.2}

# 检索每个知识点时取多少块材料
CHUNKS_PER_TAG = 6
# 查重阈值
DEDUP_THRESHOLD = 0.92


# ---------------------------------------------------------------------------
#  数据结构
# ---------------------------------------------------------------------------

@dataclass
class Material:
    """一段用于出题的原文材料。"""

    chunk_id: int
    doc_id: int
    content: str
    page_no: int = 0
    section_path: str = ""
    doc_name: str = ""
    tag_ids: list[int] = field(default_factory=list)

    def header(self) -> str:
        parts = [f"chunkId={self.chunk_id}"]
        if self.doc_name:
            parts.append(f"文档：{self.doc_name}")
        if self.page_no:
            parts.append(f"第{self.page_no}页")
        if self.section_path:
            parts.append(self.section_path)
        return "[" + " | ".join(parts) + "]"

    def render(self) -> str:
        return f"{self.header()}\n{self.content}"


@dataclass
class GeneratedQuestion:
    q_type: str
    difficulty: int
    stem: str
    answer: str
    analysis: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    rubric: list[dict[str, Any]] | None = None
    code_snippet: str | None = None
    tag_ids: list[int] = field(default_factory=list)
    source_chunk_ids: list[int] = field(default_factory=list)
    full_score: float = 5.0
    quality_score: float = 1.0
    self_check_msg: str = ""


# ---------------------------------------------------------------------------
#  主流程
# ---------------------------------------------------------------------------

def run_generate(payload: dict[str, Any], emit: EmitFn) -> None:
    kb_id = int(payload.get("kbId") or 0)
    paper_id = int(payload.get("paperId") or 0)
    count = max(1, min(60, int(payload.get("count") or 10)))
    tag_ids = [int(t) for t in (payload.get("tagIds") or [])]
    include_children = bool(payload.get("includeChildTags", True))
    type_ratio = payload.get("qTypeRatio") or DEFAULT_TYPE_RATIO
    diff_ratio = payload.get("difficultyRatio") or DEFAULT_DIFF_RATIO
    enable_self_check = bool(payload.get("selfCheck", True))

    batch_id = uuid.uuid4().hex
    logger.info("=== 开始出题 paper=%s kb=%s count=%s ===", paper_id, kb_id, count)

    try:
        # ---------------- 1. 选材料 ----------------
        emit("progress", {"progress": 3, "stage": "正在挑选命题材料"})
        materials = _select_materials(kb_id, tag_ids, include_children)
        if not materials:
            raise ValueError("该知识库还没有可用的分块。请先上传资料并等待解析完成。")

        emit("progress", {
            "progress": 8,
            "stage": f"已选出 {len(materials)} 段材料",
        })

        # ---------------- 2. 分批出题 ----------------
        emit("progress", {"progress": 12, "stage": "正在调用大模型出题"})
        raw_questions = _generate_in_batches(
            kb_id, materials, count, type_ratio, diff_ratio, emit
        )
        if not raw_questions:
            raise ValueError("大模型没有产出有效题目，请检查 API Key 或换用其他模型")

        # ---------------- 3. 结构校验 ----------------
        valid = _validate(raw_questions)
        dropped_invalid = len(raw_questions) - len(valid)
        if dropped_invalid:
            logger.info("结构校验丢弃 %d 道题", dropped_invalid)

        # ---------------- 4. 自检防幻觉 ----------------
        if enable_self_check and valid:
            emit("progress", {"progress": 62, "stage": "正在自检题目（防幻觉）"})
            valid = _self_check(valid, materials, emit)

        # ---------------- 5. 查重 ----------------
        emit("progress", {"progress": 80, "stage": "正在查重"})
        unique = _dedup(kb_id, valid)
        dropped_dup = len(valid) - len(unique)

        # ---------------- 6. 落库 ----------------
        emit("progress", {"progress": 92, "stage": "正在写入题库"})
        saved = _save(kb_id, paper_id, unique, batch_id)

        emit("done", {
            "paperId": paper_id,
            "kbId": kb_id,
            "requested": count,
            "generated": len(raw_questions),
            "droppedByValidate": dropped_invalid,
            "droppedBySelfCheck": len(raw_questions) - dropped_invalid - len(valid),
            "droppedByDedup": dropped_dup,
            "saved": saved,
            "batchId": batch_id,
        })
        logger.info("=== 出题完成 paper=%s 保存 %d 道 ===", paper_id, saved)

    except LlmError as exc:
        logger.warning("出题失败（LLM）：%s", exc)
        emit("error", {"errorMsg": str(exc), "hint": "请在「设置 → AI 配置」里填写可用的 API Key"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("出题失败")
        emit("error", {"errorMsg": f"{type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------------------
#  1. 选材料
# ---------------------------------------------------------------------------

def _select_materials(kb_id: int, tag_ids: list[int], include_children: bool) -> list[Material]:
    """按知识点取分块；没指定知识点就均匀取样整个知识库。"""
    effective_tags = list(tag_ids)
    if effective_tags and include_children:
        effective_tags = _expand_tags(kb_id, effective_tags)

    with get_engine().connect() as conn:
        if effective_tags:
            placeholders = ",".join(f":t{i}" for i in range(len(effective_tags)))
            params: dict[str, Any] = {"kb": kb_id}
            params.update({f"t{i}": t for i, t in enumerate(effective_tags)})
            # 用 EXISTS 而不是 JOIN + DISTINCT：
            # MySQL 在 DISTINCT 下要求 ORDER BY 的列必须出现在 SELECT 列表里，
            # 而 chunk_index 我们不想要进结果，所以 JOIN 方案会直接报 3065。
            rows = conn.execute(
                sql_text(
                    f"SELECT c.id, c.doc_id, c.content, c.page_no, c.section_path, "
                    f"       d.file_name "
                    f"FROM bb_doc_chunk c "
                    f"LEFT JOIN bb_document d ON d.id = c.doc_id "
                    f"WHERE c.kb_id = :kb AND CHAR_LENGTH(c.content) > 40 "
                    f"  AND EXISTS ("
                    f"    SELECT 1 FROM bb_chunk_tag ct "
                    f"    WHERE ct.chunk_id = c.id AND ct.tag_id IN ({placeholders})"
                    f"  ) "
                    f"ORDER BY c.doc_id, c.chunk_index "
                    f"LIMIT 400"
                ),
                params,
            ).fetchall()
        else:
            rows = conn.execute(
                sql_text(
                    "SELECT c.id, c.doc_id, c.content, c.page_no, c.section_path, d.file_name "
                    "FROM bb_doc_chunk c "
                    "LEFT JOIN bb_document d ON d.id = c.doc_id "
                    "WHERE c.kb_id = :kb AND CHAR_LENGTH(c.content) > 40 "
                    "ORDER BY c.doc_id, c.chunk_index LIMIT 400"
                ),
                {"kb": kb_id},
            ).fetchall()

        if not rows:
            # 指定了知识点但一个分块都没命中 —— 这时才退回全库，
            # 并在进度里说清楚。绝不能「材料少就悄悄扩大范围」，
            # 否则用户选第一章却出了 MyBatis 的题。
            if effective_tags:
                logger.warning("知识点范围内没有分块，退回全库选材料")
                emit("progress", {
                    "progress": 6,
                    "stage": "该知识点下还没有分块，已改用全库材料",
                })
                rows = conn.execute(
                    sql_text(
                        "SELECT c.id, c.doc_id, c.content, c.page_no, c.section_path, d.file_name "
                        "FROM bb_doc_chunk c "
                        "LEFT JOIN bb_document d ON d.id = c.doc_id "
                        "WHERE c.kb_id = :kb AND CHAR_LENGTH(c.content) > 40 "
                        "ORDER BY c.doc_id, c.chunk_index LIMIT 400"
                    ),
                    {"kb": kb_id},
                ).fetchall()
            if not rows:
                return []

        chunk_ids = [int(r[0]) for r in rows]
        tag_map = _chunk_tags(chunk_ids)

    materials = [
        Material(
            chunk_id=int(r[0]), doc_id=int(r[1]), content=r[2] or "",
            page_no=int(r[3] or 0), section_path=r[4] or "", doc_name=r[5] or "",
            tag_ids=tag_map.get(int(r[0]), []),
        )
        for r in rows
    ]

    # 均匀取样：长文档不至于把材料全占满
    if len(materials) > 60:
        step = len(materials) / 60
        materials = [materials[int(i * step)] for i in range(60)]
    return materials


def _expand_tags(kb_id: int, tag_ids: list[int]) -> list[int]:
    """把知识点扩展成「自己 + 所有子孙」。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            sql_text("SELECT id, parent_id FROM bb_tag WHERE kb_id = :kb"), {"kb": kb_id}
        ).fetchall()

    children: dict[int, list[int]] = {}
    for tid, pid in rows:
        children.setdefault(int(pid or 0), []).append(int(tid))

    out: list[int] = []
    stack = list(tag_ids)
    seen: set[int] = set()
    while stack:
        tid = stack.pop()
        if tid in seen:
            continue
        seen.add(tid)
        out.append(tid)
        stack.extend(children.get(tid, []))
    return out


def _chunk_tags(chunk_ids: list[int]) -> dict[int, list[int]]:
    if not chunk_ids:
        return {}
    out: dict[int, list[int]] = {}
    with get_engine().connect() as conn:
        batch = 500
        for start in range(0, len(chunk_ids), batch):
            piece = chunk_ids[start:start + batch]
            placeholders = ",".join(f":c{i}" for i in range(len(piece)))
            params = {f"c{i}": c for i, c in enumerate(piece)}
            rows = conn.execute(
                sql_text(
                    f"SELECT chunk_id, tag_id FROM bb_chunk_tag "
                    f"WHERE chunk_id IN ({placeholders})"
                ),
                params,
            ).fetchall()
            for cid, tid in rows:
                out.setdefault(int(cid), []).append(int(tid))
    return out


# ---------------------------------------------------------------------------
#  2. 分批出题
# ---------------------------------------------------------------------------

def _generate_in_batches(
    kb_id: int,
    materials: list[Material],
    count: int,
    type_ratio: dict[str, Any],
    diff_ratio: dict[str, Any],
    emit: EmitFn,
) -> list[dict[str, Any]]:
    from app.services.mock_llm import _expand_ratio

    batch_size = int(_get_setting("gen.batch_size", "5") or 5)
    kb_name = _kb_name(kb_id)
    tag_names = _tag_names(kb_id, sorted({t for m in materials for t in m.tag_ids}))

    # type_ratio 可能是 {"SINGLE":0.4,...} 也可能是 ["SINGLE","SHORT"]，两种都支持
    types = _expand_ratio(type_ratio, count)
    diffs = _expand_ratio(diff_ratio, count)

    results: list[dict[str, Any]] = []
    produced = 0
    round_index = 0
    max_rounds = (count // max(1, batch_size)) + 3

    while produced < count and round_index < max_rounds:
        round_index += 1
        need = min(batch_size, count - produced)

        # 每轮换一批材料，避免反复用同样的原文
        offset = ((round_index - 1) * batch_size) % max(1, len(materials))
        picked = (materials + materials)[offset:offset + max(3, min(len(materials), need + 1))]

        type_slice = types[produced:produced + need] or ["SHORT"]
        diff_slice = diffs[produced:produced + need] or ["MEDIUM"]

        prompt = prompt_service.render(
            "QUESTION_GEN",
            kb_name=kb_name,
            context="\n\n".join(m.render() for m in picked),
            count=need,
            tags="、".join(tag_names) or "（未指定，覆盖材料主要内容）",
            q_type_ratio=json.dumps(type_slice, ensure_ascii=False),
            difficulty_ratio=json.dumps(diff_slice, ensure_ascii=False),
        )

        try:
            data, result = llm_client.chat_json(
                [{"role": "user", "content": prompt}],
                task_type="QUESTION_GEN",
                biz_type="PAPER",
                biz_id=0,
                temperature=0.7,
                max_tokens=8192,
            )
        except LlmError:
            if results:
                logger.warning("第 %d 批出题失败，用已有结果收尾", round_index)
                break
            raise

        batch = data.get("questions") or []
        for q in batch:
            if isinstance(q, dict):
                results.append(q)
        produced = len(results)

        emit("progress", {
            "progress": min(58, 12 + int(46 * produced / max(1, count))),
            "stage": f"已生成 {produced}/{count} 道题（LLM 用时 {result.latency_ms} ms）",
        })

    return results[:count] if len(results) > count else results


# ---------------------------------------------------------------------------
#  3. 结构校验
# ---------------------------------------------------------------------------

_REQUIRED = ("qType", "stem", "answer")


def _validate(raw: list[dict[str, Any]]) -> list[GeneratedQuestion]:
    out: list[GeneratedQuestion] = []
    for item in raw:
        try:
            q_type = str(item.get("qType") or "").strip().upper()
            if q_type not in Q_TYPE_CODE:
                continue
            if any(not str(item.get(k) or "").strip() for k in _REQUIRED):
                continue

            options = item.get("options") or []
            if q_type in ("SINGLE", "MULTI"):
                options = [o for o in options if isinstance(o, dict)
                           and str(o.get("key") or "").strip()
                           and str(o.get("content") or "").strip()]
                if len(options) < 3:
                    continue
                answer = str(item["answer"]).strip().upper().replace("，", ",")
                keys = {o["key"].strip().upper() for o in options}
                # 答案里的每个选项字母都得真实存在
                if not set(re.findall(r"[A-Z]", answer)) <= keys:
                    continue

            rubric = item.get("rubric")
            if q_type in ("SHORT", "TERM", "ESSAY", "COMPARE"):
                if not isinstance(rubric, list) or not rubric:
                    continue
                rubric = [
                    {"point": str(p.get("point") or "")[:500],
                     "score": float(p.get("score") or 0)}
                    for p in rubric if isinstance(p, dict) and str(p.get("point") or "").strip()
                ]
                if not rubric:
                    continue

            full_score = float(item.get("fullScore")
                               or (10 if q_type in ("SHORT", "TERM", "ESSAY", "COMPARE", "CODE") else 5))

            out.append(GeneratedQuestion(
                q_type=q_type,
                difficulty=DIFF_CODE.get(str(item.get("difficulty", 2)).upper(), 2)
                if not str(item.get("difficulty", "")).isdigit()
                else max(1, min(3, int(item["difficulty"]))),
                stem=str(item["stem"]).strip()[:4000],
                answer=str(item["answer"]).strip()[:6000],
                analysis=str(item.get("analysis") or "").strip()[:4000],
                options=[{"key": str(o["key"]).strip().upper()[:2],
                          "content": str(o["content"]).strip()[:1000]} for o in options],
                rubric=rubric if isinstance(rubric, list) else None,
                code_snippet=(str(item["codeSnippet"])[:4000]
                              if item.get("codeSnippet") else None),
                tag_ids=[int(t) for t in (item.get("tagIds") or []) if str(t).isdigit()][:3],
                source_chunk_ids=[int(t) for t in (item.get("sourceChunkIds") or [])
                                  if str(t).isdigit()][:6],
                full_score=full_score,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("校验单题失败，丢弃：%s", exc)
    return out


# ---------------------------------------------------------------------------
#  4. 自检防幻觉
# ---------------------------------------------------------------------------

def _self_check(
    questions: list[GeneratedQuestion], materials: list[Material], emit: EmitFn
) -> list[GeneratedQuestion]:
    threshold = float(_get_setting("gen.self_check_threshold", "0.75") or 0.75)
    by_id = {m.chunk_id: m for m in materials}
    kept: list[GeneratedQuestion] = []

    for index, question in enumerate(questions):
        context = "\n\n".join(
            by_id[cid].render() for cid in question.source_chunk_ids if cid in by_id
        )
        if not context:
            # 没有可核对的材料 —— 用材料池里最长的几段兜底
            context = "\n\n".join(m.render() for m in materials[:3])

        try:
            data, _ = llm_client.chat_json(
                [{"role": "user", "content": prompt_service.render(
                    "SELF_CHECK",
                    question_json=json.dumps(question.__dict__, ensure_ascii=False, default=str),
                    context=context,
                )}],
                task_type="SELF_CHECK",
                temperature=0.1,
                max_tokens=512,
            )
            passed = bool(data.get("pass", True))
            score = float(data.get("score") or (1.0 if passed else 0.3))
            reason = str(data.get("reason") or "")[:500]
        except Exception as exc:  # noqa: BLE001
            logger.debug("自检调用失败，默认放行：%s", exc)
            passed, score, reason = True, 0.8, "自检未执行"

        question.quality_score = score
        question.self_check_msg = reason

        if passed and score >= threshold:
            kept.append(question)
        else:
            logger.info("自检不通过，丢弃：%s（%.2f，%s）", question.stem[:40], score, reason)

        emit("progress", {
            "progress": min(78, 62 + int(16 * (index + 1) / max(1, len(questions)))),
            "stage": f"自检 {index + 1}/{len(questions)}，通过 {len(kept)} 道",
        })

    return kept


# ---------------------------------------------------------------------------
#  5. 查重
# ---------------------------------------------------------------------------

def _dedup(kb_id: int, questions: list[GeneratedQuestion]) -> list[GeneratedQuestion]:
    if not questions:
        return []

    with get_engine().connect() as conn:
        rows = conn.execute(
            sql_text("SELECT stem FROM bb_question WHERE kb_id = :kb LIMIT 2000"),
            {"kb": kb_id},
        ).fetchall()

    existing = [_normalize(r[0]) for r in rows if r[0]]
    normalized_map = {_normalize(q.stem): q for q in questions}

    # 字面查重：归一化后完全相同直接丢
    unique: dict[str, GeneratedQuestion] = {}
    for key, question in normalized_map.items():
        if key in existing:
            logger.info("查重（字面）：丢弃 %s", question.stem[:40])
            continue
        unique[key] = question

    candidates = list(unique.values())
    if len(candidates) < 2 and not existing:
        return candidates

    # 向量查重：与已有题目 + 本批内已接受的题目比相似度
    try:
        pool_texts = existing[:500] + [q.stem for q in candidates]
        vectors = embedding_service.encode(pool_texts, batch_size=32)

        existing_vectors = vectors[:len(existing[:500])]
        new_vectors = vectors[len(existing[:500]):]

        accepted: list[GeneratedQuestion] = []
        accepted_vectors: list[list[float]] = []

        for question, vector in zip(candidates, new_vectors):
            best = 0.0
            for other in existing_vectors:
                best = max(best, _dot(vector, other))
                if best >= DEDUP_THRESHOLD:
                    break
            if best < DEDUP_THRESHOLD:
                for other in accepted_vectors:
                    best = max(best, _dot(vector, other))
                    if best >= DEDUP_THRESHOLD:
                        break

            if best >= DEDUP_THRESHOLD:
                logger.info("查重（向量 %.3f）：丢弃 %s", best, question.stem[:40])
            else:
                accepted.append(question)
                accepted_vectors.append(vector)

        return accepted

    except Exception as exc:  # noqa: BLE001
        logger.warning("向量查重不可用，只做字面查重：%s", exc)
        return candidates


def _normalize(text: str) -> str:
    return re.sub(r"[\s，。、；：！？,.;:!?（）()【】\[\]\"'`]", "", (text or "").lower())


def _dot(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


# ---------------------------------------------------------------------------
#  6. 落库
# ---------------------------------------------------------------------------

def _save(
    kb_id: int, paper_id: int, questions: list[GeneratedQuestion], batch_id: str
) -> int:
    if not questions:
        return 0

    # 题目应该继承它依据的分块上的知识点：LLM 给的 tagIds 往往只挂到最细的子节点，
    # 用户在界面上通常按顶层章节筛选，只挂子节点就会「按章节查不到任何题」。
    # 这里把「LLM 给的」∪「source chunks 上的」∪「这些标签的所有祖先」。
    all_chunk_ids = sorted({cid for q in questions for cid in q.source_chunk_ids})
    chunk_tag_index = _chunk_tags(all_chunk_ids)
    ancestors = _ancestor_map(kb_id)

    saved = 0
    with get_engine().begin() as conn:
        for order, question in enumerate(questions):
            merged_tags: list[int] = []

            def add_tag(tag_id: int) -> None:
                if tag_id in merged_tags:
                    return
                merged_tags.append(tag_id)
                # 顺带把祖先也挂上，这样按章节筛选能命中
                parent = ancestors.get(tag_id)
                while parent:
                    if parent in merged_tags:
                        break
                    merged_tags.append(parent)
                    parent = ancestors.get(parent)

            for tag_id in list(question.tag_ids):
                add_tag(tag_id)
            for chunk_id in question.source_chunk_ids:
                for tag_id in chunk_tag_index.get(chunk_id, []):
                    add_tag(tag_id)

            merged_tags = merged_tags[:12]
            question.tag_ids = merged_tags

            doc_id = _doc_of_chunk(conn, question.source_chunk_ids)
            result = conn.execute(
                sql_text(
                    "INSERT INTO bb_question "
                    "(kb_id, q_type, difficulty, stem, answer, analysis, rubric, code_snippet, "
                    " source_chunk_ids, source_doc_id, status, origin, gen_batch_id, "
                    " quality_score, self_check_msg, use_count, correct_count, avg_score_rate) "
                    "VALUES (:kb, :qt, :diff, :stem, :answer, :analysis, :rubric, :code, "
                    " :chunks, :doc, 0, 1, :batch, :quality, :msg, 0, 0, 0)"
                ),
                {
                    "kb": kb_id,
                    "qt": Q_TYPE_CODE[question.q_type],
                    "diff": question.difficulty,
                    "stem": question.stem,
                    "answer": question.answer,
                    "analysis": question.analysis,
                    "rubric": json.dumps(question.rubric, ensure_ascii=False)
                    if question.rubric else None,
                    "code": question.code_snippet,
                    "chunks": json.dumps(question.source_chunk_ids, ensure_ascii=False),
                    "doc": doc_id,
                    "batch": batch_id,
                    "quality": question.quality_score,
                    "msg": question.self_check_msg[:500],
                },
            )
            question_id = int(result.lastrowid)
            saved += 1

            # 选项
            correct_keys = set(re.findall(r"[A-Z]", question.answer.upper()))
            for opt_order, option in enumerate(question.options):
                conn.execute(
                    sql_text(
                        "INSERT INTO bb_question_option "
                        "(question_id, option_key, content, is_correct, sort_order) "
                        "VALUES (:q, :k, :c, :ok, :o)"
                    ),
                    {
                        "q": question_id, "k": option["key"], "c": option["content"],
                        "ok": 1 if option["key"] in correct_keys else 0, "o": opt_order,
                    },
                )

            # 知识点关联
            for tag_id in question.tag_ids:
                conn.execute(
                    sql_text(
                        "INSERT IGNORE INTO bb_question_tag (question_id, tag_id, kb_id) "
                        "VALUES (:q, :t, :kb)"
                    ),
                    {"q": question_id, "t": tag_id, "kb": kb_id},
                )

            # 加入题卷
            if paper_id:
                conn.execute(
                    sql_text(
                        "INSERT IGNORE INTO bb_paper_item (paper_id, question_id, sort_order, score) "
                        "VALUES (:p, :q, :o, :s)"
                    ),
                    {"p": paper_id, "q": question_id, "o": order, "s": question.full_score},
                )

        # 刷新题卷统计
        if paper_id:
            conn.execute(
                sql_text(
                    "UPDATE bb_paper SET total_count = ("
                    "  SELECT COUNT(*) FROM bb_paper_item WHERE paper_id = :p"
                    "), total_score = ("
                    "  SELECT COALESCE(SUM(score), 0) FROM bb_paper_item WHERE paper_id = :p"
                    ") WHERE id = :p"
                ),
                {"p": paper_id},
            )

        # 刷新知识点题量
        conn.execute(
            sql_text(
                "UPDATE bb_tag t SET question_count = ("
                "  SELECT COUNT(*) FROM bb_question_tag qt WHERE qt.tag_id = t.id"
                ") WHERE t.kb_id = :kb"
            ),
            {"kb": kb_id},
        )

    return saved


def _doc_of_chunk(conn, chunk_ids: list[int]) -> int:
    if not chunk_ids:
        return 0
    try:
        row = conn.execute(
            sql_text("SELECT doc_id FROM bb_doc_chunk WHERE id = :id LIMIT 1"),
            {"id": int(chunk_ids[0])},
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
#  工具
# ---------------------------------------------------------------------------

def _ancestor_map(kb_id: int) -> dict[int, int]:
    """返回 {tagId: parentId}，parentId 为 0 表示顶层。用于给题目补全祖先知识点。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            sql_text("SELECT id, parent_id FROM bb_tag WHERE kb_id = :kb"), {"kb": kb_id}
        ).fetchall()
    return {int(r[0]): int(r[1] or 0) for r in rows}


def _kb_name(kb_id: int) -> str:
    with get_engine().connect() as conn:
        row = conn.execute(
            sql_text("SELECT name FROM bb_knowledge_base WHERE id = :id"), {"id": kb_id}
        ).fetchone()
        return str(row[0]) if row else f"知识库{kb_id}"


def _tag_names(kb_id: int, tag_ids: list[int]) -> list[str]:
    if not tag_ids:
        return []
    placeholders = ",".join(f":t{i}" for i in range(len(tag_ids)))
    params: dict[str, Any] = {"kb": kb_id}
    params.update({f"t{i}": t for i, t in enumerate(tag_ids)})
    with get_engine().connect() as conn:
        rows = conn.execute(
            sql_text(
                f"SELECT id, name FROM bb_tag WHERE kb_id = :kb AND id IN ({placeholders})"
            ),
            params,
        ).fetchall()
    return [f"{r[1]}(#{r[0]})" for r in rows]


def _get_setting(key: str, default: str = "") -> str:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sql_text("SELECT svalue FROM bb_setting WHERE skey = :k"), {"k": key}
            ).fetchone()
            return str(row[0]) if row else default
    except Exception:  # noqa: BLE001
        return default

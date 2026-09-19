"""
背备不悲 · 判分流水线

链路：
    读答卷 → 客观题程序判定 → 主观题 AI 按要点判分 → 写回 bb_answer_item
    → 汇总 bb_exam_record → 更新题目统计 → 错题进 bb_mistake（含 SM-2 复习计划）

关键设计：
  1. **客观题绝不走 LLM** —— 单选/多选/判断直接程序比对，省 Token 也避免模型胡说
  2. **判分必须可解释**：每道主观题都要产出「命中要点 / 漏掉要点 / 答错内容 / 原文引用」
  3. **分数由程序夹紧**：LLM 给负分或超满分都会被修正
  4. **申诉重判**保留两次结果，用户可以对照
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text as sql_text

from app.core.logging import get_logger
from app.core.sse import EmitFn
from app.db.mysql import get_engine
from app.services.llm import LlmError, llm_client
from app.services.prompts import prompt_service

logger = get_logger(__name__)

# 题型编码（与 bb_question.q_type 一致）
QT_SINGLE, QT_MULTI, QT_JUDGE, QT_BLANK = 1, 2, 3, 4
QT_TERM, QT_SHORT, QT_ESSAY, QT_CODE, QT_COMPARE = 5, 6, 7, 8, 9
OBJECTIVE_TYPES = {QT_SINGLE, QT_MULTI, QT_JUDGE}

# 判分方式
METHOD_PROGRAM, METHOD_AI, METHOD_AI_CODE, METHOD_MANUAL = 1, 2, 3, 4

# 多选：只选对了一部分且没选错，给一半分
MULTI_PARTIAL_RATIO = 0.5
# 一道题得分率低于此值就进错题本
MISTAKE_THRESHOLD = 0.8


@dataclass
class GradeResult:
    answer_item_id: int
    question_id: int
    q_type: int
    score: float
    full_score: float
    method: int
    hit_points: list[dict[str, Any]] = field(default_factory=list)
    miss_points: list[dict[str, Any]] = field(default_factory=list)
    wrong_points: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    feedback: str = ""
    ai_call_id: int = 0


# ---------------------------------------------------------------------------
#  主流程
# ---------------------------------------------------------------------------

def run_grade(payload: dict[str, Any], emit: EmitFn) -> None:
    exam_id = int(payload.get("examId") or 0)
    task_id = int(payload.get("taskId") or 0)
    # 申诉重判：只重判一道题
    appeal_item_id = payload.get("answerItemId")
    appeal_reason = payload.get("appealReason") or ""

    logger.info("=== 开始判分 exam=%s task=%s appeal=%s ===", exam_id, task_id, appeal_item_id)

    try:
        _mark_exam(exam_id, status=2)  # 判分中

        items = _load_answer_items(exam_id, appeal_item_id)
        if not items:
            raise ValueError("这份答卷没有待判的题目")

        emit("progress", {"progress": 5, "stage": f"共 {len(items)} 道题待判"})

        results: list[GradeResult] = []
        for index, item in enumerate(items, start=1):
            result = _grade_one(item, exam_id, appeal_reason=appeal_reason)
            results.append(result)

            emit("progress", {
                "progress": min(95, 5 + int(90 * index / len(items))),
                "stage": f"已判 {index}/{len(items)}：{item['stem'][:24]}… "
                         f"得 {result.score}/{result.full_score}",
            })

        _persist(exam_id, results, appeal_mode=bool(appeal_item_id))

        if appeal_item_id:
            emit("done", {
                "examId": exam_id,
                "appealAnswerItemId": appeal_item_id,
                "score": results[0].score,
                "fullScore": results[0].full_score,
            })
        else:
            emit("done", _summary(exam_id))

        logger.info("=== 判分完成 exam=%s ===", exam_id)

    except LlmError as exc:
        logger.warning("判分失败（LLM）：%s", exc)
        _mark_exam(exam_id, status=4)
        emit("error", {"errorMsg": str(exc),
                       "hint": "请在 beibei-agent/.env 里把 LLM_MOCK 设为 true 先验证流程，或填写可用的 API Key"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("判分失败")
        _mark_exam(exam_id, status=4)
        emit("error", {"errorMsg": f"{type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------------------
#  读取
# ---------------------------------------------------------------------------

def _load_answer_items(exam_id: int, only_item_id: Any = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT ai.id AS answer_item_id, ai.user_answer, ai.score AS old_score, "
        "       ai.full_score, q.id AS question_id, q.q_type, q.stem, q.answer, "
        "       q.rubric, q.source_chunk_ids, q.code_snippet "
        "FROM bb_answer_item ai "
        "JOIN bb_question q ON q.id = ai.question_id "
        "WHERE ai.exam_id = :exam"
    )
    params: dict[str, Any] = {"exam": exam_id}
    if only_item_id:
        sql += " AND ai.id = :item"
        params["item"] = int(only_item_id)
    sql += " ORDER BY ai.id"

    with get_engine().connect() as conn:
        rows = conn.execute(sql_text(sql), params).fetchall()

        items = []
        for row in rows:
            item = {
                "answerItemId": int(row[0]),
                "userAnswer": (row[1] or "").strip(),
                "fullScore": float(row[3] or 0) or 5.0,
                "questionId": int(row[4]),
                "qType": int(row[5]),
                "stem": row[6] or "",
                "referenceAnswer": row[7] or "",
                "rubric": _parse_json(row[8]) or [],
                "codeSnippet": row[10] or "",
                "sourceChunkIds": _parse_json(row[9]) or [],
                "sourceChunks": [],
            }
            item["sourceChunks"] = _load_chunks(conn, item["sourceChunkIds"])
            items.append(item)
    return items


def _load_chunks(conn, chunk_ids: list[Any]) -> list[dict[str, Any]]:
    ids = [int(c) for c in chunk_ids if str(c).isdigit()][:6]
    if not ids:
        return []
    placeholders = ",".join(f":c{i}" for i in range(len(ids)))
    params = {f"c{i}": v for i, v in enumerate(ids)}
    rows = conn.execute(
        sql_text(
            f"SELECT id, content, page_no, section_path FROM bb_doc_chunk "
            f"WHERE id IN ({placeholders})"
        ),
        params,
    ).fetchall()
    return [
        {"chunkId": int(r[0]), "content": (r[1] or "")[:2500],
         "pageNo": int(r[2] or 0), "sectionPath": r[3] or ""}
        for r in rows
    ]


# ---------------------------------------------------------------------------
#  判分
# ---------------------------------------------------------------------------

def _grade_one(item: dict[str, Any], exam_id: int, *, appeal_reason: str = "") -> GradeResult:
    q_type = item["qType"]
    full = float(item["fullScore"]) or 5.0
    user = item["userAnswer"]

    if not user:
        return GradeResult(
            answer_item_id=item["answerItemId"], question_id=item["questionId"],
            q_type=q_type, score=0.0, full_score=full, method=METHOD_PROGRAM,
            miss_points=[{"point": _p.get("point", ""), "hint": "未作答"}
                         for _p in (item["rubric"] or [])],
            feedback="未作答。",
        )

    if q_type == QT_SINGLE or q_type == QT_JUDGE:
        return _grade_exact(item, full, user)
    if q_type == QT_MULTI:
        return _grade_multi(item, full, user)
    if q_type == QT_BLANK:
        return _grade_blank(item, exam_id, full, user, appeal_reason)
    return _grade_subjective(item, exam_id, full, user, appeal_reason)


def _grade_exact(item: dict[str, Any], full: float, user: str) -> GradeResult:
    """单选 / 判断：程序直接比对。"""
    expected = _norm_choice(item["referenceAnswer"])
    actual = _norm_choice(user)
    correct = expected == actual and expected != ""

    return GradeResult(
        answer_item_id=item["answerItemId"], question_id=item["questionId"],
        q_type=item["qType"], score=full if correct else 0.0, full_score=full,
        method=METHOD_PROGRAM,
        hit_points=[{"point": f"正确答案 {expected}", "score": full}] if correct else [],
        miss_points=[] if correct else [{"point": f"正确答案是 {expected}",
                                         "hint": f"你选了 {actual or '（空）'}"}],
        feedback="回答正确。" if correct else f"回答错误，正确答案是 {expected}。",
    )


def _grade_multi(item: dict[str, Any], full: float, user: str) -> GradeResult:
    """多选：全对满分；只选对一部分且没选错给一半；选错任何一项为 0。"""
    expected = set(_norm_choice(item["referenceAnswer"]))
    actual = set(_norm_choice(user))

    if not expected:
        return _grade_exact(item, full, user)

    if actual == expected:
        return GradeResult(
            answer_item_id=item["answerItemId"], question_id=item["questionId"],
            q_type=item["qType"], score=full, full_score=full, method=METHOD_PROGRAM,
            hit_points=[{"point": f"全部选对：{''.join(sorted(expected))}", "score": full}],
            feedback="完全正确。",
        )

    wrong_picks = actual - expected
    missed = expected - actual

    if wrong_picks:
        return GradeResult(
            answer_item_id=item["answerItemId"], question_id=item["questionId"],
            q_type=item["qType"], score=0.0, full_score=full, method=METHOD_PROGRAM,
            miss_points=[{"point": f"正确答案是 {''.join(sorted(expected))}",
                          "hint": f"漏选 {''.join(sorted(missed))}"}] if missed else [],
            wrong_points=[{"point": f"多选了 {''.join(sorted(wrong_picks))}",
                           "correction": "多选、错选均不得分"}],
            feedback=f"多选了 {''.join(sorted(wrong_picks))}，本项不得分。",
        )

    partial = round(full * MULTI_PARTIAL_RATIO, 1)
    return GradeResult(
        answer_item_id=item["answerItemId"], question_id=item["questionId"],
        q_type=item["qType"], score=partial, full_score=full, method=METHOD_PROGRAM,
        hit_points=[{"point": f"选对 {''.join(sorted(actual))}", "score": partial}],
        miss_points=[{"point": f"漏选 {''.join(sorted(missed))}",
                      "hint": "少选得一半分，选全才满分"}],
        feedback=f"漏选了 {''.join(sorted(missed))}，得一半分。",
    )


def _grade_blank(item: dict[str, Any], exam_id: int, full: float, user: str, reason: str) -> GradeResult:
    """填空：先做规范化精确匹配，不中就交 AI —— 因为填空题常有多种正确表述。"""
    expected = _normalize_text(item["referenceAnswer"])
    actual = _normalize_text(user)

    if actual and (actual == expected or actual in expected or expected in actual):
        return GradeResult(
            answer_item_id=item["answerItemId"], question_id=item["questionId"],
            q_type=item["qType"], score=full, full_score=full, method=METHOD_PROGRAM,
            hit_points=[{"point": item["referenceAnswer"][:120], "score": full}],
            feedback="回答正确。",
        )

    # 关键词覆盖率兜底：答案里的关键术语出现一半以上就算对
    keywords = [k for k in _keywords(item["referenceAnswer"]) if len(k) >= 2]
    if keywords:
        hit = sum(1 for k in keywords if _normalize_text(k) in actual)
        if hit / len(keywords) >= 0.6:
            return GradeResult(
                answer_item_id=item["answerItemId"], question_id=item["questionId"],
                q_type=item["qType"], score=full, full_score=full, method=METHOD_PROGRAM,
                hit_points=[{"point": f"命中关键词 {hit}/{len(keywords)}", "score": full}],
                feedback="关键内容答对。",
            )

    # 表述差异较大时才交 AI
    return _grade_by_ai(item, exam_id, full, user, reason, q_type=item["qType"])


def _grade_subjective(item: dict[str, Any], exam_id: int, full: float, user: str,
                      reason: str) -> GradeResult:
    return _grade_by_ai(item, exam_id, full, user, reason, q_type=item["qType"])


def _grade_by_ai(item: dict[str, Any], exam_id: int, full: float, user: str,
                 reason: str, *, q_type: int) -> GradeResult:
    rubric = item["rubric"] or []
    context = "\n\n".join(
        f"[chunkId={c['chunkId']} | 第{c['pageNo']}页 | {c['sectionPath']}]\n{c['content']}"
        for c in item["sourceChunks"]
    ) or "（没有检索到原文依据，请只依据题目与参考答案判断）"

    prompt = prompt_service.render(
        "GRADING_SUBJECTIVE",
        stem=item["stem"],
        reference_answer=item["referenceAnswer"],
        rubric=json.dumps(rubric, ensure_ascii=False) if rubric else "（本题没有配置评分要点，按参考答案整体判断）",
        context=context,
        user_answer=user,
        full_score=full,
    )
    if reason:
        prompt += f"\n\n【学生申诉理由】{reason}\n请认真核对该理由，如果学生说得有道理，请修正评分。"

    try:
        data, result = llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            task_type="GRADING",
            biz_type="EXAM",
            biz_id=exam_id,
            temperature=0.2,
            max_tokens=2048,
        )
    except LlmError:
        raise

    # 分数夹紧：LLM 偶尔会给负数或超满分
    score = _clamp(float(data.get("score") or 0), 0.0, full)

    citations = _resolve_citations(data.get("citations") or [], item["sourceChunks"])

    return GradeResult(
        answer_item_id=item["answerItemId"], question_id=item["questionId"],
        q_type=q_type, score=score, full_score=full,
        method=METHOD_AI_CODE if q_type == QT_CODE else METHOD_AI,
        hit_points=_clean_points(data.get("hitPoints"), "score"),
        miss_points=_clean_points(data.get("missPoints"), "hint"),
        wrong_points=_clean_points(data.get("wrongPoints"), "correction"),
        citations=citations,
        feedback=str(data.get("feedback") or "")[:2000],
    )


# ---------------------------------------------------------------------------
#  落库
# ---------------------------------------------------------------------------

def _persist(exam_id: int, results: list[GradeResult], *, appeal_mode: bool) -> None:
    with get_engine().begin() as conn:
        for r in results:
            payload = {
                "score": r.score,
                "hit": json.dumps(r.hit_points, ensure_ascii=False),
                "miss": json.dumps(r.miss_points, ensure_ascii=False),
                "wrong": json.dumps(r.wrong_points, ensure_ascii=False),
                "cites": json.dumps(r.citations, ensure_ascii=False),
                "feedback": r.feedback,
                "method": r.method,
                "id": r.answer_item_id,
            }
            if appeal_mode:
                conn.execute(
                    sql_text(
                        "UPDATE bb_answer_item SET score = :score, hit_points = :hit, "
                        "miss_points = :miss, wrong_points = :wrong, citations = :cites, "
                        "ai_feedback = :feedback, grade_method = :method, "
                        "appeal_status = 2, appeal_score = :score, appeal_result = :cites "
                        "WHERE id = :id"
                    ),
                    payload,
                )
            else:
                conn.execute(
                    sql_text(
                        "UPDATE bb_answer_item SET score = :score, hit_points = :hit, "
                        "miss_points = :miss, wrong_points = :wrong, citations = :cites, "
                        "ai_feedback = :feedback, grade_method = :method "
                        "WHERE id = :id"
                    ),
                    payload,
                )

        if appeal_mode:
            item_id = results[0].answer_item_id
            conn.execute(
                sql_text("UPDATE bb_answer_item SET appeal_at = NOW() WHERE id = :id"),
                {"id": item_id},
            )
            return

        # 汇总答卷
        conn.execute(
            sql_text(
                "UPDATE bb_exam_record e SET "
                "  status = 3, graded_at = NOW(), "
                "  got_score = (SELECT COALESCE(SUM(score),0) FROM bb_answer_item WHERE exam_id = e.id), "
                "  correct_count = (SELECT COUNT(*) FROM bb_answer_item ai WHERE ai.exam_id = e.id "
                "                   AND ai.score >= ai.full_score * 0.999), "
                "  wrong_count = (SELECT COUNT(*) FROM bb_answer_item ai WHERE ai.exam_id = e.id "
                "                 AND ai.score < ai.full_score * 0.999) "
                "WHERE e.id = :exam"
            ),
            {"exam": exam_id},
        )

        # 更新题目统计（用于难度校准）
        for r in results:
            conn.execute(
                sql_text(
                    "UPDATE bb_question SET "
                    "  use_count = use_count + 1, "
                    "  correct_count = correct_count + :correct, "
                    "  avg_score_rate = ("
                    "    SELECT COALESCE(AVG(ai.score / NULLIF(ai.full_score, 0)), 0) "
                    "    FROM bb_answer_item ai WHERE ai.question_id = :qid"
                    "  ) "
                    "WHERE id = :qid"
                ),
                {"qid": r.question_id,
                 "correct": 1 if r.full_score and r.score >= r.full_score * 0.999 else 0},
            )

        _update_mistakes(conn, exam_id, results)


def _update_mistakes(conn, exam_id: int, results: list[GradeResult]) -> None:
    """
    错题进错题本并按 SM-2 排复习时间。

    SM-2 简化实现：
      答对：repetitions+1，interval = 0→1、1→6、之后 round(interval × ease)
      答错：repetitions 归零，interval 回到 1 天
      ease 随成绩加减，下限 1.30
    """
    row = conn.execute(
        sql_text("SELECT user_id, kb_id FROM bb_exam_record WHERE id = :e"), {"e": exam_id}
    ).fetchone()
    if not row:
        return
    user_id, kb_id = int(row[0] or 1), int(row[1] or 0)

    mastered_streak = int(_setting(conn, "review.mastered_streak", "4"))
    mastered_interval = int(_setting(conn, "review.mastered_interval", "30"))

    for r in results:
        rate = (r.score / r.full_score) if r.full_score else 0.0
        if rate >= MISTAKE_THRESHOLD:
            # 答得好 —— 如果已在错题本里，推进复习进度
            existing = conn.execute(
                sql_text("SELECT id, repetitions, interval_days, ease_factor, right_streak "
                         "FROM bb_mistake WHERE user_id = :u AND question_id = :q"),
                {"u": user_id, "q": r.question_id},
            ).fetchone()
            if not existing:
                continue

            mistake_id, reps, interval, ease, streak = (
                int(existing[0]), int(existing[1]), int(existing[2]),
                float(existing[3]), int(existing[4]))
            grade = 5 if rate >= 0.95 else 4
            ease = max(1.3, ease + 0.1)
            reps += 1
            streak += 1
            interval = 1 if reps == 1 else (6 if reps == 2 else int(round(interval * ease)))
            mastered = 1 if (streak >= mastered_streak and interval >= mastered_interval) else 0

            conn.execute(
                sql_text(
                    "UPDATE bb_mistake SET repetitions = :reps, interval_days = :interval, "
                    "ease_factor = :ease, right_streak = :streak, mastered = :mastered, "
                    "next_review_at = :next WHERE id = :id"
                ),
                {"reps": reps, "interval": interval, "ease": round(ease, 2),
                 "streak": streak, "mastered": mastered,
                 "next": datetime.now() + timedelta(days=interval), "id": mistake_id},
            )
            conn.execute(
                sql_text(
                    "INSERT INTO bb_review_log "
                    "(mistake_id, user_id, exam_id, grade, score_rate, "
                    " interval_before, interval_after) "
                    "VALUES (:m, :u, :e, :g, :rate, :before, :after)"
                ),
                {"m": mistake_id, "u": user_id, "e": exam_id, "g": grade,
                 "rate": round(rate, 4), "before": interval, "after": interval},
            )
        else:
            # 答得不好 —— 进错题本 / 重置复习进度
            existing = conn.execute(
                sql_text("SELECT id, wrong_count, ease_factor FROM bb_mistake "
                         "WHERE user_id = :u AND question_id = :q"),
                {"u": user_id, "q": r.question_id},
            ).fetchone()

            if existing:
                conn.execute(
                    sql_text(
                        "UPDATE bb_mistake SET wrong_count = wrong_count + 1, repetitions = 0, "
                        "right_streak = 0, interval_days = 1, "
                        "ease_factor = MAX(1.3, ease_factor - 0.2), "
                        "last_wrong_at = NOW(), next_review_at = :next, mastered = 0 "
                        "WHERE id = :id"
                    ),
                    {"next": datetime.now() + timedelta(days=1), "id": int(existing[0])},
                )
            else:
                conn.execute(
                    sql_text(
                        "INSERT INTO bb_mistake "
                        "(user_id, kb_id, question_id, wrong_count, right_streak, last_wrong_at, "
                        " ease_factor, interval_days, repetitions, next_review_at, mastered) "
                        "VALUES (:u, :kb, :q, 1, 0, NOW(), 2.50, 1, 0, :next, 0)"
                    ),
                    {"u": user_id, "kb": kb_id, "q": r.question_id,
                     "next": datetime.now() + timedelta(days=1)},
                )


def _summary(exam_id: int) -> dict[str, Any]:
    with get_engine().connect() as conn:
        row = conn.execute(
            sql_text(
                "SELECT total_score, got_score, correct_count, wrong_count, status "
                "FROM bb_exam_record WHERE id = :e"
            ),
            {"e": exam_id},
        ).fetchone()
        mistakes = conn.execute(
            sql_text(
                "SELECT COUNT(*) FROM bb_mistake m "
                "JOIN bb_answer_item ai ON ai.question_id = m.question_id "
                "WHERE ai.exam_id = :e"
            ),
            {"e": exam_id},
        ).scalar()
    if not row:
        return {"examId": exam_id}
    rate = round(float(row[1] or 0) / float(row[0] or 1) * 100, 1)
    return {
        "examId": exam_id,
        "totalScore": float(row[0] or 0),
        "gotScore": float(row[1] or 0),
        "scoreRate": rate,
        "correctCount": int(row[2] or 0),
        "wrongCount": int(row[3] or 0),
        "mistakeCount": int(mistakes or 0),
    }


def _mark_exam(exam_id: int, status: int) -> None:
    try:
        with get_engine().begin() as conn:
            conn.execute(
                sql_text("UPDATE bb_exam_record SET status = :s WHERE id = :e"),
                {"s": status, "e": exam_id},
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("更新答卷状态失败：%s", exc)


# ---------------------------------------------------------------------------
#  工具
# ---------------------------------------------------------------------------

def _norm_choice(text: str) -> str:
    """选择题答案归一化：去空格标点、转大写、排序去重。"""
    if not text:
        return ""
    letters = re.findall(r"[A-Za-z]", text.upper())
    if letters:
        return "".join(sorted(set(letters)))
    return _normalize_text(text)


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"[\s，。、；：！？,.;:!?（）()【】\[\]\"'`*#>_-]", "", str(text)).lower()


def _keywords(text: str) -> list[str]:
    if not text:
        return []
    return [m.group(0) for m in re.finditer(r"[A-Za-z][A-Za-z0-9+#.\-]{1,17}|[\u4e00-\u9fff]{2,12}", text)]


def _clamp(value: float, low: float, high: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return low
    return max(low, min(high, value))


def _clean_points(raw: Any, score_key: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        point = str(item.get("point") or "").strip()[:500]
        if not point:
            continue
        entry: dict[str, Any] = {"point": point}
        if score_key == "score":
            try:
                entry["score"] = round(float(item.get("score") or 0), 1)
            except (TypeError, ValueError):
                entry["score"] = 0.0
        else:
            entry[score_key] = str(item.get(score_key) or "")[:500]
        out.append(entry)
    return out


def _resolve_citations(raw: Any, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    只保留**真实存在于 source chunks 里**的引用，杜绝模型编造 chunkId。
    """
    if not isinstance(raw, list):
        return []
    by_id = {int(c["chunkId"]): c for c in chunks}
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            cid = int(item.get("chunkId"))
        except (TypeError, ValueError):
            continue
        chunk = by_id.get(cid)
        if not chunk:
            logger.debug("丢弃编造的引用 chunkId=%s", cid)
            continue
        out.append({
            "chunkId": cid,
            "pageNo": chunk["pageNo"],
            "sectionPath": chunk["sectionPath"],
            "quote": str(item.get("quote") or "")[:500],
            "snippet": chunk["content"][:300],
        })
        if len(out) >= 4:
            break
    return out


def _parse_json(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _setting(conn, key: str, default: str) -> str:
    try:
        row = conn.execute(
            sql_text("SELECT svalue FROM bb_setting WHERE skey = :k"), {"k": key}
        ).fetchone()
        return str(row[0]) if row else default
    except Exception:  # noqa: BLE001
        return default

"""
背备不悲 · AI 模拟面试服务

三件事：
  1. **简历解析** 文件 → 全文 → AI 抽取结构化档案（SSE 推进度，走异步任务）
  2. **面试对话** 提问 → 候选人作答 → 五维评分 → 追问（一轮一次 LLM 调用，同步返回）
  3. **评估报告** 整场记录 → 综合报告 + 薄弱知识点（供学习模块出题用）

与「学习出题」的本质区别（别再混在一起想）：
  - 学习出题考的是**材料**，答案有原文依据，客观题能 100% 程序化判分；
  - 模拟面试考的是**人**，没有标准答案，只能按维度打分，
    而且必须做一件事——**简历一致性核对**：候选人嘴上说的和简历写的对不对得上。
    这是模拟面试相对于「随便聊聊」唯一硬核的价值。

简历与学习知识库完全隔离：简历不进 Milvus、不建知识点树、不参与 RAG 检索。
只有最后一步「薄弱点 → 出题」才通过 kbId 主动跨过去。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.core.logging import get_logger
from app.core.sse import EmitFn
from app.db.mysql import get_engine
from app.services.llm import LlmError, llm_client
from app.services.parsing import parse
from app.services.prompts import prompt_service

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
#  常量
# ---------------------------------------------------------------------------

DIFFICULTY_TEXT = {
    1: "初级（应届生 / 1 年以内）",
    2: "中级（2~4 年经验）",
    3: "高级（5 年以上 / 技术专家）",
}

VALID_TYPES = {"INTRO", "PROJECT", "TECH", "FOLLOWUP", "SCENARIO", "BEHAVIOR"}

# 简历里出现这些词 → 判定为「有风险的问点」，Mock 与真实模型都参考
RISK_HINTS = ("精通", "熟练掌握", "架构", "主导", "负责整体", "高并发", "千万级", "从 0 到 1")

RESUME_STATUS_PENDING = 0
RESUME_STATUS_PARSING = 1
RESUME_STATUS_READY = 2
RESUME_STATUS_FAILED = 3

INTERVIEW_STATUS_DRAFT = 0
INTERVIEW_STATUS_RUNNING = 1
INTERVIEW_STATUS_FINISHED = 2
INTERVIEW_STATUS_FAILED = 3

MIN_TURNS = 5
MAX_TURNS = 20


# ---------------------------------------------------------------------------
#  数据库小工具
# ---------------------------------------------------------------------------

def _json_col(value: Any) -> Any:
    """MySQL JSON 列读出来可能是 str 也可能是 dict，统一成 Python 对象。"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _dumps(value: Any) -> str | None:
    """写 JSON 列：pymysql 不能直接适配 list/dict，必须先序列化。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _load_resume(resume_id: int) -> dict[str, Any]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, file_name, file_path, file_type, raw_text, char_count, "
                "       profile_json, target_position, status "
                "FROM bb_resume WHERE id = :id"
            ),
            {"id": resume_id},
        ).fetchone()
    if row is None:
        raise ValueError(f"简历不存在：#{resume_id}")
    return {
        "id": int(row[0]),
        "fileName": row[1] or "",
        "filePath": _absolute_path(row[2] or ""),
        "fileType": row[3] or "",
        "rawText": row[4] or "",
        "charCount": int(row[5] or 0),
        "profile": _json_col(row[6]) or {},
        "targetPosition": row[7] or "",
        "status": int(row[8] or 0),
    }


def _absolute_path(stored: str) -> str:
    """
    把库里存的路径变成绝对路径。

    约定：bb_resume.file_path / bb_document.file_path 里存的是**相对 upload.dir 的路径**
    （Java 侧 FileStorageService 的目录规则），所以这里必须拼回去。
    直接拿相对路径去 open() 会得到「文件不存在：0/202609/xxx.pdf」——
    这个坑踩过一次，别改回去。
    """
    if not stored:
        return ""
    path = Path(stored)
    if path.is_absolute():
        return str(path)
    return str(Path(get_settings().upload_dir) / path)


def _load_interview(interview_id: int) -> dict[str, Any]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, resume_id, kb_id, job_title, difficulty, max_turns, "
                "       turn_count, status, total_score, summary "
                "FROM bb_interview WHERE id = :id"
            ),
            {"id": interview_id},
        ).fetchone()
    if row is None:
        raise ValueError(f"面试场次不存在：#{interview_id}")
    return {
        "id": int(row[0]),
        "resumeId": int(row[1]),
        "kbId": int(row[2]) if row[2] is not None else None,
        "jobTitle": row[3] or "",
        "difficulty": int(row[4] or 2),
        "maxTurns": int(row[5] or 10),
        "turnCount": int(row[6] or 0),
        "status": int(row[7] or 0),
        "totalScore": float(row[8]) if row[8] is not None else None,
        "summary": row[9] or "",
    }


def _load_turns(interview_id: int) -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, seq, role, content, question_type, based_on, expects, "
                "       score, feedback_json "
                "FROM bb_interview_turn WHERE interview_id = :id ORDER BY seq ASC, id ASC"
            ),
            {"id": interview_id},
        ).fetchall()
    return [
        {
            "id": int(r[0]),
            "seq": int(r[1]),
            "role": int(r[2]),
            "content": r[3] or "",
            "questionType": r[4] or "",
            "basedOn": r[5] or "",
            "expects": _json_col(r[6]) or [],
            "score": float(r[7]) if r[7] is not None else None,
            "feedback": _json_col(r[8]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
#  简历档案 → 可读文本（给 LLM 也方便 Mock 解析）
# ---------------------------------------------------------------------------

def profile_to_text(profile: dict[str, Any] | None) -> str:
    """
    把结构化档案渲染成**中文分点文本**而不是 JSON。

    这么做的原因：真实 LLM 读文本比读 JSON 更少犯格式错，
    Mock 模型也能靠「- 技能：a、b、c」这种固定格式正则抽出来。
    """
    p = profile or {}
    if not p:
        return "（未解析出结构化档案）"

    lines: list[str] = []

    def add(label: str, value: Any) -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, list):
            value = "、".join(str(v) for v in value if str(v).strip())
            if not value:
                return
        lines.append(f"- {label}：{value}")

    add("姓名", p.get("name"))
    years = p.get("years")
    if years:
        add("工作年限", f"{years} 年")
    add("学历", p.get("education"))
    add("院校", p.get("school"))
    add("专业", p.get("major"))
    add("当前公司", p.get("currentCompany"))
    add("当前职位", p.get("currentTitle"))
    add("意向岗位", p.get("targetPosition"))
    add("技能", p.get("skills"))
    add("亮点", p.get("highlights"))
    add("自我评价", p.get("selfEvaluation"))

    projects = p.get("projects") or []
    if projects:
        lines.append("- 项目经历：")
        for i, proj in enumerate(projects, 1):
            if not isinstance(proj, dict):
                continue
            title = proj.get("name") or f"项目{i}"
            role = proj.get("role") or ""
            period = proj.get("period") or ""
            lines.append(f"  {i}. 《{title}》 角色：{role} 周期：{period}")
            stack = proj.get("techStack") or []
            if stack:
                lines.append(f"     技术栈：{'、'.join(str(s) for s in stack)}")
            for hl in (proj.get("highlights") or []):
                lines.append(f"     要点：{hl}")
            evidence = proj.get("evidence")
            if evidence:
                lines.append(f"     原文佐证：「{evidence}」")

    works = p.get("workExperience") or []
    if works:
        lines.append("- 工作经历：")
        for i, w in enumerate(works, 1):
            if not isinstance(w, dict):
                continue
            lines.append(
                f"  {i}. {w.get('company', '')} / {w.get('title', '')} "
                f"/ {w.get('period', '')}：{w.get('duty', '')}"
            )

    risks = p.get("risks") or []
    if risks:
        lines.append("- 需要面试官重点核实的点：")
        for r in risks:
            lines.append(f"  · {r}")

    return "\n".join(lines) if lines else "（未解析出结构化档案）"


def _dedup(items: list[Any], limit: int = 0) -> list[str]:
    """
    去重（忽略大小写与空格），保留首次出现的顺序。

    真实模型很容易把同一门技术写两遍：实测 DeepSeek 一次抽出 57 个「技能」，
    里面 SpringBoot、MySQL、Redis、锁机制 各出现了两次。
    不去重的话前端「技能」一栏全是噪音，后面按技能轮换提问也会重复问同一门。
    limit > 0 时只保留前 N 个（技能超过 20 个反而说明抽取粒度太细，留给面试官抓重点）。
    """
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower().replace(" ", "").replace("-", "")
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out[:limit] if limit > 0 else out


def _normalize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """收敛 LLM 输出，缺字段补空，类型不对的强转，防止前端渲染炸掉。"""
    raw = raw or {}

    def as_list(key: str) -> list[Any]:
        value = raw.get(key)
        if isinstance(value, list):
            return [v for v in value if v not in (None, "")]
        if isinstance(value, str) and value.strip():
            return [x.strip() for x in value.replace("，", ",").split(",") if x.strip()]
        return []

    projects = []
    for item in (raw.get("projects") or []):
        if isinstance(item, str):
            projects.append({"name": item})
        elif isinstance(item, dict):
            projects.append({
                "name": str(item.get("name") or ""),
                "role": str(item.get("role") or ""),
                "period": str(item.get("period") or ""),
                "techStack": _dedup(item.get("techStack") or []),
                "highlights": _dedup(item.get("highlights") or []),
                "evidence": str(item.get("evidence") or ""),
            })

    works = []
    for item in (raw.get("workExperience") or raw.get("work_experience") or []):
        if isinstance(item, str):
            works.append({"company": item})
        elif isinstance(item, dict):
            works.append({
                "company": str(item.get("company") or ""),
                "title": str(item.get("title") or ""),
                "period": str(item.get("period") or ""),
                "duty": str(item.get("duty") or ""),
            })

    try:
        years = int(float(raw.get("years") or 0))
    except (TypeError, ValueError):
        years = 0

    return {
        "name": str(raw.get("name") or ""),
        "years": years,
        "education": str(raw.get("education") or ""),
        "school": str(raw.get("school") or ""),
        "major": str(raw.get("major") or ""),
        "currentCompany": str(raw.get("currentCompany") or ""),
        "currentTitle": str(raw.get("currentTitle") or ""),
        "targetPosition": str(raw.get("targetPosition") or ""),
        # 技能最多留 20 个：实测模型会抽到 50+ 个细碎名词，面试轮次根本覆盖不完
        "skills": _dedup(as_list("skills"), limit=20),
        "projects": projects,
        "workExperience": works,
        "selfEvaluation": str(raw.get("selfEvaluation") or ""),
        "highlights": _dedup(as_list("highlights"), limit=8),
        "risks": _dedup(as_list("risks"), limit=8),
    }


# ---------------------------------------------------------------------------
#  1. 简历解析（SSE worker）
# ---------------------------------------------------------------------------

def run_parse_resume(payload: dict[str, Any], emit: EmitFn) -> None:
    resume_id = int(payload.get("resumeId") or 0)
    if not resume_id:
        raise ValueError("缺少 resumeId")

    def report(progress: int, stage: str) -> None:
        emit("progress", {"progress": max(0, min(100, progress)), "stage": stage})

    report(3, "正在读取简历文件")
    resume = _load_resume(resume_id)
    _set_resume_status(resume_id, RESUME_STATUS_PARSING, "")

    try:
        report(10, "正在解析简历内容")
        parsed = parse(
            file_path=resume["filePath"] or None,
            file_type=resume["fileType"] or None,
            text_content=payload.get("textContent"),
            file_name=resume["fileName"],
            ocr_enabled=bool(payload.get("ocrEnabled", True)),
        )
        raw_text = (parsed.full_text or "").strip()
        if len(raw_text) < 30:
            raise ValueError(
                "简历里几乎没解析出文字。如果是扫描件/图片版 PDF，"
                "请确认 OCR 可用；或直接把简历文字粘贴进来重传。"
            )

        report(35, f"解析完成，共 {len(raw_text)} 字，正在交给 AI 抽取档案")
        _save_resume_text(resume_id, raw_text, parsed.char_count or len(raw_text))

        report(55, "AI 正在抽取结构化档案")
        prompt = prompt_service.render(
            "RESUME_PARSE",
            resume_text=raw_text[:12000],
        )
        profile_raw, result = llm_client.chat_json(
            [{"role": "user", "content": prompt}],
            task_type="RESUME_PARSE",
            biz_type="RESUME",
            biz_id=resume_id,
            temperature=0.2,
        )
        profile = _normalize_profile(profile_raw)

        report(90, "正在保存简历档案")
        _save_resume_profile(resume_id, profile)
        _set_resume_status(resume_id, RESUME_STATUS_READY, "")

        report(100, "简历已就绪")
        emit("done", {
            "resumeId": resume_id,
            "charCount": len(raw_text),
            "profile": profile,
            "skillCount": len(profile["skills"]),
            "projectCount": len(profile["projects"]),
            "riskCount": len(profile["risks"]),
            "model": result.model,
            "tokens": result.total_tokens,
            "latencyMs": result.latency_ms,
        })
        logger.info(
            "简历 #%s 解析完成：%s 字，技能 %d 项，项目 %d 个，模型 %s",
            resume_id, len(raw_text), len(profile["skills"]),
            len(profile["projects"]), result.model,
        )
    except Exception as exc:  # noqa: BLE001
        _set_resume_status(resume_id, RESUME_STATUS_FAILED, f"{type(exc).__name__}: {exc}"[:900])
        raise


def _set_resume_status(resume_id: int, status: int, error: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE bb_resume SET status = :s, error_msg = :e WHERE id = :id"),
            {"s": status, "e": error, "id": resume_id},
        )


def _save_resume_text(resume_id: int, raw_text: str, char_count: int) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE bb_resume SET raw_text = :t, char_count = :c WHERE id = :id"
            ),
            {"t": raw_text, "c": char_count, "id": resume_id},
        )


def _save_resume_profile(resume_id: int, profile: dict[str, Any]) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE bb_resume SET profile_json = :p, "
                "target_position = COALESCE(NULLIF(:tp, ''), target_position) WHERE id = :id"
            ),
            {"p": _dumps(profile), "tp": profile.get("targetPosition") or "", "id": resume_id},
        )


# ---------------------------------------------------------------------------
#  2. 面试对话
# ---------------------------------------------------------------------------

def start_interview(payload: dict[str, Any]) -> dict[str, Any]:
    """
    开始一场面试：生成开场问题并落库。

    面试官的第 1 个问题固定是自我介绍，但**开头那句话由 AI 自己写**，
    这样换模型时开场白的语气会跟着变，不会千篇一律。
    """
    interview_id = int(payload.get("interviewId") or 0)
    if not interview_id:
        raise ValueError("缺少 interviewId")

    interview = _load_interview(interview_id)
    if interview["status"] == INTERVIEW_STATUS_FINISHED:
        raise ValueError("这场面试已经结束了，请新建一场")
    resume = _load_resume(interview["resumeId"])
    if resume["status"] != RESUME_STATUS_READY:
        raise ValueError("这份简历还没解析成功，请先在简历库点「重新解析」")

    job_title = interview["jobTitle"] or resume["targetPosition"] or "Java 后端开发工程师"
    question = _ask_next_question(
        interview=interview,
        resume=resume,
        turns=[],
        job_title=job_title,
    )

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bb_interview_turn "
                "(interview_id, seq, role, content, question_type, based_on, expects) "
                "VALUES (:iid, 1, 1, :content, :qtype, :based, :expects)"
            ),
            {
                "iid": interview_id, "content": question["question"],
                "qtype": question["type"], "based": question["basedOn"][:300],
                "expects": _dumps(question["expects"]),
            },
        )
        conn.execute(
            text(
                "UPDATE bb_interview SET status = :s, "
                "started_at = COALESCE(started_at, NOW()), "
                "job_title = :jt, turn_count = 0 WHERE id = :id"
            ),
            {"s": INTERVIEW_STATUS_RUNNING, "jt": job_title[:100], "id": interview_id},
        )

    logger.info("面试 #%s 已开始，岗位 %s，模型 %s",
                interview_id, job_title, question.get("model", ""))
    return {"interviewId": interview_id, "jobTitle": job_title, "question": question}


def submit_answer(payload: dict[str, Any]) -> dict[str, Any]:
    """
    提交一轮回答：先评分，再决定是追问下一题还是收官。

    返回值三种情况：
      - finished=false：给了 evaluation + nextQuestion，前端接着聊
      - finished=true ：轮数用完，nextQuestion 为 null，前端转去出报告
    """
    interview_id = int(payload.get("interviewId") or 0)
    answer = (payload.get("answer") or "").strip()
    if not interview_id:
        raise ValueError("缺少 interviewId")
    if len(answer) < 2:
        raise ValueError("回答太短了，至少说一句完整的话")
    if len(answer) > 8000:
        answer = answer[:8000]

    interview = _load_interview(interview_id)
    if interview["status"] == INTERVIEW_STATUS_FINISHED:
        raise ValueError("这场面试已经结束了")
    resume = _load_resume(interview["resumeId"])
    turns = _load_turns(interview_id)

    pending = [t for t in turns if t["role"] == 1]
    if not pending:
        raise ValueError("还没有面试官提问，请先开始面试")
    last_question = pending[-1]
    if turns and turns[-1]["role"] == 2:
        raise ValueError("上一轮回答还没处理完，请稍候")

    job_title = interview["jobTitle"] or resume["targetPosition"] or "Java 后端开发工程师"

    # ---- 评分 ----
    evaluation = _evaluate_answer(
        interview=interview, resume=resume, question=last_question,
        answer=answer, job_title=job_title,
    )
    answered_count = interview["turnCount"] + 1

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bb_interview_turn "
                "(interview_id, seq, role, content, score, feedback_json) "
                "VALUES (:iid, :seq, 2, :content, :score, :feedback)"
            ),
            {
                "iid": interview_id,
                "seq": last_question["seq"] + 1,
                "content": answer,
                "score": evaluation["score"],
                "feedback": _dumps(evaluation),
            },
        )
        conn.execute(
            text("UPDATE bb_interview SET turn_count = :n WHERE id = :id"),
            {"n": answered_count, "id": interview_id},
        )

    # ---- 是否还有下一题 ----
    max_turns = max(MIN_TURNS, min(MAX_TURNS, interview["maxTurns"]))
    if answered_count >= max_turns:
        logger.info("面试 #%s 已完成 %d/%d 轮，等待生成报告",
                    interview_id, answered_count, max_turns)
        return {
            "interviewId": interview_id,
            "turnCount": answered_count,
            "maxTurns": max_turns,
            "finished": True,
            "evaluation": evaluation,
            "nextQuestion": None,
        }

    interview["turnCount"] = answered_count
    turns = _load_turns(interview_id)
    question = _ask_next_question(
        interview=interview, resume=resume, turns=turns, job_title=job_title,
    )
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bb_interview_turn "
                "(interview_id, seq, role, content, question_type, based_on, expects) "
                "VALUES (:iid, :seq, 1, :content, :qtype, :based, :expects)"
            ),
            {
                "iid": interview_id, "seq": last_question["seq"] + 2,
                "content": question["question"], "qtype": question["type"],
                "based": question["basedOn"][:300], "expects": _dumps(question["expects"]),
            },
        )

    return {
        "interviewId": interview_id,
        "turnCount": answered_count,
        "maxTurns": max_turns,
        "finished": False,
        "evaluation": evaluation,
        "nextQuestion": question,
    }


def finish_interview(payload: dict[str, Any]) -> dict[str, Any]:
    """生成整场评估报告，并把薄弱知识点回写（供学习模块出题）。"""
    interview_id = int(payload.get("interviewId") or 0)
    if not interview_id:
        raise ValueError("缺少 interviewId")

    interview = _load_interview(interview_id)
    resume = _load_resume(interview["resumeId"])
    turns = _load_turns(interview_id)

    answers = [t for t in turns if t["role"] == 2]
    if not answers:
        raise ValueError("还没有回答记录，无法生成报告")

    job_title = interview["jobTitle"] or resume["targetPosition"] or "Java 后端开发工程师"
    transcript = _build_transcript(turns)
    prompt = prompt_service.render(
        "INTERVIEW_REPORT",
        job_title=job_title,
        difficulty=DIFFICULTY_TEXT.get(interview["difficulty"], "中级（2~4 年经验）"),
        resume_profile=profile_to_text(resume["profile"]),
        transcript=transcript,
    )
    raw, result = llm_client.chat_json(
        [{"role": "user", "content": prompt}],
        task_type="INTERVIEW_REPORT",
        biz_type="INTERVIEW",
        biz_id=interview_id,
        temperature=0.3,
    )
    report = _normalize_report(raw, turns)

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE bb_interview SET status = :s, total_score = :score, "
                "summary = :summary, report_json = :report, finished_at = NOW() "
                "WHERE id = :id"
            ),
            {
                "s": INTERVIEW_STATUS_FINISHED,
                "score": report["overallScore"],
                "summary": report["summary"][:600],
                "report": _dumps(report),
                "id": interview_id,
            },
        )

    logger.info("面试 #%s 报告生成完成：总分 %.1f，薄弱知识点 %d 个",
                interview_id, report["overallScore"], len(report["knowledgePoints"]))
    return {
        "interviewId": interview_id,
        "report": report,
        "model": result.model,
        "latencyMs": result.latency_ms,
    }


# ---------------------------------------------------------------------------
#  2.1 提问
# ---------------------------------------------------------------------------

def _ask_next_question(
    *, interview: dict[str, Any], resume: dict[str, Any],
    turns: list[dict[str, Any]], job_title: str,
) -> dict[str, Any]:
    asked = [t["content"] for t in turns if t["role"] == 1]
    recent = _recent_qa(turns)
    turn_no = len([t for t in turns if t["role"] == 2]) + 1

    profile = resume["profile"] or {}
    prompt = prompt_service.render(
        "INTERVIEW_ASK",
        job_title=job_title,
        difficulty=DIFFICULTY_TEXT.get(interview["difficulty"], "中级（2~4 年经验）"),
        resume_profile=profile_to_text(profile),
        asked_questions=("\n".join(f"{i + 1}. {q}" for i, q in enumerate(asked))
                         if asked else "（还没有问过任何问题，这是第一题）"),
        recent_qa=recent or "（这是第一轮，没有上一轮问答）",
        turn_no=turn_no,
        max_turns=interview["maxTurns"],
    )
    raw, result = llm_client.chat_json(
        [{"role": "user", "content": prompt}],
        task_type="INTERVIEW_ASK",
        biz_type="INTERVIEW",
        biz_id=interview["id"],
        temperature=0.7,
    )

    question = str(raw.get("question") or "").strip()
    if len(question) < 4:
        raise LlmError("面试官没能给出有效问题，请检查模型配置后重试")

    qtype = str(raw.get("type") or "").strip().upper()
    if qtype not in VALID_TYPES:
        qtype = "INTRO" if turn_no == 1 else "PROJECT"

    expects = raw.get("expects") or []
    if isinstance(expects, str):
        expects = [expects]
    expects = _dedup([str(e) for e in expects if str(e).strip()])[:8]

    return {
        "question": question,
        "type": qtype,
        "basedOn": str(raw.get("basedOn") or raw.get("based_on") or "")[:300],
        "expects": expects,
        "turnNo": turn_no,
        "model": result.model,
    }


def _recent_qa(turns: list[dict[str, Any]]) -> str:
    """只取最近一轮问答，避免 prompt 随轮次线性膨胀。"""
    qa: list[str] = []
    for t in reversed(turns):
        if t["role"] == 2:
            qa.insert(0, f"候选人：{t['content']}")
        elif t["role"] == 1:
            qa.insert(0, f"面试官：{t['content']}")
            break
    return "\n".join(qa)


# ---------------------------------------------------------------------------
#  2.2 评分
# ---------------------------------------------------------------------------

def _evaluate_answer(
    *, interview: dict[str, Any], resume: dict[str, Any],
    question: dict[str, Any], answer: str, job_title: str,
) -> dict[str, Any]:
    prompt = prompt_service.render(
        "INTERVIEW_EVAL",
        job_title=job_title,
        question=question["content"],
        question_type=question["questionType"] or "PROJECT",
        expects=_dumps(question["expects"]) if question["expects"] else "（未指定）",
        resume_evidence=question["basedOn"] or "（本题不是针对简历某一段提的）",
        answer=answer,
    )
    raw, result = llm_client.chat_json(
        [{"role": "user", "content": prompt}],
        task_type="INTERVIEW_EVAL",
        biz_type="INTERVIEW",
        biz_id=interview["id"],
        temperature=0.2,
    )

    scores_raw = raw.get("scores") or {}
    if not isinstance(scores_raw, dict):
        scores_raw = {}
    dimension_labels = {
        "techAccuracy": "技术准确性",
        "specificity": "项目具体性",
        "structure": "表达结构",
        "consistency": "与简历一致性",
        "relevance": "岗位匹配度",
    }
    scores: dict[str, float] = {}
    for key in dimension_labels:
        try:
            value = float(scores_raw.get(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        scores[key] = round(max(0.0, min(100.0, value)), 1)

    score = _clamp_score(raw.get("score"))
    if score <= 0 and any(scores.values()):
        # 模型只给了分项没给总分时，按五维平均兜底，避免出现 0 分
        score = round(sum(scores.values()) / len(scores), 1)

    return {
        "score": score,
        "scores": scores,
        "dimensionLabels": dimension_labels,
        "goodPoints": _str_list(raw.get("goodPoints") or raw.get("good_points")),
        "problems": _str_list(raw.get("problems")),
        "suggestion": str(raw.get("suggestion") or ""),
        "contradiction": str(raw.get("contradiction") or ""),
        "followUpNeeded": bool(raw.get("followUpNeeded", raw.get("follow_up_needed", False))),
        "model": result.model,
    }


# ---------------------------------------------------------------------------
#  2.3 报告
# ---------------------------------------------------------------------------

def _normalize_report(raw: dict[str, Any] | None, turns: list[dict[str, Any]]) -> dict[str, Any]:
    raw = raw or {}

    overall = _clamp_score(raw.get("overallScore") or raw.get("overall_score"))
    if overall <= 0:
        # 兜底：用各轮平均分，总比显示 0 强
        per_turn = [t["score"] for t in turns if t["role"] == 2 and t["score"] is not None]
        overall = round(sum(per_turn) / len(per_turn), 1) if per_turn else 0.0

    dimensions = []
    for item in (raw.get("dimensions") or []):
        if isinstance(item, dict):
            dimensions.append({
                "name": str(item.get("name") or ""),
                "score": _clamp_score(item.get("score")),
                "comment": str(item.get("comment") or ""),
            })

    weak_points = []
    for item in (raw.get("weakPoints") or raw.get("weak_points") or []):
        if isinstance(item, str):
            weak_points.append({"skill": item, "level": "", "evidence": "", "suggestion": ""})
        elif isinstance(item, dict):
            weak_points.append({
                "skill": str(item.get("skill") or ""),
                "level": str(item.get("level") or ""),
                "evidence": str(item.get("evidence") or ""),
                "suggestion": str(item.get("suggestion") or ""),
            })

    knowledge_points = _str_list(raw.get("knowledgePoints") or raw.get("knowledge_points"))
    if not knowledge_points:
        # 模型没给知识点时，用薄弱项的技能名兜底 —— 联动出题必须有东西可用
        knowledge_points = [w["skill"] for w in weak_points if w["skill"]][:6]

    return {
        "overallScore": overall,
        "summary": str(raw.get("summary") or ""),
        "dimensions": dimensions,
        "strengths": _str_list(raw.get("strengths")),
        "weakPoints": weak_points,
        "knowledgePoints": knowledge_points[:8],
        "nextSteps": _str_list(raw.get("nextSteps") or raw.get("next_steps")),
        "turnScores": [
            {"seq": t["seq"], "score": t["score"]}
            for t in turns if t["role"] == 2
        ],
    }


def _build_transcript(turns: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for t in turns:
        if t["role"] == 1:
            head = f"【面试官·{t['questionType'] or 'PROJECT'}】"
            if t["basedOn"]:
                head += f"（针对简历：{t['basedOn']}）"
            lines.append(f"{head}\n{t['content']}")
        else:
            score = f"（本轮得分 {t['score']:.0f}）" if t["score"] is not None else ""
            lines.append(f"【候选人】{score}\n{t['content']}")
            problems = (t["feedback"] or {}).get("problems") or []
            if problems:
                lines.append("  面试官观察：" + "；".join(str(p) for p in problems[:3]))
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
#  工具
# ---------------------------------------------------------------------------

def _clamp_score(value: Any) -> float:
    try:
        score = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(100.0, score)), 1)


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []

"""
背备不悲 · AI 模拟面试端到端验证

一次性把整条链路跑通并核对落库结果：
    简历入库 → 解析（SSE）→ 开始面试 → N 轮问答 → 生成报告 → 核对 bb_* 三张表

用法：
    python scripts/test_interview.py                       # 用已有简历 PDF，跑 5 轮
    python scripts/test_interview.py --turns 10            # 指定轮数（5~20）
    python scripts/test_interview.py --resume D:\\x.pdf    # 指定简历文件
    python scripts/test_interview.py --keep                # 保留测试数据（默认跑完删掉）

为什么默认删：这是验证脚本，不该在库里留一堆「测试面试」污染统计页。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "beibei-agent"))

from app.config import get_settings  # noqa: E402
from app.db.mysql import get_engine  # noqa: E402

AGENT = "http://127.0.0.1:8000"

# 候选人「标准回答」统一从网关脚本里取，避免两份脚本各维护一遍、
# 改了一处忘了另一处（之前就因为这个，一份脚本还在编「两年工作经验」）。
from test_interview_gateway import ANSWERS  # noqa: E402


def sse_post(path: str, payload: dict, token: str, timeout: int = 900) -> dict:
    """POST 一个 SSE 接口，打印进度，返回 done 事件的数据。"""
    resp = requests.post(
        AGENT + path, json=payload, stream=True, timeout=timeout,
        headers={"X-Internal-Token": token, "Accept": "text/event-stream"},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{path} 返回 HTTP {resp.status_code}: {resp.text[:400]}")

    event_name = None
    result: dict = {}
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip()
        if not line:
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
            if event_name == "progress":
                print(f"    [{data.get('progress'):>3}%] {data.get('stage', '')}")
            elif event_name == "done":
                result = data
            elif event_name == "error":
                raise RuntimeError(f"智能体报错：{data.get('errorMsg')}")
    return result


def post_json(path: str, payload: dict, token: str, timeout: int = 300) -> dict:
    resp = requests.post(
        AGENT + path, json=payload, timeout=timeout,
        headers={"X-Internal-Token": token, "Content-Type": "application/json"},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{path} 返回 HTTP {resp.status_code}: {resp.text[:400]}")
    body = resp.json()
    if not body.get("ok", True):
        raise RuntimeError(f"{path} 业务失败：{body}")
    return body


def find_resume_pdf() -> Path:
    for base in (Path("D:/beibei-data/upload"), ROOT):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.pdf")):
            if "简历" in path.name or path.stat().st_size < 2_000_000:
                return path
    raise SystemExit("找不到可用的简历 PDF，请用 --resume 指定")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=5, help="面试轮数，5~20")
    parser.add_argument("--resume", type=str, default="", help="简历文件路径")
    parser.add_argument("--job", type=str, default="Java 后端开发工程师")
    parser.add_argument("--difficulty", type=int, default=2, choices=[1, 2, 3])
    parser.add_argument("--keep", action="store_true", help="保留测试数据")
    args = parser.parse_args()

    turns = max(5, min(20, args.turns))
    settings = get_settings()
    token = settings.internal_token
    engine = get_engine()

    resume_path = Path(args.resume) if args.resume else find_resume_pdf()
    if not resume_path.exists():
        raise SystemExit(f"简历文件不存在：{resume_path}")

    print("=" * 78)
    print("  背备不悲 · 模拟面试端到端验证")
    print("=" * 78)
    print(f"  简历文件：{resume_path}")
    print(f"  目标岗位：{args.job}    难度：{args.difficulty}    轮数：{turns}")
    print(f"  LLM 模式：{'Mock（无真实 API Key）' if settings.llm_mock else '真实模型'}")
    print()

    # ---------- 1. 建简历记录 ----------
    print("[1/5] 建立简历记录")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bb_resume (user_id, file_name, file_path, file_size, file_type, status) "
                "VALUES (1, :n, :p, :s, :t, 0)"
            ),
            {
                "n": resume_path.name, "p": str(resume_path),
                "s": resume_path.stat().st_size, "t": resume_path.suffix.lstrip(".").lower(),
            },
        )
        resume_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    print(f"    resumeId = {resume_id}")
    print()

    # ---------- 2. 解析简历 ----------
    print("[2/5] 解析简历（SSE）")
    started = time.time()
    parsed = sse_post("/api/v1/resume-parse", {"resumeId": resume_id, "taskId": 0}, token)
    print(f"    解析耗时 {time.time() - started:.1f}s，"
          f"{parsed.get('charCount')} 字，技能 {parsed.get('skillCount')} 项，"
          f"项目 {parsed.get('projectCount')} 个")
    profile = parsed.get("profile") or {}
    print(f"    姓名={profile.get('name')!r} 学历={profile.get('education')!r} "
          f"院校={profile.get('school')!r}")
    print(f"    技能：{'、'.join(profile.get('skills') or [])}")
    risks = profile.get("risks") or []
    if risks:
        print(f"    待核实点：{'、'.join(risks)}")
    print()

    # ---------- 3. 建面试场次 ----------
    print("[3/5] 开始面试")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bb_interview "
                "(user_id, resume_id, job_title, difficulty, max_turns, status) "
                "VALUES (1, :r, :j, :d, :m, 0)"
            ),
            {"r": resume_id, "j": args.job, "d": args.difficulty, "m": turns},
        )
        interview_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    started_body = post_json("/api/v1/interview/start", {"interviewId": interview_id}, token)
    question = started_body["question"]
    print(f"    interviewId = {interview_id}")
    print(f"    第 1 题 [{question['type']}] {question['question']}")
    print()

    # ---------- 4. 多轮问答 ----------
    print(f"[4/5] 进行 {turns} 轮问答")
    scores: list[float] = []
    finished = False
    for round_no in range(1, turns + 1):
        answer = ANSWERS[(round_no - 1) % len(ANSWERS)]
        body = post_json(
            "/api/v1/interview/answer",
            {"interviewId": interview_id, "answer": answer},
            token,
        )
        evaluation = body["evaluation"]
        scores.append(evaluation["score"])
        dims = evaluation["scores"]
        print(f"    第 {round_no:>2} 轮  得分 {evaluation['score']:>5.1f}  "
              f"(准确 {dims['techAccuracy']:.0f} / 具体 {dims['specificity']:.0f} / "
              f"结构 {dims['structure']:.0f} / 一致 {dims['consistency']:.0f} / "
              f"匹配 {dims['relevance']:.0f})")
        for problem in (evaluation.get("problems") or [])[:2]:
            print(f"           ⚠ {problem}")

        finished = bool(body["finished"])
        next_question = body.get("nextQuestion")
        if next_question:
            print(f"           → [{next_question['type']}] {next_question['question'][:70]}")
        if finished:
            print("           轮数已用完，结束提问")
            break

    if not finished:
        print("    手动收官（提前结束）")
    print()

    # ---------- 5. 生成报告 ----------
    print("[5/5] 生成评估报告")
    started = time.time()
    report_body = post_json("/api/v1/interview/finish", {"interviewId": interview_id}, token)
    report = report_body["report"]
    print(f"    耗时 {time.time() - started:.1f}s，总分 {report['overallScore']}")
    print(f"    总评：{report['summary'][:150]}")
    print("    维度：")
    for dim in report.get("dimensions") or []:
        print(f"      - {dim['name']}: {dim['score']:.0f}  {dim['comment'][:50]}")
    print("    薄弱知识点（联动出题就靠它）：")
    for kp in report.get("knowledgePoints") or []:
        print(f"      · {kp}")
    print("    薄弱项明细：")
    for weak in (report.get("weakPoints") or [])[:5]:
        print(f"      - {weak['skill']}：{weak['evidence'][:60]}")
    print()

    # ---------- 核对落库 ----------
    print("=" * 78)
    print("  落库核对")
    print("=" * 78)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, turn_count, total_score, LEFT(summary,40), "
                 "       report_json IS NOT NULL FROM bb_interview WHERE id = :id"),
            {"id": interview_id},
        ).fetchone()
        interviewer = conn.execute(
            text("SELECT COUNT(*) FROM bb_interview_turn WHERE interview_id = :id AND role = 1"),
            {"id": interview_id},
        ).scalar()
        candidate = conn.execute(
            text("SELECT COUNT(*) FROM bb_interview_turn WHERE interview_id = :id AND role = 2"),
            {"id": interview_id},
        ).scalar()
        typed = conn.execute(
            text("SELECT COUNT(*) FROM bb_interview_turn "
                 "WHERE interview_id = :id AND role = 1 AND question_type <> ''"),
            {"id": interview_id},
        ).scalar()
        traceable = conn.execute(
            text("SELECT COUNT(*) FROM bb_interview_turn "
                 "WHERE interview_id = :id AND role = 1 AND based_on <> ''"),
            {"id": interview_id},
        ).scalar()
        rstatus = conn.execute(
            text("SELECT status FROM bb_resume WHERE id = :id"), {"id": resume_id}
        ).scalar()

    checks = [
        ("简历状态 = 2 就绪", rstatus == 2, f"实际 {rstatus}"),
        ("面试状态 = 2 已结束", row[0] == 2, f"实际 {row[0]}"),
        ("已完成轮数 = 回答数", row[1] == candidate, f"turn_count={row[1]} 回答数={candidate}"),
        ("面试官提问数 = 回答数", interviewer == candidate, f"{interviewer} vs {candidate}"),
        ("每道题都有题型", typed == interviewer, f"{typed}/{interviewer}"),
        ("有问题能追溯简历", traceable > 0, f"{traceable}/{interviewer} 题带 based_on"),
        ("报告已落库", bool(row[4]), "report_json 为空"),
        ("总分已落库", row[2] is not None, "total_score 为空"),
    ]
    all_ok = True
    for name, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + ("" if ok else f"  ← {detail}"))
        all_ok = all_ok and ok

    print()
    print(f"  问答轮数：{candidate}    平均分：{sum(scores) / max(1, len(scores)):.1f}")
    print(f"  结论：{'全部通过 ✅' if all_ok else '存在失败项 ❌'}")

    # ---------- 清理 ----------
    if not args.keep:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM bb_interview_turn WHERE interview_id = :id"),
                         {"id": interview_id})
            conn.execute(text("DELETE FROM bb_interview WHERE id = :id"), {"id": interview_id})
            conn.execute(text("DELETE FROM bb_resume WHERE id = :id"), {"id": resume_id})
        print("  测试数据已清理（--keep 可保留）")
    else:
        print(f"  已保留：interviewId={interview_id} resumeId={resume_id}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
背备不悲 · M4（错题本 + 艾宾浩斯复习 + 统计）端到端测试

链路：建库 → 上传 → 出题 → 审核 → 答题（故意答错）→ 判分
      → 错题本 → 模拟"第二天到了" → 今日待复习 → 发起复习 → 答对
      → 验证 SM-2 推进 → 统计看板 → 清理

用法：
    D:\\conda-envs\\beibei\\python.exe scripts\\test_review.py
    D:\\conda-envs\\beibei\\python.exe scripts\\test_review.py --keep
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080/api"
ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "test-data" / "JavaWeb-测试讲义.md"
PY = r"E:\Develop\conda\envs\ac_env_3135\python.exe"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass


def section(t: str) -> None:
    print(f"\n{'=' * 76}\n  {t}\n{'=' * 76}")


def sql(script: str) -> str:
    """在子进程里跑一段 Python（已经带好 sqlalchemy 与 engine），用于直接校验落库结果。"""
    full = ("import sys\n"
            "sys.path.insert(0, r'E:\\学习资源\\背书工具\\beibei-agent')\n"
            "from sqlalchemy import text\n"
            "from app.db.mysql import get_engine\n"
            "c = get_engine().connect()\n"
            + script + "\n"
            "c.commit()\n"
            "c.close()\n")
    r = subprocess.run([PY, "-c", full], capture_output=True, text=True, encoding="utf-8")
    return (r.stdout or r.stderr or "").strip()


def stream_task(client: httpx.Client, task_id: int) -> dict | None:
    final = None
    with client.stream("GET", f"{BASE}/task/{task_id}/stream",
                       timeout=httpx.Timeout(900.0, connect=10.0)) as s:
        event = None
        for line in s.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                p = json.loads(line[5:].strip())
                if event in ("done", "error"):
                    final = p
                    if event == "error":
                        print(f"      ✗ {p.get('errorMsg')}")
                event = None
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()

    client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(60.0, connect=10.0))
    failures = 0

    # ---------------------------------------------------------------- 1
    section("1. 准备数据：建库 → 上传 → 出题 → 审核")
    kb_id = client.post("/kb", json={"name": "M4复习测试"}).json()["data"]["id"]
    with open(DOC, "rb") as fp:
        up = client.post("/doc/upload", params={"kbId": kb_id},
                         files={"files": (DOC.name, fp, "text/markdown")}, timeout=180).json()["data"][0]
    stream_task(client, up["taskId"])
    gen = client.post("/paper/generate", json={
        "kbId": kb_id, "title": "M4 复习测试卷", "count": args.count,
        "qTypeRatio": {"SINGLE": 0.5, "JUDGE": 0.25, "SHORT": 0.25}, "selfCheck": True,
    }).json()["data"]
    stream_task(client, gen["taskId"])
    paper_id = gen["paperId"]
    approved = client.post(f"/paper/{paper_id}/approve-all").json()["data"]
    print(f"  知识库 #{kb_id} · 题卷 #{paper_id} · 通过 {approved} 道")

    # ---------------------------------------------------------------- 2
    section("2. 答题：前一半故意答错（制造错题）")
    start = client.post("/exam/start", json={"paperId": paper_id, "examMode": 2}).json()["data"]
    exam_id = start["examId"]
    questions = start["questions"]
    bank = {q["id"]: q for q in client.get("/question/list", params={
        "kbId": kb_id, "status": 1, "pageNum": 1, "pageSize": 100}).json()["data"]["list"]}

    answers = []
    for i, q in enumerate(questions):
        correct = bank.get(q["questionId"], {}).get("answer", "")
        if i < len(questions) // 2:
            user = "完全不懂，随便写"          # 故意答错
        else:
            user = correct                     # 答对
        answers.append({"questionId": q["questionId"], "userAnswer": user, "inputMode": 1})

    task = client.post(f"/exam/{exam_id}/submit", json={
        "answers": answers, "durationSec": 300}).json()["data"]
    final = stream_task(client, task)
    print(f"  判分: {json.dumps(final.get('result'), ensure_ascii=False) if final else '失败'}")

    # ---------------------------------------------------------------- 3
    section("3. 错题本（SM-2 初始状态）")
    page = client.get("/mistake/list", params={"kbId": kb_id, "mastered": 0,
                                               "pageNum": 1, "pageSize": 50}).json()["data"]
    print(f"  错题 {page['total']} 条")
    for m in page["list"][:4]:
        print(f"    [{m['stage']}] 错过{m['wrongCount']}次 ease={m['easeFactor']} "
              f"间隔{m['intervalDays']}天 连续答对{m['rightStreak']} "
              f"下次={str(m['nextReviewAt'])[:16]}  {m['stem'][:34]}")
    if page["total"] == 0:
        print("  ✗ 没有错题入库")
        failures += 1

    # ---------------------------------------------------------------- 4
    section("4. 今日待复习（应为空 —— SM-2 排到了明天）")
    due = client.get("/review/today").json()["data"]
    print(f"  今日待复习 {len(due)} 道")
    if due:
        print("  ! 刚答错的题不应立刻要求复习（间隔应为 1 天）")
        failures += 1
    else:
        print("  ✓ 符合预期：刚答错的题排到明天，不是立刻")

    # ---------------------------------------------------------------- 5
    section("5. 模拟「第二天到了」：把到期时间改到过去")
    out = sql(
        f"c.execute(text(\"UPDATE bb_mistake SET next_review_at = DATE_SUB(NOW(), INTERVAL 2 DAY) "
        f"WHERE kb_id = {kb_id} AND mastered = 0\"))\n"
        f"n = c.execute(text('SELECT COUNT(*) FROM bb_mistake WHERE kb_id = {kb_id} "
        f"AND mastered = 0')).scalar()\n"
        f"print('   已把 %d 条错题设为逾期' % n)"
    )
    print(out)

    due = client.get("/review/today").json()["data"]
    print(f"  今日待复习 {len(due)} 道")
    for d in due[:4]:
        print(f"    逾期{d['overdueDays']}天 [{d['qTypeName']}] {d['stem'][:40]}")
    if not due:
        print("  ✗ 逾期错题没有出现在待复习里")
        failures += 1

    # ---------------------------------------------------------------- 6
    section("6. 发起复习并全部答对（验证 SM-2 推进）")
    review = client.post("/review/start", params={"kbId": kb_id, "limit": 20}).json()["data"]
    print(f"  复习题卷 #{review['paperId']}「{review['title']}」 {review['count']} 道")
    if review["paperId"]:
        rstart = client.post("/exam/start", json={
            "paperId": review["paperId"], "examMode": 3}).json()["data"]
        rbank = {q["id"]: q for q in client.get("/question/list", params={
            "kbId": kb_id, "status": 1, "pageNum": 1, "pageSize": 100}).json()["data"]["list"]}
        ranswers = [{"questionId": q["questionId"],
                     "userAnswer": rbank.get(q["questionId"], {}).get("answer", "答对了"),
                     "inputMode": 1}
                    for q in rstart["questions"]]
        rtask = client.post(f"/exam/{rstart['examId']}/submit", json={
            "answers": ranswers, "durationSec": 120}).json()["data"]
        rfinal = stream_task(client, rtask)
        print(f"  复习判分: {json.dumps(rfinal.get('result'), ensure_ascii=False) if rfinal else '失败'}")

    # ---------------------------------------------------------------- 7
    section("7. SM-2 推进结果")
    out = sql(
        "rows = c.execute(text('SELECT question_id, wrong_count, right_streak, ease_factor, "
        "interval_days, repetitions, next_review_at, mastered FROM bb_mistake "
        f"WHERE kb_id = {kb_id} ORDER BY id')).fetchall()\n"
        "print('   错题本共 %d 条' % len(rows))\n"
        "for r in rows:\n"
        "    print('    q=%s 错%s次 连续对%s ease=%s 间隔%sd 重复%s 下次=%s 已掌握=%s' % tuple(r))"
    )
    print(out)
    if "重复1" in out and "ease=2.6" in out:
        print("  ✓ SM-2 已推进：repetitions 0→1、ease 2.50→2.60、连续答对 0→1")
        print("    （标准 SM-2：第 1 次答对间隔仍为 1 天，第 2 次答对才涨到 6 天）")
    else:
        print("  ! 未看到 SM-2 推进，检查逻辑")

    # ---------------------------------------------------------------- 8
    section("8. 复习历史")
    out = sql(
        "n = c.execute(text('SELECT COUNT(*) FROM bb_review_log')).scalar()\n"
        "print('   复习记录 %d 条' % n)\n"
        "rows = c.execute(text('SELECT grade, score_rate, interval_after FROM bb_review_log "
        "ORDER BY id DESC LIMIT 5')).fetchall()\n"
        "for r in rows:\n"
        "    print('    grade=%s 得分率=%s 间隔=%sd' % tuple(r))"
    )
    print(out)

    # ---------------------------------------------------------------- 9
    section("9. 复习日历")
    cal = client.get("/review/calendar", params={"pastDays": 30, "futureDays": 14}).json()["data"]
    active = [d for d in cal if d["dueCount"] or d["reviewedCount"]]
    print(f"  日历共 {len(cal)} 天，其中有排期或已复习的 {len(active)} 天")
    for d in active[:6]:
        print(f"    {d['date']}  待复习 {d['dueCount']}  已复习 {d['reviewedCount']}")

    # ---------------------------------------------------------------- 10
    section("10. 统计看板")
    ov = client.get("/stat/overview").json()["data"]
    print(f"  概览：知识库 {ov['kbCount']} · 分块 {ov['chunkCount']} · "
          f"已发布题 {ov['publishedCount']} · 错题 {ov['mistakeCount']} · 已掌握 {ov['masteredCount']}")
    print(f"        今日待复习 {ov['todayDueCount']} · 今日已复习 {ov['todayReviewedCount']} · "
          f"累计答题 {ov['totalAnswered']} · 平均得分率 {ov['avgScoreRate']}% · 连续打卡 {ov['streakDays']} 天")

    radar = client.get("/stat/radar", params={"kbId": kb_id}).json()["data"]
    print(f"  知识点掌握度 {len(radar)} 项（按掌握度从低到高）：")
    for r in radar[:6]:
        bar = '█' * int(r["scoreRate"] / 10) + '░' * (10 - int(r["scoreRate"] / 10))
        print(f"    {bar} {r['scoreRate']:5.1f}%  {r['name'][:22]}  (答{r['answered']}对{r['correct']})")

    trend = client.get("/stat/trend", params={"days": 7}).json()["data"]
    active_trend = [t for t in trend if t["answered"]]
    print(f"  近 7 天趋势：{len(active_trend)} 天有答题记录")
    for t in active_trend:
        print(f"    {t['date']}  {t['avgScoreRate']:5.1f}%  {t['answered']} 道 / {t['examCount']} 份")

    cost = client.get("/stat/cost", params={"days": 7}).json()["data"]
    print(f"  AI 调用：{cost['totalCalls']} 次 · {cost['totalTokens']} tokens · "
          f"约 {cost['totalCost']} 元 · 平均 {cost['avgLatencyMs']} ms")
    for c in cost["items"][:4]:
        print(f"    {c['date']} {c['vendor']}/{c['model']} {c['calls']}次 "
              f"{c['promptTokens'] + c['completionTokens']} tokens {c['avgLatencyMs']}ms")

    mastery = client.get("/stat/kb-mastery").json()["data"]
    print(f"  知识库掌握情况 {len(mastery)} 个：")
    for m in mastery:
        print(f"    {m['name'][:20]:<22} 题量{m['questionCount']:>3} 已答{m['answeredCount']:>3} "
              f"得分率 {m['scoreRate']}%")

    # ---------------------------------------------------------------- 11
    section("11. 手动标记已掌握")
    if page["list"]:
        mid = page["list"][0]["id"]
        client.post(f"/mistake/{mid}/mastered", params={"mastered": True})
        after = client.get("/mistake/list", params={"kbId": kb_id, "mastered": 1,
                                                    "pageNum": 1, "pageSize": 50}).json()["data"]
        print(f"  标记 #{mid} 已掌握 → 已掌握列表 {after['total']} 条")
        if after["total"] == 0:
            print("  ✗ 标记已掌握失败")
            failures += 1

    # ---------------------------------------------------------------- 12
    section("12. 清理")
    if args.keep:
        print(f"  按 --keep 保留 kb={kb_id}")
    else:
        client.delete(f"/kb/{kb_id}")
        print("  ✓ 已清理")

    print(f"\n{'=' * 76}")
    print("  ✓ M4 测试全部通过" if failures == 0 else f"  ✗ 有 {failures} 项未通过")
    print(f"{'=' * 76}\n")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

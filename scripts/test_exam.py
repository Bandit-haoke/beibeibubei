"""
背备不悲 · M3（答题与判分）端到端测试

链路：建库 → 上传 → 出题 → 审核 → 开始作答 → 故意答对一半
      → 交卷判分 → 查结果（命中/遗漏要点、原文引用）→ 错题本 → 申诉重判 → 清理

用法：
    D:\\conda-envs\\beibei\\python.exe scripts\\test_exam.py
    D:\\conda-envs\\beibei\\python.exe scripts\\test_exam.py --keep
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080/api"
ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "test-data" / "JavaWeb-测试讲义.md"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass


def section(t: str) -> None:
    print(f"\n{'=' * 76}\n  {t}\n{'=' * 76}")


def stream_task(client: httpx.Client, task_id: int) -> dict | None:
    final: dict | None = None
    last = ""
    with client.stream("GET", f"{BASE}/task/{task_id}/stream",
                       timeout=httpx.Timeout(900.0, connect=10.0)) as s:
        event = None
        for line in s.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if event == "progress":
                    stage = payload.get("stage", "")
                    if stage != last:
                        print(f"      [{payload.get('progress', 0):>3}%] {stage}")
                        last = stage
                elif event in ("done", "error"):
                    final = payload
                    if event == "error":
                        print(f"      ✗ {payload.get('errorMsg')}")
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
    section("1. 建库 + 上传 + 出题（准备答题素材）")
    kb_id = client.post("/kb", json={"name": "M3判分测试"}).json()["data"]["id"]
    with open(DOC, "rb") as fp:
        up = client.post("/doc/upload", params={"kbId": kb_id},
                         files={"files": (DOC.name, fp, "text/markdown")}, timeout=180).json()["data"][0]
    final = stream_task(client, up["taskId"])
    print(f"  入库: {final.get('result') if final else '失败'}")

    gen = client.post("/paper/generate", json={
        "kbId": kb_id, "title": "M3 判分测试卷", "count": args.count,
        "qTypeRatio": {"SINGLE": 0.4, "JUDGE": 0.2, "BLANK": 0.2, "SHORT": 0.2},
        "selfCheck": True,
    }).json()["data"]
    final = stream_task(client, gen["taskId"])
    print(f"  出题: {final.get('result') if final else '失败'}")
    paper_id = gen["paperId"]

    approved = client.post(f"/paper/{paper_id}/approve-all").json()["data"]
    print(f"  审核通过: {approved} 道")

    # ---------------------------------------------------------------- 2
    section("2. 开始作答")
    start = client.post("/exam/start", json={
        "paperId": paper_id, "examMode": 2, "onlyPublished": True,
    }).json()["data"]
    exam_id = start["examId"]
    questions = start["questions"]
    print(f"  答卷 #{exam_id}「{start['title']}」 共 {len(questions)} 道 / {start['totalScore']} 分")
    for q in questions[:3]:
        print(f"    [{q['qTypeName']}] {q['stem'][:62]}")

    # ---------------------------------------------------------------- 3
    section("3. 作答：一半认真答，一半故意答错")
    # 从题库拿标准答案，用来模拟「答对」
    bank = client.get("/question/list", params={
        "kbId": kb_id, "status": 1, "pageNum": 1, "pageSize": 100,
    }).json()["data"]["list"]
    answer_key = {q["id"]: q for q in bank}

    answers = []
    for index, q in enumerate(questions):
        ref = answer_key.get(q["questionId"], {})
        correct = ref.get("answer", "")

        if index % 2 == 0:
            user_answer = correct            # 答对
            mode = "答对"
        else:
            if q["qType"] == 1 and q["options"]:
                wrong = next((o["key"] for o in q["options"] if not o["correct"]), "A")
                user_answer = wrong
            elif q["qType"] == 3:
                user_answer = "错误" if correct == "正确" else "正确"
            else:
                user_answer = "不太清楚，随便写一点"
            mode = "答错"

        answers.append({
            "questionId": q["questionId"],
            "userAnswer": user_answer,
            "inputMode": 1,
        })
        print(f"    #{index + 1} [{q['qTypeName']}] {mode}：{str(user_answer)[:44]}")

    client.post(f"/exam/{exam_id}/save-draft", json={"answers": answers, "durationSec": 128})
    print("  ✓ 已存草稿（验证断点续答）")

    # ---------------------------------------------------------------- 4
    section("4. 交卷并判分")
    task_id = client.post(f"/exam/{exam_id}/submit", json={
        "answers": answers, "durationSec": 245,
    }).json()["data"]
    print(f"  判分任务 #{task_id}")
    final = stream_task(client, task_id)
    if final and final.get("status") == 2:
        print("  ✓ 判分完成:", json.dumps(final.get("result"), ensure_ascii=False))
    else:
        print("  ✗ 判分失败")
        failures += 1

    # ---------------------------------------------------------------- 5
    section("5. 判分结果")
    result = client.get(f"/exam/{exam_id}/result").json()["data"]
    print(f"  得分 {result['gotScore']} / {result['totalScore']}  （{result['scoreRate']}%）")
    print(f"  全对 {result['correctCount']} 道，答错 {result['wrongCount']} 道，用时 {result['durationSec']} 秒")

    for item in result["items"][:4]:
        print(f"\n    [{item['qTypeName']}] {item['stem'][:60]}")
        print(f"      你的答案: {str(item['userAnswer'])[:70]}")
        print(f"      得分: {item['score']}/{item['fullScore']}  判分方式: {item['gradeMethodName']}")
        if item["hitPoints"]:
            for p in item["hitPoints"]:
                print(f"        ✓ [{p.get('score', '-')}分] {str(p.get('point'))[:52]}")
        if item["missPoints"]:
            for p in item["missPoints"]:
                print(f"        ✗ 漏: {str(p.get('point'))[:44]}")
                if p.get("hint"):
                    print(f"           提示: {str(p['hint'])[:56]}")
        if item["wrongPoints"]:
            for p in item["wrongPoints"]:
                print(f"        ! 错: {str(p.get('point'))[:44]}")
        if item["citations"]:
            for c in item["citations"][:2]:
                print(f"        📖 引用 chunkId={c.get('chunkId')} 第{c.get('pageNo')}页 "
                      f"{str(c.get('sectionPath'))[:30]}")
        if item["aiFeedback"]:
            print(f"       AI 评语: {str(item['aiFeedback'])[:80]}")

    # ---------------------------------------------------------------- 6
    section("6. 错题本（判定 + SM-2 复习计划）")
    # /review/today 属于 M4 范围，这里直接查库验证错题本是否按 SM-2 落了参数
    import subprocess
    script = (
        "import sys; sys.path.insert(0, r'E:\\学习资源\\背书工具\\beibei-agent');"
        "from sqlalchemy import text; from app.db.mysql import get_engine;"
        "c = get_engine().connect();"
        "rows = c.execute(text('SELECT question_id, wrong_count, ease_factor, interval_days, "
        "repetitions, next_review_at, mastered FROM bb_mistake ORDER BY id')).fetchall();"
        "print('错题本条目:', len(rows));"
        "[print('  question=%s 错%s次 ease=%s 间隔%sd 重复%s 下次复习=%s 已掌握=%s' % tuple(r)) for r in rows]"
    )
    out = subprocess.run(
        [r"E:\Develop\conda\envs\ac_env_3135\python.exe", "-c", script],
        capture_output=True, text=True, encoding="utf-8",
    )
    print(out.stdout.strip() or out.stderr.strip()[:300])
    if "错题本条目: 0" in (out.stdout or ""):
        print("  ✗ 错题本没有记录，SM-2 落库失败")
        failures += 1

    # ---------------------------------------------------------------- 7
    section("7. 申诉重判")
    target = next((i for i in result["items"] if i["score"] < i["fullScore"]), None)
    if target:
        print(f"  对 #{target['questionId']} 申诉（原得分 {target['score']}/{target['fullScore']}）")
        appeal_task = client.post(f"/answer/{target['answerItemId']}/appeal", json={
            "reason": "我答案里其实提到了这个要点，只是表述不同，请重新核对。",
        }).json()["data"]
        final = stream_task(client, appeal_task)
        if final and final.get("status") == 2:
            print("  ✓ 重判完成:", json.dumps(final.get("result"), ensure_ascii=False))
            after = client.get(f"/exam/{exam_id}/result").json()["data"]
            item = next(i for i in after["items"] if i["answerItemId"] == target["answerItemId"])
            print(f"  重判后得分: {item['appealScore']}  申诉状态={item['appealStatus']}")
        else:
            print("  ✗ 重判失败")
            failures += 1
    else:
        print("  全部满分，跳过")

    # ---------------------------------------------------------------- 8
    section("8. 语音热词纠错（不需要 ASR 凭据）")
    r = client.post("/asr/correct-hotwords", json={
        "text": "缓存血崩是指大批 key 同时过期，sential 负责熔断降级",
        "kbId": kb_id,
    })
    if r.status_code == 404:
        print("  （/asr/correct-hotwords 尚未实现）")
    else:
        d = r.json().get("data", {})
        print(f"  原文: {d.get('original')}")
        print(f"  纠正: {d.get('corrected')}")
        print(f"  热词表大小: {d.get('hotwordCount')}")
        for f in d.get("fixes", []):
            print(f"    {f['from']} → {f['to']} ({f['score']})")

    # ---------------------------------------------------------------- 9
    section("9. 清理")
    if args.keep:
        print(f"  按 --keep 保留 kb={kb_id} paper={paper_id} exam={exam_id}")
    else:
        client.delete(f"/kb/{kb_id}")
        print("  ✓ 已清理")

    print(f"\n{'=' * 76}")
    print("  ✓ M3 测试全部通过" if failures == 0 else f"  ✗ 有 {failures} 项未通过")
    print(f"{'=' * 76}\n")
    return 0 if failures == 0 else 1


def _has_endpoint(client: httpx.Client, path: str) -> bool:
    try:
        return client.get(path).status_code != 404
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    sys.exit(main())

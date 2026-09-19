"""
背备不悲 · M2（AI 出题）端到端测试

链路：建库 → 上传讲义（Mock 模型会抽知识点树 + 分块打标）→ 按知识点出题
      → 查看审核视图 → 整卷通过 → 查题库 → 清理

用法：
    D:\\conda-envs\\beibei\\python.exe scripts\\test_generate.py
    D:\\conda-envs\\beibei\\python.exe scripts\\test_generate.py --keep
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
    print(f"\n{'=' * 74}\n  {t}\n{'=' * 74}")


def stream_task(client: httpx.Client, task_id: int, label: str = "") -> dict | None:
    """订阅 SSE 并打印进度，返回终态 payload。"""
    final: dict | None = None
    last = ""
    with client.stream("GET", f"{BASE}/task/{task_id}/stream",
                       timeout=httpx.Timeout(900.0, connect=10.0)) as stream:
        event = None
        for line in stream.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                if event == "progress":
                    stage = payload.get("stage", "")
                    if stage != last:
                        print(f"      [{payload.get('progress', 0):>3}%] {stage}")
                        last = stage
                elif event == "done":
                    final = payload
                elif event == "error":
                    final = payload
                    print(f"      ✗ {payload.get('errorMsg')}")
                event = None
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--count", type=int, default=12)
    args = parser.parse_args()

    client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(60.0, connect=10.0))
    failures = 0

    # ---------------------------------------------------------------- 1
    section("1. 环境自检")
    data = client.get("/sys/health").json()["data"]
    for c in data["agent"]["checks"]:
        mark = "✓" if c["ok"] else "!"
        print(f"    {mark} [{c['level']:<8}] {c['name']:<22} {c.get('detail') or c.get('error')}")

    # ---------------------------------------------------------------- 2
    section("2. 建库 + 上传讲义（Mock 模型会抽知识点并打标）")
    kb = client.post("/kb", json={"name": "M2出题测试", "description": "临时"}).json()["data"]
    kb_id = kb["id"]
    print(f"  知识库 #{kb_id}")

    with open(DOC, "rb") as fp:
        up = client.post("/doc/upload", params={"kbId": kb_id},
                         files={"files": (DOC.name, fp, "text/markdown")}, timeout=180).json()["data"][0]
    print(f"  docId={up['docId']} taskId={up['taskId']}")
    final = stream_task(client, up["taskId"])
    if final and final.get("status") == 2:
        print("  ✓ 入库完成:", json.dumps(final.get("result"), ensure_ascii=False))
    else:
        print("  ✗ 入库失败")
        failures += 1

    # ---------------------------------------------------------------- 3
    section("3. 知识点树（Mock 从标题路径还原）")
    tree = client.get("/tag/tree", params={"kbId": kb_id}).json()["data"]

    def count(nodes):
        return sum(1 + count(n.get("children") or []) for n in nodes)

    print(f"  共 {count(tree)} 个知识点")

    def show(nodes, indent=2):
        for n in nodes[:8]:
            print("  " + " " * indent + f"· {n['name']}  ({n['chunkCount']} 分块)")
            show(n.get("children") or [], indent + 3)

    show(tree)

    tag_ids = [n["id"] for n in tree][:2]
    print(f"  出题时限定知识点: {tag_ids}")

    # ---------------------------------------------------------------- 4
    section(f"4. AI 出题（{args.count} 道，Mock 模型）")
    gen = client.post("/paper/generate", json={
        "kbId": kb_id,
        "title": "M2 自动出题测试",
        "count": args.count,
        "tagIds": tag_ids,
        "includeChildTags": True,
        "qTypeRatio": {"SINGLE": 0.4, "JUDGE": 0.2, "BLANK": 0.2, "SHORT": 0.2},
        "difficultyRatio": {"EASY": 0.3, "MEDIUM": 0.5, "HARD": 0.2},
        "selfCheck": True,
    }).json()["data"]
    paper_id = gen["paperId"]
    print(f"  paperId={paper_id} taskId={gen['taskId']}")

    final = stream_task(client, gen["taskId"])
    if final and final.get("status") == 2:
        print("  ✓ 出题完成:", json.dumps(final.get("result"), ensure_ascii=False))
    else:
        print("  ✗ 出题失败:", final)
        failures += 1

    # ---------------------------------------------------------------- 5
    section("5. 审核视图（只显示待审草稿）")
    review = client.get(f"/paper/{paper_id}/review").json()["data"]
    paper_vo = review["paper"]
    print(f"  题卷「{paper_vo['title']}」 状态={paper_vo['status']} "
          f"共 {paper_vo['totalCount']} 道，待审 {paper_vo.get('draftCount', 0)} 道，"
          f"已发布 {paper_vo.get('publishedCount', 0)} 道")
    if paper_vo.get("genSummary"):
        print(f"  生成统计: {json.dumps(paper_vo['genSummary'], ensure_ascii=False)}")

    for q in review["questions"][:4]:
        print(f"\n    #{q['id']} [{q['qTypeName']}/{q['difficultyName']}] "
              f"质量分 {q['qualityScore']}  知识点 {[t['name'] for t in q['tags']]}")
        print(f"      题干: {q['stem'][:78]}")
        if q["options"]:
            for o in q["options"]:
                print(f"        {'✓' if o['correct'] else ' '} {o['key']}. {o['content'][:52]}")
        print(f"      答案: {str(q['answer'])[:70]}")
        if q.get("rubric"):
            for p in q["rubric"][:3]:
                print(f"        · [{p.get('score')}分] {str(p.get('point'))[:56]}")

    # ---------------------------------------------------------------- 6
    section("6. 整卷通过审核")
    approved = client.post(f"/paper/{paper_id}/approve-all").json()["data"]
    print(f"  ✓ 通过 {approved} 道")
    paper = client.get(f"/paper/{paper_id}").json()["data"]["paper"]
    print(f"  题卷状态={paper['status']} 待审={paper['draftCount']} 已发布={paper['publishedCount']}")

    # ---------------------------------------------------------------- 7
    section("7. 题库查询（只看已发布）")
    bank = client.get("/question/list", params={
        "kbId": kb_id, "status": 1, "pageNum": 1, "pageSize": 5,
    }).json()["data"]
    print(f"  已发布题目总数: {bank['total']}")
    for q in bank["list"][:3]:
        print(f"    #{q['id']} [{q['qTypeName']}] {q['stem'][:64]}")

    # 按知识点过滤
    if tag_ids:
        filtered = client.get("/question/list", params={
            "kbId": kb_id, "status": 1, "tagId": tag_ids[0], "pageNum": 1, "pageSize": 5,
        }).json()["data"]
        print(f"  按知识点 #{tag_ids[0]} 过滤: {filtered['total']} 道")

    # ---------------------------------------------------------------- 8
    section("8. 查重验证（同样条件再出一次，应大量被丢弃）")
    gen2 = client.post("/paper/generate", json={
        "kbId": kb_id, "title": "M2 查重测试", "count": args.count,
        "tagIds": tag_ids, "includeChildTags": True,
        "qTypeRatio": {"SINGLE": 0.4, "JUDGE": 0.2, "BLANK": 0.2, "SHORT": 0.2},
        "selfCheck": True,
    }).json()["data"]
    final2 = stream_task(client, gen2["taskId"])
    if final2 and final2.get("status") == 2:
        r = final2["result"]
        print(f"  第二次生成: 生成 {r.get('generated')} 道，"
              f"结构校验丢弃 {r.get('droppedByValidate')}，"
              f"自检丢弃 {r.get('droppedBySelfCheck')}，"
              f"查重丢弃 {r.get('droppedByDedup')}，最终保存 {r.get('saved')}")
    else:
        print("  ✗ 第二次生成失败")

    # ---------------------------------------------------------------- 9
    section("9. 清理")
    if args.keep:
        print(f"  按 --keep 保留知识库 #{kb_id}、题卷 #{paper_id} / #{gen2['paperId']}")
    else:
        for pid in (paper_id, gen2["paperId"]):
            client.delete(f"/paper/{pid}", params={"withQuestions": True})
        client.delete(f"/kb/{kb_id}")
        print("  ✓ 已清理")

    print(f"\n{'=' * 74}")
    print("  ✓ M2 测试全部通过" if failures == 0 else f"  ✗ 有 {failures} 项未通过")
    print(f"{'=' * 74}\n")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

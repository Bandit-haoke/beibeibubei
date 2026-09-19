"""
背备不悲 · 端到端冒烟测试

跑一遍 M0 + M1 的关键链路：
  健康检查 → 建知识库 → 上传文档 → 订阅 SSE 看解析进度 → 查分块 → 检索 → 清理

用法：
    D:\\conda-envs\\beibei\\python.exe scripts\\smoke_test.py
    D:\\conda-envs\\beibei\\python.exe scripts\\smoke_test.py --keep   # 保留测试数据
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080/api"
ROOT = Path(__file__).resolve().parent.parent
TEST_FILE = ROOT / "docs" / "test-data" / "JavaWeb-测试讲义.md"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass

PASS, FAIL, WARN = "✓", "✗", "!"


def ok(msg: str) -> None:
    print(f"  {PASS} {msg}")


def bad(msg: str) -> None:
    print(f"  {FAIL} {msg}")


def warn(msg: str) -> None:
    print(f"  {WARN} {msg}")


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="保留测试数据，不删除知识库")
    args = parser.parse_args()

    client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(60.0, connect=10.0))
    failures = 0

    # ---------------------------------------------------------------- 1
    section("1. 环境自检")
    try:
        body = client.get("/sys/health").json()
        data = body["data"]
        agent = data["agent"]
        print(f"  Java  : JDK {data['java']['version']} / PID {data['java']['pid']}")
        print(f"  智能体: coreOk={agent.get('coreOk')}")
        if agent.get("unreachable"):
            bad(f"智能体不可达：{agent.get('error')}")
            return 1
        for check in agent.get("checks", []):
            mark = PASS if check["ok"] else WARN
            text = check.get("detail") or check.get("error") or ""
            print(f"    {mark} [{check['level']:<8}] {check['name']:<22} {text}")
        if not agent.get("coreOk"):
            bad("核心链路不通，终止测试")
            return 1
        ok("核心链路正常")
    except Exception as exc:  # noqa: BLE001
        bad(f"调用失败：{exc}")
        return 1

    # ---------------------------------------------------------------- 2
    section("2. 创建知识库")
    kb_id = None
    try:
        resp = client.post("/kb", json={
            "name": "冒烟测试知识库",
            "description": "由 smoke_test.py 自动创建，测试完会删除",
            "coverColor": "#4C7CF3",
        }).json()
        if resp["code"] != 0:
            bad(f"创建失败：{resp['msg']}")
            failures += 1
        else:
            kb_id = resp["data"]["id"]
            ok(f"知识库 #{kb_id} {resp['data']['name']}")
            print(f"      向量模型   : {resp['data']['embeddingModel']}")
            print(f"      Milvus 集合: {resp['data']['milvusCollection']}")
    except Exception as exc:  # noqa: BLE001
        bad(f"异常：{exc}")
        return 1

    if kb_id is None:
        return 1

    # ---------------------------------------------------------------- 3
    section("3. 上传文档并订阅解析进度")
    doc_id = None
    try:
        if not TEST_FILE.exists():
            bad(f"测试文件不存在：{TEST_FILE}")
            return 1
        print(f"  文件：{TEST_FILE.name}（{TEST_FILE.stat().st_size / 1024:.1f} KB）")

        with open(TEST_FILE, "rb") as fp:
            resp = client.post(
                "/doc/upload",
                params={"kbId": kb_id},
                files={"files": (TEST_FILE.name, fp, "text/markdown")},
                timeout=120.0,
            ).json()

        if resp["code"] != 0:
            bad(f"上传失败：{resp['msg']}")
            return 1

        results = resp["data"]
        for r in results:
            print(f"      {r['fileName']} -> docId={r['docId']} taskId={r['taskId']} {r['message']}")
        task_ids = [r["taskId"] for r in results if r["taskId"]]
        doc_id = results[0]["docId"] if results else None

        if not task_ids:
            bad("没有拿到 taskId")
            failures += 1

        for task_id in task_ids:
            print(f"\n  --- 任务 #{task_id} 进度 ---")
            last_stage = ""
            final = None
            with httpx.stream("GET", f"{BASE}/task/{task_id}/stream",
                              timeout=httpx.Timeout(600.0, connect=10.0)) as stream:
                event = None
                for line in stream.iter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        if event == "progress":
                            stage = payload.get("stage", "")
                            if stage != last_stage:
                                print(f"      [{payload.get('progress', 0):>3}%] {stage}")
                                last_stage = stage
                        elif event == "done":
                            final = payload
                            print(f"      完成：{json.dumps(payload.get('result'), ensure_ascii=False)}")
                        elif event == "error":
                            final = payload
                            bad(f"失败：{payload.get('errorMsg')}")

            if final and final.get("status") == 2:
                ok(f"任务 #{task_id} 解析成功")
            else:
                warn(f"任务 #{task_id} 未成功完成（若提示缺少向量模型，属预期）")
                failures += 1

    except Exception as exc:  # noqa: BLE001
        bad(f"异常：{type(exc).__name__}: {exc}")
        failures += 1

    # ---------------------------------------------------------------- 4
    section("4. 查看分块")
    try:
        if doc_id:
            resp = client.get(f"/doc/{doc_id}/chunks", params={"pageNum": 1, "pageSize": 5}).json()
            if resp["code"] == 0:
                page = resp["data"]
                ok(f"分块总数 {page['total']}")
                for chunk in page["list"][:3]:
                    preview = chunk["content"][:70].replace("\n", " ")
                    tags = "、".join(t["name"] for t in chunk.get("tags", [])) or "无标签"
                    print(f"      #{chunk['chunkIndex']:>3} [{chunk['tokenCount']:>4} token] "
                          f"{chunk['sectionPath'][:26]:<26} | {tags}")
                    print(f"           {preview}...")
            else:
                bad(f"查询失败：{resp['msg']}")
                failures += 1
    except Exception as exc:  # noqa: BLE001
        bad(f"异常：{exc}")
        failures += 1

    # ---------------------------------------------------------------- 5
    section("5. 混合检索")
    try:
        resp = client.post("/search", json={
            "kbId": kb_id,
            "query": "Redis 缓存穿透和击穿有什么区别",
            "topK": 5,
        }).json()
        if resp["code"] != 0:
            bad(f"检索请求失败：{resp['msg']}")
            failures += 1
        else:
            payload = resp.get("data") or {}
            if payload.get("ok") is False:
                warn(f"检索不可用：{payload.get('error')}")
                if payload.get("hint"):
                    print(f"      提示：{payload['hint']}")
            else:
                hits = payload.get("hits") or []
                ok(f"召回 {len(hits)} 个分块（引擎：{payload.get('source')}）")
                for i, hit in enumerate(hits[:3], 1):
                    print(f"      {i}. score={hit['score']:.4f} "
                          f"{(hit.get('fileName') or '')[:20]} "
                          f"{(hit.get('sectionPath') or '')[:30]}")
                    print(f"         {hit['text'][:80]}...")
    except Exception as exc:  # noqa: BLE001
        bad(f"异常：{exc}")
        failures += 1

    # ---------------------------------------------------------------- 6
    section("6. 知识点")
    try:
        resp = client.get("/tag/tree", params={"kbId": kb_id}).json()
        if resp["code"] == 0:
            tree = resp["data"]
            total = _count_nodes(tree)
            if total:
                ok(f"知识点 {total} 个")
                for node in tree[:6]:
                    print(f"      {node['name']}  ({node['chunkCount']} 分块, "
                          f"{len(node.get('children') or [])} 子节点)")
            else:
                warn("还没有知识点（需要配置大模型 API Key 后才会自动抽取）")
        else:
            bad(f"查询失败：{resp['msg']}")
    except Exception as exc:  # noqa: BLE001
        bad(f"异常：{exc}")

    # ---------------------------------------------------------------- 7
    section("7. 清理")
    if args.keep:
        warn(f"按 --keep 保留知识库 #{kb_id}")
    else:
        try:
            resp = client.delete(f"/kb/{kb_id}").json()
            if resp["code"] == 0:
                ok(f"已删除知识库 #{kb_id}")
            else:
                bad(f"删除失败：{resp['msg']}")
        except Exception as exc:  # noqa: BLE001
            bad(f"异常：{exc}")

    print(f"\n{'=' * 72}")
    if failures == 0:
        print(f"  {PASS} 冒烟测试全部通过")
    else:
        print(f"  {FAIL} 有 {failures} 项未通过")
    print(f"{'=' * 72}\n")
    return 0 if failures == 0 else 1


def _count_nodes(nodes: list[dict]) -> int:
    return sum(1 + _count_nodes(n.get("children") or []) for n in nodes)


if __name__ == "__main__":
    sys.exit(main())

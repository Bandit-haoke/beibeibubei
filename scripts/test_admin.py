"""
背备不悲 · M5（AI 配置 + 导出 + 备份 + 一致性）端到端测试

覆盖：
  1. AI 厂商 CRUD、连通性测试、切换、任务路由
  2. Prompt 模板版本化编辑与回滚
  3. API Key AES 加密存储（Java 加密 → Python 解密）
  4. 题库导出 Anki / CSV / JSON
  5. 向量一致性校验与孤儿清理
  6. 数据备份

用法：
    D:\\conda-envs\\beibei\\python.exe scripts\\test_admin.py
    D:\\conda-envs\\beibei\\python.exe scripts\\test_admin.py --keep
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
PY = r"D:\conda-envs\beibei\python.exe"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass


def section(t: str) -> None:
    print(f"\n{'=' * 78}\n  {t}\n{'=' * 78}")


def sql(script: str) -> str:
    full = ("import sys\n"
            "sys.path.insert(0, r'E:\\学习资源\\背书工具\\beibei-agent')\n"
            "from sqlalchemy import text\n"
            "from app.db.mysql import get_engine\n"
            "c = get_engine().connect()\n"
            + script + "\nc.commit()\nc.close()\n")
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
                event = None
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--count", type=int, default=6)
    args = parser.parse_args()

    client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(60.0, connect=10.0))
    failures = 0

    # ================================================================ 1
    section("1. AI 厂商管理")
    providers = client.get("/ai/provider/list").json()["data"]
    print(f"  已有 {len(providers)} 个厂商：")
    for p in providers:
        print(f"    #{p['id']:<3} {p['name']:<22} {p['vendor']:<10} {p['capability']:<12} "
              f"启用={p['enabled']} 当前={p['isActive']} 锁定={p['locked']} "
              f"key={p['apiKeyMasked'] or '（空）'}")

    if any(p["hasApiKey"] and "****" in p["apiKeyMasked"] for p in providers):
        print("  ✓ API Key 以掩码形式返回，未泄露明文")
    else:
        print("  ! 没有已配置 Key 的厂商（还没填过，无法验证掩码）")

    # 新建一个「OpenAI 兼容」的自定义厂商，验证 CRUD
    created = client.post("/ai/provider", json={
        "name": "M5测试厂商", "vendor": "custom", "protocol": "openai-compatible",
        "baseUrl": "http://127.0.0.1:9999", "model": "test-model",
        "apiKey": "sk-test-1234567890abcdef", "capability": "CHAT",
        "enabled": 1, "priority": 500, "remark": "由 test_admin.py 创建",
        "extraParams": {"temperature": 0.5, "max_tokens": 2048, "price_in": 1.0, "price_out": 2.0},
    }).json()["data"]
    new_id = created["id"]
    print(f"\n  新建厂商 #{new_id}「{created['name']}」 key 显示为 {created['apiKeyMasked']}")
    if created["hasApiKey"] and "sk-tes" in created["apiKeyMasked"]:
        print("  ✓ 返回的是掩码而非明文")
    else:
        print("  ✗ 掩码不符合预期")
        failures += 1

    # 数据库里应该是密文
    out = sql(
        f"row = c.execute(text('SELECT api_key_enc FROM bb_ai_provider WHERE id = {new_id}')).fetchone()\n"
        "print('  数据库里存的:', repr(row[0]))"
    )
    print(out)
    if "sk-test" in out:
        print("  ✗ 数据库里是明文！加密没生效")
        failures += 1
    else:
        print("  ✓ 数据库里不是明文，AES 加密生效")

    # Python 侧能否解开
    out = sql(
        "import sys\n"
        "sys.path.insert(0, r'E:\\学习资源\\背书工具\\beibei-agent')\n"
        "from app.core.crypto import decrypt\n"
        "from app.config import get_settings\n"
        f"row = c.execute(text('SELECT api_key_enc FROM bb_ai_provider WHERE id = {new_id}')).fetchone()\n"
        "plain = decrypt(row[0], get_settings().secret_key)\n"
        "print('  Python 解密结果:', plain)"
    )
    print(out)
    if "sk-test-1234567890abcdef" in out:
        print("  ✓ Python 能解开 Java 加的密（两边密钥一致）")
    else:
        print("  ✗ Python 解不开，检查 SECRET_KEY 是否两边一致")
        failures += 1

    # 连通性测试（指向不存在的端口，应该优雅失败）
    test = client.post(f"/ai/provider/{new_id}/test").json()["data"]
    print(f"\n  连通性测试（故意指向不存在的端口）：ok={test['ok']}")
    print(f"    {test['message']}")
    if not test["ok"]:
        print("  ✓ 失败时给出了可读的原因，而不是抛 500")
    else:
        failures += 1

    # 修改（apiKey 留空表示不改动）
    updated = client.put(f"/ai/provider/{new_id}", json={
        "name": "M5测试厂商（改过名）", "remark": "改过备注",
    }).json()["data"]
    print(f"\n  改名后：{updated['name']}，Key 仍为 {updated['apiKeyMasked']}")
    if updated["hasApiKey"]:
        print("  ✓ apiKey 留空没有把原来的 Key 冲掉")
    else:
        print("  ✗ Key 被冲掉了")
        failures += 1

    # ================================================================ 2
    section("2. 任务路由")
    routes = client.get("/ai/route").json()["data"]
    for r in routes:
        print(f"    {r['taskName']:<14} {r['description'][:32]:<34} → "
              f"{r['providerName'] or '（跟随当前使用）'}")

    target = routes[0]
    client.put("/ai/route", json={
        "taskType": target["taskType"], "providerId": new_id,
        "fallbackProviderId": None, "remark": "M5 测试指向",
    })
    after = client.get("/ai/route").json()["data"]
    changed = next(r for r in after if r["taskType"] == target["taskType"])
    print(f"\n  把「{target['taskName']}」指向 #{new_id} → 现在指向：{changed['providerName']}")
    if changed["providerId"] == new_id:
        print("  ✓ 任务路由生效")
    else:
        print("  ✗ 任务路由没生效")
        failures += 1

    # ================================================================ 3
    section("3. Prompt 模板版本化")
    groups = client.get("/ai/prompt/list").json()["data"]
    print(f"  共 {len(groups)} 套模板：")
    for g in groups:
        print(f"    {g['name']:<20} v{g['activeVersion']:<3} 共 {g['versionCount']} 个版本  [{g['code']}]")

    group = groups[0]
    active = next(v for v in group["versions"] if v["isActive"] == 1)
    detail = client.get(f"/ai/prompt/{active['id']}").json()["data"]
    print(f"\n  编辑「{group['name']}」v{detail['version']}（{len(detail['content'])} 字）")

    new_content = detail["content"] + "\n\n【M5 测试追加】这是测试写入的内容。"
    saved = client.put(f"/ai/prompt/{active['id']}", json={
        "content": new_content, "remark": "M5 测试修改",
    }).json()["data"]
    print(f"  保存后生成 v{saved['version']}，isActive={saved['isActive']}")
    if saved["version"] == detail["version"] + 1:
        print("  ✓ 版本号递增")
    else:
        print("  ✗ 版本号没有递增")
        failures += 1

    versions = client.get(f"/ai/prompt/code/{group['code']}/versions").json()["data"]
    print(f"  该模板现有版本：{[v['version'] for v in versions]}")
    actives = [v for v in versions if v["isActive"] == 1]
    if len(actives) == 1:
        print("  ✓ 只有一个激活版本（新的激活，旧的自动停用）")
    else:
        print(f"  ✗ 有 {len(actives)} 个激活版本")
        failures += 1

    # 回滚到上一版
    old_version = next(v for v in versions if v["version"] == detail["version"])
    rolled = client.post(f"/ai/prompt/rollback/{old_version['id']}").json()["data"]
    print(f"\n  回滚到 v{old_version['version']} → 生成 v{rolled['version']}")
    if "M5 测试追加" not in rolled["content"]:
        print("  ✓ 回滚成功，内容回到旧版本")
    else:
        print("  ✗ 回滚后的内容仍带测试追加")
        failures += 1

    # ================================================================ 4
    section("4. 准备题库数据（用于导出与一致性校验）")
    kb_id = client.post("/kb", json={"name": "M5导出测试"}).json()["data"]["id"]
    with open(DOC, "rb") as fp:
        up = client.post("/doc/upload", params={"kbId": kb_id},
                         files={"files": (DOC.name, fp, "text/markdown")}, timeout=180).json()["data"][0]
    stream_task(client, up["taskId"])
    gen = client.post("/paper/generate", json={
        "kbId": kb_id, "title": "M5 导出测试卷", "count": args.count,
        "qTypeRatio": {"SINGLE": 0.4, "JUDGE": 0.2, "SHORT": 0.2, "BLANK": 0.2},
        "selfCheck": True,
    }).json()["data"]
    stream_task(client, gen["taskId"])
    approved = client.post(f"/paper/{gen['paperId']}/approve-all").json()["data"]
    print(f"  知识库 #{kb_id} · 通过审核 {approved} 道")

    # ================================================================ 5
    section("5. 题库导出")
    for fmt, label in (("anki", "Anki"), ("csv", "Excel/CSV"), ("json", "JSON")):
        r = client.get("/question/export", params={"kbId": kb_id, "status": 1, "format": fmt})
        body = r.content.decode("utf-8", "replace")
        disp = r.headers.get("content-disposition", "")
        print(f"\n  [{label}] HTTP {r.status_code} · {len(r.content)} 字节")
        print(f"    文件名头: {disp[:90]}")
        if fmt == "anki":
            print("    前 3 行:")
            for line in body.split("\n")[:3]:
                print(f"      {line[:110]}")
        elif fmt == "csv":
            print(f"    BOM 存在: {body.startswith(chr(0xFEFF))}")
            print("    表头:", body.lstrip("\ufeff").split("\n")[0][:100])
        else:
            data = json.loads(body)
            print(f"    导出 {data['count']} 道题，首题字段: {list(data['questions'][0].keys())[:8]}")
        if r.status_code != 200 or len(r.content) < 50:
            print("    ✗ 导出内容异常")
            failures += 1

    # ================================================================ 6
    section("6. 向量一致性校验")
    report = client.get("/sys/consistency").json()["data"]
    print(f"  MySQL 分块 {report.get('mysqlChunks')} · Milvus 向量 {report.get('milvusVectors')}")
    print(f"  孤儿向量 {report.get('orphanCount')} · 缺失向量 {report.get('missingCount')} · "
          f"分区错位 {report.get('misplacedCount', 0)}")
    print(f"  集合：{report.get('collection')}")
    if report.get("healthy"):
        print("  ✓ 数据一致")
    else:
        print(f"  ! 发现不一致：孤儿={report.get('orphanPks', [])[:5]} "
              f"缺失={report.get('missingPks', [])[:5]}")
        if report.get("partitionErrors"):
            print(f"    分区错误：{report['partitionErrors'][:2]}")
    if report.get("ok") and report.get("mysqlChunks", 0) > 0:
        print("  ✓ 校验接口工作正常")
    elif not report.get("ok"):
        print(f"  ✗ 校验失败：{report.get('error')}")
        failures += 1

    # 制造一条孤儿向量：删掉 MySQL 里的分块记录，保留 Milvus 向量
    out = sql(
        f"row = c.execute(text('SELECT id FROM bb_doc_chunk WHERE kb_id = {kb_id} ORDER BY id LIMIT 1')).fetchone()\n"
        f"c.execute(text('DELETE FROM bb_doc_chunk WHERE id = :i'), {{'i': row[0]}})\n"
        "print('  已删除分块 id=%s（Milvus 里还留着它的向量）' % row[0])"
    )
    print(out)

    report2 = client.get("/sys/consistency").json()["data"]
    print(f"  再查：孤儿向量 {report2.get('orphanCount')} 条 {report2.get('orphanPks', [])[:3]}")
    if report2.get("orphanCount", 0) >= 1:
        print("  ✓ 成功检测出孤儿向量")
        repair = client.post("/sys/consistency/repair").json()["data"]
        print(f"  清理结果：删除 {repair.get('deleted')} 条")
        if repair.get("after", {}).get("orphanCount") == 0:
            print("  ✓ 清理后孤儿向量归零")
        else:
            print("  ✗ 清理后仍有孤儿")
            failures += 1
    else:
        print("  ✗ 没能检测出刚制造的孤儿向量")
        failures += 1

    # ================================================================ 7
    section("7. 数据备份")
    bk = client.post("/sys/backup").json()["data"]
    print(f"  备份文件：{bk['filename']}")
    print(f"  {bk['tableCount']} 张表 / {bk['rowCount']} 行 / {bk['fileCount']} 个上传文件 / "
          f"{bk['sizeBytes'] / 1024:.1f} KB")
    if bk["rowCount"] > 0 and bk["sizeBytes"] > 1000:
        print("  ✓ 备份包含数据与文件")
    else:
        print("  ✗ 备份内容异常")
        failures += 1

    files = client.get("/sys/backup/list").json()["data"]
    print(f"  备份目录现有 {len(files)} 个文件")

    # 校验备份包内容
    out = sql(
        "import zipfile\n"
        f"z = zipfile.ZipFile(r'{bk['path']}')\n"
        "names = z.namelist()\n"
        "print('  包内条目数:', len(names))\n"
        "print('  含 manifest.json:', 'manifest.json' in names)\n"
        "print('  含 data.json:', 'data.json' in names)\n"
        "print('  含上传文件:', any(n.startswith('upload/') for n in names))\n"
        "import json as J\n"
        "d = J.loads(z.read('data.json'))\n"
        "print('  数据表:', len(d), '张；其中 bb_question', len(d.get('bb_question', [])), '行')"
    )
    print(out)
    if "含 data.json: True" not in out or "含上传文件: True" not in out:
        print("  ✗ 备份包内容不完整")
        failures += 1

    client.delete(f"/sys/backup/{bk['filename']}")
    print("  已删除测试备份")

    # ================================================================ 8
    section("8. 清理")
    client.delete(f"/ai/provider/{new_id}")
    client.put("/ai/route", json={
        "taskType": target["taskType"], "providerId": None,
        "fallbackProviderId": None, "remark": "",
    })
    print(f"  已删除测试厂商 #{new_id}，并把任务路由改回「跟随当前使用」")

    if args.keep:
        print(f"  按 --keep 保留知识库 #{kb_id}")
    else:
        client.delete(f"/kb/{kb_id}")
        print("  ✓ 已清理测试知识库")

    print(f"\n{'=' * 78}")
    print("  ✓ M5 测试全部通过" if failures == 0 else f"  ✗ 有 {failures} 项未通过")
    print(f"{'=' * 78}\n")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

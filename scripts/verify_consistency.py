"""一致性检测与修复的针对性验证：手工制造孤儿向量，看能否检测并清理干净。"""

import json
import subprocess
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8080/api"
PY = r"D:\conda-envs\beibei\python.exe"
DOC = Path(r"E:\学习资源\背书工具\docs\test-data\JavaWeb-测试讲义.md")

client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(60, connect=10))


def stream(task_id: int) -> dict | None:
    with client.stream("GET", f"{BASE}/task/{task_id}/stream",
                       timeout=httpx.Timeout(600, connect=10)) as s:
        event = None
        for line in s.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                if event in ("done", "error"):
                    return json.loads(line[5:].strip())
                event = None
    return None


def run_sql(kb_id: int) -> str:
    code = (
        "import sys\n"
        "sys.path.insert(0, r'E:\\学习资源\\背书工具\\beibei-agent')\n"
        "from sqlalchemy import text, bindparam\n"
        "from app.db.mysql import get_engine\n"
        "c = get_engine().connect()\n"
        "ids = [r[0] for r in c.execute(text('SELECT id FROM bb_doc_chunk "
        f"WHERE kb_id = {kb_id} ORDER BY id LIMIT 3')).fetchall()]\n"
        "c.execute(text('DELETE FROM bb_doc_chunk WHERE id IN :ids')"
        ".bindparams(bindparam('ids', expanding=True)), {'ids': ids})\n"
        "c.commit()\n"
        "c.close()\n"
        "print('已删除分块', ids)\n"
    )
    r = subprocess.run([PY, "-c", code], capture_output=True, text=True, encoding="utf-8")
    return (r.stdout or r.stderr or "").strip()


kb_id = client.post("/kb", json={"name": "一致性验证"}).json()["data"]["id"]
with open(DOC, "rb") as fp:
    up = client.post("/doc/upload", params={"kbId": kb_id},
                     files={"files": (DOC.name, fp, "text/markdown")}, timeout=180).json()["data"][0]
stream(up["taskId"])
print(f"已入库，知识库 #{kb_id}")

before = client.get("/sys/consistency").json()["data"]
print(f"初始状态：MySQL分块={before['mysqlChunks']} Milvus向量={before['milvusVectors']} "
      f"孤儿={before['orphanCount']} 缺失={before['missingCount']} 健康={before['healthy']}")

print(run_sql(kb_id))

after_break = client.get("/sys/consistency").json()["data"]
print(f"制造孤儿后：孤儿={after_break['orphanCount']} 缺失={after_break['missingCount']} "
      f"健康={after_break['healthy']}")

repair = client.post("/sys/consistency/repair").json()["data"]
print(f"执行清理：删除 {repair['deleted']} 条")
final = repair.get("after") or {}
print(f"清理后：孤儿={final.get('orphanCount')} 缺失={final.get('missingCount')} "
      f"健康={final.get('healthy')}")

recheck = client.get("/sys/consistency").json()["data"]
print(f"再次复查：孤儿={recheck['orphanCount']} 健康={recheck['healthy']}")

ok = (after_break["orphanCount"] == 3
      and repair["deleted"] == 3
      and final.get("orphanCount") == 0
      and recheck["orphanCount"] == 0)

print()
print("  ✓ 一致性检测与修复都正确" if ok else "  ✗ 仍有问题")

client.delete(f"/kb/{kb_id}")
print("  已清理测试知识库")
sys.exit(0 if ok else 1)

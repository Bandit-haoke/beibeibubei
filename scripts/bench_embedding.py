"""
向量化速度基准测试

测量 BGE-M3 在 CPU 上的真实吞吐，并对比「不排序分批」与「按长度排序分批」的差距。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\学习资源\背书工具\beibei-agent")
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text  # noqa: E402

from app.db.mysql import get_engine  # noqa: E402
from app.services.embedding import embedding_service  # noqa: E402

BATCH = 32
ROUND_CHARS = 1000


def load_texts() -> tuple[list[str], str]:
    """优先用库里真实的分块；没有就合成一段等价长度的中文。"""
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("SELECT content FROM bb_doc_chunk "
                     "WHERE CHAR_LENGTH(content) BETWEEN 400 AND 2400 LIMIT 128")
            ).fetchall()
        if len(rows) >= 32:
            return [r[0] for r in rows], f"数据库真实分块 {len(rows)} 条"
    except Exception as exc:  # noqa: BLE001
        print(f"  读取分块失败，改用合成文本：{exc}")

    unit = ("Redis 缓存穿透是指查询一个数据库和缓存中都不存在的数据，"
            "解决方案有两种，一是缓存空值并设置较短的过期时间，二是使用布隆过滤器提前拦截。"
            "缓存击穿是指某一个热点 key 在失效的瞬间，大量并发请求同时穿透到数据库。"
            "缓存雪崩是指大量 key 在同一时刻集中过期，或者 Redis 服务本身宕机。")
    texts = []
    while len(texts) < 128:
        texts.append((unit * 4)[:ROUND_CHARS])
    return texts, "合成文本（每条约 1000 字）"


def measure(texts: list[str], *, sort_by_len: bool, label: str) -> float:
    order = sorted(range(len(texts)), key=lambda i: len(texts[i])) if sort_by_len else list(range(len(texts)))
    total_chars = sum(len(texts[i]) for i in order)

    started = time.time()
    for start in range(0, len(order), BATCH):
        idx = order[start:start + BATCH]
        embedding_service.encode([texts[i] for i in idx], batch_size=len(idx))
    elapsed = time.time() - started

    print(f"  {label}")
    print(f"    {len(texts)} 条 / {total_chars} 字  用时 {elapsed:.1f}s")
    print(f"    → {total_chars / elapsed:,.0f} 字/秒    {len(texts) / elapsed:.2f} 条/秒")
    return total_chars / elapsed


def main() -> None:
    print("=" * 74)
    print("  BGE-M3 CPU 向量化速度基准")
    print("=" * 74)

    texts, source = load_texts()
    print(f"  文本来源：{source}")
    lengths = sorted(len(t) for t in texts)
    print(f"  长度分布：{lengths[0]} ~ {lengths[-1]} 字，平均 {sum(lengths)//len(lengths)} 字")
    print()

    # 预热：加载模型 + 第一次推理（含内存分配）
    print("  预热中（加载模型 + 首次推理）...")
    t0 = time.time()
    embedding_service.encode(["预热文本"], batch_size=1)
    print(f"  预热完成，用时 {time.time() - t0:.1f}s")
    print()

    unsorted_speed = measure(texts, sort_by_len=False, label="【旧】按原始顺序分批（当前用户遇到的行为）")
    print()
    sorted_speed = measure(texts, sort_by_len=True, label="【新】按长度排序后分批（已改的代码）")

    print()
    print("=" * 74)
    if unsorted_speed > 0:
        print(f"  排序分批带来的提升：{sorted_speed / unsorted_speed:.2f}x")
    print(f"  按新速度估算 226 个分块（221108 字）：约 {221108 / sorted_speed / 60:.1f} 分钟")
    print(f"  按旧速度估算 226 个分块（221108 字）：约 {221108 / max(unsorted_speed, 1) / 60:.1f} 分钟")
    print("=" * 74)


if __name__ == "__main__":
    main()

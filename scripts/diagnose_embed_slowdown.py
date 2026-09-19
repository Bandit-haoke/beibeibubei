"""
验证「PaddleOCR 加载后拖慢向量化」这个假设。

方法：
  1. 只加载向量模型，测一遍吞吐          → 基线
  2. 加载 PaddleOCR（模拟解析 PDF 时发生的事），再测一遍
  3. 限制 torch 线程数后再测一遍          → 看能否缓解
"""

import sys
import time

sys.path.insert(0, r"E:\学习资源\背书工具\beibei-agent")
sys.stdout.reconfigure(encoding="utf-8")

from app.services.embedding import embedding_service  # noqa: E402

UNIT = ("Redis 缓存穿透是指查询一个数据库和缓存中都不存在的数据，解决方案有两种，"
        "一是缓存空值并设置较短的过期时间，二是使用布隆过滤器提前拦截。"
        "缓存击穿是指某一个热点 key 在失效的瞬间，大量并发请求同时穿透到数据库。"
        "缓存雪崩是指大量 key 在同一时刻集中过期，或者 Redis 服务本身宕机。")

TEXTS = [(UNIT * 4)[:600]] * 64
TOTAL_CHARS = sum(len(t) for t in TEXTS)


def measure(label: str, *, batch: int = 32) -> float:
    started = time.time()
    for start in range(0, len(TEXTS), batch):
        chunk = TEXTS[start:start + batch]
        embedding_service.encode(chunk, batch_size=len(chunk))
    elapsed = time.time() - started
    speed = TOTAL_CHARS / elapsed
    print(f"  {label}")
    print(f"    {len(TEXTS)} 条 / {TOTAL_CHARS} 字   用时 {elapsed:6.1f}s   →  {speed:8,.0f} 字/秒")
    return speed


print("=" * 76)
print("  PaddleOCR 是否拖慢向量化 —— 对照实验")
print("=" * 76)

print("\n[0] 预热（加载 BGE-M3）...")
t0 = time.time()
embedding_service.encode(["预热"], batch_size=1)
print(f"    完成，用时 {time.time() - t0:.1f}s")

import torch  # noqa: E402

print(f"\n    torch 默认线程数: {torch.get_num_threads()}")

print()
base = measure("[1] 基线：只加载了向量模型")

print("\n[2] 现在加载 PaddleOCR（模拟解析 PDF 时的状态）...")
t0 = time.time()
try:
    from app.services.parsing import _get_ocr

    _get_ocr()
    print(f"    完成，用时 {time.time() - t0:.1f}s")
    ocr_loaded = True
except Exception as exc:  # noqa: BLE001
    print(f"    加载失败：{type(exc).__name__}: {exc}")
    ocr_loaded = False

after_ocr = measure("[3] 加载 PaddleOCR 之后") if ocr_loaded else 0.0

print()
print("[4] 把 torch 线程数从 %d 限制到 8，再测" % torch.get_num_threads())
torch.set_num_threads(8)
limited = measure("[5] torch 线程数 = 8")

print()
print("=" * 76)
if ocr_loaded and base > 0:
    print(f"  PaddleOCR 的影响：{after_ocr / base:.2f}x   （1.00 表示无影响）")
if after_ocr > 0:
    print(f"  限制线程数的影响：{limited / after_ocr:.2f}x")
print()
print(f"  结论：")
if ocr_loaded and after_ocr < base * 0.6:
    print(f"    ✓ 假设成立 —— PaddleOCR 加载后向量化慢了 {base / after_ocr:.1f} 倍")
    if limited > after_ocr * 1.3:
        print(f"    限制 torch 线程数能救回来 {limited / after_ocr:.1f} 倍")
else:
    print(f"    ✗ 假设不成立 —— PaddleOCR 不是主因，得另找原因")
print("=" * 76)

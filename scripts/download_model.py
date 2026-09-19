"""
背备不悲 · 模型权重下载器（从 ModelScope）

为什么不用 modelscope SDK / huggingface-cli：
  1. 不额外装包（ModelScope 在国内实测 13 MB/s，hf-mirror 反而慢）
  2. 能精确跳过不需要的大文件 —— BGE-M3 仓库里的 onnx/model.onnx_data 其实是
     另一份 2.1 GB 的权重，纯 PyTorch 推理用不到，默认不下，省一半空间和时间

用法：
    D:\\conda-envs\\beibei\\python.exe scripts\\download_model.py
    D:\\conda-envs\\beibei\\python.exe scripts\\download_model.py --model BAAI/bge-m3 --dest D:\\ai-models\\bge-m3
    D:\\conda-envs\\beibei\\python.exe scripts\\download_model.py --with-onnx    # 需要 ONNX 时
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

API = "https://modelscope.cn/api/v1/models/{model}/repo/files"
RAW = "https://modelscope.cn/models/{model}/resolve/master/{path}"

# 这些目录/文件对本项目的纯 PyTorch 推理没用，默认跳过
SKIP_PREFIXES = ("onnx/", "imgs/", ".git")
SKIP_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".md")
# colbert 头用来做多向量检索，我们只用稠密向量，2 MB 而已下了也无妨
KEEP_ALWAYS = ("config.json", "modules.json", "tokenizer.json",
               "tokenizer_config.json", "special_tokens_map.json",
               "sentence_bert_config.json", "config_sentence_transformers.json",
               "sentencepiece.bpe.model", "pytorch_model.bin", "model.safetensors")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def list_files(client: httpx.Client, model: str) -> list[dict]:
    resp = client.get(API.format(model=model), params={"Revision": "master", "Recursive": "true"})
    resp.raise_for_status()
    payload = resp.json()
    files = payload.get("Data", {}).get("Files", [])
    return [f for f in files if f.get("Type") == "blob"]


def should_skip(path: str, *, with_onnx: bool) -> bool:
    if not with_onnx and path.startswith("onnx/"):
        return True
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return True
    return any(path.lower().endswith(s) for s in SKIP_SUFFIXES)


def download(client: httpx.Client, model: str, path: str, dest: Path) -> tuple[bool, int]:
    target = dest / path
    target.parent.mkdir(parents=True, exist_ok=True)
    url = RAW.format(model=model, path=path)

    # 已存在且非空就跳过（支持断点续传式的重复执行）
    if target.exists() and target.stat().st_size > 0:
        return False, target.stat().st_size

    tmp = target.with_suffix(target.suffix + ".part")
    downloaded = 0
    started = time.time()
    last_print = 0.0

    with client.stream("GET", url, timeout=httpx.Timeout(300.0, connect=20.0)) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        with open(tmp, "wb") as fp:
            for chunk in resp.iter_bytes(chunk_size=1024 * 512):
                fp.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_print > 1.5:
                    speed = downloaded / max(now - started, 0.001)
                    pct = f"{downloaded / total * 100:5.1f}%" if total else "  ?  "
                    print(f"      {pct}  {human(downloaded)} / {human(total)}  "
                          f"{human(speed)}/s", flush=True)
                    last_print = now

    tmp.replace(target)
    elapsed = time.time() - started
    speed = downloaded / max(elapsed, 0.001)
    print(f"      ✓ 完成 {human(downloaded)}，用时 {elapsed:.0f}s（{human(speed)}/s）", flush=True)
    return True, downloaded


def main() -> int:
    parser = argparse.ArgumentParser(description="从 ModelScope 下载模型权重")
    parser.add_argument("--model", default="BAAI/bge-m3")
    parser.add_argument("--dest", default=r"D:\ai-models\bge-m3")
    parser.add_argument("--with-onnx", action="store_true", help="同时下载 ONNX 权重（多 2.1 GB）")
    args = parser.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(f"  背备不悲 · 模型下载")
    print("=" * 72)
    print(f"  模型: {args.model}")
    print(f"  目标: {dest}")
    print("=" * 72)

    with httpx.Client(follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        try:
            files = list_files(client, args.model)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ 获取文件清单失败：{type(exc).__name__}: {exc}")
            return 1

        todo = [f for f in files if not should_skip(f["Path"], with_onnx=args.with_onnx)]
        skipped = [f for f in files if should_skip(f["Path"], with_onnx=args.with_onnx)]
        todo.sort(key=lambda f: f.get("Size", 0), reverse=True)

        total_bytes = sum(f.get("Size", 0) for f in todo)
        print(f"\n  需要下载 {len(todo)} 个文件，共 {human(total_bytes)}")
        print(f"  跳过 {len(skipped)} 个文件"
              f"（onnx 权重 / 示例图片），省下 {human(sum(f.get('Size', 0) for f in skipped))}\n")

        started = time.time()
        got = 0
        for index, item in enumerate(todo, 1):
            path = item["Path"]
            size = item.get("Size", 0)
            print(f"  [{index}/{len(todo)}] {path}  ({human(size)})", flush=True)
            try:
                _, n = download(client, args.model, path, dest)
                got += n or size
            except Exception as exc:  # noqa: BLE001
                print(f"      ✗ 失败：{type(exc).__name__}: {exc}")
                return 1

    elapsed = time.time() - started
    print("\n" + "=" * 72)
    print(f"  ✓ 下载完成，用时 {elapsed:.0f}s")
    print(f"  模型目录: {dest}")
    print("=" * 72)
    print("\n  下一步：把 beibei-agent/.env 里的")
    print(f"    EMBEDDING_MODEL={args.model}")
    print(f"  改成")
    print(f"    EMBEDDING_MODEL={dest}")
    print("  然后重启 beibei-agent 即可（本地路径不需要联网）。\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

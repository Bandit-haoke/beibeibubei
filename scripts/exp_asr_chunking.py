"""
对照实验：长录音「整段发」vs「切段发」

目的：确认「语音不可用」的根因到底是不是讯飞单会话 60 秒上限。
      如果整段发会失败、切段发成功，那切段就是真正的解药，而不是掩盖问题。

用法：python scripts/exp_asr_chunking.py [秒数]
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "beibei-agent"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import get_settings  # noqa: E402
from app.services.asr import (  # noqa: E402
    AsrUnavailable,
    IAT_SAMPLE_RATE,
    _split_pcm,
    _xfyun_iat,
    resolve_xfyun_credentials,
    transcode_to_pcm16k,
)
from repro_asr_long import synth  # noqa: E402


async def try_once(pcm: bytes, cred) -> tuple[bool, float, str]:
    started = time.time()
    try:
        text = await _xfyun_iat(pcm, credentials=cred, language="zh_cn", domain="iat")
        return True, time.time() - started, text
    except AsrUnavailable as exc:
        return False, time.time() - started, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, time.time() - started, f"{type(exc).__name__}: {exc}"


def show(label: str, ok: bool, secs: float, text: str) -> None:
    mark = "✅" if ok else "❌"
    print(f"  {mark} {label}")
    print(f"     耗时 {secs:.1f}s")
    print(f"     {'识别' if ok else '失败'}：{text[:150]}")


async def main() -> int:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 52
    settings = get_settings()
    cred = resolve_xfyun_credentials()
    if not cred.complete:
        print("没有可用凭据，先配置讯飞三元组")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="beibei_exp_"))
    wav = tmp / "clip.wav"
    print(f"合成 {seconds} 秒语音 ...")
    synth(seconds, wav, settings.ffmpeg_path)
    pcm = transcode_to_pcm16k(wav.read_bytes(), suffix=".wav")
    audio_secs = len(pcm) / 2 / IAT_SAMPLE_RATE
    print(f"  PCM {len(pcm)} 字节，{audio_secs:.1f} 秒\n")

    print("=" * 74)
    print("  A. 整段发（不切）—— 这就是原来的行为")
    print("=" * 74)
    ok_a, secs_a, text_a = await try_once(pcm, cred)
    show("整段", ok_a, secs_a, text_a)

    print()
    print("=" * 74)
    print("  B. 切段发 —— 现在的行为")
    print("=" * 74)
    chunks = _split_pcm(pcm)
    print(f"  切成 {len(chunks)} 段：" +
          "、".join(f"{len(c) / 2 / IAT_SAMPLE_RATE:.1f}s" for c in chunks))
    started = time.time()
    parts, all_ok = [], True
    for i, seg in enumerate(chunks, 1):
        ok, secs, text = await try_once(seg, cred)
        print(f"     第 {i}/{len(chunks)} 段 {len(seg) / 2 / IAT_SAMPLE_RATE:.1f}s → "
              f"{'OK' if ok else 'FAIL'} {secs:.1f}s")
        if ok:
            parts.append(text)
        else:
            all_ok = False
            print(f"        {text[:120]}")
    show("切段合计", all_ok, time.time() - started, "".join(parts))

    print()
    print("=" * 74)
    print("  结论")
    print("=" * 74)
    if not ok_a and all_ok:
        print("  ✅ 整段会失败、切段成功 —— 证实「单会话 60 秒上限」就是根因，切段是真解药")
    elif ok_a and all_ok:
        print("  ⚠️ 两种都能成功 —— 说明这次的时长还没触到上限。")
        print("     切段仍然是必要的保险（用户录音可以到 60 秒，整段会顶到上限），")
        print("     但上一次的失败可能另有原因，请把失败时间点告诉开发者查日志。")
    elif ok_a and not all_ok:
        print("  ❗ 整段成功、切段反而失败 —— 切段引入了新问题，需要复查切点逻辑")
    else:
        print("  ❗ 两种都失败 —— 不是时长问题，看上面的错误码定位")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

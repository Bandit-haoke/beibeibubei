"""
复现「长录音导致语音不可用」

背景：讯飞语音听写单次会话上限 60 秒，而我们是按 40ms 一帧**实时**上传的，
所以一段 N 秒的录音要花 N 秒以上才发得完，接近 60 秒就会撞上限。

用法：python scripts/repro_asr_long.py [秒数]
"""

from __future__ import annotations

import asyncio
import base64
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "beibei-agent"))

import requests  # noqa: E402

from app.config import get_settings  # noqa: E402

AGENT = "http://127.0.0.1:8000"

# 反复读，凑够时长
SENTENCE = (
    "缓存穿透可以用布隆过滤器解决。缓存击穿用互斥锁重建。"
    "缓存雪崩就给过期时间加随机值。Redis 分布式锁要设置过期时间。"
    "MySQL 联合索引要遵守最左前缀原则。Spring Boot 的自动装配靠条件注解。"
)


def synth(seconds: int, out: Path, ffmpeg: str) -> None:
    """
    用系统 TTS 合成中文语音，再用 ffmpeg **裁到精确的秒数**。

    为什么要裁：SAPI 的语速不固定，按字数估算时长会差一倍
    （第一次写这个脚本时就估成了 99 秒，而我要的是 52 秒），
    只有裁过之后才能说「我测的确实是 52 秒」。
    """
    # 多合成一些，再裁掉多余的；按每秒约 4.2 字估（中文 TTS 默认语速实测值）
    text = (SENTENCE * 40)[: int(seconds * 4.2) + 40]
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    raw = out.with_name("raw.wav")
    script = f"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$text=[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}'))
$s=New-Object System.Speech.Synthesis.SpeechSynthesizer
$zh=$s.GetInstalledVoices()|Where-Object{{$_.VoiceInfo.Culture.Name -like 'zh-*'}}|Select-Object -First 1
if(-not $zh){{Write-Output 'NO_ZH';exit 3}}
$s.SelectVoice($zh.VoiceInfo.Name); $s.Rate=0
$s.SetOutputToWaveFile('{raw}'); $s.Speak($text); $s.SetOutputToNull(); $s.Dispose()
"""
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   capture_output=True, timeout=300, check=True)

    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(raw), "-t", str(seconds), str(out)],
                   capture_output=True, timeout=120, check=True)
    raw.unlink(missing_ok=True)


def duration_of(path: Path, ffmpeg: str) -> float:
    """用 ffmpeg 读出 wav 的真实时长。"""
    proc = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True)
    m = __import__("re").search(r"Duration: (\d+):(\d+):([\d.]+)", proc.stderr)
    if not m:
        return -1.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def main() -> int:
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 52
    settings = get_settings()
    tmp = Path(tempfile.mkdtemp(prefix="beibei_asr_long_"))
    wav = tmp / "long.wav"

    print(f"合成 {seconds} 秒的中文语音 ...")
    synth(seconds, wav, settings.ffmpeg_path)
    actual = duration_of(wav, settings.ffmpeg_path)
    print(f"  实际时长 {actual:.1f} 秒，{wav.stat().st_size} 字节")

    print("提交到 /api/v1/asr（直连 Python）...")
    started = time.time()
    with open(wav, "rb") as fh:
        resp = requests.post(
            f"{AGENT}/api/v1/asr",
            files={"audio": (wav.name, fh, "audio/wav")},
            data={"applyHotwords": "false"},
            headers={"X-Internal-Token": settings.internal_token},
            timeout=600,
        )
    elapsed = time.time() - started

    print(f"  HTTP {resp.status_code}   耗时 {elapsed:.1f}s")
    print()
    if resp.status_code == 200:
        body = resp.json()
        print(f"  识别成功：时长 {body.get('durationMs')} ms")
        print(f"  文本：{(body.get('text') or '')[:120]}")
        return 0

    print("  ❌ 失败，详细原因：")
    print("  " + resp.text[:800])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

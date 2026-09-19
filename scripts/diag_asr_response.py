"""
排查「录完音解析后什么都不显示」

做法：用系统 TTS 合成一段含专有名词的语音，分别用
    kbId=19 + 热词纠错   （面试室的实际参数）
    kbId=19 不带热词
    kbId=0  不带热词
打同一条 Java 网关接口，把**后端返回的完整 JSON** 打出来。
这样就能区分「后端返回空文本」和「前端没渲染」。

用法：python scripts/diag_asr_response.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "beibei-agent"))
sys.path.insert(0, str(ROOT / "scripts"))

import requests  # noqa: E402

from app.config import get_settings  # noqa: E402

JAVA = "http://127.0.0.1:8080"


def main() -> int:
    settings = get_settings()
    tmp = Path(tempfile.mkdtemp(prefix="beibei_diag_"))
    wav = tmp / "speech.wav"

    # 借 test_asr 的合成函数（已经踩过引号的坑，别重写）
    import importlib.util
    spec = importlib.util.spec_from_file_location("t", ROOT / "scripts" / "test_asr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sentence = ("缓存穿透可以用布隆过滤器解决，缓存击穿用互斥锁重建，"
                "Redis 分布式锁要设置过期时间，MySQL 联合索引要遵守最左前缀原则")
    print("合成测试语音 ...")
    if not mod.synthesize(sentence, wav):
        return 2
    print(f"  {wav.stat().st_size} 字节\n")

    scenarios = [
        ("面试室实际参数", {"kbId": "19", "applyHotwords": "true"}),
        ("kbId=19 关热词", {"kbId": "19", "applyHotwords": "false"}),
        ("kbId=0 关热词", {"kbId": "0", "applyHotwords": "false"}),
    ]

    for label, data in scenarios:
        with open(wav, "rb") as fh:
            resp = requests.post(f"{JAVA}/api/asr/transcribe",
                                 files={"audio": ("speech.wav", fh, "audio/wav")},
                                 data=data, timeout=300)
        print("=" * 74)
        print(f"  {label}   HTTP {resp.status_code}   {data}")
        print("=" * 74)
        try:
            body = resp.json()
        except Exception:
            print("  （响应不是 JSON）", resp.text[:300])
            continue

        print(f"  code = {body.get('code')}")
        if body.get("code") != 0:
            print(f"  msg  = {str(body.get('msg'))[:200]}")
        payload = body.get("data") or {}
        text = payload.get("text")
        print(f"  text      = {text!r}")
        print(f"  rawText   = {(payload.get('rawText') or '')[:90]!r}")
        print(f"  fixes     = {json.dumps(payload.get('hotwordFixes'), ensure_ascii=False)}")
        print(f"  长度      = text {len(text or '')} 字 / raw {len(payload.get('rawText') or '')} 字")
        print(f"  hotwordCount={payload.get('hotwordCount')} chunkCount={payload.get('chunkCount')}")
        print()

    print("判读方法：")
    print("  text 非空  → 后端没问题，是前端没渲染（看 VoiceInput 的 emit 与父组件）")
    print("  text 为空  → 后端把文本弄丢了（看 correct_hotwords / _join_words）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

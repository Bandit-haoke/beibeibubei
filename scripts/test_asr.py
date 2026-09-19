"""
背备不悲 · 语音转文字（讯飞）真机往返测试

为什么需要这个脚本：
    ASR 这段代码写完了、热词纠错也验证过，但**从来没做过一次真实的
    「录音 → 识别」往返**（一直没有讯飞凭据）。
    没有往返测试，就没法知道请求帧、采样率、动态修正解析到底对不对。

怎么在不用麦克风的情况下测：
    用 Windows 内置的中文语音合成（Microsoft Huihui）把一句已知的话
    合成成 WAV，再喂进 ASR 链路，最后拿识别结果和原句比对。
    这样「说什么」是已知的，识别对不对一眼就能看出来。

用法：
    python scripts/test_asr.py                 # 走 Java 网关（浏览器实际路径）
    python scripts/test_asr.py --direct        # 直连 Python 8000，隔离 ASR 本身
    python scripts/test_asr.py --audio x.wav   # 用自己录的音频（推荐偶尔用真人录音校准）
    python scripts/test_asr.py --say "自定义测试句子"

返回码：0 通过 / 1 识别内容不对 / 2 环境没准备好（没凭据、服务没起）
"""

from __future__ import annotations

import argparse
import base64
import difflib
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "beibei-agent"))

from app.config import get_settings  # noqa: E402

JAVA = "http://127.0.0.1:8080"
AGENT = "http://127.0.0.1:8000"

# 默认测试句：刻意包含多个「专有名词 + 容易听错」的技术术语，
# 顺便把热词纠错也一起测了
DEFAULT_SENTENCE = "缓存穿透可以用布隆过滤器解决，缓存击穿用互斥锁重建，缓存雪崩就给过期时间加随机值"

# 比对时重点看这些词有没有识别出来
KEY_TERMS = ["缓存穿透", "布隆过滤器", "缓存击穿", "互斥锁", "缓存雪崩", "过期时间", "随机"]

# ---------------------------------------------------------------------------
#  热词纠错回归用例
#
#  这几条全部来自**真机实测抓到的 bug**，不需要 ASR 凭据就能跑，所以放在最前面。
#  最要命的一条是第 1 条：讯飞明明把「缓存击穿」识别对了，
#  后处理却把它改成了「缓存穿透」—— 两者只差一个字，
#  而「穿透 / 击穿 / 雪崩」是三个完全不同的概念，改错比不改更糟。
# ---------------------------------------------------------------------------
HOTWORD_CASES: list[tuple[str, str, str]] = [
    ("已经正确·不许改（真机抓到的 bug）",
     "缓存穿透可以用布隆过滤器解决缓存击穿用互斥锁重建，缓存雪崩就给过期时间加随机值。",
     "缓存穿透可以用布隆过滤器解决缓存击穿用互斥锁重建，缓存雪崩就给过期时间加随机值。"),
    ("听错·激→击（要纠成击穿，不能纠成穿透）",
     "缓存激穿用互斥锁重建", "缓存击穿用互斥锁重建"),
    ("听错·起→器", "布隆过滤起解决穿透", "布隆过滤器解决穿透"),
    ("听错·两处", "缓存穿斗加分布式琐", "缓存穿透加分布式锁"),
    ("三个术语并存·一个都不该动",
     "缓存穿透、缓存击穿、缓存雪崩、布隆过滤器", None),
    ("无关文本·不许动", "今天天气不错适合学习", "今天天气不错适合学习"),
]


def run_hotword_regression() -> bool:
    from app.services.asr import correct_hotwords

    hotwords = ["缓存穿透", "缓存击穿", "缓存雪崩", "布隆过滤器", "分布式锁", "Redis",
                "自动装配", "事务隔离级别", "聚簇索引", "回表", "主从复制"]

    print("[-] 热词纠错回归（不需要凭据）")
    all_ok = True
    for desc, src, expect in HOTWORD_CASES:
        got, fixes = correct_hotwords(src, hotwords)
        want = expect if expect is not None else src
        ok = got == want
        all_ok = all_ok and ok
        line = f"  [{'OK ' if ok else 'FAIL'}] {desc}"
        if fixes and ok:
            line += "  →  " + "、".join(f"{f['from']}→{f['to']}" for f in fixes)
        print(line)
        if not ok:
            print(f"        期望: {want}")
            print(f"        实际: {got}")
    print()
    return all_ok


def normalize(text: str) -> str:
    """去掉标点和空白，只留汉字与字母数字，避免标点差异影响相似度。"""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text or "")


def synthesize(text: str, out_path: Path) -> bool:
    """
    用 Windows SAPI 中文语音把 text 合成成 WAV。

    返回 False 表示这台机器没有中文语音包或 SAPI 不可用，
    调用方应改用 --audio 传真人录音。
    """
    # 用 base64 把文本传进 PowerShell，彻底避开三层引号转义
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}'))
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$zh = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'zh-*' }} | Select-Object -First 1
if (-not $zh) {{ Write-Output 'NO_ZH_VOICE'; exit 3 }}
$s.SelectVoice($zh.VoiceInfo.Name)
$s.Rate = 0
$s.SetOutputToWaveFile('{out_path}')
$s.Speak($text)
$s.SetOutputToNull()
$s.Dispose()
Write-Output ('VOICE=' + $zh.VoiceInfo.Name)
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 调用 PowerShell 失败：{type(exc).__name__}: {exc}")
        return False

    out = proc.stdout.decode("utf-8", "replace").strip()
    err = proc.stderr.decode("utf-8", "replace").strip()
    if "NO_ZH_VOICE" in out or proc.returncode == 3:
        print("  ✗ 系统里没有中文语音包（需要一个 Microsoft Huihui 之类的 zh-CN 语音）")
        return False
    if proc.returncode != 0 or not out_path.exists():
        print(f"  ✗ 语音合成失败（exit={proc.returncode}）：{err[:300]}")
        return False
    print(f"  ✓ 合成完成：{out_path.stat().st_size} 字节，语音={out.split('=', 1)[-1]}")
    return True


def call_java_gateway(wav: Path, kb_id: int | None, apply_hotwords: bool) -> dict:
    with open(wav, "rb") as fh:
        resp = requests.post(
            f"{JAVA}/api/asr/transcribe",
            files={"audio": (wav.name, fh, "audio/wav")},
            data={"applyHotwords": str(apply_hotwords).lower(),
                  **({"kbId": str(kb_id)} if kb_id else {})},
            timeout=180,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"网关 HTTP {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    if body.get("code") == 5032:
        raise RuntimeError(f"ASR 不可用：{body.get('msg')}")
    if body.get("code") != 0:
        raise RuntimeError(f"网关业务失败 code={body.get('code')}：{body.get('msg')}")
    return body.get("data") or {}


def call_python_direct(wav: Path, kb_id: int | None, apply_hotwords: bool) -> dict:
    with open(wav, "rb") as fh:
        resp = requests.post(
            f"{AGENT}/api/v1/asr",
            files={"audio": (wav.name, fh, "audio/wav")},
            data={"applyHotwords": str(apply_hotwords).lower(),
                  **({"kbId": str(kb_id)} if kb_id else {})},
            headers={"X-Internal-Token": get_settings().internal_token},
            timeout=180,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"智能体 HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=str, default="", help="用指定音频文件，跳过 TTS 合成")
    parser.add_argument("--say", type=str, default=DEFAULT_SENTENCE, help="要合成的测试句子")
    parser.add_argument("--kb", type=int, default=0, help="用哪个知识库的热词表，0=不用")
    parser.add_argument("--direct", action="store_true", help="直连 Python 8000，不走 Java 网关")
    parser.add_argument("--no-hotwords", action="store_true", help="关闭热词纠错，看原始识别结果")
    parser.add_argument("--only-hotwords", action="store_true",
                        help="只跑热词纠错回归（不需要凭据，可放进 CI）")
    args = parser.parse_args()

    settings = get_settings()
    print("=" * 78)
    print("  背备不悲 · 讯飞语音听写 真机往返测试")
    print("=" * 78)
    print()

    # ---------- 0. 热词纠错回归（无凭据也跑）----------
    hotword_ok = run_hotword_regression()

    if args.only_hotwords:
        print("结论：" + ("热词纠错全部通过 ✅" if hotword_ok else "热词纠错有失败项 ❌"))
        return 0 if hotword_ok else 1

    # ---------- 1. 凭据预检 ----------
    # 走和运行时同一套解析逻辑：先看「AI 配置」页里的厂商，再看 .env。
    # 自己另写一遍判断，就会出现「脚本说没配、实际能跑」这种自相矛盾。
    print("[0/4] 凭据检查（AI 配置页 优先，其次 beibei-agent/.env）")
    from app.services.asr import resolve_xfyun_credentials
    cred = resolve_xfyun_credentials()

    for name, value in (("APPID", cred.app_id), ("APIKey", cred.api_key),
                        ("APISecret", cred.api_secret)):
        shown = f"{value[:6]}…{value[-4:]}（{len(value)} 位）" if value else "（空）"
        print(f"  {'OK ' if value else 'MISS'} {name:<10} = {shown}")
    print(f"  凭据来源：{cred.source or '（没找到）'}")
    if cred.base_url:
        print(f"   请求端点：{cred.base_url}")

    if not cred.complete:
        missing = [n for n, v in (("APPID", cred.app_id), ("APIKey", cred.api_key),
                                  ("APISecret", cred.api_secret)) if not v]
        print()
        print("  ✗ 还差 " + "、".join(missing) + "，没法测。讯飞要**三个**值，只填 API Key 不够。")
        print()
        print("  怎么拿到这三个值：")
        print("    1. 打开 https://console.xfyun.cn/app/myapp  注册 / 登录（需实名认证）")
        print("    2. 「创建应用」→ 填个名字，平台选 WebAPI")
        print("    3. 进应用 → 左侧「语音听写（流式版）」→ 领取免费额度（默认每日 500 次）")
        print("    4. 应用详情页能看到 APPID / APIKey / APISecret，后两个都是 32 位")
        print()
        print("  填在哪里（两个地方都行）：")
        print("    A. 前端「设置 → AI 配置」→ 编辑「讯飞语音听写」→ 三栏都填上 → 打开「启用」")
        print("       （不需要重启，保存即生效）")
        print("    B. 改 beibei-agent/.env 的 XFYUN_APP_ID / XFYUN_API_KEY / XFYUN_API_SECRET")
        print("       （改完必须重启 beibei-agent）")
        print()
        print("  参考文档：https://www.xfyun.cn/doc/asr/voicedictation/API.html")
        return 2
    print()

    # ---------- 1. 准备音频 ----------
    print("[1/4] 准备测试音频")
    tmpdir = Path(tempfile.mkdtemp(prefix="beibei_asr_"))
    if args.audio:
        wav = Path(args.audio)
        if not wav.exists():
            print(f"  ✗ 文件不存在：{wav}")
            return 2
        expected = args.say
        print(f"  用指定文件：{wav}（{wav.stat().st_size} 字节）")
        print(f"  ⚠️ 用外部音频时无法自动比对内容，只打印识别结果")
        expected = ""
    else:
        wav = tmpdir / "tts_test.wav"
        if not synthesize(args.say, wav):
            print("  提示：可以自己录一段 wav/webm，用 --audio 传进来")
            return 2
        expected = args.say
    print(f"  期望文本：{expected or '（未指定）'}")
    print()

    # ---------- 2. 识别 ----------
    path_name = "直连 Python :8000" if args.direct else "Java 网关 :8080（浏览器实际路径）"
    print(f"[2/4] 调用 ASR（{path_name}）")
    kb_id = args.kb or None
    try:
        result = (call_python_direct if args.direct else call_java_gateway)(
            wav, kb_id, not args.no_hotwords)
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ {exc}")
        print()
        print("  排查顺序：")
        print("    1. 服务起了吗？  :8000 / :8080 是否监听")
        print("    2. 凭据填了吗？  就是上面 [0/4] 那三个值")
        print("    3. 报 401「HMAC signature does not match」→ APIKey/APISecret 复制错了")
        print("    4. 报 403 时钟偏移 → 本机时间偏差超过 5 分钟，校准时间")
        print("    5. 报 11200 → 该能力没授权/额度用完，去控制台领免费额度")
        return 2

    raw = result.get("rawText") or result.get("text") or ""
    text = result.get("text") or ""
    fixes = result.get("hotwordFixes") or []
    print(f"  原始识别：{raw}")
    if fixes:
        pairs = "、".join(f"{f.get('from')}→{f.get('to')}" for f in fixes)
        print(f"  热词纠错：{pairs}")
    print(f"  最终文本：{text}")
    print(f"  音频时长：{result.get('durationMs')} ms   PCM 字节：{result.get('pcmBytes')}")
    print()

    if not text.strip():
        print("[3/4] 比对 —— ✗ 识别结果为空")
        return 1

    # ---------- 3. 比对 ----------
    print("[3/4] 比对结果")
    if not expected:
        print("  （用外部音频，跳过比对）")
        return 0

    a, b = normalize(expected), normalize(text)
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    print(f"  字符级相似度：{ratio * 100:.1f}%")

    hit = [t for t in KEY_TERMS if normalize(t) in b]
    miss = [t for t in KEY_TERMS if t not in hit]
    print(f"  命中关键词（{len(hit)}/{len(KEY_TERMS)}）：{'、'.join(hit) or '（无）'}")
    if miss:
        print(f"  漏掉关键词：{'、'.join(miss)}")

    # 判定标准：相似度 ≥ 0.75 且至少命中一半关键词。
    # 不用「一字不差」是因为 TTS 合成音和真人发音差别很大，
    # 而且专业术语本来就有多种合理写法。
    ok = ratio >= 0.75 and len(hit) >= math.ceil(len(KEY_TERMS) / 2)

    # ---------- 4. 结论 ----------
    print()
    print("[4/4] 结论")
    print("  " + ("✅ 通过 —— 讯飞语音听写链路可用，录音转文字能正常工作"
                  if ok else
                  "❌ 未通过 —— 链路通了但识别质量不合格，看上面的漏词"))
    print()
    print("  说明：TTS 合成音的识别难度和真人不一样（没有呼吸声、语速均匀），")
    print("       所以这个用例主要验证「链路 + 协议 + 热词」正确，")
    print("       真人识别效果建议在浏览器里按住说话实测一次校准。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

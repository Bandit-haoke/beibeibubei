"""
背备不悲 · 语音转文字

链路：
    浏览器录音(webm/opus) → ffmpeg 转 16k 单声道 PCM → 讯飞语音听写(WebSocket) → 文本
                                                                              ↓
                                                            专有名词热词纠错（后处理）

设计要点：
  1. **热词纠错放在后处理**，不依赖 ASR 厂商的热词接口是否开通。
     ASR 对「缓存击穿」这类术语经常听成「缓存基础」「缓存基础」，用编辑距离
     对着知识库里的真实术语纠一遍，效果立竿见影而且完全可测。
  2. ffmpeg 先转 16k 单声道 s16le —— 讯飞只认这个格式，
     浏览器 MediaRecorder 默认给的是 webm/opus。
  3. 未配置凭据时抛出明确的 AsrUnavailable，Java 侧转成 code=5032，
     前端隐藏录音按钮而不是报错。
"""

from __future__ import annotations

import asyncio
import base64
import difflib
import hashlib
import hmac
import json
import logging
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlencode

from sqlalchemy import text as sql_text

from app.config import get_settings
from app.core.logging import get_logger
from app.db.mysql import get_engine

logger = get_logger(__name__)

XFYUN_HOST = "iat-api.xfyun.cn"
XFYUN_PATH = "/v2/iat"
# 每帧 40ms 的 16k 单声道 16bit PCM = 1280 字节
FRAME_SIZE = 1280
FRAME_INTERVAL = 0.04
IAT_SAMPLE_RATE = 16000
IAT_BYTES_PER_SECOND = IAT_SAMPLE_RATE * 2     # 16bit 单声道
# 讯飞语音听写定位是「1 分钟内的即时语音转文字」，单会话硬上限 60 秒。
# 而我们是按 40ms 一帧实时上传的，N 秒录音就要 N 秒以上才发得完 ——
# 所以超过这个秒数就必须切段，否则 50 秒以上的录音会随机报「语音不可用」。
#
# 取 35 秒的理由：段越少，切在词中间的机会越少（切一次就可能毁掉一个词）；
# 但要给握手和网络留余量，不能贴着 60 秒上限。
IAT_CHUNK_SECONDS = 35
# 下刀位置的搜索半径。窗口太窄会找不到真正的停顿，只能切在字中间。
IAT_CUT_WINDOW_SECONDS = 3.0


class AsrUnavailable(RuntimeError):
    """
    语音服务不可用。

    permanent 用来区分两类失败：
      True  —— 凭据没配、能力没开通这种「改配置才能好」的，前端可以干脆隐藏录音按钮
      False —— 网络抖动、讯飞临时超时这种「重试可能就好」的，应该重试并保留按钮
    混在一起的话，一次网络抖动就会让用户以为功能坏了。
    """

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


# ---------------------------------------------------------------------------
#  凭据解析
# ---------------------------------------------------------------------------

class XfyunCredentials(NamedTuple):
    """
    讯飞三元组 + 来源 + 端点。

    用具名元组而不是「四五个值的普通元组」：调用方写 `cred.app_id` 比
    `t[0]` 清楚得多，而且出错时不会因为顺序写反而静默用错值。
    它同时支持元组解包，两种情况都能用。
    """

    app_id: str = ""
    api_key: str = ""
    api_secret: str = ""
    source: str = ""
    base_url: str = ""

    @property
    def complete(self) -> bool:
        """三个值齐了才算可用 —— 只有 APIKey 是发不出请求的。"""
        return bool(self.app_id and self.api_key and self.api_secret)


def _row_to_credentials(row: Any, source: str) -> XfyunCredentials:
    """把 bb_ai_provider 的一行变成凭据对象（Key 需要解密）。"""
    settings = get_settings()
    from app.core.crypto import decrypt

    name, app_id, key_enc, secret_enc, base_url = (
        row[0], row[1] or "", row[2] or "", row[3] or "", row[4] or "")
    api_key = decrypt(key_enc, settings.secret_key) if key_enc else ""
    api_secret = decrypt(secret_enc, settings.secret_key) if secret_enc else ""
    return XfyunCredentials(app_id, api_key, api_secret, source.format(name=name), base_url)


def load_provider_credentials(provider_id: int) -> XfyunCredentials:
    """
    按 id 取某个厂商的凭据，**不看 enabled**。

    「测试连通」按钮必须能在启用之前用 —— 先测通再启用才是正常顺序。
    所以这里和 resolve_xfyun_credentials() 的过滤条件刻意不同。
    """
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sql_text("SELECT name, app_id, api_key_enc, api_secret_enc, base_url "
                         "FROM bb_ai_provider WHERE id = :id"),
                {"id": provider_id},
            ).fetchone()
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取厂商 #%s 配置失败：%s", provider_id, exc)
        return XfyunCredentials()
    if row is None:
        return XfyunCredentials()
    return _row_to_credentials(row, "厂商 #{name}")


def resolve_xfyun_credentials() -> XfyunCredentials:
    """
    取讯飞凭据。

    讯飞和别家不一样：它要**三个**值，不是「一个 API Key」。
    所以取值顺序必须支持数据库，否则用户就得去改 .env 文件再重启服务，体验上完全是倒退。

    顺序（与 llm.py 的分层保持一致）：
      1. bb_model_route 里 ASR 任务指定的厂商（「AI 配置」页配的）
      2. 任意 capability 含 ASR 且启用的厂商，按 priority 升序
      3. .env 的 XFYUN_*（兜底，也是最早期的路径）

    前两层只要缺任何一个值就继续往下找 —— 半个三元组是没法用的。

    ⚠️ 必须排除「讯飞语音转写（LFASR）」那条配置：
    它同样挂在 ASR 能力下（面经要用），但走的是另一套 HTTP 接口（raasr.xfyun.cn）、
    另一套密钥。如果不排除，用户一旦新增了语音转写配置，这里的选路就可能挑中它，
    表现为**语音输入突然不可用** —— 而且是"配了反而坏了"，非常难理解。
    它只由 app/services/interview_note.py 的 resolve_lfasr_credentials() 使用。
    """
    settings = get_settings()

    # 讯飞语音转写专用配置的识别条件（vendor 标记或 base_url 含 raasr）
    not_lfasr = ("AND LOWER(COALESCE(p.vendor, '')) <> 'xfyun_lfasr' "
                 "AND COALESCE(p.base_url, '') NOT LIKE '%raasr%' ")

    queries = (
        # 1) 任务路由指定的 ASR 厂商
        ("SELECT p.name, p.app_id, p.api_key_enc, p.api_secret_enc, p.base_url "
         "FROM bb_ai_provider p JOIN bb_model_route r ON r.provider_id = p.id "
         "WHERE r.task_type = 'ASR' AND p.enabled = 1 " + not_lfasr + "LIMIT 1"),
        # 2) 任何启用的 ASR 厂商
        ("SELECT p.name, p.app_id, p.api_key_enc, p.api_secret_enc, p.base_url "
         "FROM bb_ai_provider p "
         "WHERE p.enabled = 1 AND p.capability LIKE '%ASR%' "
         "  AND COALESCE(p.locked, 0) = 0 " + not_lfasr +
         "ORDER BY p.priority ASC LIMIT 1"),
    )

    for sql in queries:
        try:
            with get_engine().connect() as conn:
                row = conn.execute(sql_text(sql)).fetchone()
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取 ASR 厂商配置失败：%s", exc)
            break
        if row is None:
            continue
        cred = _row_to_credentials(row, "AI 配置（{name}）")
        if cred.complete:
            return cred
        logger.info(
            "ASR 厂商「%s」凭据不完整（appId=%s key=%s secret=%s），继续往下找",
            row[0], bool(cred.app_id), bool(cred.api_key), bool(cred.api_secret),
        )

    if settings.xfyun_app_id and settings.xfyun_api_key and settings.xfyun_api_secret:
        return XfyunCredentials(settings.xfyun_app_id, settings.xfyun_api_key,
                                settings.xfyun_api_secret, "beibei-agent/.env")

    return XfyunCredentials()


def _xfyun_error_hint(status: int | None, detail: str) -> str:
    """
    把讯飞的失败翻成人话。

    传进来的 `status` 可能是两种东西，都要认：
      - 握手阶段的 HTTP 状态码（401 / 403 / 404，见官方文档「鉴权结果」）
      - 会话阶段的业务错误码（10005 / 10114 / 11200…，见官方文档「错误码」）
    每一条都对应一个非常具体的、五分钟能改完的配置问题或重试建议。
    """
    text = detail or ""

    # ---- 会话阶段的业务错误码 ----
    business = {
        10005: "APPID 不对，或这个应用没开通「语音听写（流式版）」",
        10006: "采样率参数不对（我们固定发 16k 单声道 16bit PCM）",
        10007: "参数值不合法",
        10009: "音频数据非法",
        10014: "会话超时，稍后重试；如果经常出现说明录音太长了",
        10019: "会话超时，稍后重试",
        10043: "音频解码失败",
        10101: "引擎会话已结束（客户端还在发数据）",
        10114: "单次会话超过 60 秒上限，录音太长，请分段说",
        10139: "参数错误",
        10160: "请求不是合法 JSON",
        10161: "音频没有做 base64 编码",
        10163: "缺少必传参数或参数不合法",
        10165: "音频帧乱序（第一帧必须 status=0）",
        10200: "超过 10 秒没有发送数据，连接被断开",
        10222: "讯飞侧网络异常，稍后重试",
        10500: "讯飞内部错误，稍后重试",
        10700: "讯飞引擎访问超时，稍后重试",
        11200: "该能力未授权、授权过期或总调用量用完了，去控制台看套餐用量",
        11201: "当日调用次数超限（免费额度默认每日 500 次）",
        11202: "每秒调用次数超限，稍后重试",
        11203: "授权已过期，去控制台续期",
    }
    if status in business:
        return business[status]

    # ---- 握手阶段的 HTTP 状态码 ----
    if "HMAC signature does not match" in text:
        return "APIKey 或 APISecret 不对（注意别带上多余的空格/换行）"
    if "cannot be verified" in text and "date" in text.lower():
        return "本机时间与标准时间差超过 5 分钟，校准一下系统时间"
    if "IP address is not allowed" in text:
        return "控制台开了 IP 白名单，请关掉（白名单要填公网 IP，局域网 IP 无效）"
    if "Unauthorized" in text:
        return "缺少鉴权参数，检查 APIKey / APISecret"
    if status == 401:
        return "鉴权失败：检查 APIKey 与 APISecret"
    if status == 403:
        return "被拒绝：检查系统时间是否偏差过大、或控制台是否开了 IP 白名单"
    if status == 404:
        return ("端点地址不对。语音听写（流式版）的地址应该是 "
                "wss://iat-api.xfyun.cn/v2/iat")
    if isinstance(status, int) and status >= 500:
        return "讯飞服务端异常，稍后重试"
    return "检查三个值是否都来自同一个应用，以及该应用是否已开通「语音听写（流式版）」"


async def probe_xfyun_credentials(cred: XfyunCredentials) -> dict[str, Any]:
    """
    真机探测讯飞凭据：真的去和讯飞握一次手。

    这是唯一能确认「三个值都对」的办法 —— 只 ping 端口或者只看格式，
    都发现不了 APIKey/APISecret 配错。握手成功后立刻断开，不会产生识别调用量。

    HTTP 101 表示协议升级成功，也就是鉴权通过。
    """
    import websockets

    if not cred.complete:
        missing = [n for n, v in (("APPID", cred.app_id), ("APIKey", cred.api_key),
                                  ("APISecret", cred.api_secret)) if not v]
        return {"ok": False, "error": "还差 " + "、".join(missing) + " 没填",
                "hint": "讯飞需要三个值，只填 API Key 发不出请求"}

    host, path = _split_endpoint(cred.base_url)
    endpoint = f"wss://{host}{path}"
    url = _build_auth_url(cred.api_key, cred.api_secret, host, path)

    started = time.time()
    try:
        async with websockets.connect(url, open_timeout=12, close_timeout=3) as ws:
            await ws.close()
        latency = int((time.time() - started) * 1000)
        return {
            "ok": True, "latencyMs": latency, "endpoint": endpoint,
            "source": cred.source,
            "message": "握手成功（HTTP 101），APPID / APIKey / APISecret 三个值都有效",
        }
    except Exception as exc:  # noqa: BLE001
        latency = int((time.time() - started) * 1000)
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        detail = str(exc)
        logger.warning("讯飞凭据探测失败 %s：%s", endpoint, detail)
        return {
            "ok": False, "latencyMs": latency, "endpoint": endpoint,
            "source": cred.source, "status": status,
            "error": detail[:300],
            "hint": _xfyun_error_hint(status, detail),
        }


# ---------------------------------------------------------------------------
#  音频转码
# ---------------------------------------------------------------------------

def transcode_to_pcm16k(audio_bytes: bytes, suffix: str = ".webm") -> bytes:
    """任意音频 → 16k 单声道 16bit 小端 PCM。"""
    settings = get_settings()
    ffmpeg = settings.ffmpeg_path

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        dst = Path(tmp) / "out.pcm"
        src.write_bytes(audio_bytes)

        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src),
            "-ac", "1", "-ar", "16000", "-f", "s16le", "-acodec", "pcm_s16le",
            str(dst),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=120)
        except FileNotFoundError as exc:
            raise AsrUnavailable(
                f"找不到 ffmpeg（{ffmpeg}）。语音转文字依赖它做格式转换。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AsrUnavailable("音频转码超时") from exc

        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace")[:300]
            raise AsrUnavailable(f"ffmpeg 转码失败：{detail}")
        if not dst.exists() or dst.stat().st_size == 0:
            raise AsrUnavailable("音频转码后为空，可能录音文件损坏")

        pcm = dst.read_bytes()

    duration_ms = int(len(pcm) / 2 / 16000 * 1000)
    logger.info("音频转码完成：%d 字节 PCM，约 %.1f 秒", len(pcm), duration_ms / 1000)
    return pcm


# ---------------------------------------------------------------------------
#  讯飞语音听写
# ---------------------------------------------------------------------------

def _split_endpoint(base_url: str) -> tuple[str, str]:
    """
    把配置里的 Base URL 拆成 (host, path)。

    要容忍几种「人不一定会写对」的形式：
      - `wss://iat-api.xfyun.cn/v2/iat`（标准）
      - `https://iat-api.xfyun.cn/v2/iat`（复制成 http 了）
      - `ws[s]://iat-api.xfyun.cn/v2/iat` ← **讯飞官方文档就是这种简写**，
        表示「ws 或 wss」。很多人会连方括号一起复制进来，
        结果 Java 的 URI 解析直接炸：`Illegal character in scheme name at index 2: ws%5Bs%5D://…`
      - 少了协议前缀的裸域名

    解析不出来就退回默认端点，绝不因为一个 URL 写错就让整个语音功能不可用。
    """
    raw = (base_url or "").strip()
    if not raw:
        return XFYUN_HOST, XFYUN_PATH

    # 文档简写 → 真实协议；顺带把所有方括号去掉
    raw = re.sub(r"^(wss?|https?)\[s\]://", "wss://", raw, flags=re.I)
    raw = raw.replace("[", "").replace("]", "")
    raw = re.sub(r"^(wss?|https?)://", "", raw, flags=re.I)

    host, _, path = raw.partition("/")
    host = host.strip()
    if not host:
        return XFYUN_HOST, XFYUN_PATH
    return host, ("/" + path.strip("/") if path.strip("/") else XFYUN_PATH)


def _build_auth_url(api_key: str, api_secret: str,
                    host: str = XFYUN_HOST, path: str = XFYUN_PATH) -> str:
    """按讯飞文档做 HMAC-SHA256 签名，得到带鉴权参数的 WebSocket URL。"""
    date = format_datetime(datetime.now(timezone.utc), usegmt=True)
    signature_origin = (
        f"host: {host}\n"
        f"date: {date}\n"
        f"GET {path} HTTP/1.1"
    )
    signature = base64.b64encode(
        hmac.new(api_secret.encode(), signature_origin.encode(), hashlib.sha256).digest()
    ).decode()

    authorization = base64.b64encode(
        (
            f'api_key="{api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        ).encode()
    ).decode()

    return f"wss://{host}{path}?" + urlencode({
        "authorization": authorization, "date": date, "host": host,
    })


async def _xfyun_iat(
    pcm: bytes, *, credentials: XfyunCredentials, language: str = "zh_cn", domain: str = "iat"
) -> str:
    import websockets

    if not credentials.complete:
        # ⚠️ 报错里要写清「两个地方都可以填」，并且强调讯飞要三个值 ——
        #    只说「填 API Key」会让人以为一个字段就够了，白折腾半天。
        raise AsrUnavailable(
            "未配置讯飞凭据。讯飞需要 **三个** 值：APPID / APIKey / APISecret。\n"
            "  方式一（推荐，不用重启）：前端「设置 → AI 配置」→ 讯飞语音听写 → "
            "三栏都填上并打开「启用」\n"
            "  方式二：改 beibei-agent/.env 的 XFYUN_APP_ID / XFYUN_API_KEY / "
            "XFYUN_API_SECRET，改完重启 beibei-agent\n"
            "  取不到就先用打字作答，不影响其它功能",
            permanent=True,
        )

    host, path = _split_endpoint(credentials.base_url)
    url = _build_auth_url(credentials.api_key, credentials.api_secret, host, path)
    # 以 sn（结果序号）为键的片段表，见 _merge_result 的说明
    segments: dict[int, str] = {}

    try:
        async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
            # 发送音频
            async def sender() -> None:
                total = len(pcm)
                for offset in range(0, total, FRAME_SIZE):
                    chunk = pcm[offset:offset + FRAME_SIZE]
                    status = 0 if offset == 0 else (2 if offset + FRAME_SIZE >= total else 1)
                    frame = {
                        "data": {
                            "status": status,
                            "format": "audio/L16;rate=16000",
                            "encoding": "raw",
                            "audio": base64.b64encode(chunk).decode(),
                        }
                    }
                    if status == 0:
                        frame["common"] = {"app_id": credentials.app_id}
                        frame["business"] = {
                            "language": language,
                            "domain": domain,
                            "accent": "mandarin",
                            # 后端点检测静默时间。官方现行文档叫 eos，
                            # 早期版本叫 vad_eos —— 两个都发，省得踩版本差异。
                            "eos": 3000,
                            "vad_eos": 3000,
                            "dwa": "wpgs",     # 动态修正，边说边出字
                        }
                    await ws.send(json.dumps(frame))
                    await asyncio.sleep(FRAME_INTERVAL)

            async def receiver() -> None:
                async for message in ws:
                    payload = json.loads(message)
                    code = payload.get("code", 0)
                    if code != 0:
                        hint = _xfyun_error_hint(code, str(payload.get("message", "")))
                        logger.warning(
                            "讯飞返回错误 code=%s message=%s（音频 %.1f 秒）→ %s",
                            code, payload.get("message", ""),
                            len(pcm) / 2 / IAT_SAMPLE_RATE, hint,
                        )
                        raise AsrUnavailable(
                            f"讯飞返回错误 {code}：{payload.get('message', '')}（{hint}）"
                        )
                    data = payload.get("data") or {}
                    result = data.get("result") or {}
                    if result:
                        _merge_result(segments, result)
                    if data.get("status") == 2:
                        break

            await asyncio.gather(sender(), receiver())
    except AsrUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        # 一定要记下来：以前这里只把异常包一层抛出去，
        # 日志里只有一句「503 Service Unavailable」，完全看不出是超时、
        # 鉴权失败还是网络断了 —— 排查全靠猜。
        logger.warning(
            "调用讯飞语音听写失败（音频 %.1f 秒）：%s: %s",
            len(pcm) / 2 / IAT_SAMPLE_RATE, type(exc).__name__, exc,
        )
        raise AsrUnavailable(f"调用讯飞语音听写失败：{type(exc).__name__}: {exc}") from exc

    return "".join(segments[k] for k in sorted(segments)).strip()


def _merge_result(segments: dict[int, str], result: dict[str, Any]) -> None:
    """
    把一片识别结果并进片段表。

    ⚠️ **这里以前是错的，而且是长音频才会暴露的那种错。**

    开启动态修正（dwa=wpgs）后，讯飞返回的 `rg` 是**结果序号 sn**，不是数组下标。
    老实现写成 `pieces[start-1:end] = [text]` —— 按列表下标替换。
    可 `pieces` 的条目数并不等于 sn（只有 text 非空才追加，替换还会改变长度），
    所以只要出现过一次 rpl，序号就从此错位，之后的替换全部落到错误位置，
    输出退化成层层叠加的乱码：

        缓存击穿用缓存击穿用护缓存击穿用护翅缓存击穿用互斥所…

    现在改成以 sn 为键的字典，与讯飞官方 demo 一致：
        pgs=rpl       → 先删掉 rg 范围内的片段，再写入本次结果
        pgs=apd/缺省   → 直接写入本次结果
    最后按 sn 升序拼接。
    """
    text = _join_words(result.get("ws") or [])
    sn = result.get("sn")
    if not isinstance(sn, int):
        sn = (max(segments) + 1) if segments else 1

    if (result.get("pgs") or "").lower() == "rpl":
        rg = result.get("rg")
        if isinstance(rg, list) and len(rg) == 2:
            for key in range(int(rg[0]), int(rg[1]) + 1):
                segments.pop(key, None)

    if text:
        segments[sn] = text


async def _transcribe_segment(pcm: bytes, credentials: XfyunCredentials,
                              *, attempts: int = 3) -> str:
    """
    识别一段音频，**失败自动重试**。

    为什么需要重试：一段 50 秒的录音要实时上传 50 秒，
    这中间任何一个瞬时抖动（连接被重置、讯飞侧 10500/10700）都会让整段白录。
    用户重录一次的代价远高于我们多试两次。

    只对「重试可能就好」的失败重试；凭据没配这种改配置才能好的，直接抛出去。
    """
    last: AsrUnavailable | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await _xfyun_iat(
                pcm, credentials=credentials, language="zh_cn", domain="iat")
        except AsrUnavailable as exc:
            last = exc
            if exc.permanent or attempt >= attempts:
                raise
            wait = 1.0 * attempt
            logger.warning("第 %d/%d 次识别失败，%.0f 秒后重试：%s",
                           attempt, attempts, wait, exc)
            await asyncio.sleep(wait)
    raise last if last else AsrUnavailable("识别失败")


def _audio_level(pcm: bytes) -> tuple[float, float]:
    """
    返回音频的 (RMS, 峰值)，量纲是 int16 的 0~32768。

    为什么要量它：用户报「录完音什么都不显示」时，
    「讯飞没识别出文字」既可能是**录到的是静音**（麦克风/权限问题），
    也可能是**讯飞引擎问题**。两者的处理方式完全不同，
    而只看「识别结果为空」是分不出来的 —— 电平一量就清楚了。
    """
    try:
        import numpy as np
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        if samples.size == 0:
            return 0.0, 0.0
        return float(np.sqrt(np.mean(samples ** 2))), float(np.max(np.abs(samples)))
    except Exception:  # noqa: BLE001
        return -1.0, -1.0


# 正常说话的 RMS 一般在 500~5000；纯数字静音是 0，设备底噪通常 < 20。
# 门槛取 20：只拦「基本肯定是没拾到声音」的情况。
# 宁可偏保守 —— 误判成静音会让用户去折腾麦克风，而真正的问题可能在别处。
SILENCE_RMS = 20.0


def _join_words(ws: list[dict[str, Any]]) -> str:
    """把讯飞返回的 ws 结构拼成文本（cn 是当前词，w 是候选词）。"""
    out = []
    for group in ws:
        for candidate in (group.get("cw") or []):
            word = candidate.get("w")
            if word:
                out.append(word)
    return "".join(out)


def _split_pcm(pcm: bytes, chunk_seconds: int = IAT_CHUNK_SECONDS) -> list[bytes]:
    """
    把长录音切成若干段，**切点尽量落在静音处**。

    为什么必须切：讯飞语音听写是「1 分钟内的即时语音转文字」，
    单会话上限 60 秒；而上传是按 40ms 一帧实时发的，
    所以 N 秒录音要花 N 秒以上才发得完，50 秒以上的录音很容易撞上限被掐断，
    表现就是用户看到的「语音不可用」。

    为什么不按固定长度硬切：切在字中间会把一个字劈成两半，
    两段各识别出半个音，拼起来就是错字。
    所以在一个 ±1.5 秒的窗口里找**能量最低**的位置下刀。
    """
    per_chunk = chunk_seconds * IAT_SAMPLE_RATE
    total_samples = len(pcm) // 2
    if total_samples <= per_chunk:
        return [pcm]

    import numpy as np

    samples = np.frombuffer(pcm, dtype="<i2")
    win = int(IAT_CUT_WINDOW_SECONDS * IAT_SAMPLE_RATE)
    chunks: list[bytes] = []
    pos = 0
    while total_samples - pos > per_chunk:
        target = pos + per_chunk
        lo = max(pos + 1, target - win)
        hi = min(total_samples - 1, target + win)
        if hi > lo:
            # 先做平滑再取最小：直接取最小会挑中某个偶然的过零点。
            # 平滑窗口取 20ms 量级，正好盖住一个音节内部的抖动。
            seg = np.abs(samples[lo:hi]).astype(np.float32)
            k = max(1, int(0.02 * IAT_SAMPLE_RATE))
            smooth = np.convolve(seg, np.ones(k) / k, mode="same")
            cut = lo + int(np.argmin(smooth))
        else:
            cut = target
        chunks.append(samples[pos:cut].tobytes())
        pos = cut
    chunks.append(samples[pos:].tobytes())

    # 丢掉不足 0.4 秒的碎片（那种多半只是切点抖动，硬发过去反而引入噪声）
    min_samples = int(0.4 * IAT_SAMPLE_RATE)
    return [c for c in chunks if len(c) // 2 >= min_samples]


# ---------------------------------------------------------------------------
#  热词纠错（后处理，与 ASR 厂商无关）
# ---------------------------------------------------------------------------

_PUNCT = re.compile(r"[\s，。、；：！？,.;:!?（）()【】\[\]\"'`]")


def _similarity(a: str, b: str) -> float:
    """
    归一化编辑距离相似度：1 - 编辑距离 / 较长长度。

    为什么不用 `difflib.SequenceMatcher.ratio()`：
    对「缓存激穿」这种四字词，ratio 对「缓存击穿」和「缓存穿透」**都给 0.75（打平）**，
    而编辑距离分别是 1 和 2 —— 能正确分出哪个才是听错的那一个。

    短专有名词差一个字就是另一个概念（穿透 / 击穿 / 雪崩），必须分清，
    所以这里不能用「匹配字符数」这种粗粒度指标。
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,                # 删除
                cur[j - 1] + 1,             # 插入
                prev[j - 1] + (ca != cb),   # 替换
            ))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def hotwords_for_kb(kb_id: int | None, limit: int = 300) -> list[str]:
    """
    收集该知识库里的专有名词：知识点名称 + 文档里出现的高频术语。
    这些词会用于把 ASR 听错的词纠回来。
    """
    words: list[str] = []
    try:
        with get_engine().connect() as conn:
            if kb_id:
                rows = conn.execute(
                    sql_text("SELECT name FROM bb_tag WHERE kb_id = :kb ORDER BY level, id LIMIT :n"),
                    {"kb": kb_id, "n": limit},
                ).fetchall()
                words.extend(r[0] for r in rows if r[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取知识点热词失败：%s", exc)

    # 常见技术术语兜底（即使知识库还没抽知识点也能兜住高频错字）
    words.extend([
        "Redis", "Spring Boot", "Spring Cloud", "MyBatis", "MySQL", "Nacos",
        "Sentinel", "Gateway", "RabbitMQ", "Kafka", "Docker", "Kubernetes",
        "缓存穿透", "缓存击穿", "缓存雪崩", "布隆过滤器", "分布式锁",
        "自动装配", "依赖注入", "事务隔离级别", "聚簇索引", "回表",
        "持久化", "主从复制", "哨兵模式", "分库分表", "熔断降级",
    ])

    # 去重且保留较长的词（长词优先匹配）
    seen: dict[str, None] = {}
    for w in words:
        w = str(w).strip()
        if 2 <= len(w) <= 20:
            seen.setdefault(w, None)
    return sorted(seen.keys(), key=len, reverse=True)


def correct_hotwords(text: str, hotwords: list[str], *, threshold: float = 0.75) -> tuple[str, list[dict[str, str]]]:
    """
    用编辑距离把识别错的专有名词纠回来。

    ⚠️ 实现上**不做盲目的滑动窗口**。之前那版在每个位置开窗跟热词比对，
    结果把「的自动装配」切成「的自动装」匹配上「自动装配」，替换后多出一个「配」，
    文本被改坏成「自动装配配」。

    正确做法：**按热词的首字定位**。ASR 听错专有名词时首字通常是准的
    （缓存击穿→缓存基础、布隆过滤器→布隆过滤起），所以只需在首字出现的位置
    开一个**与热词等长**的窗口比对，相似度够高才替换。
    """
    if not text or not hotwords:
        return text, []

    fixes: list[dict[str, str]] = []

    # ---------------- 1. 中文术语：按首字定位 + 等长比对 ----------------
    # 首字 → 以该字开头的热词，这样比全表扫描快得多
    by_first: dict[str, list[str]] = {}
    for w in hotwords:
        if w and "\u4e00" <= w[0] <= "\u9fff" and w.isascii() is False:
            by_first.setdefault(w[0], []).append(w)
    # 长词优先，避免「缓存穿透」先被「缓存」截胡
    for v in by_first.values():
        v.sort(key=len, reverse=True)

    chars = list(text)
    i = 0
    while i < len(chars):
        candidates = by_first.get(chars[i])
        if not candidates:
            i += 1
            continue

        # 1) 先判断「这一段本来就是对的」。
        #    ⚠️ 这一步不能省：只按相似度找最近的热词，会把**一个正确术语改成另一个相似术语**。
        #    真机实测抓到的 bug —— 讯飞正确识别出「缓存击穿」，却被改成了「缓存穿透」：
        #    两者只差一个字，相似度 2*3/(4+4) = 0.75，正好卡在阈值上，
        #    而「缓存穿透」在候选里排在前面，于是先被采纳。
        #    「穿透 / 击穿 / 雪崩」是三个完全不同的概念，改错比不改更糟。
        already_len = 0
        for word in candidates:
            n = len(word)
            if i + n <= len(chars) and "".join(chars[i:i + n]) == word:
                already_len = n
                break
        if already_len:
            i += already_len
            continue

        # 2) 确实听错了才纠：在**所有**候选里挑相似度最高的，而不是第一个过线的
        best_word, best_ratio = "", 0.0
        for word in candidates:
            n = len(word)
            if i + n > len(chars):
                continue
            ratio = _similarity("".join(chars[i:i + n]), word)
            if ratio > best_ratio:
                best_word, best_ratio = word, ratio
        if best_word and best_ratio >= threshold:
            window = "".join(chars[i:i + len(best_word)])
            fixes.append({"from": window, "to": best_word, "score": f"{best_ratio:.2f}"})
            chars[i:i + len(best_word)] = list(best_word)
            i += len(best_word)
        else:
            i += 1

    result = "".join(chars)

    # ---------------- 2. 英文/技术术语：整体词比对 ----------------
    latin_pool = [w for w in hotwords if w and w[0].isascii() and len(w) >= 3]
    latin_lower = {w.lower().replace(" ", ""): w for w in latin_pool}

    def fix_latin(match: re.Match) -> str:
        raw = match.group(0)
        clean = raw.strip()
        if len(clean) < 4:
            return raw
        key = clean.lower().replace(" ", "")
        if key in latin_lower:
            return raw  # 已经对了（只可能大小写有差异，不动它）
        pool = list(latin_lower.keys())
        hits = difflib.get_close_matches(key, pool, n=1, cutoff=0.78)
        if not hits:
            return raw
        best = latin_lower[hits[0]]
        ratio = difflib.SequenceMatcher(None, key, hits[0]).ratio()
        fixes.append({"from": clean, "to": best, "score": f"{ratio:.2f}"})
        return raw.replace(clean, best, 1)

    result = re.sub(r"[A-Za-z][A-Za-z0-9+#.\- ]{2,24}", fix_latin, result)

    if fixes:
        logger.info("热词纠错 %d 处：%s", len(fixes),
                    "、".join(f"{f['from']}→{f['to']}" for f in fixes[:6]))
    return result, fixes


def _best_match(word: str, by_len: dict[int, list[str]]) -> tuple[str | None, float]:
    pool: list[str] = []
    for size in range(max(2, len(word) - 1), len(word) + 2):
        pool.extend(by_len.get(size, []))
    if not pool:
        return None, 0.0
    matches = difflib.get_close_matches(word, pool, n=1, cutoff=0.6)
    if not matches:
        return None, 0.0
    best = matches[0]
    return best, difflib.SequenceMatcher(None, word, best).ratio()


# ---------------------------------------------------------------------------
#  对外入口
# ---------------------------------------------------------------------------

async def transcribe(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    kb_id: int | None = None,
    apply_hotwords: bool = True,
    mic_label: str = "",
) -> dict[str, Any]:
    """完整的语音转文字流程。"""
    suffix = Path(filename).suffix or ".webm"

    pcm = transcode_to_pcm16k(audio_bytes, suffix=suffix)
    duration_ms = int(len(pcm) / 2 / 16000 * 1000)

    # 先量电平：如果是静音，根本不用浪费一次讯飞调用，
    # 而且能立刻给出「是麦克风的问题」这种可执行的结论
    rms, peak = _audio_level(pcm)
    logger.info("音频电平：RMS=%.1f 峰值=%.1f（%.1f 秒）· 麦克风=%s",
                rms, peak, duration_ms / 1000, mic_label or "（前端未上报）")

    if rms >= 0 and rms < SILENCE_RMS:
        logger.warning("录到的基本是静音（RMS=%.1f，峰值=%.1f），不再调用讯飞", rms, peak)
        raise AsrUnavailable(
            f"没有拾到声音（音频电平 RMS={rms:.0f}，几乎为静音）。请依次检查：\n"
            "  1. Windows「设置 → 系统 → 声音 → 输入」里的设备选对了吗，对着说话看音量条动不动\n"
            "  2. 麦克风有没有被物理静音，或者笔记本的麦克风静音键\n"
            "  3. Windows「设置 → 隐私和安全性 → 麦克风」是否允许桌面应用访问\n"
            "  4. 浏览器地址栏左侧的权限图标里，麦克风是否是「允许」\n"
            "  5. 如果插着蓝牙耳机，浏览器可能选了耳机麦克风，换成笔记本内置麦克风试试",
            permanent=False,
        )

    credentials = resolve_xfyun_credentials()

    # 长录音切段：讯飞单会话上限 60 秒，超了会被掐断（用户看到的就是「语音不可用」）
    segments = _split_pcm(pcm)
    if len(segments) > 1:
        logger.info(
            "录音 %.1f 秒，超过单会话上限，切成 %d 段识别",
            len(pcm) / 2 / IAT_SAMPLE_RATE, len(segments),
        )

    parts: list[str] = []
    for idx, seg in enumerate(segments, 1):
        if len(segments) > 1:
            logger.info("  第 %d/%d 段（%.1f 秒）", idx, len(segments),
                        len(seg) / 2 / IAT_SAMPLE_RATE)
        parts.append(await _transcribe_segment(seg, credentials))
    raw_text = "".join(parts)

    hotwords = hotwords_for_kb(kb_id) if apply_hotwords else []
    text, fixes = correct_hotwords(raw_text, hotwords) if hotwords else (raw_text, [])

    # 结果摘要一定要打日志。
    # 之前只记「转码完成」，于是用户报「录完音什么都不显示」时无从判断
    # 到底是「后端没识别出文字」还是「前端没渲染」—— 只能靠猜。
    if raw_text:
        logger.info(
            "识别完成：%.1f 秒 → %d 字（纠错 %d 处，热词表 %d 条，切 %d 段）",
            duration_ms / 1000, len(text), len(fixes), len(hotwords), len(segments),
        )
        logger.debug("识别文本：%s", text[:200])
    else:
        logger.warning(
            "识别结果为空：%.1f 秒音频没有识别出任何文字（切 %d 段，热词表 %d 条）。"
            "常见原因：麦克风没收到声音、录音设备选错、或录音太短",
            duration_ms / 1000, len(segments), len(hotwords),
        )

    return {
        "text": text,
        "rawText": raw_text,
        "hotwordFixes": fixes,
        "durationMs": duration_ms,
        "pcmBytes": len(pcm),
        "provider": "xfyun",
        # 凭据来自哪里 —— 排查「明明填了却说不认识」时，这一行最有用
        "credentialSource": credentials.source,
        "hotwordCount": len(hotwords),
        # 切了几段 —— 长录音出问题时，先看这个
        "chunkCount": len(segments),
    }

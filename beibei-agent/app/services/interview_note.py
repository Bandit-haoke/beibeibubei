"""
背备不悲 · 面经服务

把一段「真实发生过的面试录音」整理成面经，流程四步：

  1. 长音频转写
       - 优先：讯飞【语音转写 LFASR】，单文件最长 5 小时，且带原生角色分离
       - 降级：已配置的【语音听写 iat】（单会话 60 秒上限，按 35 秒切段）
     LFASR 未开通时（错误码 26601/26625/26633）自动降级，不阻断功能。

  2. 说话人角色判定
       - LFASR 路径：引擎给出 speaker 编号，用大模型判断哪个编号是面试官
       - 降级路径：没有说话人信息，用大模型按内容逐句推断

  3. 口语清洗
       - 本地正则：去语气词（嗯/啊/额/那个）、去 3 连重复、去重复标点
       - 大模型：去口头禅、修口误与自我纠正，保留技术细节不动

  4. 生成面经
       - 问题清单（问题 + 回答要点 + 分类）
       - 经验点、总览、Markdown 正文

设计取舍：整条流水线写成同步风格 —— pymilvus、httpx 都是同步的，
用 app.core.sse.stream_from_worker 起子线程跑，不需要为了 SSE 改成 async。
唯一必须 async 的是语音听写的 WebSocket 调用，用 asyncio.run 单独包一层。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from app.core.logging import get_logger
from app.core.sse import EmitFn, ProgressReporter
from app.db.mysql import get_engine
from app.services.asr import (
    AsrUnavailable,
    IAT_SAMPLE_RATE,
    _similarity,
    _split_pcm,
    _transcribe_segment,
    resolve_xfyun_credentials,
    transcode_to_pcm16k,
)
from app.services.llm import llm_client
from app.services.prompts import prompt_service

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
#  常量
# ---------------------------------------------------------------------------

LFASR_BASE = "https://raasr.xfyun.cn/api"
LFASR_SLICE_BYTES = 10 * 1024 * 1024      # 官方建议 10M 一片
LFASR_POLL_SECONDS = 8                    # 轮询间隔，官方建议 10 分钟，但本工具要实时反馈
LFASR_MAX_WAIT_SECONDS = 60 * 60          # 最长等 1 小时（官方 SLA 上限 5 小时，这里保守）
LFASR_DONE_STATUS = 9                     # 转写结果上传完成

# 录音格式白名单（与讯飞语音转写支持的格式一致）
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".opus", ".aac", ".ogg", ".wma", ".amr"}

NOTE_STATUS_PENDING = 0
NOTE_STATUS_TRANSCRIBING = 1
NOTE_STATUS_TRANSCRIBED = 2
NOTE_STATUS_SUMMARIZING = 3
NOTE_STATUS_DONE = 4
NOTE_STATUS_FAILED = 9

ROLE_INTERVIEWER = 1
ROLE_ME = 2

# 引擎无法判断时的兜底：归到候选人，宁可多算一句回答，也不要凭空造一个问题
ROLE_FALLBACK = ROLE_ME


# ---------------------------------------------------------------------------
#  本地口语清洗
# ---------------------------------------------------------------------------

# 只匹配「独立出现」的语气词：前后必须是标点/空白，或者句首句尾。
# 不能无脑全局替换 —— "真的啊" 里的 "啊" 是有语气的，
# "啊哈" 里的 "啊" 是构词的一部分，全局替换会把句子改味。
#
# 「哈」故意不在列表里：笑声是有情绪信息的，不属于"无意义填充"。
_FILLER_TOKENS = [
    # 单字语气词
    "嗯", "呃", "额", "哦", "唔", "唉", "诶", "哎", "噢", "喔",
    "啊", "呀", "哇", "呐", "咧", "咦", "嗨",
    # 口头禅
    "那个", "这个", "就是说", "然后就是", "怎么说呢", "对吧", "是吧",
    "你知道吧", "你懂我意思吧", "反正吧", "对不对",
]

# 边界字符集。
#
# ⚠️ 这里踩过一个坑：直接用 "[" + 字符 + "]" 拼字符类，如果字符里含 `]`，
# 字符类会**提前闭合**，后面的内容变成必须匹配的字面量。
# 当时的结果是 lookbehind 变成两字符宽，只有句首（^）那个分支还能命中 ——
# 表现出来就是"一句话里只去掉了第一个语气词"。
# 所以这里一律用 re.escape 转义，并且不含 `[`/`]` 这两个字符（本来也不需要）。
_BOUNDARY_LITERALS = "，。！？、；：…—·～~,.!?;:\"'“”‘’（）()【】{}《》<>"
_BOUNDARY_CLASS = "[" + re.escape(_BOUNDARY_LITERALS) + r"\s]"

_FILLER_RE = re.compile(
    r"(?:(?<=^)|(?<=" + _BOUNDARY_CLASS + r"))"
    r"(" + "|".join(sorted(_FILLER_TOKENS, key=len, reverse=True)) + r")"
    r"(?=" + _BOUNDARY_CLASS + r"|$)"
)

# 同一个中文字连续 3 次以上：我我我 -> 我、哈哈哈 -> 哈。
#
# ⚠️ 必须限定为 CJK 字符，不能用 `(.)\1{2,}`：
# 那样会把 "QPS 大概 3000 左右" 里的 "000" 也折叠成一个 0，
# 数字是技术内容里最不能动的东西 —— 这种错误还不会报错，只会静默改错。
_STUTTER_CHAR_RE = re.compile(r"([\u4e00-\u9fff])\1{2,}")

# 常见的"叠词式结巴"：这个这个 -> 这个、就是就是 -> 就是。
# 只处理这些固定词，不敢用 `(.{2})\1` 这种通配 ——
# "研究研究"、"看看"、"试试" 都是正常说法，通配会把它们改坏。
_STUTTER_WORDS = [
    "就是", "这个", "那个", "我们", "你们", "然后", "因为", "所以",
    "但是", "其实", "可能", "应该", "觉得", "知道", "进行", "的话",
]
_STUTTER_WORD_RE = re.compile("(" + "|".join(_STUTTER_WORDS) + r")\1+")

# 重复标点：，，。 -> ，
_DUP_PUNCT_RE = re.compile(r"([，。！？、；：])\1+")
_SPACES_RE = re.compile(r"[ \t\u3000]{2,}")
# 句首残留的孤立标点（含省略号、破折号）
_LEADING_PUNCT_RE = re.compile(r"^[，。、；：！？…—～·\s]+")


def clean_text_locally(raw: str) -> tuple[str, list[str]]:
    """
    确定性的本地清洗。返回 (清洗后文本, 被去掉的词)。

    这一步不依赖大模型，所以永远会执行 —— 即使大模型调用失败，
    输出也不会是一堆"嗯嗯啊啊"。

    顺序有讲究，按「先合并再删除」来：
      1. 先去结巴（我我我 → 我），否则"啊啊啊"这种会被当成一个整体，
         删不掉（它前面是句首、后面却还是"啊"，不满足边界条件）；
      2. 再删语气词，此时它们已经独立成词，边界条件才成立；
      3. 最后收拾重复标点和句首孤立的标点。
    """
    if not raw:
        return "", []

    removed: list[str] = []
    text_value = raw

    # 1. 结巴
    for match in _STUTTER_CHAR_RE.finditer(text_value):
        removed.append(match.group(0))
    text_value = _STUTTER_CHAR_RE.sub(r"\1", text_value)

    for match in _STUTTER_WORD_RE.finditer(text_value):
        removed.append(match.group(0))
    text_value = _STUTTER_WORD_RE.sub(r"\1", text_value)

    # 2. 语气词 / 口头禅
    for match in _FILLER_RE.finditer(text_value):
        removed.append(match.group(1))
    text_value = _FILLER_RE.sub("", text_value)

    # 3. 标点
    text_value = _DUP_PUNCT_RE.sub(r"\1", text_value)
    text_value = _SPACES_RE.sub(" ", text_value)
    text_value = _LEADING_PUNCT_RE.sub("", text_value).strip()

    deduped: list[str] = []
    for item in removed:
        if item not in deduped:
            deduped.append(item)
    return text_value, deduped


# ---------------------------------------------------------------------------
#  凭据
# ---------------------------------------------------------------------------

@dataclass
class LfasrCredentials:
    app_id: str
    secret_key: str
    source: str
    base_url: str = LFASR_BASE


@dataclass
class Utterance:
    """一句转写结果（转写阶段还不知道谁是面试官）。"""

    seq: int
    text: str
    start_ms: int = 0
    end_ms: int = 0
    speaker_id: int = 0          # 0 = 引擎没给（降级路径）
    role: int = 0                # 1 面试官 2 我；0 = 待判定
    clean_text: str = ""
    removed_words: str = ""
    question_type: str = ""
    sentences: list[str] = field(default_factory=list)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def resolve_lfasr_credentials() -> LfasrCredentials | None:
    """
    找【语音转写】专用的凭据。

    讯飞每个服务有各自的 APIKey/APISecret，所以优先找专门配置的那条：
      1. ASR 能力、vendor = xfyun_lfasr
      2. ASR 能力、base_url 里含 raasr（用户自己填的也算）
      3. 退回语音听写那条凭据试一把（部分账号两个服务共用一个 secret）
    都找不到就返回 None，调用方自动走降级。
    """
    sql = text(
        "SELECT id, name, vendor, base_url, app_id, api_key_enc, api_secret_enc "
        "FROM bb_ai_provider "
        "WHERE capability LIKE '%ASR%' AND enabled = 1 "
        "ORDER BY priority ASC, id ASC"
    )
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(sql).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询语音转写凭据失败：%s", exc)
        return None

    if not rows:
        return None

    from app.services.asr import _row_to_credentials  # 复用同一套解密逻辑

    dedicated: list[Any] = []
    fallback: list[Any] = []
    for row in rows:
        vendor = (row[2] or "").lower()
        base_url = (row[3] or "").lower()
        if vendor == "xfyun_lfasr" or "raasr" in base_url:
            dedicated.append(row)
        elif vendor == "xfyun":
            fallback.append(row)

    for ordered, is_dedicated in ((dedicated, True), (fallback, False)):
        for row in ordered:
            try:
                cred = _row_to_credentials(row, source=f"AI 配置（{row[1]}）")
            except Exception as exc:  # noqa: BLE001
                logger.warning("解密语音转写凭据失败 provider=%s：%s", row[0], exc)
                continue
            if cred.app_id and cred.api_secret:
                suffix = "（语音转写专用）" if is_dedicated else "（复用语音听写凭据）"
                # 只有「专用配置」才采信它自己填的 Base URL。
                # 复用语音听写凭据时，那一行的 base_url 是 wss://iat-api.xfyun.cn/v2/iat，
                # 拿它去请求会拼出 wss://iat-api.xfyun.cn/v2/iat/prepare 得到 403，
                # 把真正的原因（服务未开通 = 26601）遮掉了，排查时非常误导。
                base_url = LFASR_BASE
                if is_dedicated:
                    base_url = (row[3] or "").rstrip("/") or LFASR_BASE
                return LfasrCredentials(
                    app_id=cred.app_id,
                    secret_key=cred.api_secret,
                    source=cred.source + suffix,
                    base_url=base_url,
                )
    return None


# ---------------------------------------------------------------------------
#  讯飞语音转写 LFASR
# ---------------------------------------------------------------------------

def _signa(app_id: str, secret_key: str, ts: str) -> str:
    """signa = base64(HmacSHA1(MD5(app_id + ts), secret_key))，已用官方测试向量校验。"""
    digest = hashlib.md5((app_id + ts).encode("utf-8")).hexdigest()
    mac = hmac.new(secret_key.encode("utf-8"), digest.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode("utf-8")


class _SliceIdGenerator:
    """官方文档给的 slice_id 生成器：aaaaaaaaaa, aaaaaaaaab, ..."""

    def __init__(self) -> None:
        self._ch = "aaaaaaaaa`"

    def next(self) -> str:
        ch = self._ch
        j = len(ch) - 1
        while j >= 0:
            cj = ch[j]
            if cj != "z":
                ch = ch[:j] + chr(ord(cj) + 1) + ch[j + 1:]
                break
            ch = ch[:j] + "a" + ch[j + 1:]
            j -= 1
        self._ch = ch
        return ch


def _lfasr_error_text(err_no: int | None, failed: str) -> str:
    """把讯飞错误码翻译成能直接照着做的提示。"""
    hints = {
        26601: "应用信息非法。多半是这个讯飞应用没有开通【语音转写】服务，"
               "或该服务的 APISecret 与语音听写不同（讯飞每个服务的密钥是各自独立的）。",
        26625: "语音转写的可用时长不足。请到讯飞控制台【语音转写】页面领取免费额度或购买。",
        26633: "语音转写的可用时长不足（音频时长校验阶段）。请到讯飞控制台补充额度。",
        26607: "该语种未授权，请到讯飞控制台添加。",
        26622: "音频时长超限（上限 5 小时）。",
        26623: "音频格式不支持，请用 mp3/wav/m4a/flac/opus。",
        26631: "音频文件超过 500MB 上限。",
        26604: "获取结果次数超过上限（100 次）。",
        26603: "接口访问频率受限，稍后重试。",
    }
    code = err_no or 0
    base = f"讯飞语音转写失败（err_no={code}）：{failed}"
    hint = hints.get(code)
    return f"{base} —— {hint}" if hint else base


# 这几个错误说明「这条路走不通」，应该直接降级而不是重试
_LFASR_FATAL_CODES = {26601, 26625, 26633, 26607, 26623, 26622, 26631}


class LfasrUnavailable(RuntimeError):
    """语音转写不可用，调用方应降级到语音听写。"""

    def __init__(self, message: str, *, fatal: bool = True) -> None:
        super().__init__(message)
        self.fatal = fatal


def _post_form(client: httpx.Client, path: str, params: dict[str, Any]) -> dict[str, Any]:
    resp = client.post(path, data=params)
    resp.raise_for_status()
    return resp.json()


def transcribe_with_lfasr(
    audio_path: Path,
    credentials: LfasrCredentials,
    *,
    reporter: ProgressReporter,
    progress_range: tuple[int, int] = (5, 55),
) -> list[Utterance]:
    """走讯飞语音转写：prepare → upload → merge → getProgress → getResult。"""
    start, end = progress_range
    span = max(1, end - start)
    file_bytes = audio_path.read_bytes()
    file_len = len(file_bytes)
    slice_num = max(1, (file_len + LFASR_SLICE_BYTES - 1) // LFASR_SLICE_BYTES)

    logger.info(
        "语音转写开始：%s（%.1f MB，分 %d 片）· 凭据来源：%s",
        audio_path.name, file_len / 1024 / 1024, slice_num, credentials.source,
    )

    base = credentials.base_url or LFASR_BASE
    with httpx.Client(base_url=base, timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        # ---- 1. prepare ----
        ts = str(int(time.time()))
        prepare_params = {
            "app_id": credentials.app_id,
            "signa": _signa(credentials.app_id, credentials.secret_key, ts),
            "ts": ts,
            "file_len": str(file_len),
            "file_name": audio_path.name,
            "slice_num": str(slice_num),
            "lfasr_type": "0",
            # 角色分离：has_seperate 打开，并声明是两个人对话
            "has_seperate": "true",
            "speaker_number": "2",
            "role_type": "1",
            # 顺滑词：官方就会过滤"嗯/啊"这类语气词（结果里标记为 wp=s）
            "has_smooth": "true",
            "eng_vad_margin": "1",
            # 科技领域，能明显改善技术名词识别
            "pd": "tech",
        }
        result = _post_form(client, "/prepare", prepare_params)
        if result.get("ok") != 0:
            code = result.get("err_no")
            message = _lfasr_error_text(code, result.get("failed") or "")
            raise LfasrUnavailable(message, fatal=code in _LFASR_FATAL_CODES)

        task_id = result.get("data")
        if not task_id:
            raise LfasrUnavailable("语音转写预处理没有返回 task_id", fatal=False)
        logger.info("语音转写任务已创建 task_id=%s", task_id)
        reporter.emit(start + int(span * 0.05), "已提交转写任务，正在上传音频")

        # ---- 2. upload（按 10M 切片，必须按顺序） ----
        slice_gen = _SliceIdGenerator()
        for idx in range(slice_num):
            chunk = file_bytes[idx * LFASR_SLICE_BYTES:(idx + 1) * LFASR_SLICE_BYTES]
            ts = str(int(time.time()))
            upload_params = {
                "app_id": credentials.app_id,
                "signa": _signa(credentials.app_id, credentials.secret_key, ts),
                "ts": ts,
                "task_id": task_id,
                "slice_id": slice_gen.next(),
            }
            resp = client.post(
                "/upload",
                data=upload_params,
                files={"content": (audio_path.name, chunk, "application/octet-stream")},
            )
            resp.raise_for_status()
            up = resp.json()
            if up.get("ok") != 0:
                raise LfasrUnavailable(
                    f"第 {idx + 1}/{slice_num} 片上传失败：{up.get('failed')}", fatal=False
                )
            ratio = 0.05 + 0.35 * (idx + 1) / slice_num
            reporter.emit(start + int(span * ratio),
                          f"正在上传音频 {idx + 1}/{slice_num} 片")
            logger.info("  第 %d/%d 片上传成功", idx + 1, slice_num)

        # ---- 3. merge ----
        ts = str(int(time.time()))
        merged = _post_form(client, "/merge", {
            "app_id": credentials.app_id,
            "signa": _signa(credentials.app_id, credentials.secret_key, ts),
            "ts": ts,
            "task_id": task_id,
        })
        if merged.get("ok") != 0:
            raise LfasrUnavailable(f"合并音频失败：{merged.get('failed')}", fatal=False)

        # ---- 4. 轮询进度 ----
        reporter.emit(start + int(span * 0.45), "音频已提交，等待转写结果")
        deadline = time.time() + LFASR_MAX_WAIT_SECONDS
        status = 0
        while time.time() < deadline:
            time.sleep(LFASR_POLL_SECONDS)
            ts = str(int(time.time()))
            prog = _post_form(client, "/getProgress", {
                "app_id": credentials.app_id,
                "signa": _signa(credentials.app_id, credentials.secret_key, ts),
                "ts": ts,
                "task_id": task_id,
            })
            if prog.get("ok") != 0:
                code = prog.get("err_no")
                if code in _LFASR_FATAL_CODES:
                    raise LfasrUnavailable(
                        _lfasr_error_text(code, prog.get("failed") or ""), fatal=True
                    )
                logger.warning("查询转写进度失败（继续重试）：%s", prog.get("failed"))
                continue

            payload = prog.get("data")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            payload = payload or {}
            status = int(payload.get("status", 0))
            desc = payload.get("desc", "")
            logger.info("语音转写进度：status=%s desc=%s", status, desc)
            ratio = 0.45 + 0.45 * min(status, LFASR_DONE_STATUS) / LFASR_DONE_STATUS
            reporter.emit(start + int(span * ratio), f"转写中：{desc or '处理中'}")
            if status == LFASR_DONE_STATUS:
                break
        else:
            raise LfasrUnavailable("语音转写超时（超过 1 小时仍未完成）", fatal=False)

        # ---- 5. 取结果 ----
        ts = str(int(time.time()))
        got = _post_form(client, "/getResult", {
            "app_id": credentials.app_id,
            "signa": _signa(credentials.app_id, credentials.secret_key, ts),
            "ts": ts,
            "task_id": task_id,
        })
        if got.get("ok") != 0:
            raise LfasrUnavailable(f"获取转写结果失败：{got.get('failed')}", fatal=False)

        data = got.get("data")
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, list):
            raise LfasrUnavailable("转写结果格式异常", fatal=False)

    reporter.emit(end, "转写完成")
    return _lfasr_to_utterances(data)


def _lfasr_to_utterances(data: list[dict[str, Any]]) -> list[Utterance]:
    """
    把 LFASR 的句子列表转成 Utterance。

    结果字段：bg/ed 毫秒时间戳，onebest 句子内容，speaker 说话人编号（1 起，未开启分离时为 0）。
    """
    utterances: list[Utterance] = []
    for item in data:
        content = (item.get("onebest") or "").strip()
        if not content:
            continue
        try:
            speaker_id = int(item.get("speaker") or 0)
        except (TypeError, ValueError):
            speaker_id = 0
        utterances.append(Utterance(
            seq=len(utterances) + 1,
            text=content,
            start_ms=int(float(item.get("bg") or 0)),
            end_ms=int(float(item.get("ed") or 0)),
            speaker_id=speaker_id,
        ))
    logger.info(
        "语音转写结果：%d 句，说话人编号 %s",
        len(utterances), sorted({u.speaker_id for u in utterances}),
    )
    return utterances


def _credentials_for_provider(provider_id: int) -> LfasrCredentials | None:
    """按 provider id 精确取凭据（用户刚在界面上填完就点测试，用它）"""
    from app.services.asr import _row_to_credentials

    sql = text(
        "SELECT id, name, vendor, base_url, app_id, api_key_enc, api_secret_enc "
        "FROM bb_ai_provider WHERE id = :id"
    )
    with get_engine().connect() as conn:
        row = conn.execute(sql, {"id": provider_id}).fetchone()
    if row is None:
        return None
    cred = _row_to_credentials(row, source=f"AI 配置（{row[1]}）")
    if not (cred.app_id and cred.api_secret):
        return None
    return LfasrCredentials(
        app_id=cred.app_id,
        secret_key=cred.api_secret,
        source=cred.source,
        base_url=(row[3] or LFASR_BASE).rstrip("/") or LFASR_BASE,
    )


def probe_lfasr(provider_id: int | None = None) -> dict[str, Any]:
    """
    探测语音转写能不能用。

    只调 prepare，**不上传音频、不消耗转写时长**，所以可以放心点"测试"。
    这一步就能定死三件事：凭据对不对、服务开没开通、角色分离参数收不收。
    """
    started = time.time()
    creds: LfasrCredentials | None = None
    if provider_id:
        try:
            creds = _credentials_for_provider(int(provider_id))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"读取凭据失败：{exc}", "hint": ""}
    if creds is None:
        creds = resolve_lfasr_credentials()
    if creds is None:
        return {
            "ok": False,
            "error": "没有找到可用的语音转写凭据",
            "hint": "先填好 APPID / APIKey / APISecret 并保存，再点测试",
        }

    ts = str(int(time.time()))
    params = {
        "app_id": creds.app_id,
        "signa": _signa(creds.app_id, creds.secret_key, ts),
        "ts": ts,
        "file_len": "1048576",
        "file_name": "probe.mp3",
        "slice_num": "1",
        "lfasr_type": "0",
        "has_seperate": "true",
        "speaker_number": "2",
        "role_type": "1",
    }
    try:
        with httpx.Client(
            base_url=creds.base_url or LFASR_BASE,
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            result = _post_form(client, "/prepare", params)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"请求讯飞失败：{type(exc).__name__}: {exc}",
            "hint": "检查网络，并确认 Base URL 是 https://raasr.xfyun.cn/api",
            "endpoint": creds.base_url,
        }

    latency = int((time.time() - started) * 1000)
    if result.get("ok") == 0:
        logger.info("语音转写探测通过（%d ms，来源 %s）", latency, creds.source)
        return {
            "ok": True,
            "latencyMs": latency,
            "endpoint": creds.base_url,
            "source": creds.source,
            "message": f"语音转写可用，已开启角色分离（凭据来源：{creds.source}）",
        }

    code = result.get("err_no")
    logger.warning("语音转写探测失败 err_no=%s failed=%s", code, result.get("failed"))
    return {
        "ok": False,
        "error": _lfasr_error_text(code, result.get("failed") or ""),
        "hint": ("到讯飞控制台【语音转写】页面领取免费额度；"
                 "并确认该服务的 APISecret 与语音听写不是同一个（讯飞每个服务密钥独立）"),
        "endpoint": creds.base_url,
        "errNo": code,
    }


# ---------------------------------------------------------------------------
#  降级：语音听写 iat
# ---------------------------------------------------------------------------

_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；!?;])\s*")
"""仅用于诊断/兜底展示。**不要**拿它切说话人边界 —— 见 transcribe_with_iat 的说明。"""


def transcribe_with_iat(
    audio_path: Path,
    *,
    reporter: ProgressReporter,
    progress_range: tuple[int, int] = (5, 55),
) -> list[Utterance]:
    """
    降级路径：用已配置的【语音听写】按 35 秒切段转写。

    这条路**拿不到说话人信息**，所以每段再按标点切成句子，
    时间戳按字符数在段内均摊 —— 只用于展示顺序，不承诺精确。
    """
    start, end = progress_range
    span = max(1, end - start)
    reporter.emit(start, "正在转码音频（语音听写降级模式）")

    audio_bytes = audio_path.read_bytes()
    pcm = transcode_to_pcm16k(audio_bytes, suffix=audio_path.suffix or ".mp3")
    duration_ms = int(len(pcm) / 2 / IAT_SAMPLE_RATE * 1000)
    segments = _split_pcm(pcm)
    logger.info(
        "语音听写降级：音频 %.1f 秒，切成 %d 段",
        duration_ms / 1000, len(segments),
    )

    credentials = resolve_xfyun_credentials()

    async def run_all() -> list[str]:
        out: list[str] = []
        for index, seg in enumerate(segments, 1):
            out.append(await _transcribe_segment(seg, credentials))
            reporter.emit(
                start + int(span * index / len(segments)),
                f"语音识别中 {index}/{len(segments)} 段",
            )
        return out

    try:
        texts = asyncio.run(run_all())
    except AsrUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AsrUnavailable(f"语音听写失败：{exc}") from exc

    # 预先算好每段的起止时间（段长不等，不能拿第 0 段去乘）
    offsets: list[tuple[int, int]] = []
    cursor_ms = 0
    for seg in segments:
        seg_ms = int(len(seg) / 2 / IAT_SAMPLE_RATE * 1000)
        offsets.append((cursor_ms, cursor_ms + seg_ms))
        cursor_ms += seg_ms

    # ⚠️ 这里刻意**不按标点切句**，一段就是一块。
    #
    # 原因：讯飞语音听写的标点恢复并不可靠，实测会把两个人的话连成一条逗号长串：
    #   「你好，请先做一个自我介绍面试官好，我叫张三，有三年 Java 后端经验……」
    # 第一句是面试官提问、第二句是候选人回答，但中间只有逗号甚至什么都没有。
    # 按标点切句会得到"一句话里两个人的内容"，后面再怎么判角色都救不回来。
    #
    # 所以改成：这里只保证"块"和音频时间范围对齐，真正的切句交给大模型
    # （见 infer_and_segment_by_llm），它能同时利用语义和上下文判断换人边界。
    blocks: list[Utterance] = []
    for index, chunk_text in enumerate(texts):
        chunk_text = (chunk_text or "").strip()
        if not chunk_text:
            continue
        seg_start, seg_end = offsets[index] if index < len(offsets) else (cursor_ms, cursor_ms)
        blocks.append(Utterance(
            seq=len(blocks) + 1,
            text=chunk_text,
            start_ms=seg_start,
            end_ms=seg_end,
            speaker_id=0,
        ))

    logger.info("语音听写降级结果：%d 块（无说话人信息，稍后由大模型切句）", len(blocks))
    return blocks


def _audio_duration_ms(audio_path: Path) -> int:
    """用 ffmpeg 转码顺带拿到时长；失败不影响主流程。"""
    try:
        audio_bytes = audio_path.read_bytes()
        pcm = transcode_to_pcm16k(audio_bytes, suffix=audio_path.suffix or ".mp3")
        return int(len(pcm) / 2 / IAT_SAMPLE_RATE * 1000)
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取音频时长失败：%s", exc)
        return 0


# ---------------------------------------------------------------------------
#  大模型步骤
# ---------------------------------------------------------------------------

_ROLE_NAMES = {ROLE_INTERVIEWER: "面试官", ROLE_ME: "我"}


def _normalize_role(value: Any) -> int:
    try:
        role = int(value)
    except (TypeError, ValueError):
        return 0
    return role if role in (ROLE_INTERVIEWER, ROLE_ME) else 0


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _chat_json(prompt: str, *, biz_id: int, task_type: str) -> dict[str, Any]:
    data, _ = llm_client.chat_json(
        [{"role": "user", "content": prompt}],
        task_type=task_type,
        biz_type="INTERVIEW_NOTE",
        biz_id=biz_id,
        temperature=0.2,
    )
    return data if isinstance(data, dict) else {}


def map_speakers_by_llm(
    utterances: list[Utterance], *, note_id: int, reporter: ProgressReporter
) -> dict[int, int]:
    """
    LFASR 给出了 speaker 编号，但编号本身没有语义（不知道 1 是谁）。
    取每个编号的若干代表性发言，让大模型判断哪个编号是面试官。
    """
    reporter.emit(60, "正在判断哪位是面试官")
    by_speaker: dict[int, list[str]] = {}
    for item in utterances:
        by_speaker.setdefault(item.speaker_id, []).append(item.text)

    if len(by_speaker) <= 1:
        only = next(iter(by_speaker), 0)
        logger.info("只识别出 1 个说话人（编号 %s），无法区分角色", only)
        return {only: ROLE_ME}

    # 每个说话人取开头、中间、结尾各一段，避免只看开头误判
    lines: list[str] = []
    for speaker_id, texts in sorted(by_speaker.items()):
        picks = [texts[0]]
        if len(texts) > 2:
            picks.append(texts[len(texts) // 2])
        if len(texts) > 1:
            picks.append(texts[-1])
        for sample in picks:
            lines.append(f"[说话人{speaker_id}] {sample[:200]}")
    prompt = prompt_service.render(
        "INTERVIEW_NOTE_SPEAKER_MAP",
        speaker_samples="\n".join(lines[:40]),
        speaker_ids=",".join(str(s) for s in sorted(by_speaker)),
    )
    try:
        data = _chat_json(prompt, biz_id=note_id, task_type="INTERVIEW_NOTE_SPEAKER_MAP")
        raw_map = data.get("mapping") or {}
        mapping = {int(k): _normalize_role(v) for k, v in raw_map.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("说话人映射失败，按「话多的那个是候选人」兜底：%s", exc)
        mapping = {}

    # 兜底：模型没给出有效映射时，用「谁话多谁是候选人」这个朴素但通常正确的规则
    valid = [k for k, v in mapping.items() if v]
    if len(set(mapping.get(k) for k in valid)) < 2:
        counts = {sid: sum(len(t) for t in texts) for sid, texts in by_speaker.items()}
        interviewer = min(counts, key=lambda k: counts[k])
        mapping = {sid: (ROLE_INTERVIEWER if sid == interviewer else ROLE_ME)
                   for sid in by_speaker}
        logger.info("采用兜底映射（话少的当面试官）：%s", mapping)

    logger.info("说话人映射结果：%s（原编号 %s）", mapping, sorted(by_speaker))
    return mapping


def infer_and_segment_by_llm(
    blocks: list[Utterance], *, note_id: int, reporter: ProgressReporter
) -> list[Utterance]:
    """
    降级路径的核心：没有说话人信息，让大模型**边切句边判角色**。

    为什么切句也要交给大模型：讯飞语音听写的标点恢复会把两个人的话连成
    「你好，请先做一个自我介绍面试官好，我叫张三」这样一条串，
    按标点切根本切不出说话人边界。大模型能看出"请先做一个自我介绍"是提问、
    "面试官好，我叫张三"是回答，从而在正确的位置切开。

    防幻觉：要求模型切分后的文本拼回去与原文一致，并用编辑距离校验（阈值 0.75）。
    不一致就整块退化成"候选人说的"，宁可保守，也不要把编出来的内容写进面经。
    """
    result: list[Utterance] = []
    for index, block in enumerate(blocks, 1):
        reporter.emit(60 + int(10 * index / len(blocks)),
                      f"正在切分并判断说话人 {index}/{len(blocks)}")
        prompt = prompt_service.render("INTERVIEW_NOTE_SEGMENT", text=block.text)
        items: list[dict[str, Any]] = []
        try:
            data = _chat_json(prompt, biz_id=note_id, task_type="INTERVIEW_NOTE_SEGMENT")
            raw_items = data.get("items")
            if isinstance(raw_items, list):
                items = [it for it in raw_items if isinstance(it, dict)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("第 %d 块切分失败，整块按候选人处理：%s", index, exc)

        pieces = [(it.get("text") or "").strip() for it in items]
        pieces = [p for p in pieces if p]
        joined = "".join(pieces)

        if pieces and _similarity(joined, block.text) >= 0.75:
            span = max(1, block.end_ms - block.start_ms)
            total = sum(len(p) for p in pieces) or 1
            cursor = block.start_ms
            for piece, item in zip(pieces, items):
                share = int(span * len(piece) / total)
                result.append(Utterance(
                    seq=len(result) + 1,
                    text=piece,
                    start_ms=cursor,
                    end_ms=cursor + share,
                    speaker_id=0,
                    role=_normalize_role(item.get("role")) or ROLE_FALLBACK,
                ))
                cursor += share
        else:
            if items:
                logger.warning(
                    "第 %d 块切分结果与原文不一致（相似度 %.2f），整块按候选人处理",
                    index, _similarity(joined, block.text) if joined else 0.0,
                )
            result.append(Utterance(
                seq=len(result) + 1,
                text=block.text,
                start_ms=block.start_ms,
                end_ms=block.end_ms,
                speaker_id=0,
                role=ROLE_FALLBACK,
            ))

    logger.info("降级路径切分完成：%d 块 → %d 句", len(blocks), len(result))
    return result


def polish_by_llm(
    utterances: list[Utterance], *, note_id: int, reporter: ProgressReporter
) -> None:
    """去口头禅、修口误。本地清洗已做过一遍，这一步负责"说人话"。"""
    batches = _chunked(utterances, 60)
    for index, batch in enumerate(batches, 1):
        reporter.emit(72 + int(10 * index / len(batches)),
                      f"正在清洗口语 {index}/{len(batches)}")
        lines = "\n".join(
            f"{item.seq}|{_ROLE_NAMES.get(item.role, '?')}|{item.clean_text or item.text}"
            for item in batch
        )
        prompt = prompt_service.render("INTERVIEW_NOTE_POLISH", lines=lines)
        try:
            data = _chat_json(prompt, biz_id=note_id, task_type="INTERVIEW_NOTE_POLISH")
            for entry in data.get("items") or []:
                try:
                    seq = int(entry.get("seq"))
                except (TypeError, ValueError):
                    continue
                target = next((u for u in batch if u.seq == seq), None)
                if target is None:
                    continue
                polished = (entry.get("cleanText") or "").strip()
                # 模型偶尔会把句子清空或大改。清空可以接受，
                # 但如果清完只剩一两个字，多半是幻觉，保留本地清洗结果更稳。
                if polished and len(polished) >= max(2, len(target.clean_text or target.text) // 4):
                    target.clean_text = polished
                elif not polished:
                    target.clean_text = ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("第 %d 批口语清洗失败，保留本地清洗结果：%s", index, exc)


def _is_question(text_value: str) -> bool:
    if not text_value:
        return False
    if text_value.rstrip().endswith(("？", "?")):
        return True
    # 用 `in` 而不是 startswith：真实转写里常带前缀，
    # "请你介绍一下这个项目的难点" 以 startswith 判断会漏掉。
    markers = ("介绍一下", "说说", "讲讲", "谈谈", "聊一下", "为什么", "怎么", "如何",
               "什么是", "有没有", "能不能", "是否", "举个例子", "你了解", "你来", "你负责")
    return any(m in text_value for m in markers)


# 问题分类：先用关键词粗判，够前端做筛选了；
# 更细的分类由大模型在 questions_json 的 category 里给出。
_QUESTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("INTRO", ("自我介绍", "介绍一下你自己", "介绍下自己")),
    ("ALGO", ("算法", "复杂度", "时间复杂度", "手写", "排序", "链表", "二叉树", "动态规划")),
    ("PROJECT", ("项目", "你做的", "负责", "这块", "业务")),
    ("SCENARIO", ("如果", "假设", "线上", "故障", "怎么设计", "如何设计", "方案")),
    ("REVERSE", ("你有什么想问", "反问", "想问我们")),
]


def classify_question(text_value: str) -> str:
    for label, keywords in _QUESTION_RULES:
        if any(keyword in text_value for keyword in keywords):
            return label
    return "TECH" if _is_question(text_value) else "OTHER"


def build_note(
    utterances: list[Utterance],
    *,
    note_id: int,
    company: str,
    position: str,
    reporter: ProgressReporter,
) -> dict[str, Any]:
    """生成面经正文、问题清单与经验点。长文本按角色拼成对话稿，超长则截断。"""
    reporter.emit(85, "正在生成面经")
    transcript_lines: list[str] = []
    for item in utterances:
        content = item.clean_text or item.text
        if not content:
            continue
        stamp = f"[{item.start_ms // 1000 // 60:02d}:{item.start_ms // 1000 % 60:02d}]"
        transcript_lines.append(f"{stamp} {_ROLE_NAMES.get(item.role, '?')}：{content}")
    transcript = "\n".join(transcript_lines)

    # 一份面试记录动辄上万字，超长会让模型丢细节，这里按上限截断并明确告知
    limit = 24000
    if len(transcript) > limit:
        logger.info("面试记录 %d 字，超出单次上限，截断到 %d 字", len(transcript), limit)
        transcript = transcript[:limit] + "\n……（后文因长度限制省略）"

    prompt = prompt_service.render(
        "INTERVIEW_NOTE_SUMMARY",
        company=company or "（未填写）",
        position=position or "（未填写）",
        transcript=transcript,
    )
    data = _chat_json(prompt, biz_id=note_id, task_type="INTERVIEW_NOTE_SUMMARY")
    return {
        "title": (data.get("title") or "").strip(),
        "summary": (data.get("summary") or "").strip()[:600],
        "questions": data.get("questions") or [],
        "highlights": data.get("highlights") or [],
        "content": data.get("content") or "",
    }


# ---------------------------------------------------------------------------
#  数据库
# ---------------------------------------------------------------------------

def _load_note(note_id: int) -> dict[str, Any]:
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, title, company, position, file_name, file_path, file_type "
                "FROM bb_interview_note WHERE id = :id"
            ),
            {"id": note_id},
        ).fetchone()
    if row is None:
        raise ValueError(f"面经记录不存在：#{note_id}")
    return {
        "id": row[0], "title": row[1], "company": row[2], "position": row[3],
        "fileName": row[4], "filePath": row[5], "fileType": row[6],
    }


def _update_note(note_id: int, **fields: Any) -> None:
    if not fields:
        return
    params: dict[str, Any] = {"id": note_id}
    assignments: list[str] = []
    for key, value in fields.items():
        column = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        assignments.append(f"`{column}` = :{key}")
        params[key] = value
    # JSON 列要传字符串，否则驱动会报类型错误
    for key in ("rawJson", "questionsJson", "highlightsJson"):
        if key in params and params[key] is not None and not isinstance(params[key], str):
            params[key] = json.dumps(params[key], ensure_ascii=False)
    with get_engine().begin() as conn:
        conn.execute(
            text(f"UPDATE bb_interview_note SET {', '.join(assignments)} WHERE id = :id"),
            params,
        )


def _save_turns(note_id: int, utterances: list[Utterance]) -> None:
    keep = [u for u in utterances if (u.clean_text or u.text).strip()]
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM bb_interview_note_turn WHERE note_id = :id"), {"id": note_id})
        for item in keep:
            conn.execute(
                text(
                    "INSERT INTO bb_interview_note_turn "
                    "(note_id, seq, role, start_ms, end_ms, raw_text, clean_text, removed_words, question_type) "
                    "VALUES (:note_id, :seq, :role, :start_ms, :end_ms, :raw_text, :clean_text, :removed_words, :question_type)"
                ),
                {
                    "note_id": note_id,
                    "seq": item.seq,
                    "role": item.role or ROLE_FALLBACK,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "raw_text": item.text,
                    "clean_text": item.clean_text,
                    "removed_words": item.removed_words[:300],
                    "question_type": item.question_type,
                },
            )
    logger.info("面经 #%s 已保存 %d 条对话", note_id, len(keep))


# ---------------------------------------------------------------------------
#  主流水线
# ---------------------------------------------------------------------------

def _absolute_path(stored: str) -> Path:
    """上传目录里的相对路径 → 绝对路径。"""
    from app.config import get_settings

    settings = get_settings()
    root = Path(settings.upload_dir)
    candidate = Path(stored)
    return candidate if candidate.is_absolute() else root / stored


def _make_reporter(emit: EmitFn, note_id: int) -> ProgressReporter:
    """
    进度双写：既推 SSE（前端实时看），也写数据库（刷新页面还能看到）。

    为什么值得多这一步：面经是全项目最慢的一条流水线 —— 等讯飞转写要十几分钟，
    期间浏览器可能刷新、网络可能抖动。SSE 一断，如果进度只存在于内存里，
    用户看到的就是"卡在 45% 不动了"，只能重来。写库之后进度是持久的。

    写库按 2 秒节流，避免转写轮询期间频繁 UPDATE。
    """
    reporter = ProgressReporter(emit)
    original = reporter.emit
    state = {"at": 0.0, "progress": -1}

    def emit_and_persist(progress: int, stage: str = "") -> None:
        original(progress, stage)
        now = time.time()
        if progress == state["progress"] and stage == "":
            return
        if now - state["at"] < 2.0 and progress < 100:
            return
        state["at"] = now
        state["progress"] = progress
        try:
            _update_note(note_id, progress=progress, stage=(stage or "")[:120])
        except Exception as exc:  # noqa: BLE001
            logger.warning("写面经进度失败（不影响主流程）：%s", exc)

    reporter.emit = emit_and_persist  # type: ignore[method-assign]
    return reporter


def run_generate_note(payload: dict[str, Any], emit: EmitFn) -> None:
    """
    Java 侧建好 bb_interview_note 记录后调用这里。

    payload: noteId, filePath（相对上传目录）, fileName, company, position
    """
    note_id = int(payload.get("noteId") or 0)
    if not note_id:
        raise ValueError("缺少 noteId")

    reporter = _make_reporter(emit, note_id)
    note = _load_note(note_id)
    relative = payload.get("filePath") or note["filePath"]
    if not relative:
        raise ValueError("面经记录没有关联音频文件")

    audio_path = _absolute_path(relative)
    if not audio_path.exists():
        raise ValueError(f"音频文件不存在：{audio_path}")

    logger.info("开始面经流水线 #%s 文件=%s", note_id, audio_path)
    _update_note(note_id, status=NOTE_STATUS_TRANSCRIBING, progress=2, stage="准备中", errorMsg="")

    duration_ms = _audio_duration_ms(audio_path)
    if duration_ms and duration_ms < 2000:
        raise ValueError(f"音频只有 {duration_ms} 毫秒，太短了，请上传完整的面试录音")
    reporter.emit(5, f"音频时长约 {duration_ms / 1000 / 60:.1f} 分钟，开始转写")

    engine = ""
    role_source = ""
    utterances: list[Utterance] = []
    lfasr_note = ""

    # ---- 1. 转写：优先 LFASR，失败自动降级 ----
    lfasr_credentials = resolve_lfasr_credentials()
    if lfasr_credentials:
        try:
            utterances = transcribe_with_lfasr(audio_path, lfasr_credentials, reporter=reporter)
            engine = "LFASR"
            role_source = "LFASR"
        except LfasrUnavailable as exc:
            logger.warning("语音转写不可用，降级为语音听写：%s", exc)
            lfasr_note = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("语音转写异常，降级为语音听写")
            lfasr_note = f"{type(exc).__name__}: {exc}"
    else:
        lfasr_note = ("没有找到【语音转写】的专用凭据（讯飞每个服务的 APIKey/APISecret 是独立的）。"
                      "到「AI 配置」里新增一条 ASR 能力、厂商选「讯飞语音转写」的配置即可启用。")
        logger.info("未配置语音转写凭据，直接使用语音听写降级模式")

    if not utterances:
        reporter.emit(5, "使用语音听写模式（无说话人分离）")
        utterances = transcribe_with_iat(audio_path, reporter=reporter)
        engine = "IAT"
        role_source = "LLM"

    if not utterances:
        raise ValueError(
            "没有从音频里识别出任何文字。请确认录音里有人说话、音量正常，"
            "且格式是 mp3/wav/m4a/flac/opus 之一。"
        )

    _update_note(
        note_id,
        status=NOTE_STATUS_TRANSCRIBED,
        progress=55,
        stage=f"转写完成，共 {len(utterances)} 句",
        engine=engine,
        roleSource=role_source,
        durationMs=duration_ms,
        speakerCount=len({u.speaker_id for u in utterances}),
        rawJson=[{
            "seq": u.seq, "text": u.text, "startMs": u.start_ms,
            "endMs": u.end_ms, "speaker": u.speaker_id,
        } for u in utterances],
    )

    # ---- 2. 角色判定 ----
    if role_source == "LFASR":
        # 引擎已经切好句并给出说话人编号，只需要把编号映射到"面试官/我"
        mapping = map_speakers_by_llm(utterances, note_id=note_id, reporter=reporter)
        for item in utterances:
            item.role = mapping.get(item.speaker_id) or ROLE_FALLBACK
    else:
        # 降级路径：没有说话人信息，而且标点也不可靠，
        # 所以这一步同时负责「切句」和「判角色」，会返回新的句子列表
        utterances = infer_and_segment_by_llm(utterances, note_id=note_id, reporter=reporter)

    for item in utterances:
        if item.role == ROLE_INTERVIEWER:
            item.question_type = classify_question(item.text)

    # ---- 3. 本地清洗（确定性，先做） ----
    for item in utterances:
        cleaned, removed = clean_text_locally(item.text)
        item.clean_text = cleaned
        item.removed_words = "/".join(removed)[:300]

    # ---- 4. 大模型润色 ----
    polish_by_llm(utterances, note_id=note_id, reporter=reporter)

    # 清洗后为空的句子直接丢掉，否则前端会看到一排空行
    utterances = [u for u in utterances if (u.clean_text or "").strip()]
    if not utterances:
        raise ValueError("清洗后没有剩下有效内容，可能是录音质量太差或几乎没人说话")
    # 重新编号，保证 seq 连续
    for index, item in enumerate(utterances, 1):
        item.seq = index

    _update_note(note_id, status=NOTE_STATUS_SUMMARIZING, progress=82,
                 stage="正在生成面经", turnCount=len(utterances))

    # ---- 5. 生成面经 ----
    result = build_note(
        utterances, note_id=note_id,
        company=note["company"] or "", position=note["position"] or "",
        reporter=reporter,
    )

    questions = result["questions"]
    if not isinstance(questions, list):
        questions = []

    title = result["title"] or _default_title(note)
    _save_turns(note_id, utterances)
    _update_note(
        note_id,
        status=NOTE_STATUS_DONE,
        progress=100,
        stage="已完成",
        title=title[:200],
        summary=result["summary"],
        content=result["content"],
        questionsJson=questions,
        highlightsJson=result["highlights"] if isinstance(result["highlights"], list) else [],
        turnCount=len(utterances),
        questionCount=sum(1 for u in utterances if u.role == ROLE_INTERVIEWER),
        errorMsg="",
    )

    logger.info(
        "面经 #%s 完成：引擎=%s 角色来源=%s 句数=%d 问题数=%d",
        note_id, engine, role_source, len(utterances), len(questions),
    )
    emit("done", {
        "noteId": note_id,
        "title": title,
        "engine": engine,
        "roleSource": role_source,
        "turnCount": len(utterances),
        "questionCount": len(questions),
        "durationMs": duration_ms,
        "degraded": role_source != "LFASR",
        "degradeReason": lfasr_note,
    })


def _default_title(note: dict[str, Any]) -> str:
    company = note["company"] or "面试"
    position = note["position"] or ""
    stamp = time.strftime("%m-%d")
    return f"{company}{position}面经（{stamp}）".strip()

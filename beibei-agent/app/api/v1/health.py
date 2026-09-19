"""
背备不悲 · 环境自检

`GET /api/v1/health` 一次性检查 8 项，每项可独立降级：
  core  ：MySQL、Milvus         —— 失败则文档入库/出题不可用
  optional：ffmpeg、磁盘、向量模型、OCR、LLM、ASR —— 失败只影响对应功能

前端首页的「环境自检」面板直接消费这个接口。
"""

from __future__ import annotations

import importlib.util
import shutil
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Query

from app.config import get_settings
from app.core.logging import get_logger
from app.db import milvus, mysql
from app.schemas.common import HealthCheck, HealthReport
from app.services.asr import resolve_xfyun_credentials
from app.services.llm import LlmError, llm_client

logger = get_logger(__name__)
router = APIRouter(tags=["健康检查"])


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
#  各检查项
# ---------------------------------------------------------------------------

def _check_mysql() -> HealthCheck:
    h = mysql.health()
    if h.get("ok"):
        return HealthCheck(
            key="mysql", name="MySQL 业务库", ok=True, level="core",
            detail=f"{h.get('version')} · {h.get('tableCount')}/{h.get('expectedCount')} 张表",
            extra={"host": h.get("host"), "database": h.get("database")},
        )
    return HealthCheck(
        key="mysql", name="MySQL 业务库", ok=False, level="core",
        error=h.get("error") or f"缺少表: {', '.join(h.get('missingTables', []))}",
        hint=h.get("hint", ""),
        extra={"host": h.get("host"), "tableCount": h.get("tableCount", 0),
               "missingTables": h.get("missingTables", [])},
    )


def _check_milvus() -> HealthCheck:
    h = milvus.health()
    if h.get("ok"):
        hybrid = h.get("hybridSearch")
        return HealthCheck(
            key="milvus", name="Milvus 向量库", ok=True, level="core",
            detail=f"集合 {h.get('chunkCollection')} · 混合检索{'开启' if hybrid else '未开启（纯稠密）'}",
            extra={"uri": h.get("uri"), "collections": h.get("collections", []),
                   "chunkCollectionExists": h.get("chunkCollectionExists", False),
                   "hybridSearch": bool(hybrid)},
        )
    return HealthCheck(
        key="milvus", name="Milvus 向量库", ok=False, level="core",
        error=h.get("error", ""), hint=h.get("hint", ""), extra={"uri": h.get("uri")},
    )


def _check_ffmpeg() -> HealthCheck:
    settings = get_settings()
    path = shutil.which(settings.ffmpeg_path)
    if path:
        return HealthCheck(key="ffmpeg", name="ffmpeg（语音转码）", ok=True,
                           detail=path, extra={"path": path})
    return HealthCheck(
        key="ffmpeg", name="ffmpeg（语音转码）", ok=False,
        error="未找到 ffmpeg 可执行文件",
        hint="语音转文字依赖它把浏览器录制的 webm/opus 转成 16k PCM。未安装时语音输入不可用，其余功能正常",
    )


def _check_embedding() -> HealthCheck:
    settings = get_settings()
    has_torch = _module_available("torch")
    has_st = _module_available("sentence_transformers")
    if not (has_torch and has_st):
        missing = [n for n, ok in (("torch", has_torch), ("sentence-transformers", has_st)) if not ok]
        return HealthCheck(
            key="embedding", name="向量模型", ok=False,
            error=f"缺少依赖: {', '.join(missing)}",
            hint="执行 pip install -r requirements-ai.txt 安装（约 4~6 GB，先确认 HF_HOME 指向 D 盘）",
        )

    try:
        from app.services.embedding import embedding_service

        info = embedding_service.health(quick=True)
    except Exception as exc:  # noqa: BLE001
        return HealthCheck(key="embedding", name="向量模型", ok=False,
                           error=f"{type(exc).__name__}: {exc}")

    if not info.get("ok"):
        return HealthCheck(
            key="embedding", name="向量模型", ok=False,
            error=info.get("error", "未知错误"),
            hint="首次使用需要下载 BGE-M3 权重（约 2.3 GB），已配 hf-mirror 镜像",
            extra=info,
        )

    detail = f"{info['model']} (dim={info.get('configuredDim')})"
    if info.get("gpu"):
        detail += f" · GPU {info['gpu']} {info.get('vramGb', '')}GB"
    elif info.get("cudaAvailable") is False:
        detail += " · 仅 CPU（未检测到可用 CUDA）"
    if info.get("pending"):
        detail += " · 尚未加载"

    return HealthCheck(key="embedding", name="向量模型", ok=True, detail=detail, extra=info)


def _check_ocr() -> HealthCheck:
    has_paddle = _module_available("paddle")
    has_ocr = _module_available("paddleocr")
    if has_paddle and has_ocr:
        try:
            import paddle  # noqa: PLC0415

            return HealthCheck(key="ocr", name="OCR（照片识别）", ok=True,
                               detail=f"PaddleOCR · paddle {paddle.__version__}",
                               extra={"device": "cpu"})
        except Exception:  # noqa: BLE001
            return HealthCheck(key="ocr", name="OCR（照片识别）", ok=True, detail="PaddleOCR 已安装")
    missing = [n for n, ok in (("paddlepaddle", has_paddle), ("paddleocr", has_ocr)) if not ok]
    return HealthCheck(
        key="ocr", name="OCR（照片识别）", ok=False,
        error=f"缺少依赖: {', '.join(missing)}",
        hint="照片识别上传依赖它。未安装时文字类文档上传不受影响",
    )


def _check_llm(*, probe: bool) -> HealthCheck:
    """
    自检「实际会用哪个模型」。

    ⚠️ 这里**不能**只看 .env 的 DEEPSEEK_API_KEY。
    运行时的 Key 存在 MySQL 的 bb_ai_provider 里（前端「AI 配置」填的、AES 加密存的），
    .env 只是数据库没配时的兜底。只查 .env 会在「Key 配在数据库里」时
    误报「未配置 API Key」—— 而这恰恰是最容易让人以为「AI 没接上」的那种报错。
    所以统一走 llm_client.resolve_provider()，和真正调用时用的是同一套解析逻辑。
    """
    settings = get_settings()

    if settings.llm_mock:
        return HealthCheck(
            key="llm", name="大模型", ok=True,
            detail="Mock 演示模式（本地规则法，不联网）· 出题/判分/面试链路可跑通",
            hint="配好 API Key 后把 beibei-agent/.env 里的 LLM_MOCK 改成 false 即可切到真实模型",
            extra={"provider": "mock", "mock": True},
        )

    try:
        provider = llm_client.resolve_provider("")
    except LlmError as exc:
        return HealthCheck(
            key="llm", name="大模型", ok=False,
            error=str(exc),
            hint="在「设置 → AI 配置」里添加厂商并填写 API Key 并设为启用；"
                 "或把 beibei-agent/.env 的 LLM_MOCK 改回 true 用本地 Mock",
        )
    except Exception as exc:  # noqa: BLE001
        return HealthCheck(key="llm", name="大模型", ok=False,
                           error=f"{type(exc).__name__}: {exc}")

    extra = {
        "providerId": provider.id,
        "providerName": provider.name,
        "vendor": provider.vendor,
        "model": provider.model,
        "baseUrl": provider.base_url,
    }

    if not probe:
        return HealthCheck(
            key="llm", name="大模型", ok=True,
            detail=f"{provider.name} · {provider.model} · Key 已配置（未实测）",
            hint="想看真实连通性，用 GET /api/v1/health?probe_llm=true",
            extra=extra,
        )

    # 真实探测：拿实际要用的那家厂商发一条最小请求
    try:
        resp = httpx.post(
            provider.chat_url,
            headers={"Authorization": f"Bearer {provider.api_key}",
                     "Content-Type": "application/json"},
            json={"model": provider.model,
                  "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 1, "stream": False},
            timeout=20.0,
        )
        if resp.status_code == 200:
            return HealthCheck(key="llm", name="大模型", ok=True,
                               detail=f"{provider.name} · {provider.model} · 连通正常",
                               extra={**extra, "statusCode": 200})
        return HealthCheck(key="llm", name="大模型", ok=False,
                           error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                           hint="检查 API Key 是否有效、账户是否有余额", extra=extra)
    except Exception as exc:  # noqa: BLE001
        return HealthCheck(key="llm", name="大模型", ok=False,
                           error=f"{type(exc).__name__}: {exc}",
                           hint=f"检查网络能否访问 {provider.base_url}", extra=extra)


def _check_asr() -> HealthCheck:
    """
    自检讯飞凭据。

    和 _check_llm 同理：**不能只看 .env**。讯飞要三个值（APPID/APIKey/APISecret），
    现在也支持在前端「AI 配置」里配，所以统一走 resolve_xfyun_credentials()，
    并在 detail 里把「凭据从哪来的」写清楚 ——
    否则用户会搞不清自己填的到底生效了没。
    """
    cred = resolve_xfyun_credentials()
    if cred.complete:
        return HealthCheck(
            key="asr", name="语音转文字（讯飞）", ok=True,
            detail=f"凭据已配置 · 来源：{cred.source}（未实测）",
            hint="想验证真实识别效果，跑 python scripts/test_asr.py",
            extra={"provider": "xfyun", "source": cred.source,
                   "endpoint": (cred.base_url or "默认 iat-api.xfyun.cn"),
                   "appId": cred.app_id[:6] + "****" if len(cred.app_id) > 6 else "****"},
        )
    return HealthCheck(
        key="asr", name="语音转文字（讯飞）", ok=False,
        error="未配置讯飞凭据（需要 APPID / APIKey / APISecret 三个值）",
        hint="前端「设置 → AI 配置」里填讯飞语音听写的三个值并启用；"
             "或改 beibei-agent/.env。未配置时答题页会隐藏录音按钮，打字作答不受影响",
    )


def _check_disk() -> HealthCheck:
    settings = get_settings()
    target = Path(settings.upload_dir)
    probe = target if target.exists() else Path(target.anchor or "C:/")
    try:
        probe.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(probe)
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        ok = free_gb > 5
        return HealthCheck(
            key="disk", name=f"磁盘空间（{probe.drive or probe}）", ok=ok,
            detail=f"剩余 {free_gb:.1f} GB / 共 {total_gb:.1f} GB",
            error="" if ok else f"剩余不足 5 GB（当前 {free_gb:.1f} GB）",
            hint="" if ok else "模型权重与上传资料建议放在空间更大的盘",
            extra={"freeGb": round(free_gb, 1), "totalGb": round(total_gb, 1),
                   "uploadDir": str(target)},
        )
    except Exception as exc:  # noqa: BLE001
        return HealthCheck(key="disk", name="磁盘空间", ok=False,
                           error=f"{type(exc).__name__}: {exc}",
                           hint=f"上传目录 {settings.upload_dir} 不可写")


# ---------------------------------------------------------------------------
#  接口
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthReport, summary="环境自检（8 项）")
def health(probe_llm: bool = Query(default=False, description="是否真实调用一次 DeepSeek 验证 Key")) -> HealthReport:
    settings = get_settings()

    checks = [
        _check_mysql(),
        _check_milvus(),
        _check_disk(),
        _check_embedding(),
        _check_ocr(),
        _check_ffmpeg(),
        _check_llm(probe=probe_llm),
        _check_asr(),
    ]

    core_checks = [c for c in checks if c.level == "core"]
    core_ok = all(c.ok for c in core_checks)

    logger.info(
        "环境自检: core=%s, 通过 %d/%d 项",
        "OK" if core_ok else "FAIL",
        sum(1 for c in checks if c.ok),
        len(checks),
    )

    return HealthReport(
        ok=core_ok,
        coreOk=core_ok,
        checkedAt=datetime.now().isoformat(timespec="seconds"),
        checks=checks,
    )


@router.get("/health/ping", summary="极简存活探测（Java 侧心跳用）")
def ping() -> dict[str, object]:
    settings = get_settings()
    return {
        "pong": True,
        "service": "beibei-agent",
        "version": settings.__class__.__name__ and "0.1.0",
        "milvusCollection": settings.chunk_collection,
    }

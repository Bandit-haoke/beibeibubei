"""背备不悲 · 语音转文字接口"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.security import verify_internal_token
from app.services.asr import (
    AsrUnavailable,
    correct_hotwords,
    hotwords_for_kb,
    load_provider_credentials,
    probe_xfyun_credentials,
    resolve_xfyun_credentials,
    transcribe,
)

logger = get_logger(__name__)
router = APIRouter(tags=["语音"])


@router.post("/asr", summary="语音转文字")
async def asr_endpoint(
    audio: UploadFile = File(..., description="浏览器录制的音频（webm/opus 或 wav）"),
    kbId: int | None = Form(default=None, description="知识库 ID，用于加载专有名词热词表"),
    applyHotwords: bool = Form(default=True),
    micLabel: str = Form(default="", description="前端上报的麦克风设备名，用于排查「录到静音」"),
    _: None = Depends(verify_internal_token),
) -> dict[str, Any]:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="音频文件为空")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频超过 20 MB，请缩短录音时长")

    try:
        result = await transcribe(
            data,
            filename=audio.filename or "audio.webm",
            kb_id=kbId,
            apply_hotwords=applyHotwords,
            mic_label=micLabel,
        )
    except AsrUnavailable as exc:
        # 返回 200 + 结构化失败体，而不是 503。
        # 原因：Java 侧 AgentClient 对非 200 是走异常分支的，拿不到响应体，
        # 于是讯飞的真实错误码（10114 / 11200 …）会在中转时丢掉，
        # 前端只能显示一句笼统的「语音不可用」—— 排查时两眼一抹黑。
        # 走 200 之后 error / hint / permanent 能一路透到界面上。
        logger.warning("语音转文字失败（permanent=%s）：%s", exc.permanent, exc)
        return {
            "ok": False,
            "asrUnavailable": True,
            "permanent": exc.permanent,
            "text": "",
            "error": str(exc),
            "hint": "可以改用打字作答；如果反复失败，把这条错误信息发给开发者",
        }

    return {"ok": True, **result}


class CorrectRequest(BaseModel):
    text: str
    kbId: int | None = None


class ProbeRequest(BaseModel):
    """凭据探测。providerId 指定测哪条厂商配置（不看 enabled），留空则测当前生效的。"""

    providerId: int | None = None


@router.post("/asr/probe", summary="讯飞凭据探测（真机握手，验证三个值）")
async def probe_endpoint(
    req: ProbeRequest | None = None, _: None = Depends(verify_internal_token)
) -> dict[str, Any]:
    """
    「测试连通」按钮的 ASR 分支落到这里。

    为什么要真机握手：讯飞是**三个值**一起决定成败的，
    填错一个（尤其是 APISecret）只有握手才知道。
    单纯检查「字段非空」或者 ping 端口都发现不了。

    握手成功后立刻断开，不消耗识别调用量。
    """
    provider_id = req.providerId if req else None
    cred = (load_provider_credentials(provider_id) if provider_id
            else resolve_xfyun_credentials())
    return {**await probe_xfyun_credentials(cred)}


@router.post("/asr/correct-hotwords", summary="热词纠错（调试用，不需要 ASR 凭据）")
def correct_endpoint(req: CorrectRequest, _: None = Depends(verify_internal_token)) -> dict[str, Any]:
    """
    单独暴露热词纠错，便于在没有 ASR 凭据时验证纠错效果，
    也方便排查「识别结果里某个专有名词老是错」的问题。
    """
    hotwords = hotwords_for_kb(req.kbId)
    fixed, fixes = correct_hotwords(req.text, hotwords)
    return {
        "ok": True,
        "original": req.text,
        "corrected": fixed,
        "fixes": fixes,
        "hotwordCount": len(hotwords),
    }


@router.get("/asr/hotwords", summary="查看当前热词表")
def hotwords_endpoint(kbId: int | None = None, _: None = Depends(verify_internal_token)) -> dict[str, Any]:
    words = hotwords_for_kb(kbId)
    return {"ok": True, "count": len(words), "hotwords": words}

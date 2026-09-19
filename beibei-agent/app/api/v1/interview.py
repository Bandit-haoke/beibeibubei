"""背备不悲 · AI 模拟面试接口

接口分工：
  - `/resume-parse`   简历解析（慢，走 SSE，Java 侧建异步任务）
  - `/interview/start`   开始面试、拿第一题（一次 LLM 调用，同步返回）
  - `/interview/answer`  提交一轮回答（评分 + 追问，同步返回）
  - `/interview/finish`  出整场评估报告（同步返回）

为什么后三个不做 SSE：一轮就是一次 LLM 调用，几秒钟的事。
进度条对「一次网络请求」没有意义，反而让前端状态机复杂一倍。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.core.security import verify_internal_token
from app.core.sse import stream_from_worker
from app.services.interview import (
    finish_interview,
    run_parse_resume,
    start_interview,
    submit_answer,
)
from app.services.llm import LlmError

logger = get_logger(__name__)

router = APIRouter(tags=["模拟面试"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class ResumeParseRequest(BaseModel):
    taskId: int = 0
    resumeId: int
    textContent: str | None = Field(default=None, description="手动粘贴的简历文字，优先于文件")
    ocrEnabled: bool = True


class StartRequest(BaseModel):
    interviewId: int


class AnswerRequest(BaseModel):
    interviewId: int
    answer: str = ""


class FinishRequest(BaseModel):
    interviewId: int
    # Java 侧可选指定用哪家模型出报告，留空走任务路由
    providerId: int = 0


@router.post("/resume-parse", summary="解析简历并抽取结构化档案（SSE 推进度）")
async def resume_parse(
    req: ResumeParseRequest, _: None = Depends(verify_internal_token)
) -> StreamingResponse:
    payload = req.model_dump()
    return StreamingResponse(
        stream_from_worker(lambda emit: run_parse_resume(payload, emit)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _guard(action, payload: dict) -> dict:
    """
    把业务异常转成 `{"ok": false, "error": "..."}` 的 200 响应。

    为什么不抛 HTTP 500：Java 侧统一走 postSafe，它只在非 200 时才拿到异常文本，
    拼出来的提示会变成 `500 Internal Server Error: {"code":500,...}` 这种没法看的字符串。
    直接在响应体里给 ok/error，Java 只判断 ok，错误文案就能原样透到前端。
    """
    try:
        return {"ok": True, **action(payload)}
    except ValueError as exc:
        logger.warning("模拟面试业务校验失败：%s", exc)
        return {"ok": False, "error": str(exc)}
    except LlmError as exc:
        logger.warning("模拟面试模型调用失败：%s", exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("模拟面试接口异常")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.post("/interview/start", summary="开始一场模拟面试，返回第一题")
def interview_start(req: StartRequest, _: None = Depends(verify_internal_token)) -> dict:
    return _guard(start_interview, {"interviewId": req.interviewId})


@router.post("/interview/answer", summary="提交一轮回答：评分并追问下一题")
def interview_answer(req: AnswerRequest, _: None = Depends(verify_internal_token)) -> dict:
    return _guard(submit_answer, {"interviewId": req.interviewId, "answer": req.answer})


@router.post("/interview/finish", summary="结束面试并生成评估报告")
def interview_finish(req: FinishRequest, _: None = Depends(verify_internal_token)) -> dict:
    return _guard(finish_interview, {"interviewId": req.interviewId})

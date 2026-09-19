"""
背备不悲 · SSE 工具

把「同步的耗时流水线」包装成「异步的 SSE 响应流」。

做法：起一个子线程跑流水线，流水线通过 emit(event, data) 回调推进
asyncio 队列，主协程从队列取事件写成 SSE 文本。

这样流水线代码可以完全写成同步风格（PyMuPDF、sentence-transformers、
pymilvus 都是同步阻塞的），不需要为了 SSE 把整条链路改造成 async。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

END_MARKER = "__END__"

EmitFn = Callable[[str, dict[str, Any]], None]


def sse_line(event: str, data: dict[str, Any]) -> str:
    """拼一个 SSE 报文。ensure_ascii=False 让中文在调试时肉眼可读。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_from_worker(work: Callable[[EmitFn], None]) -> AsyncIterator[str]:
    """
    执行 work（在子线程），把它 emit 的事件转成 SSE 文本流。

    work 抛异常时自动补发一个 error 事件，保证前端不会一直等下去。
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

    def emit(event: str, data: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    async def runner() -> None:
        try:
            await asyncio.to_thread(work, emit)
        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE 工作线程异常")
            emit("error", {"errorMsg": f"{type(exc).__name__}: {exc}"})
        finally:
            emit(END_MARKER, {})

    task = asyncio.create_task(runner())
    try:
        while True:
            event, data = await queue.get()
            if event == END_MARKER:
                break
            yield sse_line(event, data)
    finally:
        await task


class ProgressReporter:
    """把「第 X/Y 步」换算成百分比，避免流水线里到处手写进度数字。"""

    def __init__(self, emit: EmitFn, *, start: int = 0, end: int = 100) -> None:
        self._emit = emit
        self._start = start
        self._end = end
        self._last = -1

    def report(self, ratio: float, stage: str) -> None:
        ratio = max(0.0, min(1.0, ratio))
        progress = int(self._start + (self._end - self._start) * ratio)
        self.emit(progress, stage)

    def emit(self, progress: int, stage: str) -> None:
        progress = max(0, min(100, progress))
        if progress == self._last and stage == "":
            return
        self._last = progress
        self._emit("progress", {"progress": progress, "stage": stage})

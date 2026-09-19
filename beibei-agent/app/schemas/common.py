"""背备不悲 · 通用数据结构"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """与 Java 侧 Result<T> 对齐的统一响应体。"""

    code: int = 0
    msg: str = "ok"
    data: T | None = None


class HealthCheck(BaseModel):
    key: str = Field(description="检查项标识")
    name: str = Field(description="展示名")
    ok: bool = Field(description="是否通过")
    level: str = Field(default="optional", description="core 表示核心（失败则主流程不可用），optional 表示可降级")
    detail: str = Field(default="", description="通过时的说明")
    error: str = Field(default="", description="失败原因")
    hint: str = Field(default="", description="修复建议")
    extra: dict[str, Any] = Field(default_factory=dict, description="附加信息")


class HealthReport(BaseModel):
    ok: bool = Field(description="全部 core 检查是否通过")
    coreOk: bool = Field(description="核心检查是否全部通过")
    checkedAt: str
    checks: list[HealthCheck]

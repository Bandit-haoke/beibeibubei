"""
背备不悲 · 内部调用令牌校验

Java 是唯一对外网关，只有它能调 Python。两边共享 INTERNAL_TOKEN。
Python 只监听 127.0.0.1，所以这个令牌是第二道防线。
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def verify_internal_token(
    x_internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> None:
    """作为依赖使用： Depends(verify_internal_token)"""
    settings = get_settings()

    if not settings.internal_token or settings.internal_token == "change_me":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL_TOKEN 未配置，请检查 beibei-agent/.env",
        )

    if x_internal_token != settings.internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="内部令牌校验失败：请求头 X-Internal-Token 与 Python 侧配置不一致",
        )

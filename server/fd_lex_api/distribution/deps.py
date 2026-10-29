"""分发面鉴权：配置化 token fail-closed（接 Logto/wgk- 客户凭据前的最小骨架）。

与 ``billing/deps.require_internal_token`` 同款语义：
- 未配置 ``DISTRIBUTION_API_TOKEN`` → 403（绝不无鉴权放行）；
- 缺 Bearer / 不匹配 → 401。

后续项（如实标注）：客户级凭据（wgk- 前缀 per-customer key，走 Logto/registry
凭据体系）接入后，本函数换实现即可，路由不动。
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..config import get_settings


async def require_distribution_token(request: Request) -> None:
    """分发面 bearer 校验（fail-closed）。"""
    expected = get_settings().distribution_api_token
    authorization = request.headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token")
    if expected is None or not expected:
        raise HTTPException(
            status_code=403,
            detail="distribution api token not configured (fail-closed)",
        )
    if token.strip() != expected:
        raise HTTPException(status_code=401, detail="invalid distribution token")
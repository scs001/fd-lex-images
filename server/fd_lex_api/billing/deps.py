"""FastAPI 依赖：会话 / sub2api 客户端 / internal bearer 鉴权骨架。

鉴权现状（骨架）：``/internal/*`` 全部走 ``INTERNAL_API_TOKEN`` 的简单
bearer 校验，未配置令牌时 fail-closed（403），绝不无令牌放行；
**接入 Logto 后由此一处收敛**（换 Depends 实现，路由不动）。
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..metering.db import get_db
from .metering_source import SqlMeteringSource
from .sub2api import Sub2ApiClient


# 请求级会话：结束即提交/回滚（转发 metering 的会话依赖）。
get_db_session = get_db


def get_metering_source(db: Session = Depends(get_db_session)) -> SqlMeteringSource:
    """结算/对账的计量读取口：真实 metering_records 表（整月聚合域）。"""
    return SqlMeteringSource(db.get_bind())


def get_sub2api_client() -> Iterator[Sub2ApiClient]:
    """sub2api admin 客户端（请求级；测试经 dependency_overrides 换假件）。"""
    client = Sub2ApiClient()
    try:
        yield client
    finally:
        client.close()


async def require_internal_token(request: Request) -> None:
    """internal 面鉴权：Bearer 令牌与 INTERNAL_API_TOKEN 严格相等；
    未配置令牌即 fail-closed（403）。接 Logto 后在此收敛。"""
    expected = get_settings().internal_api_token
    authorization = request.headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing bearer token")
    if expected is None or not expected:
        raise HTTPException(status_code=403, detail="internal api token not configured")
    if token.strip() != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")

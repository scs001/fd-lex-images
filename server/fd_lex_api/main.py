"""fd-lex API 服务端。

lex-platform-v1（task 5.1+5.2+4.3+4.4）：结算/分发/控制台/后台 API。
本期提供：/healthz 健康检查、/api/version 版本自报、
/internal/metering（双单位计量摄取/消费/查询）、
/internal/billing（结算触发/三方对账/账本/额度状态/套餐配置）、
/api/console（客户控制台：Logto 登录校验/用量/账单/额度/registry 凭据代理）、
/api/admin（运营后台：客户/身份绑定/套餐/账本/用量/凭据留痕）。

路由前缀口径：宿主 Caddy 把 https://lex.finddatatech.cloud/api/* 原样反代到
本服务（不剥 /api），故控制台/后台端点自带 /api 前缀；/internal/* 与 /healthz
仅供集群内部与探针使用。
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fd_lex_api.admin_api.routes import router as admin_router
from fd_lex_api.billing.routes import router as billing_router
from fd_lex_api.config import get_settings
from fd_lex_api.console_api.routes import router as console_router
from fd_lex_api.distribution.routes import router as distribution_router
from fd_lex_api.esignature import console_router as esignature_console_router
from fd_lex_api.esignature import signer_router as esignature_signer_router
from fd_lex_api.metering.routes import router as metering_router


def _init_tables() -> None:
    """开发便利：幂等建 metering_*/billing_*/console_* 表。

    生产迁移链由主代理收敛（alembic 就位后关闭 METERING_AUTO_CREATE_TABLES）。
    """
    if not get_settings().metering_auto_create_tables:
        return
    from fd_lex_api.billing import init_billing
    from fd_lex_api.console_api.models import ensure_console_schema
    from fd_lex_api.esignature.models import ensure_esign_schema
    from fd_lex_api.metering.db import ensure_schema

    ensure_schema()
    init_billing()
    ensure_console_schema()
    ensure_esign_schema()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动钩子：建表（幂等，可经 METERING_AUTO_CREATE_TABLES 关闭）+ 计量驱动。"""
    _init_tables()
    from fd_lex_api.metering.driver import start_metering_driver, stop_metering_driver

    start_metering_driver()
    try:
        yield
    finally:
        stop_metering_driver()


app = FastAPI(
    title="fd-lex-api",
    description="识律(lex) 平台服务端：结算/分发/控制台/后台 API",
    version="0.1.0",
    lifespan=lifespan,
)

# 骨架期 CORS 全开（allow_origins=* 时 credentials 必须为 False）；
# 生产同源（lex 域 /api 反代）不经 CORS；接入 Logto 后按域名收敛 allow_origins。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 内部服务面（计量 + 结算账本）；鉴权骨架见 billing/deps.require_internal_token
app.include_router(metering_router)
app.include_router(billing_router)
# 控制台面（4.3）：Logto ID token 校验 + registry 凭据代理 + 用量/账单/额度
app.include_router(console_router)
# 运营后台面（4.4）：内部令牌或 Logto 管理员角色
app.include_router(admin_router)
# 交付包分发面（6.3）：manifest 列表/详情、pack 流式下载（Range）、sha256 校验
app.include_router(distribution_router)
# 电子签（lex-contract-esignature）：控制台面发起/出证/验证；签署人 H5 面落签
app.include_router(esignature_console_router)
app.include_router(esignature_signer_router)


def _build_version() -> str:
    """构建版本：CI/部署注入 BUILD_VERSION 优先，缺省 dev。"""
    return os.environ.get("BUILD_VERSION") or "dev"


@app.get("/healthz")
def healthz() -> dict:
    """存活探针。"""
    return {"status": "ok"}


@app.get("/api/version")
def version() -> dict:
    """版本自报：镜像 tag / 部署核对用。"""
    return {"service": "fd-lex-api", "version": _build_version()}
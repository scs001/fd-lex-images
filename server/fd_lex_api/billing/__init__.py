"""计费域（lex-billing）：账本权威 + sub2api 幂等结算 + 三方对账 + 两档预警 +
额度状态预检。

（架构照 fd-wire billing 移植；lex 适配=双单位计价（套餐配额表驱动）+
计量流侧对账 + fail-closed 额度状态查询。）

入口一览：
- 建表：`init_billing(engine)`（create_all billing_* 表；套餐数字不预填，
  由 plans.upsert_plan 后台配置——design D8「调价不发版」）
- 开户：`ensure_customer(session, sub2api, name=..., plan_code=...)`
- 结算：`SettlementService(session, sub2api, metering).settle(period, batch_ref)`
- 对账：`reconcile(session, sub2api, metering, period=..., opening_balances=...)`
- 预警：`evaluate_usage_warnings(session, customer=..., unit=..., ...)`
  （settle 内已自动调；本模块只判定与留档，投递是通知通道的事）
- 预检：`quota_status(session, customer, period, metering=..., sub2api=...)`
  （registry 侧硬停 402 的输入，本模块不拦调用）
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .customers import ensure_customer
from .ledger import (
    Ledger,
    RecordResult,
    adjustment_key,
    grant_key,
    grant_unit_key,
    hardstop_key,
    settle_key,
)
from .metering_source import (
    METERING_RECORDS_DDL,
    CUSTOMER_TRACK,
    PLATFORM_TRACK,
    MeteringSource,
    MeteringUsage,
    SqlMeteringSource,
    StaticMeteringSource,
)
from .models import (
    NOTICE_CHANNELS,
    SUB2API_APPLIED_KINDS,
    Base,
    Customer,
    CustomerStatus,
    LedgerEntry,
    LedgerKind,
    NoticeKind,
    NoticeRecord,
    Plan,
    PlanQuota,
    validate_period,
)
from .money import MICRO_PER_YUAN, micro_to_yuan, micro_to_yuan_str, yuan_to_micro
from .notices import USAGE_WARNING_TIERS, evaluate_usage_warnings, threshold_tiers_hit
from .plans import QuotaSpec, get_plan, upsert_plan
from .quota import (
    QuotaStatus,
    UnitQuotaStatus,
    quota_status,
)
from .reconcile import ReconcileReport, ReconcileRow, UnitReconcile, reconcile
from .settle import (
    CustomerSettlement,
    SettlementReport,
    SettlementService,
    UnitSettlement,
    default_resolver,
)
from .sub2api import (
    ProbeResult,
    Sub2ApiClient,
    Sub2ApiError,
    Sub2ApiUnavailable,
    Sub2User,
)

__all__ = [
    "CUSTOMER_TRACK",
    "MICRO_PER_YUAN",
    "METERING_RECORDS_DDL",
    "NOTICE_CHANNELS",
    "PLATFORM_TRACK",
    "SUB2API_APPLIED_KINDS",
    "USAGE_WARNING_TIERS",
    "Base",
    "Customer",
    "CustomerSettlement",
    "CustomerStatus",
    "Ledger",
    "LedgerEntry",
    "LedgerKind",
    "MeteringSource",
    "MeteringUsage",
    "NoticeKind",
    "NoticeRecord",
    "Plan",
    "PlanQuota",
    "ProbeResult",
    "QuotaSpec",
    "QuotaStatus",
    "RecordResult",
    "ReconcileReport",
    "ReconcileRow",
    "SettlementReport",
    "SettlementService",
    "SqlMeteringSource",
    "StaticMeteringSource",
    "Sub2ApiClient",
    "Sub2ApiError",
    "Sub2ApiUnavailable",
    "Sub2User",
    "UnitQuotaStatus",
    "UnitReconcile",
    "UnitSettlement",
    "adjustment_key",
    "default_resolver",
    "ensure_customer",
    "evaluate_usage_warnings",
    "get_plan",
    "grant_key",
    "grant_unit_key",
    "hardstop_key",
    "init_billing",
    "micro_to_yuan",
    "micro_to_yuan_str",
    "quota_status",
    "reconcile",
    "settle_key",
    "threshold_tiers_hit",
    "upsert_plan",
    "validate_period",
    "yuan_to_micro",
]


def init_billing(engine: Engine | None = None, *, session: Session | None = None) -> Engine:
    """建 billing_* 表（幂等）。返回所用 engine。

    注意：不建 `metering_records`（归 metering 模块）；套餐数字不预填
    （design D8），配置走 plans.upsert_plan。迁移链就位前用 create_all
    起步，alembic 版本由主代理统一收敛。
    """
    if engine is None:
        import os

        url = os.getenv("DATABASE_URL") or "sqlite:///./fd_lex_dev.db"
        engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine

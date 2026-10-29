"""控制台身份 → 客户解析与用量读取（metering_records 只读）。

身份映射的现实（v1）：
- metering 的 ``caller`` 是 registry 审计事件里的 ``identity.username``
  （即 Logto username）；billing 侧 v1 用 ``Customer.sub2api_user_id``
  承载计量身份键（见 billing/metering_source.py 的耦合点说明）。
- 两者在真实客户上未必相等（sub2api_user_id 是支付侧 egress 用户 id）。
  故本模块引入 ``console_identity_bindings``：运营后台把客户的 Logto
  身份绑定到 billing Customer 后，控制台按登录身份解析客户与用量；
  未绑定时回落 ``sub2api_user_id == identity``（骨架期兼容路径）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..billing.models import Customer
from ..metering.db import to_utc
from ..metering.models import MeteringRecord
from .models import ConsoleIdentityBinding


def period_bounds(period: str) -> tuple[datetime, datetime]:
    """YYYY-MM → [月初, 次月初) 的 aware UTC 边界（与账本 period 口径一致）。"""
    year = int(period[0:4])
    month = int(period[5:7])
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), (month % 12) + 1, 1)
    return to_utc(start), to_utc(end)


def bindings_for_identity(db: Session, identity: str) -> list[ConsoleIdentityBinding]:
    return list(
        db.execute(
            select(ConsoleIdentityBinding)
            .where(ConsoleIdentityBinding.identity == identity)
            .order_by(ConsoleIdentityBinding.id)
        )
        .scalars()
        .all()
    )


def customer_identities(db: Session, customer: Customer) -> list[str]:
    """一个客户的全部计量身份：绑定行的 identity + sub2api_user_id 回落。"""
    identities = [
        row.identity
        for row in db.execute(
            select(ConsoleIdentityBinding)
            .where(ConsoleIdentityBinding.customer_id == customer.id)
            .order_by(ConsoleIdentityBinding.identity)
        )
        .scalars()
        .all()
    ]
    if customer.sub2api_user_id and customer.sub2api_user_id not in identities:
        identities.append(customer.sub2api_user_id)
    return identities


def resolve_console_customer(db: Session, identity: str) -> Customer | None:
    """登录身份 → 客户：绑定表优先，回落 sub2api_user_id 相等（骨架兼容）。"""
    binding = db.execute(
        select(ConsoleIdentityBinding)
        .where(ConsoleIdentityBinding.identity == identity)
        .order_by(ConsoleIdentityBinding.id)
    ).scalars().first()
    if binding is not None:
        customer = db.get(Customer, binding.customer_id)
        if customer is not None:
            return customer
    return db.execute(
        select(Customer).where(Customer.sub2api_user_id == identity)
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# 用量读取（metering_records 只读；客户轨道才计价）
# ---------------------------------------------------------------------------


def _customer_track_conditions(identities: Iterable[str], period: str):
    start, end = period_bounds(period)
    values = [value for value in identities if value]
    return [
        MeteringRecord.credential_track == "customer",
        MeteringRecord.caller.in_(values or [""]),
        MeteringRecord.event_timestamp >= start,
        MeteringRecord.event_timestamp < end,
    ]


def usage_by_unit(db: Session, identities: Iterable[str], period: str) -> dict[str, int]:
    """按单位聚合数量（计费用；identities 为空返回空表）。"""
    conditions = _customer_track_conditions(identities, period)
    rows = db.execute(
        select(MeteringRecord.unit, func.sum(MeteringRecord.quantity))
        .where(*conditions)
        .group_by(MeteringRecord.unit)
    ).all()
    return {unit: int(quantity or 0) for unit, quantity in rows}


def usage_rows(db: Session, identities: Iterable[str], period: str) -> list[dict]:
    """按（单位×工具×server）聚合调用数与数量（控制台用量明细）。"""
    conditions = _customer_track_conditions(identities, period)
    rows = db.execute(
        select(
            MeteringRecord.unit,
            MeteringRecord.server_name,
            MeteringRecord.tool_name,
            func.count(MeteringRecord.id),
            func.sum(MeteringRecord.quantity),
        )
        .where(*conditions)
        .group_by(MeteringRecord.unit, MeteringRecord.server_name, MeteringRecord.tool_name)
        .order_by(MeteringRecord.unit, MeteringRecord.server_name, MeteringRecord.tool_name)
    ).all()
    return [
        {
            "unit": unit,
            "server_name": server,
            "tool_name": tool,
            "calls": int(calls),
            "quantity": int(quantity or 0),
        }
        for unit, server, tool, calls, quantity in rows
    ]


def usage_totals(db: Session, identities: Iterable[str], period: str) -> dict:
    """合计调用数与按单位数量 + 最近调用（新→旧，最多 20 条）。"""
    conditions = _customer_track_conditions(identities, period)
    total_calls = db.execute(
        select(func.count(MeteringRecord.id)).where(*conditions)
    ).scalar_one()
    recent = (
        db.execute(
            select(MeteringRecord)
            .where(*conditions)
            .order_by(MeteringRecord.event_timestamp.desc(), MeteringRecord.id.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    return {
        "calls": int(total_calls or 0),
        "by_unit": usage_by_unit(db, identities, period),
        "recent": [
            {
                "event_timestamp": record.event_timestamp.isoformat(),
                "server_name": record.server_name,
                "tool_name": record.tool_name,
                "unit": record.unit,
                "quantity": record.quantity,
            }
            for record in recent
        ],
    }


__all__ = [
    "bindings_for_identity",
    "customer_identities",
    "period_bounds",
    "resolve_console_customer",
    "usage_by_unit",
    "usage_rows",
    "usage_totals",
]
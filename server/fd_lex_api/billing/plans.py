"""套餐档位与按单位配额：后台可配的数据，不是代码常量。

design D8 裁决「套餐数字后台可配不预填」：本模块不携带任何默认价格，
只提供幂等的配置读写面（``upsert_plan``）——运营后台（后续任务）调它
即可调价，调价不发版。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Plan, PlanQuota


@dataclass(frozen=True)
class QuotaSpec:
    """一个单位的配额配置。"""

    unit: str
    included_quantity: int = 0
    overage_unit_price_micro: int = 0


def get_plan(session: Session, code: str) -> Plan:
    plan = session.execute(select(Plan).where(Plan.code == code)).scalar_one_or_none()
    if plan is None:
        raise ValueError(f"未知套餐档位: {code!r}")
    return plan


def upsert_plan(
    session: Session,
    *,
    code: str,
    name: str,
    monthly_price_micro: int = 0,
    is_active: bool = True,
    quotas: Iterable[QuotaSpec | Mapping] = (),
) -> Plan:
    """创建或更新套餐档位（后台可配的最小服务面）。

    - 档位不存在 → 创建；存在 → 更新月费/启停/配额（保留客户关系）；
    - quotas 按 unit 覆盖对应 PlanQuota 行；未提及的单位配置保持不动；
    - 调价即时生效：结算每次从本表现读价，无发版动作。
    """
    plan = session.execute(select(Plan).where(Plan.code == code)).scalar_one_or_none()
    created = plan is None
    if created:
        plan = Plan(code=code, name=name)
        session.add(plan)
    assert plan is not None
    plan.name = name
    plan.monthly_price_micro = monthly_price_micro
    plan.is_active = is_active
    session.flush()

    existing = {q.unit: q for q in plan.quotas}
    for spec in quotas:
        if isinstance(spec, Mapping):
            spec = QuotaSpec(
                unit=str(spec["unit"]),
                included_quantity=int(spec.get("included_quantity", 0)),
                overage_unit_price_micro=int(spec.get("overage_unit_price_micro", 0)),
            )
        row = existing.get(spec.unit)
        if row is None:
            row = PlanQuota(plan_id=plan.id, unit=spec.unit)
            session.add(row)
            plan.quotas.append(row)
        row.included_quantity = spec.included_quantity
        row.overage_unit_price_micro = spec.overage_unit_price_micro
    session.flush()
    return plan

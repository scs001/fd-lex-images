"""额度状态查询与 fail-closed 预检（spec 需求 3 的计量侧地基）。

职责边界（本期）：只做**数据结构与服务接口**——
- ``quota_status``：单客户周期内逐单位的额度水位（含额/已用/剩余/两档阈值）
  与支付侧余额探针，输出硬停判定（allowed/语义原因）；
- 402 硬停的执行在 registry 侧（后续任务消费本接口），预警通知渠道投递
  在通知通道（后续任务消费 NoticeRecord 行）——本模块不发通知、不拦调用。

fail-closed 语义：
- 计费面不可达 → ``balance.reachable=False`` 且预检不通过（宁可错拒，
  不放行后追缴）；
- 额度耗尽（remaining<=0 且超额单价为 0，即无法以超额继续）→ 硬停；
- 用量取自计量流（metering，权威实时），账本滞后于计量不产生放行误判。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from sqlalchemy.orm import Session

from .metering_source import MeteringSource, MeteringUsage, StaticMeteringSource
from .models import Customer, validate_period
from .notices import threshold_tiers_hit
from .sub2api import ProbeResult, Sub2ApiClient

#: 额度耗尽且无超额单价时的拒绝语义（registry 侧映射为 HTTP 402）
REASON_QUOTA_EXHAUSTED = "quota_exhausted"
REASON_BILLING_PLANE_UNREACHABLE = "billing_plane_unreachable"
REASON_INSUFFICIENT_BALANCE = "insufficient_balance"


@dataclass
class UnitQuotaStatus:
    """单客户单单位的额度水位。"""

    unit: str
    included_quantity: int
    used_quantity: int
    overage_unit_price_micro: int = 0
    configured: bool = True  # 套餐未配置该单位=False（不参与计价）

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.included_quantity - self.used_quantity)

    @property
    def used_pct(self) -> int:
        """已用百分比（向上取整，全整数运算；未配置=0）。"""
        if self.included_quantity <= 0:
            return 0
        return (self.used_quantity * 100 + self.included_quantity - 1) // self.included_quantity

    @property
    def tiers_hit(self) -> list[int]:
        """已跨过的预警档位（80/95）。"""
        return threshold_tiers_hit(self.used_quantity, self.included_quantity)

    @property
    def overage_priced(self) -> bool:
        """超额有单价 → 超出部分可继续（走 sub2api 余额扣减）。"""
        return self.configured and self.overage_unit_price_micro > 0

    @property
    def exhausted(self) -> bool:
        """硬停依据：额度耗尽且超额不计价（无超额单价背书继续用量）。"""
        return (
            self.configured
            and self.used_quantity >= self.included_quantity
            and not self.overage_priced
        )


@dataclass
class QuotaStatus:
    """单客户额度状态快照（registry 侧硬停预检的输入）。"""

    customer_id: int
    customer_name: str
    period: str
    units: list[UnitQuotaStatus] = field(default_factory=list)
    balance: ProbeResult | None = None

    @property
    def exhausted_units(self) -> list[str]:
        return [u.unit for u in self.units if u.exhausted]

    @property
    def allowed(self) -> bool:
        """fail-closed 总判定：额度未耗尽 且 （未要求余额或余额充足）。"""
        if self.exhausted_units:
            return False
        if self.balance is not None and not self.balance.sufficient:
            return False
        return True

    @property
    def denial_reason(self) -> str | None:
        """拒绝语义（allowed=True 时为 None）；registry 侧映射 402 时如实转述。"""
        if self.exhausted_units:
            return f"{REASON_QUOTA_EXHAUSTED}:{','.join(self.exhausted_units)}"
        if self.balance is not None and not self.balance.sufficient:
            if not self.balance.reachable:
                return REASON_BILLING_PLANE_UNREACHABLE
            return REASON_INSUFFICIENT_BALANCE
        return None

    def as_dict(self) -> dict:
        return {
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "period": self.period,
            "allowed": self.allowed,
            "denial_reason": self.denial_reason,
            "units": [
                {
                    "unit": u.unit,
                    "included_quantity": u.included_quantity,
                    "used_quantity": u.used_quantity,
                    "remaining_quantity": u.remaining_quantity,
                    "used_pct": u.used_pct,
                    "tiers_hit": u.tiers_hit,
                    "overage_priced": u.overage_priced,
                    "configured": u.configured,
                }
                for u in self.units
            ],
            "balance": (
                {
                    "reachable": self.balance.reachable,
                    "balance_micro": self.balance.balance_micro,
                    "min_balance_micro": self.balance.min_balance_micro,
                    "sufficient": self.balance.sufficient,
                    "error": self.balance.error,
                }
                if self.balance is not None
                else None
            ),
        }


def quota_status(
    session: Session,
    customer: Customer,
    period: str,
    *,
    metering: MeteringSource,
    sub2api: Sub2ApiClient | None = None,
    min_balance_micro: int = 0,
    usage_override: Mapping[str, int] | None = None,
) -> QuotaStatus:
    """查询单客户周期额度状态（只读，不写任何表、不发通知）。

    - 用量：客户凭据轨道 metering 聚合（权威实时）；``usage_override`` 供
      调用方注入已算好的用量（unit → quantity），跳过计量源查询；
    - 余额：传入 sub2api 时做余额探针（min_balance_micro>0 或不可达 →
      预检不通过，fail-closed）；未传入则只看额度水位；
    - 套餐未配置的单位以 configured=False 呈现（用量可见但不计价）。
    """
    validate_period(period)
    if usage_override is not None:
        usages = [
            MeteringUsage(customer_ref=customer.sub2api_user_id or "", unit=u, quantity=q)
            for u, q in sorted(usage_override.items())
        ]
        source: MeteringSource = StaticMeteringSource(usages)
    else:
        source = metering

    usage_by_unit: dict[str, int] = {}
    for usage in source.aggregates(period):
        if usage.customer_ref == (customer.sub2api_user_id or ""):
            usage_by_unit[usage.unit] = usage.quantity

    status = QuotaStatus(
        customer_id=customer.id,
        customer_name=customer.name,
        period=period,
    )
    for quota in sorted(customer.plan.quotas, key=lambda q: q.unit):
        used = usage_by_unit.pop(quota.unit, 0)
        status.units.append(
            UnitQuotaStatus(
                unit=quota.unit,
                included_quantity=quota.included_quantity,
                used_quantity=used,
                overage_unit_price_micro=quota.overage_unit_price_micro,
                configured=True,
            )
        )
    for unit, used in sorted(usage_by_unit.items()):  # 有用量但套餐未配置的单位
        status.units.append(
            UnitQuotaStatus(
                unit=unit, included_quantity=0, used_quantity=used, configured=False
            )
        )

    if sub2api is not None and customer.sub2api_user_id:
        # 余额下限与 registry 预检口径对齐：preflight 对 balance<=0 一律 402
        # （2026-10-06 首客开户演练实弹）；min 传 0 时若按字面比较会得出
        # 「零余额 sufficient=true」的控制台假阴（演练实测）——故下限至少取 1。
        floor = max(min_balance_micro, 1)
        status.balance = sub2api.probe(customer.sub2api_user_id, min_balance_micro=floor)
    return status

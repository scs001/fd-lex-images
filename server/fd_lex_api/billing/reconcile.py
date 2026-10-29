"""对账 reconcile()：lex 账本（权威）× 计量流 × sub2api 余额快照 三方核对。

（照 fd-wire billing/reconcile.py 移植；lex 适配=第三方法——计量流聚合
与账本已结数量逐单位比对，未结/超结差异不静默。）

只读不动账（差异供后台人工处置，spec「对账一致：差异告警不静默」）。

口径：
1. 余额侧（账本 × sub2api，照 wire）：
       expected = opening − Σ(账本 sub2api_applied 条目金额)
       difference = snapshot − expected （≠0 即差异条目）
   账本侧只计 sub2api_applied=True 的条目（settle 写 overage 时置位；
   grant 是套餐额度分配、adjustment 默认未执行，都不自动动 sub2api 余额）。
2. 计量流侧（计量流 × 账本，lex 新增）：
       expected_overage[unit] = max(0, metered − included_grant)
       difference = expected_overage − settled_overage
   正差=漏结/漏价（计量>账本），负差=多结（账本>计量，如计量记录被撤）。
   含额内的用量天然一致，不进差异。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ledger import Ledger
from .metering_source import MeteringSource
from .models import Customer, validate_period
from .sub2api import Sub2ApiClient, Sub2ApiError


@dataclass(frozen=True)
class UnitReconcile:
    """单客户单单位的计量流×账本核对。

    口径：超额部分必须全额入账——
        expected_overage = max(0, metered − included)
        difference = expected_overage − settled_overage
    正差=漏结/漏价（计量流有、账本无），负差=多结（如计量记录被撤）。
    含额内的用量天然一致，不进差异。
    """

    unit: str
    metered_quantity: int         # 计量流侧（客户轨聚合）
    included_quantity: int        # 账本侧含额 grant 数量
    settled_overage_quantity: int  # 账本侧已结超额数量

    @property
    def expected_overage_quantity(self) -> int:
        return max(0, self.metered_quantity - self.included_quantity)

    @property
    def difference(self) -> int:
        return self.expected_overage_quantity - self.settled_overage_quantity

    @property
    def is_mismatch(self) -> bool:
        return self.difference != 0


@dataclass(frozen=True)
class ReconcileRow:
    """单客户对账行：error 行 reachable=False（不猜快照）。"""

    customer_id: int
    customer_name: str
    sub2api_user_id: str | None
    ledger_applied_micro: int
    opening_micro: int
    expected_micro: int
    snapshot_micro: int | None = None
    difference_micro: int | None = None  # None = 快照不可得
    units: tuple[UnitReconcile, ...] = ()
    reachable: bool = True
    error: str | None = None

    @property
    def is_mismatch(self) -> bool:
        """余额差异（快照可得且 ≠0）。"""
        return self.difference_micro not in (None, 0)

    @property
    def unit_mismatches(self) -> tuple[UnitReconcile, ...]:
        return tuple(u for u in self.units if u.is_mismatch)

    @property
    def is_clean(self) -> bool:
        """三方全对齐：余额无差异、计量逐单位无差异、无错误。"""
        return (
            self.error is None
            and not self.is_mismatch
            and not self.unit_mismatches
            and self.difference_micro == 0
        )


@dataclass
class ReconcileReport:
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period: str | None = None
    rows: list[ReconcileRow] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.rows)

    @property
    def mismatches(self) -> list[ReconcileRow]:
        """余额侧差异（账本 × sub2api）。"""
        return [r for r in self.rows if r.is_mismatch]

    @property
    def metering_mismatches(self) -> list[ReconcileRow]:
        """计量流侧差异（计量流 × 账本，含 unbilled/overbilled）。"""
        return [r for r in self.rows if r.unit_mismatches]

    @property
    def errors(self) -> list[ReconcileRow]:
        return [r for r in self.rows if r.error is not None]

    @property
    def matched(self) -> int:
        return sum(1 for r in self.rows if r.is_clean)


def _metering_by_unit(
    metering: MeteringSource, period: str, refs: set[str]
) -> dict[str, int]:
    """按客户身份集合聚合（绑定身份 + sub2api_user_id；同客户多身份求和）。

    2026-10-06 首客开户演练实测：仅按 sub2api_user_id 匹配会漏掉 patch-key
    的 Logto sub 身份（如 8tajhoprelg0）用量 → 计量侧假阴。
    """
    totals: dict[str, int] = {}
    for u in metering.aggregates(period):
        if u.customer_ref in refs:
            totals[u.unit] = totals.get(u.unit, 0) + u.quantity
    return totals


def _ledger_units_by_unit(session: Session, customer_id: int, period: str) -> tuple[dict[str, int], dict[str, int]]:
    """账本侧：逐单位 (included grant 数量, overage 已结数量)。"""
    ledger = Ledger(session)
    included: dict[str, int] = {}
    overage: dict[str, int] = {}
    for entry in ledger.entries(customer_id, period):
        if entry.unit is None:
            continue  # 月费 grant 与单位无关
        if entry.kind == "grant":
            included[entry.unit] = included.get(entry.unit, 0) + entry.quantity
        elif entry.kind == "overage":
            overage[entry.unit] = overage.get(entry.unit, 0) + entry.quantity
    return included, overage


def reconcile(
    session: Session,
    sub2api: Sub2ApiClient,
    metering: MeteringSource,
    *,
    period: str,
    opening_balances: Mapping[int, int] | None = None,
    customer_ids: Iterable[int] | None = None,
) -> ReconcileReport:
    """生成三方差异报告；不写任何表。customer_ids 缺省=全部绑定 sub2api 的客户。"""
    validate_period(period)
    opening = opening_balances or {}
    stmt = select(Customer).where(Customer.sub2api_user_id.is_not(None))
    if customer_ids is not None:
        stmt = stmt.where(Customer.id.in_(list(customer_ids)))
    customers = list(session.execute(stmt.order_by(Customer.id)).scalars().all())

    ledger = Ledger(session)
    report = ReconcileReport(period=period)
    for customer in customers:
        applied = ledger.applied_total(customer.id, period=period)
        opening_micro = opening.get(customer.id, 0)
        expected = opening_micro - applied

        # 计量流侧（任何情况下都算——sub2api 挂了也能出计量差异）
        from ..console_api.identity import customer_identities  # 延迟导入避环

        metered = _metering_by_unit(
            metering, period, set(customer_identities(session, customer))
        )
        included_by_unit, overage_by_unit = _ledger_units_by_unit(
            session, customer.id, period
        )
        unit_rows = tuple(
            sorted(
                (
                    UnitReconcile(
                        unit=unit,
                        metered_quantity=metered.get(unit, 0),
                        included_quantity=included_by_unit.get(unit, 0),
                        settled_overage_quantity=overage_by_unit.get(unit, 0),
                    )
                    for unit in set(metered) | set(included_by_unit) | set(overage_by_unit)
                ),
                key=lambda u: u.unit,
            )
        )

        try:
            snapshot = sub2api.read_user(customer.sub2api_user_id)  # type: ignore[arg-type]
        except Sub2ApiError as exc:
            report.rows.append(
                ReconcileRow(
                    customer_id=customer.id,
                    customer_name=customer.name,
                    sub2api_user_id=customer.sub2api_user_id,
                    ledger_applied_micro=applied,
                    opening_micro=opening_micro,
                    expected_micro=expected,
                    snapshot_micro=None,
                    difference_micro=None,
                    units=unit_rows,
                    reachable=False,
                    error=f"sub2api 读取失败: {exc}",
                )
            )
            continue
        report.rows.append(
            ReconcileRow(
                customer_id=customer.id,
                customer_name=customer.name,
                sub2api_user_id=customer.sub2api_user_id,
                ledger_applied_micro=applied,
                opening_micro=opening_micro,
                expected_micro=expected,
                snapshot_micro=snapshot.balance_micro,
                difference_micro=snapshot.balance_micro - expected,
                units=unit_rows,
                reachable=True,
            )
        )
    return report

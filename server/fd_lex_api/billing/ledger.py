"""lex 权威账本：同 idempotency_key 重放只记一条。

（照 fd-wire billing/ledger.py 移植；lex 适配=键规范带单位维度。）

写入用 SAVEPOINT（begin_nested）包住 flush：并发/重放撞唯一约束时
只回滚该条插入，不殃及同事务内其它账目。

键规范（在此收口）：
- ``grant:{cid}:{period}``                月费 grant（金额=套餐月费）
- ``grant:{cid}:{period}:{unit}``         单位含额 grant（数量=包含额度）
- ``settle:{period}:{scope}:{cid}:{unit}`` 超额结算（scope=batch_ref|period）
- ``adjust:{cid}:{period}:{source_ref}``  人工调整
- ``hardstop:{cid}:{period}:{ref}``       硬停事件留档
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import LedgerEntry, LedgerKind, validate_period


@dataclass(frozen=True)
class RecordResult:
    entry: LedgerEntry
    created: bool  # False = 同键重放命中既有条目


def grant_key(customer_id: int, period: str) -> str:
    return f"grant:{customer_id}:{period}"


def grant_unit_key(customer_id: int, period: str, unit: str) -> str:
    return f"grant:{customer_id}:{period}:{unit}"


def settle_key(period: str, batch_ref: str | None, customer_id: int, unit: str) -> str:
    scope = batch_ref if batch_ref else "period"
    return f"settle:{period}:{scope}:{customer_id}:{unit}"


def adjustment_key(source_ref: str, customer_id: int, period: str) -> str:
    return f"adjust:{customer_id}:{period}:{source_ref}"


def hardstop_key(customer_id: int, period: str, ref: str) -> str:
    return f"hardstop:{customer_id}:{period}:{ref}"


class Ledger:
    """账本服务：所有记账必经此口（幂等 + 可追溯 source_ref）。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- 查询 -------------------------------------------------------------

    def find(self, idempotency_key: str) -> LedgerEntry | None:
        return self._session.execute(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key)
        ).scalar_one_or_none()

    def entries(self, customer_id: int, period: str | None = None) -> list[LedgerEntry]:
        stmt = select(LedgerEntry).where(LedgerEntry.customer_id == customer_id)
        if period is not None:
            stmt = stmt.where(LedgerEntry.period == validate_period(period))
        return list(self._session.execute(stmt.order_by(LedgerEntry.id)).scalars().all())

    def applied_total(self, customer_id: int, period: str | None = None) -> int:
        """已实际经 sub2api 执行的扣/调合计（对账的账本侧口径）。"""
        return sum(
            e.amount_micro for e in self.entries(customer_id, period) if e.sub2api_applied
        )

    def overage_quantity(
        self, customer_id: int, period: str, unit: str
    ) -> int:
        """某单位某周期已入账的超额数量（对账的计量流侧口径）。"""
        return sum(
            e.quantity
            for e in self.entries(customer_id, period)
            if e.kind == LedgerKind.OVERAGE.value and e.unit == unit
        )

    def granted_quantity(self, customer_id: int, period: str, unit: str) -> int:
        """某单位某周期已入账的包含额度（grant 数量）。"""
        return sum(
            e.quantity
            for e in self.entries(customer_id, period)
            if e.kind == LedgerKind.GRANT.value and e.unit == unit
        )

    # -- 幂等记账 -----------------------------------------------------------

    def record(
        self,
        *,
        customer_id: int,
        kind: LedgerKind,
        period: str,
        idempotency_key: str,
        unit: str | None = None,
        quantity: int = 0,
        amount_micro: int = 0,
        source_ref: str | None = None,
        sub2api_applied: bool = False,
    ) -> RecordResult:
        """记一条；同 idempotency_key 已存在则原样返回（created=False）。"""
        validate_period(period)
        existing = self.find(idempotency_key)
        if existing is not None:
            return RecordResult(existing, created=False)
        entry = LedgerEntry(
            customer_id=customer_id,
            kind=kind.value,
            unit=unit,
            quantity=quantity,
            amount_micro=amount_micro,
            period=period,
            idempotency_key=idempotency_key,
            source_ref=source_ref,
            sub2api_applied=sub2api_applied,
        )
        try:
            with self._session.begin_nested():
                self._session.add(entry)
                self._session.flush()
        except IntegrityError:
            existing = self.find(idempotency_key)
            if existing is None:  # pragma: no cover - 非幂等键的完整性问题
                raise
            return RecordResult(existing, created=False)
        return RecordResult(entry, created=True)

    # -- 语义化快捷方式（都是 record 的薄封装，键规范在此收口） --------------

    def ensure_grant(
        self,
        *,
        customer_id: int,
        period: str,
        monthly_price_micro: int,
        source_ref: str | None = None,
    ) -> RecordResult:
        """套餐月费 grant——grant:{cid}:{period} 幂等（amount=月费）。"""
        return self.record(
            customer_id=customer_id,
            kind=LedgerKind.GRANT,
            period=period,
            idempotency_key=grant_key(customer_id, period),
            amount_micro=monthly_price_micro,
            source_ref=source_ref,
        )

    def ensure_unit_grant(
        self,
        *,
        customer_id: int,
        period: str,
        unit: str,
        included_quantity: int,
        source_ref: str | None = None,
    ) -> RecordResult:
        """单位含额 grant——grant:{cid}:{period}:{unit} 幂等（quantity=含额）。"""
        return self.record(
            customer_id=customer_id,
            kind=LedgerKind.GRANT,
            period=period,
            idempotency_key=grant_unit_key(customer_id, period, unit),
            unit=unit,
            quantity=included_quantity,
            source_ref=source_ref,
        )

    def record_overage(
        self,
        *,
        customer_id: int,
        period: str,
        unit: str,
        idempotency_key: str,
        quantity: int,
        amount_micro: int,
        source_ref: str | None = None,
        sub2api_applied: bool = False,
    ) -> RecordResult:
        """超额入账（settle 执行器专用；幂等键由 settle_key 规范给出）。"""
        return self.record(
            customer_id=customer_id,
            kind=LedgerKind.OVERAGE,
            period=period,
            idempotency_key=idempotency_key,
            unit=unit,
            quantity=quantity,
            amount_micro=amount_micro,
            source_ref=source_ref,
            sub2api_applied=sub2api_applied,
        )

    def record_adjustment(
        self,
        *,
        customer_id: int,
        period: str,
        amount_micro: int,
        source_ref: str,
        sub2api_applied: bool = False,
    ) -> RecordResult:
        """人工调整（带符号）；只有已手工在 sub2api 执行过才置 sub2api_applied。"""
        if amount_micro == 0:
            raise ValueError("调整金额不能为 0")
        return self.record(
            customer_id=customer_id,
            kind=LedgerKind.ADJUSTMENT,
            period=period,
            idempotency_key=adjustment_key(source_ref, customer_id, period),
            amount_micro=amount_micro,
            source_ref=source_ref,
            sub2api_applied=sub2api_applied,
        )

    def record_hardstop(
        self, *, customer_id: int, period: str, ref: str
    ) -> RecordResult:
        """额度耗尽硬停事件留档（amount=0，仅事件轨迹）。"""
        return self.record(
            customer_id=customer_id,
            kind=LedgerKind.HARDSTOP,
            period=period,
            idempotency_key=hardstop_key(customer_id, period, ref),
            source_ref=ref,
        )

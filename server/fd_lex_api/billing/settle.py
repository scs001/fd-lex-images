"""结算执行器 settle()：计量聚合 → 套餐 grant → 逐单位超额判定 → sub2api 幂等扣减。

（照 fd-wire billing/settle.py 移植；lex 适配=逐单位循环，双单位价由
套餐配额表驱动。）

时序（每客户）：
1. 聚合客户凭据轨道的 (unit, quantity)（MeteringSource，只读 metering 表；
   真实表 adapter=整月聚合域，batch_ref 供水位线实现扩展）
2. ensure_grant：套餐月费条目（幂等键 grant:{cid}:{period}）
3. 逐单位：ensure_unit_grant（含额）→ overage_qty = max(0, 用量-含额)
   → 单价×数量 = 超额金额（单价来自套餐配额表——后台调价即时生效）
4. 超额>0 且账本无 settle 键 → sub2api.adjustBalance(幂等键=settle 键)
   → 成功才写 overage 条目（sub2api_applied=True）
5. 失败（sub2api 不可达/4xx）→ 不写账，报告标 failed_sub2api，
   下轮重放同键：sub2api 服务端幂等去重、账本补记——净效果一次扣减

重放保证：
- settle 键已存在于账本 → 直接 replayed，sub2api 零调用、账本零新增
  （验收：同批次重放不双扣不双记）
- 套餐未配置某单位 → 该单位用量不进账单，报告标 unbilled_no_quota
  （不静默；对账侧同样呈现差异）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ledger import Ledger, RecordResult, settle_key
from .metering_source import MeteringSource, MeteringUsage
from .models import Customer, CustomerStatus, Plan, PlanQuota, validate_period
from .notices import evaluate_usage_warnings
from .sub2api import Sub2ApiClient, Sub2ApiError

CustomerResolver = Callable[[str], Customer | None]


def default_resolver(session: Session) -> CustomerResolver:
    """默认身份映射（耦合点）：metering 的 caller → Customer。

    顺序：① ``console_identity_bindings`` 绑定表（运营后台绑定的 Logto 身份，
    含 patch-key 的 Logto sub 形态，如 8tajhoprelg0）；② 回落
    ``Customer.sub2api_user_id == ref``（支付侧用户 id 直配的兼容路径）。
    2026-10-06 首客开户演练实测：仅凭 ② 会漏掉已绑定身份，结算报
    skipped_no_customer——绑定表才是真实身份映射的落点。
    """

    def resolve(ref: str) -> Customer | None:
        from ..console_api.models import ConsoleIdentityBinding  # 延迟导入避环

        binding = (
            session.execute(
                select(ConsoleIdentityBinding)
                .where(ConsoleIdentityBinding.identity == ref)
                .order_by(ConsoleIdentityBinding.id)
            )
            .scalars()
            .first()
        )
        if binding is not None:
            customer = session.get(Customer, binding.customer_id)
            if customer is not None:
                return customer
        return session.execute(
            select(Customer).where(Customer.sub2api_user_id == ref)
        ).scalar_one_or_none()

    return resolve


def _sum_by_unit(usages: list[MeteringUsage]) -> list[MeteringUsage]:
    """同一客户的多个身份 ref：按单位求和（含额按客户只算一次的口径依据）。"""
    totals: dict[str, int] = {}
    for usage in usages:
        totals[usage.unit] = totals.get(usage.unit, 0) + usage.quantity
    ref = usages[0].customer_ref if usages else ""
    return [
        MeteringUsage(customer_ref=ref, unit=unit, quantity=qty)
        for unit, qty in sorted(totals.items())
    ]


@dataclass
class UnitSettlement:
    """单客户单单位的结算明细。"""

    unit: str
    used_quantity: int = 0
    included_quantity: int = 0
    overage_quantity: int = 0
    overage_amount_micro: int = 0
    sub2api_called: bool = False
    unbilled_no_quota: bool = False  # 套餐未配置该单位 → 未计价
    notice_tiers_sent: list[int] = field(default_factory=list)


@dataclass
class CustomerSettlement:
    """单客户结算结果。status ∈ settled / replayed / skipped_* / failed_*。"""

    status: str
    customer_ref: str
    units: list[UnitSettlement] = field(default_factory=list)
    customer_id: int | None = None
    grant_created: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("settled", "replayed")

    @property
    def sub2api_called(self) -> bool:
        return any(u.sub2api_called for u in self.units)

    @property
    def has_unbilled(self) -> bool:
        return any(u.unbilled_no_quota for u in self.units)


@dataclass
class SettlementReport:
    period: str
    batch_ref: str | None
    results: list[CustomerSettlement] = field(default_factory=list)

    @property
    def sub2api_call_count(self) -> int:
        return sum(1 for r in self.results if r.sub2api_called)

    @property
    def failures(self) -> list[CustomerSettlement]:
        return [r for r in self.results if not r.ok]


class SettlementService:
    """结算执行器（一个实例一个 session，非线程共享）。"""

    def __init__(
        self,
        session: Session,
        sub2api: Sub2ApiClient,
        metering: MeteringSource,
        *,
        resolver: CustomerResolver | None = None,
    ) -> None:
        self._session = session
        self._sub2api = sub2api
        self._metering = metering
        self._ledger = Ledger(session)
        self._resolver = resolver or default_resolver(session)

    def settle(self, period: str, batch_ref: str | None = None) -> SettlementReport:
        """结算一个计量批次（batch_ref=None 表示整月聚合域）。"""
        validate_period(period)
        report = SettlementReport(period=period, batch_ref=batch_ref)
        try:
            usages = sorted(
                self._metering.aggregates(period, batch_ref),
                key=lambda u: (u.customer_ref, u.unit),
            )
        except Exception as exc:  # 计量源不可读：整批失败，不动任何账
            report.results.append(
                CustomerSettlement(
                    status="failed_metering_source", customer_ref="", error=str(exc)
                )
            )
            return report

        # 先解析客户再归并：同一客户的多个计量身份 ref（如 Logto 用户名与
        # patch-key 的 sub）合并为一组——配额按客户只算一次（多身份不重复
        # 享受含额）；解析不到的 ref 保持独立，走 skipped_no_customer 报告。
        resolved: dict[int, tuple[Customer, list[MeteringUsage]]] = {}
        refs: dict[int, set[str]] = {}
        unresolved: dict[str, list[MeteringUsage]] = {}
        for usage in usages:
            customer = self._resolver(usage.customer_ref)
            if customer is None:
                unresolved.setdefault(usage.customer_ref, []).append(usage)
                continue
            refs.setdefault(customer.id, set()).add(usage.customer_ref)
            resolved.setdefault(customer.id, (customer, []))[1].append(usage)

        for cid in sorted(resolved):
            customer, group = resolved[cid]
            label = ",".join(sorted(refs[cid]))
            report.results.append(
                self._settle_customer(
                    period, batch_ref, label, _sum_by_unit(group), customer=customer
                )
            )
        for ref in sorted(unresolved):
            report.results.append(
                self._settle_customer(period, batch_ref, ref, unresolved[ref])
            )
        self._session.commit()  # 逐客户失败已入报告；成功部分照常落账
        return report

    # -- 单客户 -------------------------------------------------------------

    def _settle_customer(
        self,
        period: str,
        batch_ref: str | None,
        customer_ref: str,
        usages: list[MeteringUsage],
        *,
        customer: Customer | None = None,
    ) -> CustomerSettlement:
        result = CustomerSettlement(status="settled", customer_ref=customer_ref)
        customer = customer if customer is not None else self._resolver(customer_ref)
        if customer is None:
            result.status = "skipped_no_customer"
            result.error = f"metering customer_ref 无法映射客户: {customer_ref}"
            return result
        result.customer_id = customer.id
        if customer.status != CustomerStatus.ACTIVE.value:
            result.status = "skipped_inactive"
            result.error = f"客户状态 {customer.status}，不结算"
            return result

        plan = customer.plan
        source_ref = batch_ref if batch_ref is not None else f"period:{period}"

        # 1) 套餐月费 grant（幂等：grant:{cid}:{period}）
        grant: RecordResult = self._ledger.ensure_grant(
            customer_id=customer.id,
            period=period,
            monthly_price_micro=plan.monthly_price_micro,
            source_ref=source_ref,
        )
        result.grant_created = grant.created

        # 2) 逐单位：含额 grant + 超额幂等扣减；任一单位失败即停（下轮重放自愈）
        for usage in usages:
            unit_result, error = self._settle_unit(
                period, source_ref, customer, plan, usage
            )
            result.units.append(unit_result)
            if error is not None:
                result.status = error.status
                result.error = error.message
                return result

        created_any = grant.created or any(
            u.sub2api_called for u in result.units
        )
        result.status = "settled" if created_any else "replayed"

        # 3) 两档预警（逐单位；不中断结算）
        for unit_result in result.units:
            self._notify(period, customer, unit_result, result)
        return result

    def _settle_unit(
        self,
        period: str,
        source_ref: str,
        customer: Customer,
        plan: Plan,
        usage: MeteringUsage,
    ) -> tuple[UnitSettlement, "_UnitError | None"]:
        unit_result = UnitSettlement(unit=usage.unit, used_quantity=usage.quantity)
        quota: PlanQuota | None = plan.quota(usage.unit)
        if quota is None:
            # 套餐未配置该单位：不进账单也不报错——留痕由报告与对账呈现
            unit_result.unbilled_no_quota = True
            return unit_result, None

        unit_result.included_quantity = quota.included_quantity

        # 单位含额 grant（幂等：grant:{cid}:{period}:{unit}）
        self._ledger.ensure_unit_grant(
            customer_id=customer.id,
            period=period,
            unit=usage.unit,
            included_quantity=quota.included_quantity,
            source_ref=source_ref,
        )

        # 超额判定与幂等扣减
        unit_result.overage_quantity = max(0, usage.quantity - quota.included_quantity)
        if unit_result.overage_quantity <= 0:
            return unit_result, None

        unit_result.overage_amount_micro = (
            unit_result.overage_quantity * quota.overage_unit_price_micro
        )
        if unit_result.overage_amount_micro <= 0:
            # 超额但单价为 0（后台未定价）：无可扣金额，不碰 sub2api
            return unit_result, None

        key = settle_key(period, source_ref, customer.id, usage.unit)
        existing = self._ledger.find(key)
        if existing is not None:
            # 账本已有 → 不再碰 sub2api、不再记账（重放）
            unit_result.overage_amount_micro = existing.amount_micro
            unit_result.overage_quantity = existing.quantity
            return unit_result, None

        if not customer.sub2api_user_id:
            return unit_result, _UnitError(
                "failed_no_sub2api_user", "客户未绑定 sub2api 账户"
            )
        try:
            self._sub2api.adjust_balance(
                user_id=customer.sub2api_user_id,
                amount_micro=-unit_result.overage_amount_micro,  # 扣减为负
                idempotency_key=key,
            )
        except Sub2ApiError as exc:
            # 不写账——下轮同键重放自愈
            return unit_result, _UnitError("failed_sub2api", str(exc))
        unit_result.sub2api_called = True

        entry = self._ledger.record_overage(
            customer_id=customer.id,
            period=period,
            unit=usage.unit,
            idempotency_key=key,
            quantity=unit_result.overage_quantity,
            amount_micro=unit_result.overage_amount_micro,
            source_ref=source_ref,
            sub2api_applied=True,
        )
        if not entry.created:  # 并发对手已记（sub2api 同键幂等，净一次扣减）
            unit_result.sub2api_called = False
        return unit_result, None

    def _notify(
        self,
        period: str,
        customer: Customer,
        unit_result: UnitSettlement,
        owner: CustomerSettlement,
    ) -> None:
        try:
            notices = evaluate_usage_warnings(
                self._session,
                customer=customer,
                period=period,
                unit=unit_result.unit,
                used_quantity=unit_result.used_quantity,
                included_quantity=unit_result.included_quantity,
            )
            unit_result.notice_tiers_sent = [n.threshold_pct for n in notices]
        except Exception as exc:  # 预警失败不阻塞结算，留报告线索
            owner.error = owner.error or f"预警评估失败(unit={unit_result.unit}): {exc}"


@dataclass(frozen=True)
class _UnitError:
    status: str
    message: str

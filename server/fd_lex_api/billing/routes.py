"""结算/账本内部与后台端点（/internal/billing）。

（对齐 fd-wire 的 internal/admin 路由风格；鉴权骨架=INTERNAL_API_TOKEN
bearer，接 Logto 后收敛。）

- ``POST /internal/billing/settle/{period}``：触发结算（可选 batch_ref）
- ``GET  /internal/billing/reconcile``：三方对账报告（账本×计量流×sub2api）
- ``GET  /internal/billing/customers/{customer_id}/ledger``：账本流水
- ``GET  /internal/billing/customers/{customer_id}/quota``：额度状态
  （registry 侧硬停 402 预检消费此口）
- ``PUT  /internal/billing/plans/{code}``：套餐档位/含额/超额单价配置
  （后台可配的最小服务面——调价不发版；运营后台 UI 是后续任务）
- ``POST /internal/billing/customers``：开户（sub2api 代建账户，幂等）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .customers import ensure_customer
from .deps import (
    get_db_session,
    get_metering_source,
    get_sub2api_client,
    require_internal_token,
)
from .ledger import Ledger, adjustment_key
from .metering_source import MeteringSource
from .models import Customer, Plan, validate_period
from .plans import QuotaSpec, upsert_plan
from .quota import quota_status
from .reconcile import reconcile
from .settle import SettlementService
from .sub2api import Sub2ApiClient, Sub2ApiError

router = APIRouter(prefix="/internal/billing", tags=["billing"],
                   dependencies=[Depends(require_internal_token)])


# ---------------------------------------------------------------------------
# 结算触发
# ---------------------------------------------------------------------------


@router.post("/settle/{period}")
def settle(
    period: str,
    batch_ref: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
    sub2api: Sub2ApiClient = Depends(get_sub2api_client),
    metering: MeteringSource = Depends(get_metering_source),
) -> dict[str, Any]:
    """触发一个聚合域的结算；返回逐客户结算报告。"""
    try:
        validate_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    service = SettlementService(db, sub2api, metering)
    report = service.settle(period, batch_ref)
    return {
        "period": report.period,
        "batch_ref": report.batch_ref,
        "sub2api_call_count": report.sub2api_call_count,
        "failures": len(report.failures),
        "results": [
            {
                "status": r.status,
                "customer_ref": r.customer_ref,
                "customer_id": r.customer_id,
                "grant_created": r.grant_created,
                "ok": r.ok,
                "error": r.error,
                "units": [
                    {
                        "unit": u.unit,
                        "used_quantity": u.used_quantity,
                        "included_quantity": u.included_quantity,
                        "overage_quantity": u.overage_quantity,
                        "overage_amount_micro": u.overage_amount_micro,
                        "sub2api_called": u.sub2api_called,
                        "unbilled_no_quota": u.unbilled_no_quota,
                        "notice_tiers_sent": u.notice_tiers_sent,
                    }
                    for u in r.units
                ],
            }
            for r in report.results
        ],
    }


# ---------------------------------------------------------------------------
# 三方对账
# ---------------------------------------------------------------------------


@router.get("/reconcile")
def reconcile_route(
    period: str = Query(...),
    db: Session = Depends(get_db_session),
    sub2api: Sub2ApiClient = Depends(get_sub2api_client),
    metering: MeteringSource = Depends(get_metering_source),
) -> dict[str, Any]:
    """账本 × 计量流 × sub2api 三方口径核对（只读，不動账）。"""
    try:
        validate_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    report = reconcile(db, sub2api, metering, period=period)
    return {
        "period": report.period,
        "generated_at": report.generated_at.isoformat(),
        "checked": report.checked,
        "matched": report.matched,
        "balance_mismatches": len(report.mismatches),
        "metering_mismatches": len(report.metering_mismatches),
        "errors": len(report.errors),
        "rows": [
            {
                "customer_id": r.customer_id,
                "customer_name": r.customer_name,
                "sub2api_user_id": r.sub2api_user_id,
                "ledger_applied_micro": r.ledger_applied_micro,
                "opening_micro": r.opening_micro,
                "expected_micro": r.expected_micro,
                "snapshot_micro": r.snapshot_micro,
                "difference_micro": r.difference_micro,
                "units": [
                    {
                        "unit": u.unit,
                        "metered_quantity": u.metered_quantity,
                        "included_quantity": u.included_quantity,
                        "settled_overage_quantity": u.settled_overage_quantity,
                        "expected_overage_quantity": u.expected_overage_quantity,
                        "difference": u.difference,
                    }
                    for u in r.units
                ],
                "reachable": r.reachable,
                "error": r.error,
            }
            for r in report.rows
        ],
    }


# ---------------------------------------------------------------------------
# 账本流水 / 额度状态
# ---------------------------------------------------------------------------


def _get_customer(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"no such customer: {customer_id}")
    return customer


@router.get("/customers/{customer_id}/ledger")
def customer_ledger(
    customer_id: int,
    period: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """账本流水（billing_ledger_entries 只读；可按周期过滤）。"""
    if period is not None:
        try:
            validate_period(period)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    customer = _get_customer(db, customer_id)
    entries = Ledger(db).entries(customer.id, period)
    return {
        "customer_id": customer.id,
        "period": period,
        "entries": [
            {
                "id": e.id,
                "kind": e.kind,
                "unit": e.unit,
                "quantity": e.quantity,
                "amount_micro": e.amount_micro,
                "period": e.period,
                "idempotency_key": e.idempotency_key,
                "source_ref": e.source_ref,
                "sub2api_applied": e.sub2api_applied,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


@router.get("/customers/{customer_id}/quota")
def customer_quota(
    customer_id: int,
    period: str = Query(...),
    min_balance_micro: int = Query(default=0, ge=0),
    db: Session = Depends(get_db_session),
    sub2api: Sub2ApiClient = Depends(get_sub2api_client),
    metering: MeteringSource = Depends(get_metering_source),
) -> dict[str, Any]:
    """额度状态查询（fail-closed 预检；402 语义由 registry 侧消费）。"""
    try:
        validate_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    customer = _get_customer(db, customer_id)
    status = quota_status(
        db,
        customer,
        period,
        metering=metering,
        sub2api=sub2api,
        min_balance_micro=min_balance_micro,
    )
    return status.as_dict()


# ---------------------------------------------------------------------------
# 开户 / 套餐配置（后台可配的最小服务面）
# ---------------------------------------------------------------------------


class CreateCustomerBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    plan_code: str = Field(min_length=1, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=191)


@router.post("/customers")
def create_customer(
    body: CreateCustomerBody,
    db: Session = Depends(get_db_session),
    sub2api: Sub2ApiClient = Depends(get_sub2api_client),
) -> dict[str, Any]:
    """开户（幂等）：Customer 行 + sub2api 代建/认领账户（email 命中即认领）。"""
    try:
        customer, created = ensure_customer(
            db,
            sub2api,
            name=body.name,
            plan_code=body.plan_code,
            email=body.email,
            idempotency_key=body.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "created": created,
        "customer": {"id": customer.id, "name": customer.name,
                     "sub2api_user_id": customer.sub2api_user_id},
    }


class QuotaBody(BaseModel):
    """单单位配额配置。"""

    unit: str = Field(min_length=1, max_length=16)
    included_quantity: int = Field(default=0, ge=0)
    overage_unit_price_micro: int = Field(default=0, ge=0)


class FundingBody(BaseModel):
    """资金变动登记（开户收款/出账补记在 lex 账本的留痕；2026-10-06 首客演练补口）。"""

    #: 带符号：正=客户入金（账本按成本符号记负）；负=出账/消耗补记（账本记正）。
    amount_micro: int
    period: str = Field(min_length=7, max_length=7)
    source_ref: str = Field(min_length=1, max_length=128)
    #: true=同时经 sub2api adjustBalance 执行（成功才落账）；
    #: false=款项已在支付侧生效（人工/外部渠道已调账），本服务只登记。
    apply_to_sub2api: bool = False


@router.post("/customers/{customer_id}/funding")
def record_funding(
    body: FundingBody,
    customer_id: int = Path(ge=1),
    db: Session = Depends(get_db_session),
    sub2api: Sub2ApiClient = Depends(get_sub2api_client),
) -> dict[str, Any]:
    """资金变动登记（幂等键 = adjust:{cid}:{period}:{source_ref}，source_ref 取流水号）。

    口径：登记即表示该笔资金已在支付侧生效（apply_to_sub2api 只决定是否由本
    服务执行调账）——账本条目因此一律 sub2api_applied=True，对账式
    ``expected = opening − Σapplied`` 才能覆盖"钱从哪来"。账本取成本符号：
    入金记负、出账记正。失败 502 且不落账——重试同键净一次（与结算同纪律）。
    """
    if body.amount_micro == 0:
        raise HTTPException(status_code=422, detail="amount_micro 不能为 0")
    customer = _get_customer(db, customer_id)
    try:
        validate_period(body.period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ledger = Ledger(db)
    key = adjustment_key(body.source_ref, customer.id, body.period)
    existing = ledger.find(key)
    if existing is not None:
        db.commit()
        return {
            "created": False,
            "entry": {
                "id": existing.id,
                "kind": existing.kind,
                "amount_micro": existing.amount_micro,
                "period": existing.period,
                "idempotency_key": existing.idempotency_key,
                "source_ref": existing.source_ref,
                "sub2api_applied": existing.sub2api_applied,
            },
        }

    if body.apply_to_sub2api:
        if not customer.sub2api_user_id:
            raise HTTPException(status_code=409, detail="客户未绑定 sub2api 账户")
        try:
            sub2api.adjust_balance(
                user_id=customer.sub2api_user_id,
                amount_micro=body.amount_micro,
                idempotency_key=key,
            )
        except Sub2ApiError as exc:
            raise HTTPException(status_code=502, detail=f"sub2api 资金调整失败：{exc}") from exc

    entry = ledger.record_adjustment(
        customer_id=customer.id,
        period=body.period,
        amount_micro=-body.amount_micro,  # 成本符号：入金为负、出账为正
        source_ref=body.source_ref,
        sub2api_applied=True,
    )
    db.commit()
    return {
        "created": entry.created,
        "entry": {
            "id": entry.entry.id,
            "kind": entry.entry.kind,
            "amount_micro": entry.entry.amount_micro,
            "period": entry.entry.period,
            "idempotency_key": entry.entry.idempotency_key,
            "source_ref": entry.entry.source_ref,
            "sub2api_applied": entry.entry.sub2api_applied,
        },
    }


class PlanBody(BaseModel):
    """套餐档位配置（数字不预填，全部由本口配置——调价不发版）。"""

    name: str = Field(min_length=1, max_length=64)
    monthly_price_micro: int = Field(default=0, ge=0)
    is_active: bool = True
    quotas: list[QuotaBody] = Field(default_factory=list)


@router.put("/plans/{code}")
def put_plan(
    code: str,
    body: PlanBody,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """创建/更新套餐档位与按单位配额（结算即买即读现价，新价即时生效）。"""
    plan = upsert_plan(
        db,
        code=code,
        name=body.name,
        monthly_price_micro=body.monthly_price_micro,
        is_active=body.is_active,
        quotas=[
            QuotaSpec(
                unit=q.unit,
                included_quantity=q.included_quantity,
                overage_unit_price_micro=q.overage_unit_price_micro,
            )
            for q in body.quotas
        ],
    )
    db.commit()
    return {
        "code": plan.code,
        "name": plan.name,
        "monthly_price_micro": plan.monthly_price_micro,
        "is_active": plan.is_active,
        "quotas": [
            {"unit": q.unit, "included_quantity": q.included_quantity,
             "overage_unit_price_micro": q.overage_unit_price_micro}
            for q in sorted(plan.quotas, key=lambda x: x.unit)
        ],
    }


@router.get("/plans")
def list_plans(db: Session = Depends(get_db_session)) -> dict[str, Any]:
    """套餐档位一览（后台下拉数据源）。"""
    plans = list(db.execute(select(Plan).order_by(Plan.id)).scalars().all())
    return {
        "plans": [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "monthly_price_micro": p.monthly_price_micro,
                "is_active": p.is_active,
                "quotas": [
                    {"unit": q.unit, "included_quantity": q.included_quantity,
                     "overage_unit_price_micro": q.overage_unit_price_micro}
                    for q in sorted(p.quotas, key=lambda x: x.unit)
                ],
            }
            for p in plans
        ]
    }

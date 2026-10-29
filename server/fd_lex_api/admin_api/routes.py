"""后台路由（/api/admin/*）：客户/身份/套餐/账本/用量/凭据留痕。

全部端点挂在 ``require_admin`` 之下（内部令牌或 Logto 管理员角色）。
数据一律真读真写既有 billing/metering 表；sub2api 只在开户时经既有
``ensure_customer`` 契约调用（测试用 dependency_overrides 换假件，绝不真调）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..billing.customers import ensure_customer
from ..billing.deps import get_db_session, get_sub2api_client
from ..billing.ledger import Ledger
from ..billing.models import Customer, CustomerStatus, LedgerEntry, Plan, validate_period
from ..billing.money import micro_to_yuan_str
from ..billing.plans import QuotaSpec, get_plan, upsert_plan
from ..billing.quota import quota_status
from ..billing.sub2api import Sub2ApiClient, Sub2ApiError
from ..console_api.identity import (
    customer_identities,
    period_bounds,
    usage_by_unit,
)
from ..console_api.models import ConsoleCredentialEvent, ConsoleIdentityBinding
from ..metering.models import MeteringRecord
from .auth import AdminActor, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------------------
# 公共序列化
# ---------------------------------------------------------------------------


def _plan_dict(plan: Plan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "monthly_price_micro": plan.monthly_price_micro,
        "monthly_price_yuan": micro_to_yuan_str(plan.monthly_price_micro),
        "is_active": plan.is_active,
        "quotas": [
            {
                "unit": quota.unit,
                "included_quantity": quota.included_quantity,
                "overage_unit_price_micro": quota.overage_unit_price_micro,
                "overage_unit_price_yuan": micro_to_yuan_str(quota.overage_unit_price_micro),
            }
            for quota in sorted(plan.quotas, key=lambda q: q.unit)
        ],
    }


def _customer_dict(db: Session, customer: Customer) -> dict[str, Any]:
    plan = db.get(Plan, customer.plan_id)
    return {
        "id": customer.id,
        "name": customer.name,
        "sub2api_user_id": customer.sub2api_user_id,
        "plan_id": customer.plan_id,
        "plan_code": plan.code if plan else "",
        "plan_name": plan.name if plan else "",
        "status": customer.status,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
    }


def _entry_dict(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "customer_id": entry.customer_id,
        "kind": entry.kind,
        "unit": entry.unit,
        "quantity": entry.quantity,
        "amount_micro": entry.amount_micro,
        "amount_yuan": micro_to_yuan_str(entry.amount_micro),
        "period": entry.period,
        "idempotency_key": entry.idempotency_key,
        "source_ref": entry.source_ref,
        "sub2api_applied": entry.sub2api_applied,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _customer_or_404(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"no such customer: {customer_id}")
    return customer


# ---------------------------------------------------------------------------
# 我是谁（前端判定用哪条鉴权路径）
# ---------------------------------------------------------------------------


@router.get("/whoami")
def whoami(actor: AdminActor = Depends(require_admin)) -> dict[str, Any]:
    return actor.as_dict()


# ---------------------------------------------------------------------------
# 客户
# ---------------------------------------------------------------------------


@router.get("/customers")
def list_customers(db: Session = Depends(get_db_session)) -> dict[str, Any]:
    customers = db.execute(select(Customer).order_by(Customer.id.desc())).scalars().all()
    return {"customers": [_customer_dict(db, c) for c in customers], "count": len(customers)}


class CreateCustomerBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    plan_code: str = Field(min_length=1, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=191)


@router.post("/customers", status_code=status.HTTP_201_CREATED)
def create_customer(
    body: CreateCustomerBody,
    db: Session = Depends(get_db_session),
    sub2api: Sub2ApiClient = Depends(get_sub2api_client),
) -> dict[str, Any]:
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
    except Sub2ApiError as exc:
        raise HTTPException(
            status_code=502, detail=f"sub2api 开户失败：{exc}"
        ) from exc
    return {"created": created, "customer": _customer_dict(db, customer)}


class PatchCustomerBody(BaseModel):
    plan_code: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=16)


@router.patch("/customers/{customer_id}")
def patch_customer(
    body: PatchCustomerBody,
    customer_id: int = Path(ge=1),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    customer = _customer_or_404(db, customer_id)
    if body.plan_code is not None:
        try:
            plan = get_plan(db, body.plan_code)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        customer.plan_id = plan.id
    if body.status is not None:
        valid = {item.value for item in CustomerStatus}
        if body.status not in valid:
            raise HTTPException(
                status_code=422, detail=f"status must be one of {sorted(valid)}"
            )
        customer.status = body.status
    db.flush()
    return {"customer": _customer_dict(db, customer)}


# ---------------------------------------------------------------------------
# 身份绑定（Logto username ↔ Customer）
# ---------------------------------------------------------------------------


@router.get("/customers/{customer_id}/identities")
def list_identities(
    customer_id: int = Path(ge=1), db: Session = Depends(get_db_session)
) -> dict[str, Any]:
    customer = _customer_or_404(db, customer_id)
    rows = (
        db.execute(
            select(ConsoleIdentityBinding)
            .where(ConsoleIdentityBinding.customer_id == customer.id)
            .order_by(ConsoleIdentityBinding.id)
        )
        .scalars()
        .all()
    )
    return {
        "customer_id": customer.id,
        "identities": [row.as_dict() for row in rows],
        "sub2api_user_id": customer.sub2api_user_id,
        "metering_identities": customer_identities(db, customer),
    }


class BindIdentityBody(BaseModel):
    identity: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=255)


@router.post("/customers/{customer_id}/identities", status_code=status.HTTP_201_CREATED)
def bind_identity(
    body: BindIdentityBody,
    customer_id: int = Path(ge=1),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    customer = _customer_or_404(db, customer_id)
    row = ConsoleIdentityBinding(
        customer_id=customer.id, identity=body.identity.strip(), note=body.note
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"identity already bound: {body.identity.strip()}",
        ) from exc
    return {"binding": row.as_dict()}


@router.delete("/identities/{binding_id}")
def unbind_identity(
    binding_id: int = Path(ge=1), db: Session = Depends(get_db_session)
) -> dict[str, Any]:
    row = db.get(ConsoleIdentityBinding, binding_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no such binding: {binding_id}")
    payload = row.as_dict()
    db.delete(row)
    db.flush()
    return {"deleted": True, "binding": payload}


# ---------------------------------------------------------------------------
# 额度（单客户，按绑定身份聚合用量）
# ---------------------------------------------------------------------------


@router.get("/customers/{customer_id}/quota")
def admin_quota(
    customer_id: int = Path(ge=1),
    period: str = Query(..., min_length=7, max_length=7),
    db: Session = Depends(get_db_session),
    sub2api: Sub2ApiClient = Depends(get_sub2api_client),
) -> dict[str, Any]:
    try:
        validate_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    customer = _customer_or_404(db, customer_id)
    identities = customer_identities(db, customer)
    override = usage_by_unit(db, identities, period)
    result = quota_status(
        db, customer, period, metering=None, sub2api=sub2api, usage_override=override
    )
    return {
        "customer": _customer_dict(db, customer),
        "period": period,
        "identities": identities,
        "status": result.as_dict(),
    }


# ---------------------------------------------------------------------------
# 账本
# ---------------------------------------------------------------------------


@router.get("/ledger")
def admin_ledger(
    customer_id: int | None = Query(default=None, ge=1),
    period: str | None = Query(default=None, min_length=7, max_length=7),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    if period is not None:
        try:
            validate_period(period)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    stmt = select(LedgerEntry)
    if customer_id is not None:
        _customer_or_404(db, customer_id)
        stmt = stmt.where(LedgerEntry.customer_id == customer_id)
    if period is not None:
        stmt = stmt.where(LedgerEntry.period == period)
    entries = list(
        db.execute(stmt.order_by(LedgerEntry.id.desc()).limit(limit)).scalars().all()
    )
    total = sum(entry.amount_micro for entry in entries)
    return {
        "customer_id": customer_id,
        "period": period,
        "entries": [_entry_dict(e) for e in entries],
        "count": len(entries),
        "totals": {
            "amount_micro": total,
            "amount_yuan": micro_to_yuan_str(total),
            "note": "sum over returned rows (limited)",
        },
    }


# ---------------------------------------------------------------------------
# 用量（metering_records 聚合：轨道×调用者×单位）
# ---------------------------------------------------------------------------


@router.get("/usage/overview")
def usage_overview(
    period: str = Query(..., min_length=7, max_length=7),
    credential_track: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        validate_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if credential_track is not None and credential_track not in ("platform", "customer"):
        raise HTTPException(status_code=422, detail="credential_track must be platform|customer")
    start, end = period_bounds(period)
    conditions = [
        MeteringRecord.event_timestamp >= start,
        MeteringRecord.event_timestamp < end,
    ]
    if credential_track:
        conditions.append(MeteringRecord.credential_track == credential_track)

    rows = db.execute(
        select(
            MeteringRecord.credential_track,
            MeteringRecord.caller,
            MeteringRecord.unit,
            func.count(MeteringRecord.id),
            func.sum(MeteringRecord.quantity),
        )
        .where(*conditions)
        .group_by(
            MeteringRecord.credential_track, MeteringRecord.caller, MeteringRecord.unit
        )
        .order_by(MeteringRecord.credential_track, MeteringRecord.caller, MeteringRecord.unit)
    ).all()
    total_calls = sum(int(calls) for _, _, _, calls, _ in rows)
    by_track: dict[str, int] = {}
    by_unit: dict[str, int] = {}
    for track, _, unit, calls, quantity in rows:
        by_track[track] = by_track.get(track, 0) + int(calls)
        by_unit[unit] = by_unit.get(unit, 0) + int(quantity or 0)
    return {
        "period": period,
        "credential_track": credential_track,
        "breakdown": [
            {
                "credential_track": track,
                "caller": caller,
                "unit": unit,
                "calls": int(calls),
                "quantity": int(quantity or 0),
            }
            for track, caller, unit, calls, quantity in rows
        ],
        "totals": {"calls": total_calls, "by_track": by_track, "by_unit": by_unit},
    }


# ---------------------------------------------------------------------------
# 套餐（调价不发版）
# ---------------------------------------------------------------------------


@router.get("/plans")
def list_plans(db: Session = Depends(get_db_session)) -> dict[str, Any]:
    plans = list(db.execute(select(Plan).order_by(Plan.id)).scalars().all())
    return {"plans": [_plan_dict(p) for p in plans], "count": len(plans)}


class QuotaBody(BaseModel):
    unit: str = Field(min_length=1, max_length=16)
    included_quantity: int = Field(default=0, ge=0)
    overage_unit_price_micro: int = Field(default=0, ge=0)


class PlanBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    monthly_price_micro: int = Field(default=0, ge=0)
    is_active: bool = True
    quotas: list[QuotaBody] = Field(default_factory=list)


@router.put("/plans/{code}")
def put_plan(
    body: PlanBody,
    code: str = Path(min_length=1, max_length=32),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    plan = upsert_plan(
        db,
        code=code,
        name=body.name,
        monthly_price_micro=body.monthly_price_micro,
        is_active=body.is_active,
        quotas=[
            QuotaSpec(
                unit=quota.unit,
                included_quantity=quota.included_quantity,
                overage_unit_price_micro=quota.overage_unit_price_micro,
            )
            for quota in body.quotas
        ],
    )
    db.flush()
    return {"plan": _plan_dict(plan)}


# ---------------------------------------------------------------------------
# 凭据操作留痕（lex 控制台代理路径）
# ---------------------------------------------------------------------------


@router.get("/credentials/events")
def credential_events(
    username: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    stmt = select(ConsoleCredentialEvent).order_by(ConsoleCredentialEvent.id.desc()).limit(limit)
    if username:
        stmt = stmt.where(ConsoleCredentialEvent.username == username)
    rows = list(db.execute(stmt).scalars().all())
    return {
        "events": [row.as_dict() for row in rows],
        "count": len(rows),
        "note": (
            "issuance audit of the lex console proxy only; keys minted directly in "
            "the registry console are not listed (query registry /api/patch-keys as "
            "the owning user for the authoritative list)"
        ),
    }


__all__ = ["router"]
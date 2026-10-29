"""控制台端点（/api/console/*）（lex-platform-v1 任务 4.3）。

- ``GET  /api/console/auth/config``：公开 OIDC 配置（无密钥；SPA 据此发起
  Logto PKCE 登录）——登录未配置时 configured=false，前端如实呈现缺项。
- ``GET  /api/console/me``：登录身份 + 客户解析 + 是否后台角色。
- ``GET  /api/console/usage``：本客户周期用量（metering_records 只读）。
- ``GET  /api/console/billing``：本客户周期账本流水与合计（只读）。
- ``GET  /api/console/quota``：本客户周期额度水位 + 硬停预检 + 恢复途径输入。
- ``GET/POST/DELETE /api/console/credentials*``：经本服务代理 registry
  patch-keys（Bearer 透传客户 access token；跨域 cookie 难题绕行方案见
  registry_client 模块头）。铸造/吊销成功写 ``console_credential_events``。

鉴权：除 auth/config 外全部要求 ``Authorization: Bearer <Logto ID token>``；
凭据写操作额外要求 ``X-Registry-Token: <Logto access token>``（aud 为
registry 接受的 API resource）——ID token 只证明"你是谁"，access token 才是
registry 面承认的凭据，两者职责分离。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..billing.deps import get_db_session, get_sub2api_client
from ..billing.ledger import Ledger
from ..billing.models import Customer, LedgerEntry, Plan, validate_period
from ..billing.money import micro_to_yuan_str
from ..billing.plans import get_plan
from ..billing.quota import quota_status
from ..billing.sub2api import Sub2ApiClient
from ..config import get_settings
from ..metering.models import UNITS
from .auth import ConsoleUser, require_console_user
from .identity import (
    bindings_for_identity,
    customer_identities,
    resolve_console_customer,
    usage_by_unit,
    usage_rows,
    usage_totals,
)
from .models import (
    CREDENTIAL_ACTION_MINT,
    CREDENTIAL_ACTION_REVOKE,
    ConsoleCredentialEvent,
)
from .registry_client import RegistryPatchKeyClient, RegistryUnavailable, get_registry_client

router = APIRouter(prefix="/api/console", tags=["console"])


# ---------------------------------------------------------------------------
# 公开配置（登录入口用；无任何密钥）
# ---------------------------------------------------------------------------


@router.get("/auth/config")
def auth_config() -> dict[str, Any]:
    """控制台登录配置（公开）。未配置即如实上报缺项，前端显示阻塞态。"""
    settings = get_settings()
    issuer = settings.logto_oidc_base()
    configured = bool(issuer and settings.logto_client_id.strip())
    return {
        "configured": configured,
        "issuer": issuer,
        "client_id": settings.logto_client_id.strip(),
        "resource": settings.logto_resource.strip(),
        "scopes": settings.console_scope_list(),
        "organization_required": bool(settings.required_org_id_set()),
        "missing": [
            name
            for name, value in (
                ("LOGTO_ISSUER", issuer),
                ("LOGTO_CLIENT_ID", settings.logto_client_id.strip()),
            )
            if not value
        ],
    }


# ---------------------------------------------------------------------------
# 身份与客户
# ---------------------------------------------------------------------------


def _plan_of(db: Session, customer: Customer) -> Plan | None:
    return db.get(Plan, customer.plan_id)


def _customer_dict(db: Session, customer: Customer) -> dict[str, Any]:
    plan = _plan_of(db, customer)
    return {
        "id": customer.id,
        "name": customer.name,
        "sub2api_user_id": customer.sub2api_user_id,
        "plan_code": plan.code if plan else "",
        "plan_name": plan.name if plan else "",
        "monthly_price_micro": plan.monthly_price_micro if plan else 0,
        "monthly_price_yuan": micro_to_yuan_str(plan.monthly_price_micro) if plan else None,
        "status": customer.status,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
    }


def _bound_customer(db: Session, user: ConsoleUser) -> tuple[Customer | None, list[str]]:
    """登录身份 → (客户, 该客户全部计量身份)；未绑定返回 (None, [identity])。"""
    customer = resolve_console_customer(db, user.identity)
    if customer is None:
        return None, [user.identity]
    return customer, customer_identities(db, customer)


@router.get("/me")
def me(
    user: ConsoleUser = Depends(require_console_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """当前登录身份、客户绑定与后台角色判定。"""
    settings = get_settings()
    customer, identities = _bound_customer(db, user)
    binds = bindings_for_identity(db, user.identity)
    return {
        "identity": user.identity,
        "username": user.username,
        "email": user.email,
        "sub": user.sub,
        "roles": user.roles,
        "organizations": user.organizations,
        "is_admin": user.has_admin_role(settings.admin_role_set()),
        "customer": _customer_dict(db, customer) if customer else None,
        "identities": identities,
        "bindings": [b.as_dict() for b in binds],
    }


# ---------------------------------------------------------------------------
# 用量（metering_records 只读）
# ---------------------------------------------------------------------------


@router.get("/usage")
def usage(
    period: str = Query(..., min_length=7, max_length=7),
    user: ConsoleUser = Depends(require_console_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """本客户（含绑定身份）周期用量：合计 + 按单位/工具明细 + 最近调用。"""
    try:
        validate_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    customer, identities = _bound_customer(db, user)
    totals = usage_totals(db, identities, period)
    return {
        "period": period,
        "unit_catalog": list(UNITS),
        "customer": _customer_dict(db, customer) if customer else None,
        "identities": identities,
        "totals": {"calls": totals["calls"], "by_unit": totals["by_unit"]},
        "breakdown": usage_rows(db, identities, period),
        "recent": totals["recent"],
    }


# ---------------------------------------------------------------------------
# 账单（billing ledger 只读）
# ---------------------------------------------------------------------------


def _entry_dict(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
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


@router.get("/billing")
def billing(
    period: str = Query(..., min_length=7, max_length=7),
    user: ConsoleUser = Depends(require_console_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """本客户周期账本流水；未开户/未绑定返回 customer=null 的真实空态。"""
    try:
        validate_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    customer, _ = _bound_customer(db, user)
    if customer is None:
        return {"period": period, "customer": None, "entries": [], "totals": None}
    entries = Ledger(db).entries(customer.id, period)
    by_kind: dict[str, int] = {}
    for entry in entries:
        by_kind[entry.kind] = by_kind.get(entry.kind, 0) + entry.amount_micro
    return {
        "period": period,
        "customer": _customer_dict(db, customer),
        "entries": [_entry_dict(e) for e in entries],
        "totals": {
            "amount_micro": sum(e.amount_micro for e in entries),
            "amount_yuan": micro_to_yuan_str(sum(e.amount_micro for e in entries)),
            "by_kind": {
                kind: {"amount_micro": amount, "amount_yuan": micro_to_yuan_str(amount)}
                for kind, amount in sorted(by_kind.items())
            },
        },
    }


# ---------------------------------------------------------------------------
# 额度状态（fail-closed 预检 + 恢复途径输入）
# ---------------------------------------------------------------------------


@router.get("/quota")
def quota(
    period: str = Query(..., min_length=7, max_length=7),
    user: ConsoleUser = Depends(require_console_user),
    db: Session = Depends(get_db_session),
    sub2api: Sub2ApiClient = Depends(get_sub2api_client),
) -> dict[str, Any]:
    """本客户周期额度水位与硬停预检（用量按绑定身份聚合，权威实时）。

    恢复途径由前端按 denial_reason 渲染（lex-billing-metering 规格：
    控制台如实展示状态与恢复途径）；本端点给出判定输入。
    """
    try:
        validate_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    customer, identities = _bound_customer(db, user)
    if customer is None:
        return {
            "period": period,
            "customer": None,
            "status": None,
            "identities": identities,
            "recovery": ["not_provisioned"],
        }
    override = usage_by_unit(db, identities, period)
    status = quota_status(db, customer, period, metering=None, sub2api=sub2api,
                          usage_override=override)
    recovery: list[str] = []
    if not status.allowed:
        if status.exhausted_units:
            recovery.append("upgrade_quota")
        balance = status.balance
        if balance is not None and not balance.sufficient:
            recovery.append("top_up_balance" if balance.reachable
                            else "billing_plane_unreachable")
        recovery.append("contact_sales")
    return {
        "period": period,
        "customer": _customer_dict(db, customer),
        "status": status.as_dict(),
        "identities": identities,
        "recovery": recovery,
    }


# ---------------------------------------------------------------------------
# 凭据管理（registry patch-keys 代理）
# ---------------------------------------------------------------------------


def _registry_token(request: Request) -> str:
    token = (request.headers.get("x-registry-token") or "").strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail=(
                "missing X-Registry-Token: the console must send the Logto access "
                "token (aud=registry API resource) for credential operations"
            ),
        )
    return token


def _registry_error(status_code: int, payload: Any) -> HTTPException:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, str) or not detail:
        detail = f"registry patch-keys returned {status_code}"
    return HTTPException(status_code=status_code, detail=detail)


class MintBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)


def _record_event(
    db: Session,
    *,
    action: str,
    key_id: str,
    key_name: str | None,
    key_prefix: str | None,
    username: str,
    groups: list[str] | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        ConsoleCredentialEvent(
            action=action,
            key_id=key_id,
            key_name=key_name,
            key_prefix=key_prefix,
            username=username,
            groups_json=json.dumps(groups or [], ensure_ascii=False),
            detail=detail,
        )
    )
    db.flush()


@router.get("/credentials")
def list_credentials(
    request: Request,
    user: ConsoleUser = Depends(require_console_user),
    registry: RegistryPatchKeyClient = Depends(get_registry_client),
) -> JSONResponse:
    """列出当前客户在 registry 的凭据（元数据；明文/哈希不返回）。"""
    try:
        status_code, payload = registry.list_keys(_registry_token(request))
    except RegistryUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if status_code >= 400:
        raise _registry_error(status_code, payload)
    return JSONResponse(status_code=status_code, content=payload)


@router.post("/credentials", status_code=201)
def mint_credential(
    body: MintBody,
    request: Request,
    user: ConsoleUser = Depends(require_console_user),
    db: Session = Depends(get_db_session),
    registry: RegistryPatchKeyClient = Depends(get_registry_client),
) -> JSONResponse:
    """铸造长命凭据（不设过期）；明文仅在本次响应中出现一次。"""
    try:
        status_code, payload = registry.mint_key(_registry_token(request), body.name)
    except RegistryUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        _record_event(
            db,
            action=CREDENTIAL_ACTION_MINT,
            key_id="",
            key_name=body.name,
            key_prefix=None,
            username=user.identity,
            detail=str(detail or f"registry {status_code}")[:500],
        )
        # 失败留痕必须先落库：get_db 依赖在异常路径会回滚
        db.commit()
        raise _registry_error(status_code, payload)
    info = payload.get("info", {}) if isinstance(payload, dict) else {}
    _record_event(
        db,
        action=CREDENTIAL_ACTION_MINT,
        key_id=str(info.get("key_id", "")),
        key_name=str(info.get("name") or body.name),
        key_prefix=str(info.get("key_prefix", "")) or None,
        username=user.identity,
        groups=info.get("groups") if isinstance(info.get("groups"), list) else None,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.delete("/credentials/{key_id}")
def revoke_credential(
    request: Request,
    key_id: str = Path(min_length=1, max_length=128),
    user: ConsoleUser = Depends(require_console_user),
    db: Session = Depends(get_db_session),
    registry: RegistryPatchKeyClient = Depends(get_registry_client),
) -> JSONResponse:
    """吊销凭据（不可逆；registry 侧即时生效，下一次调用 401）。"""
    try:
        status_code, payload = registry.revoke_key(_registry_token(request), key_id)
    except RegistryUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        _record_event(
            db,
            action=CREDENTIAL_ACTION_REVOKE,
            key_id=key_id,
            key_name=None,
            key_prefix=None,
            username=user.identity,
            detail=str(detail or f"registry {status_code}")[:500],
        )
        db.commit()  # 失败留痕必须先落库（异常路径会回滚）
        raise _registry_error(status_code, payload)
    info = payload if isinstance(payload, dict) else {}
    _record_event(
        db,
        action=CREDENTIAL_ACTION_REVOKE,
        key_id=str(info.get("key_id") or key_id),
        key_name=str(info.get("name")) if info.get("name") else None,
        key_prefix=str(info.get("key_prefix")) if info.get("key_prefix") else None,
        username=user.identity,
        groups=info.get("groups") if isinstance(info.get("groups"), list) else None,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/credentials/events")
def credential_events(
    limit: int = Query(default=50, ge=1, le=200),
    user: ConsoleUser = Depends(require_console_user),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """本客户经 lex 控制台发生的凭据操作留痕（审计视图；实时列表以 registry 为准）。"""
    rows = (
        db.execute(
            select(ConsoleCredentialEvent)
            .where(ConsoleCredentialEvent.username == user.identity)
            .order_by(ConsoleCredentialEvent.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "identity": user.identity,
        "events": [row.as_dict() for row in rows],
        "note": "lex-console only; keys minted directly in the registry console are not listed here",
    }


__all__ = ["router"]
"""客户开户：Customer 行 + sub2api 代建/认领账户（幂等）。

（照 fd-wire billing/customers.py 移植；lex 适配=①默认幂等键对客户名做
散列——Idempotency-Key 是 HTTP 头，必须 ASCII，中文客户名直拼会炸；
②建户契约按生产实测补齐 email/password（2026-10-06 开户演练）；③email
前置认领——同名邮箱账户已存在（如客户先前在其面板首登自动开立）时直接
归户，不重复建。）

密码说明：sub2api 建户契约要求 password ≥6，但面板登录走 Logto SSO，
密码仅为满足契约随机生成、不落任何存储。
"""

from __future__ import annotations

import hashlib
import re
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Customer, CustomerStatus
from .plans import get_plan
from .sub2api import Sub2ApiClient


def _default_idempotency_key(name: str) -> str:
    """客户名 → ASCII 安全的默认幂等键（HTTP 头不能带非 ASCII）。"""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return f"customer:{digest}"


def _default_username(name: str) -> str:
    """客户名 → 可打印 ASCII 用户名（中文名降级为散列短 slug）。"""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if len(slug) >= 3:
        return slug[:64]
    return "lex-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def _default_email(name: str, plan_code: str) -> str:
    """未给邮箱时的确定性占位（运营侧最好传客户真实邮箱以对齐 SSO）。"""
    digest = hashlib.sha256(f"{name}:{plan_code}".encode("utf-8")).hexdigest()[:16]
    return f"customer-{digest}@customers.lex.internal"


def ensure_customer(
    session: Session,
    sub2api: Sub2ApiClient,
    *,
    name: str,
    plan_code: str,
    email: str | None = None,
    username: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[Customer, bool]:
    """建客户（幂等）：已存在（同名同档）直接返回；否则 sub2api 认领/建户后落库。"""
    plan = get_plan(session, plan_code)
    existing = session.execute(
        select(Customer).where(Customer.name == name, Customer.plan_id == plan.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    key = idempotency_key or _default_idempotency_key(f"{name}:{plan.code}")
    resolved_email = (email or "").strip() or _default_email(name, plan.code)
    user = sub2api.find_user_by_email(resolved_email)
    if user is None:
        user = sub2api.create_user(
            email=resolved_email,
            password=secrets.token_urlsafe(24),
            username=(username or "").strip() or _default_username(name),
            notes=f"lex customer: {name} (plan={plan.code})",
            idempotency_key=key,
        )

    # 同键并发重试：对手可能已插入同 sub2api_user_id 的行
    dup = session.execute(
        select(Customer).where(Customer.sub2api_user_id == user.id)
    ).scalar_one_or_none()
    if dup is not None:
        return dup, False

    customer = Customer(
        name=name,
        sub2api_user_id=user.id,
        plan_id=plan.id,
        status=CustomerStatus.ACTIVE.value,
    )
    try:
        with session.begin_nested():
            session.add(customer)
            session.flush()
    except IntegrityError:
        existing = session.execute(
            select(Customer).where(Customer.name == name, Customer.plan_id == plan.id)
        ).scalar_one_or_none()
        if existing is None:
            raise
        return existing, False
    return customer, True
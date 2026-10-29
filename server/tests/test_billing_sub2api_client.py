"""sub2api admin 客户端契约（2026-10-06 按生产实测重写）：

x-api-key 头 / envelope 业务码 / 带符号金额→operation / 余额数值无换算 /
email 认领 / 探针 fail-closed。全部经 httpx.MockTransport，绝不真实调用。"""

from __future__ import annotations

import json

import httpx
import pytest

from fd_lex_api.billing import Sub2ApiClient, Sub2ApiError

from test_billing_common import BASE, FakeSub2Api, make_engine, make_plan


def test_adjust_balance_sign_maps_to_operation_with_idempotency_key() -> None:
    fake = FakeSub2Api()
    fake.add_user("u-1", balance_micro=1_000_000)
    client = fake.client()

    client.adjust_balance(user_id="u-1", amount_micro=-400_000, idempotency_key="k-1")
    call = fake.adjust_calls[0]
    assert call["idem"] == "k-1"
    assert call["auth"] == "test-admin-key"  # x-api-key，非 Bearer
    assert json.loads(call["body"]) == {"balance": 400_000, "operation": "subtract"}
    assert fake.balance("u-1") == 600_000

    client.adjust_balance(user_id="u-1", amount_micro=+100, idempotency_key="k-2")
    assert json.loads(fake.adjust_calls[1]["body"]) == {"balance": 100, "operation": "add"}
    assert fake.balance("u-1") == 600_100


def test_adjust_requires_explicit_key_and_nonzero_amount() -> None:
    fake = FakeSub2Api()
    client = fake.client()
    with pytest.raises(ValueError):
        client.adjust_balance(user_id="u-1", amount_micro=-1, idempotency_key="")
    with pytest.raises(ValueError):
        client.adjust_balance(user_id="u-1", amount_micro=0, idempotency_key="k")


def test_replay_same_key_charged_once_via_server_cache() -> None:
    """同幂等键重放：假件服务端缓存返回同响应，余额只动一次。"""
    fake = FakeSub2Api()
    fake.add_user("u-1", balance_micro=1_000_000)
    client = fake.client()
    client.adjust_balance(user_id="u-1", amount_micro=-100, idempotency_key="same")
    client.adjust_balance(user_id="u-1", amount_micro=-100, idempotency_key="same")
    assert len(fake.adjust_calls) == 2  # 两次调用
    assert fake.balance("u-1") == 1_000_000 - 100  # 净一次扣减


def test_read_user_parses_envelope_and_username_email_status() -> None:
    """读取面：envelope 解包 + username/email/status + 数值原样（微元），x-api-key。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={
            "code": 0, "message": "success",
            "data": {"id": 54, "email": "lex-demo@findmail.com",
                     "username": "lexdemocustomer", "balance": 15_000_000,
                     "status": "active"},
        })

    client = Sub2ApiClient(
        base_url=BASE, admin_key="key-x",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    user = client.read_user("54")
    assert captured["auth"] == "key-x"
    assert (user.id, user.name, user.email, user.status) == (
        "54", "lexdemocustomer", "lex-demo@findmail.com", "active",
    )
    assert user.balance_micro == 15_000_000  # 写读同单位，无换算


def test_business_code_nonzero_raises_even_on_http_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 400, "message": "email already exists"})

    client = Sub2ApiClient(
        base_url=BASE, admin_key="k",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(Sub2ApiError, match="email already exists"):
        client.read_user("1")


def test_unreachable_maps_to_unavailable_and_probe_fail_closed() -> None:
    fake = FakeSub2Api()
    fake.add_user("u-1", balance_micro=1)
    client = fake.client()
    fake.fail_reads_left = 2  # read_user 与 probe 各消耗一次 503

    with pytest.raises(Sub2ApiError):
        client.read_user("u-1")  # 503 → Sub2ApiUnavailable

    probe = client.probe("u-1", min_balance_micro=0)
    assert probe.reachable is False and probe.sufficient is False  # fail-closed
    assert probe.error is not None


def test_probe_sufficient_boundary() -> None:
    fake = FakeSub2Api()
    fake.add_user("u-1", balance_micro=1_000)
    client = fake.client()
    assert client.probe("u-1", min_balance_micro=1_000).sufficient is True
    assert client.probe("u-1", min_balance_micro=1_001).sufficient is False


def test_4xx_raises_contract_error() -> None:
    fake = FakeSub2Api()
    client = fake.client()  # u-missing 不存在 → 404
    with pytest.raises(Sub2ApiError) as exc_info:
        client.read_user("u-missing")
    assert exc_info.value.status_code == 404


def test_create_user_contract_fields_and_password_floor() -> None:
    fake = FakeSub2Api()
    client = fake.client()
    user = client.create_user(
        email="lexa@findmail.com", password="secret-123",
        username="lex-a", notes="lex customer: A (plan=std)",
    )
    create_calls = [
        c for c in fake.calls if c["op"] == "POST" and c["url"].endswith("/api/v1/admin/users")
    ]
    body = json.loads(create_calls[0]["body"])
    assert body["email"] == "lexa@findmail.com"
    assert body["password"] == "secret-123"
    assert body["username"] == "lex-a"
    assert user.email == "lexa@findmail.com"
    assert user.balance_micro == 0  # 新户零余额（预检 402 的起点）
    with pytest.raises(ValueError):
        client.create_user(email="x@y.z", password="12345")  # < 6 位


def test_find_user_by_email_exact_hit_and_miss() -> None:
    fake = FakeSub2Api()
    fake.add_user("54", name="lexdemocustomer", balance_micro=1,
                  email="lex-demo@findmail.com")
    client = fake.client()
    found = client.find_user_by_email("lex-demo@findmail.com")
    assert found is not None and found.id == "54"
    assert client.find_user_by_email("nobody@findmail.com") is None


def test_ensure_customer_default_key_is_ascii_safe() -> None:
    """默认幂等键对客户名做散列：HTTP 头不能带非 ASCII（中文客户名不炸）。"""
    from sqlalchemy.orm import Session

    from fd_lex_api.billing import ensure_customer

    fake = FakeSub2Api()
    engine = make_engine()
    with Session(engine) as session:
        plan = make_plan(session, code="std")
        session.commit()
        customer, created = ensure_customer(
            session, fake.client(), name="华东法务客户", plan_code="std"
        )
        assert created is True
        create_calls = [
            c for c in fake.calls
            if c["op"] == "POST" and c["url"].endswith("/api/v1/admin/users")
        ]
        key = create_calls[0]["idem"]
        assert key is not None and key.isascii() and key.startswith("customer:")
        # 未给邮箱 → 确定性占位邮箱（可打印 ASCII）
        body = json.loads(create_calls[0]["body"])
        assert body["email"].endswith("@customers.lex.internal")
        assert customer.sub2api_user_id.startswith("su-")


def test_ensure_customer_adopts_existing_email_account() -> None:
    """邮箱已有 sub2api 账户（如客户面板首登自动开立）→ 认领归户，不重复建。"""
    from sqlalchemy.orm import Session

    from fd_lex_api.billing import ensure_customer

    fake = FakeSub2Api()
    fake.add_user("su-existing", name="lexdemo", balance_micro=0,
                  email="lex-demo@findmail.com")
    engine = make_engine()
    with Session(engine) as session:
        make_plan(session, code="std")
        session.commit()
        customer, created = ensure_customer(
            session, fake.client(), name="认领客户", plan_code="std",
            email="lex-demo@findmail.com",
        )
        assert created is True
        assert customer.sub2api_user_id == "su-existing"
        create_calls = [
            c for c in fake.calls
            if c["op"] == "POST" and c["url"].endswith("/api/v1/admin/users")
        ]
        assert create_calls == []  # 未触发建户
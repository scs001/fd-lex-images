"""运营后台面（/api/admin/*）：双路径鉴权/客户/身份绑定/套餐/账本/用量/留痕。

鉴权两条路径都测：X-Admin-Token（= INTERNAL_API_TOKEN，fail-closed）与
Logto ID token 的 roles 命中 ADMIN_ROLES（verify_id_token 换成假件）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from fd_lex_api.admin_api.auth import require_admin
from fd_lex_api.billing import Base as BillingBase
from fd_lex_api.billing import Customer, LedgerEntry, Plan, PlanQuota
from fd_lex_api.billing.deps import get_sub2api_client
from fd_lex_api.config import reset_settings
from fd_lex_api.console_api.models import ConsoleBase
from fd_lex_api.main import app
from fd_lex_api.metering.db import MeteringBase, get_engine, reset_metering_runtime
from fd_lex_api.metering.models import MeteringRecord

from test_billing_common import FakeSub2Api

TOKEN = "test-internal-token"
HEADERS = {"X-Admin-Token": TOKEN}

ADMIN_USER = {
    "username": "lexadmin",
    "email": "admin@findmail.com",
    "sub": "admin-1",
    "roles": ["lex-admin"],
    "organizations": ["hnrbfpgq2717"],
}


@pytest.fixture()
def admin_env(monkeypatch, tmp_path):
    db_path = tmp_path / "lex_admin_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setenv("ADMIN_ROLES", "lex-admin")
    monkeypatch.delenv("LOGTO_REQUIRED_ORG_IDS", raising=False)
    reset_metering_runtime()
    engine = get_engine()
    BillingBase.metadata.create_all(engine)
    MeteringBase.metadata.create_all(engine)
    ConsoleBase.metadata.create_all(engine)

    fake_sub2api = FakeSub2Api()
    app.dependency_overrides[get_sub2api_client] = lambda: fake_sub2api.client()
    try:
        yield TestClient(app), fake_sub2api, engine
    finally:
        app.dependency_overrides.clear()
        reset_metering_runtime()
        reset_settings()


def seed_plan_customer(engine, *, name: str = "识律演示客户", sub2api_id: str = "8tajhoprelg0"):
    with Session(engine) as session:
        plan = Plan(code="standard", name="标准版", monthly_price_micro=2_000_000)
        session.add(plan)
        session.flush()
        session.add(
            PlanQuota(
                plan_id=plan.id, unit="line", included_quantity=1000,
                overage_unit_price_micro=4000,
            )
        )
        customer = Customer(name=name, plan_id=plan.id, sub2api_user_id=sub2api_id)
        session.add(customer)
        session.commit()
        return customer.id


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------


def test_admin_requires_credentials(admin_env) -> None:
    client, _, _ = admin_env
    assert client.get("/api/admin/whoami").status_code == 401
    assert (
        client.get("/api/admin/whoami", headers={"X-Admin-Token": "wrong"}).status_code == 401
    )


def test_admin_fail_closed_when_token_unconfigured(admin_env, monkeypatch) -> None:
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
    reset_settings()
    client, _, _ = admin_env
    resp = client.get("/api/admin/whoami", headers=HEADERS)
    assert resp.status_code == 403
    assert "not configured" in resp.json()["detail"]


def test_admin_accepts_internal_token(admin_env) -> None:
    client, _, _ = admin_env
    body = client.get("/api/admin/whoami", headers=HEADERS).json()
    assert body["via"] == "internal-token"


def test_admin_accepts_logto_admin_role(admin_env, monkeypatch) -> None:
    """角色路径不受客户组织门禁约束：运营（内部身份）不属 lex-customers 也应放行。"""
    client, _, _ = admin_env
    import fd_lex_api.admin_api.auth as admin_auth

    monkeypatch.setenv("LOGTO_ISSUER", "https://auth.test.example")
    monkeypatch.setenv("LOGTO_CLIENT_ID", "client-lex")
    # 组织门禁开启（客户面要求），后台角色面必须显式绕过
    monkeypatch.setenv("LOGTO_REQUIRED_ORG_IDS", "hnrbfpgq2717")
    reset_settings()

    from fd_lex_api.console_api.auth import ConsoleUser

    def fake_verify(token: str, *, enforce_organization: bool = True) -> ConsoleUser:
        assert enforce_organization is False, "admin path must not apply the customer org gate"
        return ConsoleUser(
            identity="lexadmin", username="lexadmin", email="admin@findmail.com",
            sub="admin-1", roles=["lex-admin"], organizations=[],
        )

    monkeypatch.setattr(admin_auth, "verify_id_token", fake_verify)
    body = client.get(
        "/api/admin/whoami", headers={"Authorization": "Bearer admin-token"}
    ).json()
    assert body == {"via": "logto-role", "identity": "lexadmin", "roles": ["lex-admin"]}

    # 非管理员角色 → 403
    monkeypatch.setattr(
        admin_auth,
        "verify_id_token",
        lambda token, **kwargs: ConsoleUser(
            identity="someone", username="someone", email=None, sub="u2", roles=["viewer"]
        ),
    )
    assert (
        client.get("/api/admin/whoami", headers={"Authorization": "Bearer x"}).status_code
        == 403
    )
    reset_settings()


# ---------------------------------------------------------------------------
# 客户与身份绑定
# ---------------------------------------------------------------------------


def test_customer_create_list_patch(admin_env) -> None:
    client, fake_sub2api, engine = admin_env
    seed_plan_customer(engine)
    listing = client.get("/api/admin/customers", headers=HEADERS).json()
    assert listing["count"] == 1
    assert listing["customers"][0]["plan_code"] == "standard"

    created = client.post(
        "/api/admin/customers",
        headers=HEADERS,
        json={"name": "新客户", "plan_code": "standard"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["created"] is True
    assert body["customer"]["sub2api_user_id"]

    patched = client.patch(
        f"/api/admin/customers/{body['customer']['id']}",
        headers=HEADERS,
        json={"status": "suspended"},
    )
    assert patched.json()["customer"]["status"] == "suspended"
    bad = client.patch(
        f"/api/admin/customers/{body['customer']['id']}",
        headers=HEADERS,
        json={"status": "bogus"},
    )
    assert bad.status_code == 422


def test_customer_create_surfaces_sub2api_failure(admin_env) -> None:
    client, _, engine = admin_env
    seed_plan_customer(engine)
    # 换一个必失败的 sub2api 假件：开户失败如实 502（不静默落本地客户行）
    from fd_lex_api.billing.sub2api import Sub2ApiClient, Sub2ApiUnavailable

    class BoomClient(Sub2ApiClient):
        def find_user_by_email(self, email: str):  # type: ignore[override]
            return None  # 邮箱无既有账户 → 进入 create 路径

        def create_user(self, **kwargs):  # type: ignore[override]
            raise Sub2ApiUnavailable("sub2api 不可达: connect timeout")

    app.dependency_overrides[get_sub2api_client] = lambda: BoomClient(base_url="http://x")
    resp = client.post(
        "/api/admin/customers",
        headers=HEADERS,
        json={"name": "失败客户", "plan_code": "standard"},
    )
    assert resp.status_code == 502
    assert "sub2api" in resp.json()["detail"]


def test_identity_bind_and_unbind(admin_env) -> None:
    client, _, engine = admin_env
    customer_id = seed_plan_customer(engine)
    created = client.post(
        f"/api/admin/customers/{customer_id}/identities",
        headers=HEADERS,
        json={"identity": "lexdemocustomer", "note": "演示账号"},
    )
    assert created.status_code == 201
    binding_id = created.json()["binding"]["id"]

    dupe = client.post(
        f"/api/admin/customers/{customer_id}/identities",
        headers=HEADERS,
        json={"identity": "lexdemocustomer"},
    )
    assert dupe.status_code == 409

    listing = client.get(
        f"/api/admin/customers/{customer_id}/identities", headers=HEADERS
    ).json()
    assert listing["identities"][0]["identity"] == "lexdemocustomer"
    assert "8tajhoprelg0" in listing["metering_identities"]

    deleted = client.delete(f"/api/admin/identities/{binding_id}", headers=HEADERS)
    assert deleted.json()["deleted"] is True


def test_admin_quota_uses_bound_identities(admin_env) -> None:
    client, _, engine = admin_env
    customer_id = seed_plan_customer(engine)
    client.post(
        f"/api/admin/customers/{customer_id}/identities",
        headers=HEADERS,
        json={"identity": "lexdemocustomer"},
    )
    with Session(engine) as session:
        session.add(
            MeteringRecord(
                event_timestamp=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
                request_id="req-admin-1",
                caller="lexdemocustomer",
                credential_track="customer",
                server_name="fd-legal-search-mcp",
                tool_name="law_reference",
                quantity=25,
                unit="line",
                source="customer",
            )
        )
        session.commit()
    body = client.get(
        f"/api/admin/customers/{customer_id}/quota?period=2026-10", headers=HEADERS
    ).json()
    units = {u["unit"]: u for u in body["status"]["units"]}
    assert units["line"]["used_quantity"] == 25


# ---------------------------------------------------------------------------
# 套餐（调价不发版）
# ---------------------------------------------------------------------------


def test_plan_upsert_and_list(admin_env) -> None:
    client, _, _ = admin_env
    resp = client.put(
        "/api/admin/plans/pro",
        headers=HEADERS,
        json={
            "name": "专业版",
            "monthly_price_micro": 9_900_000,
            "is_active": True,
            "quotas": [
                {"unit": "line", "included_quantity": 100_000,
                 "overage_unit_price_micro": 3000},
                {"unit": "call", "included_quantity": 5_000,
                 "overage_unit_price_micro": 200000},
            ],
        },
    )
    assert resp.status_code == 200
    plan = resp.json()["plan"]
    assert plan["monthly_price_yuan"] == "¥9.90"
    quotas = {q["unit"]: q for q in plan["quotas"]}
    # 展示口径沿用 billing.money（两位小数量化）；单价细粒度以 micro 为准
    assert quotas["line"]["overage_unit_price_micro"] == 3000
    assert quotas["call"]["included_quantity"] == 5_000

    # 调价：同 code 再 PUT，价格即时以新值读出（无发版动作）
    client.put(
        "/api/admin/plans/pro",
        headers=HEADERS,
        json={"name": "专业版", "monthly_price_micro": 12_000_000, "is_active": True,
              "quotas": [{"unit": "line", "included_quantity": 100_000,
                          "overage_unit_price_micro": 5000}]},
    )
    listing = client.get("/api/admin/plans", headers=HEADERS).json()
    pro = next(p for p in listing["plans"] if p["code"] == "pro")
    assert pro["monthly_price_yuan"] == "¥12.00"
    pro_quotas = {q["unit"]: q for q in pro["quotas"]}
    assert pro_quotas["line"]["overage_unit_price_micro"] == 5000


# ---------------------------------------------------------------------------
# 账本 / 用量 / 凭据留痕
# ---------------------------------------------------------------------------


def test_admin_ledger_filter_by_customer(admin_env) -> None:
    client, _, engine = admin_env
    customer_id = seed_plan_customer(engine)
    with Session(engine) as session:
        session.add(
            LedgerEntry(
                customer_id=customer_id, kind="grant", unit=None, quantity=0,
                amount_micro=2_000_000, period="2026-10",
                idempotency_key="grant:test", sub2api_applied=False,
            )
        )
        session.commit()
    body = client.get(
        f"/api/admin/ledger?customer_id={customer_id}&period=2026-10", headers=HEADERS
    ).json()
    assert body["count"] == 1
    assert body["entries"][0]["amount_yuan"] == "¥2.00"
    assert body["totals"]["amount_micro"] == 2_000_000


def test_admin_usage_overview(admin_env) -> None:
    client, _, engine = admin_env
    with Session(engine) as session:
        session.add(
            MeteringRecord(
                event_timestamp=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
                request_id="req-admin-2",
                caller="lexdemocustomer",
                credential_track="customer",
                server_name="fd-legal-search-mcp",
                tool_name="case_search",
                quantity=1250,
                unit="line",
                source="customer",
            )
        )
        session.commit()
    body = client.get("/api/admin/usage/overview?period=2026-10", headers=HEADERS).json()
    assert body["totals"]["calls"] == 1
    assert body["totals"]["by_unit"] == {"line": 1250}
    assert body["breakdown"][0]["caller"] == "lexdemocustomer"
    bad = client.get(
        "/api/admin/usage/overview?period=2026-10&credential_track=nope", headers=HEADERS
    )
    assert bad.status_code == 422


def test_admin_credential_events_listing(admin_env) -> None:
    client, _, engine = admin_env
    with Session(engine) as session:
        from fd_lex_api.console_api.models import ConsoleCredentialEvent

        session.add(
            ConsoleCredentialEvent(
                action="mint", key_id="k-9", key_name="console-key",
                key_prefix="wgk-Abc", username="lexdemocustomer",
                groups_json='["lex-customers"]',
            )
        )
        session.commit()
    body = client.get(
        "/api/admin/credentials/events?username=lexdemocustomer", headers=HEADERS
    ).json()
    assert body["count"] == 1
    assert body["events"][0]["key_name"] == "console-key"
    assert body["events"][0]["groups"] == ["lex-customers"]
    assert "registry console" in body["note"]


def test_admin_bad_period_rejected(admin_env) -> None:
    client, _, _ = admin_env
    assert (
        client.get("/api/admin/usage/overview?period=2026-99", headers=HEADERS).status_code
        == 422
    )
    assert client.get("/api/admin/ledger?period=bad", headers=HEADERS).status_code == 422
"""控制台面（/api/console/*）：鉴权/身份解析/用量/账单/额度/registry 凭据代理。

测试隔离：临时文件库 + reset 运行时缓存；registry 与 sub2api 全部换假件
（绝不真实调用生产设施——registry 允许只读实测，但测试一律离线）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from fd_lex_api.billing import Base as BillingBase
from fd_lex_api.billing import Customer, LedgerEntry, Plan, PlanQuota
from fd_lex_api.billing.deps import get_sub2api_client
from fd_lex_api.config import reset_settings
from fd_lex_api.console_api.auth import ConsoleUser, require_console_user
from fd_lex_api.console_api.models import (
    ConsoleBase,
    ConsoleCredentialEvent,
    ConsoleIdentityBinding,
)
from fd_lex_api.console_api.registry_client import get_registry_client
from fd_lex_api.main import app
from fd_lex_api.metering.db import MeteringBase, get_engine, reset_metering_runtime
from fd_lex_api.metering.models import MeteringRecord

from test_billing_common import FakeSub2Api

TOKEN = "test-internal-token"
USER = ConsoleUser(
    identity="lexdemocustomer",
    username="lexdemocustomer",
    email="lex-demo@findmail.com",
    sub="sub-123",
    roles=["lex-user"],
    organizations=["hnrbfpgq2717"],
)


class FakeRegistry:
    """registry patch-keys 假件：记录调用并返回契约形状的响应。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.keys = [
            {
                "key_id": "key-1",
                "name": "demo-key",
                "key_prefix": "wgk-Abc123",
                "username": USER.identity,
                "email": USER.email,
                "provider": "oauth2",
                "egress_user": "8tajhoprelg0",
                "groups": ["lex-customers"],
                "status": "active",
                "created_at": "2026-10-05T09:31:37",
                "last_used_at": None,
                "revoked_at": None,
            }
        ]
        self.mint_status = 201
        self.registry_token_seen: str | None = None

    def list_keys(self, token: str):
        self.calls.append(("GET", "/api/patch-keys", token))
        self.registry_token_seen = token
        return 200, {"total": len(self.keys), "items": self.keys}

    def mint_key(self, token: str, name: str):
        self.calls.append(("POST", "/api/patch-keys", token))
        self.registry_token_seen = token
        if self.mint_status >= 400:
            return self.mint_status, {"detail": "too many active keys"}
        return 201, {
            "key": "wgk-PlaintextOnce123",
            "info": {
                "key_id": "key-2",
                "name": name,
                "key_prefix": "wgk-Plaintex",
                "username": USER.identity,
                "email": USER.email,
                "groups": ["lex-customers"],
                "status": "active",
            },
        }

    def revoke_key(self, token: str, key_id: str):
        self.calls.append(("DELETE", f"/api/patch-keys/{key_id}", token))
        self.registry_token_seen = token
        if key_id == "missing":
            return 404, {"detail": "Key not found"}
        return 200, {
            "key_id": key_id,
            "name": "demo-key",
            "key_prefix": "wgk-Abc123",
            "username": USER.identity,
            "groups": ["lex-customers"],
            "status": "revoked",
        }


@pytest.fixture()
def console_env(monkeypatch, tmp_path):
    """临时库 + 假 registry/sub2api + 控制台身份（dependency_overrides）。"""
    db_path = tmp_path / "lex_console_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.delenv("PLATFORM_IDENTITIES", raising=False)
    reset_metering_runtime()

    engine = get_engine()
    BillingBase.metadata.create_all(engine)
    MeteringBase.metadata.create_all(engine)
    ConsoleBase.metadata.create_all(engine)
    with engine.begin() as conn:
        # metering_records 由 metering 模块的模型建表（与 billing 同库）
        pass

    fake_sub2api = FakeSub2Api()
    fake_sub2api.add_user("8tajhoprelg0", balance_micro=50_000_000)
    fake_registry = FakeRegistry()

    app.dependency_overrides[require_console_user] = lambda: USER
    app.dependency_overrides[get_registry_client] = lambda: fake_registry
    app.dependency_overrides[get_sub2api_client] = lambda: fake_sub2api.client()
    try:
        yield TestClient(app), fake_registry, fake_sub2api, engine
    finally:
        app.dependency_overrides.clear()
        reset_metering_runtime()
        reset_settings()


def seed_customer(engine, *, identity: str = USER.identity) -> int:
    """套餐 + 客户 + 身份绑定 + 两条计量记录（一条 customer 一条 platform）。"""
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        plan = Plan(code="standard", name="标准版", monthly_price_micro=2_000_000)
        session.add(plan)
        session.flush()
        session.add(
            PlanQuota(
                plan_id=plan.id,
                unit="line",
                included_quantity=1000,
                overage_unit_price_micro=4000,
            )
        )
        session.add(
            PlanQuota(
                plan_id=plan.id,
                unit="call",
                included_quantity=100,
                overage_unit_price_micro=0,
            )
        )
        customer = Customer(
            name="识律演示客户", plan_id=plan.id, sub2api_user_id="8tajhoprelg0"
        )
        session.add(customer)
        session.flush()
        session.add(
            ConsoleIdentityBinding(customer_id=customer.id, identity=identity, note="测试绑定")
        )
        session.add(
            MeteringRecord(
                event_timestamp=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
                request_id="req-console-1",
                caller=identity,
                credential_track="customer",
                server_name="fd-legal-search-mcp",
                tool_name="law_reference",
                quantity=42,
                unit="line",
                source="customer",
            )
        )
        session.add(
            MeteringRecord(
                event_timestamp=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc),
                request_id="req-console-2",
                caller=identity,
                credential_track="customer",
                server_name="fd-legal-search-mcp",
                tool_name="contract_draft",
                quantity=1,
                unit="call",
                source="customer",
            )
        )
        session.add(
            MeteringRecord(
                event_timestamp=datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc),
                request_id="req-console-3",
                caller="platform-bot",
                credential_track="platform",
                server_name="internal",
                tool_name=None,
                quantity=999,
                unit="line",
                source="platform-internal",
            )
        )
        session.commit()
        return customer.id


# ---------------------------------------------------------------------------
# 鉴权与配置
# ---------------------------------------------------------------------------


def test_auth_config_reports_missing_when_unconfigured(console_env, monkeypatch) -> None:
    monkeypatch.delenv("LOGTO_ISSUER", raising=False)
    monkeypatch.delenv("LOGTO_CLIENT_ID", raising=False)
    reset_settings()
    client, _, _, _ = console_env
    resp = client.get("/api/console/auth/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert set(body["missing"]) == {"LOGTO_ISSUER", "LOGTO_CLIENT_ID"}


def test_console_endpoints_require_bearer(console_env) -> None:
    """无 overrides 时：无 Bearer 401；带无效 token 401（真校验路径）。"""
    app.dependency_overrides.pop(require_console_user, None)
    client, _, _, _ = console_env
    assert client.get("/api/console/me").status_code == 401
    assert (
        client.get("/api/console/me", headers={"Authorization": "Bearer nope"}).status_code
        in (401, 503)
    )


def test_verify_id_token_rejects_wrong_audience(monkeypatch) -> None:
    """真签名校验：错 audience 401、组织不命中 403（用本地 EC 密钥对）。"""
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import ec

    from fd_lex_api.console_api import auth as console_auth

    key = ec.generate_private_key(ec.SECP384R1())
    monkeypatch.setenv("LOGTO_ISSUER", "https://auth.test.example")
    monkeypatch.setenv("LOGTO_CLIENT_ID", "client-lex")
    monkeypatch.setenv("LOGTO_REQUIRED_ORG_IDS", "hnrbfpgq2717")
    reset_settings()

    class StubJwks:
        def get_signing_key_from_jwt(self, token):
            public_key = key.public_key()

            class StubKey:
                key = public_key

            return StubKey()

    monkeypatch.setattr(console_auth, "_jwks_client", lambda url: StubJwks())

    def make(claims: dict) -> str:
        base = {
            "iss": "https://auth.test.example/oidc",
            "aud": "client-lex",
            "sub": "user-1",
            "username": "lexdemocustomer",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "iat": datetime.now(timezone.utc),
        }
        base.update(claims)
        return pyjwt.encode(base, key, algorithm="ES384")

    user = console_auth.verify_id_token(make({"organizations": ["hnrbfpgq2717"]}))
    assert user.identity == "lexdemocustomer"
    assert user.organizations == ["hnrbfpgq2717"]

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as wrong_aud:
        console_auth.verify_id_token(make({"aud": "someone-else", "organizations": []}))
    assert wrong_aud.value.status_code == 401

    with pytest.raises(HTTPException) as wrong_org:
        console_auth.verify_id_token(make({"organizations": ["other-org"]}))
    assert wrong_org.value.status_code == 403
    reset_settings()


# ---------------------------------------------------------------------------
# 身份与客户解析
# ---------------------------------------------------------------------------


def test_me_resolves_customer_via_binding(console_env) -> None:
    client, _, _, engine = console_env
    seed_customer(engine)
    body = client.get("/api/console/me").json()
    assert body["identity"] == USER.identity
    assert body["customer"]["name"] == "识律演示客户"
    assert body["customer"]["plan_code"] == "standard"
    assert "8tajhoprelg0" in body["identities"]
    assert body["is_admin"] is False


def test_me_without_customer_is_honest_null(console_env) -> None:
    client, _, _, _ = console_env
    body = client.get("/api/console/me").json()
    assert body["customer"] is None
    assert body["identities"] == [USER.identity]


# ---------------------------------------------------------------------------
# 用量 / 账单 / 额度
# ---------------------------------------------------------------------------


def test_usage_aggregates_bound_identities_only(console_env) -> None:
    client, _, _, engine = console_env
    seed_customer(engine)
    body = client.get("/api/console/usage?period=2026-10").json()
    assert body["totals"]["calls"] == 2
    assert body["totals"]["by_unit"] == {"line": 42, "call": 1}
    assert body["customer"]["id"]
    # platform 轨道记录不进客户用量
    assert all(row["quantity"] != 999 for row in body["breakdown"])
    units = {(row["unit"], row["tool_name"]) for row in body["breakdown"]}
    assert ("line", "law_reference") in units
    assert body["recent"][0]["unit"] == "call"  # 新→旧


def test_usage_rejects_bad_period(console_env) -> None:
    client, _, _, _ = console_env
    assert client.get("/api/console/usage?period=2026-13").status_code == 422


def test_billing_returns_ledger_entries(console_env) -> None:
    client, _, _, engine = console_env
    customer_id = seed_customer(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        session.add(
            LedgerEntry(
                customer_id=customer_id,
                kind="overage",
                unit="line",
                quantity=10,
                amount_micro=40_000,
                period="2026-10",
                idempotency_key="settle:test:line",
                sub2api_applied=True,
            )
        )
        session.commit()
    body = client.get("/api/console/billing?period=2026-10").json()
    assert body["customer"]["id"] == customer_id
    assert body["entries"][0]["amount_yuan"] == "¥0.04"
    assert body["totals"]["amount_micro"] == 40_000


def test_billing_without_customer_is_null_state(console_env) -> None:
    client, _, _, _ = console_env
    body = client.get("/api/console/billing?period=2026-10").json()
    assert body["customer"] is None
    assert body["entries"] == []


def test_quota_uses_bound_identity_usage(console_env) -> None:
    client, _, _, engine = console_env
    seed_customer(engine)
    body = client.get("/api/console/quota?period=2026-10").json()
    units = {u["unit"]: u for u in body["status"]["units"]}
    assert units["line"]["used_quantity"] == 42
    assert units["line"]["included_quantity"] == 1000
    assert units["line"]["tiers_hit"] == []
    assert body["status"]["allowed"] is True
    assert body["recovery"] == []


def test_quota_reports_exhaustion_and_recovery(console_env) -> None:
    client, _, _, engine = console_env
    customer_id = seed_customer(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        # call 单位含额 100、超额单价 0；灌 100 次用量 → 硬停语义
        session.add(
            MeteringRecord(
                event_timestamp=datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc),
                request_id="req-console-4",
                caller=USER.identity,
                credential_track="customer",
                server_name="fd-legal-search-mcp",
                tool_name="contract_draft",
                quantity=100,
                unit="call",
                source="customer",
            )
        )
        session.commit()
    body = client.get("/api/console/quota?period=2026-10").json()
    assert body["status"]["allowed"] is False
    assert body["status"]["denial_reason"] == "quota_exhausted:call"
    assert "upgrade_quota" in body["recovery"]
    assert "contact_sales" in body["recovery"]


# ---------------------------------------------------------------------------
# 凭据代理
# ---------------------------------------------------------------------------


REGISTRY_HEADERS = {"X-Registry-Token": "access-token-abc"}


def test_credentials_list_proxies_registry(console_env) -> None:
    client, registry, _, _ = console_env
    resp = client.get("/api/console/credentials", headers=REGISTRY_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["items"][0]["key_prefix"] == "wgk-Abc123"
    assert registry.registry_token_seen == "access-token-abc"


def test_credentials_require_registry_token(console_env) -> None:
    client, _, _, _ = console_env
    assert client.get("/api/console/credentials").status_code == 401


def test_mint_credential_returns_plaintext_and_records_event(console_env) -> None:
    client, registry, _, engine = console_env
    resp = client.post(
        "/api/console/credentials", json={"name": "new-key"}, headers=REGISTRY_HEADERS
    )
    assert resp.status_code == 201
    assert resp.json()["key"] == "wgk-PlaintextOnce123"
    assert registry.calls[-1][0] == "POST"
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        events = session.execute(select(ConsoleCredentialEvent)).scalars().all()
    assert [(e.action, e.key_id, e.key_name) for e in events] == [
        ("mint", "key-2", "new-key")
    ]
    # 明文/哈希绝不落库
    assert "wgk-PlaintextOnce123" not in json.dumps([e.as_dict() for e in events])


def test_mint_credential_error_is_passed_through_and_recorded(console_env) -> None:
    client, registry, _, engine = console_env
    registry.mint_status = 429
    resp = client.post(
        "/api/console/credentials", json={"name": "too-many"}, headers=REGISTRY_HEADERS
    )
    assert resp.status_code == 429
    assert resp.json()["detail"] == "too many active keys"
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        event = session.execute(select(ConsoleCredentialEvent)).scalar_one()
    assert event.action == "mint"
    assert event.detail == "too many active keys"


def test_revoke_credential_records_event(console_env) -> None:
    client, _, _, engine = console_env
    resp = client.delete("/api/console/credentials/key-1", headers=REGISTRY_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"
    body = client.get("/api/console/credentials/events").json()
    assert body["events"][0]["action"] == "revoke"
    assert body["events"][0]["key_id"] == "key-1"


def test_revoke_unknown_key_404(console_env) -> None:
    client, _, _, _ = console_env
    resp = client.delete("/api/console/credentials/missing", headers=REGISTRY_HEADERS)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Key not found"


def test_registry_unreachable_maps_to_502(console_env) -> None:
    client, registry, _, _ = console_env

    def boom(token: str):
        from fd_lex_api.console_api.registry_client import RegistryUnavailable

        raise RegistryUnavailable("registry unreachable at https://mcp.test: timeout")

    registry.list_keys = boom
    resp = client.get("/api/console/credentials", headers=REGISTRY_HEADERS)
    assert resp.status_code == 502
    assert "unreachable" in resp.json()["detail"]
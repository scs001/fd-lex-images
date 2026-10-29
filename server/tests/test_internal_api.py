"""内部服务面（/internal/*）：bearer fail-closed 鉴权 + 计量摄取/查询 +
结算触发/对账/额度/套餐配置端点。

测试隔离策略：DATABASE_URL 指向临时文件库 + reset 运行时缓存；
sub2api 用 dependency_overrides 换假件（绝不真实调用）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from fd_lex_api.billing.deps import get_sub2api_client
from fd_lex_api.config import reset_settings
from fd_lex_api.main import app
from fd_lex_api.metering.db import (
    ensure_schema,
    get_engine,
    reset_metering_runtime,
)

from test_billing_common import FakeSub2Api
from fd_lex_api.billing import Base as BillingBase

TOKEN = "test-internal-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

SEARCH_EVENT = {
    "log_type": "mcp_server_access",
    "timestamp": "2026-09-15T10:00:00+00:00",
    "request_id": "req-api-1",
    "identity": {"username": "u-api"},
    "mcp_server": {"name": "legal-search-mcp"},
    "mcp_request": {"method": "tools/call", "tool_name": "case_search"},
    "mcp_response": {"status": "ok", "rows_returned": 1234},
}


@pytest.fixture()
def api_client(monkeypatch, tmp_path):
    """临时文件库 + 配置好令牌的 TestClient（sub2api 换假件）。"""
    db_path = tmp_path / "lex_api_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.delenv("PLATFORM_IDENTITIES", raising=False)
    reset_metering_runtime()

    engine = get_engine()
    BillingBase.metadata.create_all(engine)
    from fd_lex_api.console_api.models import ConsoleBase
    from fd_lex_api.metering.db import MeteringBase

    MeteringBase.metadata.create_all(engine)
    ConsoleBase.metadata.create_all(engine)  # 结算 resolver 绑定表优先需此表

    fake = FakeSub2Api()
    fake.add_user("u-api", balance_micro=10_000_000)
    app.dependency_overrides[get_sub2api_client] = lambda: fake.client()
    try:
        yield TestClient(app), fake, engine
    finally:
        app.dependency_overrides.pop(get_sub2api_client, None)
        reset_metering_runtime()
        reset_settings()


# ---------------------------------------------------------------------------
# 鉴权：fail-closed 骨架（接 Logto 后收敛）
# ---------------------------------------------------------------------------


def test_internal_requires_bearer_token(api_client) -> None:
    client, _, _ = api_client
    assert client.get("/internal/metering/usage").status_code == 401
    assert client.get("/internal/metering/usage",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_internal_fail_closed_when_token_unconfigured(api_client, monkeypatch) -> None:
    """未配置 INTERNAL_API_TOKEN：拒绝而不是无鉴权放行（fail-closed）。"""
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
    reset_settings()
    try:
        client, _, _ = api_client
        resp = client.get("/internal/metering/usage", headers=HEADERS)
        assert resp.status_code == 403
        assert "not configured" in resp.json()["detail"]
    finally:
        reset_settings()


# ---------------------------------------------------------------------------
# 计量面
# ---------------------------------------------------------------------------


def test_ingest_push_and_usage(api_client) -> None:
    client, _, _ = api_client
    resp = client.post("/internal/metering/events", json=[SEARCH_EVENT], headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 1

    resp = client.get(
        "/internal/metering/usage",
        params={"credential_track": "customer"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["calls"] == 1
    assert data["totals"]["by_unit"] == {"line": 1234}
    assert data["breakdown"][0]["unit"] == "line"

    # 重放同事件：幂等不双记
    resp = client.post("/internal/metering/events", json=[SEARCH_EVENT], headers=HEADERS)
    assert resp.json()["duplicates"] == 1


def test_ingest_rejects_bad_body(api_client) -> None:
    client, _, _ = api_client
    resp = client.post("/internal/metering/events", json={"no": "events"}, headers=HEADERS)
    assert resp.status_code == 422


def test_consume_endpoint_unconfigured_conflict(api_client) -> None:
    """Mongo 未配置 → 409（生产路径骨架的显式不可用）。"""
    client, _, _ = api_client
    resp = client.post("/internal/metering/consume", headers=HEADERS)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 结算面（套餐配置 → 开户 → 结算 → 对账 → 额度）
# ---------------------------------------------------------------------------


def _setup_plan_and_customer(client, fake) -> str:
    """建套餐+客户；返回客户身份键（=sub2api_user_id，metering caller 的映射键）。"""
    resp = client.put(
        "/internal/billing/plans/standard",
        headers=HEADERS,
        json={
            "name": "标准版",
            "monthly_price_micro": 1_990_000,
            "quotas": [
                {"unit": "line", "included_quantity": 1_000_000,
                 "overage_unit_price_micro": 4_000},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        "/internal/billing/customers",
        headers=HEADERS,
        json={"name": "客户API", "plan_code": "standard", "idempotency_key": "cust:api"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] is True
    sub2api_user_id = resp.json()["customer"]["sub2api_user_id"]
    fake.users[sub2api_user_id] = {"name": "客户API", "balance_micro": 10_000_000}
    return sub2api_user_id


def test_plan_upsert_customer_settle_ledger_flow(api_client) -> None:
    client, fake, engine = api_client
    user_ref = _setup_plan_and_customer(client, fake)

    # 计量落两笔（含超额）→ 结算（caller=客户身份键，结算 resolver 据此映射）
    with engine.begin() as conn:
        for i in range(2):
            conn.execute(
                text(
                    "INSERT INTO metering_records (event_timestamp, request_id, caller,"
                    " credential_track, server_name, quantity, unit, source) VALUES ("
                    "'2026-09-15 10:00:00+00:00', :rid, :caller, 'customer',"
                    " 'legal-search-mcp', 500_000, 'line', 'customer')"
                ),
                {"rid": f"req-flow-{i}", "caller": user_ref},
            )
    resp = client.post(
        "/internal/billing/settle/2026-09",
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["failures"] == 0
    result = report["results"][0]
    assert result["status"] == "settled"
    unit = {u["unit"]: u for u in result["units"]}["line"]
    assert unit["used_quantity"] == 1_000_000  # 恰好在含额内

    # 账本流水可查
    customer_id = result["customer_id"]
    resp = client.get(
        f"/internal/billing/customers/{customer_id}/ledger",
        params={"period": "2026-09"},
        headers=HEADERS,
    )
    kinds = {e["kind"] for e in resp.json()["entries"]}
    assert {"grant", "overage"} <= kinds or kinds == {"grant"}

    # 同周期重放结算：不双扣
    balance_before = sum(
        u["balance_micro"] for u in fake.users.values()
    )
    resp = client.post("/internal/billing/settle/2026-09", headers=HEADERS)
    assert resp.json()["results"][0]["status"] == "replayed"
    assert sum(u["balance_micro"] for u in fake.users.values()) == balance_before


def test_customer_funding_ledger_and_optional_sub2api(api_client) -> None:
    """入金登记（2026-10-06 首客演练补口）：留痕/调账/幂等三态。"""
    client, fake, engine = api_client
    user_ref = _setup_plan_and_customer(client, fake)
    balance_before = fake.users[user_ref]["balance_micro"]

    # ① 登记（款项已在支付侧生效）：账本记负、applied=True（对账可见）
    resp = client.post(
        "/internal/billing/customers/1/funding",
        headers=HEADERS,
        json={
            "amount_micro": 5_000_000,
            "period": "2026-09",
            "source_ref": "bank-202609-001",
            "apply_to_sub2api": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] is True
    assert body["entry"]["kind"] == "adjustment"
    assert body["entry"]["amount_micro"] == -5_000_000  # 成本符号：入金为负
    assert body["entry"]["sub2api_applied"] is True
    assert fake.users[user_ref]["balance_micro"] == balance_before

    # ② 幂等重放：同 source_ref 不双记
    again = client.post(
        "/internal/billing/customers/1/funding",
        headers=HEADERS,
        json={
            "amount_micro": 5_000_000,
            "period": "2026-09",
            "source_ref": "bank-202609-001",
            "apply_to_sub2api": False,
        },
    )
    assert again.json()["created"] is False

    # ③ 经 sub2api 入金：先调支付侧，成功才落账（applied=True）
    resp = client.post(
        "/internal/billing/customers/1/funding",
        headers=HEADERS,
        json={
            "amount_micro": 2_000_000,
            "period": "2026-09",
            "source_ref": "wire-202609-002",
            "apply_to_sub2api": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["entry"]["sub2api_applied"] is True
    assert fake.users[user_ref]["balance_micro"] == balance_before + 2_000_000

    # ④ 出账补记（负金额 → 账本记正）
    resp = client.post(
        "/internal/billing/customers/1/funding",
        headers=HEADERS,
        json={
            "amount_micro": -1_000_000,
            "period": "2026-09",
            "source_ref": "manual-charge-202609-003",
            "apply_to_sub2api": False,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["entry"]["amount_micro"] == 1_000_000

    # 账本流水含三笔 adjustment（入金记负、出账记正）
    entries = client.get(
        "/internal/billing/customers/1/ledger",
        params={"period": "2026-09"},
        headers=HEADERS,
    ).json()["entries"]
    adjusts = [e for e in entries if e["kind"] == "adjustment"]
    assert {e["amount_micro"] for e in adjusts} == {-5_000_000, -2_000_000, 1_000_000}


def test_quota_endpoint(api_client) -> None:
    client, fake, engine = api_client
    user_ref = _setup_plan_and_customer(client, fake)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO metering_records (event_timestamp, request_id, caller,"
                " credential_track, server_name, quantity, unit, source) VALUES ("
                "'2026-09-15 10:00:00+00:00', 'req-q-1', :caller, 'customer',"
                " 'legal-search-mcp', 950_000, 'line', 'customer')"
            ),
            {"caller": user_ref},
        )
        cid = conn.execute(
            text("SELECT id FROM billing_customers WHERE sub2api_user_id=:r"),
            {"r": user_ref},
        ).scalar_one()

    resp = client.get(
        f"/internal/billing/customers/{cid}/quota",
        params={"period": "2026-09"},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["allowed"] is True
    unit = {u["unit"]: u for u in data["units"]}["line"]
    assert unit["used_pct"] == 95
    assert unit["tiers_hit"] == [80, 95]
    assert data["balance"]["reachable"] is True


def test_reconcile_endpoint(api_client) -> None:
    client, fake, engine = api_client
    _setup_plan_and_customer(client, fake)
    resp = client.get(
        "/internal/billing/reconcile", params={"period": "2026-09"}, headers=HEADERS
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["checked"] >= 1
    assert data["errors"] == 0  # 假件可达

    # 破坏对账：侧路动账
    uid = next(iter(fake.users))
    fake.users[uid]["balance_micro"] -= 999
    resp = client.get(
        "/internal/billing/reconcile", params={"period": "2026-09"}, headers=HEADERS
    )
    assert resp.json()["balance_mismatches"] >= 1


def test_period_validation_422(api_client) -> None:
    client, _, _ = api_client
    assert client.post("/internal/billing/settle/2026-9", headers=HEADERS).status_code == 422
    assert client.get(
        "/internal/billing/reconcile", params={"period": "bad"}, headers=HEADERS
    ).status_code == 422

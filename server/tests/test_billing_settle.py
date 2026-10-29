"""结算执行器：幂等重放不双扣不双记 / 双单位各得正确计价 / 套餐配置驱动 /
失败自愈 / 未配单位不静默。

真实 metering_records 表（caller/event_timestamp/credential_track/quantity/unit）
按整月聚合域结算（batch_ref=None）；批次语义在协议层用 Static 验证。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from fd_lex_api.billing import (
    Customer,
    Ledger,
    LedgerEntry,
    MeteringUsage,
    NoticeRecord,
    SettlementService,
    SqlMeteringSource,
    StaticMeteringSource,
    yuan_to_micro,
)

from test_billing_common import (
    FakeSub2Api,
    add_customer,
    insert_metering,
    make_engine,
    make_plan,
)

PERIOD = "2026-09"
TS = "2026-09-15 10:00:00+00:00"  # 落在 2026-09 聚合域
OPENING = 10_000_000  # 预存 ¥10
SOURCE_REF = f"period:{PERIOD}"


def build_env(rows_by_unit: dict[str, dict[str, int]], *,
              plan_quotas: list[dict] | None = None,
              monthly_price_micro: int = 1_990_000,
              fake: FakeSub2Api | None = None,
              ts: str = TS):
    """rows_by_unit: {unit: {caller: 数量}} —— 客户凭据轨道的计量行。"""
    engine = make_engine()
    fake = fake or FakeSub2Api()
    session = Session(engine)
    plan = make_plan(
        session,
        code="standard",
        name="标准版",
        monthly_price_micro=monthly_price_micro,
        quotas=plan_quotas
        or [
            {"unit": "line", "included_quantity": 1_000_000,
             "overage_unit_price_micro": 4_000},   # ¥0.004/行
            {"unit": "call", "included_quantity": 500,
             "overage_unit_price_micro": 2_000_000},  # ¥2/次
        ],
    )
    session.commit()
    refs = {ref for per_unit in rows_by_unit.values() for ref in per_unit}
    for ref in sorted(refs):
        add_customer(session, name=f"客户-{ref}", plan_id=plan.id, sub2api_user_id=ref)
        fake.add_user(ref, name=ref, balance_micro=OPENING)
    session.commit()
    for unit, per_ref in rows_by_unit.items():
        for ref, qty in per_ref.items():
            insert_metering(engine, customer_ref=ref, ts=ts, quantity=qty, unit=unit)
    service = SettlementService(session, fake.client(), SqlMeteringSource(engine))
    return engine, session, fake, service


def customer_by_ref(session: Session, ref: str) -> Customer:
    return session.execute(
        select(Customer).where(Customer.sub2api_user_id == ref)
    ).scalar_one()


def ledger_count(session: Session) -> int:
    return len(list(session.execute(select(LedgerEntry)).scalars()))


# ---------------------------------------------------------------------------
# 幂等结算（验收核心）：同幂等键重放 → 余额只动一次
# ---------------------------------------------------------------------------


def test_replay_same_period_no_double_charge_no_double_entry() -> None:
    """同幂等键重放：sub2api 只调一次、余额只动一次、账本只记一条。"""
    engine, session, fake, service = build_env(
        {"line": {"u-a": 1_400_000}, "call": {"u-a": 700}}  # 双单位都超额
    )
    first = service.settle(PERIOD)
    assert first.results[0].status == "settled"
    overage_line = 400_000 * 4_000  # 400k 超额行 × ¥0.004
    overage_call = 200 * 2_000_000  # 200 超额次 × ¥2
    charged = overage_line + overage_call
    balance_after_first = fake.balance("u-a")
    assert balance_after_first == OPENING - charged
    assert len(fake.adjust_calls) == 2  # line+call 各一次 adjust
    entries_after = ledger_count(session)
    notices_after = len(list(session.execute(select(NoticeRecord)).scalars()))

    second = service.settle(PERIOD)  # 同聚合域重放（重试/重复提交）
    assert second.results[0].status == "replayed"
    assert fake.balance("u-a") == balance_after_first  # 不双扣
    assert len(fake.adjust_calls) == 2  # sub2api 零新增调用
    assert second.sub2api_call_count == 0
    assert ledger_count(session) == entries_after  # 账本零新增
    assert len(list(session.execute(select(NoticeRecord)).scalars())) == notices_after

    # 账本逐单位各一条 overage，幂等键即 settle 键
    ledger = Ledger(session)
    entries = ledger.entries(customer_by_ref(session, "u-a").id, PERIOD)
    overages = [e for e in entries if e.kind == "overage"]
    assert {(e.unit, e.quantity, e.amount_micro) for e in overages} == {
        ("line", 400_000, overage_line),
        ("call", 200, overage_call),
    }
    assert all(e.sub2api_applied for e in overages)


def test_sub2api_failure_then_retry_self_heals() -> None:
    """sub2api 不可达：不写账；恢复后同键重放净一次扣减。"""
    fake = FakeSub2Api()
    engine, session, fake, service = build_env(
        {"line": {"u-a": 1_100_000}}, fake=fake
    )
    fake.fail_adjust_left = 1  # 第一次 adjust 503 → 计费面不可用语义

    failed = service.settle(PERIOD)
    result = failed.results[0]
    assert result.status == "failed_sub2api"
    assert fake.balance("u-a") == OPENING  # 分文未扣
    ledger_after_fail = Ledger(session)
    fail_entries = ledger_after_fail.entries(customer_by_ref(session, "u-a").id, PERIOD)
    assert not [e for e in fail_entries if e.kind == "overage"]  # 账本未记超额

    retried = service.settle(PERIOD)
    assert retried.results[0].status in ("settled", "replayed")
    assert fake.balance("u-a") == OPENING - 100_000 * 4_000  # 净一次扣减
    ledger = Ledger(session)
    overages = [
        e for e in ledger.entries(customer_by_ref(session, "u-a").id, PERIOD)
        if e.kind == "overage"
    ]
    assert len(overages) == 1 and overages[0].sub2api_applied


def test_batch_ref_scopes_idempotency_key() -> None:
    """batch_ref 不同 → settle 键不同（增量批次可分别结算）。"""
    engine = make_engine()
    session = Session(engine)
    fake = FakeSub2Api()
    plan = make_plan(session, quotas=[{"unit": "line", "included_quantity": 0,
                                       "overage_unit_price_micro": 1_000}])
    add_customer(session, name="客", plan_id=plan.id, sub2api_user_id="u-x")
    session.commit()
    fake.add_user("u-x", balance_micro=OPENING)
    source = StaticMeteringSource([MeteringUsage("u-x", "line", 100)])
    service = SettlementService(session, fake.client(), source)

    service.settle(PERIOD, batch_ref="batch-1")
    service.settle(PERIOD, batch_ref="batch-2")  # 不同批次：各自入账
    assert fake.balance("u-x") == OPENING - 200 * 1_000
    service.settle(PERIOD, batch_ref="batch-2")  # 同批次重放：不动
    assert fake.balance("u-x") == OPENING - 200 * 1_000


# ---------------------------------------------------------------------------
# 双单位计价 + 套餐配置驱动
# ---------------------------------------------------------------------------


def test_dual_unit_pricing_line_and_call() -> None:
    """两类调用各按正确单位与单价结算（行/次互不串价）。"""
    engine, session, fake, service = build_env(
        {"line": {"u-a": 1_000_400}, "call": {"u-b": 501}}
    )
    report = service.settle(PERIOD)
    by_ref = {r.customer_ref: r for r in report.results}
    assert all(r.ok for r in report.results), [r.error for r in report.results]

    # u-a：行超额 400 × ¥0.004 = ¥1.6；无次数用量 → 无 call 单位条目
    unit_a = {u.unit: u for u in by_ref["u-a"].units}
    assert set(unit_a) == {"line"}
    assert unit_a["line"].overage_quantity == 400
    assert unit_a["line"].overage_amount_micro == yuan_to_micro("1.6")

    # u-b：次超额 1 × ¥2 = ¥2；无行用量 → 无 line 单位条目
    unit_b = {u.unit: u for u in by_ref["u-b"].units}
    assert set(unit_b) == {"call"}
    assert unit_b["call"].overage_quantity == 1
    assert unit_b["call"].overage_amount_micro == yuan_to_micro("2")

    assert fake.balance("u-a") == OPENING - yuan_to_micro("1.6")
    assert fake.balance("u-b") == OPENING - yuan_to_micro("2")


def test_plan_config_change_applies_without_release() -> None:
    """套餐后台可配：改超额单价后，新价对后续计量即时生效（无发版）。"""
    from fd_lex_api.billing import upsert_plan

    engine, session, fake, service = build_env({"line": {"u-a": 1_100_000}})
    first = service.settle(PERIOD)
    assert first.results[0].ok
    charged_first = 100_000 * 4_000  # ¥0.004/行
    assert fake.balance("u-a") == OPENING - charged_first

    # 运营调价：¥0.004 → ¥0.006（后台 PUT /plans 的服务层等价动作）
    plan = session.execute(
        select(Customer).where(Customer.sub2api_user_id == "u-a")
    ).scalar_one().plan
    upsert_plan(
        session, code=plan.code, name=plan.name,
        monthly_price_micro=plan.monthly_price_micro,
        quotas=[{"unit": "line", "included_quantity": 1_000_000,
                 "overage_unit_price_micro": 6_000}],
    )
    session.commit()

    # 新周期的新计量按新价结算
    insert_metering(engine, customer_ref="u-a", ts="2026-10-15 10:00:00+00:00",
                    quantity=1_050_000, unit="line")
    october = service.settle("2026-10")
    assert october.results[0].ok
    assert fake.balance("u-a") == OPENING - charged_first - 50_000 * 6_000


def test_monthly_grant_recorded_once_per_period() -> None:
    """月费 grant 每周期一条（幂等），金额=套餐月费；单位 grant 带含额数量。"""
    engine, session, fake, service = build_env({"line": {"u-a": 10}})
    service.settle(PERIOD)
    ledger = Ledger(session)
    entries = ledger.entries(customer_by_ref(session, "u-a").id, PERIOD)
    grants = [e for e in entries if e.kind == "grant"]
    money_grants = [e for e in grants if e.unit is None]
    assert len(money_grants) == 1
    assert money_grants[0].amount_micro == 1_990_000
    unit_grants = {(e.unit, e.quantity) for e in grants if e.unit is not None}
    assert ("line", 1_000_000) in unit_grants


# ---------------------------------------------------------------------------
# 未配单位 / 无绑定 / 无超额
# ---------------------------------------------------------------------------


def test_unit_without_quota_config_is_unbilled_not_crash() -> None:
    """套餐未配置的单位：不进账单不扣款，报告显式标 unbilled（不静默）。"""
    engine, session, fake, service = build_env(
        {"token": {"u-a": 18_000}},  # 套餐未配 token
        plan_quotas=[{"unit": "line", "included_quantity": 1_000_000,
                      "overage_unit_price_micro": 4_000}],
    )
    report = service.settle(PERIOD)
    result = report.results[0]
    assert result.ok and result.has_unbilled
    assert fake.balance("u-a") == OPENING  # 未扣款
    ledger = Ledger(session)
    entries = ledger.entries(customer_by_ref(session, "u-a").id, PERIOD)
    assert not [e for e in entries if e.kind == "overage"]


def test_token_unit_settles_after_config_with_no_migration() -> None:
    """token 计价上线：套餐补配 token 配额即可结算——计量记录结构零迁移。"""
    from fd_lex_api.billing import upsert_plan

    engine, session, fake, service = build_env(
        {"token": {"u-a": 118_000}},
        plan_quotas=[{"unit": "line", "included_quantity": 1_000_000,
                      "overage_unit_price_micro": 4_000}],
    )
    plan = session.execute(
        select(Customer).where(Customer.sub2api_user_id == "u-a")
    ).scalar_one().plan
    upsert_plan(  # 后台补配 token：18k 免费 + ¥0.01/千 token 超额
        session, code=plan.code, name=plan.name,
        monthly_price_micro=plan.monthly_price_micro,
        quotas=[
            {"unit": "line", "included_quantity": 1_000_000,
             "overage_unit_price_micro": 4_000},
            {"unit": "token", "included_quantity": 18_000,
             "overage_unit_price_micro": 10},
        ],
    )
    session.commit()
    report = service.settle(PERIOD)
    result = report.results[0]
    assert result.ok and not result.has_unbilled
    unit = {u.unit: u for u in result.units}["token"]
    assert unit.overage_quantity == 100_000
    assert unit.overage_amount_micro == 1_000_000  # ¥1
    assert fake.balance("u-a") == OPENING - 1_000_000


def test_within_quota_no_overage_no_sub2api_call() -> None:
    """额度内：零超额零扣款，但两档预警照常留档。"""
    engine, session, fake, service = build_env({"line": {"u-a": 1_000_000}})
    report = service.settle(PERIOD)
    result = report.results[0]
    assert result.ok
    assert fake.balance("u-a") == OPENING  # 分文未扣
    assert len(fake.adjust_calls) == 0
    unit = {u.unit: u for u in result.units}["line"]
    assert sorted(unit.notice_tiers_sent) == [80, 95]  # 100% 用量两档预警


def test_no_sub2api_binding_fails_without_ledger_write() -> None:
    """客户未绑定 sub2api：标 failed_no_sub2api_user，不写账。"""
    engine = make_engine()
    session = Session(engine)
    fake = FakeSub2Api()
    plan = make_plan(session, quotas=[{"unit": "line", "included_quantity": 0,
                                       "overage_unit_price_micro": 1_000}])
    customer = add_customer(session, name="无绑定客", plan_id=plan.id,
                            sub2api_user_id=None)
    session.commit()
    service = SettlementService(
        session, fake.client(), StaticMeteringSource([MeteringUsage("ghost", "line", 100)]),
        resolver=lambda ref: customer if ref == "ghost" else None,
    )
    report = service.settle(PERIOD)
    assert report.results[0].status == "failed_no_sub2api_user"
    entries = Ledger(session).entries(customer.id, PERIOD)
    assert not [e for e in entries if e.kind == "overage"]
    assert {e.kind for e in entries} == {"grant"}  # 仅 grant（月费+含额），无超额账


def test_inactive_customer_skipped() -> None:
    engine = make_engine()
    session = Session(engine)
    fake = FakeSub2Api()
    plan = make_plan(session, quotas=[{"unit": "line", "included_quantity": 0,
                                       "overage_unit_price_micro": 1_000}])
    add_customer(session, name="停用客", plan_id=plan.id,
                 sub2api_user_id="u-z", status="suspended")
    session.commit()
    fake.add_user("u-z", balance_micro=OPENING)
    service = SettlementService(
        session, fake.client(), StaticMeteringSource([MeteringUsage("u-z", "line", 100)])
    )
    report = service.settle(PERIOD)
    assert report.results[0].status == "skipped_inactive"
    assert fake.balance("u-z") == OPENING


def test_unknown_metering_source_fails_whole_batch() -> None:
    """计量源不可读：整批失败，不动任何账（fail-closed）。"""
    class BoomSource:
        def aggregates(self, period, batch_ref=None):
            raise RuntimeError("metering source down")

    engine, session, fake, service = build_env({"line": {"u-a": 10}})
    service._metering = BoomSource()
    report = service.settle(PERIOD)
    assert report.results[0].status == "failed_metering_source"
    assert ledger_count(session) == 0


def test_bindings_resolver_and_multi_identity_merge() -> None:
    """绑定表解析 + 多身份归并（2026-10-06 首客开户演练实测口径）：

    patch-key 的 Logto sub（8tajhoprelg0）与用户名（lexdemocustomer）两个
    计量 ref 归并为同一客户一次结算，含额按客户只算一次。
    """
    from fd_lex_api.console_api.models import ConsoleIdentityBinding

    engine = make_engine()
    session = Session(engine)
    fake = FakeSub2Api()
    plan = make_plan(
        session, code="std", name="标准版", monthly_price_micro=0,
        quotas=[{"unit": "call", "included_quantity": 1,
                 "overage_unit_price_micro": 10_000}],
    )
    session.commit()
    customer = add_customer(session, name="首客", plan_id=plan.id, sub2api_user_id="56")
    fake.add_user("56", balance_micro=OPENING)
    session.add(ConsoleIdentityBinding(customer_id=customer.id, identity="8tajhoprelg0"))
    session.add(
        ConsoleIdentityBinding(customer_id=customer.id, identity="lexdemocustomer")
    )
    session.commit()
    insert_metering(engine, customer_ref="8tajhoprelg0", ts=TS, quantity=1, unit="call")
    insert_metering(
        engine, customer_ref="lexdemocustomer", ts=TS, quantity=1, unit="call"
    )
    service = SettlementService(session, fake.client(), SqlMeteringSource(engine))
    report = service.settle(PERIOD)

    assert len(report.results) == 1  # 两身份归并为一次结算
    result = report.results[0]
    assert result.ok and result.customer_id == customer.id
    assert result.customer_ref == "8tajhoprelg0,lexdemocustomer"
    unit = result.units[0]
    # 合并用量 2 次 − 含额 1 次 → 超额 1 次 × ¥0.01
    assert (unit.used_quantity, unit.overage_quantity, unit.overage_amount_micro) == (
        2, 1, 10_000,
    )
    assert fake.balance("56") == OPENING - 10_000

    # 对账同口径：计量按身份集合匹配（含绑定身份），余额三方守恒（清账）
    from fd_lex_api.billing import reconcile

    report = reconcile(
        session, fake.client(), SqlMeteringSource(engine),
        period=PERIOD, opening_balances={customer.id: OPENING},
    )
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.is_clean, (row.difference_micro, row.units)


def test_pg_period_dialect_expression() -> None:
    """PG 方言：period 提取用 to_char + AT TIME ZONE 'UTC'（防会话时区月错位）。"""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy import create_engine

    from fd_lex_api.billing.metering_source import _period_expr

    pg_engine = create_engine("postgresql+psycopg://u:p@localhost/db")
    sql = str(
        _period_expr(pg_engine).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "to_char" in sql
    assert "timezone" in sql.lower()
    assert "YYYY-MM" in sql

    sqlite_engine = create_engine("sqlite://")
    sqlite_sql = str(
        _period_expr(sqlite_engine).compile(compile_kwargs={"literal_binds": True})
    )
    assert "strftime" in sqlite_sql

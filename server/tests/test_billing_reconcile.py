"""三方对账：账本（权威）× 计量流 × sub2api 余额 快照核对，差异不静默。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from fd_lex_api.billing import (
    Customer,
    SqlMeteringSource,
    SettlementService,
    reconcile,
)

from test_billing_common import (
    FakeSub2Api,
    add_customer,
    insert_metering,
    make_engine,
    make_plan,
)

PERIOD = "2026-09"
TS = "2026-09-15 10:00:00+00:00"
OPENING = 50_000_000  # 客户预存 ¥50（期初余额）


def build_two_customers():
    """标准环境：两客户（A 双单位超额、B 额度内），先结算再对账。"""
    engine = make_engine()
    session = Session(engine)
    fake = FakeSub2Api()
    plan = make_plan(
        session,
        code="standard",
        monthly_price_micro=1_990_000,
        quotas=[
            {"unit": "line", "included_quantity": 1_000_000,
             "overage_unit_price_micro": 4_000},
            {"unit": "call", "included_quantity": 500,
             "overage_unit_price_micro": 2_000_000},
        ],
    )
    add_customer(session, name="客户A", plan_id=plan.id, sub2api_user_id="u-a")
    add_customer(session, name="客户B", plan_id=plan.id, sub2api_user_id="u-b")
    for ref in ("u-a", "u-b"):
        fake.add_user(ref, name=ref, balance_micro=OPENING)
    session.commit()
    insert_metering(engine, customer_ref="u-a", ts=TS, quantity=1_400_000, unit="line")
    insert_metering(engine, customer_ref="u-a", ts=TS, quantity=700, unit="call",
                    request_id="req-a-call")
    insert_metering(engine, customer_ref="u-b", ts=TS, quantity=100, unit="line",
                    request_id="req-b-line")

    service = SettlementService(session, fake.client(), SqlMeteringSource(engine))
    report = service.settle(PERIOD)
    assert all(r.ok for r in report.results), [r.error for r in report.results]
    ids = {
        c.sub2api_user_id: c.id
        for c in session.execute(select(Customer)).scalars()
    }
    return engine, session, fake, ids


def test_three_way_reconcile_consistent() -> None:
    """对账一致：账本、支付侧余额、计量流三方口径一致（全绿）。"""
    engine, session, fake, ids = build_two_customers()
    report = reconcile(
        session, fake.client(), SqlMeteringSource(engine), period=PERIOD,
        opening_balances={ids["u-a"]: OPENING, ids["u-b"]: OPENING},
    )
    assert report.checked == 2
    assert report.errors == []
    assert report.mismatches == []
    assert report.metering_mismatches == []
    assert report.matched == 2

    row_a = next(r for r in report.rows if r.sub2api_user_id == "u-a")
    applied_a = 400_000 * 4_000 + 200 * 2_000_000  # grant 不 applied，仅超额扣减
    assert row_a.ledger_applied_micro == applied_a
    assert row_a.expected_micro == OPENING - applied_a
    assert row_a.snapshot_micro == fake.balance("u-a") == OPENING - applied_a
    assert row_a.difference_micro == 0
    # 逐单位 covered == metered（A：line/call 全结清）
    assert all(u.difference == 0 for u in row_a.units)


def test_metering_stream_mismatch_unbilled_flagged() -> None:
    """计量流侧差异：漏结（计量>账本）不被静默——对账报告必须指认。"""
    engine, session, fake, ids = build_two_customers()
    # 结算后计量流又进来一批未结算用量（漏结形态）
    insert_metering(engine, customer_ref="u-a", ts=TS, quantity=5_000, unit="line",
                    request_id="req-late")
    report = reconcile(
        session, fake.client(), SqlMeteringSource(engine), period=PERIOD,
        opening_balances={ids["u-a"]: OPENING, ids["u-b"]: OPENING},
    )
    assert len(report.metering_mismatches) == 1
    row = report.metering_mismatches[0]
    unit = {u.unit: u for u in row.units}["line"]
    assert unit.metered_quantity == 1_405_000
    assert unit.included_quantity == 1_000_000
    assert unit.expected_overage_quantity == 405_000
    assert unit.settled_overage_quantity == 400_000
    assert unit.difference == 5_000  # 正差=漏结
    assert not row.is_mismatch  # 余额侧仍对齐（漏结≠余额错）


def test_overbilled_metering_mismatch_flagged() -> None:
    """计量流侧差异：多结（账本>计量）同样指认（如计量记录被撤）。"""
    engine, session, fake, ids = build_two_customers()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "DELETE FROM metering_records WHERE caller='u-a' AND unit='call'"
        )
    report = reconcile(
        session, fake.client(), SqlMeteringSource(engine), period=PERIOD,
        opening_balances={ids["u-a"]: OPENING, ids["u-b"]: OPENING},
    )
    row = next(r for r in report.rows if r.sub2api_user_id == "u-a")
    unit = {u.unit: u for u in row.units}["call"]
    assert unit.metered_quantity == 0
    assert unit.settled_overage_quantity == 200
    assert unit.expected_overage_quantity == 0
    assert unit.difference == -200  # 负差=多结
    assert row in report.metering_mismatches


def test_balance_drift_mismatch_flagged() -> None:
    """余额侧差异：sub2api 侧被人手工动账 → expected vs snapshot 差异条目。"""
    engine, session, fake, ids = build_two_customers()
    fake.users["u-a"]["balance_micro"] += -1_234  # 侧路动账（未走账本）
    report = reconcile(
        session, fake.client(), SqlMeteringSource(engine), period=PERIOD,
        opening_balances={ids["u-a"]: OPENING, ids["u-b"]: OPENING},
    )
    assert len(report.mismatches) == 1
    assert report.mismatches[0].sub2api_user_id == "u-a"
    assert report.mismatches[0].difference_micro == -1_234


def test_sub2api_unreachable_reports_error_not_guess() -> None:
    """sub2api 不可达：不猜快照（difference=None），错误行显式呈现；
    计量流侧核对照常完成（三方少一方也出两方结论）。"""
    engine, session, fake, ids = build_two_customers()
    fake.fail_reads_left = 2
    report = reconcile(
        session, fake.client(), SqlMeteringSource(engine), period=PERIOD,
        opening_balances={ids["u-a"]: OPENING, ids["u-b"]: OPENING},
    )
    assert len(report.errors) == 2
    for row in report.errors:
        assert row.reachable is False
        assert row.difference_micro is None
    # 计量流侧仍有结论：u-b 额度内，covered==metered，无计量差异
    row_b = next(r for r in report.rows if r.sub2api_user_id == "u-b")
    assert row_b.units and not row_b.unit_mismatches


def test_reconcile_customer_ids_filter() -> None:
    engine, session, fake, ids = build_two_customers()
    report = reconcile(
        session, fake.client(), SqlMeteringSource(engine),
        period=PERIOD, customer_ids=[ids["u-a"]],
        opening_balances={ids["u-a"]: OPENING},
    )
    assert report.checked == 1
    assert report.rows[0].sub2api_user_id == "u-a"

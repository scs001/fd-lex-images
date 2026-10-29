"""额度状态查询与 fail-closed 预检：额度水位 / 两档阈值 / 硬停判定 /
计费面不可达宁可错拒（地基——402 执行在 registry 侧，通知投递在通知通道）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from fd_lex_api.billing import (
    MeteringUsage,
    StaticMeteringSource,
    quota_status,
    yuan_to_micro,
)

from test_billing_common import (
    FakeSub2Api,
    add_customer,
    make_engine,
    make_plan,
)

PERIOD = "2026-09"


def build_env(*, overage_line_price: int = 4_000, overage_call_price: int = 0):
    """套餐：line 含额 1000、超额 ¥0.004/行；call 含额 500、超额默认不计价。"""
    engine = make_engine()
    session = Session(engine)
    fake = FakeSub2Api()
    plan = make_plan(
        session,
        code="standard",
        monthly_price_micro=yuan_to_micro("199"),
        quotas=[
            {"unit": "line", "included_quantity": 1_000,
             "overage_unit_price_micro": overage_line_price},
            {"unit": "call", "included_quantity": 500,
             "overage_unit_price_micro": overage_call_price},
        ],
    )
    customer = add_customer(session, name="客户A", plan_id=plan.id,
                            sub2api_user_id="u-a")
    session.commit()
    fake.add_user("u-a", balance_micro=yuan_to_micro("10"))
    return engine, session, fake, customer


def _status(session, fake, customer, used: dict, **kw):
    return quota_status(
        session, customer, PERIOD,
        metering=StaticMeteringSource([]),
        sub2api=fake.client() if kw.pop("with_sub2api", True) else None,
        usage_override=used,
        **kw,
    )


def test_within_quota_allowed() -> None:
    engine, session, fake, customer = build_env()
    status = _status(session, fake, customer, {"line": 700, "call": 100})
    assert status.allowed and status.denial_reason is None
    unit = {u.unit: u for u in status.units}
    assert unit["line"].remaining_quantity == 300
    assert unit["line"].used_pct == 70
    assert unit["line"].tiers_hit == []
    assert unit["call"].used_pct == 20
    assert status.balance is not None and status.balance.sufficient


def test_two_tier_thresholds_80_and_95() -> None:
    """用量先后到 80% 与 95%：tiers_hit 分别只报对应档（预警留档另测）。"""
    engine, session, fake, customer = build_env()
    at80 = _status(session, fake, customer, {"line": 800})
    assert {u.unit: u for u in at80.units}["line"].tiers_hit == [80]

    at95 = _status(session, fake, customer, {"line": 950})
    assert {u.unit: u for u in at95.units}["line"].tiers_hit == [80, 95]


def test_exhausted_without_overage_price_hardstops() -> None:
    """额度耗尽且超额不计价 → 硬停（allowed=False，语义原因如实）。"""
    engine, session, fake, customer = build_env(overage_call_price=0)
    status = _status(session, fake, customer, {"call": 500})
    assert not status.allowed
    assert status.denial_reason == "quota_exhausted:call"
    unit = {u.unit: u for u in status.units}["call"]
    assert unit.exhausted


def test_exhausted_with_overage_price_continues_via_balance() -> None:
    """额度耗尽但超额有价 → 不硬停，继续用量由 sub2api 余额背书。"""
    engine, session, fake, customer = build_env(overage_call_price=2_000_000)
    status = _status(session, fake, customer, {"call": 500})
    assert status.allowed
    unit = {u.unit: u for u in status.units}["call"]
    assert unit.used_quantity >= unit.included_quantity
    assert not unit.exhausted and unit.overage_priced


def test_billing_plane_unreachable_fail_closed() -> None:
    """计费面不可达 → 预检不通过（fail-closed，宁可错拒不放行追缴）。"""
    engine, session, fake, customer = build_env()
    client = fake.client()
    fake.fail_reads_left = 1
    status = quota_status(
        session, customer, PERIOD,
        metering=StaticMeteringSource([]), sub2api=client,
        usage_override={"line": 10},
    )
    assert not status.allowed
    assert status.denial_reason == "billing_plane_unreachable"
    assert status.balance.reachable is False


def test_insufficient_balance_denied() -> None:
    engine, session, fake, customer = build_env()
    fake.users["u-a"]["balance_micro"] = 0
    status = quota_status(
        session, customer, PERIOD,
        metering=StaticMeteringSource([]), sub2api=fake.client(),
        min_balance_micro=1,
        usage_override={"line": 10},
    )
    assert not status.allowed
    assert status.denial_reason == "insufficient_balance"


def test_zero_balance_denied_with_default_floor() -> None:
    """零余额 → 默认口径即拒绝：与 registry 预检 balance<=0 → 402 一致
    （2026-10-06 首客开户演练：不传 min 时曾得 sufficient=true 的假阴）。"""
    engine, session, fake, customer = build_env()
    fake.users["u-a"]["balance_micro"] = 0
    status = _status(session, fake, customer, {"line": 10})  # 不传 min_balance_micro
    assert not status.allowed
    assert status.denial_reason == "insufficient_balance"
    assert status.balance is not None and status.balance.sufficient is False


def test_usage_on_unconfigured_unit_visible_but_not_blocking() -> None:
    """有用量但套餐未配置的单位：状态可见（configured=False），不阻断。"""
    engine, session, fake, customer = build_env()
    status = _status(session, fake, customer, {"line": 10, "token": 5_000})
    token = {u.unit: u for u in status.units}["token"]
    assert token.configured is False
    assert token.used_quantity == 5_000
    assert status.allowed


def test_notice_records_written_once_per_tier_and_unit() -> None:
    """预警留档：同客户同周期同单位同档位只发一次；行/次互不抑制。"""
    from fd_lex_api.billing import evaluate_usage_warnings

    engine, session, fake, customer = build_env()
    first = evaluate_usage_warnings(
        session, customer=customer, period=PERIOD, unit="line",
        used_quantity=950, included_quantity=1_000,
    )
    assert sorted(n.threshold_pct for n in first) == [80, 95]
    replay = evaluate_usage_warnings(
        session, customer=customer, period=PERIOD, unit="line",
        used_quantity=990, included_quantity=1_000,
    )
    assert replay == []  # 两档都已发过

    calls = evaluate_usage_warnings(
        session, customer=customer, period=PERIOD, unit="call",
        used_quantity=500, included_quantity=500,
    )
    assert sorted(n.threshold_pct for n in calls) == [80, 95]  # 次数额度独立判定
